import pytest

from arkumu.metadata.services.simple_project_entry_service import SimpleProjectEntryService
from arkumu.metadata.models.mappings import Mapping
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


# Minimal schema_manifest that mirrors what a real mapping provides
_TEST_MANIFEST = {
    "Projekt": {
        "entity_type": {
            "uri": "http://arkumu.org/data/testorg/types/projekt",
            "name": "Projekt",
            "canonical_uri": "http://arkumu.org/data/types/projekt",
        },
        "properties": {
            "Titel": {
                "uri": "http://arkumu.org/data/testorg/properties/titel",
                "name": "Titel",
                "canonical_uri": "http://arkumu.org/data/properties/bevorzugter-titel",
            },
            "Projektart": {
                "uri": "http://arkumu.org/data/testorg/properties/projektart",
                "name": "Projektart",
                "canonical_uri": "http://arkumu.org/data/properties/projektart",
            },
            "Ereignis": {
                "uri": "http://arkumu.org/data/testorg/properties/ereignis",
                "name": "Ereignis",
                "canonical_uri": "http://arkumu.org/data/properties/ereignis",
            },
            "Akteur": {
                "uri": "http://arkumu.org/data/testorg/properties/akteur",
                "name": "Akteur",
                "canonical_uri": "http://arkumu.org/data/properties/akteur",
            },
            "Digitales Objekt": {
                "uri": "http://arkumu.org/data/testorg/properties/digitales-objekt",
                "name": "Digitales Objekt",
                "canonical_uri": "http://arkumu.org/data/properties/digitales-objekt",
            },
        },
    },
    "Digitales_Objekt": {
        "entity_type": {
            "uri": "http://arkumu.org/data/testorg/types/digitales-objekt",
            "name": "Digitales_Objekt",
            "canonical_uri": "http://arkumu.org/data/types/digitales-objekt",
        },
        "properties": {
            "Dateipfad": {
                "uri": "http://arkumu.org/data/testorg/properties/dateipfad",
                "name": "Dateipfad",
                "canonical_uri": "http://arkumu.org/data/properties/dateipfad",
            },
        },
    },
}


@pytest.mark.django_db
class TestSimpleProjectEntryService:
    def _make_org(self):
        org = Organization.objects.create(code="testorg", name="Test Org")
        Mapping.objects.create(
            name="test-mapping",
            organization_id=org.code,
            is_active=True,
            mapping_config={"schema_manifest": _TEST_MANIFEST},
        )
        return org

    def test_create_project_creates_entity_and_dataset_membership(self):
        org = self._make_org()
        service = SimpleProjectEntryService(organization=org)
        entity = service.create_project(title="My Test Project")

        assert entity._resource.resource_type == ResourceType.ENTITY
        assert Triple.objects.filter(
            subject=entity._resource,
            predicate__uri="http://purl.org/dc/terms/isPartOf",
            source=org,
        ).exists()

    def test_create_project_sets_title_triple(self):
        org = self._make_org()
        service = SimpleProjectEntryService(organization=org)
        entity = service.create_project(title="My Test Project")

        # Title uses the mapping-resolved URI, not the canonical one
        assert Triple.objects.filter(
            subject=entity._resource,
            predicate__uri="http://arkumu.org/data/testorg/properties/titel",
            object__value="My Test Project",
            object__resource_type=ResourceType.LITERAL,
        ).exists()

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
            predicate__uri="http://arkumu.org/data/testorg/properties/projektart",
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
            predicate__uri="http://arkumu.org/data/testorg/properties/ereignis",
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
            predicate__uri="http://arkumu.org/data/testorg/properties/akteur",
            object=akteur,
            source=org,
        ).exists()

    def test_create_digital_object_and_link_to_project(self):
        org = self._make_org()
        service = SimpleProjectEntryService(organization=org)
        project = service.create_project(title="Project with DO")

        do_entity = service.create_digital_object(
            project=project,
            s3_key="testorg/uploads/test.pdf",
            file_name="test.pdf",
            content_type="application/pdf",
            file_size=1024,
        )

        assert do_entity._resource.resource_type == ResourceType.ENTITY
        assert Triple.objects.filter(
            subject=project._resource,
            predicate__uri="http://arkumu.org/data/testorg/properties/digitales-objekt",
            object=do_entity._resource,
            source=org,
        ).exists()
        assert Triple.objects.filter(
            subject=do_entity._resource,
            predicate__uri="http://purl.org/dc/terms/isPartOf",
        ).exists()
