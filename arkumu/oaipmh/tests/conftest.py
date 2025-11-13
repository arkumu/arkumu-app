"""
Shared pytest fixtures for OAI-PMH tests.

Provides common test data, mock services, and utility functions.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch
from lxml import etree as ET
from typing import Dict, Any, List

from django.test import Client, TransactionTestCase
from django.contrib.auth import get_user_model
from django.db import transaction
from django.core.cache import cache
from django.utils import timezone as dj_timezone

from arkumu.users.models import Organization
from arkumu.metadata.models.resource import Resource, PublicAccessLevel, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.storage.models.s3_file_objects import S3FileObject
from arkumu.projects import ProjectSnapshot
from arkumu.projects.services.dump_fixity_index import FixityRecord
from arkumu.oaipmh import views, path_mapping
from arkumu.oaipmh.views import HARVESTABLE_FILE_STATUSES, _fallback_record_from_storage
from arkumu.projects.services import dump_fixity_index, s3_key_index

User = get_user_model()
_FAST_SNAPSHOT_SERVICE = None


@pytest.fixture
def oai_client(db):
    """HTTP client for OAI-PMH endpoint testing with authentication."""
    client = Client()

    # Create a test user for authentication
    user = User.objects.create_user(
        username='oai_test_user',
        password='test_password',
        email='oai@test.com'
    )

    # Login the client for authenticated requests
    client.login(username='oai_test_user', password='test_password')

    return client


@pytest.fixture
def sample_organizations(db):
    """Create sample organizations for testing."""
    orgs = []

    # Active organization
    org1 = Organization.objects.create(
        name="Test University Library",
        code="test_univ",
        domain="library.test.edu",
        is_active=True
    )
    orgs.append(org1)

    # Another active organization
    org2 = Organization.objects.create(
        name="Research Institute",
        code="research_inst",
        domain="research.test.org",
        is_active=True
    )
    orgs.append(org2)

    # Inactive organization (should not appear in sets)
    org3 = Organization.objects.create(
        name="Inactive Org",
        code="inactive_org",
        domain="inactive.test.com",
        is_active=False
    )
    orgs.append(org3)

    return orgs


@pytest.fixture
def sample_resources(db, sample_organizations):
    """Create sample resources for testing."""
    resources = []

    # Public approved resources (harvestable)
    base_time = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    for i in range(5):
        resource = Resource.objects.create(
            uri=f"https://arkumu.org/entities/projekt/{i+1}",
            organization=sample_organizations[0],  # test_univ
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True,
            updated_at=base_time.replace(day=i+1)  # Different dates for temporal filtering
        )
        resources.append(resource)

        S3FileObject.objects.create(
            file_name=f"test-file-{i+1}.txt",
            s3_key=f"test_univ/file-{i+1}.txt",
            file_size_bytes=1024,
            content_type="text/plain",
            related_resource=resource,
            status='completed'
        )

    # Resource from second organization
    resource = Resource.objects.create(
        uri="https://arkumu.org/entities/projekt/600",
        organization=sample_organizations[1],  # research_inst
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
        updated_at=base_time.replace(month=2)
    )
    resources.append(resource)

    S3FileObject.objects.create(
        file_name="research-file-1.txt",
        s3_key="research_inst/file-1.txt",
        file_size_bytes=2048,
        content_type="text/plain",
        related_resource=resource,
        status='completed'
    )

    # Private resource (not harvestable)
    resource = Resource.objects.create(
        uri="https://test.example.com/private/1",
        organization=sample_organizations[0],
        public_access_level=PublicAccessLevel.PRIVATE,
        is_public_approved=True,
        updated_at=base_time.replace(month=3)
    )
    resources.append(resource)

    # Unapproved resource (not harvestable)
    resource = Resource.objects.create(
        uri="https://test.example.com/unapproved/1",
        organization=sample_organizations[0],
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=False,
        updated_at=base_time.replace(month=4)
    )
    resources.append(resource)

    return resources


@pytest.fixture
def parity_dataset(db):
    """Dataset mirroring docs/db_vs_snapshot_comparison.md instructions."""
    org_specs = (
        ("FUK Library", "fuk"),
        ("KHM Museum", "khm"),
        ("HMT Music Archive", "hmt"),
    )
    project_type_map = {
        "fuk": "http://arkumu.org/data/fuk/types/projekt",
        "khm": "http://arkumu.org/data/khm/types/00-projekte",
        "hmt": "http://arkumu.org/data/hmt/types/00-hfm-projekte",
    }
    rdf_type_uri = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
    rdf_type_resource, _ = Resource.objects.get_or_create(
        uri=rdf_type_uri,
        defaults={
            "resource_type": ResourceType.PROPERTY,
            "name": "rdf:type",
        },
    )
    project_type_resources: Dict[str, Resource] = {}
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    dataset: Dict[str, Any] = {
        "orgs": {},
        "org_codes": [],
        "sample_project_uris": [],
    }

    for offset, (name, code) in enumerate(org_specs):
        organization = Organization.objects.create(
            name=name,
            code=code,
            domain=f"{code}.arkumu.test",
            is_active=True,
        )
        dataset["org_codes"].append(code)

        resources: List[Resource] = []
        for idx in range(12):
            uri = f"http://arkumu.org/data/entities/projekt/{(offset + 1) * 1000 + idx}"
            resource = Resource.objects.create(
                uri=uri,
                organization=organization,
                public_access_level=PublicAccessLevel.PUBLIC,
                is_public_approved=True,
                updated_at=base_time + timedelta(days=offset, minutes=idx),
                value=f"{code.upper()} Reference Project {idx}",
            )
            resources.append(resource)

            S3FileObject.objects.create(
                file_name=f"{code}-object-{idx}.tif",
                s3_key=f"{code}/objects/object-{idx}.tif",
                file_size_bytes=2048 + idx,
                content_type="image/tiff",
                related_resource=resource,
                status='completed',
                organization=code,
            )
        project_type_uri = project_type_map.get(code, "http://arkumu.org/data/types/projekt")
        project_type_resource = project_type_resources.get(project_type_uri)
        if project_type_resource is None:
            project_type_resource, _ = Resource.objects.get_or_create(
                uri=project_type_uri,
                defaults={
                    "resource_type": ResourceType.CLASS,
                    "name": f"{code.upper()} Project Type",
                },
            )
            project_type_resources[project_type_uri] = project_type_resource
        for resource in resources:
            Triple.objects.create(
                subject=resource,
                predicate=rdf_type_resource,
                object=project_type_resource,
                source=organization,
            )

        dataset["orgs"][code] = {
            "organization": organization,
            "resources": resources,
            "uris": [res.uri for res in resources],
        }
        dataset["sample_project_uris"].extend([res.uri for res in resources[:3]])

    # Identifier that lacks harvestable files for error parity assertions
    primary_org = dataset["orgs"][org_specs[0][1]]["organization"]
    orphan_resource = Resource.objects.create(
        uri="http://arkumu.org/data/entities/projekt/999901",
        organization=primary_org,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
        updated_at=base_time + timedelta(days=10),
    )
    Triple.objects.create(
        subject=orphan_resource,
        predicate=rdf_type_resource,
        object=project_type_resources[project_type_map["fuk"]],
        source=primary_org,
    )
    dataset["non_harvestable_uri"] = orphan_resource.uri

    return dataset


@pytest.fixture(autouse=True)
def clear_oai_related_cache():
    """Ensure cache is cleared between tests to avoid stale OAI pages."""
    cache.clear()

@pytest.fixture
def mock_canonical_graph_service():
    """Mock CanonicalGraphService for testing."""
    with patch('arkumu.oaipmh.views.CanonicalGraphService') as mock_class:
        mock_instance = Mock()
        mock_class.return_value = mock_instance

        # Default mock response for get_entity_graph
        mock_instance.get_entity_graph.return_value = {
            "root_id": "https://test.example.com/resource/1",
            "nodes": {
                "https://test.example.com/resource/1": {
                    "type": "Resource",
                    "label": "Test Resource",
                    "uri": "https://test.example.com/resource/1"
                }
            },
            "edges": [
                {
                    "subject_id": "https://test.example.com/resource/1",
                    "predicate_canonical": "http://purl.org/dc/terms/title",
                    "predicate_uri": "http://purl.org/dc/terms/title",
                    "object_value": "Test Resource Title",
                    "object_id": None
                },
                {
                    "subject_id": "https://test.example.com/resource/1",
                    "predicate_canonical": "http://purl.org/dc/terms/creator",
                    "predicate_uri": "http://purl.org/dc/terms/creator",
                    "object_value": "Test Creator",
                    "object_id": None
                },
                {
                    "subject_id": "https://test.example.com/resource/1",
                    "predicate_canonical": "http://purl.org/dc/terms/description",
                    "predicate_uri": "http://purl.org/dc/terms/description",
                    "object_value": "A test resource for OAI-PMH testing",
                    "object_id": None
                }
            ]
        }

        yield mock_instance


@pytest.fixture(autouse=True)
def _fast_snapshot_service(monkeypatch):
    """Patch snapshot service with a lightweight fallback-driven implementation."""
    from arkumu.metadata.models.resource import Resource  # Local import for Django readiness

    global _FAST_SNAPSHOT_SERVICE

    class _SnapshotStub:
        def __init__(self):
            self._snapshot = None
            self._index = {}

        def _build(self):
            resources = (
                Resource.objects.filter(
                    s3fileobject__status__in=HARVESTABLE_FILE_STATUSES,
                    s3fileobject__s3_key__isnull=False,
                )
                .exclude(s3fileobject__s3_key="")
                .distinct()
            )

            records = []
            index = {}
            for resource in resources:
                record = _fallback_record_from_storage(resource)
                if not record or not record.uri:
                    continue
                records.append(record)
                index[record.uri] = record

            self._snapshot = ProjectSnapshot(
                projects=records,
                counts={"projects": len(records)},
                generated_at=dj_timezone.now(),
            )
            self._index = index

        def _ensure_snapshot(self):
            if self._snapshot is None:
                self._build()

        def get_cross_institutional_snapshot(self, *, force_refresh: bool = False):
            if force_refresh or self._snapshot is None:
                self._build()
            return self._snapshot

        def refresh_cross_institutional_snapshot(self):
            self._build()
            return self._snapshot

        def get_record_by_uri(self, uri: str):
            if not uri:
                return None
            self._ensure_snapshot()
            return self._index.get(uri)

    if _FAST_SNAPSHOT_SERVICE is None:
        _FAST_SNAPSHOT_SERVICE = _SnapshotStub()

    monkeypatch.setattr(views, "snapshot_service", _FAST_SNAPSHOT_SERVICE)
    yield


@pytest.fixture(autouse=True)
def _db_assembler_stub(monkeypatch):
    """Ensure DB-backed assembly returns deterministic records for synthetic data."""

    class _AssemblerStub:
        def build_record(self, context):
            return _fallback_record_from_storage(context.resource)

    monkeypatch.setattr(views, "_db_project_assembler_instance", _AssemblerStub())


@pytest.fixture(autouse=True)
def _oai_storage_stubs(monkeypatch):
    """Provide deterministic storage lookups for synthetic parity datasets."""

    def fake_find_fixity(org_code, candidates):
        for candidate in candidates or []:
            if not candidate:
                continue
            normalized = str(candidate).strip().lstrip("/")
            if not normalized:
                continue
            return FixityRecord(
                dump_key=normalized,
                storage_key=normalized,
                checksum_or_etag="sha256:stub",
                status="completed",
            )
        return None

    def fake_lookup(org_code, candidates):
        for candidate in candidates or []:
            if candidate:
                normalized = str(candidate).strip()
                if normalized:
                    return normalized
        return None

    def fake_resolver(org_code, *, path=None, file_name=None):
        candidate = path or file_name
        return [candidate] if candidate else []

    monkeypatch.setattr(dump_fixity_index, "find_fixity", fake_find_fixity)
    monkeypatch.setattr(s3_key_index, "lookup_dump_storage_key", fake_lookup)
    monkeypatch.setattr(path_mapping, "resolve_external_paths", fake_resolver)
    views.project_builder._path_resolver = fake_resolver


@pytest.fixture
def sample_graph_data():
    """Sample graph data for testing serializers."""
    return {
        "root_id": "https://test.example.com/resource/1",
        "nodes": {
            "https://test.example.com/resource/1": {
                "type": "Resource",
                "label": "Sample Resource",
                "uri": "https://test.example.com/resource/1"
            }
        },
        "edges": [
            {
                "subject_id": "https://test.example.com/resource/1",
                "predicate_canonical": "http://purl.org/dc/terms/title",
                "predicate_uri": "http://purl.org/dc/terms/title",
                "object_value": "Sample Resource Title",
                "object_id": None
            },
            {
                "subject_id": "https://test.example.com/resource/1",
                "predicate_canonical": "http://purl.org/dc/terms/creator",
                "predicate_uri": "http://purl.org/dc/terms/creator",
                "object_value": "Jane Doe",
                "object_id": None
            },
            {
                "subject_id": "https://test.example.com/resource/1",
                "predicate_canonical": "http://purl.org/dc/terms/creator",
                "predicate_uri": "http://purl.org/dc/terms/creator",
                "object_value": "John Smith",
                "object_id": None
            },
            {
                "subject_id": "https://test.example.com/resource/1",
                "predicate_canonical": "http://purl.org/dc/terms/subject",
                "predicate_uri": "http://purl.org/dc/terms/subject",
                "object_value": "Test Subject",
                "object_id": None
            }
        ]
    }


@pytest.fixture
def xml_validator():
    """XML validation utilities."""
    class XMLValidator:
        @staticmethod
        def _ensure_bytes(xml_content):
            if isinstance(xml_content, str):
                return xml_content.encode("utf-8")
            return xml_content

        @staticmethod
        def validate_oai_response(xml_content: str) -> bool:
            """Validate XML against basic OAI-PMH structure."""
            try:
                xml_bytes = XMLValidator._ensure_bytes(xml_content)
                root = ET.fromstring(xml_bytes)

                # Check root element - need to handle namespace
                if not (root.tag == "OAI-PMH" or root.tag.endswith("}OAI-PMH")):
                    return False

                # Check required child elements
                response_date = root.find("responseDate")
                request = root.find("request")

                # Handle namespaced elements
                if response_date is None:
                    response_date = root.find(".//{http://www.openarchives.org/OAI/2.0/}responseDate")
                if request is None:
                    request = root.find(".//{http://www.openarchives.org/OAI/2.0/}request")

                if response_date is None or request is None:
                    return False

                # Check for either a verb response or error
                verb_elements = ["Identify", "ListMetadataFormats", "ListSets",
                               "ListIdentifiers", "ListRecords", "GetRecord"]
                has_verb = False
                for verb in verb_elements:
                    if (root.find(verb) is not None or
                        root.find(f".//{{http://www.openarchives.org/OAI/2.0/}}{verb}") is not None):
                        has_verb = True
                        break

                has_error = (root.find("error") is not None or
                           root.find(".//{http://www.openarchives.org/OAI/2.0/}error") is not None)

                return has_verb or has_error

            except ET.ParseError:
                return False

        @staticmethod
        def extract_error(xml_content: str) -> tuple[str, str]:
            """Extract error code and message from OAI-PMH response."""
            try:
                xml_bytes = XMLValidator._ensure_bytes(xml_content)
                root = ET.fromstring(xml_bytes)
                error = root.find("error")
                if error is None:
                    error = root.find(".//{http://www.openarchives.org/OAI/2.0/}error")
                if error is not None:
                    return error.get("code", ""), error.text or ""
                return "", ""
            except ET.ParseError:
                return "", ""

        @staticmethod
        def count_records(xml_content: str) -> int:
            """Count records in ListIdentifiers or ListRecords response."""
            try:
                xml_bytes = XMLValidator._ensure_bytes(xml_content)
                root = ET.fromstring(xml_bytes)

                # Check ListIdentifiers
                list_identifiers = root.find("ListIdentifiers")
                if list_identifiers is None:
                    list_identifiers = root.find(".//{http://www.openarchives.org/OAI/2.0/}ListIdentifiers")
                if list_identifiers is not None:
                    headers = list_identifiers.findall("header")
                    if not headers:
                        headers = list_identifiers.findall(".//{http://www.openarchives.org/OAI/2.0/}header")
                    return len(headers)

                # Check ListRecords
                list_records = root.find("ListRecords")
                if list_records is None:
                    list_records = root.find(".//{http://www.openarchives.org/OAI/2.0/}ListRecords")
                if list_records is not None:
                    records = list_records.findall("record")
                    if not records:
                        records = list_records.findall(".//{http://www.openarchives.org/OAI/2.0/}record")
                    return len(records)

                return 0
            except ET.ParseError:
                return 0

        @staticmethod
        def get_resumption_token(xml_content: str) -> str:
            """Extract resumption token from response."""
            try:
                xml_bytes = XMLValidator._ensure_bytes(xml_content)
                root = ET.fromstring(xml_bytes)

                # Check in ListIdentifiers or ListRecords
                for verb in ["ListIdentifiers", "ListRecords"]:
                    verb_element = root.find(verb)
                    if verb_element is None:
                        verb_element = root.find(f".//{{http://www.openarchives.org/OAI/2.0/}}{verb}")
                    if verb_element is not None:
                        token_element = verb_element.find("resumptionToken")
                        if token_element is None:
                            token_element = verb_element.find(".//{http://www.openarchives.org/OAI/2.0/}resumptionToken")
                        if token_element is not None:
                            return token_element.text or ""

                return ""
            except ET.ParseError:
                return ""

    return XMLValidator()


@pytest.fixture
def large_dataset(db, sample_organizations):
    """Create a large dataset for pagination testing."""
    resources = []
    base_time = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    # Create 250 resources for pagination testing
    for i in range(250):
        resource = Resource.objects.create(
            uri=f"https://arkumu.org/entities/projekt/large/{i+1:03d}",
            organization=sample_organizations[0],
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True,
            updated_at=base_time.replace(second=i % 60, minute=(i // 60) % 60)
        )
        resources.append(resource)

        S3FileObject.objects.create(
            file_name=f"large-file-{i+1:03d}.bin",
            s3_key=f"test_univ/large/file-{i+1:03d}.bin",
            file_size_bytes=2048,
            content_type="application/octet-stream",
            related_resource=resource,
            status='completed'
        )

    return resources


# Utility functions for tests
def assert_valid_oai_identifier(identifier: str):
    """Assert that an identifier follows OAI format."""
    assert identifier.startswith("oai:arkumu:resource:")
    assert len(identifier) > len("oai:arkumu:resource:")


def assert_valid_datestamp(datestamp: str):
    """Assert that a datestamp follows OAI-PMH format."""
    try:
        # Should be in format YYYY-MM-DDThh:mm:ssZ
        datetime.fromisoformat(datestamp.replace('Z', '+00:00'))
    except ValueError:
        pytest.fail(f"Invalid datestamp format: {datestamp}")


def assert_xml_namespace(element: ET.Element, namespace: str):
    """Assert that an element has the correct namespace."""
    assert element.tag.startswith(f"{{{namespace}}}")


@pytest.fixture(autouse=True)
def cleanup_database(db):
    """Automatically clean up database after each test."""
    # Test runs here
    yield
    # Cleanup after test
    with transaction.atomic():
        # Clean up test data created during tests
        Resource.objects.filter(uri__startswith="https://test.example.com/").delete()
        Organization.objects.filter(code__startswith="test_").delete()
        User.objects.filter(username__startswith="test_").delete()
