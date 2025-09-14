"""
Optimized Graph Search Service for Catalog Explorer

Efficient navigation: Class → Entity → Property → Literal
"""

from typing import Dict, List, Optional, Any
import logging
from django.db.models import Q, Count, Prefetch
from django.core.cache import cache
from arkumu.metadata.models import Resource, Triple, ResourceType

logger = logging.getLogger(__name__)


class GraphSearchService:
    """
    Optimized graph search service for catalog exploration.

    Provides efficient queries for navigating the RDF graph structure:
    - Classes (types of things)
    - Properties (attributes/fields)
    - Literals (actual values)

    Entities (IRIs) are hidden from users - they're just technical references.
    """

    def __init__(self, user=None):
        self.user = user
        self.rdf_type_uri = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'

    def get_classes_with_counts(self, limit: int = 50) -> List[Dict]:
        """
        Get all classes with entity counts and sample properties.

        Returns:
            List of classes with their entity counts and top properties
        """
        cache_key = 'catalog:classes:overview'
        cached = cache.get(cache_key)
        if cached:
            return cached

        # Get classes with entity counts using efficient aggregation
        classes = Resource.objects.filter(
            resource_type=ResourceType.CLASS
        ).annotate(
            entity_count=Count(
                'object_triples__subject',
                filter=Q(
                    object_triples__predicate__uri=self.rdf_type_uri,
                    object_triples__subject__resource_type=ResourceType.ENTITY
                ),
                distinct=True
            )
        ).filter(entity_count__gt=0).order_by('-entity_count')[:limit]

        results = []
        for cls in classes:
            # Extract clean name from URI
            class_name = cls.uri.split('/')[-1].replace('-', ' ').title()

            results.append({
                'uri': cls.uri,
                'name': cls.name or class_name,
                'entity_count': cls.entity_count,
                'description': f"{cls.entity_count} entities"
            })

        cache.set(cache_key, results, 300)  # Cache for 5 minutes
        return results

    def get_properties_for_class(self, class_uri: str, limit: int = 30) -> List[Dict]:
        """
        Get all properties used by entities of a specific class.

        Args:
            class_uri: URI of the class
            limit: Maximum number of properties to return

        Returns:
            List of properties with usage counts and sample values
        """
        cache_key = f'catalog:properties:{class_uri}'
        cached = cache.get(cache_key)
        if cached:
            return cached

        # Get sample entities of this class (for efficiency)
        sample_entity_ids = Triple.objects.filter(
            predicate__uri=self.rdf_type_uri,
            object__uri=class_uri
        ).values_list('subject_id', flat=True)[:100]

        # Get properties used by these entities with counts
        property_stats = Triple.objects.filter(
            subject_id__in=sample_entity_ids,
            object__resource_type=ResourceType.LITERAL
        ).values(
            'predicate__uri',
            'predicate__name'
        ).annotate(
            usage_count=Count('id'),
            sample_value_count=Count('object__value', distinct=True)
        ).order_by('-usage_count')[:limit]

        results = []
        for prop in property_stats:
            prop_name = prop['predicate__uri'].split('/')[-1].replace('-', '_')

            # Get a few sample values for this property
            sample_values = Triple.objects.filter(
                subject_id__in=sample_entity_ids,
                predicate__uri=prop['predicate__uri'],
                object__resource_type=ResourceType.LITERAL
            ).values_list('object__value', flat=True).distinct()[:5]

            results.append({
                'uri': prop['predicate__uri'],
                'name': prop['predicate__name'] or prop_name,
                'display_name': prop_name.replace('_', ' ').title(),
                'usage_count': prop['usage_count'],
                'unique_values': prop['sample_value_count'],
                'sample_values': list(sample_values)
            })

        cache.set(cache_key, results, 300)
        return results

    def search_literals(self,
                       query: str,
                       class_uri: Optional[str] = None,
                       property_uri: Optional[str] = None,
                       limit: int = 50) -> List[Dict]:
        """
        Search for literals (actual content) with optional class/property filters.

        Args:
            query: Search term
            class_uri: Optional class filter
            property_uri: Optional property filter
            limit: Maximum results

        Returns:
            List of matching literals with their entities and properties
        """
        if not query or not query.strip():
            return []

        # Build base query for literal search
        base_query = Triple.objects.filter(
            object__resource_type=ResourceType.LITERAL,
            object__value__icontains=query.strip()
        )

        # Apply property filter if specified
        if property_uri:
            base_query = base_query.filter(predicate__uri=property_uri)

        # Apply class filter using efficient subquery
        if class_uri:
            entity_subquery = Triple.objects.filter(
                predicate__uri=self.rdf_type_uri,
                object__uri=class_uri
            ).values('subject_id')
            base_query = base_query.filter(subject_id__in=entity_subquery)

        # Get matching triples with related data
        matches = base_query.select_related(
            'subject', 'predicate', 'object'
        )[:limit * 2]  # Get extra for deduplication

        # Group results by entity to show all matching properties
        entities_data = {}
        for triple in matches:
            entity_uri = triple.subject.uri
            if entity_uri not in entities_data:
                entities_data[entity_uri] = {
                    'entity_uri': entity_uri,
                    'matched_properties': [],
                    'other_properties': {}
                }

            prop_name = triple.predicate.uri.split('/')[-1].replace('-', '_')
            entities_data[entity_uri]['matched_properties'].append({
                'name': prop_name,
                'value': triple.object.value,
                'property_uri': triple.predicate.uri
            })

        # Get additional context properties for each entity
        for entity_uri in list(entities_data.keys())[:limit]:
            entity_data = entities_data[entity_uri]

            # Get a few more properties for context
            context_props = Triple.objects.filter(
                subject__uri=entity_uri,
                object__resource_type=ResourceType.LITERAL
            ).exclude(
                predicate__uri__in=[p['property_uri'] for p in entity_data['matched_properties']]
            ).select_related('predicate', 'object')[:5]

            for prop in context_props:
                prop_name = prop.predicate.uri.split('/')[-1].replace('-', '_')
                entity_data['other_properties'][prop_name] = prop.object.value

        return list(entities_data.values())[:limit]

    def get_faceted_search_options(self, class_uri: Optional[str] = None) -> Dict:
        """
        Get available facets for filtering (classes and properties).

        Returns:
            Dictionary with available classes and properties for faceted search
        """
        facets = {
            'classes': [],
            'properties': []
        }

        # Get top classes if no specific class selected
        if not class_uri:
            facets['classes'] = self.get_classes_with_counts(limit=20)
        else:
            # Get properties for the selected class
            facets['properties'] = self.get_properties_for_class(class_uri, limit=20)

        return facets

    def get_entity_details(self, entity_uri: str) -> Optional[Dict]:
        """
        Get complete details for a specific entity.

        Args:
            entity_uri: URI of the entity

        Returns:
            Dictionary with entity class, properties, and relationships
        """
        try:
            entity = Resource.objects.get(uri=entity_uri, resource_type=ResourceType.ENTITY)
        except Resource.DoesNotExist:
            return None

        # Get entity class
        class_triple = Triple.objects.filter(
            subject=entity,
            predicate__uri=self.rdf_type_uri
        ).select_related('object').first()

        # Get all literal properties with prefetch
        properties = {}
        literal_triples = Triple.objects.filter(
            subject=entity,
            object__resource_type=ResourceType.LITERAL
        ).select_related('predicate', 'object')

        for triple in literal_triples:
            prop_name = triple.predicate.uri.split('/')[-1].replace('-', '_')
            if prop_name not in properties:
                properties[prop_name] = []
            properties[prop_name].append(triple.object.value)

        # Flatten single-value properties
        for key, values in properties.items():
            if len(values) == 1:
                properties[key] = values[0]

        # Get relationships to other entities
        relationships = {}
        rel_triples = Triple.objects.filter(
            subject=entity,
            object__resource_type=ResourceType.ENTITY
        ).exclude(
            predicate__uri=self.rdf_type_uri
        ).select_related('predicate', 'object')[:20]

        for triple in rel_triples:
            rel_name = triple.predicate.uri.split('/')[-1].replace('-', '_')
            if rel_name not in relationships:
                relationships[rel_name] = []
            relationships[rel_name].append(triple.object.uri)

        return {
            'uri': entity.uri,
            'class': {
                'uri': class_triple.object.uri,
                'name': class_triple.object.uri.split('/')[-1].replace('-', ' ').title()
            } if class_triple else None,
            'properties': properties,
            'relationships': relationships
        }

    def get_available_types(self, limit: int = 50) -> List[Dict]:
        """
        Get available entity types (classes) with counts.

        Alias for get_classes_with_counts for backward compatibility.
        """
        classes = self.get_classes_with_counts(limit=limit)

        # Transform to expected format
        results = []
        for cls in classes:
            results.append({
                'name': cls['name'],
                'display_name': cls['name'],
                'uri': cls['uri'],
                'count': cls['entity_count']
            })

        return results

    def get_available_properties(self, resource_type: Optional[str] = None, limit: int = 50) -> List[Dict]:
        """
        Get list of searchable properties with usage counts.

        Args:
            resource_type: Optional class/type URI to filter properties
            limit: Maximum number of properties to return
        """
        if resource_type:
            # Get properties for specific class
            return self.get_properties_for_class(resource_type, limit=limit)

        # Get all properties across all classes
        cache_key = 'catalog:properties:all'
        cached = cache.get(cache_key)
        if cached:
            return cached

        # Get sample of all properties with literals
        property_stats = Triple.objects.filter(
            object__resource_type=ResourceType.LITERAL
        ).values(
            'predicate__uri',
            'predicate__name'
        ).annotate(
            usage_count=Count('id')
        ).order_by('-usage_count')[:limit]

        results = []
        for prop in property_stats:
            prop_name = prop['predicate__uri'].split('/')[-1].replace('-', '_')

            # Skip system properties
            if prop_name in ['type', 'isPartOf']:
                continue

            results.append({
                'name': prop_name,
                'display_name': prop_name.replace('_', ' ').title(),
                'uri': prop['predicate__uri'],
                'usage_count': prop['usage_count']
            })

        cache.set(cache_key, results, 300)
        return results

    def search_by_property_with_graph(self,
                                    query: str,
                                    property_name: str = 'title',
                                    resource_type: str = None,
                                    limit: int = 50) -> List[Dict]:
        """
        Search for entities by property value and return complete graphs.

        Backward compatibility wrapper for search_literals.
        """
        # Convert property_name to URI if needed
        if not property_name.startswith('http'):
            # For backward compatibility, search for any property URI ending with this name
            # since property URIs include institution codes like /hmt/, /fuk/
            from arkumu.metadata.models import Resource
            property_uri_suffix = property_name.replace('_', '-')

            # Find matching property URI from available properties
            matching_props = Resource.objects.filter(
                resource_type=ResourceType.PROPERTY,
                uri__endswith=f"/{property_uri_suffix}"
            ).values_list('uri', flat=True).first()

            property_uri = matching_props or property_name
        else:
            property_uri = property_name

        # Convert resource_type to class URI if needed
        class_uri = None
        if resource_type:
            if not resource_type.startswith('http'):
                class_uri = f"http://arkumu.org/data/types/{resource_type.replace('_', '-')}"
            else:
                class_uri = resource_type

        # Use the optimized search method
        results = self.search_literals(
            query=query,
            class_uri=class_uri,
            property_uri=property_uri,
            limit=limit
        )

        # Transform to expected format with full graph data
        graph_results = []
        for result in results:
            # Get full entity details for graph visualization
            entity_details = self.get_entity_details(result['entity_uri'])
            if entity_details:
                graph_results.append({
                    'entity_uri': result['entity_uri'],
                    'entity_type': entity_details['class']['name'] if entity_details['class'] else 'Unknown',
                    'properties': entity_details['properties'],
                    'outgoing_relations': entity_details['relationships'],
                    'incoming_relations': {},  # Not implemented yet
                    'connected_entities': {}  # Not implemented yet
                })

        return graph_results

    def get_statistics(self) -> Dict:
        """Get overall catalog statistics."""

        cache_key = 'catalog:statistics'
        cached = cache.get(cache_key)
        if cached:
            return cached

        stats = {
            'total_classes': Resource.objects.filter(
                resource_type=ResourceType.CLASS
            ).count(),
            'total_entities': Resource.objects.filter(
                resource_type=ResourceType.ENTITY
            ).count(),
            'total_properties': Resource.objects.filter(
                resource_type=ResourceType.PROPERTY
            ).count(),
            'total_literals': Resource.objects.filter(
                resource_type=ResourceType.LITERAL
            ).count(),
            'total_triples': Triple.objects.count()
        }

        cache.set(cache_key, stats, 600)  # Cache for 10 minutes
        return stats