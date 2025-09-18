"""
Simple cache wrapper for CanonicalGraphService.
Just cache the results, don't reimplement the logic.
"""

import logging
from typing import Dict, Optional
from django.core.cache import cache

logger = logging.getLogger(__name__)


class GraphCacheWrapper:
    """Cache wrapper for your existing CanonicalGraphService."""

    def get_project_graph(self, org_code: str, **kwargs) -> Dict:
        """Get project graph with caching."""

        # Create cache key from parameters
        cache_key = f"graph:projects:{org_code}:{hash(str(kwargs))}"

        # Try cache first
        cached = cache.get(cache_key)
        if cached:
            logger.debug(f"Cache hit for project graph {org_code}")
            return cached

        # Cache miss - use your existing service
        from arkumu.metadata.services.canonical_graph_service import CanonicalGraphService

        service = CanonicalGraphService(org_code=org_code)
        result = service.get_project_graph(**kwargs)

        # Cache for 30 minutes
        cache.set(cache_key, result, 1800)

        logger.info(f"Cached project graph for {org_code}: {result['counts']}")
        return result

    def get_entity_graph(self, org_code: str, resource_uri: str, **kwargs) -> Dict:
        """Get entity graph with caching."""

        cache_key = f"graph:entity:{org_code}:{resource_uri}:{hash(str(kwargs))}"

        cached = cache.get(cache_key)
        if cached:
            logger.debug(f"Cache hit for entity graph {resource_uri}")
            return cached

        from arkumu.metadata.services.canonical_graph_service import CanonicalGraphService

        service = CanonicalGraphService(org_code=org_code)
        result = service.get_entity_graph(resource_uri, **kwargs)

        # Cache for 30 minutes
        cache.set(cache_key, result, 1800)

        logger.info(f"Cached entity graph for {resource_uri}: {result['counts']}")
        return result

    def invalidate_org(self, org_code: str):
        """Clear cache for organization."""
        # Simple: clear everything (could be more targeted)
        cache.clear()
        logger.info(f"Cache cleared for {org_code}")


# Global instance
graph_cache = GraphCacheWrapper()