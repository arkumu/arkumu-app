"""
Flexible catalog service that works with actual harmonized data.
"""

from typing import Dict, List, Optional, Set, Tuple
from django.db.models import QuerySet, Prefetch, Q, Count
from django.contrib.auth import get_user_model
from arkumu.metadata.models import Resource, Triple, HarmonizationRule
from arkumu.metadata.models.resource import ResourceType, PublicAccessLevel

User = get_user_model()


class FlexibleCatalogService:
    """Service for catalog navigation that adapts to actual harmonized data."""
    
    # Common RDF predicates
    RDF_TYPE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
    RDFS_LABEL = 'http://www.w3.org/2000/01/rdf-schema#label'
    DC_TITLE = 'http://purl.org/dc/terms/title'
    
    def __init__(self, user: User):
        self.user = user
        self._harmonized_types = None
        self._type_categories = None
    
    def _discover_harmonized_types(self) -> Dict[str, List[str]]:
        """Discover what types actually exist in harmonization rules."""
        if self._harmonized_types is not None:
            return self._harmonized_types
        
        # Get all type mappings from harmonization rules
        type_rules = HarmonizationRule.objects.filter(
            is_active=True,
            catalog_property_uri__contains='/types/'
        ).values_list('catalog_property_uri', flat=True).distinct()
        
        # Categorize types based on names (German/English keywords)
        categories = {
            'projects': [],
            'events': [],
            'persons': [], 
            'organizations': [],
            'documents': [],
            'other': []
        }
        
        # Keywords to identify types
        project_keywords = ['projekt', 'project', 'vorhaben', 'arbeit', 'werk']
        event_keywords = ['ereignis', 'event', 'veranstaltung', 'aufführung', 'konzert']
        person_keywords = ['person', 'akteur', 'künstler', 'student', 'dozent', 'mitarbeiter']
        org_keywords = ['organisation', 'organization', 'hochschule', 'institut', 'einrichtung']
        doc_keywords = ['dokument', 'document', 'datei', 'objekt', 'digital']
        
        for type_uri in type_rules:
            type_name = type_uri.split('/')[-1].lower()
            
            categorized = False
            for keyword in project_keywords:
                if keyword in type_name:
                    categories['projects'].append(type_uri)
                    categorized = True
                    break
            
            if not categorized:
                for keyword in event_keywords:
                    if keyword in type_name:
                        categories['events'].append(type_uri)
                        categorized = True
                        break
            
            if not categorized:
                for keyword in person_keywords:
                    if keyword in type_name:
                        categories['persons'].append(type_uri)
                        categorized = True
                        break
            
            if not categorized:
                for keyword in org_keywords:
                    if keyword in type_name:
                        categories['organizations'].append(type_uri)
                        categorized = True
                        break
            
            if not categorized:
                for keyword in doc_keywords:
                    if keyword in type_name:
                        categories['documents'].append(type_uri)
                        categorized = True
                        break
            
            if not categorized:
                categories['other'].append(type_uri)
        
        self._harmonized_types = categories
        return categories
    
    def _get_source_types_for_category(self, category: str) -> List[str]:
        """Get all source URIs that map to types in a category."""
        harmonized_types = self._discover_harmonized_types()
        target_types = harmonized_types.get(category, [])
        
        if not target_types:
            return []
        
        # Get all source patterns that map to these target types
        source_patterns = HarmonizationRule.objects.filter(
            is_active=True,
            catalog_property_uri__in=target_types
        ).values_list('source_property_pattern', flat=True)
        
        # Include both source patterns and target types
        all_types = list(source_patterns) + target_types
        return all_types
    
    def get_resource_counts_by_type(self) -> Dict[str, int]:
        """Get counts of resources by category."""
        counts = {}
        
        # Get RDF type resource
        rdf_type_resource = Resource.objects.filter(uri=self.RDF_TYPE).first()
        if not rdf_type_resource:
            return {'projects': 0, 'events': 0, 'persons': 0, 'organizations': 0, 'documents': 0}
        
        for category in ['projects', 'events', 'persons', 'organizations', 'documents']:
            type_uris = self._get_source_types_for_category(category)
            
            if not type_uris:
                counts[category] = 0
                continue
            
            # Count resources of these types
            count = Triple.objects.for_user(self.user).filter(
                predicate=rdf_type_resource,
                object__uri__in=type_uris
            ).values('subject').distinct().count()
            
            counts[category] = count
        
        return counts
    
    def get_resources_by_category(self, category: str, include_related: bool = True) -> QuerySet:
        """Get resources for a specific category."""
        type_uris = self._get_source_types_for_category(category)
        
        if not type_uris:
            return Resource.objects.none()
        
        # Get RDF type resource
        rdf_type_resource = Resource.objects.filter(uri=self.RDF_TYPE).first()
        if not rdf_type_resource:
            return Resource.objects.none()
        
        # Find resources of these types
        resource_triples = Triple.objects.for_user(self.user).filter(
            predicate=rdf_type_resource,
            object__uri__in=type_uris
        ).select_related('subject')
        
        resource_ids = list(resource_triples.values_list('subject_id', flat=True))
        
        # Build base queryset with access control
        if not self.user.is_authenticated:
            resources = Resource.objects.filter(
                id__in=resource_ids,
                public_access_level=PublicAccessLevel.PUBLIC,
                is_public_approved=True
            )
        elif hasattr(self.user, 'role') and self.user.role == 'system_admin':
            resources = Resource.objects.filter(id__in=resource_ids)
        else:
            from django.db.models import Q
            q = Q(id__in=resource_ids)
            
            org_filter = Q()
            if hasattr(self.user, 'organization') and self.user.organization:
                org_filter = Q(organization=self.user.organization)
            
            public_filter = Q(
                public_access_level__in=[PublicAccessLevel.PUBLIC, PublicAccessLevel.RESTRICTED],
                is_public_approved=True
            )
            
            resources = Resource.objects.filter(q & (org_filter | public_filter))
        
        # Add prefetches for related data if requested
        if include_related:
            prefetches = []
            
            # Prefetch labels
            label_predicates = Resource.objects.filter(
                uri__in=[self.RDFS_LABEL, self.DC_TITLE]
            )
            prefetches.append(
                Prefetch(
                    'subject_triples',
                    queryset=Triple.objects.for_user(self.user).filter(
                        predicate__in=label_predicates
                    ).select_related('predicate', 'object'),
                    to_attr='label_triples'
                )
            )
            
            # Prefetch some common relationships
            prefetches.append(
                Prefetch(
                    'subject_triples',
                    queryset=Triple.objects.for_user(self.user).select_related('predicate', 'object'),
                    to_attr='all_triples'
                )
            )
            
            resources = resources.prefetch_related(*prefetches)
        
        return resources.distinct()
    
    def get_all_projects(self, include_events: bool = True, include_participants: bool = True, include_documents: bool = False) -> QuerySet:
        """Get all project-like resources."""
        return self.get_resources_by_category('projects', include_related=True)
    
    def get_all_events(self, include_participants: bool = True) -> QuerySet:
        """Get all event-like resources."""
        return self.get_resources_by_category('events', include_related=True)
    
    def get_all_persons(self) -> QuerySet:
        """Get all person-like resources."""
        return self.get_resources_by_category('persons', include_related=True)
    
    def search_resources(self, query: str, resource_types: Optional[List[str]] = None, limit: int = 50) -> QuerySet:
        """Search for resources by their connected literal values and properties."""
        from django.db.models import Q
        
        if not query.strip():
            return Resource.objects.none()
        
        # Build base access control filter
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
        
        # STRATEGY 1: Find resources that have literal values matching the query
        # This searches in the actual content connected to resources
        matching_literal_triples = Triple.objects.for_user(self.user).filter(
            object__resource_type=ResourceType.LITERAL,
            object__value__icontains=query
        ).select_related('subject')
        
        # Get the subject resources (entities with matching literal content)
        literal_match_resource_ids = list(
            matching_literal_triples.values_list('subject_id', flat=True).distinct()
        )
        
        # STRATEGY 2: Also search in resource URIs/names (fallback)
        direct_match_resources = Resource.objects.filter(
            base_access_filter & (Q(value__icontains=query) | Q(name__icontains=query) | Q(uri__icontains=query))
        )
        direct_match_resource_ids = list(direct_match_resources.values_list('id', flat=True))
        
        # Combine both strategies
        all_matching_ids = list(set(literal_match_resource_ids + direct_match_resource_ids))
        
        if not all_matching_ids:
            return Resource.objects.none()
        
        # Apply access control to the final results
        matching_resources = Resource.objects.filter(
            Q(id__in=all_matching_ids) & base_access_filter
        )
        
        # Filter by category if specified
        if resource_types:
            # Map generic types to categories
            type_mapping = {
                'http://arkumu.org/types/Project': 'projects',
                'http://arkumu.org/types/Event': 'events', 
                'http://arkumu.org/types/Person': 'persons',
                'http://arkumu.org/types/Organization': 'organizations',
                'http://arkumu.org/types/Document': 'documents'
            }
            
            categories = []
            for resource_type in resource_types:
                if resource_type in type_mapping:
                    categories.append(type_mapping[resource_type])
            
            if categories:
                # Get all type URIs for these categories
                all_type_uris = []
                for category in categories:
                    all_type_uris.extend(self._get_source_types_for_category(category))
                
                if all_type_uris:
                    # Filter by type
                    rdf_type_resource = Resource.objects.filter(uri=self.RDF_TYPE).first()
                    if rdf_type_resource:
                        typed_resource_ids = Triple.objects.for_user(self.user).filter(
                            predicate=rdf_type_resource,
                            object__uri__in=all_type_uris
                        ).values_list('subject_id', flat=True)
                        
                        matching_resources = matching_resources.filter(id__in=typed_resource_ids)
        
        return matching_resources.select_related('organization').distinct()[:limit]
    
    def get_resource_with_relationships(self, resource_uri: str, depth: int = 2) -> Dict:
        """Get a resource with its relationships."""
        # Get the resource with access control
        try:
            if not self.user.is_authenticated:
                resource = Resource.objects.filter(
                    uri=resource_uri,
                    public_access_level=PublicAccessLevel.PUBLIC,
                    is_public_approved=True
                ).first()
            else:
                from django.db.models import Q
                q = Q(uri=resource_uri)
                
                org_filter = Q()
                if hasattr(self.user, 'organization') and self.user.organization:
                    org_filter = Q(organization=self.user.organization)
                
                public_filter = Q(
                    public_access_level__in=[PublicAccessLevel.PUBLIC, PublicAccessLevel.RESTRICTED],
                    is_public_approved=True
                )
                
                resource = Resource.objects.filter(q & (org_filter | public_filter)).first()
            
            if not resource:
                return None
        except Exception:
            return None
        
        result = {
            'project': {  # Keep 'project' for template compatibility
                'uri': resource.uri,
                'id': str(resource.id),
                'labels': [],
                'relationships': {}
            }
        }
        
        # Get all triples for this resource (as subject)
        resource_triples = Triple.objects.for_user(self.user).filter(
            subject=resource
        ).select_related('predicate', 'object', 'object__organization')
        
        # Group by predicate type
        relationships_by_type = {}
        for triple in resource_triples:
            pred_uri = triple.predicate.uri or triple.predicate.value
            if pred_uri not in relationships_by_type:
                relationships_by_type[pred_uri] = []
            
            obj_data = {
                'uri': triple.object.uri,
                'value': triple.object.value,
                'type': triple.object.resource_type,
                'id': str(triple.object.id)
            }
            
            # Handle labels specially
            if pred_uri in [self.RDFS_LABEL, self.DC_TITLE]:
                if triple.object.value:
                    result['project']['labels'].append(triple.object.value)
            else:
                relationships_by_type[pred_uri].append(obj_data)
        
        result['project']['relationships'] = relationships_by_type
        
        return result
    
    def get_debug_info(self) -> Dict:
        """Get debug information about discovered types."""
        harmonized_types = self._discover_harmonized_types()
        
        debug_info = {
            'discovered_categories': {},
            'total_harmonization_rules': HarmonizationRule.objects.filter(is_active=True).count(),
            'total_type_rules': HarmonizationRule.objects.filter(
                is_active=True,
                catalog_property_uri__contains='/types/'
            ).count()
        }
        
        for category, types in harmonized_types.items():
            debug_info['discovered_categories'][category] = {
                'count': len(types),
                'types': types[:5]  # First 5 for brevity
            }
        
        return debug_info