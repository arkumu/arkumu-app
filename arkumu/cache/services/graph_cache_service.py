"""
Graph Cache Service

Memory-efficient caching using shared graph manager to prevent memory multiplication.
"""

import logging
from typing import Dict, Optional, Any, List
from uuid import uuid4
from django.core.cache import cache
from django.utils import timezone
from .base_cache_service import BaseCacheService, CACHE_TTL
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
        self._org_scoped_services: Dict[str, Any] = {}

    @property
    def canonical_service(self):
        """Lazy-loaded canonical graph service."""
        if self._canonical_service is None:
            from arkumu.metadata.services.canonical_graph_service import CanonicalGraphService
            self._canonical_service = CanonicalGraphService(org_code=None)  # Cross-institutional
        return self._canonical_service

    def _get_canonical_service(self, organization_code: Optional[str], restrict_to_org: bool):
        """Get canonical service respecting organization scoping when requested."""
        from arkumu.metadata.services.canonical_graph_service import CanonicalGraphService

        if restrict_to_org and organization_code:
            if organization_code not in self._org_scoped_services:
                self._org_scoped_services[organization_code] = CanonicalGraphService(org_code=organization_code)
            return self._org_scoped_services[organization_code]

        return self.canonical_service

    def _build_cache_params(
        self,
        *,
        resource_uri: str,
        depth: int,
        organization_code: Optional[str],
        predicate_whitelist: Optional[List[str]],
        include_incoming: bool,
        expand_neighbors: bool,
        restrict_to_org: bool,
        neighbor_predicate_whitelist: Optional[List[str]],
    ) -> Dict[str, Any]:
        """Create deterministic cache parameters with optional predicate hashing."""
        cache_params = {
            'uri': resource_uri,
            'depth': depth,
            'org': organization_code or 'global',
            'timestamp': self._get_resource_timestamp(resource_uri),
            'incoming': int(include_incoming),
            'expand': int(expand_neighbors),
            'restrict': int(restrict_to_org),
        }

        if predicate_whitelist:
            cache_params['predicates'] = self._hash_predicate_list(predicate_whitelist)

        if neighbor_predicate_whitelist:
            cache_params['neighbor_predicates'] = self._hash_predicate_list(neighbor_predicate_whitelist)

        return cache_params

    @staticmethod
    def _hash_predicate_list(predicate_whitelist: List[str]) -> str:
        import hashlib

        return hashlib.md5(
            str(sorted(predicate_whitelist)).encode()
        ).hexdigest()[:8]

    def _wrap_graph_payload(
        self,
        *,
        graph_data: Optional[Dict],
        depth: int,
        organization_code: Optional[str],
        predicate_whitelist: Optional[List[str]],
        include_incoming: bool,
        expand_neighbors: bool,
        restrict_to_org: bool,
        neighbor_predicate_whitelist: Optional[List[str]],
        source: str,
    ) -> Dict[str, Any]:
        """Normalize graph payload structure for all consumers."""
        return {
            'graph': graph_data or {},
            'meta': {
                'cached_at': timezone.now().isoformat(),
                'depth': depth,
                'organization_code': organization_code or 'global',
                'predicate_whitelist': predicate_whitelist or [],
                'predicate_hash': self._hash_predicate_list(predicate_whitelist) if predicate_whitelist else None,
                'neighbor_predicate_whitelist': neighbor_predicate_whitelist or [],
                'neighbor_predicate_hash': self._hash_predicate_list(neighbor_predicate_whitelist) if neighbor_predicate_whitelist else None,
                'include_incoming': include_incoming,
                'expand_neighbors': expand_neighbors,
                'restrict_to_org': restrict_to_org,
                'source': source
            }
        }

    def get_entity_graph(
        self,
        resource_uri: str,
        depth: int = 2,
        organization_code: str = None,
        predicate_whitelist: Optional[List[str]] = None,
        *,
        include_incoming: bool = True,
        expand_neighbors: bool = True,
        restrict_to_org: bool = False,
        neighbor_predicate_whitelist: Optional[List[str]] = None,
    ) -> Optional[Dict]:
        """
        Get entity graph with caching - same interface as CanonicalGraphService.

        Args:
            resource_uri: URI of the resource to get graph for
            depth: Traversal depth (1-3)
            organization_code: Organization scope for security
            predicate_whitelist: Optional list of allowed predicates
        """
        cache_params = self._build_cache_params(
            resource_uri=resource_uri,
            depth=depth,
            organization_code=organization_code,
            predicate_whitelist=predicate_whitelist,
            include_incoming=include_incoming,
            expand_neighbors=expand_neighbors,
            restrict_to_org=restrict_to_org and bool(organization_code),
            neighbor_predicate_whitelist=neighbor_predicate_whitelist,
        )

        # Try cache first
        cached_result = self.get_cached('entity', **cache_params)
        if cached_result:
            logger.debug(f"Cache hit for entity graph: {resource_uri}")
            return cached_result

        # Cache miss - delegate to canonical service
        logger.info(f"Cache miss for entity graph: {resource_uri}, fetching from canonical service")
        try:
            effective_restrict = restrict_to_org and bool(organization_code)
            canonical_service = self._get_canonical_service(organization_code, effective_restrict)

            canonical_graph = canonical_service.get_entity_graph(
                resource_uri=resource_uri,
                depth=depth,
                restrict_to_org=effective_restrict,
                predicate_canon_whitelist=predicate_whitelist,
                include_incoming=include_incoming,
                expand_neighbors=expand_neighbors,
                neighbor_predicate_canon_whitelist=neighbor_predicate_whitelist
            )

            # Cache the result
            if canonical_graph is not None:
                payload = self._wrap_graph_payload(
                    graph_data=canonical_graph,
                    depth=depth,
                    organization_code=organization_code,
                    predicate_whitelist=predicate_whitelist,
                    include_incoming=include_incoming,
                    expand_neighbors=expand_neighbors,
                    restrict_to_org=effective_restrict,
                    neighbor_predicate_whitelist=neighbor_predicate_whitelist,
                    source='canonical_service'
                )
                self.set_cached('entity', payload, 'graph_entity', **cache_params)
                logger.info(f"Cached entity graph for: {resource_uri}")
                return payload

            return None

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

    def cache_entity_graph(
        self,
        resource_uri: str,
        graph_data: Dict,
        depth: int = 2,
        organization_code: str = None,
        predicate_whitelist: Optional[List[str]] = None,
        *,
        include_incoming: bool = True,
        expand_neighbors: bool = True,
        restrict_to_org: bool = False,
        neighbor_predicate_whitelist: Optional[List[str]] = None,
    ):
        """
        Cache entity graph data.

        Args:
            resource_uri: URI of the resource
            graph_data: Graph data from CanonicalGraphService
            depth: Traversal depth used
            organization_code: Organization scope
            predicate_whitelist: Predicates used in traversal
        """
        cache_params = self._build_cache_params(
            resource_uri=resource_uri,
            depth=depth,
            organization_code=organization_code,
            predicate_whitelist=predicate_whitelist,
            include_incoming=include_incoming,
            expand_neighbors=expand_neighbors,
            restrict_to_org=restrict_to_org and bool(organization_code),
            neighbor_predicate_whitelist=neighbor_predicate_whitelist,
        )

        payload = self._wrap_graph_payload(
            graph_data=graph_data,
            depth=depth,
            organization_code=organization_code,
            predicate_whitelist=predicate_whitelist,
            include_incoming=include_incoming,
            expand_neighbors=expand_neighbors,
            restrict_to_org=restrict_to_org and bool(organization_code),
            neighbor_predicate_whitelist=neighbor_predicate_whitelist,
            source='manual_cache'
        )

        self.set_cached('entity', payload, 'graph_entity', **cache_params)
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

        if self._should_skip_cache(enriched_data):
            self.logger.warning(
                "Skipping traversal cache for %s due to memory limits", resource_uri
            )
            return

        cache_key = self._get_cache_key('traversal', **cache_params)
        ttl = CACHE_TTL.get('graph_traversal', 3600)

        temp_cache_key = f"{cache_key}:staging:{uuid4().hex}"
        cache.set(temp_cache_key, enriched_data, ttl)
        cache.set(cache_key, enriched_data, ttl)
        cache.delete(temp_cache_key)

        logger.info(
            "Cached %s traversal for %s via atomic swap", traversal_type, resource_uri
        )

    def invalidate_resource(self, resource_uri: str):
        """
        Invalidate all cached data for a resource.
        Called when a resource is updated.
        """
        logger.info(f"Resource {resource_uri} updated - invalidating graph cache entries")

        patterns = [
            f"{self.prefix}:entity:*:uri:{resource_uri}",
            f"{self.prefix}:traversal:*:uri:{resource_uri}"
        ]

        if hasattr(cache, 'delete_pattern'):
            for pattern in patterns:
                cache.delete_pattern(pattern)
                logger.debug(f"Deleted cache pattern {pattern}")
        else:
            logger.warning(
                "Cache backend does not support delete_pattern; "
                "graph cache invalidation may leave residual entries for %s",
                resource_uri
            )

    def warm_popular_resources(self, resource_uris: List[str],
                             organization_code: str = None):
        """
        Pre-warm cache for popular/frequently accessed resources.

        Args:
            resource_uris: List of resource URIs to warm
            organization_code: Organization scope
        """
        logger.info(f"Warming cache for {len(resource_uris)} popular resources")

        for uri in resource_uris:
            try:
                self.get_entity_graph(
                    resource_uri=uri,
                    depth=2,
                    organization_code=organization_code,
                    include_incoming=True,
                    expand_neighbors=True,
                    restrict_to_org=bool(organization_code)
                )
            except Exception as exc:
                logger.warning(f"Warm-up failed for {uri}: {exc}")

    def _get_resource_timestamp(self, resource_uri: str) -> int:
        """
        Get resource timestamp for cache versioning.
        Returns a stable fallback when the resource is unavailable so cache keys
        remain deterministic, even for synthetic URIs.
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

        # Fallback to stable epoch-based version to avoid cache churn
        return 0

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

    def _build_cross_institutional_projects_graph(self) -> Dict[str, Any]:
        """
        Build cross-institutional projects graph by reusing existing view logic.
        """
        logger.info("Building cross-institutional projects graph using existing view logic...")

        # Import here to avoid circular imports
        from arkumu.catalog.views.cards import GraphSearchView

        # Create a mock request-like object for the view
        class MockRequest:
            def __init__(self):
                self.GET = {'query': ''}
                self.headers = {}

        class MockUser:
            def __init__(self):
                self.organization = None
                self.username = 'system'

        # Use the existing GraphSearchView logic but bypass the request handling
        view = GraphSearchView()

        # Get the graph from cards.py logic (lines 56-116)
        from arkumu.metadata.services.canonical_graph_service import CanonicalGraphService

        service = CanonicalGraphService()  # No org = search all institutions

        # Use CANONICAL URI to get all projects across institutions
        canonical_project_uri = "http://arkumu.org/data/types/projekt"
        all_subject_ids = service._find_subject_ids_by_class(canonical_project_uri)
        logger.info(f"Found {len(all_subject_ids)} projects using canonical URI")

        # Fallback to institution-specific URIs if needed
        if not all_subject_ids:
            logger.info("No projects via canonical URI, falling back to institution-specific")
            institution_uris = [
                "http://arkumu.org/data/fuk/types/projekt",
                "http://arkumu.org/data/rsh/types/projekt",
                "http://arkumu.org/data/det/types/projekt",
                "http://arkumu.org/data/khm/types/projekt",
                "http://arkumu.org/data/uk/types/projekt",
                "http://arkumu.org/data/hfmt/types/projekt",
            ]
            for uri in institution_uris:
                subject_ids = service._find_subject_ids_by_class(uri)
                all_subject_ids.extend(subject_ids)
                logger.info(f"Found {len(subject_ids)} subjects for {uri}")

        # Get the whole graph for all these subjects
        edges = service._fetch_triples_for_subjects(all_subject_ids)

        if edges:
            # Get neighbor expansion if needed
            neighbor_ids = [e.object_id for e in edges if e.object_type != 'LITERAL'][:100]
            if neighbor_ids:
                neighbor_edges = service._fetch_triples_for_subjects(neighbor_ids)
                edges.extend(neighbor_edges)

        # Collect all nodes
        nodes = service._collect_nodes_from_edges(edges)

        # Build complete graph (same format as cards.py)
        graph_data = {
            "organization": "cross-institutional",
            "dataset": "Projekt",
            "subjects": all_subject_ids,
            "nodes": nodes,
            "edges": [e.__dict__ for e in edges],
            "counts": {
                "subjects": len(all_subject_ids),
                "nodes": len(nodes),
                "edges": len(edges),
            },
        }

        logger.info(f"Built cross-institutional graph: {graph_data['counts']['subjects']} projects, {graph_data['counts']['edges']} edges")
        return graph_data

    def refresh_cross_institutional_projects_cache(self, *, force_refresh: bool = False) -> Optional[Dict]:
        """Refresh cross-institutional projects cache, optionally forcing a rebuild."""

        cache_resource_uri = "arkumu:cross_institutional:all_projects"
        cache_params_hash = "cross_institutional_projects_canonical"

        try:
            existing_projects = self.get_traversal_result(
                resource_uri=cache_resource_uri,
                traversal_type="catalog_projects",
                params_hash=cache_params_hash,
            )
            existing_graph = self.get_traversal_result(
                resource_uri=cache_resource_uri,
                traversal_type="catalog_search",
                params_hash=cache_params_hash,
            )

            projects_payload = existing_projects.get('result') if existing_projects else None
            graph_payload = existing_graph.get('result') if existing_graph else None

            if not force_refresh and projects_payload and projects_payload.get('projects'):
                # Touch existing entries to extend TTL without doing a full rebuild.
                self.cache_traversal_result(
                    resource_uri=cache_resource_uri,
                    traversal_type="catalog_projects",
                    params_hash=cache_params_hash,
                    result_data=projects_payload,
                )

                if graph_payload:
                    self.cache_traversal_result(
                        resource_uri=cache_resource_uri,
                        traversal_type="catalog_search",
                        params_hash=cache_params_hash,
                        result_data=graph_payload,
                    )

                project_count = len(projects_payload.get('projects', []))
                edge_count = (
                    graph_payload.get('counts', {}).get('edges')
                    if isinstance(graph_payload, dict)
                    else 'unknown'
                )
                logger.info(
                    "Cross-institutional projects cache touched (no rebuild needed): %s projects, %s edges",
                    project_count,
                    edge_count,
                )

                return {
                    "projects": projects_payload.get('projects', []),
                    "graph": graph_payload,
                    "counts": graph_payload.get('counts') if isinstance(graph_payload, dict) else None,
                    "cached_at": timezone.now().isoformat(),
                }

            logger.info(
                "Cross-institutional projects cache rebuild triggered (force_refresh=%s)",
                force_refresh,
            )

            from arkumu.metadata.services.canonical_graph_service import CanonicalGraphService

            service = CanonicalGraphService()  # No org = search all institutions
            canonical_project_uri = "http://arkumu.org/data/types/projekt"
            all_subject_ids = service._find_subject_ids_by_class(canonical_project_uri)
            logger.info(f"Found {len(all_subject_ids)} projects using canonical URI")

            normalized_subject_ids = [str(subject_id) for subject_id in all_subject_ids]

            if not normalized_subject_ids:
                institution_uris = [
                    "http://arkumu.org/data/fuk/types/projekt",
                    "http://arkumu.org/data/rsh/types/projekt",
                    "http://arkumu.org/data/det/types/projekt",
                    "http://arkumu.org/data/khm/types/projekt",
                    "http://arkumu.org/data/uk/types/projekt",
                    "http://arkumu.org/data/hfmt/types/projekt",
                ]
                for uri in institution_uris:
                    subject_ids = service._find_subject_ids_by_class(uri)
                    normalized_subject_ids.extend(str(subject_id) for subject_id in subject_ids)
                    logger.info(f"Found {len(subject_ids)} subjects for {uri}")

            edges = service._fetch_triples_for_subjects(normalized_subject_ids)
            if edges:
                neighbor_ids = [e.object_id for e in edges if e.object_type != 'LITERAL'][:100]
                if neighbor_ids:
                    neighbor_edges = service._fetch_triples_for_subjects(neighbor_ids)
                    edges.extend(neighbor_edges)

            nodes = service._collect_nodes_from_edges(edges)
            graph = {
                "organization": "cross-institutional",
                "dataset": "Projekt",
                "subjects": normalized_subject_ids,
                "nodes": nodes,
                "edges": [e.__dict__ for e in edges],
                "counts": {
                    "subjects": len(normalized_subject_ids),
                    "nodes": len(nodes),
                    "edges": len(edges),
                },
            }

            from arkumu.catalog.views.catalog_view import CatalogView
            from arkumu.catalog.services.schema_manifest_service import SchemaManifestService

            catalog_view = CatalogView()
            schema_service = SchemaManifestService()
            card_schema = schema_service.get_card_schema('fuk')  # Use FUK for consistent schema

            all_projects = catalog_view._graph_to_cards(graph, card_schema)

            self.cache_traversal_result(
                resource_uri=cache_resource_uri,
                traversal_type="catalog_search",
                params_hash=cache_params_hash,
                result_data=graph,
            )

            projects_payload = {'projects': all_projects}
            self.cache_traversal_result(
                resource_uri=cache_resource_uri,
                traversal_type="catalog_projects",
                params_hash=cache_params_hash,
                result_data=projects_payload,
            )

            logger.info(
                "Cached %s project cards and raw graph (%s subjects, %s edges)",
                len(all_projects),
                graph['counts']['subjects'],
                graph['counts']['edges'],
            )

            logger.info("Cross-institutional projects cache refreshed via rebuild")

            return {
                "projects": all_projects,
                "graph": graph,
                "counts": graph['counts'],
                "cached_at": timezone.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Failed to refresh cross-institutional projects cache: {e}")
            return None
