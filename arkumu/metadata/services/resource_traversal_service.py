"""
Resource Traversal Service

Service for traversing graph relationships to find parent entities,
specifically for linking S3FileObjects to project entities instead of literals.
"""

from typing import Optional, List
import logging
from django.db.models import Q

from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple

logger = logging.getLogger(__name__)


class ResourceTraversalService:
    """Service for traversing resource relationships via Triple graph."""

    def find_parent_project_from_literal(self, literal_resource: Resource) -> Optional[Resource]:
        """
        Find the parent project entity that a literal resource is connected to.

        Args:
            literal_resource: The literal resource to traverse from

        Returns:
            Resource: The parent project entity with organization context, or None if not found
        """
        if not literal_resource or literal_resource.resource_type != ResourceType.LITERAL:
            logger.warning(f"Resource {literal_resource} is not a literal, cannot traverse to parent project")
            return None

        # Find all triples where this literal is the object
        incoming_triples = Triple.objects.filter(
            object=literal_resource
        ).select_related('subject', 'subject__organization')

        for triple in incoming_triples:
            subject = triple.subject

            # Check if the subject is a project entity
            if self._is_project_entity(subject):
                logger.info(f"Found parent project {subject.uri} for literal {literal_resource.value}")
                return subject

            # If subject is not a project, recursively traverse up
            # (but only for non-literal subjects to avoid infinite loops)
            if subject.resource_type != ResourceType.LITERAL:
                parent_project = self._traverse_to_project_recursive(subject, visited={literal_resource.id})
                if parent_project:
                    logger.info(f"Found parent project {parent_project.uri} via recursive traversal from literal {literal_resource.value}")
                    return parent_project

        logger.warning(f"No parent project found for literal resource {literal_resource.value}")
        return None

    def _is_project_entity(self, resource: Resource) -> bool:
        """
        Check if a resource is a project entity.
        Project entities have URIs matching the pattern '/entities/projekt/[0-9]+$'
        """
        if not resource or not resource.uri:
            return False

        import re
        return bool(re.search(r'/entities/projekt/[0-9]+$', resource.uri))

    def _traverse_to_project_recursive(self, resource: Resource, visited: set, max_depth: int = 3) -> Optional[Resource]:
        """
        Recursively traverse up the graph to find a project entity.

        Args:
            resource: Current resource to traverse from
            visited: Set of resource IDs already visited (to prevent cycles)
            max_depth: Maximum traversal depth to prevent infinite recursion

        Returns:
            Resource: The parent project entity, or None if not found
        """
        if max_depth <= 0:
            return None

        if resource.id in visited:
            return None  # Cycle detected

        visited.add(resource.id)

        # Check if current resource is a project
        if self._is_project_entity(resource):
            return resource

        # Find incoming triples (resources that point to this resource)
        incoming_triples = Triple.objects.filter(
            object=resource
        ).select_related('subject', 'subject__organization')

        for triple in incoming_triples:
            subject = triple.subject

            # Skip literals and already visited resources
            if (subject.resource_type == ResourceType.LITERAL or
                subject.id in visited):
                continue

            # Check if this subject is a project
            if self._is_project_entity(subject):
                return subject

            # Recursively traverse from this subject
            parent_project = self._traverse_to_project_recursive(
                subject, visited.copy(), max_depth - 1
            )
            if parent_project:
                return parent_project

        return None

    def get_project_entity_for_resource(self, resource: Resource) -> Optional[Resource]:
        """
        Get the project entity associated with any resource.

        For project entities: returns the resource itself
        For literals: traverses to find parent project
        For other entities: traverses to find parent project

        Args:
            resource: The resource to find project entity for

        Returns:
            Resource: The project entity with organization context, or None
        """
        if not resource:
            return None

        # If it's already a project entity, return it
        if self._is_project_entity(resource):
            return resource

        # If it's a literal, use the literal-specific traversal
        if resource.resource_type == ResourceType.LITERAL:
            return self.find_parent_project_from_literal(resource)

        # For other resource types, use recursive traversal
        return self._traverse_to_project_recursive(resource, set())

    def bulk_find_project_entities_for_literals(self, literal_resources: List[Resource]) -> dict:
        """
        Efficiently find parent project entities for multiple literal resources.

        Args:
            literal_resources: List of literal resources

        Returns:
            dict: Mapping of literal resource ID to parent project resource
        """
        result = {}

        if not literal_resources:
            return result

        literal_ids = [r.id for r in literal_resources if r.resource_type == ResourceType.LITERAL]

        if not literal_ids:
            return result

        # Get all incoming triples for these literals in one query
        incoming_triples = Triple.objects.filter(
            object_id__in=literal_ids
        ).select_related('subject', 'subject__organization', 'object')

        # Group triples by object (literal) ID
        triples_by_literal = {}
        for triple in incoming_triples:
            literal_id = triple.object.id
            if literal_id not in triples_by_literal:
                triples_by_literal[literal_id] = []
            triples_by_literal[literal_id].append(triple)

        # Process each literal
        for literal_resource in literal_resources:
            if literal_resource.resource_type != ResourceType.LITERAL:
                continue

            triples = triples_by_literal.get(literal_resource.id, [])

            # Look for direct project entity connections first
            for triple in triples:
                if self._is_project_entity(triple.subject):
                    result[literal_resource.id] = triple.subject
                    break
            else:
                # If no direct project found, try recursive traversal
                project = self.find_parent_project_from_literal(literal_resource)
                if project:
                    result[literal_resource.id] = project

        return result