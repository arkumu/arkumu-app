import pytest
from django.contrib.messages.storage.fallback import FallbackStorage
from django.http import HttpResponse
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from types import SimpleNamespace

from arkumu.metadata.models.resource import PublicAccessLevel, Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.oaipmh import media_link_views
from arkumu.oaipmh.models import OAIProjectMediaLink, OAIProjectPublication
from arkumu.users.models import Organization, User


def _attach_messages(request):
    request.session = {}
    storage = FallbackStorage(request)
    setattr(request, "_messages", storage)


def _make_project(org: Organization, uri: str, name: str = "Project") -> Resource:
    return Resource.objects.create(
        uri=uri,
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
        name=name,
    )


def _make_digital_object(org: Organization, uri: str, name: str = "Digital") -> Resource:
    return Resource.objects.create(
        uri=uri,
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
        name=name,
    )


@pytest.mark.django_db
def test_digital_object_search_filters_before_pagination(monkeypatch):
    org = Organization.objects.create(name="HMT", code="hmt")

    predicate = Resource.objects.create(
        uri="http://arkumu.org/data/properties/title",
        resource_type=ResourceType.PROPERTY,
        organization=org,
        name="preferred label",
    )

    monkeypatch.setattr(media_link_views, "MEDIA_LINKS_PAGE_SIZE", 2)

    for idx in range(3):
        project = Resource.objects.create(
            uri=f"https://example.org/project/{idx}",
            resource_type=ResourceType.ENTITY,
            organization=org,
            public_access_level=PublicAccessLevel.PUBLIC,
            name=f"Project {idx}",
        )
        digital = Resource.objects.create(
            uri=f"https://example.org/digital/{idx}",
            resource_type=ResourceType.ENTITY,
            organization=org,
            public_access_level=PublicAccessLevel.PUBLIC,
            name="" if idx == 2 else f"Object {idx}",
        )
        if idx == 2:
            label_literal = Resource.objects.create(
                uri=None,
                resource_type=ResourceType.LITERAL,
                value="Lieder Handschrift",
                organization=org,
            )
            Triple.objects.create(subject=digital, predicate=predicate, object=label_literal)

        OAIProjectMediaLink.objects.create(
            project=project,
            digital_object=digital,
        )

    context = media_link_views._build_digital_object_centric_context(
        organization=org,
        page_number=1,
        search_query="lieder",
    )

    assert context["digital_object_total"] == 1
    assert len(context["digital_object_rows"]) == 1
    assert "Lieder" in context["digital_object_rows"][0]["digital_object_label"]


@pytest.mark.django_db
def test_oai_project_status_update_approves_for_oai(monkeypatch):
    rf = RequestFactory()
    org = Organization.objects.create(name="FUK", code="fuk")
    user = User.objects.create_user(username="admin", password="test", role="system_admin")
    project = Resource.objects.create(
        uri="https://example.org/project/1",
        resource_type=ResourceType.ENTITY,
        organization=org,
        public_access_level=PublicAccessLevel.RESTRICTED,
    )

    request = rf.post(
        "/fake",
        data={
            "oai_publish_action": "approve",
            "page": "2",
        },
    )
    request.user = user
    _attach_messages(request)

    monkeypatch.setattr(
        media_link_views,
        "_build_single_project_row_context",
        lambda **kwargs: {"has_harvestable_files": False, "harvestable_count": 0},
    )
    render_context = {}

    def fake_render(request, template, context):
        render_context.update(context)
        return HttpResponse("ok", status=200)

    monkeypatch.setattr(media_link_views, "render", fake_render)

    response = media_link_views.oai_project_status_update(request, project.id)
    assert response.status_code == 200
    publication = OAIProjectPublication.objects.get(project=project)
    assert publication.is_approved is True
    assert publication.approved_by == user
    assert render_context.get("current_page") == 2


@pytest.mark.django_db
def test_oai_project_status_update_revokes_oai(monkeypatch):
    rf = RequestFactory()
    org = Organization.objects.create(name="DET", code="det")
    user = User.objects.create_user(username="admin2", password="test", role="system_admin")
    project = Resource.objects.create(
        uri="https://example.org/project/2",
        resource_type=ResourceType.ENTITY,
        organization=org,
        public_access_level=PublicAccessLevel.PUBLIC,
    )
    OAIProjectPublication.objects.create(project=project, is_approved=True)

    request = rf.post("/fake", data={"oai_publish_action": "revoke"})
    request.user = user
    _attach_messages(request)

    monkeypatch.setattr(
        media_link_views,
        "_build_single_project_row_context",
        lambda **kwargs: {"has_harvestable_files": True, "harvestable_count": 2},
    )
    render_context = {}

    def fake_render(request, template, context):
        render_context.update(context)
        return HttpResponse("ok", status=200)

    monkeypatch.setattr(media_link_views, "render", fake_render)

    response = media_link_views.oai_project_status_update(request, project.id)
    assert response.status_code == 200
    publication = OAIProjectPublication.objects.get(project=project)
    assert publication.is_approved is False
    assert render_context.get("current_page") == 1


@pytest.mark.django_db
def test_summary_counts_unique_project_uris():
    org = Organization.objects.create(name="Org", code="org", domain="org", is_active=True)

    project = _make_project(org, "http://arkumu.test/entities/projekt/duplicate", name="Primary")
    digital_a = _make_project(org, "http://arkumu.test/entities/digital/a", name="Digital A")
    digital_b = _make_project(org, "http://arkumu.test/entities/digital/b", name="Digital B")

    OAIProjectMediaLink.objects.create(project=project, digital_object=digital_a)
    OAIProjectMediaLink.objects.create(project=project, digital_object=digital_b)
    OAIProjectPublication.objects.create(project=project, is_approved=True)

    link_qs = media_link_views._media_link_prefetch_queryset(org)
    summary = media_link_views._build_media_links_summary(org, link_qs)

    assert summary["available_project_count"] == 1


@pytest.mark.django_db
def test_summary_counts_curated_projects_for_non_s3_org(monkeypatch):
    org = Organization.objects.create(name="KHM", code="khm", domain="khm", is_active=True)
    harvestable_project = _make_project(org, "https://arkumu.org/entities/projekt/harvestable")
    stale_project = _make_project(org, "https://arkumu.org/entities/projekt/stale")
    duplicate_uri_project = _make_project(org, "https://arkumu.org/entities/projekt/stale-dup")
    fresh_digital = _make_digital_object(org, "https://arkumu.org/entities/digital/fresh")
    stale_digital = _make_digital_object(org, "https://arkumu.org/entities/digital/stale")

    OAIProjectMediaLink.objects.create(project=harvestable_project, digital_object=fresh_digital)
    OAIProjectMediaLink.objects.create(project=stale_project, digital_object=stale_digital, is_stale=True)
    OAIProjectMediaLink.objects.create(project=duplicate_uri_project, digital_object=fresh_digital)
    OAIProjectPublication.objects.create(project=harvestable_project, is_approved=True)
    OAIProjectPublication.objects.create(project=stale_project, is_approved=False)
    OAIProjectPublication.objects.create(project=duplicate_uri_project, is_approved=False)

    curated_ids = media_link_views._curated_harvestable_project_ids(org)
    link_qs = media_link_views._media_link_prefetch_queryset(org)

    summary = media_link_views._build_media_links_summary(
        org,
        link_qs,
        curated_harvestable_ids=curated_ids,
    )

    assert summary["harvestable_project_count"] == 1
    assert summary["available_project_count"] == 3


@pytest.mark.django_db
def test_project_panel_harvestable_filter_uses_curated_links(monkeypatch):
    org = Organization.objects.create(name="HMT", code="hmt", domain="hmt", is_active=True)
    harvestable_project = _make_project(org, "https://arkumu.org/entities/projekt/active")
    stale_project = _make_project(org, "https://arkumu.org/entities/projekt/stale-only")
    fresh_digital = _make_digital_object(org, "https://arkumu.org/entities/digital/fresh-door")
    stale_digital = _make_digital_object(org, "https://arkumu.org/entities/digital/stale-door")

    OAIProjectMediaLink.objects.create(project=harvestable_project, digital_object=fresh_digital)
    OAIProjectMediaLink.objects.create(project=stale_project, digital_object=stale_digital, is_stale=True)

    monkeypatch.setattr(media_link_views, "_build_project_row_context", lambda resource, **_: {
        "project_uri": resource.uri,
        "builder_error": False,
    })

    harvestable_context = media_link_views._build_media_links_panel_context(
        organization=org,
        page_number=1,
        harvestable_filter="harvestable",
    )

    harvestable_rows = [row["project_uri"] for row in harvestable_context["project_rows"]]
    assert harvestable_project.uri in harvestable_rows
    assert stale_project.uri not in harvestable_rows

    non_harvestable_context = media_link_views._build_media_links_panel_context(
        organization=org,
        page_number=1,
        harvestable_filter="non_harvestable",
    )

    non_harvestable_rows = [row["project_uri"] for row in non_harvestable_context["project_rows"]]
    assert stale_project.uri in non_harvestable_rows
    assert harvestable_project.uri not in non_harvestable_rows


@pytest.mark.django_db
def test_project_search_filters_before_pagination(monkeypatch):
    org = Organization.objects.create(name="KHM", code="khm", domain="khm", is_active=True)
    monkeypatch.setattr(media_link_views, "MEDIA_LINKS_PAGE_SIZE", 1)

    target = _make_project(org, "https://arkumu.org/entities/projekt/match", name="Match Project")
    other = _make_project(org, "https://arkumu.org/entities/projekt/other", name="Other Project")
    target_digital = _make_digital_object(org, "https://arkumu.org/entities/digital/target")
    other_digital = _make_digital_object(org, "https://arkumu.org/entities/digital/other")

    OAIProjectMediaLink.objects.create(project=target, digital_object=target_digital)
    OAIProjectMediaLink.objects.create(project=other, digital_object=other_digital)

    # Force ordering so the target would normally appear on page 2
    Resource.objects.filter(id=other.id).update(updated_at=timezone.now())
    Resource.objects.filter(id=target.id).update(updated_at=timezone.now() - timedelta(days=1))

    context = media_link_views._build_media_links_panel_context(
        organization=org,
        page_number=1,
        search_query="match",
    )

    project_rows = [row["project_uri"] for row in context["project_rows"]]
    assert target.uri in project_rows
    assert context["page_obj"].paginator.count == 1


@pytest.mark.django_db
def test_project_row_auto_approves_publication_for_harvestable_project(monkeypatch):
    org = Organization.objects.create(name="KHM", code="khm", domain="khm", is_active=True)
    project = _make_project(org, "https://arkumu.org/data/khm/entities/00-projekte/auto")
    digital = _make_digital_object(org, "https://arkumu.org/data/khm/entities/12-media-digitaleobjekte/auto")

    link = OAIProjectMediaLink.objects.create(project=project, digital_object=digital)
    project.prefetched_media_links = [link]

    fake_record = SimpleNamespace(title="Auto Project")
    fake_obj = SimpleNamespace(resource_id=str(digital.id), uri=digital.uri, harvestable=True)
    fake_project = SimpleNamespace(digital_objects=[fake_obj], curated_selection=None)

    assembler = SimpleNamespace(build_record=lambda context: fake_record)
    builder = SimpleNamespace(from_project_record=lambda *args, **kwargs: fake_project)

    row = media_link_views._build_project_row_context(
        project,
        builder=builder,
        assembler=assembler,
        org_code=org.code,
        is_s3_org=False,
        label_lookup={},
        publication_by_id={},
    )

    publication = OAIProjectPublication.objects.get(project=project)
    assert publication.is_approved is True
    assert row["oai_is_approved"] is True


@pytest.mark.django_db
def test_project_row_preserves_manual_revoke(monkeypatch):
    org = Organization.objects.create(name="KHM", code="khm", domain="khm", is_active=True)
    project = _make_project(org, "https://arkumu.org/data/khm/entities/00-projekte/manual")
    digital = _make_digital_object(org, "https://arkumu.org/data/khm/entities/12-media-digitaleobjekte/manual")

    link = OAIProjectMediaLink.objects.create(project=project, digital_object=digital)
    project.prefetched_media_links = [link]

    publication = OAIProjectPublication.objects.create(project=project, is_approved=False)

    fake_record = SimpleNamespace(title="Manual Project")
    fake_obj = SimpleNamespace(resource_id=str(digital.id), uri=digital.uri, harvestable=True)
    fake_project = SimpleNamespace(digital_objects=[fake_obj], curated_selection=None)

    assembler = SimpleNamespace(build_record=lambda context: fake_record)
    builder = SimpleNamespace(from_project_record=lambda *args, **kwargs: fake_project)

    row = media_link_views._build_project_row_context(
        project,
        builder=builder,
        assembler=assembler,
        org_code=org.code,
        is_s3_org=False,
        label_lookup={},
        publication_by_id={project.id: publication},
    )

    publication.refresh_from_db()
    assert publication.is_approved is False
    assert row["oai_is_approved"] is False


@pytest.mark.django_db
def test_project_row_auto_approves_s3_project_when_s3_file_present(monkeypatch):
    org = Organization.objects.create(name="FUK", code="fuk", domain="fuk", is_active=True)
    project = _make_project(org, "https://arkumu.org/data/fuk/entities/projekt/s3-auto")
    digital = _make_digital_object(org, "https://arkumu.org/data/fuk/entities/digitales-objekt/s3-auto")

    link = OAIProjectMediaLink.objects.create(project=project, digital_object=digital)
    setattr(link, "has_s3_file", True)
    project.prefetched_media_links = [link]

    fake_record = SimpleNamespace(title="S3 Auto")
    fake_obj = SimpleNamespace(resource_id=str(digital.id), uri=digital.uri, harvestable=True)
    fake_project = SimpleNamespace(digital_objects=[fake_obj], curated_selection=None)

    assembler = SimpleNamespace(build_record=lambda context: fake_record)
    builder = SimpleNamespace(from_project_record=lambda *args, **kwargs: fake_project)

    row = media_link_views._build_project_row_context(
        project,
        builder=builder,
        assembler=assembler,
        org_code=org.code,
        is_s3_org=True,
        label_lookup={},
        publication_by_id={},
    )

    publication = OAIProjectPublication.objects.get(project=project)
    assert publication.is_approved is True
    assert row["oai_is_approved"] is True
    assert row["has_harvestable_files"] is True


@pytest.mark.django_db
def test_project_row_does_not_auto_approve_s3_project_without_s3_file(monkeypatch):
    org = Organization.objects.create(name="FUK", code="fuk", domain="fuk", is_active=True)
    project = _make_project(org, "https://arkumu.org/data/fuk/entities/projekt/s3-pending")
    digital = _make_digital_object(org, "https://arkumu.org/data/fuk/entities/digitales-objekt/s3-pending")

    link = OAIProjectMediaLink.objects.create(project=project, digital_object=digital)
    setattr(link, "has_s3_file", False)
    project.prefetched_media_links = [link]

    fake_record = SimpleNamespace(title="S3 Pending")
    fake_obj = SimpleNamespace(resource_id=str(digital.id), uri=digital.uri, harvestable=True)
    fake_project = SimpleNamespace(digital_objects=[fake_obj], curated_selection=None)

    assembler = SimpleNamespace(build_record=lambda context: fake_record)
    builder = SimpleNamespace(from_project_record=lambda *args, **kwargs: fake_project)

    row = media_link_views._build_project_row_context(
        project,
        builder=builder,
        assembler=assembler,
        org_code=org.code,
        is_s3_org=True,
        label_lookup={},
        publication_by_id={},
    )

    assert OAIProjectPublication.objects.filter(project=project).count() == 0
    assert row["oai_is_approved"] is False
    assert row["has_harvestable_files"] is False


@pytest.mark.django_db
def test_clear_data_endpoint_deletes_links_and_publications(client):
    org = Organization.objects.create(name="KHM", code="khm", domain="khm", is_active=True)
    user = User.objects.create_user(username="admin", password="test", role="system_admin")
    client.force_login(user)

    project = _make_project(org, "https://arkumu.org/data/khm/entities/00-projekte/clear")
    digital = _make_digital_object(org, "https://arkumu.org/data/khm/entities/12-media-digitaleobjekte/clear")
    OAIProjectMediaLink.objects.create(project=project, digital_object=digital)
    OAIProjectPublication.objects.create(project=project, is_approved=True)

    response = client.post(
        reverse('oai_admin:oai_media_link_clear_data'),
        data={
            'organization': org.code,
            'project_access': 'all',
            'oai_publish': 'all',
            'harvestable': 'all',
            'search': '',
        },
        HTTP_HX_REQUEST='true',
    )

    assert response.status_code == 200
    assert OAIProjectMediaLink.objects.filter(project__organization=org).count() == 0
    assert OAIProjectPublication.objects.filter(project__organization=org).count() == 0


@pytest.mark.django_db
def test_clear_data_endpoint_redirects_outside_htmx(client):
    org = Organization.objects.create(name="KHM", code="khm", domain="khm", is_active=True)
    user = User.objects.create_user(username="admin2", password="test", role="system_admin")
    client.force_login(user)

    project = _make_project(org, "https://arkumu.org/data/khm/entities/00-projekte/redirect")
    digital = _make_digital_object(org, "https://arkumu.org/data/khm/entities/12-media-digitaleobjekte/redirect")
    OAIProjectMediaLink.objects.create(project=project, digital_object=digital)

    response = client.post(
        reverse('oai_admin:oai_media_link_clear_data'),
        data={
            'organization': org.code,
            'project_access': 'all',
            'oai_publish': 'all',
            'harvestable': 'all',
            'search': '',
        },
    )

    assert response.status_code == 302
    assert response.headers['Location'].endswith(reverse('metadata:metadata_dashboard'))
    assert OAIProjectMediaLink.objects.filter(project__organization=org).count() == 0
