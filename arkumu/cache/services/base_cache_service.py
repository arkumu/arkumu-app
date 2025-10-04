"""
Base Cache Service

Provides centralized caching configuration and utilities for all Arkumu apps.
"""

import logging
from typing import Dict, Optional, Any
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

# Centralized TTL configuration (in seconds) with memory management
CACHE_TTL = {
    # OAI-PMH caching
    'oai_record': 4 * 3600,      # 4 hours - individual OAI records
    'oai_page': 2 * 3600,        # 2 hours - OAI list pages

    # Graph caching (shared between OAI and catalog) - reduced to prevent memory buildup
    'graph_entity': 2 * 3600,    # 2 hours - entity graph data (was 6h)
    'graph_traversal': 1 * 3600, # 1 hour - traversal results (was 4h)

    # Catalog caching
    'catalog_search': 30 * 60,   # 30 minutes - search results (was 1h)
    'catalog_types': 6 * 3600,   # 6 hours - available types/properties (was 12h)
    'catalog_classes': 5 * 60,   # 5 minutes - overview of classes
    'catalog_property_snapshot': 5 * 60,  # 5 minutes - property usage snapshots
    'catalog_statistics': 10 * 60,  # 10 minutes - aggregated stats
    'catalog_property_list': 6 * 3600,  # 6 hours - available properties list
    'catalog_organizations': 6 * 3600,  # 6 hours - organizations overview
    'catalog_sidebar': 5 * 60,  # 5 minutes - explorer sidebar context

    # Metadata caching
    'metadata_export': 1 * 3600, # 1 hour - export formats (was 2h)

    # Project snapshots
    # Snapshot rebuilds are driven by importer hooks; keep cache warm until explicit invalidation.
    'project_snapshot': 30 * 24 * 3600,  # 30 days - cross-institutional project snapshot
}

# Cache size limits to prevent memory leaks
CACHE_LIMITS = {
    'max_entries_per_service': 1000,  # Max cache entries per service
    'memory_threshold_mb': 1024,      # Clear cache if process uses > 1GB (was 256MB - too low!)
}

# Cache key prefixes for different services
CACHE_PREFIXES = {
    'oai': 'arkumu:oai',
    'graph': 'arkumu:graph',
    'catalog': 'arkumu:catalog',
    'metadata': 'arkumu:metadata',
    'projects': 'arkumu:projects',
}


class BaseCacheService:
    """Base class for all cache services in Arkumu."""

    def __init__(self, prefix: str):
        self.prefix = CACHE_PREFIXES.get(prefix, f'arkumu:{prefix}')
        self.logger = logging.getLogger(f'{__name__}.{self.__class__.__name__}')

    def _get_cache_key(self, cache_type: str, **kwargs) -> str:
        """Generate consistent cache keys with prefix."""
        key_parts = [self.prefix, cache_type]
        # Sort kwargs for deterministic keys - prevents cache duplication
        sorted_params = sorted(kwargs.items())
        key_parts.extend(f"{k}:{v}" for k, v in sorted_params)
        return ':'.join(key_parts)

    def get_cached(self, cache_type: str, **kwargs) -> Optional[Any]:
        """Get cached data by type and parameters."""
        cache_key = self._get_cache_key(cache_type, **kwargs)
        try:
            return cache.get(cache_key)
        except Exception as exc:
            self.logger.warning(
                "Cache fetch failed for %s: %s", cache_key, exc, exc_info=True
            )
            return None

    def set_cached(self, cache_type: str, data: Any, ttl_key: str, **kwargs):
        """Cache data with configured TTL and memory checks."""
        cache_key = self._get_cache_key(cache_type, **kwargs)
        ttl = CACHE_TTL.get(ttl_key, 3600)  # Default 1 hour

        # Check memory usage before caching large objects
        if ttl_key != 'project_snapshot' and self._should_skip_cache(data):
            self.logger.warning(f"Skipping cache for {cache_key} - memory pressure")
            return

        try:
            cache.set(cache_key, data, ttl)
            self.logger.debug(f"Cached {cache_type} for {ttl}s: {cache_key}")
        except Exception as exc:
            self.logger.warning(
                "Cache store failed for %s: %s", cache_key, exc, exc_info=True
            )

    def _should_skip_cache(self, data: Any) -> bool:
        """Check if we should skip caching due to memory pressure."""
        try:
            import sys
            import psutil

            # Check process memory usage
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024

            if memory_mb > CACHE_LIMITS['memory_threshold_mb']:
                return True

            # Check object size
            data_size_mb = sys.getsizeof(data) / 1024 / 1024
            if data_size_mb > 10:  # Skip objects > 10MB
                return True

        except Exception:
            # If memory check fails, allow caching
            pass

        return False

    def invalidate(self, cache_type: str, **kwargs):
        """Invalidate specific cache entry."""
        cache_key = self._get_cache_key(cache_type, **kwargs)
        try:
            cache.delete(cache_key)
            self.logger.info(f"Invalidated cache: {cache_key}")
        except Exception as exc:
            self.logger.warning(
                "Cache delete failed for %s: %s", cache_key, exc, exc_info=True
            )

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics for monitoring."""
        return {
            'ttl_config': CACHE_TTL,
            'prefix': self.prefix,
            'backend': cache.__class__.__name__,
            'timestamp': timezone.now().isoformat()
        }
