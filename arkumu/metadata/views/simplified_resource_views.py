"""
Simplified Resource Views with HTMX

Replaces complex harmonization flow with direct resource creation and linking.
"""

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import View
from django.http import JsonResponse, HttpResponse
from django.db.models import Q, Count, Prefetch
from django.urls import reverse

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
    """Redirect to unified data explorer"""
    
    def get(self, request):
        # Redirect all resource dashboard requests to the unified data explorer
        return redirect(reverse('metadata:data_explorer'))


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


class OntologyLinkingModalView(LoginRequiredMixin, View):
    """Simple modal view for ontology linking"""
    
    def get(self, request):
        """Display ontology linking modal"""
        resource_id = request.GET.get('resource_id')
        resource = get_object_or_404(Resource, pk=resource_id) if resource_id else None
        
        # Define common ontology types with their templates and patterns
        # (same as used in CSV mapping editor)
        ontology_presets = {
            'arkumu': {
                'name': 'Arkumu',
                'uri_template': 'https://arkumu.nrw/',
                'identifier_pattern': r'^[a-zA-Z][a-zA-Z0-9_]*$',
                'example': 'hasTitle',
                'description': 'Arkumu ontology with fixed property URI'
            },
            'cidoc_crm': {
                'name': 'CIDOC-CRM',
                'uri_template': 'http://www.cidoc-crm.org/cidoc-crm/',
                'identifier_pattern': r'^(E\d+|P\d+[i]?)$',
                'example': 'P14_carried_out_by',
                'description': 'CIDOC-CRM with fixed property/class URI'
            },
            'orcid': {
                'name': 'ORCID',
                'uri_template': 'https://orcid.org/{identifier}',
                'identifier_pattern': r'^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$',
                'example': '0000-0002-1825-0097',
                'description': 'ORCID researcher identifiers'
            },
            'wikidata': {
                'name': 'Wikidata',
                'uri_template': 'https://www.wikidata.org/entity/{identifier}',
                'identifier_pattern': r'^Q\d+$',
                'example': 'Q42',
                'description': 'Wikidata entity IDs'
            },
            'gnd': {
                'name': 'GND (German National Library)',
                'uri_template': 'https://d-nb.info/gnd/{identifier}',
                'identifier_pattern': r'^\d{8,9}[\dX]?$',
                'example': '118501429',
                'description': 'German National Library authority file'
            },
            'viaf': {
                'name': 'VIAF',
                'uri_template': 'https://viaf.org/viaf/{identifier}',
                'identifier_pattern': r'^\d+$',
                'example': '12347231',
                'description': 'Virtual International Authority File'
            },
            'loc': {
                'name': 'Library of Congress',
                'uri_template': 'http://id.loc.gov/authorities/names/{identifier}',
                'identifier_pattern': r'^[a-z]{1,2}\d{8,10}$',
                'example': 'n80057250',
                'description': 'Library of Congress Name Authority File'
            },
            'isni': {
                'name': 'ISNI',
                'uri_template': 'https://isni.org/isni/{identifier}',
                'identifier_pattern': r'^\d{15}[\dX]$',
                'example': '0000000121032683',
                'description': 'International Standard Name Identifier'
            },
            'lido': {
                'name': 'LIDO Terminology',
                'uri_template': 'http://terminology.lido-schema.org/{identifier}',
                'identifier_pattern': r'^[a-zA-Z][a-zA-Z0-9_]*$',
                'example': 'eventType',
                'description': 'LIDO Terminology für Museumsdaten'
            },
            'filmportal_vocnet': {
                'name': 'Filmportal vocnet',
                'uri_template': 'https://filmportal.vocnet.org/category/{identifier}',
                'identifier_pattern': r'^[a-zA-Z][a-zA-Z0-9_]*$',
                'example': 'director',
                'description': 'Filmportal vocnet Vokabular'
            },
            'aat': {
                'name': 'AAT (Art & Architecture Thesaurus)',
                'uri_template': 'http://vocab.getty.edu/aat/{identifier}',
                'identifier_pattern': r'^\d+$',
                'example': '300021147',
                'description': 'Getty Art & Architecture Thesaurus (AAT) Vokabular'
            },
            'dublin_core': {
                'name': 'Dublin Core Terms',
                'uri_template': 'http://purl.org/dc/terms/{identifier}',
                'identifier_pattern': r'^[a-zA-Z][a-zA-Z0-9_]*$',
                'example': 'title',
                'description': 'Dublin Core Metadata Terms vocabulary'
            },
            'foaf': {
                'name': 'FOAF (Friend of a Friend)',
                'uri_template': 'http://xmlns.com/foaf/0.1/{identifier}',
                'identifier_pattern': r'^[a-zA-Z][a-zA-Z0-9_]*$',
                'example': 'name',
                'description': 'FOAF vocabulary for describing people and relationships'
            },
            'skos': {
                'name': 'SKOS (Simple Knowledge Organization System)',
                'uri_template': 'http://www.w3.org/2004/02/skos/core#{identifier}',
                'identifier_pattern': r'^[a-zA-Z][a-zA-Z0-9_]*$',
                'example': 'prefLabel',
                'description': 'SKOS vocabulary for organizing knowledge'
            },
            'schema_org': {
                'name': 'Schema.org',
                'uri_template': 'https://schema.org/{identifier}',
                'identifier_pattern': r'^[a-zA-Z][a-zA-Z0-9_]*$',
                'example': 'Person',
                'description': 'Schema.org structured data vocabulary'
            },
            'bibframe': {
                'name': 'BIBFRAME',
                'uri_template': 'http://id.loc.gov/ontologies/bibframe/{identifier}',
                'identifier_pattern': r'^[a-zA-Z][a-zA-Z0-9_]*$',
                'example': 'Work',
                'description': 'Bibliographic Framework vocabulary'
            },
            'dcat': {
                'name': 'DCAT (Data Catalog Vocabulary)',
                'uri_template': 'http://www.w3.org/ns/dcat#{identifier}',
                'identifier_pattern': r'^[a-zA-Z][a-zA-Z0-9_]*$',
                'example': 'Dataset',
                'description': 'W3C Data Catalog vocabulary'
            },
            'prov': {
                'name': 'PROV-O (Provenance Ontology)',
                'uri_template': 'http://www.w3.org/ns/prov#{identifier}',
                'identifier_pattern': r'^[a-zA-Z][a-zA-Z0-9_]*$',
                'example': 'Activity',
                'description': 'W3C Provenance ontology'
            },
            'void': {
                'name': 'VoID (Vocabulary of Interlinked Datasets)',
                'uri_template': 'http://rdfs.org/ns/void#{identifier}',
                'identifier_pattern': r'^[a-zA-Z][a-zA-Z0-9_]*$',
                'example': 'Dataset',
                'description': 'Vocabulary for describing linked datasets'
            },
            'org': {
                'name': 'ORG (Organization Ontology)',
                'uri_template': 'http://www.w3.org/ns/org#{identifier}',
                'identifier_pattern': r'^[a-zA-Z][a-zA-Z0-9_]*$',
                'example': 'Organization',
                'description': 'W3C Organization ontology'
            },
            'time': {
                'name': 'OWL-Time',
                'uri_template': 'http://www.w3.org/2006/time#{identifier}',
                'identifier_pattern': r'^[a-zA-Z][a-zA-Z0-9_]*$',
                'example': 'Instant',
                'description': 'W3C Time ontology'
            },
            'custom': {
                'name': 'Custom Ontology',
                'uri_template': '',
                'identifier_pattern': '',
                'example': '',
                'description': 'Custom ontology with user-defined template'
            }
        }
        
        return render(request, 'metadata/partials/ontology_linking_modal.html', {
            'resource': resource,
            'ontology_presets': ontology_presets
        })