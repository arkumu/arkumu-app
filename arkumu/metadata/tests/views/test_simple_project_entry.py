import pytest
from django.test import Client
from django.urls import reverse

from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.services.simple_project_entry_service import SimpleProjectEntryService
from arkumu.users.models import Organization, User


@pytest.fixture(autouse=True)
def rdf_type_resource(db):
    Resource.objects.get_or_create(
        uri="http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
        defaults={
            "resource_type": ResourceType.PROPERTY,
            "name": "rdf:type",
        },
    )


@pytest.mark.django_db
class TestSimpleProjectEntryIntegration:
    def _setup(self):
        org = Organization.objects.create(code="testorg", name="Test Org")
        user = User.objects.create_user(
            username="testuser", password="testpass", organization=org
        )
        return org, user

    def test_created_project_has_dataset_membership_for_workspace(self):
        """Projects created via SimpleProjectEntryService must appear in workspace listing."""
        org, user = self._setup()
        service = SimpleProjectEntryService(organization=org)
        entity = service.create_project(title="Workspace Test Project")

        # The workspace listing queries for entities with isPartOf to a "Projekt" dataset
        is_part_of_triple = Triple.objects.filter(
            subject=entity._resource,
            predicate__uri="http://purl.org/dc/terms/isPartOf",
            source=org,
        ).select_related("object").first()

        assert is_part_of_triple is not None
        assert is_part_of_triple.object.resource_type == ResourceType.IRI
        # Dataset name must match what ProjectWorkspaceListingService expects
        assert is_part_of_triple.object.name == "Projekt"

    def test_view_requires_login(self):
        client = Client()
        url = reverse("metadata:simple_project_entry")
        response = client.get(url)
        assert response.status_code == 302  # redirect to login

    def test_view_renders_for_authenticated_user(self):
        org, user = self._setup()
        client = Client()
        client.login(username="testuser", password="testpass")
        url = reverse("metadata:simple_project_entry")
        response = client.get(url)
        assert response.status_code == 200
        assert b"Neues Projekt" in response.content
