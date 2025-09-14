"""
Property-Based Graph Search Service

Replaces faceted search with graph-based exploration starting from property searches.
"""

from typing import Dict, List, Optional, Any, Set
import logging
from django.db.models import Q
from arkumu.metadata.models import Resource, Triple, ResourceType

logger = logging.getLogger(__name__)


class GraphSearchService:
    """
    Property-based search with complete graph retrieval.

    Allows searching for specific property values and returns the complete
    connected data graph for matching entities.
    """

    def __init__(self, user=None):
        self.user = user

    def search_by_property_with_graph(self,
                                    query: str,
                                    property_name: str = 'title',
                                    resource_type: str = None,
                                    limit: int = 50) -> List[Dict]:
        """
        Search for entities by property value and return complete graphs.

        Args:
            query: Search term to find in property values
            property_name: Property to search in (e.g., 'title', 'name', 'description')
            resource_type: Optional entity type filter (e.g., 'project', 'person')
            limit: Maximum number of results

        Returns:
            List of entity graphs with complete connected data
        """
        if not query.strip():
            return []

        logger.info(f"Graph search: '{query}' in property '{property_name}'")

        # Handle both canonical and full property URIs
        property_uris = [
            f"http://arkumu.org/data/properties/{property_name.replace('_', '-')}",
            f"http://arkumu.org/data/fuk/properties/{property_name.replace('_', '-')}",
        ]

        # Find triples: subject -[property]-> literal_containing_query
        matching_triples_query = Triple.objects.filter(
            predicate__uri__in=property_uris,
            object__resource_type=ResourceType.LITERAL,
            object__value__icontains=query
        ).select_related('subject', 'object')

        # Apply resource type filter if specified
        if resource_type:
            type_uris = [
                f"http://arkumu.org/data/types/{resource_type.replace('_', '-')}",
                f"http://arkumu.org/data/fuk/types/{resource_type.replace('_', '-')}",
            ]

            # Filter subjects that have rdf:type matching resource_type
            matching_triples_query = matching_triples_query.filter(
                subject__in=Triple.objects.filter(
                    predicate__uri='http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
                ).filter(
                    Q(object__uri__in=type_uris) | Q(object__canonical_uri__in=type_uris)
                ).values_list('subject_id', flat=True)
            )

        # Execute query with limit
        matching_triples = matching_triples_query[:limit * 2]  # Buffer for deduplication

        # Extract unique entities
        matching_entities = list({triple.subject.id: triple.subject
                                for triple in matching_triples}.values())[:limit]

        logger.info(f"Found {len(matching_entities)} entities matching search")

        # Get complete graph for each entity
        results = []
        for entity in matching_entities:
            entity_graph = self._get_complete_entity_graph(entity)
            results.append(entity_graph)

        return results

    def _get_complete_entity_graph(self, entity: Resource) -> Dict:
        """
        Get the complete connected graph for an entity.
        """
        logger.debug(f"Building graph for entity: {entity.uri}")

        # Get all outgoing triples (this entity as subject)
        outgoing_triples = Triple.objects.filter(
            subject=entity
        ).select_related('predicate', 'object')

        # Get all incoming triples (this entity as object)
        incoming_triples = Triple.objects.filter(
            object=entity,
            subject__resource_type=ResourceType.IRI  # Only entity -> entity relationships
        ).select_related('predicate', 'subject')

        # Initialize entity data structure
        entity_data = {
            'entity_uri': entity.uri,
            'entity_type': self._extract_entity_type(entity),
            'properties': {},  # Direct literal properties
            'outgoing_relations': {},  # This entity -> other entities
            'incoming_relations': {},  # Other entities -> this entity
            'connected_entities': {}  # Full data for connected entities
        }

        # Track connected entity IDs for batch loading
        connected_entity_ids = set()

        # Process outgoing relationships
        for triple in outgoing_triples:
            property_name = self._extract_property_name(triple.predicate.uri)

            if triple.object.resource_type == ResourceType.LITERAL:
                # Direct property: entity -> property -> literal
                if property_name not in entity_data['properties']:
                    entity_data['properties'][property_name] = []
                entity_data['properties'][property_name].append(triple.object.value)

            elif triple.object.resource_type == ResourceType.IRI:
                # Relationship: entity -> property -> other_entity
                if property_name not in entity_data['outgoing_relations']:
                    entity_data['outgoing_relations'][property_name] = []
                entity_data['outgoing_relations'][property_name].append({
                    'uri': triple.object.uri,
                    'type': self._extract_entity_type(triple.object)
                })
                connected_entity_ids.add(triple.object.id)

        # Process incoming relationships
        for triple in incoming_triples:
            property_name = self._extract_property_name(triple.predicate.uri)

            if property_name not in entity_data['incoming_relations']:
                entity_data['incoming_relations'][property_name] = []
            entity_data['incoming_relations'][property_name].append({
                'uri': triple.subject.uri,
                'type': self._extract_entity_type(triple.subject)
            })
            connected_entity_ids.add(triple.subject.id)

        # Get full data for all connected entities (batch loading)
        if connected_entity_ids:
            connected_entities = Resource.objects.filter(
                id__in=connected_entity_ids,
                resource_type=ResourceType.IRI
            )

            for connected_entity in connected_entities:
                entity_data['connected_entities'][connected_entity.uri] = \
                    self._get_entity_basic_data(connected_entity)

        # Flatten single-item property lists for cleaner output
        for prop_name, values in entity_data['properties'].items():
            if isinstance(values, list) and len(values) == 1:
                entity_data['properties'][prop_name] = values[0]

        logger.debug(f"Graph built: {len(entity_data['properties'])} properties, "
                    f"{len(connected_entity_ids)} connected entities")

        return entity_data

    def _get_entity_basic_data(self, entity: Resource) -> Dict:
        """
        Get basic property data for connected entities.
        """
        properties = {}

        # Get all literal properties for this entity
        property_triples = Triple.objects.filter(
            subject=entity,
            object__resource_type=ResourceType.LITERAL
        ).select_related('predicate', 'object')

        for triple in property_triples:
            property_name = self._extract_property_name(triple.predicate.uri)
            if property_name not in properties:
                properties[property_name] = []
            properties[property_name].append(triple.object.value)

        # Flatten single-item lists
        for prop_name, values in properties.items():
            if isinstance(values, list) and len(values) == 1:
                properties[prop_name] = values[0]

        return {
            'uri': entity.uri,
            'type': self._extract_entity_type(entity),
            'properties': properties
        }

    def _extract_property_name(self, property_uri: str) -> str:
        """Extract property name from URI."""
        return property_uri.split('/')[-1].replace('-', '_')

    def _extract_entity_type(self, entity: Resource) -> str:
        """Extract entity type from rdf:type relationships."""
        try:
            rdf_type_triple = Triple.objects.filter(
                subject=entity,
                predicate__uri='http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
            ).first()

            if rdf_type_triple:
                type_name = rdf_type_triple.object.uri.split('/')[-1]
                return type_name.replace('-', '_')
            return 'entity'
        except Exception:
            return 'entity'

    def get_available_properties(self, resource_type: str = None) -> List[Dict]:
        """
        Get list of searchable properties with usage counts.
        """
        query = Triple.objects.filter(
            object__resource_type=ResourceType.LITERAL
        ).values('predicate__uri', 'predicate__name').distinct()

        if resource_type:
            type_uris = [
                f"http://arkumu.org/data/types/{resource_type.replace('_', '-')}",
                f"http://arkumu.org/data/fuk/types/{resource_type.replace('_', '-')}",
            ]

            # Filter to properties used by entities of the specified type
            entities_of_type = Triple.objects.filter(
                predicate__uri='http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
            ).filter(
                Q(object__uri__in=type_uris) | Q(object__canonical_uri__in=type_uris)
            ).values_list('subject_id', flat=True)

            query = query.filter(subject_id__in=entities_of_type)

        properties = []
        for result in query[:50]:  # Limit for performance
            property_uri = result['predicate__uri']
            property_name = self._extract_property_name(property_uri)

            # Skip rdf:type and isPartOf
            if property_name in ['type', 'isPartOf']:
                continue

            # Get usage count
            usage_count = Triple.objects.filter(
                predicate__uri=property_uri,
                object__resource_type=ResourceType.LITERAL
            ).count()

            display_name = result['predicate__name'] or property_name.replace('_', ' ').title()

            properties.append({
                'name': property_name,
                'display_name': display_name,
                'uri': property_uri,
                'usage_count': usage_count
            })

        # Sort by usage count
        properties.sort(key=lambda x: x['usage_count'], reverse=True)
        return properties

    def get_available_types(self) -> List[Dict]:
        """
        Get available entity types with counts.
        """
        type_query = Triple.objects.filter(
            predicate__uri='http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
        ).values('object__uri', 'object__canonical_uri').distinct()

        types = []
        type_counts = {}

        for result in type_query:
            type_uri = result['object__canonical_uri'] or result['object__uri']
            if type_uri not in type_counts:
                type_counts[type_uri] = Triple.objects.filter(
                    predicate__uri='http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
                ).filter(
                    Q(object__uri=type_uri) | Q(object__canonical_uri=type_uri)
                ).count()

        for type_uri, count in type_counts.items():
            type_name = type_uri.split('/')[-1].replace('-', '_')
            display_name = type_name.replace('_', ' ').title()

            types.append({
                'name': type_name,
                'display_name': display_name,
                'uri': type_uri,
                'count': count
            })

        # Sort by count
        types.sort(key=lambda x: x['count'], reverse=True)
        return types[:20]  # Top 20 types