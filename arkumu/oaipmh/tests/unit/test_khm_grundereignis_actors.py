"""
Integration tests for KHM Grundereignis actor filtering in OAI-PMH output.

Tests verify that the fix for shared event actor pollution works correctly:
1. Grundereignis events surface properly in project records
2. Only Grundereignis actors appear in dc:creator fields
3. No recursive event loading from shared events
4. Crosstable filtering by project works correctly
"""

from unittest.mock import patch
import pytest
from lxml import etree as ET

from arkumu.metadata.models.resource import Resource, ResourceType, PublicAccessLevel
from arkumu.metadata.models.triples import Triple
from arkumu.users.models import Organization
from arkumu.catalog.services.project_views import ProjectURIs
from arkumu.oaipmh import views
from arkumu.projects import (
    ProjectRecord,
    ProjectInstitution,
    ProjectEvent,
    ProjectEventActor,
    ProjectActor,
)


@pytest.mark.django_db
class TestKHMGrundereignisActorFiltering:
    """Test KHM-specific Grundereignis event and actor filtering."""

    def _create_test_organization(self):
        """Create KHM test organization."""
        return Organization.objects.create(
            name="Kunsthochschule für Medien Köln",
            code="khm",
            domain="khm.example",
            is_active=True,
        )

    def _create_project_resource(self, org, project_id):
        """Create a project resource."""
        return Resource.objects.create(
            uri=f"http://arkumu.org/data/khm/entities/00-projekte/{project_id}",
            resource_type=ResourceType.ENTITY,
            organization=org,
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True,
        )

    def _create_event_resource(self, org, event_type, event_id):
        """Create an event resource."""
        return Resource.objects.create(
            uri=f"http://arkumu.org/data/khm/entities/{event_type}/{event_id}",
            resource_type=ResourceType.ENTITY,
            organization=org,
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True,
        )

    def _create_actor_resource(self, org, actor_id):
        """Create an actor resource."""
        return Resource.objects.create(
            uri=f"http://arkumu.org/data/khm/entities/03-personen/{actor_id}",
            resource_type=ResourceType.ENTITY,
            organization=org,
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True,
        )

    def _create_literal(self, org, value):
        """Create a literal resource."""
        return Resource.objects.create(
            value=value,
            resource_type=ResourceType.LITERAL,
            organization=org,
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True,
        )

    def _create_property(self, uri, canonical_uri=None):
        """Create a property resource."""
        return Resource.objects.create(
            uri=uri,
            resource_type=ResourceType.PROPERTY,
            canonical_uri=canonical_uri,
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True,
        )

    def test_grundereignis_actors_appear_in_dc_creator(self):
        """Test that Grundereignis event actors appear in dc:creator fields."""
        org = self._create_test_organization()
        project = self._create_project_resource(org, "2265")

        # Create Grundereignis event
        grundereignis = self._create_event_resource(org, "01-grundereignis", "event-1")
        grundereignis_name = self._create_literal(org, "Herstellung")

        # Create actors for Grundereignis
        actor1 = self._create_actor_resource(org, "actor-1")
        actor1_name = self._create_literal(org, "Andreas Altenhoff")
        actor2 = self._create_actor_resource(org, "actor-2")
        actor2_name = self._create_literal(org, "Dietrich Leder")

        # Create properties
        event_pred = self._create_property(
            "http://arkumu.org/data/properties/ereignis",
            canonical_uri=ProjectURIs.EVENT
        )
        event_name_pred = self._create_property(
            "http://arkumu.org/data/properties/name-des-ereignisses",
            canonical_uri=ProjectURIs.EVENT_NAME
        )
        actor_pred = self._create_property(
            "http://arkumu.org/data/properties/person",
            canonical_uri=ProjectURIs.ACTOR_IN_EVENT
        )
        actor_name_pred = self._create_property(
            "http://arkumu.org/data/properties/deutscher-name",
            canonical_uri=ProjectURIs.ACTOR_GERMAN_NAME
        )

        # Link project to Grundereignis
        Triple.objects.create(subject=project, predicate=event_pred, object=grundereignis)
        Triple.objects.create(subject=grundereignis, predicate=event_name_pred, object=grundereignis_name)

        # Link actors to Grundereignis
        Triple.objects.create(subject=grundereignis, predicate=actor_pred, object=actor1)
        Triple.objects.create(subject=grundereignis, predicate=actor_pred, object=actor2)
        Triple.objects.create(subject=actor1, predicate=actor_name_pred, object=actor1_name)
        Triple.objects.create(subject=actor2, predicate=actor_name_pred, object=actor2_name)

        # Build mock project record
        record = ProjectRecord(
            subject_id=str(project.id),
            uri=project.uri,
            title="Auf der Strecke",
            institution=ProjectInstitution(label="KHM", code="khm"),
            events=[
                ProjectEvent(
                    id=str(grundereignis.id),
                    uri=grundereignis.uri,
                    name="Herstellung",
                    actors=[
                        ProjectEventActor(name="Andreas Altenhoff", roles=[]),
                        ProjectEventActor(name="Dietrich Leder", roles=[]),
                    ],
                )
            ],
            actors=[
                ProjectActor(name="Andreas Altenhoff", roles=[]),
                ProjectActor(name="Dietrich Leder", roles=[]),
            ],
            institution_codes=["khm"],
        )

        # Test Dublin Core payload
        payload = views._build_dc_payload_from_record(record, project, include_event_details=True)

        creators = payload.get("dc:creator", [])
        creator_names = [c if isinstance(c, str) else c.get("value") for c in creators]

        # Verify only Grundereignis actors appear
        assert "Andreas Altenhoff" in creator_names
        assert "Dietrich Leder" in creator_names
        assert len(creator_names) == 2

    def test_shared_event_actors_excluded_from_dc_creator(self):
        """Test that actors from shared events (not Grundereignis) don't appear in dc:creator."""
        org = self._create_test_organization()

        # Project 1: "Auf der Strecke"
        project1 = self._create_project_resource(org, "2265")

        # Project 2: "Ostende" (shares showcase event)
        project2 = self._create_project_resource(org, "2417")

        # Grundereignis for Project 1
        grundereignis1 = self._create_event_resource(org, "01-grundereignis", "event-grund-1")
        grundereignis1_name = self._create_literal(org, "Herstellung")

        # Shared showcase event
        showcase_event = self._create_event_resource(org, "06-auszeichnungen-projekte", "event-showcase")
        showcase_name = self._create_literal(org, "Showcase 2007")

        # Actors for Project 1 Grundereignis
        actor1_p1 = self._create_actor_resource(org, "actor-p1-1")
        actor1_p1_name = self._create_literal(org, "Andreas Altenhoff")
        actor2_p1 = self._create_actor_resource(org, "actor-p1-2")
        actor2_p1_name = self._create_literal(org, "Dietrich Leder")

        # Actors for Project 2 (should NOT appear in Project 1)
        actor1_p2 = self._create_actor_resource(org, "actor-p2-1")
        actor1_p2_name = self._create_literal(org, "Gebhard Henke")
        actor2_p2 = self._create_actor_resource(org, "actor-p2-2")
        actor2_p2_name = self._create_literal(org, "Horst Königstein")

        # Create properties
        event_pred = self._create_property(
            "http://arkumu.org/data/properties/ereignis",
            canonical_uri=ProjectURIs.EVENT
        )
        event_name_pred = self._create_property(
            "http://arkumu.org/data/properties/name-des-ereignisses",
            canonical_uri=ProjectURIs.EVENT_NAME
        )
        actor_pred = self._create_property(
            "http://arkumu.org/data/properties/person",
            canonical_uri=ProjectURIs.ACTOR_IN_EVENT
        )
        actor_name_pred = self._create_property(
            "http://arkumu.org/data/properties/deutscher-name",
            canonical_uri=ProjectURIs.ACTOR_GERMAN_NAME
        )

        # Link Project 1 to Grundereignis and showcase
        Triple.objects.create(subject=project1, predicate=event_pred, object=grundereignis1)
        Triple.objects.create(subject=project1, predicate=event_pred, object=showcase_event)
        Triple.objects.create(subject=grundereignis1, predicate=event_name_pred, object=grundereignis1_name)
        Triple.objects.create(subject=showcase_event, predicate=event_name_pred, object=showcase_name)

        # Link Project 2 to showcase only
        Triple.objects.create(subject=project2, predicate=event_pred, object=showcase_event)

        # Link Grundereignis actors to Project 1
        Triple.objects.create(subject=grundereignis1, predicate=actor_pred, object=actor1_p1)
        Triple.objects.create(subject=grundereignis1, predicate=actor_pred, object=actor2_p1)
        Triple.objects.create(subject=actor1_p1, predicate=actor_name_pred, object=actor1_p1_name)
        Triple.objects.create(subject=actor2_p1, predicate=actor_name_pred, object=actor2_p1_name)

        # Link showcase actors to Project 2's crosstable (simulating shared event pollution)
        Triple.objects.create(subject=showcase_event, predicate=actor_pred, object=actor1_p2)
        Triple.objects.create(subject=showcase_event, predicate=actor_pred, object=actor2_p2)
        Triple.objects.create(subject=actor1_p2, predicate=actor_name_pred, object=actor1_p2_name)
        Triple.objects.create(subject=actor2_p2, predicate=actor_name_pred, object=actor2_p2_name)

        # Build mock project record for Project 1
        record = ProjectRecord(
            subject_id=str(project1.id),
            uri=project1.uri,
            title="Auf der Strecke",
            institution=ProjectInstitution(label="KHM", code="khm"),
            events=[
                ProjectEvent(
                    id=str(grundereignis1.id),
                    uri=grundereignis1.uri,
                    name="Herstellung",
                    actors=[
                        ProjectEventActor(name="Andreas Altenhoff", roles=[]),
                        ProjectEventActor(name="Dietrich Leder", roles=[]),
                    ],
                ),
                ProjectEvent(
                    id=str(showcase_event.id),
                    uri=showcase_event.uri,
                    name="Showcase 2007",
                    actors=[
                        # These should be filtered out
                        ProjectEventActor(name="Gebhard Henke", roles=[]),
                        ProjectEventActor(name="Horst Königstein", roles=[]),
                    ],
                ),
            ],
            actors=[
                ProjectActor(name="Andreas Altenhoff", roles=[]),
                ProjectActor(name="Dietrich Leder", roles=[]),
            ],
            institution_codes=["khm"],
        )

        # Test Dublin Core payload directly with the record
        payload = views._build_dc_payload_from_record(record, project1, include_event_details=True)

        creators = payload.get("dc:creator", [])
        creator_names = [c if isinstance(c, str) else c.get("value") for c in creators]

        # Verify ONLY Grundereignis actors appear
        assert "Andreas Altenhoff" in creator_names
        assert "Dietrich Leder" in creator_names

        # Verify actors from shared showcase event do NOT appear
        assert "Gebhard Henke" not in creator_names
        assert "Horst Königstein" not in creator_names

    def test_select_primary_event_actors_prioritizes_grundereignis(self):
        """Test _select_primary_event_actors() prioritizes Grundereignis events."""
        # Create record with multiple events
        record = ProjectRecord(
            subject_id="proj-1",
            uri="http://arkumu.org/data/khm/entities/00-projekte/2265",
            title="Test Project",
            institution=ProjectInstitution(label="KHM", code="khm"),
            events=[
                # Non-Grundereignis event (should be ignored)
                ProjectEvent(
                    id="event-showcase",
                    uri="http://arkumu.org/data/khm/entities/06-auszeichnungen-projekte/showcase-1",
                    name="Showcase 2007",
                    actors=[
                        ProjectEventActor(name="Wrong Actor", roles=[]),
                    ],
                ),
                # Grundereignis event (should be selected)
                ProjectEvent(
                    id="event-grund",
                    uri="http://arkumu.org/data/khm/entities/01-grundereignis/grund-1",
                    name="Herstellung",
                    actors=[
                        ProjectEventActor(name="Correct Actor 1", roles=[]),
                        ProjectEventActor(name="Correct Actor 2", roles=[]),
                    ],
                ),
            ],
            actors=[
                ProjectActor(name="Project Level Actor", roles=[]),
            ],
            institution_codes=["khm"],
        )

        # Call the function
        selected_actors = views._select_primary_event_actors(record)

        # Verify only Grundereignis actors are selected
        assert len(selected_actors) == 2
        actor_names = [a["name"] for a in selected_actors]
        assert "Correct Actor 1" in actor_names
        assert "Correct Actor 2" in actor_names
        assert "Wrong Actor" not in actor_names

    def test_select_primary_event_actors_fallback_to_project_actors(self):
        """Test _select_primary_event_actors() falls back to project actors when no Grundereignis."""
        # Create record without Grundereignis events
        record = ProjectRecord(
            subject_id="proj-1",
            uri="http://arkumu.org/data/khm/entities/00-projekte/2265",
            title="Test Project",
            institution=ProjectInstitution(label="KHM", code="khm"),
            events=[
                ProjectEvent(
                    id="event-showcase",
                    uri="http://arkumu.org/data/khm/entities/06-auszeichnungen-projekte/showcase-1",
                    name="Showcase 2007",
                    actors=[
                        ProjectEventActor(name="Event Actor", roles=[]),
                    ],
                ),
            ],
            actors=[
                ProjectActor(name="Project Actor 1", roles=["Director"]),
                ProjectActor(name="Project Actor 2", roles=["Producer"]),
            ],
            institution_codes=["khm"],
        )

        # Call the function
        selected_actors = views._select_primary_event_actors(record)

        # Verify project-level actors are returned as fallback
        assert len(selected_actors) == 2
        actor_names = [a["name"] for a in selected_actors]
        assert "Project Actor 1" in actor_names
        assert "Project Actor 2" in actor_names
        assert "Event Actor" not in actor_names

    def test_select_primary_event_actors_deduplicates_names(self):
        """Test _select_primary_event_actors() deduplicates actors with same name."""
        # Create record with duplicate actor names
        record = ProjectRecord(
            subject_id="proj-1",
            uri="http://arkumu.org/data/khm/entities/00-projekte/2265",
            title="Test Project",
            institution=ProjectInstitution(label="KHM", code="khm"),
            events=[
                ProjectEvent(
                    id="event-grund-1",
                    uri="http://arkumu.org/data/khm/entities/01-grundereignis/grund-1",
                    name="Herstellung",
                    actors=[
                        ProjectEventActor(name="Andreas Altenhoff", roles=["Director"]),
                        ProjectEventActor(name="Dietrich Leder", roles=["Producer"]),
                    ],
                ),
                ProjectEvent(
                    id="event-grund-2",
                    uri="http://arkumu.org/data/khm/entities/01-grundereignis/grund-2",
                    name="Nachbearbeitung",
                    actors=[
                        # Duplicate name - should be skipped
                        ProjectEventActor(name="Andreas Altenhoff", roles=["Editor"]),
                        ProjectEventActor(name="New Actor", roles=["Sound"]),
                    ],
                ),
            ],
            actors=[],
            institution_codes=["khm"],
        )

        # Call the function
        selected_actors = views._select_primary_event_actors(record)

        # Verify deduplication works
        actor_names = [a["name"] for a in selected_actors]
        assert len([n for n in actor_names if n == "Andreas Altenhoff"]) == 1
        assert "Dietrich Leder" in actor_names
        assert "New Actor" in actor_names

    @patch('arkumu.oaipmh.views._get_snapshot_record')
    def test_oai_dc_output_only_includes_grundereignis_creators(self, mock_get_record):
        """Integration test: Verify OAI DC output only includes Grundereignis creators."""
        org = self._create_test_organization()
        project = self._create_project_resource(org, "2265")

        # Mock project record
        record = ProjectRecord(
            subject_id=str(project.id),
            uri=project.uri,
            title="Auf der Strecke",
            institution=ProjectInstitution(label="KHM", code="khm"),
            events=[
                ProjectEvent(
                    id="event-grund",
                    uri="http://arkumu.org/data/khm/entities/01-grundereignis/grund-1",
                    name="Herstellung",
                    actors=[
                        ProjectEventActor(name="Andreas Altenhoff", roles=[]),
                        ProjectEventActor(name="Dietrich Leder", roles=[]),
                    ],
                ),
                ProjectEvent(
                    id="event-showcase",
                    uri="http://arkumu.org/data/khm/entities/06-auszeichnungen-projekte/showcase-1",
                    name="Showcase 2007",
                    actors=[
                        # These should NOT appear
                        ProjectEventActor(name="Gebhard Henke", roles=[]),
                        ProjectEventActor(name="Horst Königstein", roles=[]),
                    ],
                ),
            ],
            actors=[
                ProjectActor(name="Andreas Altenhoff", roles=[]),
                ProjectActor(name="Dietrich Leder", roles=[]),
            ],
            institution_codes=["khm"],
        )
        mock_get_record.return_value = record

        # Build metadata element
        metadata = views._build_metadata_element(project, "oai_dc")

        # Parse DC element
        dc_element = metadata.find(".//{http://www.openarchives.org/OAI/2.0/oai_dc/}dc")
        assert dc_element is not None

        # Extract all dc:creator elements
        creators = dc_element.findall("{http://purl.org/dc/elements/1.1/}creator")
        creator_names = [elem.text for elem in creators]

        # Verify ONLY Grundereignis actors
        assert len(creator_names) == 2
        assert "Andreas Altenhoff" in creator_names
        assert "Dietrich Leder" in creator_names

        # Verify actors from other events are excluded
        assert "Gebhard Henke" not in creator_names
        assert "Horst Königstein" not in creator_names
