"""
Tests for ResourceTraversalService

Tests the graph traversal logic for finding parent project entities from literals.
"""

import pytest
from django.test import TestCase

from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.services.resource_traversal_service import ResourceTraversalService
from arkumu.users.models import Organization


class ResourceTraversalServiceTest(TestCase):
    """Test cases for ResourceTraversalService."""

    def setUp(self):
        """Set up test data."""
        self.traversal_service = ResourceTraversalService()

        # Create test organization
        self.org = Organization.objects.create(
            code='test',
            name='Test Organization',
            is_active=True
        )

        # Create a project entity (the target we want to link to)
        self.project_resource = Resource.objects.create(
            uri='https://test.example.com/entities/projekt/123',
            resource_type=ResourceType.ENTITY,
            organization=self.org,
            value='Test Project'
        )

        # Create a property resource for the relationship
        self.filename_property = Resource.objects.create(
            uri='https://test.example.com/properties/filename',
            resource_type=ResourceType.PROPERTY,
            organization=self.org,
            value='filename'
        )

        # Create a literal resource (what files are currently linked to)
        self.literal_resource = Resource.objects.create(
            uri=None,  # Literals don't have URIs
            resource_type=ResourceType.LITERAL,
            organization=None,  # Literals have no organization
            value='test_document.pdf'
        )

    def test_is_project_entity(self):
        """Test project entity detection."""
        # Should identify project entity
        self.assertTrue(self.traversal_service._is_project_entity(self.project_resource))

        # Should not identify literal as project entity
        self.assertFalse(self.traversal_service._is_project_entity(self.literal_resource))

        # Should not identify property as project entity
        self.assertFalse(self.traversal_service._is_project_entity(self.filename_property))

    def test_find_parent_project_from_literal_direct_link(self):
        """Test finding parent project when literal is directly linked to project."""
        # Create triple: project -> filename -> literal
        Triple.objects.create(
            subject=self.project_resource,
            predicate=self.filename_property,
            object=self.literal_resource,
            source=self.org
        )

        # Should find the project entity
        parent_project = self.traversal_service.find_parent_project_from_literal(self.literal_resource)
        self.assertEqual(parent_project, self.project_resource)

    def test_find_parent_project_from_literal_indirect_link(self):
        """Test finding parent project through intermediate entity."""
        # Create intermediate entity
        intermediate_resource = Resource.objects.create(
            uri='https://test.example.com/entities/document/456',
            resource_type=ResourceType.ENTITY,
            organization=self.org,
            value='Document Entity'
        )

        # Create property for intermediate relationship
        doc_property = Resource.objects.create(
            uri='https://test.example.com/properties/has-document',
            resource_type=ResourceType.PROPERTY,
            organization=self.org,
            value='has-document'
        )

        # Create triple chain: project -> has-document -> intermediate -> filename -> literal
        Triple.objects.create(
            subject=self.project_resource,
            predicate=doc_property,
            object=intermediate_resource,
            source=self.org
        )

        Triple.objects.create(
            subject=intermediate_resource,
            predicate=self.filename_property,
            object=self.literal_resource,
            source=self.org
        )

        # Should find the project entity through traversal
        parent_project = self.traversal_service.find_parent_project_from_literal(self.literal_resource)
        self.assertEqual(parent_project, self.project_resource)

    def test_get_project_entity_for_project_returns_self(self):
        """Test that project entities return themselves."""
        result = self.traversal_service.get_project_entity_for_resource(self.project_resource)
        self.assertEqual(result, self.project_resource)

    def test_get_project_entity_for_literal_traverses_graph(self):
        """Test that literals traverse to find parent project."""
        # Create triple: project -> filename -> literal
        Triple.objects.create(
            subject=self.project_resource,
            predicate=self.filename_property,
            object=self.literal_resource,
            source=self.org
        )

        result = self.traversal_service.get_project_entity_for_resource(self.literal_resource)
        self.assertEqual(result, self.project_resource)

    def test_no_parent_project_found(self):
        """Test case where no parent project can be found."""
        # Create orphaned literal with no incoming triples
        orphaned_literal = Resource.objects.create(
            uri=None,
            resource_type=ResourceType.LITERAL,
            organization=None,
            value='orphaned_file.pdf'
        )

        result = self.traversal_service.find_parent_project_from_literal(orphaned_literal)
        self.assertIsNone(result)

    def test_bulk_find_project_entities_for_literals(self):
        """Test bulk processing of multiple literals."""
        # Create additional literals
        literal2 = Resource.objects.create(
            uri=None,
            resource_type=ResourceType.LITERAL,
            organization=None,
            value='another_document.pdf'
        )

        orphaned_literal = Resource.objects.create(
            uri=None,
            resource_type=ResourceType.LITERAL,
            organization=None,
            value='orphaned_file.pdf'
        )

        # Link first two literals to the project
        Triple.objects.create(
            subject=self.project_resource,
            predicate=self.filename_property,
            object=self.literal_resource,
            source=self.org
        )

        filename_property2 = Resource.objects.create(
            uri='https://test.example.com/properties/filename2',
            resource_type=ResourceType.PROPERTY,
            organization=self.org,
            value='filename2'
        )

        Triple.objects.create(
            subject=self.project_resource,
            predicate=filename_property2,
            object=literal2,
            source=self.org
        )

        # Test bulk processing
        literals = [self.literal_resource, literal2, orphaned_literal]
        result = self.traversal_service.bulk_find_project_entities_for_literals(literals)

        # Should find project for first two literals
        self.assertEqual(result[self.literal_resource.id], self.project_resource)
        self.assertEqual(result[literal2.id], self.project_resource)

        # Should not find project for orphaned literal
        self.assertNotIn(orphaned_literal.id, result)