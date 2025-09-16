"""
Base Cache Service

Provides centralized caching configuration and utilities for all Arkumu apps.
"""

import logging
from typing import Dict, Optional, Any
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

# Centralized TTL configuration (in seconds)
CACHE_TTL = {
    # OAI-PMH caching
    'oai_record': 4 * 3600,      # 4 hours - individual OAI records
    'oai_page': 2 * 3600,        # 2 hours - OAI list pages

    # Graph caching (shared between OAI and catalog)
    'graph_entity': 6 * 3600,    # 6 hours - entity graph data
    'graph_traversal': 4 * 3600, # 4 hours - traversal results

    # Catalog caching
    'catalog_search': 1 * 3600,  # 1 hour - search results
    'catalog_types': 12 * 3600,  # 12 hours - available types/properties

    # Metadata caching
    'metadata_export': 2 * 3600, # 2 hours - export formats
}

# Cache key prefixes for different services
CACHE_PREFIXES = {
    'oai': 'arkumu:oai',
    'graph': 'arkumu:graph',
    'catalog': 'arkumu:catalog',
    'metadata': 'arkumu:metadata',
}


class BaseCacheService:
    """Base class for all cache services in Arkumu."""

    def __init__(self, prefix: str):
        self.prefix = CACHE_PREFIXES.get(prefix, f'arkumu:{prefix}')
        self.logger = logging.getLogger(f'{__name__}.{self.__class__.__name__}')

    def _get_cache_key(self, cache_type: str, **kwargs) -> str:
        """Generate consistent cache keys with prefix."""
        key_parts = [self.prefix, cache_type]
        key_parts.extend(str(v) for v in kwargs.values())
        return ':'.join(key_parts)

    def get_cached(self, cache_type: str, **kwargs) -> Optional[Any]:
        """Get cached data by type and parameters."""
        cache_key = self._get_cache_key(cache_type, **kwargs)
        return cache.get(cache_key)

    def set_cached(self, cache_type: str, data: Any, ttl_key: str, **kwargs):
        """Cache data with configured TTL."""
        cache_key = self._get_cache_key(cache_type, **kwargs)
        ttl = CACHE_TTL.get(ttl_key, 3600)  # Default 1 hour

        cache.set(cache_key, data, ttl)
        self.logger.debug(f"Cached {cache_type} for {ttl}s: {cache_key}")

    def invalidate(self, cache_type: str, **kwargs):
        """Invalidate specific cache entry."""
        cache_key = self._get_cache_key(cache_type, **kwargs)
        cache.delete(cache_key)
        self.logger.info(f"Invalidated cache: {cache_key}")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics for monitoring."""
        return {
            'ttl_config': CACHE_TTL,
            'prefix': self.prefix,
            'backend': cache.__class__.__name__,
            'timestamp': timezone.now().isoformat()
        }