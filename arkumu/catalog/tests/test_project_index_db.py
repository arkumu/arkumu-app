import uuid

from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from arkumu.catalog.models import ProjectDetailIndex, ProjectIndex, ProjectRecordIndex
from arkumu.catalog.services import ProjectIndexService
from arkumu.catalog.services.project_index_db_service import ProjectIndexDbService
from arkumu.metadata.models import PublicAccessLevel, Resource, ResourceType
from arkumu.projects import (
    ProjectActor,
    ProjectCategory,
    ProjectDigitalObject,
    ProjectInstitution,
    ProjectRecord,
)
from arkumu.users.tests.factories import OrganizationFactory


def _record_for(resource: Resource, *, title: str, subtitle: str = "") -> ProjectRecord:
    return ProjectRecord(
        subject_id=str(resource.id),
        uri=resource.uri,
        title=title,
        subtitle=subtitle,
        description="A test project",
        institution=ProjectInstitution(label=resource.organization.name if resource.organization else None),
        categories=[ProjectCategory(label="Category A", slug="category-a")],
        actors=[ProjectActor(name="Actor One", roles=["role"])],
        digital_objects=[ProjectDigitalObject(path="/files/object.mp4")],
        year_range="2024",
        institution_codes=[resource.organization.code] if resource.organization else [],
        category_slugs=["category-a"],
    )


def test_service_writes_public_rows_and_filters_private(db):
    org = OrganizationFactory(code="abc")
    public_res = Resource.objects.create(
        id=uuid.uuid4(),
        uri="http://example.org/project/public",
        resource_type=ResourceType.ENTITY,
        organization=org,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )
    private_res = Resource.objects.create(
        id=uuid.uuid4(),
        uri="http://example.org/project/private",
        resource_type=ResourceType.ENTITY,
        organization=org,
        public_access_level=PublicAccessLevel.PRIVATE,
        is_public_approved=False,
    )

    public_record = _record_for(public_res, title="Public Project")
    private_record = _record_for(private_res, title="Private Project")

    service = ProjectIndexDbService(now=timezone.now())
    result = service._write_indexes(
        [public_record, private_record],
        {public_res.id: public_res, private_res.id: private_res},
        "v1",
        prune_missing=True,
    )

    assert result["project_index"] == 2

    stored_public = ProjectIndex.objects.get(project_resource=public_res)
    assert stored_public.uri == public_res.uri
    assert stored_public.to_record().title == "Public Project"

    # Only approved public rows should be served by the DB-backed index service.
    index_service = ProjectIndexService(backend="db")
    cards = index_service.get_cards()
    assert [card["uri"] for card in cards] == [public_res.uri]


def test_project_view_prefers_db_backend(client, user, settings, db):
    settings.PROJECT_INDEX_BACKEND = "db"

    org = OrganizationFactory(code="vieworg")
    resource = Resource.objects.create(
        id=uuid.uuid4(),
        uri="http://example.org/project/view",
        resource_type=ResourceType.ENTITY,
        organization=org,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )
    record = _record_for(resource, title="View Project")

    ProjectIndexDbService(now=timezone.now())._write_indexes(
        [record],
        {resource.id: resource},
        "v-test",
        prune_missing=True,
    )

    client.force_login(user)
    response = client.get(reverse("catalog:projekt"), {"projekt": resource.uri})

    assert response.status_code == 200
    assert b"View Project" in response.content


def test_rebuild_project_index_command(monkeypatch, capsys):
    calls = []

    def fake_rebuild(self, project_uris=None, force_snapshot=False):
        calls.append({"uris": project_uris, "force": force_snapshot})
        return {"project_index": 3}

    monkeypatch.setattr(ProjectIndexDbService, "rebuild", fake_rebuild)

    call_command(
        "rebuild_project_index",
        "--project-uri",
        "http://example.org/project/command",
        "--force-snapshot",
    )

    assert calls == [{"uris": ["http://example.org/project/command"], "force": True}]
    output = capsys.readouterr().out
    assert "index=3" in output


def test_bulk_write_updates_and_preserves_existing_rows(db):
    org = OrganizationFactory(code="sync")
    res_a = Resource.objects.create(
        id=uuid.uuid4(),
        uri="http://example.org/project/a",
        resource_type=ResourceType.ENTITY,
        organization=org,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )
    res_b = Resource.objects.create(
        id=uuid.uuid4(),
        uri="http://example.org/project/b",
        resource_type=ResourceType.ENTITY,
        organization=org,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )

    record_a_v1 = _record_for(res_a, title="Title A v1")
    record_b = _record_for(res_b, title="Title B")

    now_v1 = timezone.now()
    service_v1 = ProjectIndexDbService(now=now_v1)
    service_v1._write_indexes(
        [record_a_v1, record_b],
        {res_a.id: res_a, res_b.id: res_b},
        "v1",
        prune_missing=True,
    )

    assert ProjectIndex.objects.count() == 2
    assert ProjectRecordIndex.objects.count() == 2

    rec_a_row_v1 = ProjectRecordIndex.objects.get(project_resource=res_a)
    assert rec_a_row_v1.title == "Title A v1"
    assert rec_a_row_v1.built_at == now_v1

    # Incremental update for A only: title changes, B must remain.
    record_a_v2 = _record_for(res_a, title="Title A v2")
    now_v2 = now_v1 + timezone.timedelta(minutes=5)
    service_v2 = ProjectIndexDbService(now=now_v2)
    service_v2._write_indexes(
        [record_a_v2],
        {res_a.id: res_a},
        "v2",
        prune_missing=False,
    )

    assert ProjectIndex.objects.count() == 2
    assert ProjectRecordIndex.objects.count() == 2

    rec_a_row_v2 = ProjectRecordIndex.objects.get(project_resource=res_a)
    rec_b_row = ProjectRecordIndex.objects.get(project_resource=res_b)

    assert rec_a_row_v2.title == "Title A v2"
    assert rec_a_row_v2.built_at == now_v2
    assert rec_b_row.title == "Title B"


def test_rebuild_from_graph_writes_project_index(db, monkeypatch):
    """Test rebuild_from_graph() transforms canonical graph data into ProjectIndex rows."""
    from arkumu.catalog.services.project_index_db_service import _CanonicalURIs
    from arkumu.metadata.services import canonical_graph_service

    org = OrganizationFactory(code="graphorg")
    project_id = uuid.uuid4()
    event_id = uuid.uuid4()
    inst_id = uuid.uuid4()
    cat_id = uuid.uuid4()

    resource = Resource.objects.create(
        id=project_id,
        uri="http://example.org/project/graph-test",
        resource_type=ResourceType.ENTITY,
        organization=org,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )

    # Mock graph data structure
    mock_graph = {
        "subjects": [str(project_id)],
        "nodes": {
            str(project_id): {"uri": resource.uri, "name": "Graph Test Project"},
            str(event_id): {"uri": "http://example.org/event/1"},
            str(inst_id): {"uri": "http://example.org/inst/1", "name": "Test Institution"},
            str(cat_id): {"uri": "http://example.org/cat/1", "name": "Test Category"},
        },
        "edges": [
            # Project title
            {
                "subject_id": str(project_id),
                "predicate_canonical": _CanonicalURIs.TITLE,
                "object_value": "Graph Test Title",
            },
            # Project subtitle
            {
                "subject_id": str(project_id),
                "predicate_canonical": _CanonicalURIs.SUBTITLE,
                "object_value": "Graph Test Subtitle",
            },
            # Project -> Institution
            {
                "subject_id": str(project_id),
                "predicate_canonical": _CanonicalURIs.INSTITUTION,
                "object_id": str(inst_id),
            },
            # Institution name
            {
                "subject_id": str(inst_id),
                "predicate_canonical": _CanonicalURIs.INSTITUTION_NAME,
                "object_value": "Mock Institution",
            },
            # Project -> Category
            {
                "subject_id": str(project_id),
                "predicate_canonical": _CanonicalURIs.CATEGORY,
                "object_id": str(cat_id),
            },
            # Category name
            {
                "subject_id": str(cat_id),
                "predicate_canonical": _CanonicalURIs.CATEGORY_NAME,
                "object_value": "Mock Category",
            },
            # Project -> Event
            {
                "subject_id": str(project_id),
                "predicate_canonical": _CanonicalURIs.EVENT,
                "object_id": str(event_id),
            },
            # Event dates
            {
                "subject_id": str(event_id),
                "predicate_canonical": _CanonicalURIs.EVENT_START,
                "object_value": "2020-01-01",
            },
            {
                "subject_id": str(event_id),
                "predicate_canonical": _CanonicalURIs.EVENT_END,
                "object_value": "2023-12-31",
            },
        ],
    }

    # Patch CanonicalGraphService.get_project_graph to return mock data
    class MockGraphService:
        def __init__(self, org_code=None):
            pass

        def get_project_graph(self, **kwargs):
            return mock_graph

        def _fetch_triples_for_subjects(self, subject_ids, predicate_whitelist=None):
            return []

    monkeypatch.setattr(
        canonical_graph_service,
        "CanonicalGraphService",
        MockGraphService,
    )

    service = ProjectIndexDbService(now=timezone.now())
    result = service.rebuild_from_graph()

    assert result["project_index"] == 1

    index_row = ProjectIndex.objects.get(project_resource=resource)
    assert index_row.title == "Graph Test Title"
    assert index_row.subtitle == "Graph Test Subtitle"
    assert index_row.institution_label == "Mock Institution"
    assert index_row.category_labels == ["Mock Category"]
    assert index_row.year_range == "2020 bis 2023"
    assert index_row.org_code == "graphorg"


def test_rebuild_from_graph_command(monkeypatch, capsys):
    """Test management command with --backend=graph."""
    calls = []

    def fake_rebuild_from_graph(self, project_uris=None):
        calls.append({"uris": project_uris})
        return {"project_index": 5}

    monkeypatch.setattr(ProjectIndexDbService, "rebuild_from_graph", fake_rebuild_from_graph)

    call_command("rebuild_project_index", "--backend", "graph")

    assert len(calls) == 1
    assert calls[0]["uris"] is None
    output = capsys.readouterr().out
    assert "graph" in output
    assert "index=5" in output


def test_rebuild_from_graph_writes_project_record_index(db, monkeypatch):
    """Test rebuild_from_graph() also populates ProjectRecordIndex with record_jsonb."""
    from arkumu.catalog.services.project_index_db_service import _CanonicalURIs
    from arkumu.metadata.services import canonical_graph_service

    org = OrganizationFactory(code="recorg")
    project_id = uuid.uuid4()
    inst_id = uuid.uuid4()

    resource = Resource.objects.create(
        id=project_id,
        uri="http://example.org/project/record-index-test",
        resource_type=ResourceType.ENTITY,
        organization=org,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )

    mock_graph = {
        "subjects": [str(project_id)],
        "nodes": {
            str(project_id): {"uri": resource.uri},
            str(inst_id): {"uri": "http://example.org/inst/1"},
        },
        "edges": [
            {
                "subject_id": str(project_id),
                "predicate_canonical": _CanonicalURIs.TITLE,
                "object_value": "Record Index Test",
            },
            {
                "subject_id": str(project_id),
                "predicate_canonical": _CanonicalURIs.DESCRIPTION,
                "object_value": "A test description",
            },
            {
                "subject_id": str(project_id),
                "predicate_canonical": _CanonicalURIs.INSTITUTION,
                "object_id": str(inst_id),
            },
            {
                "subject_id": str(inst_id),
                "predicate_canonical": _CanonicalURIs.INSTITUTION_NAME,
                "object_value": "Record Inst",
            },
        ],
    }

    class MockGraphService:
        def __init__(self, org_code=None):
            pass

        def get_project_graph(self, **kwargs):
            return mock_graph

        def _fetch_triples_for_subjects(self, subject_ids, predicate_whitelist=None):
            return []

    monkeypatch.setattr(
        canonical_graph_service,
        "CanonicalGraphService",
        MockGraphService,
    )

    service = ProjectIndexDbService(now=timezone.now())
    result = service.rebuild_from_graph()

    assert result["project_index"] == 1

    record_row = ProjectIndex.objects.get(project_resource=resource)
    assert record_row.title == "Record Index Test"
    assert record_row.description == "A test description"
    assert record_row.institution_label == "Record Inst"
    assert record_row.record_jsonb["title"] == "Record Index Test"
    assert record_row.record_jsonb["description"] == "A test description"


def test_rebuild_from_graph_writes_project_detail_index(db, monkeypatch):
    """Test rebuild_from_graph() also populates ProjectDetailIndex with structured data."""
    from arkumu.catalog.services.project_index_db_service import _CanonicalURIs
    from arkumu.metadata.services import canonical_graph_service

    org = OrganizationFactory(code="detailorg")
    project_id = uuid.uuid4()
    event_id = uuid.uuid4()
    actor_junction_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    rolle_id = uuid.uuid4()  # Rolle entity for two-step role lookup
    cat_id = uuid.uuid4()

    resource = Resource.objects.create(
        id=project_id,
        uri="http://example.org/project/detail-index-test",
        resource_type=ResourceType.ENTITY,
        organization=org,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )

    mock_graph = {
        "subjects": [str(project_id)],
        "nodes": {
            str(project_id): {"uri": resource.uri},
            str(event_id): {"uri": "http://example.org/event/1"},
            str(actor_junction_id): {"uri": "http://example.org/junction/1"},
            str(actor_id): {"uri": "http://example.org/actor/1"},
            str(rolle_id): {"uri": "http://example.org/rolle/1"},
            str(cat_id): {"uri": "http://example.org/cat/musik"},
        },
        "edges": [
            {
                "subject_id": str(project_id),
                "predicate_canonical": _CanonicalURIs.TITLE,
                "object_value": "Detail Index Test",
            },
            {
                "subject_id": str(project_id),
                "predicate_canonical": _CanonicalURIs.EVENT,
                "object_id": str(event_id),
            },
            {
                "subject_id": str(event_id),
                "predicate_canonical": _CanonicalURIs.EVENT_NAME,
                "object_value": "Concert Event",
            },
            {
                "subject_id": str(event_id),
                "predicate_canonical": _CanonicalURIs.EVENT_START,
                "object_value": "2024-01-15",
            },
            {
                "subject_id": str(event_id),
                "predicate_canonical": _CanonicalURIs.EVENT_ACTOR_JUNCTION,
                "object_id": str(actor_junction_id),
            },
            {
                "subject_id": str(actor_junction_id),
                "predicate_canonical": _CanonicalURIs.ACTOR_LINK,
                "object_id": str(actor_id),
            },
            # ACTOR_ROLE now links to a rolle entity (not a literal)
            {
                "subject_id": str(actor_junction_id),
                "predicate_canonical": _CanonicalURIs.ACTOR_ROLE,
                "object_id": str(rolle_id),
            },
            # Rolle entity has the actual role name via ROLE_GERMAN_NAME
            {
                "subject_id": str(rolle_id),
                "predicate_canonical": _CanonicalURIs.ROLE_GERMAN_NAME,
                "object_value": "Performer",
            },
            {
                "subject_id": str(actor_id),
                "predicate_canonical": _CanonicalURIs.ACTOR_NAME,
                "object_value": "Max Mustermann",
            },
            {
                "subject_id": str(project_id),
                "predicate_canonical": _CanonicalURIs.CATEGORY,
                "object_id": str(cat_id),
            },
            {
                "subject_id": str(cat_id),
                "predicate_canonical": _CanonicalURIs.CATEGORY_NAME,
                "object_value": "Music",
            },
        ],
    }

    class MockGraphService:
        def __init__(self, org_code=None):
            pass

        def get_project_graph(self, **kwargs):
            return mock_graph

        def _fetch_triples_for_subjects(self, subject_ids, predicate_whitelist=None):
            # Return empty for second-level actor expansion
            return []

    monkeypatch.setattr(
        canonical_graph_service,
        "CanonicalGraphService",
        MockGraphService,
    )

    service = ProjectIndexDbService(now=timezone.now())
    result = service.rebuild_from_graph()

    assert result["project_index"] == 1

    detail_row = ProjectIndex.objects.get(project_resource=resource)
    assert detail_row.title == "Detail Index Test"
    assert len(detail_row.events) == 1
    assert detail_row.events[0]["name"] == "Concert Event"
    assert detail_row.events[0]["start"] == "2024-01-15"
    assert len(detail_row.actors) == 1
    assert detail_row.actors[0]["name"] == "Max Mustermann"
    assert detail_row.actors[0]["roles"] == ["Performer"]
    assert len(detail_row.categories) == 1
    assert detail_row.categories[0]["label"] == "Music"


def test_project_detail_index_to_view_context(db):
    """Test ProjectDetailIndex.to_view_context() builds correct dict."""
    org = OrganizationFactory(code="ctxorg")
    resource = Resource.objects.create(
        id=uuid.uuid4(),
        uri="http://example.org/project/ctx-test",
        resource_type=ResourceType.ENTITY,
        organization=org,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )

    detail = ProjectDetailIndex.objects.create(
        project_resource=resource,
        uri=resource.uri,
        org_code="ctxorg",
        title="Context Test",
        subtitle="A subtitle",
        description="Description text",
        institution_label="Test Institution",
        project_type_label="Research",
        year_range="2024",
        categories=[{"label": "Category A", "uri": "", "slug": "cat-a"}],
        actors=[{"name": "Actor One", "roles": ["Director"], "uri": ""}],
        events=[{"id": "1", "name": "Event 1", "start": "2024-01-01", "end": None, "actors": []}],
        digital_objects=[{"path": "/files/test.mp4", "uri": ""}],
        catchphrases=[{"label": "Keyword"}],
    )

    context = detail.to_view_context()

    assert context["title"] == "Context Test"
    assert context["subtitle"] == "A subtitle"
    assert context["descriptions"] == ["Description text"]
    assert context["institution"] == "Test Institution"
    assert context["projektart"] == "Research"
    assert context["year_range"] == "2024"
    assert context["categories"] == [{"label": "Category A", "uri": "", "slug": "cat-a"}]
    assert context["actors"] == [{"name": "Actor One", "roles": ["Director"], "uri": ""}]
    assert context["digital_objects"] == ["/files/test.mp4"]
    assert context["catchphrases"] == [{"label": "Keyword"}]


def test_project_view_uses_detail_index_when_available(client, user, settings, db, monkeypatch):
    """Test ProjectView prefers ProjectDetailIndex when backend is db."""
    settings.PROJECT_INDEX_BACKEND = "db"

    org = OrganizationFactory(code="detvieworg")
    resource = Resource.objects.create(
        id=uuid.uuid4(),
        uri="http://example.org/project/detail-view-test",
        resource_type=ResourceType.ENTITY,
        organization=org,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )

    # Create ProjectDetailIndex entry directly
    ProjectDetailIndex.objects.create(
        project_resource=resource,
        uri=resource.uri,
        org_code="detvieworg",
        title="Detail View Test",
        subtitle="Subtitle",
        description="Desc",
        institution_label="View Inst",
        categories=[],
        actors=[],
        events=[],
        digital_objects=[],
    )

    client.force_login(user)
    response = client.get(reverse("catalog:projekt"), {"projekt": resource.uri})

    assert response.status_code == 200
    assert b"Detail View Test" in response.content
