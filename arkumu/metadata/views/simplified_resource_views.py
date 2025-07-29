"""
Simplified Resource Views with HTMX

Replaces complex harmonization flow with direct resource creation and linking.
"""

from django.shortcuts import render, get_object_or_404
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import View
from django.http import JsonResponse, HttpResponse
from django.db.models import Q, Count, Prefetch

from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.users.models import Organization


class UnifiedResourceView(LoginRequiredMixin, View):
    """Single view handling resource creation and linking with HTMX"""
    
    def get(self, request):
        """Display unified resource management interface"""
        context = {
            'resource_types': ResourceType.choices,
            'organizations': Organization.objects.filter(is_active=True),
            'predicates': Resource.objects.filter(
                resource_type=ResourceType.PROPERTY
            ).order_by('name')[:100]  # Limit to first 100 for better UX
        }
        return render(request, 'metadata/resource/unified.html', context)
    
    def post(self, request):
        """Create resource and links in one operation"""
        # Create the resource
        resource = Resource.objects.create(
            uri=request.POST.get('uri'),
            name=request.POST.get('name'),
            resource_type=request.POST.get('resource_type', ResourceType.IRI),
            organization=request.user.organization,
            value=request.POST.get('value', ''),
        )
        
        # Create links to existing IRIs with multiple predicates
        linked_iris = request.POST.getlist('linked_iris')
        predicate_ids = request.POST.getlist('predicate_ids')
        
        created_links = 0
        if linked_iris and predicate_ids:
            for iri_id in linked_iris:
                for predicate_id in predicate_ids:
                    triple, created = Triple.objects.get_or_create(
                        subject=resource,
                        predicate_id=predicate_id,
                        object_id=iri_id,
                        source=request.user.organization
                    )
                    if created:
                        created_links += 1
        
        # Return HTMX response
        predicate_count = len(predicate_ids) if predicate_ids else 0
        iri_count = len(linked_iris) if linked_iris else 0
        total_possible = predicate_count * iri_count
        
        return HttpResponse(
            f'''
            <div class="alert alert-success">
                <svg xmlns="http://www.w3.org/2000/svg" class="stroke-current shrink-0 h-6 w-6" fill="none" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <div>
                    <h3 class="font-bold">Resource Created!</h3>
                    <div class="text-xs">
                        Created {resource.name or resource.uri} with {created_links} links
                        {f" ({predicate_count} relationships × {iri_count} resources = {total_possible} total combinations)" if total_possible > 0 else ""}
                    </div>
                </div>
            </div>
            ''',
            headers={
                'HX-Trigger': 'resourceCreated',
                'HX-Retarget': '#resource-form',
                'HX-Reswap': 'outerHTML'
            }
        )


class SearchResourcesView(LoginRequiredMixin, View):
    """HTMX endpoint for searching resources with filters"""
    
    def get(self, request):
        query = request.GET.get('q', '')
        resource_type = request.GET.get('type', '')
        org_id = request.GET.get('org', '')
        
        # Build query
        resources = Resource.objects.all()
        
        if query:
            resources = resources.filter(
                Q(uri__icontains=query) | 
                Q(name__icontains=query) |
                Q(value__icontains=query)
            )
        
        if resource_type:
            resources = resources.filter(resource_type=resource_type)
        
        if org_id:
            resources = resources.filter(organization_id=org_id)
        
        # Optimize query
        resources = resources.select_related('organization').annotate(
            usage_count=Count('subject_triples') + Count('object_triples')
        )[:20]
        
        return render(request, 'metadata/partials/resource_dropdown.html', {
            'resources': resources,
            'selection_mode': request.GET.get('mode', 'single')
        })


class QuickLinkResourcesView(LoginRequiredMixin, View):
    """HTMX endpoint for quickly linking resources with multiple predicates"""
    
    def post(self, request):
        subject_id = request.POST.get('subject_id')
        predicate_ids = request.POST.getlist('predicate_ids')
        object_ids = request.POST.getlist('object_ids')
        
        if not all([subject_id, predicate_ids, object_ids]):
            return HttpResponse(
                '<div class="alert alert-error">Missing required fields</div>',
                status=400
            )
        
        created_count = 0
        for object_id in object_ids:
            for predicate_id in predicate_ids:
                triple, created = Triple.objects.get_or_create(
                    subject_id=subject_id,
                    predicate_id=predicate_id,
                    object_id=object_id,
                    source=request.user.organization
                )
                if created:
                    created_count += 1
        
        total_combinations = len(object_ids) * len(predicate_ids)
        return HttpResponse(
            f'<span class="badge badge-success">{created_count} of {total_combinations} links created</span>',
            headers={'HX-Trigger': 'linksCreated'}
        )


class ResourceLinkFormView(LoginRequiredMixin, View):
    """HTMX partial for inline resource linking"""
    
    def get(self, request, resource_id):
        resource = get_object_or_404(Resource, id=resource_id)
        predicates = Resource.objects.filter(
            resource_type=ResourceType.PROPERTY
        ).order_by('name')
        
        return render(request, 'metadata/partials/link_form.html', {
            'resource': resource,
            'predicates': predicates
        })


class ResourceDashboardView(LoginRequiredMixin, View):
    """Simplified dashboard replacing multiple list views"""
    
    def get(self, request):
        section = request.GET.get('section', 'overview')
        
        # Base context
        context = {
            'section': section,
            'stats': self._get_stats(request.user.organization)
        }
        
        # Section-specific data
        if section == 'resources':
            context['resources'] = Resource.objects.filter(
                organization=request.user.organization
            ).select_related('organization').order_by('-created_at')[:50]
        
        elif section == 'links':
            context['triples'] = Triple.objects.filter(
                source=request.user.organization
            ).select_related(
                'subject', 'predicate', 'object'
            ).order_by('-created_at')[:50]
        
        elif section == 'search':
            # Just return the search interface
            pass
        
        # HTMX partial or full page
        if request.headers.get('HX-Request'):
            template = f'metadata/resource/partials/{section}.html'
        else:
            template = 'metadata/resource/dashboard.html'
        
        return render(request, template, context)
    
    def _get_stats(self, organization):
        """Get dashboard statistics"""
        return {
            'resource_count': Resource.objects.filter(
                organization=organization
            ).count(),
            'triple_count': Triple.objects.filter(
                source=organization
            ).count(),
            'linked_resources': Resource.objects.filter(
                organization=organization,
                subject_triples__isnull=False
            ).distinct().count(),
            'resource_types': Resource.objects.filter(
                organization=organization
            ).values('resource_type').annotate(
                count=Count('id')
            ).order_by('-count')
        }


class DeleteTripleView(LoginRequiredMixin, View):
    """HTMX endpoint for deleting a triple"""
    
    def delete(self, request, triple_id):
        triple = get_object_or_404(
            Triple, 
            id=triple_id, 
            source=request.user.organization
        )
        triple.delete()
        
        return HttpResponse(
            '<div class="text-success">Link removed</div>',
            headers={'HX-Trigger': 'linkDeleted'}
        )


class GetPredicatesView(LoginRequiredMixin, View):
    """HTMX endpoint for loading predicates with search"""
    
    def get(self, request):
        search_query = request.GET.get('predicate-search', '').strip()
        
        predicates = Resource.objects.filter(
            resource_type=ResourceType.PROPERTY
        )
        
        # Apply search filter if provided
        if search_query:
            predicates = predicates.filter(
                Q(name__icontains=search_query) | 
                Q(uri__icontains=search_query)
            ).order_by('name')[:50]  # Show top 50 matches
        else:
            predicates = predicates.order_by('name')[:100]  # Show first 100 by default
        
        return render(request, 'metadata/partials/predicate_dropdown.html', {
            'predicates': predicates,
            'search_query': search_query
        })