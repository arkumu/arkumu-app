import pytest
from django.contrib.messages.storage.fallback import FallbackStorage
from django.http import HttpResponse
from django.test import RequestFactory

from arkumu.metadata.models.resource import PublicAccessLevel, Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.oaipmh import dashboard_views
from arkumu.oaipmh.models import OAIProjectMediaLink, OAIProjectPublication
from arkumu.users.models import Organization, User


def _attach_messages(request):
    request.session = {}
    storage = FallbackStorage(request)
    setattr(request, "_messages", storage)


@pytest.mark.django_db
def test_digital_object_search_filters_before_pagination(monkeypatch):
    org = Organization.objects.create(name="HMT", code="hmt")

    predicate = Resource.objects.create(
        uri="http://arkumu.org/data/properties/title",
        resource_type=ResourceType.PROPERTY,
        organization=org,
        name="preferred label",
    )

    monkeypatch.setattr(dashboard_views, "MEDIA_LINKS_PAGE_SIZE", 2)

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

    context = dashboard_views._build_digital_object_centric_context(
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
        dashboard_views,
        "_build_single_project_row_context",
        lambda **kwargs: {"has_harvestable_files": False, "harvestable_count": 0},
    )
    render_context = {}

    def fake_render(request, template, context):
        render_context.update(context)
        return HttpResponse("ok", status=200)

    monkeypatch.setattr(dashboard_views, "render", fake_render)

    response = dashboard_views.oai_project_status_update(request, project.id)
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
        dashboard_views,
        "_build_single_project_row_context",
        lambda **kwargs: {"has_harvestable_files": True, "harvestable_count": 2},
    )
    render_context = {}

    def fake_render(request, template, context):
        render_context.update(context)
        return HttpResponse("ok", status=200)

    monkeypatch.setattr(dashboard_views, "render", fake_render)

    response = dashboard_views.oai_project_status_update(request, project.id)
    assert response.status_code == 200
    publication = OAIProjectPublication.objects.get(project=project)
    assert publication.is_approved is False
    assert render_context.get("current_page") == 1
