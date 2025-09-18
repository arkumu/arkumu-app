"""
Schema Map Cache Service

Creates and caches a comprehensive map of all classes and their properties
for fast catalog explorer navigation.
"""

import logging
from typing import Dict, List, Optional, Any
from django.core.cache import cache
from django.db.models import Q, Count, Prefetch
from django.utils import timezone
from arkumu.metadata.models import Resource, Triple, ResourceType
from .base_cache_service import BaseCacheService

logger = logging.getLogger(__name__)


class SchemaMapCacheService(BaseCacheService):
    """
    Cache service for schema maps - comprehensive class/property relationships.

    Builds a complete map of:
    - All classes with entity counts
    - All properties for each class with usage statistics
    - Sample values for each property

    This enables instant navigation without repeated database queries.
    """

    def __init__(self):
        super().__init__('schema_map')
        self.rdf_type_uri = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'

    def get_class_properties(self, class_uri: str, organization_code: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """Public helper to get properties for a class with optional org filter."""
        return self._get_properties_for_class(class_uri, organization_code)

    def get_class_properties_with_orgs(self, class_uri: str) -> Dict[str, Dict[str, Any]]:
        """Public helper returning property stats broken down by organization."""
        return self._get_properties_for_class_with_orgs(class_uri)

    def get_complete_schema_map(
        self,
        organization_code: Optional[str] = None,
        include_properties: bool = True,
    ) -> Dict[str, Any]:
        """
        Get complete schema map for catalog explorer.

        Returns:
            {
                'organizations': {org_code: {name, count}},
                'classes': {class_uri: {name, count, properties: {...}, organizations: [...]}},
                'meta': {total_classes, total_properties, cache_time}
            }
        """
        cache_key = 'complete_schema_map:global'
        cached = cache.get(cache_key)

        if cached:
            logger.info(f"Schema map cache HIT: {cache_key} - {len(cached.get('classes', {}))} classes")
            # Filter by organization if specified
            if organization_code:
                return self._filter_schema_map_by_organization(cached, organization_code)
            return cached

        logger.info("Building complete schema map with all organizations")

        # Build comprehensive map with ALL data
        classes_data = self._get_classes_with_properties_and_orgs_map()

        if include_properties:
            for class_uri, class_info in classes_data.items():
                if not class_info.get('properties'):
                    class_info['properties'] = self._get_properties_for_class(class_uri)
        schema_map = {
            'organizations': self._get_organizations_map(classes_data),
            'classes': classes_data,
            'meta': {
                'cache_time': timezone.now().isoformat(),
                'organization_filter': None
            }
        }

        # Add summary statistics
        schema_map['meta']['total_classes'] = len(schema_map['classes'])
        schema_map['meta']['total_properties'] = sum(
            len(class_info.get('properties', {}))
            for class_info in schema_map['classes'].values()
        )

        # Cache for 10 minutes - this is expensive to build
        cache.set(cache_key, schema_map, 600)
        logger.info(f"Cached schema map: {schema_map['meta']['total_classes']} classes, "
                   f"{schema_map['meta']['total_properties']} properties")

        # Filter by organization if specified
        if organization_code:
            return self._filter_schema_map_by_organization(schema_map, organization_code)

        return schema_map

    def _get_organizations_map(self, classes_data: Dict[str, Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
        """Get map of organizations that have classes with canonical URIs.

        If classes_data is provided, derive organizations from that data (fast).
        Otherwise, fall back to database query (slow).
        """
        if classes_data:
            # Fast path: derive organizations from already-loaded classes data
            org_stats = {}

            for class_info in classes_data.values():
                for org_code, org_data in class_info.get('organizations', {}).items():
                    if org_code not in org_stats:
                        org_stats[org_code] = {
                            'entity_count': 0,
                            'name': org_code  # Will be updated with real name below
                        }
                    org_stats[org_code]['entity_count'] += org_data['entity_count']

            # Get organization names in one query
            if org_stats:
                from arkumu.users.models import Organization
                org_names = Organization.objects.filter(
                    code__in=org_stats.keys()
                ).values_list('code', 'name')

                name_map = dict(org_names)
                for org_code in org_stats:
                    org_stats[org_code]['name'] = name_map.get(org_code, org_code)

            return {
                org_code: {
                    'name': data['name'],
                    'resource_count': data['entity_count'],
                    'domain': ''
                }
                for org_code, data in org_stats.items()
            }
        else:
            # Fallback: direct database query (slower)
            from arkumu.users.models import Organization

            orgs_with_classes = Triple.objects.filter(
                predicate__uri=self.rdf_type_uri,
                subject__resource_type=ResourceType.ENTITY,
                object__canonical_uri__isnull=False,
                subject__organization__isnull=False
            ).values('subject__organization__code', 'subject__organization__name').annotate(
                entity_count=Count('subject__uri', distinct=True)
            ).filter(entity_count__gt=0)

            return {
                org_data['subject__organization__code']: {
                    'name': org_data['subject__organization__name'],
                    'resource_count': org_data['entity_count'],
                    'domain': ''
                }
                for org_data in orgs_with_classes
            }

    def _filter_schema_map_by_organization(self, schema_map: Dict[str, Any], organization_code: str) -> Dict[str, Any]:
        """Filter the global schema map by organization."""
        filtered_classes = {}

        for class_uri, class_info in schema_map['classes'].items():
            # Check if this class has data for the specified organization
            if organization_code in class_info.get('organizations', {}):
                org_data = class_info['organizations'][organization_code]

                # Create filtered class info with organization-specific counts
                filtered_class = {
                    'name': class_info['name'],
                    'uri': class_uri,
                    'entity_count': org_data['entity_count'],
                    'description': f"{org_data['entity_count']} entities",
                    'properties': {}
                }

                # Filter properties for this organization
                for prop_uri, prop_info in class_info.get('properties', {}).items():
                    if organization_code in prop_info.get('organizations', {}):
                        org_prop_data = prop_info['organizations'][organization_code]
                        filtered_class['properties'][prop_uri] = {
                            'name': prop_info['name'],
                            'uri': prop_uri,
                            'usage_count': org_prop_data['usage_count'],
                            'unique_values': org_prop_data['unique_values'],
                            'sample_literals': org_prop_data.get('sample_literals', []),
                            'description': f"Used {org_prop_data['usage_count']} times, {org_prop_data['unique_values']} unique values"
                        }

                # Include all classes that have entities for this organization
                filtered_classes[class_uri] = filtered_class

        return {
            'organizations': schema_map['organizations'],
            'classes': filtered_classes,
            'meta': {
                **schema_map['meta'],
                'organization_filter': organization_code,
                'total_classes': len(filtered_classes),
                'total_properties': sum(len(c.get('properties', {})) for c in filtered_classes.values())
            }
        }

    def _get_classes_with_properties_and_orgs_map(self) -> Dict[str, Dict[str, Any]]:
        """Get complete map of classes with their properties and organization data."""

        # Step 1: Get all classes with basic info
        classes = Resource.objects.filter(
            resource_type=ResourceType.CLASS,
            canonical_uri__isnull=False
        ).filter(
            object_triples__predicate__uri=self.rdf_type_uri,
            object_triples__subject__resource_type=ResourceType.ENTITY
        ).distinct()

        # Convert to dict for fast access
        classes_dict = {cls.canonical_uri: cls for cls in classes}

        # Step 2: Get ALL entity counts per class per organization in ONE bulk query
        class_org_counts = Triple.objects.filter(
            predicate__uri=self.rdf_type_uri,
            object__canonical_uri__in=classes_dict.keys(),
            subject__resource_type=ResourceType.ENTITY,
            subject__organization__isnull=False
        ).values(
            'object__canonical_uri',
            'subject__organization__code'
        ).annotate(
            entity_count=Count('subject__uri', distinct=True)
        ).filter(entity_count__gt=0)

        # Step 3: Group entity counts by class and organization
        from collections import defaultdict
        class_counts = defaultdict(lambda: defaultdict(int))
        for item in class_org_counts:
            class_uri = item['object__canonical_uri']
            org_code = item['subject__organization__code']
            class_counts[class_uri][org_code] = item['entity_count']

        # Step 4: Build classes map without properties first (for speed)
        classes_map = {}
        for class_uri, cls in classes_dict.items():
            if class_uri in class_counts:  # Only include classes with entities
                total_entities = sum(class_counts[class_uri].values())

                class_data = {
                    'name': cls.name or class_uri.split('/')[-1],
                    'uri': class_uri,
                    'entity_count': total_entities,
                    'description': f"{total_entities} entities",
                    'properties': {},  # Empty for now - properties loaded on demand
                    'organizations': {
                        org_code: {'entity_count': count}
                        for org_code, count in class_counts[class_uri].items()
                    }
                }

                classes_map[class_uri] = class_data

        return classes_map

    def _get_properties_for_class_with_orgs(self, class_uri: str) -> Dict[str, Dict[str, Any]]:
        """Get all properties used by entities of a specific class with organization breakdown."""
        # Find entities of this class across all organizations
        entity_uris_query = Triple.objects.filter(
            predicate__uri=self.rdf_type_uri,
            object__canonical_uri=class_uri,
            subject__resource_type=ResourceType.ENTITY
        ).values_list('subject__uri', flat=True).distinct()

        entity_uris = list(entity_uris_query)
        if not entity_uris:
            return {}

        # Get property usage statistics across all entities of this class
        property_stats = Triple.objects.filter(
            subject__uri__in=entity_uris,
            predicate__resource_type=ResourceType.PROPERTY,
            predicate__canonical_uri__isnull=False
        ).exclude(
            predicate__uri=self.rdf_type_uri
        ).values(
            'predicate__canonical_uri',
            'predicate__name',
            'subject__organization__code'
        ).annotate(
            usage_count=Count('id'),
            unique_values=Count('object', distinct=True)
        ).order_by('predicate__canonical_uri', 'subject__organization__code')

        properties_map = {}

        # Group by property URI
        from itertools import groupby
        for prop_uri, prop_group in groupby(property_stats, key=lambda x: x['predicate__canonical_uri']):
            prop_group_list = list(prop_group)

            # Get property name from first entry
            prop_name = prop_group_list[0]['predicate__name'] or prop_uri.split('/')[-1]

            property_data = {
                'name': prop_name,
                'uri': prop_uri,
                'usage_count': 0,
                'unique_values': 0,
                'sample_literals': [],
                'description': '',
                'organizations': {}
            }

            total_usage = 0
            total_unique = 0

            for entry in prop_group_list:
                org_code = entry['subject__organization__code']
                if org_code:  # Skip if organization is None
                    property_data['organizations'][org_code] = {
                        'usage_count': entry['usage_count'],
                        'unique_values': entry['unique_values']
                    }
                    total_usage += entry['usage_count']
                    total_unique += entry['unique_values']

            if total_usage > 0:  # Only include properties that are actually used
                property_data['usage_count'] = total_usage
                property_data['unique_values'] = total_unique
                property_data['description'] = f"Used {total_usage} times, {total_unique} unique values"

                # Get sample literals (global, not per org for now)
                property_data['sample_literals'] = self._get_sample_literals(entity_uris, prop_uri, limit=5)

                properties_map[prop_uri] = property_data

        return properties_map

    def _get_classes_with_properties_map(self, organization_code: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """Get complete map of classes with their properties and statistics."""

        # Base filter for entities that have types
        entity_filter = Q(
            object_triples__predicate__uri=self.rdf_type_uri,
            object_triples__subject__resource_type=ResourceType.ENTITY,
            object_triples__object__canonical_uri__isnull=False
        )

        # Add organization filter if specified
        if organization_code:
            entity_filter &= Q(object_triples__subject__organization__code=organization_code)

        # Get all classes with entity counts
        classes = Resource.objects.filter(
            resource_type=ResourceType.CLASS,
            canonical_uri__isnull=False
        ).annotate(
            entity_count=Count(
                'object_triples__subject',
                filter=entity_filter,
                distinct=True
            )
        ).filter(entity_count__gt=0).order_by('-entity_count')

        classes_map = {}

        for cls in classes:
            class_uri = cls.canonical_uri

            # Get properties for this class
            properties_map = self._get_properties_for_class(class_uri, organization_code)

            classes_map[class_uri] = {
                'name': cls.name or class_uri.split('/')[-1],
                'uri': class_uri,
                'entity_count': cls.entity_count,
                'description': f"{cls.entity_count} entities",
                'properties': properties_map
            }

        return classes_map

    def _get_properties_for_class(self, class_uri: str, organization_code: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """Get all properties used by entities of a specific class."""

        # Find entities of this class
        entity_type_filter = Q(
            predicate__uri=self.rdf_type_uri,
            object__canonical_uri=class_uri,
            subject__resource_type=ResourceType.ENTITY
        )

        if organization_code:
            entity_type_filter &= Q(subject__organization__code=organization_code)

        # Get entity URIs of this class
        entity_uris = Triple.objects.filter(entity_type_filter).values_list(
            'subject__uri', flat=True
        ).distinct()

        if not entity_uris:
            return {}

        # Get all properties used by these entities with usage counts
        property_stats = Triple.objects.filter(
            subject__uri__in=entity_uris,
            predicate__resource_type=ResourceType.PROPERTY,
            predicate__canonical_uri__isnull=False
        ).exclude(
            predicate__uri=self.rdf_type_uri  # Exclude type declarations
        ).values(
            'predicate__canonical_uri',
            'predicate__name'
        ).annotate(
            usage_count=Count('id'),
            sample_values=Count('object', distinct=True)
        ).order_by('-usage_count')[:50]  # Limit to top 50 properties

        properties_map = {}

        for prop in property_stats:
            prop_uri = prop['predicate__canonical_uri']

            # Get sample literal values for this property
            sample_literals = self._get_sample_literals(entity_uris, prop_uri, limit=5)

            properties_map[prop_uri] = {
                'name': prop['predicate__name'] or prop_uri.split('/')[-1],
                'uri': prop_uri,
                'usage_count': prop['usage_count'],
                'unique_values': prop['sample_values'],
                'sample_literals': sample_literals,
                'description': f"Used {prop['usage_count']} times, {prop['sample_values']} unique values"
            }

        return properties_map

    def _get_sample_literals(self, entity_uris: List[str], property_uri: str, limit: int = 5) -> List[str]:
        """Get sample literal values for a property."""

        literals = Triple.objects.filter(
            subject__uri__in=entity_uris,
            predicate__canonical_uri=property_uri,
            object__resource_type=ResourceType.LITERAL
        ).values_list(
            'object__name', flat=True
        ).distinct()[:limit]

        return [lit for lit in literals if lit and len(lit.strip()) > 0]

    def invalidate_schema_cache(self, organization_code: Optional[str] = None):
        """Invalidate schema cache when data changes."""
        # Only need to clear the global cache since we're not caching per organization anymore
        cache.delete('complete_schema_map:global')
        logger.info("Invalidated global schema cache")

    def warm_cache(self, organization_codes: Optional[List[str]] = None):
        """Pre-warm the schema cache for better performance."""
        # Just warm the global cache
        self.get_complete_schema_map(include_properties=True)
        logger.info("Schema cache warmed successfully")
