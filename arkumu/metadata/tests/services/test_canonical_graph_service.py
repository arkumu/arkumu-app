"""
Test Canonical Graph Service

Tests the canonical-aware graph retrieval service that enables cross-archive
discovery through canonical properties and literals while maintaining
institution-specific entity URIs.
"""

import uuid
from typing import Any, Dict

import pytest
from django.test import TestCase

from arkumu.metadata.models import Resource, ResourceType, Triple
from arkumu.metadata.services.canonical_graph_service import (
    CanonicalGraphService,
    GraphEdge,
)
from arkumu.users.models import Organization


@pytest.mark.django_db
class TestCanonicalGraphService(TestCase):
    """Test canonical graph service functionality."""

    def setUp(self):
        """Set up test data simulating FUK, RSH, and DET archives."""
        # Create organizations
        self.fuk = Organization.objects.create(name="Film University Konrad Wolf", code="fuk")
        self.rsh = Organization.objects.create(name="Robert Schumann Hochschule", code="rsh")
        self.det = Organization.objects.create(name="Deutsche Tanzfilminstitut", code="det")

        # Create RDF type predicate (shared across all)
        self.rdf_type = Resource.objects.create(
            uri="http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
            name="type",
            resource_type=ResourceType.PROPERTY,
            organization=None  # System-level predicate
        )

        # Create canonical class resources (shared types)
        self.projekt_class = Resource.objects.create(
            uri="http://arkumu.org/types/projekt",
            canonical_uri="http://arkumu.org/types/projekt",
            name="Projekt",
            resource_type=ResourceType.CLASS,
            organization=None  # Canonical, no org
        )

        self.digitales_objekt_class = Resource.objects.create(
            uri="http://arkumu.org/types/digitales_objekt",
            canonical_uri="http://arkumu.org/types/digitales_objekt",
            name="Digitales_Objekt",
            resource_type=ResourceType.CLASS,
            organization=None
        )

        # Create canonical property resources
        self.title_prop = Resource.objects.create(
            uri="http://arkumu.org/properties/title",
            canonical_uri="http://arkumu.org/properties/title",
            name="title",
            resource_type=ResourceType.PROPERTY,
            organization=None
        )

        self.beschreibung_prop = Resource.objects.create(
            uri="http://arkumu.org/properties/beschreibung",
            canonical_uri="http://arkumu.org/properties/beschreibung",
            name="beschreibung",
            resource_type=ResourceType.PROPERTY,
            organization=None
        )

        self.related_to_prop = Resource.objects.create(
            uri="http://arkumu.org/properties/related_to",
            canonical_uri="http://arkumu.org/properties/related_to",
            name="related_to",
            resource_type=ResourceType.PROPERTY,
            organization=None
        )

        # Create canonical literals (shared values)
        self.literal_project_alpha = Resource.objects.create(
            uri="http://arkumu.org/literals/project-alpha-string",
            name="Project Alpha",
            value="Project Alpha",
            resource_type=ResourceType.LITERAL,
            organization=None  # Literals have no org
        )

        self.literal_description = Resource.objects.create(
            uri="http://arkumu.org/literals/important-research-project",
            name="Important research project",
            value="Important research project about digital archives",
            resource_type=ResourceType.LITERAL,
            organization=None
        )

        self.literal_object_name = Resource.objects.create(
            uri="http://arkumu.org/literals/digital-asset-001",
            name="Digital Asset 001",
            value="Digital Asset 001",
            resource_type=ResourceType.LITERAL,
            organization=None
        )

        # Create FUK-specific entities
        self.fuk_projekt_1 = Resource.objects.create(
            uri="http://arkumu.org/fuk/projekt/123",
            name="FUK Projekt 123",
            resource_type=ResourceType.IRI,
            organization=self.fuk
        )

        self.fuk_projekt_2 = Resource.objects.create(
            uri="http://arkumu.org/fuk/projekt/456",
            name="FUK Projekt 456",
            resource_type=ResourceType.IRI,
            organization=self.fuk
        )

        self.fuk_digital_object = Resource.objects.create(
            uri="http://arkumu.org/fuk/digitales_objekt/789",
            name="FUK Digital Object 789",
            resource_type=ResourceType.IRI,
            organization=self.fuk
        )

        # Create RSH-specific entities (some share same literals)
        self.rsh_projekt_1 = Resource.objects.create(
            uri="http://arkumu.org/rsh/projekt/999",
            name="RSH Projekt 999",
            resource_type=ResourceType.IRI,
            organization=self.rsh
        )

        # Create triples for FUK projekt 1
        Triple.objects.create(
            subject=self.fuk_projekt_1,
            predicate=self.rdf_type,
            object=self.projekt_class
        )
        Triple.objects.create(
            subject=self.fuk_projekt_1,
            predicate=self.title_prop,
            object=self.literal_project_alpha
        )
        Triple.objects.create(
            subject=self.fuk_projekt_1,
            predicate=self.beschreibung_prop,
            object=self.literal_description
        )
        Triple.objects.create(
            subject=self.fuk_projekt_1,
            predicate=self.related_to_prop,
            object=self.fuk_digital_object
        )

        # Create triples for FUK projekt 2
        Triple.objects.create(
            subject=self.fuk_projekt_2,
            predicate=self.rdf_type,
            object=self.projekt_class
        )

        # Create triples for FUK digital object
        Triple.objects.create(
            subject=self.fuk_digital_object,
            predicate=self.rdf_type,
            object=self.digitales_objekt_class
        )
        Triple.objects.create(
            subject=self.fuk_digital_object,
            predicate=self.title_prop,
            object=self.literal_object_name
        )

        # Create triples for RSH projekt (shares literal with FUK)
        Triple.objects.create(
            subject=self.rsh_projekt_1,
            predicate=self.rdf_type,
            object=self.projekt_class
        )
        Triple.objects.create(
            subject=self.rsh_projekt_1,
            predicate=self.title_prop,
            object=self.literal_project_alpha  # Same literal as FUK projekt 1
        )

    def test_service_initialization(self):
        """Test service initialization with organization."""
        service = CanonicalGraphService(org_code="fuk")
        assert service.organization.code == "fuk"
        assert service.organization.name == "Film University Konrad Wolf"

    def test_find_subjects_by_canonical_class(self):
        """Test finding subjects by canonical class URI."""
        service = CanonicalGraphService(org_code="fuk")

        # Find FUK projects using canonical type
        subject_ids = service._find_subject_ids_by_class(
            canonical_type_uri="http://arkumu.org/types/projekt",
            restrict_to_org=True
        )

        assert len(subject_ids) == 2
        # Convert UUIDs to strings for comparison
        subject_ids_str = [str(sid) for sid in subject_ids]
        assert str(self.fuk_projekt_1.id) in subject_ids_str
        assert str(self.fuk_projekt_2.id) in subject_ids_str
        # RSH projekt should not be included (different org)
        assert str(self.rsh_projekt_1.id) not in subject_ids_str

    def test_fetch_triples_for_subjects(self):
        """Test fetching triples for given subjects."""
        service = CanonicalGraphService(org_code="fuk")

        edges = service._fetch_triples_for_subjects([str(self.fuk_projekt_1.id)])

        # Should get all triples for FUK projekt 1
        assert len(edges) == 4  # type, title, description, related_to

        # Check that canonical URIs are present
        title_edge = next(e for e in edges if e.predicate_uri == self.title_prop.uri)
        assert title_edge.predicate_canonical == "http://arkumu.org/properties/title"
        assert title_edge.object_uri == self.literal_project_alpha.uri
        assert title_edge.object_value == "Project Alpha"

    def test_fetch_triples_with_canonical_predicate_filter(self):
        """Test filtering triples by canonical predicate whitelist."""
        service = CanonicalGraphService(org_code="fuk")

        # Only fetch title and description predicates
        edges = service._fetch_triples_for_subjects(
            [str(self.fuk_projekt_1.id)],
            predicate_canon_whitelist=[
                "http://arkumu.org/properties/title",
                "http://arkumu.org/properties/beschreibung"
            ]
        )

        assert len(edges) == 2
        predicate_uris = {e.predicate_uri for e in edges}
        assert self.title_prop.uri in predicate_uris
        assert self.beschreibung_prop.uri in predicate_uris
        # Should not include rdf:type or related_to
        assert self.rdf_type.uri not in predicate_uris
        assert self.related_to_prop.uri not in predicate_uris

    def test_get_project_graph_basic(self):
        """Test basic project graph retrieval."""
        service = CanonicalGraphService(org_code="fuk")

        graph = service.get_project_graph(
            dataset_name="Projekt",
            type_canonical_uri="http://arkumu.org/types/projekt",
            expand_neighbors=False
        )

        assert graph["organization"] == "fuk"
        assert graph["dataset"] == "Projekt"
        assert graph["type_canonical_uri"] == "http://arkumu.org/types/projekt"
        assert len(graph["subjects"]) == 2
        assert graph["counts"]["subjects"] == 2

        # Check nodes include the subjects and their objects
        nodes = graph["nodes"]
        assert str(self.fuk_projekt_1.id) in nodes
        assert str(self.fuk_projekt_2.id) in nodes
        assert str(self.literal_project_alpha.id) in nodes

    def test_get_project_graph_with_neighbor_expansion(self):
        """Test project graph with neighbor expansion."""
        service = CanonicalGraphService(org_code="fuk")

        graph = service.get_project_graph(
            dataset_name="Projekt",
            type_canonical_uri="http://arkumu.org/types/projekt",
            expand_neighbors=True,
            neighbor_predicate_canon_whitelist=None  # None means fetch all predicates for neighbors
        )

        # Should include the digital object and its properties
        nodes = graph["nodes"]
        assert str(self.fuk_digital_object.id) in nodes
        assert str(self.literal_object_name.id) in nodes

        # Check that we have edges from the digital object
        edges = graph["edges"]
        digital_obj_edges = [e for e in edges if e["subject_id"] == str(self.fuk_digital_object.id)]
        assert len(digital_obj_edges) > 0

    def test_cross_archive_discovery_via_shared_literals(self):
        """Test that entities from different archives can be found via shared literals."""
        # This test demonstrates the key insight: we don't need entity canonicalization
        # because shared literals already enable cross-archive discovery

        # Find all entities that have the title "Project Alpha"
        triples_with_shared_literal = Triple.objects.filter(
            predicate=self.title_prop,
            object=self.literal_project_alpha
        ).select_related("subject")

        subjects = [t.subject for t in triples_with_shared_literal]
        org_codes = [s.organization.code for s in subjects if s.organization]

        # Both FUK and RSH projects share this literal
        assert "fuk" in org_codes
        assert "rsh" in org_codes
        assert self.fuk_projekt_1 in subjects
        assert self.rsh_projekt_1 in subjects

    def test_canonical_properties_enable_semantic_queries(self):
        """Test that canonical properties enable queries across archives."""
        # Find all entities with any title, regardless of organization
        title_triples = Triple.objects.filter(
            predicate__canonical_uri="http://arkumu.org/properties/title"
        ).select_related("subject", "object")

        # Should find titles from both FUK and RSH
        organizations = set()
        for triple in title_triples:
            if triple.subject.organization:
                organizations.add(triple.subject.organization.code)

        assert "fuk" in organizations
        assert "rsh" in organizations

    def test_collect_nodes_from_edges(self):
        """Test node collection from edges."""
        service = CanonicalGraphService(org_code="fuk")

        # Create sample edges
        edges = [
            GraphEdge(
                triple_id="t1",
                subject_id=str(self.fuk_projekt_1.id),
                predicate_uri=self.title_prop.uri,
                predicate_canonical=self.title_prop.canonical_uri,
                object_id=str(self.literal_project_alpha.id),
                object_uri=self.literal_project_alpha.uri,
                object_type=ResourceType.LITERAL,
                object_value=self.literal_project_alpha.value
            )
        ]

        nodes = service._collect_nodes_from_edges(edges)

        assert str(self.fuk_projekt_1.id) in nodes
        assert str(self.literal_project_alpha.id) in nodes

        # Check node structure
        projekt_node = nodes[str(self.fuk_projekt_1.id)]
        assert projekt_node["uri"] == self.fuk_projekt_1.uri
        assert projekt_node["organization"] == "fuk"

        literal_node = nodes[str(self.literal_project_alpha.id)]
        assert literal_node["value"] == "Project Alpha"
        assert literal_node["organization"] is None  # Literals have no org

    def test_fetch_junction_entities(self):
        """Test fetching junction entities (Kreuztabelle) pointing to target entities."""
        # Create junction type class
        junction_class = Resource.objects.create(
            uri="http://arkumu.org/data/types/akteurin-ereignis-kreuztabelle",
            canonical_uri="http://arkumu.org/data/types/akteurin-ereignis-kreuztabelle",
            name="Akteurin-Ereignis-Kreuztabelle",
            resource_type=ResourceType.CLASS,
            organization=None
        )

        # Create an event (target entity)
        event = Resource.objects.create(
            uri="http://arkumu.org/data/fuk/entities/ereignis/1",
            name="Event 1",
            resource_type=ResourceType.ENTITY,
            organization=self.fuk
        )

        # Create an actor
        actor = Resource.objects.create(
            uri="http://arkumu.org/data/fuk/entities/akteurin/1",
            name="Actor 1",
            resource_type=ResourceType.ENTITY,
            organization=self.fuk
        )

        # Create a junction entity
        junction = Resource.objects.create(
            uri="http://arkumu.org/data/fuk/entities/junction/1",
            name="Junction 1",
            resource_type=ResourceType.ENTITY,
            organization=self.fuk
        )

        # Create predicates
        akteurin_prop = Resource.objects.create(
            uri="http://arkumu.org/data/properties/akteurin",
            canonical_uri="http://arkumu.org/data/properties/akteurin",
            name="akteurin",
            resource_type=ResourceType.PROPERTY,
            organization=None
        )
        im_ereignis_prop = Resource.objects.create(
            uri="http://arkumu.org/data/properties/im-ereignis",
            canonical_uri="http://arkumu.org/data/properties/im-ereignis",
            name="im-ereignis",
            resource_type=ResourceType.PROPERTY,
            organization=None
        )
        ist_urheberin_prop = Resource.objects.create(
            uri="http://arkumu.org/data/properties/ist-urheberin",
            canonical_uri="http://arkumu.org/data/properties/ist-urheberin",
            name="ist-urheberin",
            resource_type=ResourceType.PROPERTY,
            organization=None
        )
        urheber_literal = Resource.objects.create(
            uri="http://arkumu.org/literals/true",
            value="true",
            resource_type=ResourceType.LITERAL,
            organization=None
        )

        # Create triples: junction -> event, junction -> actor, junction -> property
        Triple.objects.create(
            subject=junction,
            predicate=self.rdf_type,
            object=junction_class,
            source=self.fuk
        )
        Triple.objects.create(
            subject=junction,
            predicate=im_ereignis_prop,
            object=event,
            source=self.fuk
        )
        Triple.objects.create(
            subject=junction,
            predicate=akteurin_prop,
            object=actor,
            source=self.fuk
        )
        Triple.objects.create(
            subject=junction,
            predicate=ist_urheberin_prop,
            object=urheber_literal,
            source=self.fuk
        )

        service = CanonicalGraphService(org_code="fuk")

        # Fetch junction entities pointing to the event
        edges = service.fetch_junction_entities([str(event.id)])

        # Should find 4 edges (type, im-ereignis, akteurin, ist-urheberin)
        assert len(edges) == 4

        # Check that the junction entity is the subject of all edges
        for edge in edges:
            assert edge.subject_id == str(junction.id)

        # Check we have edges to actor, event, and literal
        object_ids = {edge.object_id for edge in edges}
        assert str(event.id) in object_ids
        assert str(actor.id) in object_ids
        assert str(urheber_literal.id) in object_ids

    def test_fetch_junction_entities_empty_targets(self):
        """Test fetch_junction_entities with empty target list returns empty."""
        service = CanonicalGraphService(org_code="fuk")
        edges = service.fetch_junction_entities([])
        assert edges == []

    def test_fetch_junction_entities_no_junctions(self):
        """Test fetch_junction_entities when no junctions point to targets."""
        service = CanonicalGraphService(org_code="fuk")
        # Use an ID that has no junctions pointing to it
        edges = service.fetch_junction_entities([str(self.fuk_projekt_1.id)])
        assert edges == []