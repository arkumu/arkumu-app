from django.shortcuts import render
from django.http import JsonResponse, HttpResponse
from django.core.paginator import Paginator
from django.db.models import Q, Count, Exists, OuterRef, Case, When, Value, CharField, Subquery, F, Prefetch
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page, cache_control
from django.views.generic import ListView, DetailView, View
from django.conf import settings
from django.core.cache import cache
from arkumu.metadata.models.resource import Resource, ResourceType, PublicAccessLevel
from arkumu.metadata.models.triples import Triple
import logging

logger = logging.getLogger(__name__)

class OptimizedDataExplorerView(ListView):
    """Optimized data explorer with reduced database queries"""
    model = Resource
    template_name = 'metadata/data_explorer.html'
    context_object_name = 'resources'
    paginate_by = 20
    
    def get_queryset(self):
        """Ultra-optimized queryset WITHOUT expensive Count queries."""
        # Cache the queryset for this request
        cache_key = f'explorer_qs_{self.request.user.id if self.request.user.is_authenticated else "anon"}_{self.request.GET.urlencode()}'
        cached_ids = cache.get(cache_key)
        
        if cached_ids and not self.request.GET.get('nocache'):
            # Return cached results
            queryset = Resource.objects.filter(id__in=cached_ids).select_related('organization')
            # Maintain order from cached IDs
            preserved = Case(*[When(pk=pk, then=pos) for pos, pk in enumerate(cached_ids)])
            return queryset.order_by(preserved)
        
        # Build base queryset - NO COUNT ANNOTATIONS for speed
        queryset = (
            Resource.objects
            .exclude(is_placeholder=True)
            .select_related('organization')  # Avoid N+1 for organization
            .only(  # Only fetch needed fields
                'id', 'uri', 'canonical_uri', 'name', 'value', 'resource_type', 
                'created_at', 'updated_at', 'is_placeholder',
                'public_access_level', 'is_public_approved',
                'organization__id', 'organization__name', 'organization__code'
            )
        )
        
        # Apply access control first (reduces dataset early)
        queryset = self._apply_access_control(queryset)
        
        # Apply filters before any annotations
        queryset = self.apply_filters(queryset)
        
        # Only add the ontology check if filtering by it
        if self.request.GET.get('externally_linked'):
            queryset = queryset.annotate(
                has_ontology_links=Exists(
                    Triple.objects.filter(
                        subject=OuterRef('pk'),
                        predicate__uri='http://www.w3.org/2002/07/owl#sameAs',
                        is_derived=True
                    )
                )
            )
        
        # Apply sorting
        queryset = self.apply_sorting(queryset)
        
        # Cache the result IDs for 60 seconds
        result_ids = list(queryset.values_list('id', flat=True)[:1000])  # Limit cache size
        cache.set(cache_key, result_ids, 60)
        
        return queryset
    
    def _apply_access_control(self, queryset):
        """Centralized access control logic."""
        # Debug mode bypass
        if settings.DEBUG and self.request.GET.get('debug') == 'true':
            return queryset
            
        if not self.request.user.is_authenticated:
            return queryset.filter(
                public_access_level=PublicAccessLevel.PUBLIC,
                is_public_approved=True
            )
        elif not self.request.user.has_perm('metadata.view_all_resources'):
            return queryset.filter(
                public_access_level__in=[
                    PublicAccessLevel.PUBLIC, 
                    PublicAccessLevel.RESTRICTED
                ]
            )
        return queryset
    
    def _get_accessible_organizations(self):
        """Cached organization list."""
        cache_key = f'org_list_{self.request.user.id if self.request.user.is_authenticated else "anon"}'
        cached = cache.get(cache_key)
        if cached:
            return cached
            
        # Use values_list to avoid model instantiation
        orgs = (
            Resource.objects
            .exclude(is_placeholder=True)
            .values_list('organization__name', flat=True)
            .distinct()
            .order_by('organization__name')
        )
        
        # Apply same access control
        base_qs = Resource.objects.exclude(is_placeholder=True)
        base_qs = self._apply_access_control(base_qs)
        orgs = (
            base_qs
            .values_list('organization__name', flat=True)
            .distinct()
            .order_by('organization__name')
        )
        
        result = list(orgs)  # Evaluate once
        cache.set(cache_key, result, 300)  # Cache for 5 minutes
        return result
    
    def apply_filters(self, queryset):
        """Optimized filtering with early returns."""
        # Type group filter first (can change base query)
        type_group = self.request.GET.get('type_group')
        if type_group == 'placeholders':
            # Special case: show only placeholders
            queryset = (
                Resource.objects
                .filter(is_placeholder=True)
                .select_related('organization')
                .only(
                    'id', 'uri', 'canonical_uri', 'name', 'value', 'resource_type',
                    'created_at', 'updated_at', 'is_placeholder',
                    'organization__id', 'organization__name'
                )
            )
            queryset = self._apply_access_control(queryset)
        elif type_group == 'identifiers':
            queryset = queryset.exclude(resource_type=ResourceType.LITERAL)
        elif type_group == 'literals':
            queryset = queryset.filter(resource_type=ResourceType.LITERAL)
        
        # Search (use full-text search if available)
        search = self.request.GET.get('search', '').strip()
        if search:
            # Consider adding PostgreSQL full-text search here
            queryset = queryset.filter(
                Q(uri__icontains=search) |
                Q(canonical_uri__icontains=search) |
                Q(name__icontains=search) |
                Q(value__icontains=search)
            )
        
        # Resource type filter
        resource_types = self.request.GET.getlist('resource_type')
        if resource_types:
            queryset = queryset.filter(resource_type__in=resource_types)
        
        # Organization filter
        organizations = self.request.GET.getlist('organization')
        if organizations:
            queryset = queryset.filter(organization__name__in=organizations)
        
        # Canonical URI status filter
        canonical_status = self.request.GET.get('canonical_status')
        if canonical_status == 'has_canonical':
            queryset = queryset.filter(canonical_uri__isnull=False)
        elif canonical_status == 'no_canonical':
            queryset = queryset.filter(canonical_uri__isnull=True)
        elif canonical_status == 'arkumu_compliant':
            # Filter for Arkumu-compliant institutions (rsh, det, fuk)
            queryset = queryset.filter(
                organization__code__iexact__in=['rsh', 'det', 'fuk']
            )
        
        # Triple usage filter (expensive - do last)
        triple_usage = self.request.GET.get('triple_usage')
        if triple_usage:
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
        
        # Ontology linking filter
        externally_linked = self.request.GET.get('externally_linked')
        if externally_linked == 'true':
            queryset = queryset.filter(has_ontology_links=True)
        elif externally_linked == 'false':
            queryset = queryset.filter(has_ontology_links=False)
        
        return queryset
    
    def apply_sorting(self, queryset):
        """Optimized sorting without count fields."""
        sort_by = self.request.GET.get('sort', 'created')
        sort_order = self.request.GET.get('order', 'desc')
        
        # Remove count-based sorts since we don't have those annotations anymore
        valid_sorts = {
            'type': 'resource_type',
            'resource': 'name',
            'organization': 'organization__name',
            'created': 'created_at',
            'updated': 'updated_at',
        }
        
        # If user tries to sort by counts, fallback to created date
        if sort_by in ['subject_count', 'predicate_count', 'object_count', 'total_triples']:
            sort_by = 'created'
            # Could show a message that count sorting requires loading all counts first
        
        if sort_by not in valid_sorts:
            sort_by = 'created'
        
        if sort_by == 'resource':
            # Use COALESCE for name fallback
            from django.db.models.functions import Coalesce
            queryset = queryset.annotate(
                sort_name=Coalesce('name', 'uri')
            )
            field = 'sort_name'
        else:
            field = valid_sorts[sort_by]
        
        if sort_order == 'desc':
            field = f'-{field}'
            
        return queryset.order_by(field)
    
    def get_context_data(self, **kwargs):
        if not hasattr(self, 'kwargs'):
            self.kwargs = {}
        context = super().get_context_data(**kwargs)
        
        # Cache filter options
        cache_key = f'filter_options_{self.request.user.id if self.request.user.is_authenticated else "anon"}'
        filter_options = cache.get(cache_key)
        
        if not filter_options:
            filter_options = {
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
            cache.set(cache_key, filter_options, 300)  # 5 minutes
        
        context['filter_options'] = filter_options
        
        # Current filters
        context['current_filters'] = {
            'search': self.request.GET.get('search', ''),
            'resource_type': self.request.GET.getlist('resource_type'),
            'type_group': self.request.GET.get('type_group'),
            'organization': self.request.GET.getlist('organization'),
            'triple_usage': self.request.GET.get('triple_usage'),
            'externally_linked': self.request.GET.get('externally_linked'),
            'canonical_status': self.request.GET.get('canonical_status'),
        }
        
        context['current_sort'] = {
            'sort': self.request.GET.get('sort', 'created'),
            'order': self.request.GET.get('order', 'desc'),
        }
        
        # Lazy load stats with HTMX
        context['load_stats_async'] = True  # Template will load via HTMX
        
        return context


class DataExplorerResultsView(OptimizedDataExplorerView):
    """HTMX endpoint for filtered results"""
    template_name = 'metadata/data_explorer_results.html'


class ResourceTripleCountsView(View):
    """HTMX endpoint for loading triple counts asynchronously."""
    
    @method_decorator(cache_control(max_age=300))  # Browser cache for 5 minutes
    def get(self, request, resource_id):
        """Return triple counts for a single resource."""
        cache_key = f'triple_counts_{resource_id}'
        counts = cache.get(cache_key)
        
        if not counts:
            try:
                resource = Resource.objects.get(id=resource_id)
                counts = {
                    'subject_count': resource.subject_triples.count(),
                    'predicate_count': resource.predicate_triples.count(),
                    'object_count': resource.object_triples.count(),
                    'total': resource.subject_triples.count() + 
                            resource.predicate_triples.count() + 
                            resource.object_triples.count()
                }
                # Cache for 5 minutes
                cache.set(cache_key, counts, 300)
            except Resource.DoesNotExist:
                counts = {'subject_count': 0, 'predicate_count': 0, 'object_count': 0, 'total': 0}
        
        # Return HTML snippet for HTMX with DaisyUI styling
        if counts['total'] > 0:
            html = f"""
            <div class="flex gap-1">
                <span class="badge badge-ghost badge-xs">S:{counts['subject_count']}</span>
                <span class="badge badge-ghost badge-xs">P:{counts['predicate_count']}</span>
                <span class="badge badge-ghost badge-xs">O:{counts['object_count']}</span>
            </div>
            """
        else:
            html = '<span class="text-xs text-base-content/30">-</span>'
        
        return HttpResponse(html)


class BatchTripleCountsView(View):
    """HTMX endpoint for loading multiple triple counts at once."""
    
    def post(self, request):
        """Load counts for multiple resources efficiently."""
        resource_ids = request.POST.getlist('resource_ids[]')
        
        if not resource_ids:
            return JsonResponse({'counts': {}})
        
        # Check cache first
        cached_counts = {}
        uncached_ids = []
        
        for res_id in resource_ids:
            cache_key = f'triple_counts_{res_id}'
            cached = cache.get(cache_key)
            if cached:
                cached_counts[res_id] = cached
            else:
                uncached_ids.append(res_id)
        
        # Batch fetch uncached counts
        if uncached_ids:
            from django.db.models import Count
            
            resources = Resource.objects.filter(
                id__in=uncached_ids
            ).annotate(
                subject_count=Count('subject_triples', distinct=True),
                predicate_count=Count('predicate_triples', distinct=True),
                object_count=Count('object_triples', distinct=True)
            ).values('id', 'subject_count', 'predicate_count', 'object_count')
            
            for res in resources:
                counts = {
                    'subject_count': res['subject_count'],
                    'predicate_count': res['predicate_count'],
                    'object_count': res['object_count'],
                    'total': res['subject_count'] + res['predicate_count'] + res['object_count']
                }
                cached_counts[str(res['id'])] = counts
                cache.set(f'triple_counts_{res["id"]}', counts, 300)
        
        return JsonResponse({'counts': cached_counts})


class SemanticStatsView(ListView):
    """Separate view for loading semantic stats asynchronously."""
    
    @method_decorator(cache_page(60))  # Cache for 1 minute
    def get(self, request):
        """Return semantic stats as JSON or HTML partial."""
        stats = self._get_semantic_stats(request)
        
        if request.headers.get('HX-Request'):
            # Return HTML partial for HTMX
            return render(request, 'metadata/partials/semantic_stats.html', {'semantic_stats': stats})
        else:
            # Return JSON
            return JsonResponse(stats)
    
    def _get_semantic_stats(self, request):
        """Optimized semantic statistics with single query."""
        cache_key = f'semantic_stats_{request.user.id if request.user.is_authenticated else "anon"}'
        cached = cache.get(cache_key)
        if cached:
            return cached
        
        # Get base accessible queryset
        base_queryset = Resource.objects.exclude(is_placeholder=True)
        
        # Apply access control
        if not request.user.is_authenticated:
            base_queryset = base_queryset.filter(
                public_access_level=PublicAccessLevel.PUBLIC,
                is_public_approved=True
            )
        elif not request.user.has_perm('metadata.view_all_resources'):
            base_queryset = base_queryset.filter(
                public_access_level__in=[
                    PublicAccessLevel.PUBLIC,
                    PublicAccessLevel.RESTRICTED
                ]
            )
        
        # Use aggregation for all stats in one query
        from django.db.models import Count, Q
        
        # Get rdf:type predicate ID once
        rdf_type_id = cache.get('rdf_type_id')
        if not rdf_type_id:
            rdf_type = Resource.objects.filter(
                uri='http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
            ).values_list('id', flat=True).first()
            if rdf_type:
                cache.set('rdf_type_id', rdf_type, 3600)  # Cache for 1 hour
                rdf_type_id = rdf_type
        
        # Single aggregation query for basic counts
        base_stats = base_queryset.aggregate(
            total_resources=Count('id'),
        )
        
        # Triple statistics with single query
        triple_stats = Triple.objects.aggregate(
            total_triples=Count('id'),
            semantic_properties=Count('predicate', distinct=True),
        )
        
        # Semantic class stats (if rdf:type exists)
        semantic_stats = {
            'total_resources': base_stats['total_resources'],
            'total_triples': triple_stats['total_triples'],
            'semantic_properties': triple_stats['semantic_properties'],
        }
        
        if rdf_type_id:
            type_stats = Triple.objects.filter(predicate_id=rdf_type_id).aggregate(
                semantic_classes=Count('object', distinct=True),
                typed_instances=Count('subject', distinct=True),
            )
            semantic_stats.update(type_stats)
        else:
            semantic_stats['semantic_classes'] = 0
            semantic_stats['typed_instances'] = 0
        
        cache.set(cache_key, semantic_stats, 60)  # Cache for 1 minute
        return semantic_stats


class OptimizedResourceDetailView(DetailView):
    """Optimized resource detail view with prefetching."""
    model = Resource
    template_name = 'metadata/resource_detail.html'
    context_object_name = 'resource'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        resource = self.object
        
        # Use prefetched data but limit to 20 for display
        context['subject_triples'] = list(resource.subject_triples.all()[:20])
        context['predicate_triples'] = list(resource.predicate_triples.all()[:20])
        context['object_triples'] = list(resource.object_triples.all()[:20])
        
        # Counts can be done with single query
        counts = Triple.objects.filter(
            Q(subject=resource) | Q(predicate=resource) | Q(object=resource)
        ).aggregate(
            subject_count=Count('id', filter=Q(subject=resource)),
            predicate_count=Count('id', filter=Q(predicate=resource)),
            object_count=Count('id', filter=Q(object=resource)),
        )
        context.update(counts)
        
        return context
    
    def get_queryset(self):
        """Optimized queryset with prefetching."""
        # KEEP THE OPTIMIZATIONS - prefetch_related is the key performance win!
        queryset = (
            Resource.objects
            .select_related('organization')
            .prefetch_related(
                Prefetch(
                    'subject_triples',
                    queryset=Triple.objects.select_related('predicate', 'object')
                ),
                Prefetch(
                    'predicate_triples', 
                    queryset=Triple.objects.select_related('subject', 'object')
                ),
                Prefetch(
                    'object_triples',
                    queryset=Triple.objects.select_related('subject', 'predicate')
                ),
            )
        )
        
        # DON'T FILTER OUT RESOURCES - this was breaking relationships!
        # The original ResourceDetailView doesn't filter, so we shouldn't either
        # Access control should be done in the view logic, not queryset
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        resource = self.object
        
        # Use prefetched data
        context['subject_triples'] = resource.subject_triples.all()[:20]
        context['predicate_triples'] = resource.predicate_triples.all()[:20]
        context['object_triples'] = resource.object_triples.all()[:20]
        
        # Counts can be done with single query
        counts = Triple.objects.filter(
            Q(subject=resource) | Q(predicate=resource) | Q(object=resource)
        ).aggregate(
            subject_count=Count('id', filter=Q(subject=resource)),
            predicate_count=Count('id', filter=Q(predicate=resource)),
            object_count=Count('id', filter=Q(object=resource)),
        )
        context.update(counts)
        
        # Load ontology links separately if needed
        context['load_ontology_async'] = True  # Load via HTMX
        
        return context