from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from django.http import JsonResponse, HttpResponse
import logging
import re
import json
from arkumu.users.mixins import general_login_required

from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple

logger = logging.getLogger(__name__)

def _build_search_filter(field_name, search_term, search_mode='contains'):
    """
    Build a Q object for searching with different modes.
    
    Args:
        field_name: The field to search (e.g., 'uri', 'name', 'value')
        search_term: The term to search for
        search_mode: 'contains', 'startswith', 'exact', or 'regex'
    
    Returns:
        Q object for the search filter
    """
    if not search_term:
        return Q()
    
    if search_mode == 'contains':
        return Q(**{f"{field_name}__icontains": search_term})
    elif search_mode == 'startswith':
        return Q(**{f"{field_name}__istartswith": search_term})
    elif search_mode == 'exact':
        return Q(**{f"{field_name}__iexact": search_term})
    elif search_mode == 'regex':
        try:
            # Validate regex before using it
            re.compile(search_term)
            return Q(**{f"{field_name}__iregex": search_term})
        except re.error as e:
            logger.warning(f"Invalid regex pattern '{search_term}': {e}")
            # Fall back to contains search if regex is invalid
            return Q(**{f"{field_name}__icontains": search_term})
    else:
        # Default to contains if unknown mode
        return Q(**{f"{field_name}__icontains": search_term})

def _build_multi_field_search(fields, search_term, search_mode='contains'):
    """
    Build a Q object that searches across multiple fields with OR logic.
    
    Args:
        fields: List of field names to search
        search_term: The term to search for
        search_mode: 'contains', 'startswith', 'exact', or 'regex'
    
    Returns:
        Q object combining all field searches with OR
    """
    if not search_term:
        return Q()
    
    q_objects = [_build_search_filter(field, search_term, search_mode) for field in fields]
    # Combine with OR
    combined_q = q_objects[0] if q_objects else Q()
    for q_obj in q_objects[1:]:
        combined_q |= q_obj
    
    return combined_q


@general_login_required
def data_explorer(request):
    """Unified data explorer for browsing resources and triples."""
    view_mode = request.GET.get('view', 'resources')
    
    # Common data needed for all views
    institutions = Resource.objects.values_list('source', flat=True).distinct().order_by('source')
    
    context = {
        'institutions': institutions,
        'resource_types': ResourceType.choices,
        'view_mode': view_mode,
    }
    
    # Handle different view modes
    if view_mode == 'resources':
        context.update(_handle_resources_view(request))
    elif view_mode == 'triples':
        context.update(_handle_triples_view(request))
    elif view_mode == 'unified':
        context.update(_handle_unified_view(request))
    elif view_mode == 'relationships':
        context.update(_handle_relationships_view(request))
    
    # Return appropriate template based on request type
    if request.headers.get('HX-Request'):
        # Return partial content for HTMX requests
        if view_mode == 'resources':
            return render(request, 'partials/resource_list.html', context)
        elif view_mode == 'triples':
            return render(request, 'partials/triple_list.html', context)
        elif view_mode == 'unified':
            return render(request, 'partials/unified_results.html', context)
        elif view_mode == 'relationships':
            return render(request, 'partials/relationships_results.html', context)
    
    return render(request, 'data_explorer.html', context)

def _handle_resources_view(request):
    """Handle the resources view mode."""
    # Get filter parameters
    resource_type = request.GET.get('resource_type', '')
    institution = request.GET.get('institution', '')
    search_query = request.GET.get('q', '')
    search_mode = request.GET.get('search_mode', 'contains')
    page = request.GET.get('page', 1)
    
    logger.info(f"Resources view: type='{resource_type}', institution='{institution}', q='{search_query}', mode='{search_mode}', page={page}")
    
    # Base queryset
    resources = Resource.objects.all()
    
    # Apply filters
    if resource_type:
        resources = resources.filter(resource_type=resource_type)
    if institution:
        resources = resources.filter(source=institution)
    if search_query:
        search_filter = _build_multi_field_search(['uri', 'value', 'name'], search_query, search_mode)
        resources = resources.filter(search_filter)
    
    # Get total count before pagination
    total_count = resources.count()
    
    # Paginate
    paginator = Paginator(resources.order_by('-id'), 20)
    page_obj = paginator.get_page(page)
    
    logger.info(f"Resources query returned {total_count} total results, showing page {page}")
    
    return {
        'page_obj': page_obj,
        'total_count': total_count,
        'current_type': resource_type,
        'current_institution': institution,
        'current_query': search_query,
        'current_search_mode': search_mode,
    }

def _handle_triples_view(request):
    """Handle the triples view mode."""
    subject = request.GET.get('subject', '')
    predicate = request.GET.get('predicate', '')
    object_value = request.GET.get('object', '')
    institution = request.GET.get('institution', '')
    search_mode = request.GET.get('search_mode', 'contains')
    page = request.GET.get('page', 1)
    
    logger.info(f"Triples view: subject='{subject}', predicate='{predicate}', object='{object_value}', institution='{institution}', mode='{search_mode}', page={page}")
    
    # Don't load any triples if no search criteria provided
    if not any([subject, predicate, object_value, institution]):
        return {
            'page_obj': None,
            'is_paginated': False,
            'triples': [],
            'current_search_mode': search_mode,
        }
    
    triples = Triple.objects.all().select_related('subject', 'predicate', 'object')
    
    # Apply filters
    if subject:
        subject_filter = _build_multi_field_search(['subject__uri', 'subject__value', 'subject__name'], subject, search_mode)
        triples = triples.filter(subject_filter)
    if predicate:
        predicate_filter = _build_multi_field_search(['predicate__uri', 'predicate__value', 'predicate__name'], predicate, search_mode)
        triples = triples.filter(predicate_filter)
    if object_value:
        object_filter = _build_multi_field_search(['object__uri', 'object__value', 'object__name'], object_value, search_mode)
        triples = triples.filter(object_filter)
    if institution:
        triples = triples.filter(
            Q(subject__source=institution) | 
            Q(object__source=institution)
        )
    
    # Paginate
    paginator = Paginator(triples.order_by('-id'), 20)
    page_obj = paginator.get_page(page)
    
    logger.info(f"Triples query returned {triples.count()} total results, showing page {page}")
    
    return {
        'page_obj': page_obj,
        'is_paginated': paginator.num_pages > 1,
        'triples': page_obj.object_list,
        'current_search_mode': search_mode,
    }

def _handle_unified_view(request):
    """Handle the unified search view mode."""
    search_term = request.GET.get('search', '')
    institution = request.GET.get('institution', '')
    include_resources = request.GET.get('include_resources', '1') == '1'
    include_triples = request.GET.get('include_triples', '1') == '1'
    search_mode = request.GET.get('search_mode', 'contains')
    page = request.GET.get('page', 1)
    
    logger.info(f"Unified view: search='{search_term}', institution='{institution}', resources={include_resources}, triples={include_triples}, mode='{search_mode}', page={page}")
    
    resources = []
    triples = []
    search_performed = bool(search_term.strip())
    
    if search_performed:
        # Search resources
        if include_resources:
            resource_query = Resource.objects.all()
            if search_term:
                search_filter = _build_multi_field_search(['uri', 'value', 'name'], search_term, search_mode)
                resource_query = resource_query.filter(search_filter)
            if institution:
                resource_query = resource_query.filter(source=institution)
            
            resources = resource_query.order_by('-id')[:50]  # Limit to 50 for performance
        
        # Search triples
        if include_triples:
            triple_query = Triple.objects.all().select_related('subject', 'predicate', 'object')
            if search_term:
                search_filter = _build_multi_field_search([
                    'subject__uri', 'subject__value', 'subject__name',
                    'predicate__uri', 'predicate__value', 'predicate__name',
                    'object__uri', 'object__value', 'object__name'
                ], search_term, search_mode)
                triple_query = triple_query.filter(search_filter)
            if institution:
                triple_query = triple_query.filter(
                    Q(subject__source=institution) | 
                    Q(object__source=institution)
                )
            
            triples = triple_query.order_by('-id')[:50]  # Limit to 50 for performance
    
    logger.info(f"Unified search found {len(resources)} resources and {len(triples)} triples")
    
    return {
        'resources': resources,
        'triples': triples,
        'search_performed': search_performed,
        'search_term': search_term,
        'current_institution': institution,
        'include_resources': include_resources,
        'include_triples': include_triples,
        'current_search_mode': search_mode,
    }

def _handle_relationships_view(request):
    """Handle the relationships view mode - show all connections for a specific resource."""
    resource_uri = request.GET.get('resource_uri', '')
    search_mode = request.GET.get('search_mode', 'exact')  # Default to exact for URI matching
    page = request.GET.get('page', 1)
    
    logger.info(f"Relationships view: resource_uri='{resource_uri}', mode='{search_mode}', page={page}")
    
    # Don't load any relationships if no resource URI provided
    if not resource_uri.strip():
        return {
            'resource': None,
            'subject_triples': [],
            'object_triples': [],
            'all_triples': [],
            'page_obj': None,
            'total_connections': 0,
            'current_resource_uri': resource_uri,
            'current_search_mode': search_mode,
        }
    
    # Find the resource
    if search_mode == 'exact':
        resources = Resource.objects.filter(uri=resource_uri)
    else:
        # Use the search filter for non-exact matches
        search_filter = _build_search_filter('uri', resource_uri, search_mode)
        resources = Resource.objects.filter(search_filter)
    
    if not resources.exists():
        logger.warning(f"No resource found for URI: {resource_uri}")
        return {
            'resource': None,
            'subject_triples': [],
            'object_triples': [],
            'all_triples': [],
            'page_obj': None,
            'total_connections': 0,
            'current_resource_uri': resource_uri,
            'current_search_mode': search_mode,
            'error_message': f'No resource found for URI: {resource_uri}'
        }
    
    # Use the first matching resource (or exact match)
    resource = resources.first()
    
    # Get ALL relationships for this resource (both directions)
    subject_triples = Triple.objects.filter(subject=resource).select_related('predicate', 'object')
    object_triples = Triple.objects.filter(object=resource).select_related('subject', 'predicate')
    
    # Combine all triples for display
    all_triples_list = list(subject_triples) + list(object_triples)
    total_connections = len(all_triples_list)
    
    # Paginate the combined results
    paginator = Paginator(all_triples_list, 50)  # Show 50 relationships per page
    page_obj = paginator.get_page(page)
    
    logger.info(f"Found resource '{resource.uri}' with {len(subject_triples)} outgoing and {len(object_triples)} incoming relationships")
    
    return {
        'resource': resource,
        'subject_triples': subject_triples,
        'object_triples': object_triples,
        'all_triples': all_triples_list,
        'page_obj': page_obj,
        'total_connections': total_connections,
        'current_resource_uri': resource_uri,
        'current_search_mode': search_mode,
    }


@general_login_required
def export_data_as_json(request):
    """
    Export data from the data explorer as JSON.
    Supports exporting resources, triples, or property-specific data.
    """
    export_type = request.GET.get('export_type', 'current')  # 'current', 'property', 'all'
    view_mode = request.GET.get('view', 'resources')
    
    logger.info(f"JSON Export requested: type={export_type}, view_mode={view_mode}")
    
    # Build the export data based on type
    export_data = {}
    
    if export_type == 'property':
        # Export all literals associated with a specific property
        property_uri = request.GET.get('property_uri', '')
        if property_uri:
            # Get all triples where this property is the predicate
            triples = Triple.objects.filter(
                predicate__uri=property_uri
            ).select_related('subject', 'predicate', 'object')
            
            literals_list = []
            objects_list = []
            
            for triple in triples:
                # Check if this is a literal resource (has URI containing /data/literals/)
                is_literal = (triple.object and triple.object.uri and 
                             '/data/literals/' in triple.object.uri)
                
                if is_literal:
                    # This is a literal value (even though it has a URI)
                    literals_list.append({
                        'value': triple.object.value or triple.object.name,
                        'literal_uri': triple.object.uri,  # Include the literal's URI for reference
                        'subject_uri': triple.subject.uri if triple.subject else None,
                        'subject_name': triple.subject.name if triple.subject else None
                    })
                elif triple.object and triple.object.value and not triple.object.uri:
                    # Traditional literals (values without URIs)
                    literals_list.append({
                        'value': triple.object.value,
                        'subject_uri': triple.subject.uri if triple.subject else None,
                        'subject_name': triple.subject.name if triple.subject else None
                    })
                elif triple.object and triple.object.uri:
                    # Regular URI objects (resources that are not literals)
                    objects_list.append({
                        'uri': triple.object.uri,
                        'value': triple.object.value,
                        'name': triple.object.name,
                        'type': triple.object.resource_type,
                        'subject_uri': triple.subject.uri if triple.subject else None,
                        'subject_name': triple.subject.name if triple.subject else None
                    })
            
            export_data = {
                'property': property_uri,
                'total_literals': len(literals_list),
                'total_objects': len(objects_list),
                'literals': literals_list,  # Only literal values
                'objects': objects_list,    # Only URI-based resources
                'summary': {
                    'description': f'All values associated with property: {property_uri}',
                    'literal_count': len(literals_list),
                    'resource_count': len(objects_list),
                    'total_relationships': len(literals_list) + len(objects_list)
                }
            }
    
    elif export_type == 'current':
        # Export current search results based on view mode
        if view_mode == 'resources':
            # Get current resource search parameters
            resource_type = request.GET.get('resource_type', '')
            institution = request.GET.get('institution', '')
            search_query = request.GET.get('q', '')
            search_mode = request.GET.get('search_mode', 'contains')
            
            # Apply same filters as in _handle_resources_view
            resources = Resource.objects.all()
            if resource_type:
                resources = resources.filter(resource_type=resource_type)
            if institution:
                resources = resources.filter(source=institution)
            if search_query:
                search_filter = _build_multi_field_search(['uri', 'value', 'name'], search_query, search_mode)
                resources = resources.filter(search_filter)
            
            # Limit to reasonable amount for JSON export
            resources = resources[:1000]
            
            export_data = {
                'export_type': 'resources',
                'filters': {
                    'resource_type': resource_type,
                    'institution': institution,
                    'search_query': search_query,
                    'search_mode': search_mode
                },
                'total': len(resources),
                'resources': [
                    {
                        'id': r.id,
                        'uri': r.uri,
                        'value': r.value,
                        'name': r.name,
                        'type': r.resource_type,
                        'source': r.source,
                        'created_at': r.created_at.isoformat() if r.created_at else None
                    }
                    for r in resources
                ]
            }
        
        elif view_mode == 'triples':
            # Get current triple search parameters
            subject = request.GET.get('subject', '')
            predicate = request.GET.get('predicate', '')
            object_value = request.GET.get('object', '')
            institution = request.GET.get('institution', '')
            search_mode = request.GET.get('search_mode', 'contains')
            
            # Apply same filters as in _handle_triples_view
            triples = Triple.objects.all().select_related('subject', 'predicate', 'object')
            if subject:
                subject_filter = _build_multi_field_search(['subject__uri', 'subject__value', 'subject__name'], subject, search_mode)
                triples = triples.filter(subject_filter)
            if predicate:
                predicate_filter = _build_multi_field_search(['predicate__uri', 'predicate__value', 'predicate__name'], predicate, search_mode)
                triples = triples.filter(predicate_filter)
            if object_value:
                object_filter = _build_multi_field_search(['object__uri', 'object__value', 'object__name'], object_value, search_mode)
                triples = triples.filter(object_filter)
            if institution:
                triples = triples.filter(
                    Q(subject__source=institution) | 
                    Q(object__source=institution)
                )
            
            # Limit to reasonable amount
            triples = triples[:1000]
            
            export_data = {
                'export_type': 'triples',
                'filters': {
                    'subject': subject,
                    'predicate': predicate,
                    'object': object_value,
                    'institution': institution,
                    'search_mode': search_mode
                },
                'total': len(triples),
                'triples': [
                    {
                        'id': t.id,
                        'subject': {
                            'uri': t.subject.uri if t.subject else None,
                            'value': t.subject.value if t.subject else None,
                            'name': t.subject.name if t.subject else None
                        },
                        'predicate': {
                            'uri': t.predicate.uri if t.predicate else None,
                            'value': t.predicate.value if t.predicate else None
                        },
                        'object': {
                            'uri': t.object.uri if t.object else None,
                            'value': t.object.value if t.object else None,
                            'name': t.object.name if t.object else None
                        }
                    }
                    for t in triples
                ]
            }
        
        elif view_mode == 'relationships':
            # Export relationships for a specific resource
            resource_uri = request.GET.get('resource_uri', '')
            if resource_uri:
                resource = Resource.objects.filter(uri=resource_uri).first()
                if resource:
                    subject_triples = Triple.objects.filter(subject=resource).select_related('predicate', 'object')
                    object_triples = Triple.objects.filter(object=resource).select_related('subject', 'predicate')
                    
                    export_data = {
                        'export_type': 'relationships',
                        'resource': {
                            'uri': resource.uri,
                            'value': resource.value,
                            'name': resource.name,
                            'type': resource.resource_type
                        },
                        'outgoing_relationships': [
                            {
                                'predicate': t.predicate.uri if t.predicate else None,
                                'object': {
                                    'uri': t.object.uri if t.object else None,
                                    'value': t.object.value if t.object else None,
                                    'name': t.object.name if t.object else None
                                }
                            }
                            for t in subject_triples
                        ],
                        'incoming_relationships': [
                            {
                                'subject': {
                                    'uri': t.subject.uri if t.subject else None,
                                    'value': t.subject.value if t.subject else None,
                                    'name': t.subject.name if t.subject else None
                                },
                                'predicate': t.predicate.uri if t.predicate else None
                            }
                            for t in object_triples
                        ]
                    }
    
    # Create the JSON response with proper headers
    response = HttpResponse(
        json.dumps(export_data, indent=2, ensure_ascii=False),
        content_type='application/json'
    )
    
    # Set filename for download
    filename = f"arkumu_export_{view_mode}_{export_type}.json"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    return response 