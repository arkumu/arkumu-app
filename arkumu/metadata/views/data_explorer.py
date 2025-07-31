from django.shortcuts import render
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.db.models import Q, Count, Exists, OuterRef, Case, When, Value, CharField, Subquery, F
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.views.generic import ListView, DetailView
from django.conf import settings
from arkumu.metadata.models.resource import Resource, ResourceType, PublicAccessLevel
from arkumu.metadata.models.triples import Triple

class DataExplorerView(ListView):
    """Main data explorer interface"""
    model = Resource
    template_name = 'metadata/data_explorer.html'
    context_object_name = 'resources'
    paginate_by = 20
    
    def get_queryset(self):
        """Get resources with appropriate access control and debug mode support."""
        # Get sameAs predicate for Arkumu linking check
        same_as_subquery = Triple.objects.filter(
            subject=OuterRef('pk'),
            predicate__uri='http://www.w3.org/2002/07/owl#sameAs',
            object__uri__startswith='http://data.arkumu.org/arkumu/types/',
            is_derived=True
        )
        
        # Get linked ontology name from owl:sameAs relationships only
        linked_ontology_subquery = Triple.objects.filter(
            subject=OuterRef('pk'),
            predicate__uri='http://www.w3.org/2002/07/owl#sameAs',
            is_derived=True
        ).annotate(
            ontology_name=Case(
                # owl:sameAs relationships
                When(object__uri__startswith='http://data.arkumu.org/arkumu/types/', then=Value('Arkumu')),
                When(object__uri__startswith='http://www.cidoc-crm.org/cidoc-crm/', then=Value('CIDOC-CRM')),
                When(object__uri__startswith='http://purl.org/dc/', then=Value('Dublin Core')),
                When(object__uri__startswith='http://schema.org/', then=Value('Schema.org')),
                # External ontology relationships (by object URI pattern)
                When(object__uri__startswith='https://orcid.org/', then=Value('ORCID')),
                When(object__uri__startswith='https://www.wikidata.org/', then=Value('Wikidata')),
                When(object__uri__startswith='https://viaf.org/', then=Value('VIAF')),
                When(object__uri__startswith='https://d-nb.info/gnd/', then=Value('GND')),
                When(object__uri__startswith='http://id.loc.gov/', then=Value('Library of Congress')),
                When(object__uri__startswith='https://isni.org/', then=Value('ISNI')),
                When(object__uri__startswith='http://vocab.getty.edu/aat/', then=Value('AAT')),
                When(object__uri__startswith='http://terminology.lido-schema.org/', then=Value('LIDO')),
                When(object__uri__startswith='https://filmportal.vocnet.org/', then=Value('Filmportal')),
                default=Value('Other'),
                output_field=CharField()
            )
        ).values('ontology_name')[:1]
        
        # Start with all resources, excluding placeholders by default
        queryset = Resource.objects.exclude(is_placeholder=True).select_related('organization').annotate(
            subject_count=Count('subject_triples', distinct=True),
            predicate_count=Count('predicate_triples', distinct=True),
            object_count=Count('object_triples', distinct=True),
            is_arkumu_linked=Exists(same_as_subquery),
            linked_ontology=Subquery(linked_ontology_subquery)
        )
        
        # Debug mode - show all resources in development
        if settings.DEBUG and self.request.GET.get('debug') == 'true':
            return self.apply_sorting(self.apply_filters(queryset))
        
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
        
        # Apply filters and sorting
        return self.apply_sorting(self.apply_filters(queryset))
    
    def _get_accessible_organizations(self):
        """Get list of organizations accessible to current user."""
        # Start with all resources, excluding placeholders
        queryset = Resource.objects.exclude(is_placeholder=True)
        
        # Debug mode - show all organizations in development
        if settings.DEBUG and self.request.GET.get('debug') == 'true':
            return queryset.select_related('organization').values_list('organization__name', flat=True).distinct().order_by('organization__name')
        
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
        
        return queryset.select_related('organization').values_list('organization__name', flat=True).distinct().order_by('organization__name')
    
    def apply_filters(self, queryset):
        """Apply various filters based on request parameters"""
        # Search
        search = self.request.GET.get('search', '').strip()
        if search:
            queryset = queryset.filter(
                Q(uri__icontains=search) |
                Q(name__icontains=search) |
                Q(value__icontains=search)
            )
        
        # Resource type filter
        resource_types = self.request.GET.getlist('resource_type')
        if resource_types:
            queryset = queryset.filter(resource_type__in=resource_types)
        
        # Resource type groups
        type_group = self.request.GET.get('type_group')
        if type_group == 'identifiers':
            queryset = queryset.exclude(resource_type=ResourceType.LITERAL)
        elif type_group == 'literals':
            queryset = queryset.filter(resource_type=ResourceType.LITERAL)
        elif type_group == 'placeholders':
            # Override the default exclusion of placeholders and show only placeholders
            # Get sameAs predicate for Arkumu linking check
            same_as_subquery = Triple.objects.filter(
                subject=OuterRef('pk'),
                predicate__uri='http://www.w3.org/2002/07/owl#sameAs',
                object__uri__startswith='http://data.arkumu.org/arkumu/types/',
                is_derived=True
            )
            
            # Get linked ontology name subquery for placeholders (use same logic as main query)
            linked_ontology_subquery_ph = Triple.objects.filter(
                subject=OuterRef('pk'),
                predicate__uri='http://www.w3.org/2002/07/owl#sameAs',
                is_derived=True
            ).annotate(
                ontology_name=Case(
                    # owl:sameAs relationships
                    When(object__uri__startswith='http://data.arkumu.org/arkumu/types/', then=Value('Arkumu')),
                    When(object__uri__startswith='http://www.cidoc-crm.org/cidoc-crm/', then=Value('CIDOC-CRM')),
                    When(object__uri__startswith='http://purl.org/dc/', then=Value('Dublin Core')),
                    When(object__uri__startswith='http://schema.org/', then=Value('Schema.org')),
                    # External ontology relationships (by object URI pattern)
                    When(object__uri__startswith='https://orcid.org/', then=Value('ORCID')),
                    When(object__uri__startswith='https://www.wikidata.org/', then=Value('Wikidata')),
                    When(object__uri__startswith='https://viaf.org/', then=Value('VIAF')),
                    When(object__uri__startswith='https://d-nb.info/gnd/', then=Value('GND')),
                    When(object__uri__startswith='http://id.loc.gov/', then=Value('Library of Congress')),
                    When(object__uri__startswith='https://isni.org/', then=Value('ISNI')),
                    When(object__uri__startswith='http://vocab.getty.edu/aat/', then=Value('AAT')),
                    When(object__uri__startswith='http://terminology.lido-schema.org/', then=Value('LIDO')),
                    When(object__uri__startswith='https://filmportal.vocnet.org/', then=Value('Filmportal')),
                    default=Value('Other'),
                    output_field=CharField()
                )
            ).values('ontology_name')[:1]
            
            queryset = Resource.objects.filter(is_placeholder=True).select_related('organization').annotate(
                subject_count=Count('subject_triples', distinct=True),
                predicate_count=Count('predicate_triples', distinct=True),
                object_count=Count('object_triples', distinct=True),
                is_arkumu_linked=Exists(same_as_subquery),
                linked_ontology=Subquery(linked_ontology_subquery_ph)
            )
        
        # Organization filter
        organizations = self.request.GET.getlist('organization')
        if organizations:
            queryset = queryset.filter(organization__name__in=organizations)
        
        # Triple usage filter
        triple_usage = self.request.GET.get('triple_usage')
        if triple_usage == 'as_subject':
            queryset = queryset.filter(
                Exists(Triple.objects.filter(subject=OuterRef('pk')))
            )
        elif triple_usage == 'as_predicate':
            queryset = queryset.filter(
                Exists(Triple.objects.filter(predicate=OuterRef('pk')))
            )
        elif triple_usage == 'as_object':
            queryset = queryset.filter(
                Exists(Triple.objects.filter(object=OuterRef('pk')))
            )
        elif triple_usage == 'no_triples':
            queryset = queryset.filter(
                ~Exists(Triple.objects.filter(
                    Q(subject=OuterRef('pk')) |
                    Q(predicate=OuterRef('pk')) |
                    Q(object=OuterRef('pk'))
                ))
            )
        
        # External linking
        externally_linked = self.request.GET.get('externally_linked')
        if externally_linked == 'true':
            queryset = queryset.filter(is_externally_linked=True)
        elif externally_linked == 'false':
            queryset = queryset.filter(is_externally_linked=False)
        
        
        return queryset
    
    def apply_sorting(self, queryset):
        """Apply sorting based on request parameters"""
        sort_by = self.request.GET.get('sort', 'created')
        sort_order = self.request.GET.get('order', 'desc')
        
        # Define valid sortable fields with their Django field names
        valid_sorts = {
            'type': 'resource_type',
            'resource': 'name',  # Fallback to uri if name is null
            'organization': 'organization__name',
            'created': 'created_at',
            'updated': 'updated_at',
            'subject_count': 'subject_count',
            'predicate_count': 'predicate_count', 
            'object_count': 'object_count',
            'total_triples': None  # Will be handled specially
        }
        
        # Default sort
        if sort_by not in valid_sorts:
            sort_by = 'created'
            sort_order = 'desc'
        
        # Handle special sorting cases
        if sort_by == 'total_triples':
            # Sort by total triple usage (sum of all three counts)
            from django.db.models import F
            queryset = queryset.annotate(
                total_usage=F('subject_count') + F('predicate_count') + F('object_count')
            )
            field = 'total_usage'
        elif sort_by == 'resource':
            # Sort by name, but fallback to uri for resources without names
            queryset = queryset.annotate(
                sort_name=Case(
                    When(name__isnull=False, then=F('name')),
                    When(name='', then=F('uri')),
                    default=F('uri')
                )
            )
            field = 'sort_name'
        else:
            field = valid_sorts[sort_by]
        
        # Apply ordering
        if sort_order == 'desc':
            field = f'-{field}'
            
        return queryset.order_by(field)
    
    def get_context_data(self, **kwargs):
        if not hasattr(self, 'kwargs'):
            self.kwargs = {}
        context = super().get_context_data(**kwargs)
        
        # Add filter options for the template
        context['filter_options'] = {
            'resource_types': [
                {'value': ResourceType.IRI, 'label': 'IRI'},
                {'value': ResourceType.CLASS, 'label': 'Class'},
                {'value': ResourceType.PROPERTY, 'label': 'Property'},
                {'value': ResourceType.LITERAL, 'label': 'Literal'},
            ],
            'type_groups': [
                {'value': 'identifiers', 'label': 'Identifiers (IRI, Class, Property)'},
                {'value': 'literals', 'label': 'Literals Only'},
                {'value': 'placeholders', 'label': 'Placeholder Resources'},
            ],
            'triple_usage': [
                {'value': 'as_subject', 'label': 'Used as Subject'},
                {'value': 'as_predicate', 'label': 'Used as Predicate'},
                {'value': 'as_object', 'label': 'Used as Object'},
                {'value': 'no_triples', 'label': 'No Triple References'},
            ],
            'organizations': self._get_accessible_organizations(),
        }
        
        # Current filters for template
        context['current_filters'] = {
            'search': self.request.GET.get('search', ''),
            'resource_type': self.request.GET.getlist('resource_type'),
            'type_group': self.request.GET.get('type_group'),
            'organization': self.request.GET.getlist('organization'),
            'triple_usage': self.request.GET.get('triple_usage'),
            'externally_linked': self.request.GET.get('externally_linked'),
        }
        
        # Current sorting for template
        context['current_sort'] = {
            'sort': self.request.GET.get('sort', 'created'),
            'order': self.request.GET.get('order', 'desc'),
        }
        
        # Add semantic statistics (from resource dashboard)
        context['semantic_stats'] = self._get_semantic_stats()
        
        return context
    
    def _get_semantic_stats(self):
        """Get semantic model statistics for the overview section"""
        # Get rdf:type predicate
        rdf_type = Resource.objects.filter(
            uri='http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
        ).first()
        
        # Get base accessible queryset (same access control as main results)
        base_queryset = Resource.objects.exclude(is_placeholder=True)
        
        # Apply same access control as get_queryset
        if not self.request.user.is_authenticated:
            base_queryset = base_queryset.filter(
                public_access_level=PublicAccessLevel.PUBLIC,
                is_public_approved=True
            )
        elif not self.request.user.has_perm('metadata.view_all_resources'):
            base_queryset = base_queryset.filter(
                public_access_level__in=[
                    PublicAccessLevel.PUBLIC, 
                    PublicAccessLevel.RESTRICTED
                ]
            )
        
        # Get semantic statistics
        semantic_stats = {}
        if rdf_type:
            # Count semantic classes (distinct types used in rdf:type triples)
            semantic_stats['semantic_classes'] = Triple.objects.filter(
                predicate=rdf_type,
                object__in=base_queryset
            ).values('object').distinct().count()
            
            # Count typed instances (resources that have rdf:type)
            semantic_stats['typed_instances'] = Triple.objects.filter(
                predicate=rdf_type,
                subject__in=base_queryset
            ).values('subject').distinct().count()
        else:
            semantic_stats['semantic_classes'] = 0
            semantic_stats['typed_instances'] = 0
            
        # Count semantic properties (distinct predicates used)
        semantic_stats['semantic_properties'] = Triple.objects.filter(
            predicate__in=base_queryset
        ).values('predicate').distinct().count()
        
        # Total accessible resources
        semantic_stats['total_resources'] = base_queryset.count()
        
        # Total triples involving accessible resources
        semantic_stats['total_triples'] = Triple.objects.filter(
            Q(subject__in=base_queryset) |
            Q(predicate__in=base_queryset) |
            Q(object__in=base_queryset)
        ).count()
        
        return semantic_stats

class ResourceDetailView(DetailView):
    """HTMX-powered resource detail view"""
    model = Resource
    template_name = 'metadata/resource_detail.html'
    context_object_name = 'resource'
    
    def get_queryset(self):
        """Get resources with appropriate access control."""
        # Start with all resources
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
        
        # Get triple relationships
        context['subject_triples'] = Triple.objects.filter(
            subject=resource
        ).select_related('predicate', 'object')[:10]
        
        context['predicate_triples'] = Triple.objects.filter(
            predicate=resource
        ).select_related('subject', 'object')[:10]
        
        context['object_triples'] = Triple.objects.filter(
            object=resource
        ).select_related('subject', 'predicate')[:10]
        
        # Get counts
        context['subject_count'] = resource.subject_triples.count()
        context['predicate_count'] = resource.predicate_triples.count()
        context['object_count'] = resource.object_triples.count()
        
        # For literals, get organization usage breakdown
        if resource.resource_type == ResourceType.LITERAL:
            from django.db.models import Count
            from arkumu.users.models import Organization
            
            context['literal_org_usage'] = (
                Organization.objects
                .filter(triple__object=resource)
                .annotate(usage_count=Count('triple'))
                .order_by('-usage_count', 'name')
            )
        
        return context

@method_decorator(cache_page(60 * 5), name='dispatch')  # 5 minute cache
class DataExplorerResultsView(DataExplorerView):
    """HTMX endpoint for filtered results"""
    template_name = 'metadata/data_explorer_results.html'