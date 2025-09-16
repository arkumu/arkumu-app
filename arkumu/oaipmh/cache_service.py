"""
Centralized OAI-PMH Cache Service

Provides unified caching strategy for OAI-PMH responses to avoid over-caching
and ensure consistent TTLs across the application.
"""

import logging
from typing import Dict, Optional, Any
from django.core.cache import cache
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

# Centralized TTL configuration (in seconds)
CACHE_TTL = {
    'record': 4 * 3600,      # 4 hours - individual records
    'page': 2 * 3600,        # 2 hours - list pages (fresher for pagination)
    'graph': 4 * 3600,       # 4 hours - graph data (same as records)
}


class OAIPMHCacheService:
    """Centralized cache service for OAI-PMH responses."""

    @staticmethod
    def _get_cache_key(cache_type: str, **kwargs) -> str:
        """Generate consistent cache keys."""
        if cache_type == "record":
            # Record cache key includes format and timestamp
            return f"oai:record:{kwargs['uri']}:{kwargs['metadata_prefix']}:{kwargs['timestamp']}"
        elif cache_type == "page":
            # Page cache key for ListRecords/ListIdentifiers
            verb = kwargs.get('verb', 'ListRecords')
            metadata_prefix = kwargs.get('metadata_prefix', 'oai_dc')
            set_spec = kwargs.get('set_spec', '')
            from_date = kwargs.get('from_date', '')
            until_date = kwargs.get('until_date', '')
            offset = kwargs.get('offset', 0)
            return f"oai:page:{verb}:{metadata_prefix}:{set_spec}:{from_date}:{until_date}:{offset}"
        elif cache_type == "graph":
            # Graph cache key - shared between DC and METS
            return f"oai:graph:{kwargs['uri']}:{kwargs.get('depth', 2)}:{kwargs['timestamp']}"
        return f"oai:{cache_type}:{':'.join(str(v) for v in kwargs.values())}"

    @classmethod
    def get_cached_record(cls, resource, metadata_prefix: str) -> Optional[Dict]:
        """Get cached record data if available."""
        timestamp = int(resource.updated_at.timestamp())
        cache_key = cls._get_cache_key(
            "record",
            uri=resource.uri,
            metadata_prefix=metadata_prefix,
            timestamp=timestamp
        )
        return cache.get(cache_key)

    @classmethod
    def cache_record(cls, resource, metadata_prefix: str, header_xml: str, metadata_xml: str):
        """Cache individual record data."""
        timestamp = int(resource.updated_at.timestamp())
        cache_key = cls._get_cache_key(
            "record",
            uri=resource.uri,
            metadata_prefix=metadata_prefix,
            timestamp=timestamp
        )

        cached_record = {
            'header': header_xml,
            'metadata': metadata_xml,
            'timestamp': timestamp
        }

        cache.set(cache_key, cached_record, CACHE_TTL['record'])
        logger.debug(f"✅ Cached {metadata_prefix} record for {resource.uri}")

    @classmethod
    def get_cached_page(cls, verb: str, metadata_prefix: str, set_spec: str = '',
                       from_date: str = '', until_date: str = '', offset: int = 0) -> Optional[Dict]:
        """Get cached page data if available."""
        cache_key = cls._get_cache_key(
            "page",
            verb=verb,
            metadata_prefix=metadata_prefix,
            set_spec=set_spec,
            from_date=from_date,
            until_date=until_date,
            offset=offset
        )
        return cache.get(cache_key)

    @classmethod
    def cache_page(cls, verb: str, metadata_prefix: str, page_data: Dict,
                  set_spec: str = '', from_date: str = '', until_date: str = '', offset: int = 0):
        """Cache page data."""
        cache_key = cls._get_cache_key(
            "page",
            verb=verb,
            metadata_prefix=metadata_prefix,
            set_spec=set_spec,
            from_date=from_date,
            until_date=until_date,
            offset=offset
        )
        cache.set(cache_key, page_data, CACHE_TTL['page'])
        logger.debug(f"✅ Cached {verb} page for {metadata_prefix} at offset {offset}")

    @classmethod
    def get_cached_graph(cls, resource_uri: str, depth: int, timestamp: int) -> Optional[Dict]:
        """Get cached graph data if available."""
        cache_key = cls._get_cache_key(
            "graph",
            uri=resource_uri,
            depth=depth,
            timestamp=timestamp
        )
        return cache.get(cache_key)

    @classmethod
    def cache_graph(cls, resource_uri: str, depth: int, timestamp: int, graph_data: Dict):
        """Cache graph data (shared between formats)."""
        cache_key = cls._get_cache_key(
            "graph",
            uri=resource_uri,
            depth=depth,
            timestamp=timestamp
        )
        cache.set(cache_key, graph_data, CACHE_TTL['graph'])
        logger.debug(f"✅ Cached graph for {resource_uri} at depth {depth}")

    @classmethod
    def warm_record(cls, resource, metadata_prefix: str):
        """
        Warm cache for a single record.
        Used by Huey tasks for pre-generating cache.
        """
        # Check if already cached
        if cls.get_cached_record(resource, metadata_prefix):
            logger.debug(f"⏭️ Record already cached: {resource.uri} ({metadata_prefix})")
            return

        # Import here to avoid circular imports
        from arkumu.oaipmh.views import _build_record_header, _build_metadata_element

        # Build record components
        header = _build_record_header(resource)
        metadata = _build_metadata_element(resource, metadata_prefix)

        # Convert to XML strings
        header_xml = ET.tostring(header, encoding='unicode')
        metadata_xml = ET.tostring(metadata, encoding='unicode')

        # Cache the record
        cls.cache_record(resource, metadata_prefix, header_xml, metadata_xml)

        logger.info(f"🔥 Warmed cache for {resource.uri} ({metadata_prefix})")

    @classmethod
    def invalidate_resource(cls, resource_uri: str):
        """
        Invalidate all cached data for a resource.
        Called when a resource is updated.
        """
        # Use wildcard pattern to clear all related cache entries
        pattern = f"oai:*:{resource_uri}:*"

        # Note: This requires cache backend that supports delete_pattern
        # For Redis: cache.delete_pattern(pattern)
        # For now, we'll just log it
        logger.info(f"🗑️ Would invalidate cache for pattern: {pattern}")

    @classmethod
    def get_cache_stats(cls) -> Dict[str, Any]:
        """Get cache statistics for monitoring."""
        # This would connect to cache backend for stats
        # Implementation depends on cache backend (Redis, Memcached, etc.)
        return {
            'ttl_config': CACHE_TTL,
            'backend': cache.__class__.__name__
        }