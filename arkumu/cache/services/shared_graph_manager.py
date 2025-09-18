"""
Shared Graph Manager

Memory-efficient singleton for managing graph data across concurrent users.
Prevents memory multiplication by sharing one graph instance with filtered access.
"""

import logging
import threading
import psutil
import time
from typing import Dict, Optional, Any, List, Set
from collections import OrderedDict
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)


class MemoryBoundedCache:
    """LRU cache with memory pressure management."""

    def __init__(self, max_memory_mb: int = 512, max_items: int = 1000):
        self.max_memory_bytes = max_memory_mb * 1024 * 1024
        self.max_items = max_items
        self.cache = OrderedDict()
        self.lock = threading.RLock()
        self._memory_usage = 0

    def get(self, key: str) -> Optional[Any]:
        with self.lock:
            if key in self.cache:
                # Move to end (most recently used)
                value = self.cache.pop(key)
                self.cache[key] = value
                return value
        return None

    def set(self, key: str, value: Any) -> bool:
        """Set value with memory bounds checking."""
        import sys
        value_size = sys.getsizeof(value)

        with self.lock:
            # Check if we need to evict
            while (self._memory_usage + value_size > self.max_memory_bytes or
                   len(self.cache) >= self.max_items):
                if not self.cache:
                    break
                # Remove least recently used item
                old_key, old_value = self.cache.popitem(last=False)
                self._memory_usage -= sys.getsizeof(old_value)
                logger.debug(f"Evicted cache item {old_key}, freed {sys.getsizeof(old_value)} bytes")

            # Add new item
            if key in self.cache:
                old_value = self.cache.pop(key)
                self._memory_usage -= sys.getsizeof(old_value)

            self.cache[key] = value
            self._memory_usage += value_size

            logger.debug(f"Cached {key}, using {self._memory_usage / 1024 / 1024:.1f}MB")
            return True

    def clear(self):
        with self.lock:
            self.cache.clear()
            self._memory_usage = 0

    def get_stats(self) -> Dict:
        with self.lock:
            return {
                'items': len(self.cache),
                'memory_mb': self._memory_usage / 1024 / 1024,
                'max_memory_mb': self.max_memory_bytes / 1024 / 1024,
                'hit_ratio': getattr(self, '_hits', 0) / max(getattr(self, '_requests', 1), 1)
            }


class SharedGraphManager:
    """
    Singleton manager for shared graph data across all users.

    Key optimizations:
    1. Single graph instance shared across all users
    2. Organization-level filtering instead of separate graphs
    3. Memory-bounded caching with LRU eviction
    4. Connection pooling for graph database
    5. Streaming results for large datasets
    """

    _instance = None
    _lock = threading.RLock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return

        self._initialized = True
        self.lock = threading.RLock()

        # Memory configuration
        max_memory = getattr(settings, 'GRAPH_CACHE_MAX_MEMORY_MB', 512)
        max_items = getattr(settings, 'GRAPH_CACHE_MAX_ITEMS', 1000)

        # Memory-bounded caches
        self.entity_cache = MemoryBoundedCache(max_memory // 2, max_items // 2)
        self.traversal_cache = MemoryBoundedCache(max_memory // 2, max_items // 2)

        # Shared graph connection (lazy-loaded)
        self._graph_connection = None
        self._connection_lock = threading.RLock()

        # Performance tracking
        self.stats = {
            'requests': 0,
            'cache_hits': 0,
            'memory_evictions': 0,
            'connection_reuses': 0
        }

        logger.info(f"SharedGraphManager initialized with {max_memory}MB memory limit")

    def get_graph_connection(self):
        """Get shared graph connection with connection pooling."""
        with self._connection_lock:
            if self._graph_connection is None:
                from arkumu.catalog.services.graph_search_service import GraphSearchService
                # Create connection but don't load full graph into memory
                self._graph_connection = GraphSearchService()
                logger.info("Created shared graph connection")
            else:
                self.stats['connection_reuses'] += 1

            return self._graph_connection

    def get_filtered_projects(self, organization_code: str,
                            filters: Dict = None,
                            limit: int = 100,
                            offset: int = 0) -> Dict:
        """
        Get projects for organization using shared graph with streaming.

        Instead of loading full graph per org, filter shared data.
        """
        self.stats['requests'] += 1

        # Create cache key for this specific request
        cache_key = f"projects:{organization_code}:{hash(str(filters))}:{limit}:{offset}"

        # Try cache first
        cached_result = self.entity_cache.get(cache_key)
        if cached_result:
            self.stats['cache_hits'] += 1
            logger.debug(f"Cache hit for {organization_code} projects")
            return cached_result

        # Cache miss - get from shared connection
        with self.lock:
            try:
                graph_service = self.get_graph_connection()

                # Stream results instead of loading full graph
                projects = self._stream_organization_projects(
                    graph_service, organization_code, filters, limit, offset
                )

                result = {
                    'projects': projects,
                    'organization': organization_code,
                    'total_count': len(projects),
                    'cached_at': timezone.now().isoformat(),
                    'cache_key': cache_key
                }

                # Cache with memory bounds
                self.entity_cache.set(cache_key, result)

                logger.info(f"Loaded {len(projects)} projects for {organization_code}")
                return result

            except Exception as e:
                logger.error(f"Error getting projects for {organization_code}: {e}")
                return {'projects': [], 'error': str(e)}

    def _stream_organization_projects(self, graph_service, org_code: str,
                                    filters: Dict, limit: int, offset: int) -> List[Dict]:
        """
        Stream projects from PostgreSQL with proper pagination to prevent memory issues.

        Instead of loading all data into memory, use database-level pagination.
        """
        try:
            from django.db import connection

            # Build dynamic SQL with filters
            where_conditions = ["organization_code = %s"]
            params = [org_code]

            # Add additional filters if provided
            if filters.get('resource_uri'):
                where_conditions.append("uri = %s")
                params.append(filters['resource_uri'])

            if filters.get('category'):
                where_conditions.append("category ILIKE %s")
                params.append(f"%{filters['category']}%")

            # Construct SQL with LIMIT/OFFSET for memory efficiency
            sql = f"""
            SELECT
                uri,
                title,
                subtitle,
                institution,
                year,
                category,
                description
            FROM projects
            WHERE {' AND '.join(where_conditions)}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """

            params.extend([limit, offset])

            # Execute with database cursor (memory efficient)
            with connection.cursor() as cursor:
                cursor.execute(sql, params)

                # Fetch results in batches to avoid memory spikes
                projects = []
                while True:
                    batch = cursor.fetchmany(50)  # Fetch 50 at a time
                    if not batch:
                        break

                    for row in batch:
                        projects.append({
                            'uri': row[0],
                            'title': row[1] or '',
                            'subtitle': row[2] or '',
                            'institution': row[3] or '',
                            'year': row[4] or '',
                            'category': row[5] or '',
                            'description': row[6] or ''
                        })

            logger.info(f"Streamed {len(projects)} projects for {org_code} from database")
            return projects

        except Exception as e:
            logger.error(f"Error streaming projects from database for {org_code}: {e}")
            # Fallback to existing method
            return self._fallback_get_projects(graph_service, org_code, limit, offset)

    def _extract_project_data(self, graph, project_uri) -> Dict:
        """Extract project data from RDFLib graph for a specific project URI."""
        try:
            from rdflib import URIRef

            project_data = {'uri': str(project_uri)}

            # Define the properties we want to extract
            properties = {
                'title': URIRef("http://arkumu.org/data/properties/bevorzugter-titel"),
                'subtitle': URIRef("http://arkumu.org/data/properties/bevorzugter-untertitel"),
                'institution': URIRef("http://arkumu.org/data/properties/einliefernde-hochschule"),
                'category': URIRef("http://arkumu.org/data/properties/projektkategorie")
            }

            # Extract each property
            for key, predicate in properties.items():
                values = list(graph.objects(project_uri, predicate))
                if values:
                    project_data[key] = str(values[0])  # Take first value
                else:
                    project_data[key] = ''

            # Handle event/year specially (nested property)
            event_predicate = URIRef("http://arkumu.org/data/properties/ereignis")
            events = list(graph.objects(project_uri, event_predicate))
            if events:
                event_uri = events[0]
                start_predicate = URIRef("http://arkumu.org/data/properties/ereignisbeginn")
                years = list(graph.objects(event_uri, start_predicate))
                if years:
                    project_data['year'] = str(years[0])
                else:
                    project_data['year'] = ''
            else:
                project_data['year'] = ''

            return project_data

        except Exception as e:
            logger.error(f"Error extracting project data for {project_uri}: {e}")
            return None

    def _fallback_get_projects(self, graph_service, org_code: str,
                              limit: int, offset: int) -> List[Dict]:
        """Fallback to existing method with memory limits."""
        try:
            # Get projects but limit memory usage
            all_projects = graph_service.get_project_graph(org_code)

            if not all_projects or 'projects' not in all_projects:
                return []

            # Apply pagination to limit memory
            projects = all_projects['projects'][offset:offset + limit]

            return projects

        except Exception as e:
            logger.error(f"Fallback method failed for {org_code}: {e}")
            return []

    def invalidate_organization(self, organization_code: str):
        """Invalidate all cached data for an organization."""
        with self.lock:
            # Remove all cache entries for this organization
            keys_to_remove = []

            for key in self.entity_cache.cache.keys():
                if f":{organization_code}:" in key:
                    keys_to_remove.append(key)

            for key in self.traversal_cache.cache.keys():
                if f":{organization_code}:" in key:
                    keys_to_remove.append(key)

            for key in keys_to_remove:
                if key in self.entity_cache.cache:
                    del self.entity_cache.cache[key]
                if key in self.traversal_cache.cache:
                    del self.traversal_cache.cache[key]

            logger.info(f"Invalidated {len(keys_to_remove)} cache entries for {organization_code}")

    def get_memory_usage(self) -> Dict:
        """Get current memory usage statistics."""
        process = psutil.Process()
        memory_info = process.memory_info()

        return {
            'process_memory_mb': memory_info.rss / 1024 / 1024,
            'entity_cache': self.entity_cache.get_stats(),
            'traversal_cache': self.traversal_cache.get_stats(),
            'performance_stats': self.stats,
            'cache_efficiency': {
                'hit_ratio': self.stats['cache_hits'] / max(self.stats['requests'], 1),
                'connection_reuse_ratio': self.stats['connection_reuses'] / max(self.stats['requests'], 1)
            }
        }

    def health_check(self) -> Dict:
        """Check if manager is healthy and within memory bounds."""
        memory_stats = self.get_memory_usage()
        process_memory = memory_stats['process_memory_mb']

        # Alert if using more than 1GB
        is_healthy = process_memory < 1024

        return {
            'healthy': is_healthy,
            'memory_usage_mb': process_memory,
            'warnings': [] if is_healthy else [f"High memory usage: {process_memory:.1f}MB"],
            'cache_stats': memory_stats
        }

    def clear_all_caches(self):
        """Emergency cache clear for memory pressure."""
        with self.lock:
            self.entity_cache.clear()
            self.traversal_cache.clear()
            self.stats['memory_evictions'] += 1
            logger.warning("Emergency cache clear executed")


# Global singleton instance
graph_manager = SharedGraphManager()