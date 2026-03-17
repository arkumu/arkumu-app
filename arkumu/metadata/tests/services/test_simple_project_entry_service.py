import pytest

from arkumu.metadata.services.simple_project_entry_service import SimpleProjectEntryService
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.users.models import Organization


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
class TestSimpleProjectEntryService:
    def _make_org(self):
        return Organization.objects.create(code="testorg", name="Test Org")

    def test_create_project_creates_entity_and_dataset_membership(self):
        org = self._make_org()
        service = SimpleProjectEntryService(organization=org)
        entity = service.create_project(title="My Test Project")

        assert entity._resource.resource_type == ResourceType.ENTITY
        # Must have isPartOf triple to "Projekt" dataset
        assert Triple.objects.filter(
            subject=entity._resource,
            predicate__uri="http://purl.org/dc/terms/isPartOf",
            source=org,
        ).exists()

    def test_create_project_sets_title_triple(self):
        org = self._make_org()
        service = SimpleProjectEntryService(organization=org)
        entity = service.create_project(title="My Test Project")

        title_triples = Triple.objects.filter(
            subject=entity._resource,
            object__value="My Test Project",
            object__resource_type=ResourceType.LITERAL,
        )
        assert title_triples.exists()

    def test_create_project_sets_projektart(self):
        org = self._make_org()
        projektart = Resource.objects.create(
            uri="http://arkumu.org/data/types/projektart/test-type",
            resource_type=ResourceType.ENTITY,
            name="Test Type",
        )
        service = SimpleProjectEntryService(organization=org)
        entity = service.create_project(
            title="Typed Project",
            projektart_uri=projektart.uri,
        )
        assert Triple.objects.filter(
            subject=entity._resource,
            object=projektart,
        ).exists()

    def test_create_project_links_ereignis(self):
        org = self._make_org()
        ereignis = Resource.objects.create(
            uri=f"http://arkumu.org/data/{org.code}/ereignis/e1",
            resource_type=ResourceType.ENTITY,
            name="Test Event",
            organization=org,
        )
        service = SimpleProjectEntryService(organization=org)
        entity = service.create_project(
            title="Project with Event",
            ereignis_uris=[ereignis.uri],
        )
        assert Triple.objects.filter(
            subject=entity._resource,
            object=ereignis,
            source=org,
        ).exists()

    def test_create_project_links_akteure(self):
        org = self._make_org()
        akteur = Resource.objects.create(
            uri=f"http://arkumu.org/data/{org.code}/akteurin/a1",
            resource_type=ResourceType.ENTITY,
            name="Test Actor",
            organization=org,
        )
        service = SimpleProjectEntryService(organization=org)
        entity = service.create_project(
            title="Project with Actor",
            akteure_uris=[akteur.uri],
        )
        assert Triple.objects.filter(
            subject=entity._resource,
            object=akteur,
            source=org,
        ).exists()
