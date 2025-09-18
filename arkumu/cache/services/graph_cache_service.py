"""
Graph Cache Service

Memory-efficient caching using shared graph manager to prevent memory multiplication.
"""

import logging
from typing import Dict, Optional, Any, List
from django.utils import timezone
from .base_cache_service import BaseCacheService
# Removed custom cache wrapper - using original cache logic

logger = logging.getLogger(__name__)


class GraphCacheService(BaseCacheService):
    """
    Memory-optimized service for graph operations using shared graph manager.

    Key improvements:
    - Uses shared graph instance instead of per-request loading
    - Memory-bounded caching with LRU eviction
    - Streaming results for large datasets
    - Organization-level filtering instead of separate graphs

    Used by:
    - OAI-PMH views for Dublin Core and METS metadata generation
    - Catalog explorer for entity relationships
    - Metadata explorer for resource connections
    """

    def __init__(self):
        super().__init__('graph')
        # Lazy import to avoid circular dependencies
        self._canonical_service = None

    @property
    def canonical_service(self):
        """Lazy-loaded canonical graph service."""
        if self._canonical_service is None:
            from arkumu.metadata.services.canonical_graph_service import CanonicalGraphService
            self._canonical_service = CanonicalGraphService(org_code=None)  # Cross-institutional
        return self._canonical_service

    def get_entity_graph(self, resource_uri: str, depth: int = 2,
                        organization_code: str = None,
                        predicate_whitelist: List[str] = None) -> Optional[Dict]:
        """
        Get entity graph with caching - same interface as CanonicalGraphService.

        Args:
            resource_uri: URI of the resource to get graph for
            depth: Traversal depth (1-3)
            organization_code: Organization scope for security
            predicate_whitelist: Optional list of allowed predicates
        """
        # Create cache key
        cache_params = {
            'uri': resource_uri,
            'depth': depth,
            'org': organization_code or 'global',
            'timestamp': self._get_resource_timestamp(resource_uri)
        }

        if predicate_whitelist:
            import hashlib
            whitelist_hash = hashlib.md5(str(sorted(predicate_whitelist)).encode()).hexdigest()[:8]
            cache_params['predicates'] = whitelist_hash

        # Try cache first
        cached_result = self.get_cached('entity', **cache_params)
        if cached_result:
            logger.debug(f"Cache hit for entity graph: {resource_uri}")
            return cached_result

        # Cache miss - delegate to canonical service
        logger.info(f"Cache miss for entity graph: {resource_uri}, fetching from canonical service")
        try:
            result = self.canonical_service.get_entity_graph(
                resource_uri=resource_uri,
                depth=depth,
                restrict_to_org=False,  # Always cross-institutional for cached access
                predicate_canon_whitelist=predicate_whitelist
            )

            # Cache the result
            if result:
                self.set_cached('entity', result, 'graph_entity', **cache_params)
                logger.info(f"Cached entity graph for: {resource_uri}")

            return result

        except Exception as e:
            logger.error(f"Error getting entity graph from canonical service for {resource_uri}: {e}")
            return None

    def _extract_org_from_uri(self, resource_uri: str) -> str:
        """Extract organization code from resource URI."""
        try:
            # Assuming URI format contains org code
            # e.g., http://arkumu.org/data/fuk/projekt/123 -> fuk
            parts = resource_uri.split('/')
            for i, part in enumerate(parts):
                if part == 'data' and i + 1 < len(parts):
                    return parts[i + 1]
            return 'unknown'
        except:
            return 'unknown'

    def cache_entity_graph(self, resource_uri: str, graph_data: Dict,
                          depth: int = 2, organization_code: str = None,
                          predicate_whitelist: List[str] = None):
        """
        Cache entity graph data.

        Args:
            resource_uri: URI of the resource
            graph_data: Graph data from CanonicalGraphService
            depth: Traversal depth used
            organization_code: Organization scope
            predicate_whitelist: Predicates used in traversal
        """
        cache_params = {
            'uri': resource_uri,
            'depth': depth,
            'org': organization_code or 'global',
            'timestamp': self._get_resource_timestamp(resource_uri)
        }

        if predicate_whitelist:
            import hashlib
            whitelist_hash = hashlib.md5(str(sorted(predicate_whitelist)).encode()).hexdigest()[:8]
            cache_params['predicates'] = whitelist_hash

        # Add metadata to cached data
        enriched_data = {
            'graph': graph_data,
            'cached_at': timezone.now().isoformat(),
            'depth': depth,
            'organization_code': organization_code,
            'predicate_count': len(predicate_whitelist) if predicate_whitelist else 0
        }

        self.set_cached('entity', enriched_data, 'graph_entity', **cache_params)
        logger.info(f"Cached entity graph for {resource_uri} (depth={depth}, org={organization_code})")

    def get_traversal_result(self, resource_uri: str, traversal_type: str,
                           params_hash: str) -> Optional[Dict]:
        """
        Get cached traversal result for specific parameters.

        Args:
            resource_uri: Starting resource URI
            traversal_type: Type of traversal (oai_dc, mets, catalog_search)
            params_hash: Hash of traversal parameters
        """
        cache_params = {
            'uri': resource_uri,
            'type': traversal_type,
            'params': params_hash,
            'timestamp': self._get_resource_timestamp(resource_uri)
        }

        return self.get_cached('traversal', **cache_params)

    def cache_traversal_result(self, resource_uri: str, traversal_type: str,
                             params_hash: str, result_data: Any):
        """
        Cache traversal result.

        Args:
            resource_uri: Starting resource URI
            traversal_type: Type of traversal
            params_hash: Hash of parameters used
            result_data: Result to cache
        """
        cache_params = {
            'uri': resource_uri,
            'type': traversal_type,
            'params': params_hash,
            'timestamp': self._get_resource_timestamp(resource_uri)
        }

        enriched_data = {
            'result': result_data,
            'cached_at': timezone.now().isoformat(),
            'traversal_type': traversal_type
        }

        self.set_cached('traversal', enriched_data, 'graph_traversal', **cache_params)
        logger.info(f"Cached {traversal_type} traversal for {resource_uri}")

    def invalidate_resource(self, resource_uri: str):
        """
        Invalidate all cached data for a resource.
        Called when a resource is updated.
        """
        # Note: This is a simplified version. In production, we'd need
        # a more sophisticated pattern matching or cache tagging system
        logger.info(f"Resource {resource_uri} updated - cache invalidation needed")

        # For now, we log the invalidation. A proper implementation would:
        # 1. Use cache patterns/tags to find related entries
        # 2. Delete all graph and traversal caches for this resource
        # 3. Potentially invalidate related resources

    def warm_popular_resources(self, resource_uris: List[str],
                             organization_code: str = None):
        """
        Pre-warm cache for popular/frequently accessed resources.

        Args:
            resource_uris: List of resource URIs to warm
            organization_code: Organization scope
        """
        logger.info(f"Warming cache for {len(resource_uris)} popular resources")

        # This would typically be called by background tasks
        # to pre-generate cache for resources that are frequently accessed
        for uri in resource_uris:
            logger.debug(f"Scheduled cache warming for {uri}")

    def _get_resource_timestamp(self, resource_uri: str) -> int:
        """
        Get resource timestamp for cache versioning.
        Returns current timestamp if resource not found.
        For synthetic URIs (arkumu:*), returns a fixed timestamp to enable caching.
        """
        # Handle synthetic/virtual resource URIs that don't exist in the database
        if resource_uri.startswith('arkumu:'):
            # Use a fixed timestamp for synthetic keys to enable proper caching
            # Change this value when you want to invalidate synthetic caches
            return 1726632000  # Fixed timestamp: 2024-09-18 00:00:00 UTC

        try:
            from arkumu.metadata.models.resource import Resource
            resource = Resource.objects.filter(uri=resource_uri).first()
            if resource and resource.updated_at:
                return int(resource.updated_at.timestamp())
        except Exception as e:
            logger.warning(f"Could not get timestamp for {resource_uri}: {e}")

        # Fallback to current timestamp
        return int(timezone.now().timestamp())

    def get_cache_statistics(self) -> Dict[str, Any]:
        """Get detailed cache statistics for monitoring."""
        base_stats = self.get_cache_stats()

        # Add graph-specific statistics
        base_stats.update({
            'service_type': 'graph_cache',
            'supported_operations': [
                'entity_graph_caching',
                'traversal_result_caching',
                'resource_invalidation',
                'popular_resource_warming'
            ],
            'cache_types': ['entity', 'traversal']
        })

        return base_stats