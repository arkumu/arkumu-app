from django.shortcuts import get_object_or_404, render
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import DetailView
from django.views import View
from django.http import Http404, HttpResponse
from django.conf import settings
from django.template.loader import render_to_string
from django.middleware.csrf import get_token
from django.db.models import Q
import graphviz
import logging
import json
from datetime import datetime

from arkumu.metadata.models.resource import Resource, ResourceType, PublicAccessLevel
from arkumu.metadata.models.triples import Triple

logger = logging.getLogger(__name__)


class ResourceGraphView(LoginRequiredMixin, DetailView):
    """Main resource graph visualization page"""
    model = Resource
    template_name = 'metadata/resource_graph.html'
    context_object_name = 'resource'
    pk_url_kwarg = 'resource_id'
    
    def get_queryset(self):
        """Get resources with appropriate access control."""
        queryset = Resource.objects.all().select_related('organization')
        
        # Debug mode - show all resources in development
        if settings.DEBUG and self.request.GET.get('debug') == 'true':
            return queryset
        
        # Apply access control based on user permissions
        if not self.request.user.is_authenticated:
            # Anonymous users see only public approved resources
            queryset = queryset.filter(
                public_access_level=PublicAccessLevel.PUBLIC,
                is_public_approved=True
            )
        elif not self.request.user.has_perm('metadata.view_all_resources'):
            # Authenticated users see public + restricted resources
            queryset = queryset.filter(
                public_access_level__in=[
                    PublicAccessLevel.PUBLIC, 
                    PublicAccessLevel.RESTRICTED
                ]
            )
        # Staff/admin users see all resources (no additional filtering)
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        resource = self.object
        
        # Get level parameter from URL or default to 1
        levels = int(self.request.GET.get('levels', 1))
        levels = max(1, min(levels, 5))  # Clamp between 1 and 5
        
        try:
            # Generate the graph with specified levels
            graph_service = ResourceGraphService()
            graph_svg = graph_service.generate_initial_graph(
                resource, 
                levels=levels, 
                max_nodes=50
            )
            
            context['graph_svg'] = graph_svg
            context['graph_stats'] = graph_service.get_graph_stats()
            context['current_levels'] = levels
            context['can_expand'] = levels < 5 and context['graph_stats']['nodes_added'] > 1
            
        except Exception as e:
            logger.error(f"Failed to generate graph for resource {resource.id}: {e}")
            context['graph_svg'] = None
            context['graph_error'] = str(e)
            context['current_levels'] = levels
            context['can_expand'] = False
        
        return context


class ResourceGraphExpandView(LoginRequiredMixin, View):
    """HTMX endpoint for expanding graph levels"""
    
    def get_queryset(self):
        """Same access control as main view"""
        queryset = Resource.objects.all().select_related('organization')
        
        if settings.DEBUG and self.request.GET.get('debug') == 'true':
            return queryset
        
        if not self.request.user.is_authenticated:
            queryset = queryset.filter(
                public_access_level=PublicAccessLevel.PUBLIC,
                is_public_approved=True
            )
        elif not self.request.user.has_perm('metadata.view_all_resources'):
            queryset = queryset.filter(
                public_access_level__in=[
                    PublicAccessLevel.PUBLIC, 
                    PublicAccessLevel.RESTRICTED
                ]
            )
        
        return queryset
    
    def post(self, request, resource_id):
        """Handle level expansion request"""
        try:
            # Get resource with access control
            resource = get_object_or_404(self.get_queryset(), id=resource_id)
            
            # Get requested levels
            current_levels = int(request.POST.get('current_levels', 1))
            new_levels = current_levels + 1
            new_levels = max(1, min(new_levels, 5))  # Clamp between 1 and 5
            
            # Generate expanded graph
            graph_service = ResourceGraphService()
            graph_svg = graph_service.generate_initial_graph(
                resource, 
                levels=new_levels, 
                max_nodes=75  # Allow more nodes for expanded view
            )
            
            # Render updated graph container
            graph_stats = graph_service.get_graph_stats()
            can_expand = new_levels < 5 and graph_stats['nodes_added'] > 1
            
            graph_content = render_to_string(
                'metadata/partials/resource_graph_content.html',
                {
                    'graph_svg': graph_svg,
                    'graph_stats': graph_stats,
                    'current_levels': new_levels,
                    'can_expand': can_expand,
                    'resource': resource,
                },
                request=request
            )
            
            # Build OOB response (similar to CSV mapping pattern)
            response_html = self._build_oob_response("", {
                'graph-content': graph_content
            })
            
            return HttpResponse(response_html)
            
        except Exception as e:
            logger.error(f"Failed to expand graph for resource {resource_id}: {e}")
            error_html = f'<div class="alert alert-error">Failed to expand graph: {str(e)}</div>'
            return HttpResponse(error_html)
    
    def _build_oob_response(self, main_html, oob_updates):
        """Build response with out-of-band updates (similar to CSV mapping)"""
        if not oob_updates:
            return main_html
        
        oob_html = ""
        for target_id, content in oob_updates.items():
            oob_html += f'<div id="{target_id}" hx-swap-oob="innerHTML">{content}</div>'
        
        return f'{main_html}{oob_html}'


class ResourceGraphService:
    """Service for generating resource relationship graphs"""
    
    # Resource type styling (matching data explorer badges)
    NODE_COLORS = {
        ResourceType.IRI: {
            'fillcolor': '#dbeafe', 
            'color': '#3b82f6', 
            'fontcolor': '#1e40af'
        },
        ResourceType.CLASS: {
            'fillcolor': '#f3e8ff', 
            'color': '#a855f7', 
            'fontcolor': '#7c3aed'
        },
        ResourceType.PROPERTY: {
            'fillcolor': '#ecfdf5', 
            'color': '#10b981', 
            'fontcolor': '#065f46'
        },
        ResourceType.LITERAL: {
            'fillcolor': '#f9fafb', 
            'color': '#6b7280', 
            'fontcolor': '#374151'
        },
    }
    
    def __init__(self):
        self.stats = {
            'nodes_added': 0,
            'edges_added': 0,
            'max_depth_reached': 0
        }
    
    def generate_initial_graph(self, central_resource, levels=1, max_nodes=25):
        """Generate initial resource graph showing only specified levels"""
        
        # Get organization for filtering
        organization_code = central_resource.organization.code if central_resource.organization else None
        
        # Create GraphViz graph with neato layout
        dot = graphviz.Digraph(
            name='ResourceGraph',
            comment=f'Resource relationship graph for {central_resource.id}',
            engine='neato',  # Force/spring layout
            format='svg',
            graph_attr={
                'overlap': 'false',
                'splines': 'curved',
                'sep': '1.0',
                'bgcolor': 'transparent',
                'fontname': 'Arial',
                'size': '12,8',
                'ratio': 'fill',
                'pad': '0.5',
            },
            node_attr={
                'fontname': 'Arial',
                'fontsize': '10',
                'style': 'filled,rounded',
                'shape': 'box',
                'margin': '0.2,0.1',
                'width': '1.2',
                'height': '0.6',
                'fixedsize': 'true',
            },
            edge_attr={
                'fontname': 'Arial',
                'fontsize': '8',
                'arrowsize': '0.7',
                'len': '1.8',
            }
        )
        
        # Get relationship data with level-based approach
        graph_data = self._get_level_based_relationship_data(
            central_resource, 
            levels=levels, 
            max_nodes=max_nodes,
            organization_code=organization_code
        )
        
        # Build the graph
        self._add_nodes_to_graph(dot, graph_data, central_resource)
        self._add_edges_to_graph(dot, graph_data)
        
        # Generate SVG
        try:
            svg_content = dot.pipe(format='svg').decode('utf-8')
            
            # Clean up SVG (remove XML declaration)
            if svg_content.startswith('<?xml'):
                svg_content = svg_content.split('\n', 1)[1]
            
            # Add custom CSS styling
            styled_svg = self._add_svg_styling(svg_content)
            
            return styled_svg
            
        except Exception as e:
            logger.error(f"GraphViz rendering failed: {e}")
            return None
    
    def _get_relationship_data(self, central_resource, max_depth=2, max_nodes=50):
        """Query relationship data showing only resources with direct connections"""
        
        nodes = {}
        edges = []
        processed_resources = set()
        current_depth = 0
        
        # Start with central resource
        nodes[central_resource.id] = {
            'resource': central_resource,
            'depth': 0,
            'is_central': True
        }
        processed_resources.add(central_resource.id)
        
        # Queue for breadth-first traversal
        queue = [(central_resource, 0)]
        
        while queue and len(nodes) < max_nodes and current_depth < max_depth:
            resource, depth = queue.pop(0)
            current_depth = max(current_depth, depth)
            
            if depth >= max_depth:
                continue
            
            # Get relationships where this resource is subject
            subject_query = Triple.objects.filter(subject=resource).select_related('predicate', 'object')
            if organization_code:
                # Include organization resources AND external ontology links (owl:sameAs with no organization)
                subject_query = subject_query.filter(
                    Q(object__organization__code=organization_code) |
                    Q(predicate__uri='http://www.w3.org/2002/07/owl#sameAs', object__organization__isnull=True)
                )
            subject_triples = subject_query[:50]  # Increased limit to include owl:sameAs relationships
            
            for triple in subject_triples:
                if len(nodes) >= max_nodes:
                    break
                
                # Only add object resources (skip predicates as intermediate nodes)
                if triple.object and triple.object.id not in nodes:
                    nodes[triple.object.id] = {
                        'resource': triple.object,
                        'depth': depth + 1,
                        'is_central': False
                    }
                    
                    # Queue for further exploration if not at max depth
                    if depth + 1 < max_depth and triple.object.id not in processed_resources:
                        queue.append((triple.object, depth + 1))
                        processed_resources.add(triple.object.id)
                
                # Create direct edge from subject to object (using predicate as label)
                if triple.object:
                    edges.append({
                        'subject_id': resource.id,
                        'object_id': triple.object.id,
                        'predicate': triple.predicate,
                        'triple': triple,
                        'direction': 'outgoing'
                    })
            
            # Get relationships where this resource is object
            object_query = Triple.objects.filter(object=resource).select_related('subject', 'predicate')
            if organization_code:
                # Include organization resources AND external ontology links (owl:sameAs with no organization)
                object_query = object_query.filter(
                    Q(subject__organization__code=organization_code) |
                    Q(predicate__uri='http://www.w3.org/2002/07/owl#sameAs', subject__organization__isnull=True)
                )
            object_triples = object_query[:50]  # Increased limit to include owl:sameAs relationships
            
            for triple in object_triples:
                if len(nodes) >= max_nodes:
                    break
                    
                # Only add subject resources
                if triple.subject.id not in nodes:
                    nodes[triple.subject.id] = {
                        'resource': triple.subject,
                        'depth': depth + 1,
                        'is_central': False
                    }
                    
                    # Queue for further exploration
                    if depth + 1 < max_depth and triple.subject.id not in processed_resources:
                        queue.append((triple.subject, depth + 1))
                        processed_resources.add(triple.subject.id)
                
                # Create direct edge from subject to object (avoid duplicates)
                if not any(e['subject_id'] == triple.subject.id and 
                          e['object_id'] == resource.id for e in edges):
                    edges.append({
                        'subject_id': triple.subject.id,
                        'object_id': resource.id,
                        'predicate': triple.predicate,
                        'triple': triple,
                        'direction': 'incoming'
                    })
            
            # IMPORTANT: Get relationships where this resource is used as a PREDICATE
            # This is crucial for PROPERTY resources which are typically predicates
            if resource.resource_type == ResourceType.PROPERTY:
                predicate_query = Triple.objects.filter(predicate=resource).select_related('subject', 'object')
                if organization_code:
                    predicate_query = predicate_query.filter(
                        Q(subject__organization__code=organization_code) |
                        Q(object__organization__code=organization_code)
                    )
                predicate_triples = predicate_query[:50]
                
                for triple in predicate_triples:
                    if len(nodes) >= max_nodes:
                        break
                    
                    # Add both subject and object nodes
                    if triple.subject and triple.subject.id not in nodes:
                        nodes[triple.subject.id] = {
                            'resource': triple.subject,
                            'depth': depth + 1,
                            'is_central': False
                        }
                        if depth + 1 < max_depth and triple.subject.id not in processed_resources:
                            queue.append((triple.subject, depth + 1))
                            processed_resources.add(triple.subject.id)
                    
                    if triple.object and triple.object.id not in nodes:
                        nodes[triple.object.id] = {
                            'resource': triple.object,
                            'depth': depth + 1,
                            'is_central': False
                        }
                        if depth + 1 < max_depth and triple.object.id not in processed_resources:
                            queue.append((triple.object, depth + 1))
                            processed_resources.add(triple.object.id)
                    
                    # Create edge showing this property connects subject to object
                    if triple.subject and triple.object:
                        edges.append({
                            'subject_id': triple.subject.id,
                            'object_id': triple.object.id,
                            'predicate': resource,  # The property itself is the predicate
                            'triple': triple,
                            'direction': 'property_link'
                        })
        
        # Remove any nodes that don't have connections
        connected_node_ids = set()
        for edge in edges:
            connected_node_ids.add(edge['subject_id'])
            connected_node_ids.add(edge['object_id'])
        
        # Always keep the central resource even if isolated
        connected_node_ids.add(central_resource.id)
        
        # Filter nodes to only keep connected ones
        filtered_nodes = {
            node_id: node_data 
            for node_id, node_data in nodes.items() 
            if node_id in connected_node_ids
        }
        
        self.stats['nodes_added'] = len(filtered_nodes)
        self.stats['edges_added'] = len(edges)
        self.stats['max_depth_reached'] = current_depth
        
        return {'nodes': filtered_nodes, 'edges': edges}
    
    def _get_level_based_relationship_data(self, central_resource, levels=1, max_nodes=25, organization_code=None):
        """Get relationship data with clear level-based structure"""
        
        nodes = {}
        edges = []
        
        # Level 0: Always start with the central resource
        nodes[central_resource.id] = {
            'resource': central_resource,
            'level': 0,
            'is_central': True
        }
        
        current_level_resources = [central_resource]
        
        # Build graph level by level
        for level in range(1, levels + 1):
            next_level_resources = []
            
            for current_resource in current_level_resources:
                if len(nodes) >= max_nodes:
                    break
                
                # Get direct connections (both outgoing and incoming)
                connections = self._get_direct_connections(current_resource, max_per_resource=100, organization_code=organization_code)
                
                logger.info(f"Level {level}: Resource {current_resource.id} has {len(connections)} connections")
                
                for connection in connections:
                    related_resource = connection['related_resource']
                    
                    # Skip if already processed or would exceed node limit
                    if related_resource.id in nodes or len(nodes) >= max_nodes:
                        continue
                    
                    # Add the related resource at this level
                    nodes[related_resource.id] = {
                        'resource': related_resource,
                        'level': level,
                        'is_central': False
                    }
                    
                    # Add to next level processing queue
                    next_level_resources.append(related_resource)
                    
                    # Create the edge
                    edges.append({
                        'subject_id': connection['subject_id'],
                        'object_id': connection['object_id'],
                        'predicate': connection['predicate'],
                        'triple': connection['triple'],
                        'direction': connection['direction'],
                        'level': level
                    })
            
            current_level_resources = next_level_resources
            
            # Stop if no more resources to explore
            if not current_level_resources:
                break
        
        self.stats['nodes_added'] = len(nodes)
        self.stats['edges_added'] = len(edges)
        self.stats['max_depth_reached'] = levels
        
        logger.info(f"Graph built with {len(nodes)} nodes and {len(edges)} edges")
        
        return {'nodes': nodes, 'edges': edges}
    
    def _get_direct_connections(self, resource, max_per_resource=8, organization_code=None):
        """Get direct connections for a resource"""
        connections = []
        
        # Outgoing relationships (where resource is subject)
        outgoing_query = Triple.objects.filter(subject=resource).select_related('predicate', 'object')
        if organization_code:
            # Include organization resources AND external ontology links (owl:sameAs with no organization)
            outgoing_query = outgoing_query.filter(
                Q(object__organization__code=organization_code) |
                Q(predicate__uri='http://www.w3.org/2002/07/owl#sameAs', object__organization__isnull=True)
            )
        outgoing_triples = outgoing_query[:max_per_resource//2]
        
        for triple in outgoing_triples:
            if triple.object:  # Skip triples without objects
                connections.append({
                    'related_resource': triple.object,
                    'subject_id': resource.id,
                    'object_id': triple.object.id,
                    'predicate': triple.predicate,
                    'triple': triple,
                    'direction': 'outgoing'
                })
        
        # Incoming relationships (where resource is object)
        incoming_query = Triple.objects.filter(object=resource).select_related('subject', 'predicate')
        if organization_code:
            # Include organization resources AND external ontology links (owl:sameAs with no organization)
            incoming_query = incoming_query.filter(
                Q(subject__organization__code=organization_code) |
                Q(predicate__uri='http://www.w3.org/2002/07/owl#sameAs', subject__organization__isnull=True)
            )
        incoming_triples = incoming_query[:max_per_resource//2]
        
        for triple in incoming_triples:
            connections.append({
                'related_resource': triple.subject,
                'subject_id': triple.subject.id,
                'object_id': resource.id,
                'predicate': triple.predicate,
                'triple': triple,
                'direction': 'incoming'
            })
        
        # IMPORTANT: For PROPERTY resources, also get triples where this resource IS the predicate
        # This shows all the connections this property makes between resources
        if resource.resource_type == ResourceType.PROPERTY:
            predicate_query = Triple.objects.filter(predicate=resource).select_related('subject', 'object')
            if organization_code:
                predicate_query = predicate_query.filter(
                    Q(subject__organization__code=organization_code) |
                    Q(object__organization__code=organization_code)
                )
            predicate_triples = predicate_query[:max_per_resource]
            
            logger.info(f"Property {resource.id} used as predicate in {predicate_triples.count()} triples")
            
            for triple in predicate_triples:
                # For properties as predicates, we want to show both the subjects and objects
                # that are connected through this property
                if triple.subject and triple.object:
                    # Add the subject as a related resource
                    connections.append({
                        'related_resource': triple.subject,
                        'subject_id': triple.subject.id,
                        'object_id': triple.object.id,
                        'predicate': resource,  # The property itself is the predicate
                        'triple': triple,
                        'direction': 'property_link'
                    })
                    # Add the object as a related resource
                    connections.append({
                        'related_resource': triple.object,
                        'subject_id': triple.subject.id,
                        'object_id': triple.object.id,
                        'predicate': resource,  # The property itself is the predicate
                        'triple': triple,
                        'direction': 'property_link'
                    })
        
        return connections
    
    def _add_nodes_to_graph(self, dot, graph_data, central_resource):
        """Add nodes to GraphViz graph with appropriate styling"""
        
        for node_id, node_data in graph_data['nodes'].items():
            resource = node_data['resource']
            is_central = node_data['is_central']
            
            # Get styling based on resource type
            style_attrs = self.NODE_COLORS.get(
                resource.resource_type, 
                self.NODE_COLORS[ResourceType.IRI]
            ).copy()
            
            # Special styling for central resource
            if is_central:
                style_attrs['penwidth'] = '3'
                style_attrs['fontsize'] = '12'
                style_attrs['fontweight'] = 'bold'
            
            # Create node label and tooltip
            label = self._create_node_label(resource)
            full_tooltip = self._create_node_tooltip(resource)
            
            # Add tooltip attribute for GraphViz
            style_attrs['tooltip'] = full_tooltip
            
            # Add node to graph
            dot.node(
                str(node_id),
                label=label,
                **style_attrs
            )
    
    def _add_edges_to_graph(self, dot, graph_data):
        """Add edges to GraphViz graph"""
        
        for edge in graph_data['edges']:
            # Create edge label and tooltip
            predicate_label = self._create_edge_label(edge['predicate'])
            full_edge_tooltip = self._create_edge_tooltip(edge['predicate'])
            
            # Style edges based on direction
            edge_color = '#10b981' if edge['direction'] == 'outgoing' else '#3b82f6'
            
            dot.edge(
                str(edge['subject_id']),
                str(edge['object_id']),
                label=predicate_label,
                tooltip=full_edge_tooltip,
                labeltooltip=full_edge_tooltip,  # Add tooltip to the label text as well
                color=edge_color,
                fontcolor='#4b5563',
                penwidth='1.5'
            )
    
    def _create_node_label(self, resource):
        """Create display label for resource node (optimized for smaller nodes)"""
        
        if resource.resource_type == ResourceType.LITERAL:
            # For literals, show truncated value
            value = resource.value or ""
            if len(value) > 20:
                value = value[:17] + "..."
            return f'"{value}"'
        
        elif resource.name:
            # Use name if available
            name = resource.name
            if len(name) > 15:
                name = name[:12] + "..."
            return name
        
        elif resource.uri:
            # Extract meaningful part from URI
            uri_parts = resource.uri.rstrip('/').split('/')
            if len(uri_parts) > 1:
                label = uri_parts[-1]
                if len(label) > 15:
                    label = label[:12] + "..."
                return label
            return resource.uri[:15] + "..." if len(resource.uri) > 15 else resource.uri
        
        else:
            # Fallback to resource type + ID (shortened)
            return f"{resource.get_resource_type_display()[:3]}\n#{str(resource.id)[:6]}"
    
    def _create_edge_label(self, predicate):
        """Create display label for edge (predicate) - optimized for smaller graph"""
        
        if predicate.name:
            label = predicate.name
        elif predicate.uri:
            # Extract meaningful part from URI
            uri_parts = predicate.uri.rstrip('/').split('/')
            if len(uri_parts) > 1:
                label = uri_parts[-1]
            else:
                label = predicate.uri
        else:
            label = "relates"
        
        # Truncate long labels more aggressively for smaller nodes
        if len(label) > 10:
            label = label[:8] + "..."
        
        return label
    
    def _create_node_tooltip(self, resource):
        """Create comprehensive tooltip for resource node"""
        tooltip_parts = []
        
        # Resource type
        tooltip_parts.append(f"Type: {resource.get_resource_type_display()}")
        
        # Full name if available
        if resource.name:
            tooltip_parts.append(f"Name: {resource.name}")
        
        # Full URI if available
        if resource.uri:
            tooltip_parts.append(f"URI: {resource.uri}")
        
        # Full value for literals
        if resource.resource_type == ResourceType.LITERAL and resource.value:
            value = resource.value
            if len(value) > 100:  # Only truncate extremely long values in tooltip
                value = value[:97] + "..."
            tooltip_parts.append(f"Value: {value}")
        
        # Organization
        if resource.organization:
            tooltip_parts.append(f"Organization: {resource.organization.name}")
        
        return "\\n".join(tooltip_parts)
    
    def _create_edge_tooltip(self, predicate):
        """Create comprehensive tooltip for edge (predicate)"""
        # GraphViz edge tooltips can be tricky, so let's keep it simple and informative
        tooltip_parts = []
        
        # Start with the most important info - full name or URI
        if predicate.name:
            tooltip_parts.append(f"Relationship: {predicate.name}")
        elif predicate.uri:
            # Extract readable part from URI
            uri_parts = predicate.uri.rstrip('/').split('/')
            readable_name = uri_parts[-1] if len(uri_parts) > 1 else predicate.uri
            tooltip_parts.append(f"Relationship: {readable_name}")
        else:
            tooltip_parts.append("Relationship: (unnamed)")
        
        # Add full URI if different from name
        if predicate.uri and predicate.uri != predicate.name:
            tooltip_parts.append(f"Full URI: {predicate.uri}")
        
        # Add organization if available
        if predicate.organization:
            tooltip_parts.append(f"From: {predicate.organization.name}")
        
        # Use space-separated format instead of newlines for better compatibility
        return " | ".join(tooltip_parts)
    
    def _add_svg_styling(self, svg_content):
        """Add custom CSS styling to SVG"""
        
        styled_svg = f"""
        <style>
            .resource-graph {{
                max-width: 100%;
                height: auto;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                background: white;
            }}
            
            .resource-graph svg {{
                width: 100%;
                height: auto;
                min-height: 400px;
            }}
            
            .resource-graph text {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            }}
            
            .resource-graph polygon, .resource-graph ellipse, .resource-graph path {{
                cursor: pointer;
                transition: opacity 0.2s ease;
            }}
            
            .resource-graph polygon:hover, .resource-graph ellipse:hover {{
                opacity: 0.8;
            }}
            
            /* Ensure edge tooltips work */
            .resource-graph path {{
                cursor: pointer;
            }}
            
            .resource-graph path:hover {{
                stroke-width: 2.5px;
                opacity: 0.8;
            }}
        </style>
        <div class="resource-graph">
            {svg_content}
        </div>
        """
        
        return styled_svg
    
    def get_graph_stats(self):
        """Get statistics about the generated graph"""
        return self.stats