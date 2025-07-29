from typing import Dict, List, Any, Optional
from django.db import models
from django.core.cache import cache
from django.db.models import Q, Prefetch
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.models.mappings import Mapping
import logging

logger = logging.getLogger(__name__)


class ResourceRelationshipService:
    """Service for discovering and navigating relationships between resources."""
    
    def __init__(self):
        self.cache_timeout = 3600  # 1 hour
    
    def get_related_resources(self, resource_uri: str, max_depth: int = 2, organization: str = None) -> Dict[str, Any]:
        """
        Find all resources related to a given resource up to max_depth.
        
        Args:
            resource_uri: URI of the starting resource
            max_depth: Maximum depth to traverse relationships
            organization: Organization code to filter results
            
        Returns:
            Dictionary containing resource info, relationships, and graph data
        """
        cache_key = f"resource_relationships:{resource_uri}:{max_depth}:{organization}"
        cached_result = cache.get(cache_key)
        if cached_result:
            return cached_result
        
        try:
            # Get the starting resource
            resource_query = Resource.objects.filter(uri=resource_uri)
            if organization:
                resource_query = resource_query.filter(organization__code=organization)
            
            resource = resource_query.first()
            if not resource:
                raise Resource.DoesNotExist(f"Resource with URI {resource_uri} not found")
            
            # Build the relationship graph
            visited = set()
            graph = {'nodes': [], 'edges': []}
            relationships = {'outgoing': [], 'incoming': []}
            
            # Start traversal from the main resource
            self._traverse_relationships(resource, max_depth, 0, organization, visited, graph, relationships)
            
            result = {
                'resource': {
                    'uri': resource.uri,
                    'type': resource.resource_type,
                    'name': resource.name,
                    'organization': resource.organization.code if resource.organization else None,
                    'id': str(resource.id)
                },
                'relationships': relationships,
                'graph': {
                    'nodes': graph['nodes'],
                    'edges': graph['edges'],
                    'depth': max_depth,
                    'organization': organization
                }
            }
            
            cache.set(cache_key, result, self.cache_timeout)
            return result
            
        except Exception as e:
            logger.error(f"Error getting related resources for {resource_uri}: {str(e)}")
            raise
    
    def _traverse_relationships(self, resource: Resource, max_depth: int, current_depth: int, 
                               organization: str, visited: set, graph: Dict, relationships: Dict):
        """
        Recursively traverse relationships to build the graph.
        
        Args:
            resource: Current resource being processed
            max_depth: Maximum depth to traverse
            current_depth: Current traversal depth
            organization: Organization filter
            visited: Set of visited resource URIs
            graph: Graph structure being built
            relationships: Relationships structure being built
        """
        if current_depth > max_depth or resource.uri in visited:
            return
        
        visited.add(resource.uri)
        
        # Add current resource to graph nodes
        graph['nodes'].append({
            'id': str(resource.id),
            'uri': resource.uri,
            'name': resource.name,
            'type': resource.resource_type,
            'organization': resource.organization.code if resource.organization else None,
            'depth': current_depth
        })
        
        # Find outgoing relationships (where this resource is the subject)
        outgoing_query = Triple.objects.filter(subject=resource).select_related('predicate', 'object')
        if organization:
            outgoing_query = outgoing_query.filter(object__organization__code=organization)
        
        for triple in outgoing_query:
            if triple.object.uri not in visited:
                relationship_data = {
                    'predicate': triple.predicate.uri,
                    'predicate_name': triple.predicate.name or triple.predicate.uri,
                    'target': {
                        'uri': triple.object.uri,
                        'type': triple.object.resource_type,
                        'name': triple.object.name,
                        'id': str(triple.object.id)
                    },
                    'relationship_type': self._get_relationship_type(triple.predicate.uri)
                }
                
                # Add to relationships only for depth 0 (direct relationships)
                if current_depth == 0:
                    relationships['outgoing'].append(relationship_data)
                
                # Add edge to graph
                graph['edges'].append({
                    'source': str(resource.id),
                    'target': str(triple.object.id),
                    'predicate': triple.predicate.uri,
                    'predicate_name': triple.predicate.name or triple.predicate.uri,
                    'type': 'outgoing'
                })
                
                # Recursively traverse
                if current_depth < max_depth:
                    self._traverse_relationships(triple.object, max_depth, current_depth + 1, 
                                               organization, visited, graph, relationships)
        
        # Find incoming relationships (where this resource is the object)
        incoming_query = Triple.objects.filter(object=resource).select_related('predicate', 'subject')
        if organization:
            incoming_query = incoming_query.filter(subject__organization__code=organization)
        
        for triple in incoming_query:
            if triple.subject.uri not in visited:
                relationship_data = {
                    'predicate': triple.predicate.uri,
                    'predicate_name': triple.predicate.name or triple.predicate.uri,
                    'source': {
                        'uri': triple.subject.uri,
                        'type': triple.subject.resource_type,
                        'name': triple.subject.name,
                        'id': str(triple.subject.id)
                    },
                    'relationship_type': self._get_relationship_type(triple.predicate.uri)
                }
                
                # Add to relationships only for depth 0 (direct relationships)
                if current_depth == 0:
                    relationships['incoming'].append(relationship_data)
                
                # Add edge to graph
                graph['edges'].append({
                    'source': str(triple.subject.id),
                    'target': str(resource.id),
                    'predicate': triple.predicate.uri,
                    'predicate_name': triple.predicate.name or triple.predicate.uri,
                    'type': 'incoming'
                })
                
                # Recursively traverse
                if current_depth < max_depth:
                    self._traverse_relationships(triple.subject, max_depth, current_depth + 1, 
                                               organization, visited, graph, relationships)
    
    def find_resources_by_relationship(self, resource_uri: str, relationship_type: str, organization: str = None) -> List[Resource]:
        """
        Find all resources connected to a given resource by a specific relationship type.
        
        Args:
            resource_uri: URI of the starting resource
            relationship_type: Type of relationship to filter by
            organization: Organization code to filter results
            
        Returns:
            List of related resources
        """
        cache_key = f"resource_related:{resource_uri}:{relationship_type}:{organization}"
        cached_result = cache.get(cache_key)
        if cached_result:
            return cached_result
        
        try:
            # Get the starting resource
            resource_query = Resource.objects.filter(uri=resource_uri)
            if organization:
                resource_query = resource_query.filter(organization__code=organization)
            
            resource = resource_query.first()
            if not resource:
                raise Resource.DoesNotExist(f"Resource with URI {resource_uri} not found")
            
            # Find resources connected via the specified relationship type
            related_resources = []
            
            # Check outgoing relationships
            outgoing_triples = Triple.objects.filter(
                subject=resource,
                predicate__uri__icontains=relationship_type
            ).select_related('object')
            
            if organization:
                outgoing_triples = outgoing_triples.filter(object__organization__code=organization)
            
            for triple in outgoing_triples:
                related_resources.append(triple.object)
            
            # Check incoming relationships
            incoming_triples = Triple.objects.filter(
                object=resource,
                predicate__uri__icontains=relationship_type
            ).select_related('subject')
            
            if organization:
                incoming_triples = incoming_triples.filter(subject__organization__code=organization)
            
            for triple in incoming_triples:
                related_resources.append(triple.subject)
            
            # Remove duplicates
            unique_resources = list({r.uri: r for r in related_resources}.values())
            
            cache.set(cache_key, unique_resources, self.cache_timeout)
            return unique_resources
            
        except Exception as e:
            logger.error(f"Error finding resources by relationship {relationship_type} for {resource_uri}: {str(e)}")
            raise
    
    def get_relationship_graph(self, resource_uri: str, depth: int = 1, organization: str = None) -> Dict[str, Any]:
        """
        Get a graph representation of relationships for visualization.
        
        Args:
            resource_uri: URI of the starting resource
            depth: Depth of relationship traversal
            organization: Organization code to filter results
            
        Returns:
            Graph data structure with nodes and edges
        """
        result = self.get_related_resources(resource_uri, depth, organization)
        return result.get('graph', {'nodes': [], 'edges': [], 'depth': depth})
    
    def get_bidirectional_relationships(self, resource_uri: str, organization: str = None) -> Dict[str, List[Resource]]:
        """
        Get both incoming and outgoing relationships for a resource.
        
        Args:
            resource_uri: URI of the resource
            organization: Organization code to filter results
            
        Returns:
            Dictionary with 'outgoing' and 'incoming' lists of resources
        """
        cache_key = f"resource_bidirectional:{resource_uri}:{organization}"
        cached_result = cache.get(cache_key)
        if cached_result:
            return cached_result
        
        try:
            # Get the starting resource
            resource_query = Resource.objects.filter(uri=resource_uri)
            if organization:
                resource_query = resource_query.filter(organization__code=organization)
            
            resource = resource_query.first()
            if not resource:
                raise Resource.DoesNotExist(f"Resource with URI {resource_uri} not found")
            
            result = {'outgoing': [], 'incoming': []}
            
            # Get outgoing relationships
            outgoing_triples = Triple.objects.filter(subject=resource).select_related('object')
            if organization:
                outgoing_triples = outgoing_triples.filter(object__organization__code=organization)
            
            for triple in outgoing_triples:
                result['outgoing'].append(triple.object)
            
            # Get incoming relationships
            incoming_triples = Triple.objects.filter(object=resource).select_related('subject')
            if organization:
                incoming_triples = incoming_triples.filter(subject__organization__code=organization)
            
            for triple in incoming_triples:
                result['incoming'].append(triple.subject)
            
            cache.set(cache_key, result, self.cache_timeout)
            return result
            
        except Exception as e:
            logger.error(f"Error getting bidirectional relationships for {resource_uri}: {str(e)}")
            raise
    
    def get_relationship_chain(self, from_uri: str, to_uri: str, organization: str = None) -> List[Dict[str, Any]]:
        """
        Find the shortest path between two resources.
        
        Args:
            from_uri: Starting resource URI
            to_uri: Target resource URI
            organization: Organization code to filter results
            
        Returns:
            List of relationship chain steps
        """
        cache_key = f"resource_chain:{from_uri}:{to_uri}:{organization}"
        cached_result = cache.get(cache_key)
        if cached_result:
            return cached_result
        
        try:
            # Get both resources
            from_resource = Resource.objects.filter(uri=from_uri).first()
            to_resource = Resource.objects.filter(uri=to_uri).first()
            
            if not from_resource or not to_resource:
                return []
            
            # Simple BFS to find shortest path
            queue = [(from_resource, [])]
            visited = set()
            
            while queue:
                current_resource, path = queue.pop(0)
                
                if current_resource.uri in visited:
                    continue
                    
                visited.add(current_resource.uri)
                
                # Check if we reached the target
                if current_resource.uri == to_uri:
                    cache.set(cache_key, path, self.cache_timeout)
                    return path
                
                # Explore neighbors
                for triple in Triple.objects.filter(subject=current_resource).select_related('predicate', 'object'):
                    if organization and (not triple.object.organization or triple.object.organization.code != organization):
                        continue
                    
                    if triple.object.uri not in visited:
                        new_path = path + [{
                            'source': current_resource.uri,
                            'source_name': current_resource.name,
                            'predicate': triple.predicate.uri,
                            'predicate_name': triple.predicate.name or triple.predicate.uri,
                            'target': triple.object.uri,
                            'target_name': triple.object.name
                        }]
                        queue.append((triple.object, new_path))
            
            # No path found
            cache.set(cache_key, [], self.cache_timeout)
            return []
            
        except Exception as e:
            logger.error(f"Error getting relationship chain from {from_uri} to {to_uri}: {str(e)}")
            raise
    
    def get_paginated_related_resources(self, resource_uri: str, page: int = 1, per_page: int = 20, organization: str = None) -> Dict[str, Any]:
        """
        Get paginated related resources for HTMX views.
        
        Args:
            resource_uri: URI of the starting resource
            page: Page number
            per_page: Number of resources per page
            organization: Organization code to filter results
            
        Returns:
            Dictionary containing paginated resources and pagination info
        """
        from django.core.paginator import Paginator
        
        try:
            # Get bidirectional relationships
            relationships = self.get_bidirectional_relationships(resource_uri, organization)
            all_resources = relationships.get('outgoing', []) + relationships.get('incoming', [])
            
            # Remove duplicates while preserving order
            unique_resources = []
            seen_uris = set()
            for resource in all_resources:
                if resource.uri not in seen_uris:
                    unique_resources.append(resource)
                    seen_uris.add(resource.uri)
            
            # Paginate
            paginator = Paginator(unique_resources, per_page)
            page_obj = paginator.get_page(page)
            
            return {
                'resources': page_obj,
                'paginator': paginator,
                'page_number': page,
                'per_page': per_page,
                'total_count': paginator.count,
                'has_previous': page_obj.has_previous(),
                'has_next': page_obj.has_next(),
                'previous_page_number': page_obj.previous_page_number() if page_obj.has_previous() else None,
                'next_page_number': page_obj.next_page_number() if page_obj.has_next() else None,
            }
            
        except Exception as e:
            logger.error(f"Error getting paginated related resources for {resource_uri}: {str(e)}")
            raise

    def get_mapping_relationships(self, mapping_id: str) -> Dict[str, Any]:
        """
        Get all relationships defined in a mapping configuration.
        
        Args:
            mapping_id: ID of the mapping
            
        Returns:
            Dictionary containing mapping relationship configuration
        """
        cache_key = f"mapping_relationships:{mapping_id}"
        cached_result = cache.get(cache_key)
        if cached_result:
            return cached_result
        
        try:
            mapping = Mapping.objects.get(id=mapping_id)
            
            result = {
                'mapping_id': mapping_id,
                'mapping_name': mapping.name,
                'organization': mapping.organization_id,
                'fk_relationships': mapping.mapping_config.get('fk_relationships', {}),
                'workspace_datasets': mapping.mapping_config.get('workspace_datasets', []),
                'created_at': mapping.created_at.isoformat() if mapping.created_at else None,
                'validation_status': mapping.validation_status
            }
            
            cache.set(cache_key, result, self.cache_timeout)
            return result
            
        except Mapping.DoesNotExist:
            logger.error(f"Mapping with ID {mapping_id} not found")
            raise
        except Exception as e:
            logger.error(f"Error getting mapping relationships for {mapping_id}: {str(e)}")
            raise
    
    def get_organization_relationship_types(self, organization: str) -> List[str]:
        """
        Get all relationship types (predicates) used by an organization.
        
        Args:
            organization: Organization code
            
        Returns:
            List of relationship type URIs
        """
        cache_key = f"org_relationship_types:{organization}"
        cached_result = cache.get(cache_key)
        if cached_result:
            return cached_result
        
        try:
            # Get all predicates used in triples for this organization
            predicates = Triple.objects.filter(
                Q(subject__organization__code=organization) | Q(object__organization__code=organization)
            ).values_list('predicate__uri', flat=True).distinct()
            
            relationship_types = list(predicates)
            
            cache.set(cache_key, relationship_types, self.cache_timeout)
            return relationship_types
            
        except Exception as e:
            logger.error(f"Error getting relationship types for organization {organization}: {str(e)}")
            raise
    
    def _get_relationship_type(self, predicate_uri: str) -> str:
        """
        Extract a readable relationship type from a predicate URI.
        
        Args:
            predicate_uri: URI of the predicate
            
        Returns:
            Readable relationship type string
        """
        if not predicate_uri:
            return "unknown"
        
        # Extract the last part of the URI
        if '#' in predicate_uri:
            return predicate_uri.split('#')[-1]
        elif '/' in predicate_uri:
            return predicate_uri.split('/')[-1]
        else:
            return predicate_uri
    
    def invalidate_cache(self, resource_uri: str, organization: str = None):
        """
        Invalidate cache entries related to a resource.
        
        Args:
            resource_uri: URI of the resource
            organization: Organization code
        """
        # This would need to be more sophisticated in a real implementation
        # For now, we'll just clear cache entries that might be affected
        cache_patterns = [
            f"resource_relationships:{resource_uri}:*",
            f"resource_related:{resource_uri}:*",
            f"resource_bidirectional:{resource_uri}:*",
            f"resource_chain:{resource_uri}:*",
            f"resource_chain:*:{resource_uri}:*"
        ]
        
        # In a real implementation, you'd want to use a more sophisticated cache invalidation strategy
        # For now, we'll just clear the specific keys we can construct
        if organization:
            for depth in range(1, 4):  # Clear common depths
                cache.delete(f"resource_relationships:{resource_uri}:{depth}:{organization}")
            cache.delete(f"resource_bidirectional:{resource_uri}:{organization}")
            cache.delete(f"org_relationship_types:{organization}")