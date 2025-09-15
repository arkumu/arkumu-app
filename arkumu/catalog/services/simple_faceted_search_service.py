"""
Simple Faceted Search Service without harmonization dependencies.

This service provides faceted search functionality using the basic Resource/Triple model
without requiring harmonization rules or complex cross-archive logic.
"""

from typing import Dict, List, Optional, Any
import logging
from django.db.models import QuerySet, Q, Count
from django.contrib.auth import get_user_model
from arkumu.metadata.models import Resource, Triple
from arkumu.metadata.models.resource import ResourceType, PublicAccessLevel

User = get_user_model()


class SimpleFacetedSearchService:
    """Simple faceted search service without harmonization dependencies."""

    # Common RDF predicates
    RDF_TYPE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'

    def __init__(self, user: User):
        self.user = user
        self.logger = logging.getLogger(__name__)

    def _get_accessible_resources(self) -> QuerySet:
        """Get resources accessible to the current user."""
        if not self.user.is_authenticated:
            # Anonymous users can only access public resources
            return Resource.objects.filter(
                public_access_level=PublicAccessLevel.PUBLIC,
                is_public_approved=True
            )
        elif hasattr(self.user, 'role') and self.user.role == 'system_admin':
            # System admins can access all resources
            return Resource.objects.all()
        else:
            # Authenticated users can access public + their org's resources
            user_org = getattr(self.user, 'organization', None)
            if user_org:
                return Resource.objects.filter(
                    Q(public_access_level=PublicAccessLevel.PUBLIC, is_public_approved=True) |
                    Q(organization=user_org)
                )
            else:
                # User without organization - only public resources
                return Resource.objects.filter(
                    public_access_level=PublicAccessLevel.PUBLIC,
                    is_public_approved=True
                )

    def search_with_facets(self,
                          query: str = '',
                          resource_type: str = '',
                          facet_filters: Optional[Dict[str, List[str]]] = None,
                          selected_properties: Optional[List[str]] = None,
                          limit: int = 100) -> Dict[str, Any]:
        """
        Optimized faceted search using select_related and prefetch_related.
        """
        if facet_filters is None:
            facet_filters = {}

        # Build filters incrementally without loading all resources
        from django.db.models import Prefetch

        # Start with accessible resources - don't materialize yet
        base_qs = self._get_accessible_resources()

        # If filtering by type, do it at the database level
        final_resource_ids = None
        if resource_type:
            # Single query with select_related for efficient joins
            type_triples = (
                Triple.objects
                .select_related('subject', 'object', 'predicate')
                .filter(
                    predicate__uri=self.RDF_TYPE,
                    subject__in=base_qs
                )
                .filter(
                    Q(object__uri=resource_type) | Q(object__canonical_uri=resource_type)
                )
                .values_list('subject_id', flat=True)[:10000]  # Limit for performance
            )
            final_resource_ids = list(type_triples)
            self.logger.debug(f"TypeFilter: {resource_type} found={len(final_resource_ids)}")

            if not final_resource_ids:
                self.logger.warning(f"TypeFilter: {resource_type} found 0")
                return {'resources': [], 'facets': {}, 'total_count': 0}
        else:
            # Just take first 10000 accessible resources
            final_resource_ids = list(base_qs.values_list('id', flat=True)[:10000])

        # Apply property filters efficiently
        if selected_properties:
            for prop_uri in selected_properties:
                before = len(final_resource_ids)
                # Handle both canonical and full property URIs
                prop_subjects = (
                    Triple.objects
                    .filter(
                        subject_id__in=final_resource_ids
                    )
                    .filter(
                        Q(predicate__uri=prop_uri) | Q(predicate__canonical_uri=prop_uri)
                    )
                    .values_list('subject_id', flat=True)
                    .distinct()
                )
                prop_count = prop_subjects.count()
                final_resource_ids = list(set(final_resource_ids).intersection(set(prop_subjects)))
                after = len(final_resource_ids)

                self.logger.debug(f"PropFilter: {prop_uri} before={before} found={prop_count} after={after}")

                if not final_resource_ids:
                    self.logger.warning(f"PropFilter: {prop_uri} filtered to 0")
                    return {'resources': [], 'facets': {}, 'total_count': 0}

        # Apply text search if provided
        if query.strip():
            query_subjects = (
                Triple.objects
                .select_related('object')
                .filter(
                    subject_id__in=final_resource_ids,
                    object__resource_type=ResourceType.LITERAL,
                    object__value__icontains=query
                )
                .values_list('subject_id', flat=True)
                .distinct()
            )
            final_resource_ids = list(set(final_resource_ids).intersection(set(query_subjects)))

        # Apply facet filters
        for property_name, values in facet_filters.items():
            if values and not property_name.startswith('has_'):
                # Handle both canonical and full property URIs in facet filters
                facet_subjects = (
                    Triple.objects
                    .select_related('predicate', 'object')
                    .filter(
                        subject_id__in=final_resource_ids,
                        object__value__in=values
                    )
                    .filter(
                        Q(predicate__uri=property_name) | Q(predicate__canonical_uri=property_name)
                    )
                    .values_list('subject_id', flat=True)
                    .distinct()
                )
                final_resource_ids = list(set(final_resource_ids).intersection(set(facet_subjects)))

        # Get final resources with efficient prefetching
        final_resources = (
            Resource.objects
            .filter(id__in=final_resource_ids[:limit])
            .select_related('organization')
            .prefetch_related(
                Prefetch(
                    'subject_triples',
                    queryset=Triple.objects.select_related('predicate', 'object')[:20],
                    to_attr='cached_triples'
                )
            )
        )

        # Generate facets efficiently - only for first 200 results
        facets = {}
        if len(final_resource_ids) > 0:
            facet_sample = final_resource_ids[:200]

            # Get facets with single query, filtering out poor quality properties
            facet_data = (
                Triple.objects
                .filter(subject_id__in=facet_sample)
                .select_related('predicate', 'object')
                .exclude(predicate__uri=self.RDF_TYPE)  # Already filtered by type
                .exclude(predicate__uri__contains='isPartOf')  # Skip structural properties
                .exclude(object__value__isnull=True, object__uri__isnull=True)  # Skip empty values
                .values('predicate__uri', 'predicate__name', 'object__value', 'object__uri')
                .annotate(count=Count('subject_id'))
                .order_by('predicate__uri', '-count')
            )

            for item in facet_data:
                prop_uri = item['predicate__uri']
                value = item['object__value'] or item['object__uri']

                # Skip poor quality facet values
                if not value or len(str(value).strip()) < 2:
                    continue

                # Skip very long values that are likely not useful facets
                if len(str(value)) > 200:
                    continue

                # Skip values that look like UUIDs or technical identifiers (but allow -id properties with meaningful values)
                if self._is_technical_identifier(str(value)) and prop_uri.endswith('-id'):
                    continue

                if prop_uri not in facets:
                    facets[prop_uri] = []

                # Only keep top 10 values per property
                if len(facets[prop_uri]) < 10:
                    facets[prop_uri].append({
                        'value': value,
                        'label': value[:50] if len(value) > 50 else value,
                        'count': item['count']
                    })

        return {
            'resources': list(final_resources),
            'facets': facets,
            'total_count': len(final_resource_ids),
        }

    def _is_technical_identifier(self, value: str) -> bool:
        """Check if a value looks like a technical identifier that shouldn't be a facet."""
        import re

        # Check for UUID patterns
        if re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', value, re.I):
            return True

        # Check for long numeric IDs
        if re.match(r'^\d{8,}$', value):
            return True

        # Check for URIs that look like technical identifiers
        if value.startswith('http') and any(pattern in value for pattern in ['uuid', 'guid', '/id/', '_id']):
            return True

        return False

        """
        Perform faceted search.

        Args:
            query: Search term to match in literal values
            resource_type: URI of resource type to filter by
            facet_filters: Dict of property->values to filter by
            limit: Maximum number of results to return

        Returns:
            Dict containing resources, facets, and metadata
        """
        if facet_filters is None:
            facet_filters = {}

        # Start with accessible resources - optimize query
        accessible_resources = self._get_accessible_resources().only('id')
        # Use iterator for better memory efficiency with large datasets
        resource_ids = set(accessible_resources.values_list('id', flat=True).iterator(chunk_size=5000))

        accessible_count = len(resource_ids)
        try:
            self.logger.info(
                "explorer.facets.accessible count_accessible=%d user_id=%s org=%s",
                accessible_count,
                getattr(self.user, 'id', None),
                getattr(getattr(self.user, 'organization', None), 'code', None),
            )
        except Exception:
            pass

        if not resource_ids:
            return {'resources': [], 'facets': {}, 'total_count': 0}

        # Filter by resource type (enhanced for Classes, Properties, and Entities)
        after_type = None
        if resource_type:
            original_count = len(resource_ids)

            # Determine what type of resource we're filtering by
            selected_resource = Resource.objects.filter(
                Q(uri=resource_type) | Q(canonical_uri=resource_type)
            ).first()

            if selected_resource:
                resource_type_enum = selected_resource.resource_type

                if resource_type_enum == ResourceType.CLASS:
                    # Filtering by Class: Show all entities of this type
                    type_filter = Q(object__canonical_uri=resource_type) | Q(object__uri=resource_type)

                    # Also match by tail for non-canonical types
                    if '/types/' in resource_type:
                        type_tail = resource_type.split('/')[-1]
                        type_filter |= Q(
                            object__canonical_uri__isnull=True,
                            object__uri__endswith=f'/{type_tail}'
                        )

                    type_subject_ids = (
                        Triple.objects.filter(
                            predicate__uri=self.RDF_TYPE,
                            subject_id__in=resource_ids
                        )
                        .filter(type_filter)
                        .values_list('subject_id', flat=True)
                    )
                    resource_ids = set(type_subject_ids)

                elif resource_type_enum == ResourceType.PROPERTY:
                    # Filtering by Property: Show all entities that have this property
                    prop_filter = Q(predicate__canonical_uri=resource_type) | Q(predicate__uri=resource_type)

                    prop_subject_ids = (
                        Triple.objects.filter(subject_id__in=resource_ids)
                        .filter(prop_filter)
                        .values_list('subject_id', flat=True)
                        .distinct()
                    )
                    resource_ids = set(prop_subject_ids)

                elif resource_type_enum == ResourceType.IRI:
                    # Filtering by Entity: Show this specific entity
                    entity_id = selected_resource.id
                    if entity_id in resource_ids:
                        resource_ids = {entity_id}
                    else:
                        resource_ids = set()

                else:
                    # Unknown resource type, keep original logic
                    resource_ids = set()

            else:
                # Fallback: try original class-based logic
                canon = resource_type
                if '/data/' in resource_type:
                    tail = resource_type.rstrip('/').split('/')[-1]
                    canon = f"http://arkumu.org/types/{tail}"

                type_filter = Q(object__canonical_uri=canon) | Q(object__uri=canon)
                type_subject_ids = (
                    Triple.objects.filter(
                        predicate__uri=self.RDF_TYPE,
                        subject_id__in=resource_ids
                    )
                    .filter(type_filter)
                    .values_list('subject_id', flat=True)
                )
                resource_ids = set(type_subject_ids)

            after_type = len(resource_ids)
            try:
                self.logger.info(
                    "explorer.facets.resource_filter type=%s original_count=%d after_filter=%d selected_type=%s",
                    resource_type,
                    original_count,
                    after_type,
                    selected_resource.resource_type if selected_resource else 'unknown'
                )
            except Exception:
                pass

        # Filter by selected properties (must have these properties)
        if selected_properties:
            original_count = len(resource_ids)
            for prop_uri in selected_properties:
                # Find entities that have this property (any value)
                # resource_ids contains Resource IDs, we need to filter on those
                entities_with_prop = set(Triple.objects.filter(
                    subject_id__in=resource_ids,
                    predicate__uri=prop_uri
                ).values_list('subject_id', flat=True))

                resource_ids = resource_ids.intersection(entities_with_prop)

            try:
                self.logger.info(
                    "explorer.facets.property_filter properties=%d original_count=%d after_filter=%d",
                    len(selected_properties),
                    original_count,
                    len(resource_ids),
                )
            except Exception:
                pass

        # Filter by search query if provided
        after_query = None
        if query.strip():
            matching_triples = Triple.objects.filter(
                subject_id__in=resource_ids,
                object__resource_type=ResourceType.LITERAL,
                object__value__icontains=query
            ).values_list('subject_id', flat=True)
            resource_ids = set(matching_triples)
            after_query = len(resource_ids)
            try:
                self.logger.info(
                    "explorer.facets.query_filter query_len=%d count_after_query=%d",
                    len(query.strip()),
                    after_query,
                )
            except Exception:
                pass

        # Apply facet filters
        after_facets = None
        for property_name, values in facet_filters.items():
            if values:
                before = len(resource_ids)
                # Treat property_name as canonical property URI if it looks like a URI
                if isinstance(property_name, str) and property_name.startswith('http'):
                    prop_filter = Q(predicate__canonical_uri=property_name) | Q(predicate__uri=property_name)
                else:
                    prop_filter = Q(predicate__name=property_name) | Q(predicate__uri__icontains=property_name)

                matching_subjects = (
                    Triple.objects.filter(subject_id__in=resource_ids)
                    .filter(prop_filter)
                    .filter(Q(object__value__in=values) | Q(object__uri__in=values))
                    .values_list('subject_id', flat=True)
                )
                resource_ids = set(matching_subjects)
                after_facets = len(resource_ids)
                try:
                    self.logger.info(
                        "explorer.facets.apply_facet facet=%s values=%s before=%d after=%d",
                        property_name,
                        list(values)[:10],
                        before,
                        after_facets,
                    )
                except Exception:
                    pass

        # Get final resource objects with additional context
        final_resources = Resource.objects.filter(
            id__in=resource_ids
        ).select_related('organization')[:limit]

        # Return resources as-is (enhancement removed)
        enhanced_resources = list(final_resources)

        # Generate property stats and facets for the filtered results
        limited_ids = list(resource_ids)[:200]  # Limit for performance on stats/facets
        property_stats = self._generate_property_stats(limited_ids)
        facets = self._generate_facets(limited_ids)

        try:
            self.logger.info(
                "explorer.facets.result result_count=%d facet_properties=%d",
                final_resources.count(),
                len(facets.keys()),
            )
        except Exception:
            pass

        debug_meta = {
            'accessible_count': accessible_count,
            'after_type': after_type,
            'after_query': after_query,
            'after_facets': after_facets,
            'facet_properties': len(facets.keys()),
        }
        return {
            'resources': list(final_resources),
            'facets': facets,
            'property_stats': property_stats,
            'total_count': len(resource_ids),
            'debug': debug_meta,
        }

    def _generate_property_stats(self, resource_ids: List[str]) -> List[Dict[str, Any]]:
        """Summarize columns (properties) as seen on the selected rows (subjects).

        Returns list of dicts: { key, label, row_count, value_count }
        - row_count: distinct subjects that have at least one value for this property
        - value_count: distinct objects (values or linked resources)
        """
        if not resource_ids:
            return []

        stats_qs = (
            Triple.objects.filter(subject_id__in=resource_ids)
            .values('predicate__uri', 'predicate__name', 'predicate__canonical_uri')
            .annotate(
                row_count=Count('subject_id', distinct=True),
                value_count=Count('object_id', distinct=True)
            )
            .order_by('-row_count')[:50]
        )

        stats: List[Dict[str, Any]] = []
        for s in stats_qs:
            canon = s['predicate__canonical_uri']
            uri = canon or s['predicate__uri']
            name = (canon or uri or 'property').rstrip('/').split('/')[-1]
            stats.append({
                'key': uri,  # canonical key (template uses with facets)
                'uri': uri,
                'label': name,
                'row_count': s['row_count'],
                'value_count': s['value_count'],
            })

        try:
            self.logger.info(
                "explorer.facets.property_stats top=%d first=%s",
                len(stats),
                stats[0] if stats else None,
            )
        except Exception:
            pass

        return stats

    def _generate_facets(self, resource_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """Generate facet options for the given resources."""
        if not resource_ids:
            return {}

        # Get property-value combinations for faceting (canonical properties only; include literals and linked resources)
        facet_triples = (
            Triple.objects.filter(
                subject_id__in=resource_ids,
            )
            .select_related('predicate', 'object')
            .values(
                'predicate__uri',
                'predicate__name',
                'predicate__canonical_uri',
                'object__resource_type',
                'object__value',
                'object__uri',
                'object__name',
            )
            .annotate(count=Count('subject_id', distinct=True))
            .order_by('predicate__uri', '-count')
        )

        # Group by predicate (property)
        facets: Dict[str, List[Dict[str, Any]]] = {}
        for triple in facet_triples:
            prop_uri = triple['predicate__uri']
            prop_canon = triple.get('predicate__canonical_uri')
            # Only include canonical properties
            prop_key = prop_canon or prop_uri
            if not prop_canon and not (prop_key or '').startswith('http://arkumu.org/properties/'):
                continue
            # Label from canonical tail when possible
            prop_name = (prop_canon or prop_uri or '').rstrip('/').split('/')[-1]
            obj_type = triple['object__resource_type']
            count = triple['count']
            # Determine facet value and label
            if obj_type == ResourceType.LITERAL:
                value = triple['object__value']
                label = str(value) if value is not None else None
            else:
                value = triple['object__uri']
                label = triple['object__name'] or (value.split('/')[-1] if value else None)

            # Skip very long values or system properties
            if not value or (isinstance(value, str) and len(value) > 200) or 'system' in prop_uri.lower():
                continue

            if prop_key not in facets:
                facets[prop_key] = []

            # Include values even if they occur once (dev explorer convenience)
            if count >= 1:
                facets[prop_key].append({
                    'value': value,
                    'label': label or str(value),
                    'count': count
                })

        # Limit facet values to top 10 per property
        for prop_key in list(facets.keys()):
            facets[prop_key] = sorted(
                facets[prop_key],
                key=lambda x: x['count'],
                reverse=True
            )[:10]

        # Only return properties that have values
        filtered = {k: v for k, v in facets.items() if v}
        # Light debug summary: top properties and value counts
        try:
            summary = {k: len(v) for k, v in list(filtered.items())[:5]}
            self.logger.info(
                "explorer.facets.generated properties=%d sample=%s",
                len(filtered),
                summary,
            )
        except Exception:
            pass
        return filtered

    def get_available_types(self) -> Dict[str, Dict[str, Any]]:
        """Get available resource types with counts."""
        accessible_resources = self._get_accessible_resources()

        type_counts = Triple.objects.filter(
            predicate__uri=self.RDF_TYPE,
            subject__in=accessible_resources,
            object__resource_type=ResourceType.CLASS
        ).values(
            'object__uri',
            'object__name'
        ).annotate(
            count=Count('subject', distinct=True)
        ).order_by('-count')[:20]

        types = {}
        for type_info in type_counts:
            uri = type_info['object__uri']
            name = type_info['object__name'] or uri.split('/')[-1]

            types[uri] = {
                'name': name,
                'count': type_info['count']
            }

        return types

    def get_available_canonical_types(self) -> Dict[str, Dict[str, Any]]:
        """Get available canonical class types with aggregated counts across org-specific types."""
        accessible_resources = self._get_accessible_resources()

        # Pull triples and group in Python by canonical uri
        qs = (
            Triple.objects.filter(
                predicate__uri=self.RDF_TYPE,
                subject__in=accessible_resources,
                object__resource_type=ResourceType.CLASS,
            )
            .values('object__canonical_uri', 'object__uri', 'object__name', 'subject_id')
        )

        agg: Dict[str, Dict[str, Any]] = {}
        for row in qs:
            canon = row['object__canonical_uri']
            obj_uri = row['object__uri']
            obj_name = row['object__name']

            # Only expose canonical classes
            key = None
            if canon:
                key = canon
                label = obj_name or canon.split('/')[-1]
            elif obj_uri and obj_uri.startswith('http://arkumu.org/'):
                key = obj_uri
                label = obj_name or obj_uri.split('/')[-1]

            if not key:
                continue

            entry = agg.setdefault(key, {'name': label, 'subjects': set()})
            entry['subjects'].add(row['subject_id'])

        # Convert sets to counts, order by count desc, and take top 20
        items = [
            (k, {'name': v['name'], 'count': len(v['subjects'])})
            for k, v in agg.items()
        ]
        items.sort(key=lambda kv: kv[1]['count'], reverse=True)
        items = items[:20]
        result = {k: v for k, v in items}

        # Fallback: if no canonical classes with counts found, list known canonical class resources (count=0)
        if not result:
            try:
                canon_qs = Resource.objects.filter(resource_type=ResourceType.CLASS).values('canonical_uri', 'uri', 'name')[:200]
                for row in canon_qs:
                    canon = row['canonical_uri']
                    uri = row['uri']
                    key = canon or (uri if uri and uri.startswith('http://arkumu.org/types/') else None)
                    if not key:
                        continue
                    if key not in result:
                        result[key] = {'name': row['name'] or key.split('/')[-1], 'count': 0}
                self.logger.info("explorer.types.canonical_fallback count=%d", len(result))
            except Exception:
                pass

        try:
            self.logger.info("explorer.types.canonical count=%d", len(result))
        except Exception:
            pass
        return result

    def get_available_resource_types(self) -> Dict[str, Dict[str, Any]]:
        """Get all available resource types: Classes, Properties, and Entities with counts."""
        accessible_resources = self._get_accessible_resources()
        all_resources = {}

        # 1. Get Classes (entity types) via rdf:type triples
        try:
            class_qs = (
                Triple.objects.filter(
                    predicate__uri=self.RDF_TYPE,
                    subject__in=accessible_resources,
                    object__resource_type=ResourceType.CLASS,
                )
                .values('object__canonical_uri', 'object__uri', 'object__name', 'subject_id')
            )

            class_subjects = {}
            for row in class_qs:
                canon = row['object__canonical_uri']
                obj_uri = row['object__uri']
                obj_name = row['object__name']
                key = canon or obj_uri
                if key:
                    label = f"🏷️ {obj_name or key.split('/')[-1]} (Class)"
                    entry = class_subjects.setdefault(key, {'name': label, 'type': 'CLASS', 'subjects': set()})
                    entry['subjects'].add(row['subject_id'])

            # Add classes to results
            for key, data in class_subjects.items():
                all_resources[key] = {'name': data['name'], 'type': data['type'], 'count': len(data['subjects'])}

            self.logger.info(f"explorer.resources.classes count={len(class_subjects)}")
        except Exception as e:
            self.logger.error(f"Error getting classes: {e}")

        # 2. Get Properties via predicate usage
        try:
            prop_qs = (
                Triple.objects.filter(subject__in=accessible_resources)
                .exclude(predicate__uri=self.RDF_TYPE)  # Exclude rdf:type
                .values('predicate__canonical_uri', 'predicate__uri', 'predicate__name')
                .annotate(usage_count=Count('subject_id', distinct=True))
                .order_by('-usage_count')[:50]  # Limit to top 50 properties
            )

            for row in prop_qs:
                canon = row['predicate__canonical_uri']
                prop_uri = row['predicate__uri']
                prop_name = row['predicate__name']
                key = canon or prop_uri
                if key:
                    label = f"📄 {prop_name or key.split('/')[-1]} (Property)"
                    all_resources[key] = {
                        'name': label,
                        'type': 'PROPERTY',
                        'count': row['usage_count']
                    }

            self.logger.info(f"explorer.resources.properties count={len([r for r in all_resources.values() if r['type'] == 'PROPERTY'])}")
        except Exception as e:
            self.logger.error(f"Error getting properties: {e}")

        # 3. Get top Entity instances (IRI resources)
        try:
            entity_qs = accessible_resources.filter(resource_type=ResourceType.IRI)[:30]  # Sample top entities

            for entity in entity_qs:
                key = entity.canonical_uri or entity.uri
                if key:
                    label = f"🔗 {entity.name or key.split('/')[-1]} (Entity)"
                    all_resources[key] = {
                        'name': label,
                        'type': 'IRI',
                        'count': 1
                    }

            self.logger.info(f"explorer.resources.entities count={len([r for r in all_resources.values() if r['type'] == 'IRI'])}")
        except Exception as e:
            self.logger.error(f"Error getting entities: {e}")

        # Sort by count descending and return top 100
        items = sorted(all_resources.items(), key=lambda x: x[1]['count'], reverse=True)[:100]
        result = {k: v for k, v in items}

        self.logger.info(f"explorer.resources.total count={len(result)}")
        return result

    def get_available_classes(self) -> Dict[str, Dict[str, Any]]:
        """Get available classes (datasets/tables) that contain data."""
        accessible_resources = self._get_accessible_resources()
        classes = {}

        try:
            class_qs = (
                Triple.objects.filter(
                    predicate__uri=self.RDF_TYPE,
                    subject__in=accessible_resources,
                    object__resource_type=ResourceType.CLASS,
                )
                .values('object__canonical_uri', 'object__uri', 'object__name')
                .annotate(entity_count=Count('subject_id', distinct=True))
                .filter(entity_count__gt=0)
                .order_by('-entity_count')
            )

            for row in class_qs:
                canon = row['object__canonical_uri']
                uri = row['object__uri']
                name = row['object__name']
                key = canon or uri

                if key:
                    display_name = name or key.split('/')[-1]
                    classes[key] = {
                        'uri': key,
                        'name': display_name,
                        'entity_count': row['entity_count']
                    }

            self.logger.info(f"explorer.classes count={len(classes)}")
        except Exception as e:
            self.logger.error(f"Error getting classes: {e}")

        return classes

    def get_properties_for_class(self, class_uri: str) -> Dict[str, Dict[str, Any]]:
        """Get properties (columns) available for a specific class."""
        if not class_uri:
            return {}

        accessible_resources = self._get_accessible_resources()

        # Find entities of this class - check both URI and canonical_uri
        entity_ids = list(
            Triple.objects.filter(
                predicate__uri=self.RDF_TYPE,
                subject__in=accessible_resources
            ).filter(
                Q(object__uri=class_uri) | Q(object__canonical_uri=class_uri)
            ).values_list('subject_id', flat=True)
        )

        if not entity_ids:
            return {}

        try:
            # Get properties used by entities of this class
            prop_qs = (
                Triple.objects.filter(subject_id__in=entity_ids)
                .values('predicate__uri', 'predicate__name', 'predicate__canonical_uri')
                .annotate(
                    usage_count=Count('subject_id', distinct=True),
                    value_count=Count('object_id', distinct=True)
                )
                .filter(usage_count__gt=0)
                .order_by('-usage_count')
            )

            properties = {}
            for row in prop_qs:
                canon = row['predicate__canonical_uri']
                uri = canon or row['predicate__uri']
                name = row['predicate__name']

                if not name:
                    name = (uri or 'property').rstrip('/').split('/')[-1]

                if uri:
                    properties[uri] = {
                        'uri': uri,
                        'name': name,
                        'usage_count': row['usage_count'],
                        'value_count': row['value_count']
                    }

            self.logger.info(f"explorer.properties class={class_uri} count={len(properties)}")
            return properties

        except Exception as e:
            self.logger.error(f"Error getting properties for class {class_uri}: {e}")
            return {}

    def get_values_for_property(self, class_uri: str, property_uri: str, limit: int = 20, min_count: int = 2) -> List[Dict[str, Any]]:
        """Get available values for a specific property within a class."""
        if not class_uri or not property_uri:
            return []

        accessible_resources = self._get_accessible_resources()

        # Find entities of this class
        entity_ids = list(
            Triple.objects.filter(
                predicate__uri=self.RDF_TYPE,
                subject__in=accessible_resources,
                object__uri=class_uri
            ).values_list('subject_id', flat=True)
        )

        if not entity_ids:
            return []

        try:
            # Get values for this property on these entities, only show meaningful aggregations
            values_qs = (
                Triple.objects.filter(
                    subject_id__in=entity_ids,
                    predicate__uri=property_uri
                )
                .values('object__uri', 'object__name', 'object__value', 'object__resource_type')
                .annotate(count=Count('subject_id'))
                .filter(count__gte=min_count)  # Only show values used multiple times
                .order_by('-count')[:limit]
            )

            values = []
            for row in values_qs:
                if row['object__resource_type'] == ResourceType.LITERAL:
                    # Literal value
                    value = row['object__value'] or str(row['object__uri'])
                    label = value[:100] if len(value) > 100 else value
                else:
                    # Linked resource
                    label = row['object__name'] or row['object__uri']
                    value = row['object__uri']

                values.append({
                    'value': value,
                    'label': label,
                    'count': row['count'],
                    'type': row['object__resource_type']
                })

            self.logger.info(f"explorer.values class={class_uri} property={property_uri} count={len(values)}")
            return values

        except Exception as e:
            self.logger.error(f"Error getting values for {class_uri}/{property_uri}: {e}")
            return []

    def get_values_for_property_from_entities(self, property_uri: str, entity_ids: List[str], limit: int = 20, min_count: int = 1) -> List[Dict[str, Any]]:
        """Get available values for a specific property from a specific set of entities."""
        if not property_uri or not entity_ids:
            return []

        try:
            # Get values for this property on these specific entities
            values_qs = (
                Triple.objects.filter(
                    subject_id__in=entity_ids,
                    predicate__uri=property_uri
                )
                .values('object__uri', 'object__name', 'object__value', 'object__resource_type')
                .annotate(count=Count('subject_id'))
                .filter(count__gte=min_count)  # Only show values used multiple times
                .order_by('-count')[:limit]
            )

            values = []
            for row in values_qs:
                if row['object__resource_type'] == ResourceType.LITERAL:
                    # Literal value
                    value = row['object__value'] or str(row['object__uri'])
                    label = value[:100] if len(value) > 100 else value
                else:
                    # Linked resource
                    label = row['object__name'] or row['object__uri']
                    value = row['object__uri']

                values.append({
                    'value': value,
                    'label': label,
                    'count': row['count'],
                    'type': row['object__resource_type']
                })

            self.logger.info(f"explorer.values property={property_uri} entities={len(entity_ids)} values={len(values)}")
            return values

        except Exception as e:
            self.logger.error(f"Error getting values for {property_uri} from entities: {e}")
            return []
