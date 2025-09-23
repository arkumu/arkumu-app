"""
OAI-PMH Cache Service

Specialized caching service for OAI-PMH responses, building on the centralized cache foundation.
"""

import logging
from typing import Dict, Optional, Any
import xml.etree.ElementTree as ET
from django.utils import timezone
from .base_cache_service import BaseCacheService
from .graph_cache_service import GraphCacheService

logger = logging.getLogger(__name__)


class OAICacheService(BaseCacheService):
    """
    Centralized cache service for OAI-PMH responses.

    Handles caching of:
    - Individual record metadata (Dublin Core, METS)
    - Page responses (ListRecords, ListIdentifiers)
    - Graph data integration
    """

    def __init__(self):
        super().__init__('oai')
        self.graph_cache = GraphCacheService()

    def get_cached_record(self, resource, metadata_prefix: str, profile_version: str = "") -> Optional[Dict]:
        """Get cached record data if available."""
        cache_params = {
            'uri': resource.uri,
            'metadata_prefix': metadata_prefix,
            'timestamp': int(resource.updated_at.timestamp()),
            'profile_version': profile_version,
        }
        return self.get_cached('record', **cache_params)

    def cache_record(self, resource, metadata_prefix: str, header_xml: str, metadata_xml: str, profile_version: str = ""):
        """Cache individual record data."""
        cache_params = {
            'uri': resource.uri,
            'metadata_prefix': metadata_prefix,
            'timestamp': int(resource.updated_at.timestamp()),
            'profile_version': profile_version,
        }

        cached_record = {
            'header': header_xml,
            'metadata': metadata_xml,
            'timestamp': cache_params['timestamp'],
            'cached_at': timezone.now().isoformat()
        }

        self.set_cached('record', cached_record, 'oai_record', **cache_params)
        logger.debug(f"Cached {metadata_prefix} record for {resource.uri}")

    def get_cached_page(self, verb: str, metadata_prefix: str, set_spec: str = '',
                       from_date: str = '', until_date: str = '', offset: int = 0) -> Optional[Dict]:
        """Get cached page data if available."""
        cache_params = {
            'verb': verb,
            'metadata_prefix': metadata_prefix,
            'set_spec': set_spec,
            'from_date': from_date,
            'until_date': until_date,
            'offset': offset
        }
        return self.get_cached('page', **cache_params)

    def cache_page(self, verb: str, metadata_prefix: str, page_data: Dict,
                  set_spec: str = '', from_date: str = '', until_date: str = '', offset: int = 0):
        """Cache page data."""
        cache_params = {
            'verb': verb,
            'metadata_prefix': metadata_prefix,
            'set_spec': set_spec,
            'from_date': from_date,
            'until_date': until_date,
            'offset': offset
        }

        enriched_data = {
            **page_data,
            'cached_at': timezone.now().isoformat()
        }

        self.set_cached('page', enriched_data, 'oai_page', **cache_params)
        logger.debug(f"Cached {verb} page for {metadata_prefix} at offset {offset}")

    def warm_record(self, resource, metadata_prefix: str):
        """
        Warm cache for a single record using the centralized approach.

        This integrates with the graph cache service to avoid duplicate work.
        """
        # Check if already cached
        if self.get_cached_record(resource, metadata_prefix):
            logger.debug(f"Record already cached: {resource.uri} ({metadata_prefix})")
            return

        # Import here to avoid circular imports
        from arkumu.oaipmh.views import _build_record_header, _build_metadata_element

        try:
            # Build record components
            header = _build_record_header(resource)
            metadata = _build_metadata_element(resource, metadata_prefix)

            # Convert to XML strings
            header_xml = ET.tostring(header, encoding='unicode')
            metadata_xml = ET.tostring(metadata, encoding='unicode')

            # Cache the record
            self.cache_record(resource, metadata_prefix, header_xml, metadata_xml)
            logger.info(f"Warmed cache for {resource.uri} ({metadata_prefix})")

        except Exception as e:
            logger.error(f"Error warming cache for {resource.uri}: {str(e)}")
            raise

    def warm_resource_with_graph_integration(self, resource, metadata_prefixes: list = None):
        """
        Warm cache for a resource with graph cache integration.

        This method coordinates between OAI and graph caching to maximize efficiency.
        """
        if metadata_prefixes is None:
            metadata_prefixes = ['oai_dc', 'mets']

        logger.info(f"Warming integrated cache for {resource.uri}")

        # Check if we need to warm the underlying graph data first
        # This could be shared between multiple metadata formats
        org_code = resource.organization.code if resource.organization else None

        try:
            self.graph_cache.get_entity_graph(
                resource_uri=resource.uri,
                depth=3,
                organization_code=org_code,
                include_incoming=True,
                expand_neighbors=True,
                restrict_to_org=bool(org_code)
            )
        except Exception as exc:
            logger.warning(f"Graph warm-up skipped for {resource.uri}: {exc}")

        # Warm cache for each requested format
        for metadata_prefix in metadata_prefixes:
            try:
                self.warm_record(resource, metadata_prefix)
            except Exception as e:
                logger.error(f"Error warming {metadata_prefix} cache for {resource.uri}: {str(e)}")

    def invalidate_resource(self, resource_uri: str):
        """
        Invalidate all OAI-PMH cached data for a resource.
        Also triggers graph cache invalidation.
        """
        logger.info(f"Invalidating OAI cache for resource: {resource_uri}")

        # Invalidate graph cache as well
        self.graph_cache.invalidate_resource(resource_uri)

        # Note: This is a simplified implementation
        # In production, we'd need pattern matching to find all related cache entries

    def get_cache_statistics(self) -> Dict[str, Any]:
        """Get detailed OAI cache statistics."""
        base_stats = self.get_cache_stats()

        base_stats.update({
            'service_type': 'oai_cache',
            'supported_formats': ['oai_dc', 'mets'],
            'cache_types': ['record', 'page'],
            'graph_integration': True,
            'supported_verbs': ['GetRecord', 'ListRecords', 'ListIdentifiers']
        })

        return base_stats
