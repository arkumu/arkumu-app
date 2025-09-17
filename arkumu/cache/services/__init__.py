"""
Centralized Cache Services

Unified cache management for all Arkumu applications.
"""

from .base_cache_service import BaseCacheService, CACHE_TTL, CACHE_PREFIXES
from .graph_cache_service import GraphCacheService
from .oai_cache_service import OAICacheService
from .catalog_cache_service import CatalogCacheService
from .schema_map_cache_service import SchemaMapCacheService

__all__ = [
    'BaseCacheService',
    'GraphCacheService',
    'OAICacheService',
    'CatalogCacheService',
    'SchemaMapCacheService',
    'CACHE_TTL',
    'CACHE_PREFIXES',
    'CacheManager'
]


class CacheManager:
    """
    Unified cache manager providing access to all cache services.

    Usage:
        cache_manager = CacheManager()
        cache_manager.oai.warm_record(resource, 'oai_dc')
        cache_manager.graph.get_entity_graph(uri, depth=2)
        cache_manager.catalog.get_cached_search_results(query, property)
    """

    def __init__(self):
        self.graph = GraphCacheService()
        self.oai = OAICacheService()
        self.catalog = CatalogCacheService()
        self.schema_map = SchemaMapCacheService()

    def get_all_statistics(self):
        """Get statistics from all cache services."""
        return {
            'graph': self.graph.get_cache_statistics(),
            'oai': self.oai.get_cache_statistics(),
            'catalog': self.catalog.get_cache_statistics(),
            'schema_map': self.schema_map.get_cache_statistics()
        }

    def invalidate_resource_globally(self, resource_uri: str):
        """Invalidate resource across all cache services."""
        self.oai.invalidate_resource(resource_uri)
        self.graph.invalidate_resource(resource_uri)
        self.catalog.invalidate_catalog_data(resource_uri)