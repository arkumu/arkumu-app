"""
Shared pytest fixtures for OAI-PMH tests.

Provides common test data, mock services, and utility functions.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET
from typing import Dict, Any, List

from django.test import Client, TransactionTestCase
from django.contrib.auth import get_user_model
from django.db import transaction
from django.core.cache import cache

from arkumu.users.models import Organization
from arkumu.metadata.models.resource import Resource, PublicAccessLevel
from arkumu.storage.models.s3_file_objects import S3FileObject

User = get_user_model()


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
            uri=f"https://test.example.com/resource/{i+1}",
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
        uri="https://research.example.com/item/1",
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
        def validate_oai_response(xml_content: str) -> bool:
            """Validate XML against basic OAI-PMH structure."""
            try:
                root = ET.fromstring(xml_content)

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
                root = ET.fromstring(xml_content)
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
                root = ET.fromstring(xml_content)

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
                root = ET.fromstring(xml_content)

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
            uri=f"https://test.example.com/large/{i+1:03d}",
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
