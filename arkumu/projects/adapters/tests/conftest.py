"""Shared fixtures for adapter tests."""

import uuid
from typing import Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from arkumu.projects.adapters import (
    ActorData,
    EventData,
    DigitalObjectData,
    ProjectPropertiesData,
    ProjectGraph,
)


@pytest.fixture
def mock_uuid():
    """Generate a test UUID."""
    return uuid.uuid4()


@pytest.fixture
def mock_project_uuid():
    """Fixed UUID for testing."""
    return uuid.UUID("12345678-1234-5678-1234-567812345678")


@pytest.fixture
def mock_event_uuid():
    """Fixed event UUID for testing."""
    return uuid.UUID("87654321-4321-8765-4321-876543218765")


@pytest.fixture
def mock_actor_uuid():
    """Fixed actor UUID for testing."""
    return uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


@pytest.fixture
def mock_digital_object_uuid():
    """Fixed digital object UUID for testing."""
    return uuid.UUID("dddddddd-oooo-1111-2222-333333333333")


@pytest.fixture
def sample_actor_data():
    """Sample ActorData for testing."""
    return ActorData(
        actor_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        actor_name="Test Actor",
        event_id="87654321-4321-8765-4321-876543218765",
        roles=["Director", "Producer"],
        is_copyright_holder=True,
        is_neighbouring_rights_holder=False,
    )


@pytest.fixture
def sample_event_data(sample_actor_data):
    """Sample EventData for testing."""
    return EventData(
        event_id="87654321-4321-8765-4321-876543218765",
        event_uri="http://arkumu.org/data/fuk/01-ereignisse/test-event",
        name="Test Event",
        description="A test event",
        location="Test Location",
        start="2020-01-01",
        end="2020-12-31",
        event_type="Produktion",
        actors=[sample_actor_data],
    )


@pytest.fixture
def sample_digital_object_data():
    """Sample DigitalObjectData for testing."""
    return DigitalObjectData(
        object_id="dddddddd-oooo-1111-2222-333333333333",
        object_uri="http://arkumu.org/data/fuk/digitale-objekte/test.mp4",
        path="path/to/test.mp4",
        file_name="test.mp4",
        content_type="video/mp4",
        source_event_ids=["87654321-4321-8765-4321-876543218765"],
    )


@pytest.fixture
def sample_project_properties():
    """Sample ProjectPropertiesData for testing."""
    return ProjectPropertiesData(
        title="Test Project",
        subtitle="A subtitle",
        description="Test description",
        image="path/to/image.jpg",
        institution_uri="http://arkumu.org/data/fuk",
        institution_label="FUK",
        category_uris=["http://arkumu.org/data/categories/film"],
        category_labels=["Film"],
    )


@pytest.fixture
def sample_project_graph(
    sample_project_properties,
    sample_event_data,
    sample_actor_data,
    sample_digital_object_data,
):
    """Sample ProjectGraph for testing."""
    return ProjectGraph(
        project_uri="http://arkumu.org/data/fuk/00-projekte/test-project",
        properties=sample_project_properties,
        events=[sample_event_data],
        actors=[sample_actor_data],
        digital_objects=[sample_digital_object_data],
        triples=[],
    )


class MockResource:
    """Mock Resource model for testing."""

    def __init__(
        self,
        id: uuid.UUID,
        uri: str,
        resource_type: str = "ENTITY",
        value: Optional[str] = None,
        organization_code: str = "fuk",
        entity_type_uri: Optional[str] = None,
    ):
        self.id = id
        self.uri = uri
        self.resource_type = resource_type
        self.value = value
        self.organization = MagicMock()
        self.organization.code = organization_code
        self.entity_type = MagicMock() if entity_type_uri else None
        if self.entity_type:
            self.entity_type.uri = entity_type_uri


class MockPredicate:
    """Mock Predicate model for testing."""

    def __init__(
        self,
        uri: str,
        canonical_uri: Optional[str] = None,
    ):
        self.uri = uri
        self.canonical_uri = canonical_uri


class MockTriple:
    """Mock Triple model for testing."""

    def __init__(
        self,
        subject: MockResource,
        predicate: MockPredicate,
        obj: MockResource,
    ):
        self.subject = subject
        self.subject_id = subject.id
        self.predicate = predicate
        self.object = obj
        self.object_id = obj.id
