"""
Optimized Graph Search Service for Catalog Explorer

Efficient navigation: Class → Entity → Property → Literal
"""

from typing import Dict, List, Optional, Any
import logging
from django.db.models import Q, Count, Prefetch
from django.core.cache import cache
from arkumu.metadata.models import Resource, Triple, ResourceType
from arkumu.cache.services import GraphCacheService

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
        self.graph_cache = GraphCacheService()
        self.user_org = user.organization.code if user and hasattr(user, 'organization') and user.organization else None

    def get_classes_with_counts(self, organization_code: Optional[str] = None, limit: int = 50) -> List[Dict]:
        """
        Get all classes with entity counts and sample properties.

        Returns:
            List of classes with their entity counts and top properties
        """
        cache_key = f'catalog:classes:overview:{organization_code or "all"}'
        cached = cache.get(cache_key)
        if cached:
            return cached

        # Get classes with entity counts using efficient aggregation
        # Only show classes that have canonical URIs (harmonized catalog data)
        entity_filter = Q(
            object_triples__predicate__uri=self.rdf_type_uri,
            object_triples__subject__resource_type=ResourceType.ENTITY,
            object_triples__object__canonical_uri__isnull=False  # Ensure the class has canonical URI
        )

        # Add organization filter if specified
        if organization_code:
            entity_filter &= Q(object_triples__subject__organization__code=organization_code)

        classes = Resource.objects.filter(
            resource_type=ResourceType.CLASS,
            canonical_uri__isnull=False
        ).annotate(
            entity_count=Count(
                'object_triples__subject',
                filter=entity_filter,
                distinct=True
            )
        ).filter(entity_count__gt=0).order_by('-entity_count')[:limit]

        results = []
        for cls in classes:
            # Use canonical_uri and name from the resource
            results.append({
                'uri': cls.canonical_uri,
                'name': cls.name,
                'entity_count': cls.entity_count,
                'description': f"{cls.entity_count} entities"
            })

        cache.set(cache_key, results, 300)  # Cache for 5 minutes
        return results

    def get_properties_for_class(self, class_uri: str, limit: int = 30, organization_code: str = None) -> List[Dict]:
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

        # Get ALL entities of this class for accurate counts
        # Note: triples still use the raw URI, not canonical URI
        try:
            # Handle multiple resources with same canonical URI across organizations
            # We want to search across ALL organizations, so get all matching resources
            class_resources = Resource.objects.filter(canonical_uri=class_uri)

            if class_resources.exists():
                # Get all raw URIs for this canonical URI across organizations
                class_raw_uris = list(class_resources.values_list('uri', flat=True))
                logger.debug(f"Found {len(class_raw_uris)} resources for canonical URI {class_uri}")
            else:
                class_raw_uris = [class_uri]
        except Exception as e:
            logger.warning(f"Error getting class resources for {class_uri}: {e}")
            class_raw_uris = [class_uri]

        all_entity_ids = Triple.objects.filter(
            predicate__uri=self.rdf_type_uri,
            object__uri__in=class_raw_uris
        ).values_list('subject_id', flat=True)

        # Get properties used by these entities with ACTUAL counts
        # Only show properties that have canonical URIs (harmonized catalog data)
        property_stats = Triple.objects.filter(
            subject_id__in=all_entity_ids,
            object__resource_type=ResourceType.LITERAL,
            predicate__canonical_uri__isnull=False
        ).values(
            'predicate__uri',
            'predicate__name',
            'predicate__canonical_uri'
        ).annotate(
            usage_count=Count('id'),
            sample_value_count=Count('object__value', distinct=True)
        ).order_by('-usage_count')[:limit]

        results = []
        for prop in property_stats:
            # Use canonical_uri and name directly from the resource

            # Get a few sample values for this property
            sample_values = Triple.objects.filter(
                subject_id__in=all_entity_ids,
                predicate__uri=prop['predicate__uri'],
                object__resource_type=ResourceType.LITERAL
            ).values_list('object__value', flat=True).distinct()[:5]

            results.append({
                'uri': prop['predicate__canonical_uri'],
                'name': prop['predicate__name'],
                'display_name': prop['predicate__name'],
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

    def get_available_types(self, organization_code: Optional[str] = None, limit: int = 50) -> List[Dict]:
        """
        Get available entity types (classes) with counts.

        Alias for get_classes_with_counts for backward compatibility.
        """
        classes = self.get_classes_with_counts(organization_code=organization_code, limit=limit)

        # Transform to expected format
        results = []
        for cls in classes:
            results.append({
                'name': cls['name'],
                'display_name': cls['name'],
                'uri': cls['uri'],
                'entity_count': cls['entity_count']  # Keep consistent field name
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

    def get_literals_for_property(self, property_uri: str, class_uri: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """
        Get sample literal values for a specific property.

        Args:
            property_uri: URI of the property
            class_uri: Optional class filter
            limit: Maximum number of literals to return

        Returns:
            List of literal values with their entities
        """
        # Build base query for this property's literals
        base_query = Triple.objects.filter(
            predicate__uri=property_uri,
            object__resource_type=ResourceType.LITERAL
        )

        # Apply class filter if specified
        if class_uri:
            entity_subquery = Triple.objects.filter(
                predicate__uri=self.rdf_type_uri,
                object__uri=class_uri
            ).values('subject_id')
            base_query = base_query.filter(subject_id__in=entity_subquery)

        # Get literal values with their entities
        literals = base_query.select_related(
            'subject', 'object'
        ).order_by('object__value')[:limit]

        results = []
        for triple in literals:
            # Get entity class for context
            entity_class = Triple.objects.filter(
                subject=triple.subject,
                predicate__uri=self.rdf_type_uri
            ).select_related('object').first()

            results.append({
                'value': triple.object.value,
                'entity_uri': triple.subject.uri,
                'entity_class': entity_class.object.uri.split('/')[-1] if entity_class else 'Unknown'
            })

        return results

    def browse_property_values(self, property_uri: str, class_uri: Optional[str] = None,
                              organization_code: Optional[str] = None, search_term: Optional[str] = None,
                              offset: int = 0, limit: int = 50) -> Dict:
        """
        Browse literal values for a property with optional search filtering.

        Args:
            property_uri: URI of the property to browse
            class_uri: Optional class filter
            organization_code: Optional organization filter
            search_term: Optional search term to filter values
            offset: Database-level pagination offset
            limit: Maximum results

        Returns:
            Dictionary with literals, statistics, and sample values
        """
        # Build base query - filter by canonical URIs directly
        base_query = Triple.objects.filter(
            predicate__canonical_uri=property_uri,
            object__resource_type=ResourceType.LITERAL
        )

        # Apply class filter
        if class_uri:
            entity_subquery = Triple.objects.filter(
                predicate__uri=self.rdf_type_uri,
                object__canonical_uri=class_uri
            ).values('subject_id')
            base_query = base_query.filter(subject_id__in=entity_subquery)

        # Apply organization filter
        if organization_code:
            base_query = base_query.filter(subject__organization__code=organization_code)

        # Apply search filter using trigram index for efficient text search
        if search_term:
            # Use trigram search for better performance with the GIN index
            base_query = base_query.filter(object__value__icontains=search_term)

        # Get statistics
        total_values = base_query.count()
        unique_values = base_query.values('object__value').distinct().count()

        # Get paginated values with frequency using database-level pagination
        value_counts = base_query.values('object__value').annotate(
            count=Count('id')
        ).order_by('-count')[offset:offset + limit]

        # Get sample entities for each value in this page
        results = []
        for value_data in value_counts:  # Process ALL values in the page, not just 20
            value = value_data['object__value']
            count = value_data['count']

            # Get a few sample entities with this value using value_hash for efficiency
            from arkumu.common.hash_utils import generate_value_hash
            value_hash = generate_value_hash(value)
            sample_entities = base_query.filter(
                object__value_hash=value_hash
            ).select_related('subject')[:3]

            entity_samples = []
            for triple in sample_entities:
                # Get entity class
                entity_class = Triple.objects.filter(
                    subject=triple.subject,
                    predicate__uri=self.rdf_type_uri
                ).select_related('object').first()

                entity_samples.append({
                    'uri': triple.subject.uri,
                    'class': entity_class.object.uri.split('/')[-1] if entity_class else 'Unknown'
                })

            results.append({
                'value': value,
                'count': count,
                'sample_entities': entity_samples
            })

        return {
            'property_uri': property_uri,
            'property_name': property_uri.split('/')[-1],
            'total_values': total_values,
            'unique_values': unique_values,
            'values': results,
            'has_more': len(results) == limit  # Indicate if there might be more pages
        }

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

    def browse_entities_by_class(self, class_uri: str, limit: int = 20) -> List[Dict]:
        """
        Browse entities of a specific class with their properties and relationships.

        Args:
            class_uri: URI of the class to browse
            limit: Maximum number of entities to return

        Returns:
            List of entities with their properties and relationships
        """
        if not class_uri:
            return []

        try:
            # Get entities of this class
            class_resource = Resource.objects.get(uri=class_uri, resource_type=ResourceType.CLASS)

            # Find entities that have this class as their rdf:type
            entity_triples = Triple.objects.filter(
                predicate__uri=self.rdf_type_uri,
                object=class_resource
            ).select_related('subject')[:limit]

            entities = []
            for triple in entity_triples:
                entity = triple.subject

                # Get entity properties (literals only)
                properties = {}
                literal_triples = Triple.objects.filter(
                    subject=entity,
                    object__resource_type=ResourceType.LITERAL
                ).select_related('predicate', 'object')[:20]

                for prop_triple in literal_triples:
                    prop_name = prop_triple.predicate.uri.split('/')[-1].replace('-', '_')
                    properties[prop_name] = prop_triple.object.value

                # Get title for display
                title = (properties.get('title') or
                        properties.get('name') or
                        properties.get('deutsches_wikidata_label') or
                        'Untitled')

                # Get outgoing relationships (to other entities)
                outgoing_relations = []
                outgoing_triples = Triple.objects.filter(
                    subject=entity,
                    object__resource_type=ResourceType.ENTITY
                ).exclude(
                    predicate__uri=self.rdf_type_uri
                ).select_related('predicate', 'object')[:5]

                for rel_triple in outgoing_triples:
                    outgoing_relations.append({
                        'property': rel_triple.predicate.uri,
                        'target': rel_triple.object.uri
                    })

                # Get incoming relationships (from other entities)
                incoming_relations = []
                incoming_triples = Triple.objects.filter(
                    object=entity,
                    subject__resource_type=ResourceType.ENTITY
                ).select_related('predicate', 'subject')[:5]

                for rel_triple in incoming_triples:
                    incoming_relations.append({
                        'property': rel_triple.predicate.uri,
                        'source': rel_triple.subject.uri
                    })

                # Count total connections
                connected_count = (
                    Triple.objects.filter(subject=entity, object__resource_type=ResourceType.ENTITY).count() +
                    Triple.objects.filter(object=entity, subject__resource_type=ResourceType.ENTITY).count()
                )

                entities.append({
                    'entity_uri': entity.uri,
                    'entity_type': class_uri,
                    'title': title,
                    'properties': properties,
                    'outgoing_relations': outgoing_relations,
                    'incoming_relations': incoming_relations,
                    'connected_count': connected_count
                })

            return entities

        except Resource.DoesNotExist:
            logger.warning(f"Class not found: {class_uri}")
            return []
        except Exception as e:
            logger.error(f"Error browsing entities for class {class_uri}: {e}")
            return []

    def get_entity_relationships_from_cache(self, entity_uri: str) -> Optional[Dict]:
        """
        Get entity relationships leveraging cached graph data from OAI operations.

        This method tries to reuse expensive graph traversals that were cached
        during OAI-PMH metadata generation, avoiding duplicate work.
        """
        try:
            # Try to get relationships from graph cache (possibly from OAI operations)
            cached_relationships = self.graph_cache.get_entity_relationships_from_graph_cache(
                entity_uri, self.user_org
            )

            if cached_relationships:
                logger.debug(f"Reusing cached graph data for catalog view: {entity_uri}")
                return self._format_relationships_for_catalog(cached_relationships)

            # If no cached data, we could trigger fresh graph generation
            # but for now, fall back to regular methods
            logger.debug(f"No cached graph data available for {entity_uri}")
            return None

        except Exception as e:
            logger.error(f"Error getting cached relationships for {entity_uri}: {e}")
            return None

    def _format_relationships_for_catalog(self, graph_relationships: Dict) -> Dict:
        """
        Format cached graph relationships for catalog display.

        Transforms the graph data structure into the format expected by catalog views.
        """
        if not graph_relationships:
            return {}

        # Transform the cached graph data into catalog-friendly format
        formatted = {
            'incoming_relationships': [],
            'outgoing_relationships': [],
            'properties': {},
            'connected_entities_count': 0
        }

        # Extract incoming relationships
        for rel in graph_relationships.get('incoming', []):
            formatted['incoming_relationships'].append({
                'property': rel.get('property', ''),
                'entity_uri': rel.get('source_uri', ''),
                'entity_title': rel.get('source_title', 'Unknown')
            })

        # Extract outgoing relationships
        for rel in graph_relationships.get('outgoing', []):
            formatted['outgoing_relationships'].append({
                'property': rel.get('property', ''),
                'entity_uri': rel.get('target_uri', ''),
                'entity_title': rel.get('target_title', 'Unknown')
            })

        # Extract literal properties
        for prop_uri, values in graph_relationships.get('literals', {}).items():
            prop_name = prop_uri.split('/')[-1].replace('-', '_')
            formatted['properties'][prop_name] = values

        # Count connected entities
        formatted['connected_entities_count'] = (
            len(formatted['incoming_relationships']) +
            len(formatted['outgoing_relationships'])
        )

        return formatted


    def get_available_properties(self, selected_class: str = '') -> List[Dict]:
        """
        Get available properties with caching support.

        This method checks if properties data is already available in cache
        before performing expensive database queries.
        """
        # Try to leverage any cached property information
        # Shared cache key - same class properties for all users in same org
        cache_key = f"catalog_properties:{selected_class}:{self.user_org}"
        cached_properties = cache.get(cache_key)

        if cached_properties:
            logger.debug(f"Using cached available properties for class: {selected_class}")
            return cached_properties

        # Fallback to original method
        logger.debug(f"Cache miss - fetching available properties for class: {selected_class}")
        properties = self.get_properties_for_class(selected_class) if selected_class else []

        # Cache for future use
        cache.set(cache_key, properties, 6 * 3600)  # 6 hours

        return properties

    def get_available_organizations(self) -> List[Dict]:
        """
        Get available organizations with resource counts, cached.
        """
        cache_key = "catalog_organizations_all"
        cached_orgs = cache.get(cache_key)

        if cached_orgs:
            logger.debug("Using cached available organizations")
            return cached_orgs

        logger.debug("Cache miss - fetching available organizations")

        try:
            from arkumu.users.models import Organization

            # Debug: Check HMT specifically
            hmt_org = Organization.objects.filter(code='hmt').first()
            if hmt_org:
                hmt_total_resources = hmt_org.resource_set.count()
                hmt_canonical_resources = hmt_org.resource_set.filter(canonical_uri__isnull=False).count()
                logger.debug(f"HMT has {hmt_total_resources} total resources, {hmt_canonical_resources} with canonical URIs")

            # Get organizations that have resources with canonical URIs (harmonized data)
            logger.debug("Fetching organizations with canonical URIs only")
            orgs_with_counts = Organization.objects.filter(
                resource__isnull=False,
                resource__canonical_uri__isnull=False
            ).annotate(
                resource_count=Count('resource', filter=Q(resource__canonical_uri__isnull=False), distinct=True)
            ).filter(resource_count__gt=0).order_by('-resource_count', 'name')

            logger.debug(f"Found {orgs_with_counts.count()} organizations with canonical URIs")

            organizations = []
            for org in orgs_with_counts:
                logger.debug(f"Organization: {org.code} ({org.name}) - {org.resource_count} canonical resources")
                organizations.append({
                    'code': org.code,
                    'name': org.name,
                    'display_name': f"{org.name} ({org.code})",
                    'resource_count': org.resource_count
                })

            # Cache for 6 hours
            cache.set(cache_key, organizations, 6 * 3600)
            logger.debug(f"Cached {len(organizations)} organizations")

            return organizations

        except Exception as e:
            logger.error(f"Error getting available organizations: {e}")
            return []