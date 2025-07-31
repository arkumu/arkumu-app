"""
Faceted search service for filtering resources by their property values.
"""

from typing import Dict, List, Optional, Set, Tuple
from django.db.models import QuerySet, Q, Count
from django.contrib.auth import get_user_model
from arkumu.metadata.models import Resource, Triple, HarmonizationRule
from arkumu.metadata.models.resource import ResourceType, PublicAccessLevel
from arkumu.metadata.services.catalog_navigation_service import CatalogNavigationService

User = get_user_model()


class FacetedSearchService(CatalogNavigationService):
    """Service for faceted search with property-based filtering."""
    
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
        
        # Find resources of this type
        rdf_type_resource = Resource.objects.filter(uri=self.RDF_TYPE).first()
        if not rdf_type_resource:
            return {}
        
        resource_triples = Triple.objects.for_user(self.user).filter(
            predicate=rdf_type_resource,
            object__uri__in=type_uris
        )
        resource_ids = list(resource_triples.values_list('subject_id', flat=True))
        
        if not resource_ids:
            return {}
        
        # Get all properties that these resources have with literal values
        property_triples = Triple.objects.for_user(self.user).filter(
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
            sample_values = Triple.objects.for_user(self.user).filter(
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
        
        # Find resources of this type
        rdf_type_resource = Resource.objects.filter(uri=self.RDF_TYPE).first()
        if not rdf_type_resource:
            return []
        
        resource_triples = Triple.objects.for_user(self.user).filter(
            predicate=rdf_type_resource,
            object__uri__in=type_uris
        )
        resource_ids = list(resource_triples.values_list('subject_id', flat=True))
        
        # Get facet values with counts
        facet_triples = Triple.objects.for_user(self.user).filter(
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
            # No query - get all resources of the specified type
            if resource_type == 'projects':
                matching_resources = self.get_all_projects()
            elif resource_type == 'events':
                # Get events using same pattern as projects
                event_types = self._get_harmonized_types(self.ARKUMU_EVENT)
                rdf_type_resource = Resource.objects.filter(uri=self.RDF_TYPE).first()
                if not rdf_type_resource:
                    return Resource.objects.none()
                
                event_triples = Triple.objects.for_user(self.user).filter(
                    predicate=rdf_type_resource,
                    object__uri__in=event_types
                ).select_related('subject')
                
                event_ids = list(event_triples.values_list('subject_id', flat=True))
                matching_resources = Resource.objects.filter(id__in=event_ids)
            else:
                # No type specified - search all
                matching_resources = Resource.objects.none()
            
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
        
        # Apply access control
        if not self.user.is_authenticated:
            base_access_filter = Q(
                public_access_level=PublicAccessLevel.PUBLIC,
                is_public_approved=True
            )
        elif hasattr(self.user, 'role') and self.user.role == 'system_admin':
            base_access_filter = Q()
        else:
            org_filter = Q()
            if hasattr(self.user, 'organization') and self.user.organization:
                org_filter = Q(organization=self.user.organization)
            
            public_filter = Q(
                public_access_level__in=[PublicAccessLevel.PUBLIC, PublicAccessLevel.RESTRICTED],
                is_public_approved=True
            )
            
            base_access_filter = org_filter | public_filter
        
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
        
        # Find resources of this type
        rdf_type_resource = Resource.objects.filter(uri=self.RDF_TYPE).first()
        if not rdf_type_resource:
            return []
        
        resource_triples = Triple.objects.for_user(self.user).filter(
            predicate=rdf_type_resource,
            object__uri__in=type_uris
        )
        resource_ids = list(resource_triples.values_list('subject_id', flat=True))
        
        # Search within the specific property
        matching_triples = Triple.objects.for_user(self.user).filter(
            subject_id__in=resource_ids,
            predicate__uri=prop_uri,
            object__resource_type=ResourceType.LITERAL,
            object__value__icontains=query
        ).values_list('subject_id', flat=True).distinct()
        
        return list(matching_triples)