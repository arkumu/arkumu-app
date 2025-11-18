from types import SimpleNamespace

import pytest
from django.urls import reverse

from arkumu.metadata.models.resource import PublicAccessLevel, Resource, ResourceType
from arkumu.oaipmh.models import OAIProjectMediaLink, OAIProjectPublication
from arkumu.oaipmh import tailored_dashboard_views
from arkumu.projects import ProjectInstitution, ProjectRecord
from arkumu.users.models import Organization, User

from arkumu.oaipmh.oai_project import OAIProject


@pytest.mark.django_db
def test_tailored_dashboard_renders_curated_stats(client, monkeypatch):
    user = User.objects.create_user(username="tailored-admin", password="test", role="system_admin")
    client.force_login(user)

    org = Organization.objects.create(name="FUK", code="fuk", is_active=True)
    project = Resource.objects.create(
        uri="https://arkumu.org/entities/projekt/200",
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )
    digital = Resource.objects.create(
        uri="https://arkumu.org/entities/digital/200-a",
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )
    OAIProjectMediaLink.objects.create(project=project, digital_object=digital, order_index=1)
    OAIProjectPublication.objects.create(project=project, is_approved=True)

    record = ProjectRecord(
        subject_id=str(project.id),
        uri=project.uri,
        title="Tailored Dashboard",
        institution=ProjectInstitution(label=org.name, code=org.code),
    )
    fake_object = SimpleNamespace(harvestable=True)
    fake_project = OAIProject(
        record=record,
        institution_code=org.code,
        digital_objects=(fake_object,),
    )

    def _fake_project_hint(resource):
        if resource.pk == project.pk:
            return fake_project
        return None

    monkeypatch.setattr(
        tailored_dashboard_views,
        "_build_tailored_project_hint_from_resource",
        _fake_project_hint,
    )
    monkeypatch.setattr(
        tailored_dashboard_views,
        "_tailored_resources_queryset",
        lambda: Resource.objects.filter(pk=project.pk),
    )

    response = client.get(reverse("oai_admin:oai_tailored_dashboard"))
    assert response.status_code == 200

    snapshot = None
    for ctx in response.context:
        if "tailored_snapshot" in ctx:
            snapshot = ctx["tailored_snapshot"]
            break
    assert snapshot is not None
    assert snapshot.total_accessible_projects == 1

    html = response.content.decode()
    assert "Tailored OAI-PMH Endpoint" in html
    assert "ListRecords&amp;metadataPrefix=mets&amp;set=fuk" in html
    assert "/metadata/dashboard/oai-tailored/" in html


@pytest.mark.django_db
def test_oai_tailored_proxy_requires_verb_parameter(client):
    user = User.objects.create_user(username="proxy-admin", password="test", role="system_admin")
    client.force_login(user)

    response = client.get(reverse("metadata:oai_tailored_proxy"))
    assert response.status_code == 400
    assert "Missing required 'verb' parameter" in response.content.decode()
