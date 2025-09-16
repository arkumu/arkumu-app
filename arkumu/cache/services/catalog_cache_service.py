"""
Catalog Cache Service

Specialized caching service for catalog explorer operations, leveraging graph cache.
"""

import logging
from typing import Dict, Optional, Any, List
import hashlib
from django.utils import timezone
from .base_cache_service import BaseCacheService
from .graph_cache_service import GraphCacheService

logger = logging.getLogger(__name__)


class CatalogCacheService(BaseCacheService):
    """
    Cache service for catalog explorer operations.

    Integrates with graph cache service to reuse expensive traversals
    performed by OAI-PMH generation.
    """

    def __init__(self):
        super().__init__('catalog')
        self.graph_cache = GraphCacheService()

    def get_cached_search_results(self, query: str, property_name: str,
                                selected_class: str = '', user_org: str = None) -> Optional[Dict]:
        """Get cached search results."""
        cache_params = {
            'query': query,
            'property': property_name,
            'class': selected_class,
            'org': user_org or 'global'
        }
        return self.get_cached('search', **cache_params)

    def cache_search_results(self, query: str, property_name: str, results: Dict,
                           selected_class: str = '', user_org: str = None):
        """Cache search results."""
        cache_params = {
            'query': query,
            'property': property_name,
            'class': selected_class,
            'org': user_org or 'global'
        }

        enriched_results = {
            'results': results,
            'cached_at': timezone.now().isoformat(),
            'result_count': len(results.get('entities', [])),
            'query_params': cache_params
        }

        self.set_cached('search', enriched_results, 'catalog_search', **cache_params)
        logger.debug(f"Cached search results for query: {query}")

    def get_cached_types_and_properties(self, user_org: str = None) -> Optional[Dict]:
        """Get cached available types and properties."""
        cache_params = {
            'org': user_org or 'global',
            'scope': 'types_properties'
        }
        return self.get_cached('metadata', **cache_params)

    def cache_types_and_properties(self, types_data: List[Dict], properties_data: List[Dict],
                                 user_org: str = None):
        """Cache available types and properties."""
        cache_params = {
            'org': user_org or 'global',
            'scope': 'types_properties'
        }

        enriched_data = {
            'types': types_data,
            'properties': properties_data,
            'cached_at': timezone.now().isoformat(),
            'type_count': len(types_data),
            'property_count': len(properties_data)
        }

        self.set_cached('metadata', enriched_data, 'catalog_types', **cache_params)
        logger.debug(f"Cached {len(types_data)} types and {len(properties_data)} properties")

    def get_entity_relationships_from_graph_cache(self, resource_uri: str,
                                                 user_org: str = None) -> Optional[Dict]:
        """
        Get entity relationships by leveraging existing graph cache.

        This method tries to reuse graph data that might have been cached
        by OAI-PMH operations, avoiding duplicate expensive traversals.
        """
        org_code = user_org or 'global'

        # Try to get cached graph data from different sources
        # 1. Check if we have OAI-generated graph cache
        oai_graph = self.graph_cache.get_entity_graph(
            resource_uri,
            depth=2,
            organization_code=org_code
        )

        if oai_graph:
            logger.debug(f"Reusing OAI graph cache for catalog: {resource_uri}")
            return self._extract_catalog_relationships(oai_graph['graph'])

        # 2. Check for catalog-specific graph cache
        catalog_graph = self.graph_cache.get_entity_graph(
            resource_uri,
            depth=3,  # Catalog might need deeper traversal
            organization_code=org_code
        )

        if catalog_graph:
            logger.debug(f"Using catalog graph cache: {resource_uri}")
            return self._extract_catalog_relationships(catalog_graph['graph'])

        return None

    def cache_entity_relationships(self, resource_uri: str, relationship_data: Dict,
                                 user_org: str = None):
        """Cache entity relationship data for catalog display."""
        # Hash the relationship parameters for cache key
        params_hash = hashlib.md5(f"catalog_relationships_{user_org}".encode()).hexdigest()[:8]

        self.graph_cache.cache_traversal_result(
            resource_uri=resource_uri,
            traversal_type='catalog_relationships',
            params_hash=params_hash,
            result_data=relationship_data
        )

        logger.info(f"Cached catalog relationships for {resource_uri}")

    def warm_popular_entities(self, entity_uris: List[str], user_org: str = None):
        """
        Warm cache for popular entities in catalog.

        Coordinates with graph cache service to pre-generate data.
        """
        logger.info(f"Warming catalog cache for {len(entity_uris)} popular entities")

        # Use graph cache service to warm underlying data
        self.graph_cache.warm_popular_resources(entity_uris, user_org)

        # Could also pre-generate catalog-specific views here

    def _extract_catalog_relationships(self, graph_data: Dict) -> Dict:
        """
        Extract catalog-relevant relationships from graph data.

        Transforms graph data into the format expected by catalog views.
        """
        if not graph_data:
            return {}

        # This would contain logic to transform graph data
        # into the relationship format used by catalog explorer
        relationships = {
            'incoming': [],
            'outgoing': [],
            'properties': {},
            'literals': {}
        }

        # Transform graph data based on catalog needs
        # This is a simplified version - actual implementation would
        # extract specific relationship patterns

        return relationships

    def invalidate_catalog_data(self, resource_uri: str = None, user_org: str = None):
        """Invalidate catalog-specific cached data."""
        if resource_uri:
            logger.info(f"Invalidating catalog cache for resource: {resource_uri}")
            # Invalidate specific resource data
        else:
            logger.info(f"Invalidating catalog cache for organization: {user_org}")
            # Invalidate organization-wide data

        # Also trigger graph cache invalidation
        if resource_uri:
            self.graph_cache.invalidate_resource(resource_uri)

    def get_cache_statistics(self) -> Dict[str, Any]:
        """Get catalog cache statistics."""
        base_stats = self.get_cache_stats()

        base_stats.update({
            'service_type': 'catalog_cache',
            'cache_types': ['search', 'metadata', 'relationships'],
            'graph_integration': True,
            'supported_operations': [
                'search_result_caching',
                'types_properties_caching',
                'relationship_extraction',
                'popular_entity_warming'
            ]
        })

        return base_stats