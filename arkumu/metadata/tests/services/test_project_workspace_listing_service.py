import pytest

from arkumu.metadata.canonical import canonical_uri
from arkumu.metadata.models.resource import PublicAccessLevel, Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.services.project_workspace_listing_service import (
    IS_PART_OF_URI,
    ProjectWorkspaceFilters,
    ProjectWorkspaceListingService,
)
from arkumu.users.models import Organization, User


@pytest.mark.django_db
def test_listing_service_annotates_counts_and_status():
    organization = Organization.objects.create(code="demo", name="Demo Org")
    manager = User.objects.create_user(
        "manager",
        password="pass",
        role="manager",
        organization=organization,
    )

    dataset = Resource.objects.create(
        uri="http://arkumu.org/data/demo/datasets/projekt",
        resource_type=ResourceType.IRI,
        name="Projekt",
        organization=organization,
    )
    is_part_of = Resource.objects.create(
        uri=IS_PART_OF_URI,
        resource_type=ResourceType.PROPERTY,
        name="isPartOf",
        organization=organization,
    )

    project = Resource.objects.create(
        uri="http://arkumu.org/data/demo/projects/1",
        resource_type=ResourceType.ENTITY,
        name="Testprojekt",
        organization=organization,
        public_access_level=PublicAccessLevel.RESTRICTED,
        is_public_approved=False,
    )
    Triple.objects.create(subject=project, predicate=is_part_of, object=dataset, source=organization)

    event_pred = Resource.objects.create(
        uri=canonical_uri("event"),
        resource_type=ResourceType.PROPERTY,
        name="event",
        organization=organization,
        canonical_uri=canonical_uri("event"),
    )
    event = Resource.objects.create(
        uri="http://arkumu.org/data/demo/events/1",
        resource_type=ResourceType.ENTITY,
        name="Event",
        organization=organization,
    )
    Triple.objects.create(subject=project, predicate=event_pred, object=event, source=organization)

    actor_pred = Resource.objects.create(
        uri=canonical_uri("actor_in_event"),
        resource_type=ResourceType.PROPERTY,
        name="actor in event",
        organization=organization,
        canonical_uri=canonical_uri("actor_in_event"),
    )
    actor = Resource.objects.create(
        uri="http://arkumu.org/data/demo/actors/1",
        resource_type=ResourceType.ENTITY,
        name="Actor",
        organization=organization,
    )
    Triple.objects.create(subject=event, predicate=actor_pred, object=actor, source=organization)

    digital_pred = Resource.objects.create(
        uri=canonical_uri("digital_object"),
        resource_type=ResourceType.PROPERTY,
        name="digital",
        organization=organization,
        canonical_uri=canonical_uri("digital_object"),
    )
    digital = Resource.objects.create(
        uri="http://arkumu.org/data/demo/media/1",
        resource_type=ResourceType.ENTITY,
        name="Media",
        organization=organization,
    )
    Triple.objects.create(subject=project, predicate=digital_pred, object=digital, source=organization)

    service = ProjectWorkspaceListingService(manager)
    queryset = service.get_queryset(ProjectWorkspaceFilters.from_query_params({}))
    row = queryset.get(id=project.id)
    service.populate_actor_counts([row])

    assert row.events_count == 1
    assert row.actors_count == 1
    assert row.digital_objects_count == 1
    assert row.status_code == "draft"
    assert row.status_label in {"Entwurf", "draft"}

    project.public_access_level = PublicAccessLevel.PUBLIC
    project.is_public_approved = True
    project.save(update_fields=["public_access_level", "is_public_approved"])

    queryset = service.get_queryset(ProjectWorkspaceFilters.from_query_params({}))
    row = queryset.get(id=project.id)
    assert row.status_code == "published"
    assert row.status_label in {"Veröffentlicht", "published"}


@pytest.mark.django_db
def test_filters_can_require_related_entities():
    organization = Organization.objects.create(code="demo", name="Demo Org")
    manager = User.objects.create_user(
        "manager2",
        password="pass",
        role="manager",
        organization=organization,
    )

    dataset = Resource.objects.create(
        uri="http://arkumu.org/data/demo/datasets/projekt",
        resource_type=ResourceType.IRI,
        name="Projekt",
        organization=organization,
    )
    is_part_of = Resource.objects.create(
        uri=IS_PART_OF_URI,
        resource_type=ResourceType.PROPERTY,
        name="isPartOf",
        organization=organization,
    )

    project_with_event = Resource.objects.create(
        uri="http://arkumu.org/data/demo/projects/with-event",
        resource_type=ResourceType.ENTITY,
        name="Mit Event",
        organization=organization,
        public_access_level=PublicAccessLevel.RESTRICTED,
    )
    Triple.objects.create(subject=project_with_event, predicate=is_part_of, object=dataset, source=organization)

    project_without_event = Resource.objects.create(
        uri="http://arkumu.org/data/demo/projects/without-event",
        resource_type=ResourceType.ENTITY,
        name="Ohne Event",
        organization=organization,
        public_access_level=PublicAccessLevel.RESTRICTED,
    )
    Triple.objects.create(subject=project_without_event, predicate=is_part_of, object=dataset, source=organization)

    event_pred = Resource.objects.create(
        uri=canonical_uri("event"),
        resource_type=ResourceType.PROPERTY,
        name="event",
        organization=organization,
        canonical_uri=canonical_uri("event"),
    )
    event = Resource.objects.create(
        uri="http://arkumu.org/data/demo/events/2",
        resource_type=ResourceType.ENTITY,
        name="Event",
        organization=organization,
    )
    Triple.objects.create(subject=project_with_event, predicate=event_pred, object=event, source=organization)

    service = ProjectWorkspaceListingService(manager)
    filters = ProjectWorkspaceFilters.from_query_params({"has_events": "true"})
    queryset = service.get_queryset(filters)
    ids = set(queryset.values_list("id", flat=True))
    assert project_with_event.id in ids
    assert project_without_event.id not in ids
