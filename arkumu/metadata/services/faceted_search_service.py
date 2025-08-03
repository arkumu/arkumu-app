"""
Faceted search service for filtering resources by their property values.
"""

from typing import Dict, List, Optional, Set, Tuple
from django.db.models import QuerySet, Q, Count, Exists, OuterRef
from django.contrib.auth import get_user_model
from arkumu.metadata.models import Resource, Triple, HarmonizationRule
from arkumu.metadata.models.resource import ResourceType, PublicAccessLevel
from arkumu.metadata.services.catalog_navigation_service import CatalogNavigationService

User = get_user_model()


class FacetedSearchService(CatalogNavigationService):
    """Service for faceted search with property-based filtering."""
    
    def _get_harmonized_base_queryset(self) -> QuerySet:
        """Get base queryset filtered to only organizations with explicit harmonization rules."""
        from django.db.models import Q
        
        # ONLY include resources from organizations with explicit harmonization rules
        harmonized_org_ids = HarmonizationRule.objects.filter(
            is_active=True
        ).values_list('source_organization_id', flat=True).distinct()
        
        harmonization_filter = Q(organization_id__in=harmonized_org_ids)
        
        # For harmonized resources, require authentication
        if not self.user.is_authenticated:
            # Anonymous users cannot access any resources
            return Resource.objects.none()
        elif hasattr(self.user, 'role') and self.user.role == 'system_admin':
            base_access_filter = Q()  # No restrictions
        else:
            # Authenticated users can access all harmonized resources (including private)
            # since harmonization implies cross-organizational searchability
            base_access_filter = Q()  # Allow all harmonized resources
        
        return Resource.objects.filter(base_access_filter & harmonization_filter)
    
    def search_resources(self, query: str, resource_types=None, limit=50) -> QuerySet:
        """Override parent method to only search harmonized resources."""
        from django.db.models import Q
        
        if not query.strip():
            return Resource.objects.none()
        
        # Get harmonized resources first
        harmonized_resources = self._get_harmonized_base_queryset()
        
        # Use same access control as harmonized base queryset for consistency
        if not self.user.is_authenticated:
            base_access_filter = Q(
                public_access_level=PublicAccessLevel.PUBLIC,
                is_public_approved=True
            )
        elif hasattr(self.user, 'role') and self.user.role == 'system_admin':
            base_access_filter = Q()
        else:
            # For harmonized search, allow all harmonized resources (including private)
            # since harmonization implies cross-organizational searchability
            base_access_filter = Q()  # Allow all harmonized resources
        
        # Search in literal values connected to harmonized resources
        harmonized_resource_ids = list(harmonized_resources.values_list('id', flat=True))
        if not harmonized_resource_ids:
            return Resource.objects.none()
        
        # Use raw Triple query for literal searches since we already filtered to harmonized resources
        matching_literal_triples = Triple.objects.filter(
            subject_id__in=harmonized_resource_ids,
            object__resource_type=ResourceType.LITERAL,
            object__value__icontains=query
        ).select_related('subject')
        
        literal_match_resource_ids = list(
            matching_literal_triples.values_list('subject_id', flat=True).distinct()
        )
        
        # Also search in resource URIs/names but only for harmonized resources
        direct_match_resources = harmonized_resources.filter(
            base_access_filter & (Q(value__icontains=query) | Q(name__icontains=query) | Q(uri__icontains=query))
        )
        direct_match_resource_ids = list(direct_match_resources.values_list('id', flat=True))
        
        # Combine both strategies
        all_matching_ids = list(set(literal_match_resource_ids + direct_match_resource_ids))
        
        if not all_matching_ids:
            return Resource.objects.none()
        
        # Apply access control to the final results
        # Since we already filtered to harmonized resources only, use the harmonized access control
        matching_resources = Resource.objects.filter(
            Q(id__in=all_matching_ids) & base_access_filter
        )
        
        # Filter by resource type if specified
        if resource_types:
            rdf_type_resource = Resource.objects.filter(uri=self.RDF_TYPE).first()
            if rdf_type_resource:
                all_type_uris = []
                for arkumu_type in resource_types:
                    all_type_uris.extend(self._get_harmonized_types(arkumu_type))
                
                # Use raw Triple query for type lookups - types should be universally accessible
                typed_resource_ids = Triple.objects.filter(
                    predicate=rdf_type_resource,
                    object__uri__in=all_type_uris,
                    subject_id__in=harmonized_resource_ids  # Only harmonized resources
                ).values_list('subject_id', flat=True)
                
                matching_resources = matching_resources.filter(id__in=typed_resource_ids)
        
        return matching_resources.select_related('organization').distinct()[:limit]
    
    def discover_and_cache_properties(self, resource_type: str) -> Dict[str, Dict]:
        """
        Discover all properties for a resource type and cache them.
        Called when user first visits catalog search.
        """
        from django.core.cache import cache
        from collections import Counter
        
        cache_key = f'catalog_properties_{resource_type}_{self.user.organization.code if self.user.organization else "all"}'
        
        # Check if already cached
        cached_properties = cache.get(cache_key)
        if cached_properties:
            return cached_properties
        
        # Discover properties from actual data
        arkumu_type = self.ARKUMU_PROJECT if resource_type == 'projects' else self.ARKUMU_EVENT
        type_uris = self._get_harmonized_types(arkumu_type)
        
        # Find resources of this type (only harmonized ones)
        rdf_type_resource = Resource.objects.filter(uri=self.RDF_TYPE).first()
        if not rdf_type_resource:
            return {}
        
        # Only include harmonized resources
        harmonized_resources = self._get_harmonized_base_queryset()
        
        # Use raw Triple query for type lookups - types should be universally accessible
        resource_triples = Triple.objects.filter(
            predicate=rdf_type_resource,
            object__uri__in=type_uris,
            subject__in=harmonized_resources
        )
        resource_ids = list(resource_triples.values_list('subject_id', flat=True))
        
        if not resource_ids:
            return {}
        
        # Get all properties that these resources have with literal values
        # Use raw Triple query since we already filtered to harmonized resources
        property_triples = Triple.objects.filter(
            subject_id__in=resource_ids,
            object__resource_type=ResourceType.LITERAL
        ).values('predicate__uri', 'predicate__value').annotate(
            count=Count('subject', distinct=True)
        ).order_by('-count')
        
        # Build property definitions
        properties = {}
        
        # Add "All Properties" option first
        properties['all_properties'] = {
            'label': 'All Properties',
            'uri': None,
            'description': f'Search across all {resource_type} properties',
            'count': len(resource_ids),
            'is_searchable': True,
            'is_facetable': False
        }
        
        for prop_data in property_triples:
            prop_uri = prop_data['predicate__uri']
            if not prop_uri:
                continue
                
            prop_key = prop_uri.split('/')[-1]  # e.g., 'originaltitel'
            
            # Generate human-readable label
            label = self._generate_property_label(prop_key)
            
            # Determine if property is good for faceting (categorical) or searching (text)
            # Use raw Triple query since we already filtered to harmonized resources
            sample_values = Triple.objects.filter(
                subject_id__in=resource_ids[:10],  # Sample from first 10 resources
                predicate__uri=prop_uri,
                object__resource_type=ResourceType.LITERAL
            ).values_list('object__value', flat=True)[:5]
            
            is_facetable = self._is_facetable_property(sample_values)
            is_searchable = self._is_searchable_property(sample_values)
            
            properties[prop_key] = {
                'label': label,
                'uri': prop_uri,
                'description': f'Search in {label.lower()}',
                'count': prop_data['count'],
                'is_searchable': is_searchable,
                'is_facetable': is_facetable
            }
        
        # Cache for 1 hour
        cache.set(cache_key, properties, 60 * 60)
        
        return properties
    
    def _generate_property_label(self, prop_key: str) -> str:
        """Generate human-readable label from property key."""
        # Common mappings
        label_mappings = {
            'originaltitel': 'Original Title',
            'beschreibung-verkettet': 'Description',
            'kurzinformation-engl': 'Short Description (English)',
            'projektart-calc': 'Project Type',
            'faechergruppe': 'Subject Area',
            'rechtsstatus': 'Rights Status',
            'originaltitel-sprache': 'Language',
            'eventname': 'Event Name',
            'website': 'Website',
            'ort': 'Location',
            'projekt-uuid': 'Project ID',
            'pr-aenderungsts': 'Last Modified',
            'pr-erstellungsts': 'Created',
            'laenge-dauer': 'Duration',
            'projekt-website1': 'Project Website'
        }
        
        if prop_key in label_mappings:
            return label_mappings[prop_key]
        
        # Generate from key: "some-property-name" -> "Some Property Name"
        return ' '.join(word.capitalize() for word in prop_key.replace('-', ' ').replace('_', ' ').split())
    
    def _is_facetable_property(self, sample_values: List[str]) -> bool:
        """Determine if property is good for faceting (categorical values)."""
        if not sample_values:
            return False
        
        # If values are short and repetitive, it's probably categorical
        avg_length = sum(len(v) for v in sample_values) / len(sample_values)
        unique_ratio = len(set(sample_values)) / len(sample_values)
        
        # Good for faceting if: short values, low uniqueness
        return avg_length < 50 and unique_ratio < 0.8
    
    def _is_searchable_property(self, sample_values: List[str]) -> bool:
        """Determine if property is good for text search."""
        if not sample_values:
            return False
        
        # If values are longer text, it's good for searching
        avg_length = sum(len(v) for v in sample_values) / len(sample_values)
        
        # Good for searching if: longer text values
        return avg_length > 10
    
    def get_facet_values(self, resource_type: str, facet_key: str, limit: int = 20) -> List[Dict]:
        """Get available values for a specific facet."""
        # Get properties dynamically
        properties = self.discover_and_cache_properties(resource_type)
        if facet_key not in properties or not properties[facet_key]['is_facetable']:
            return []
        
        prop_config = properties[facet_key]
        prop_uri = prop_config['uri']
        
        # Get the resource type URIs
        arkumu_type = self.ARKUMU_PROJECT if resource_type == 'projects' else self.ARKUMU_EVENT
        type_uris = self._get_harmonized_types(arkumu_type)
        
        # Find resources of this type (only harmonized ones)
        rdf_type_resource = Resource.objects.filter(uri=self.RDF_TYPE).first()
        if not rdf_type_resource:
            return []
        
        # Only include harmonized resources
        harmonized_resources = self._get_harmonized_base_queryset()
        
        # Use raw Triple query for type lookups - types should be universally accessible
        resource_triples = Triple.objects.filter(
            predicate=rdf_type_resource,
            object__uri__in=type_uris,
            subject__in=harmonized_resources
        )
        resource_ids = list(resource_triples.values_list('subject_id', flat=True))
        
        # Get facet values with counts
        # Use raw Triple query since we already filtered to harmonized resources
        facet_triples = Triple.objects.filter(
            subject_id__in=resource_ids,
            predicate__uri=prop_uri,
            object__resource_type=ResourceType.LITERAL
        ).values('object__value').annotate(
            count=Count('subject', distinct=True)
        ).order_by('-count')[:limit]
        
        return [
            {
                'value': item['object__value'], 
                'count': item['count'],
                'label': item['object__value']
            } 
            for item in facet_triples if item['object__value']
        ]
    
    def get_all_facet_values(self, resource_type: str) -> Dict[str, List[Dict]]:
        """Get all facet values for a resource type."""
        properties = self.discover_and_cache_properties(resource_type)
        result = {}
        
        # Only include facetable properties
        for facet_key, prop_config in properties.items():
            if prop_config['is_facetable']:
                result[facet_key] = self.get_facet_values(resource_type, facet_key)
        
        return result
    
    def get_searchable_properties(self, resource_type: str) -> Dict[str, Dict]:
        """Get searchable properties for a resource type."""
        properties = self.discover_and_cache_properties(resource_type)
        
        # Only return searchable properties
        return {
            key: prop_config for key, prop_config in properties.items()
            if prop_config['is_searchable']
        }
    
    def search_with_facets(self, 
                          query: str = "",
                          resource_type: str = "",
                          search_property: str = "",
                          facet_filters: Dict[str, List[str]] = None,
                          limit: int = 50) -> QuerySet:
        """
        Search resources with faceted filtering and property-specific search.
        
        Args:
            query: Text search query
            resource_type: 'projects' or 'events'
            search_property: Specific property to search in (e.g., 'originaltitel')
            facet_filters: Dict of facet_key -> list of selected values
            limit: Maximum results
        """
        from django.db.models import Q
        
        if facet_filters is None:
            facet_filters = {}
        
        # Start with base search if query provided
        if query.strip():
            if search_property and search_property != 'all_properties':
                # Property-specific search
                resource_ids = self._search_in_specific_property(
                    query=query,
                    resource_type=resource_type,
                    property_key=search_property
                )
            else:
                # Search across all properties (current behavior)
                matching_resources = self.search_resources(
                    query=query,
                    resource_types=[self.ARKUMU_PROJECT if resource_type == 'projects' else self.ARKUMU_EVENT] if resource_type else None,
                    limit=limit * 3  # Get more to allow for facet filtering
                )
                resource_ids = list(matching_resources.values_list('id', flat=True))
        else:
            # No query - get all harmonized resources of the specified type
            harmonized_resources = self._get_harmonized_base_queryset()
            
            if resource_type == 'projects':
                # Get harmonized projects
                project_types = self._get_harmonized_types(self.ARKUMU_PROJECT)
                rdf_type_resource = Resource.objects.filter(uri=self.RDF_TYPE).first()
                if not rdf_type_resource:
                    return Resource.objects.none()
                
                # Use raw Triple query for type lookups - types should be universally accessible
                project_triples = Triple.objects.filter(
                    predicate=rdf_type_resource,
                    object__uri__in=project_types,
                    subject__in=harmonized_resources
                ).select_related('subject')
                
                project_ids = list(project_triples.values_list('subject_id', flat=True))
                matching_resources = Resource.objects.filter(id__in=project_ids)
                
            elif resource_type == 'events':
                # Get harmonized events
                event_types = self._get_harmonized_types(self.ARKUMU_EVENT)
                rdf_type_resource = Resource.objects.filter(uri=self.RDF_TYPE).first()
                if not rdf_type_resource:
                    return Resource.objects.none()
                
                # Use raw Triple query for type lookups - types should be universally accessible
                event_triples = Triple.objects.filter(
                    predicate=rdf_type_resource,
                    object__uri__in=event_types,
                    subject__in=harmonized_resources
                ).select_related('subject')
                
                event_ids = list(event_triples.values_list('subject_id', flat=True))
                matching_resources = Resource.objects.filter(id__in=event_ids)
            else:
                # No type specified - search all harmonized resources
                matching_resources = harmonized_resources
            
            resource_ids = list(matching_resources.values_list('id', flat=True))
        
        # Apply facet filters
        for facet_key, selected_values in facet_filters.items():
            if not selected_values:
                continue
            
            # Get the facet configuration
            facets = self.PROJECT_FACETS if resource_type == 'projects' else self.EVENT_FACETS
            if facet_key not in facets:
                continue
            
            facet_config = facets[facet_key]
            predicate_suffix = facet_config['predicate_suffix']
            
            # Find resources that have any of the selected values for this facet
            predicate_resources = Resource.objects.filter(
                uri__endswith=predicate_suffix
            )
            
            facet_resource_ids = Triple.objects.for_user(self.user).filter(
                subject_id__in=resource_ids,
                predicate__in=predicate_resources,
                object__resource_type=ResourceType.LITERAL,
                object__value__in=selected_values
            ).values_list('subject_id', flat=True).distinct()
            
            # Filter down to only resources that match this facet
            resource_ids = list(set(resource_ids) & set(facet_resource_ids))
        
        # Return final filtered resources
        if not resource_ids:
            return Resource.objects.none()
        
        # For harmonized search, we already filtered to harmonized resources
        # Apply consistent access control - require authentication
        if not self.user.is_authenticated:
            # Anonymous users cannot access any resources
            return Resource.objects.none()
        elif hasattr(self.user, 'role') and self.user.role == 'system_admin':
            base_access_filter = Q()  # No restrictions
        else:
            # Authenticated users can access all harmonized resources (including private)
            # since harmonization implies cross-organizational searchability
            base_access_filter = Q()  # Allow all harmonized resources
        
        return Resource.objects.filter(
            Q(id__in=resource_ids) & base_access_filter
        ).select_related('organization').distinct()[:limit]
    
    def _search_in_specific_property(self, query: str, resource_type: str, property_key: str) -> List[int]:
        """Search within a specific property and return resource IDs."""
        properties = self.discover_and_cache_properties(resource_type)
        if property_key not in properties:
            return []
        
        prop_config = properties[property_key]
        prop_uri = prop_config['uri']
        
        # Get resource type URIs
        arkumu_type = self.ARKUMU_PROJECT if resource_type == 'projects' else self.ARKUMU_EVENT
        type_uris = self._get_harmonized_types(arkumu_type)
        
        # Find resources of this type (only harmonized ones)
        rdf_type_resource = Resource.objects.filter(uri=self.RDF_TYPE).first()
        if not rdf_type_resource:
            return []
        
        # Only include harmonized resources
        harmonized_resources = self._get_harmonized_base_queryset()
        
        # Use raw Triple query for type lookups - types should be universally accessible
        resource_triples = Triple.objects.filter(
            predicate=rdf_type_resource,
            object__uri__in=type_uris,
            subject__in=harmonized_resources
        )
        resource_ids = list(resource_triples.values_list('subject_id', flat=True))
        
        # Search within the specific property
        # Use raw Triple query since we already filtered to harmonized resources
        matching_triples = Triple.objects.filter(
            subject_id__in=resource_ids,
            predicate__uri=prop_uri,
            object__resource_type=ResourceType.LITERAL,
            object__value__icontains=query
        ).values_list('subject_id', flat=True).distinct()
        
        return list(matching_triples)