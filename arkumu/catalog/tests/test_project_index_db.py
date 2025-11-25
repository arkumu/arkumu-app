import uuid

from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from arkumu.catalog.models import ProjectIndex, ProjectRecordIndex
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

    assert result["projects_index"] == 2
    assert result["project_records"] == 2

    stored_public = ProjectRecordIndex.objects.get(project_resource=public_res)
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
        return {"projects_index": 3, "project_records": 3}

    monkeypatch.setattr(ProjectIndexDbService, "rebuild", fake_rebuild)

    call_command(
        "rebuild_project_index",
        "--project-uri",
        "http://example.org/project/command",
        "--force-snapshot",
    )

    assert calls == [{"uris": ["http://example.org/project/command"], "force": True}]
    output = capsys.readouterr().out
    assert "cards=3" in output
    assert "records=3" in output


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
