from typing import Dict, List, Optional, Set, Tuple
from django.db.models import QuerySet, Prefetch, Q, Count
from django.contrib.auth import get_user_model
from arkumu.metadata.models import Resource, Triple, HarmonizationRule
from arkumu.metadata.models.resource import ResourceType, PublicAccessLevel

User = get_user_model()


class CatalogNavigationService:
    """Service for efficient catalog navigation with optimized queries."""
    
    # Common RDF predicates for relationships
    RDF_TYPE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
    RDFS_LABEL = 'http://www.w3.org/2000/01/rdf-schema#label'
    DC_TITLE = 'http://purl.org/dc/terms/title'
    
    # Arkumu model URIs (actual harmonized German terms)
    ARKUMU_PROJECT = 'http://arkumu.org/types/projekt'
    ARKUMU_EVENT = 'http://arkumu.org/types/ereignis'
    ARKUMU_PERSON = 'http://arkumu.org/types/akteurin'
    ARKUMU_ORGANIZATION = 'http://arkumu.org/types/einliefernde-hochschule'
    ARKUMU_DOCUMENT = 'http://arkumu.org/types/digitales-objekt'
    
    # Common relationship predicates
    HAS_EVENT = 'http://arkumu.org/properties/hasEvent'
    HAS_PARTICIPANT = 'http://arkumu.org/properties/hasParticipant'
    HAS_DOCUMENT = 'http://arkumu.org/properties/hasDocument'
    RELATED_TO = 'http://arkumu.org/properties/relatedTo'
    
    def __init__(self, user: User):
        self.user = user
        
    def _get_harmonized_types(self, arkumu_type: str) -> List[str]:
        """Get all organization-specific URIs that map to an Arkumu type."""
        # Find all HarmonizationRules that map to this Arkumu type
        rules = HarmonizationRule.objects.filter(
            catalog_property_uri=arkumu_type,
            is_active=True
        )
        
        # Collect all original URIs that map to this type
        mapped_uris = [arkumu_type]  # Include the generic type
        mapped_uris.extend([rule.source_property_pattern for rule in rules])
        
        # Only use explicit harmonization rules - no pattern matching fallback
        # This ensures complete control over which organizations are harmonized
        
        return mapped_uris
    
    def get_all_projects(self, 
                        include_events: bool = True, 
                        include_participants: bool = True,
                        include_documents: bool = False) -> QuerySet:
        """
        Get all projects with optional related resources using optimized queries.
        
        Args:
            include_events: Include related events
            include_participants: Include related participants (persons/organizations)
            include_documents: Include related documents
            
        Returns:
            QuerySet of project resources with prefetched relationships
        """
        # Get all URIs that represent "Project" type across organizations
        project_types = self._get_harmonized_types(self.ARKUMU_PROJECT)
        
        # Find the rdf:type predicate resource
        rdf_type_resource = Resource.objects.filter(uri=self.RDF_TYPE).first()
        if not rdf_type_resource:
            return Resource.objects.none()
        
        # Find all resources that are typed as projects
        # Use raw Triple query for type lookups - types should be universally accessible
        project_triples = Triple.objects.filter(
            predicate=rdf_type_resource,
            object__uri__in=project_types
        ).select_related('subject')
        
        project_ids = list(project_triples.values_list('subject_id', flat=True))
        
        # Base queryset for projects - build filter based on user access
        if not self.user.is_authenticated:
            # Anonymous users can only see public, approved resources
            projects = Resource.objects.filter(
                id__in=project_ids,
                public_access_level=PublicAccessLevel.PUBLIC,
                is_public_approved=True
            )
        elif hasattr(self.user, 'role') and self.user.role == 'system_admin':
            # System admins see everything
            projects = Resource.objects.filter(id__in=project_ids)
        else:
            # Authenticated users see their org data and public resources
            from django.db.models import Q
            q = Q(id__in=project_ids)
            
            org_filter = Q()
            if hasattr(self.user, 'organization') and self.user.organization:
                org_filter |= Q(organization=self.user.organization)
            
            public_filter = Q(
                public_access_level__in=[PublicAccessLevel.PUBLIC, PublicAccessLevel.RESTRICTED],
                is_public_approved=True
            )
            
            projects = Resource.objects.filter(q & (org_filter | public_filter))
        
        # Build prefetch queries
        prefetches = []
        
        # Prefetch labels/titles
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
        
        if include_events:
            # Get all event relationship predicates
            event_predicates = self._get_harmonized_types(self.HAS_EVENT)
            event_predicate_resources = Resource.objects.filter(uri__in=event_predicates)
            
            prefetches.append(
                Prefetch(
                    'subject_triples',
                    queryset=Triple.objects.for_user(self.user).filter(
                        predicate__in=event_predicate_resources
                    ).select_related('predicate', 'object'),
                    to_attr='event_triples'
                )
            )
        
        if include_participants:
            participant_predicates = self._get_harmonized_types(self.HAS_PARTICIPANT)
            participant_predicate_resources = Resource.objects.filter(uri__in=participant_predicates)
            
            prefetches.append(
                Prefetch(
                    'subject_triples',
                    queryset=Triple.objects.for_user(self.user).filter(
                        predicate__in=participant_predicate_resources
                    ).select_related('predicate', 'object'),
                    to_attr='participant_triples'
                )
            )
        
        if include_documents:
            document_predicates = self._get_harmonized_types(self.HAS_DOCUMENT)
            document_predicate_resources = Resource.objects.filter(uri__in=document_predicates)
            
            prefetches.append(
                Prefetch(
                    'subject_triples',
                    queryset=Triple.objects.for_user(self.user).filter(
                        predicate__in=document_predicate_resources
                    ).select_related('predicate', 'object'),
                    to_attr='document_triples'
                )
            )
        
        # Apply all prefetches
        return projects.prefetch_related(*prefetches).distinct()
    
    def get_project_with_full_graph(self, project_uri: str, depth: int = 2) -> Dict:
        """
        Get a project with its full relationship graph up to specified depth.
        
        Args:
            project_uri: URI of the project
            depth: How many levels of relationships to follow
            
        Returns:
            Dictionary with project data and relationships
        """
        # Get the project resource with proper access control
        try:
            if not self.user.is_authenticated:
                project = Resource.objects.filter(
                    uri=project_uri,
                    public_access_level=PublicAccessLevel.PUBLIC,
                    is_public_approved=True
                ).first()
            elif hasattr(self.user, 'role') and self.user.role == 'system_admin':
                project = Resource.objects.get(uri=project_uri)
            else:
                from django.db.models import Q
                org_filter = Q()
                if hasattr(self.user, 'organization') and self.user.organization:
                    org_filter = Q(organization=self.user.organization)
                
                public_filter = Q(
                    public_access_level__in=[PublicAccessLevel.PUBLIC, PublicAccessLevel.RESTRICTED],
                    is_public_approved=True
                )
                
                project = Resource.objects.filter(
                    Q(uri=project_uri) & (org_filter | public_filter)
                ).first()
                
            if not project:
                return None
        except Resource.DoesNotExist:
            return None
        
        result = {
            'project': {
                'uri': project.uri,
                'id': str(project.id),
                'labels': [],
                'relationships': {}
            }
        }
        
        # Get all triples for this project (as subject)
        project_triples = Triple.objects.for_user(self.user).filter(
            subject=project
        ).select_related('predicate', 'object', 'object__organization')
        
        # Group by predicate type
        relationships_by_type = {}
        for triple in project_triples:
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
                result['project']['labels'].append(triple.object.value)
            else:
                relationships_by_type[pred_uri].append(obj_data)
        
        result['project']['relationships'] = relationships_by_type
        
        # If depth > 1, recursively get relationships
        if depth > 1:
            visited = {project.id}
            result['related_resources'] = self._get_related_resources(
                project_triples, depth - 1, visited
            )
        
        return result
    
    def _get_related_resources(self, triples: QuerySet, depth: int, visited: Set) -> Dict:
        """Recursively get related resources up to specified depth."""
        if depth <= 0:
            return {}
        
        related = {}
        
        for triple in triples:
            if triple.object.id in visited or triple.object.resource_type == ResourceType.LITERAL:
                continue
            
            visited.add(triple.object.id)
            
            # Get triples where this object is the subject
            object_triples = Triple.objects.for_user(self.user).filter(
                subject=triple.object
            ).select_related('predicate', 'object')
            
            resource_data = {
                'uri': triple.object.uri,
                'value': triple.object.value,
                'type': triple.object.resource_type,
                'relationships': {}
            }
            
            # Group relationships by predicate
            for obj_triple in object_triples:
                pred_uri = obj_triple.predicate.uri or obj_triple.predicate.value
                if pred_uri not in resource_data['relationships']:
                    resource_data['relationships'][pred_uri] = []
                
                resource_data['relationships'][pred_uri].append({
                    'uri': obj_triple.object.uri,
                    'value': obj_triple.object.value,
                    'type': obj_triple.object.resource_type
                })
            
            related[str(triple.object.id)] = resource_data
            
            # Recurse if depth allows
            if depth > 1:
                sub_related = self._get_related_resources(
                    object_triples, depth - 1, visited
                )
                related.update(sub_related)
        
        return related
    
    def get_resource_counts_by_type(self) -> Dict[str, int]:
        """Get counts of resources by their Arkumu type for catalog overview."""
        # Define the main types we want to count
        arkumu_types = [
            (self.ARKUMU_PROJECT, 'projects'),
            (self.ARKUMU_EVENT, 'events'),
            (self.ARKUMU_PERSON, 'persons'),
            (self.ARKUMU_ORGANIZATION, 'organizations'),
            (self.ARKUMU_DOCUMENT, 'documents')
        ]
        
        counts = {}
        
        # Get rdf:type predicate
        rdf_type_resource = Resource.objects.filter(uri=self.RDF_TYPE).first()
        if not rdf_type_resource:
            return {name: 0 for _, name in arkumu_types}
        
        for arkumu_uri, name in arkumu_types:
            # Get all URIs that map to this type
            type_uris = self._get_harmonized_types(arkumu_uri)
            
            # Count resources of this type
            count = Triple.objects.for_user(self.user).filter(
                predicate=rdf_type_resource,
                object__uri__in=type_uris
            ).values('subject').distinct().count()
            
            counts[name] = count
        
        return counts
    
    def search_resources(self, 
                        query: str, 
                        resource_types: Optional[List[str]] = None,
                        limit: int = 50) -> QuerySet:
        """
        Search for resources by their connected literal values and properties.
        
        This searches within the actual content (literal values) connected to resources,
        not just the resource URIs themselves.
        
        Args:
            query: Search query string
            resource_types: List of Arkumu type URIs to filter by
            limit: Maximum number of results
            
        Returns:
            QuerySet of matching resources
        """
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
            base_access_filter = Q()  # No restrictions
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
        
        # Filter by resource type if specified
        if resource_types:
            rdf_type_resource = Resource.objects.filter(uri=self.RDF_TYPE).first()
            if rdf_type_resource:
                # Get all URIs for the requested types (including harmonized types)
                all_type_uris = []
                for arkumu_type in resource_types:
                    all_type_uris.extend(self._get_harmonized_types(arkumu_type))
                
                # Find resources that have the correct type
                # Use raw Triple query for type lookups - types should be universally accessible
                typed_resource_ids = Triple.objects.filter(
                    predicate=rdf_type_resource,
                    object__uri__in=all_type_uris
                ).values_list('subject_id', flat=True)
                
                matching_resources = matching_resources.filter(id__in=typed_resource_ids)
        
        return matching_resources.select_related('organization').distinct()[:limit]