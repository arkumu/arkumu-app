"""
Catalog views using harmonization rules for unified resource browsing.
"""

from django.views.generic import ListView, DetailView, TemplateView, View
from django.shortcuts import get_object_or_404
from django.db.models import Q, F
from django.core.cache import cache
from django.http import Http404, HttpResponse
from django.template.loader import render_to_string
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.db.models import Prefetch
from django.contrib.postgres.search import TrigramSimilarity

from arkumu.users.mixins import GeneralLoginRequiredMixin
from arkumu.catalog.services.catalog_navigation_service import CatalogNavigationService
from arkumu.catalog.services.faceted_search_service import FacetedSearchService
from arkumu.metadata.models.resource import ResourceType
from arkumu.metadata.models import Resource
from arkumu.metadata.models import Triple

from time import perf_counter

from functools import singledispatchmethod

#from rapidfuzz import process


class CatalogSearchMixin:
    """Mixin for live search updates using HTMX."""
    
    def build_oob_response(self, main_html, oob_updates=None):
        """Build response with out-of-band updates."""
        if not oob_updates:
            return main_html
        
        oob_html = ""
        for target_id, content in oob_updates.items():
            oob_html += f'<div id="{target_id}" hx-swap-oob="innerHTML">{content}</div>'
        
        return f'{main_html}{oob_html}'
    
    def render_search_results_template(self, request, results, result_count, search_query, selected_type, selected_facets):
        """Render search results template."""
        context = {
            'results': results,
            'result_count': result_count,
            'search_query': search_query,
            'selected_type': selected_type,
            'selected_facets': selected_facets,
            'csrf_token': get_token(request),
        }
        
        return render_to_string(
            'catalog/partials/search_results_list.html',
            context,
            request=request
        )
    
    def render_search_sidebar_template(self, request, resource_type, all_properties, searchable_properties, facets, selected_facets, selected_search_property, available_types):
        """Render search sidebar template with dynamic properties and facets."""
        context = {
            'selected_type': resource_type,
            'all_properties': all_properties,
            'searchable_properties': searchable_properties,
            'facets': facets,
            'selected_facets': selected_facets,
            'selected_search_property': selected_search_property,
            'available_types': available_types,
            'csrf_token': get_token(request),
        }
        
        return render_to_string(
            'catalog/partials/search_sidebar.html',
            context,
            request=request
        )


class CatalogOverviewView(GeneralLoginRequiredMixin, TemplateView):
    """Dashboard showing harmonized resource counts and navigation."""
    
    template_name = 'catalog/overview.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Use caching for expensive operations
        cache_key = f'catalog_overview_{self.request.user.id}'
        cached_data = cache.get(cache_key)
        
        if cached_data:
            context.update(cached_data)
        else:
            service = CatalogNavigationService(self.request.user)
            
            # Get resource counts by type
            resource_counts = service.get_resource_counts_by_type()
            
            # Get recent projects for quick access
            recent_projects = service.get_all_projects(
                include_events=False,
                include_participants=False,
                include_documents=False
            )[:5]  # Limit to 5 for overview
            
            data = {
                'resource_counts': resource_counts,
                'recent_projects': recent_projects,
                'total_resources': sum(resource_counts.values()),
            }
            
            # Cache for 30 minutes
            cache.set(cache_key, data, 30 * 60)
            context.update(data)
        
        return context


class HarmonizedResourceListView(GeneralLoginRequiredMixin, ListView):
    """List view for harmonized resources with filtering."""
    
    template_name = 'catalog/resource_list.html'
    context_object_name = 'resources'
    paginate_by = 20
    
    def get_queryset(self):
        service = CatalogNavigationService(self.request.user)
        resource_type = self.kwargs.get('resource_type') or self.request.GET.get('type')
        org_code = self.kwargs.get('org_code') or self.request.GET.get('org')
        search_query = self.request.GET.get('q')
        
        # Handle search
        if search_query:
            # Determine resource types to search
            search_types = []
            if resource_type:
                type_mapping = {
                    'Project': service.ARKUMU_PROJECT,
                    'Event': service.ARKUMU_EVENT,
                    'Person': service.ARKUMU_PERSON,
                    'Organization': service.ARKUMU_ORGANIZATION,
                    'Document': service.ARKUMU_DOCUMENT,
                }
                search_types = [type_mapping.get(resource_type)]
            
            return service.search_resources(
                query=search_query,
                resource_types=search_types,
                limit=self.paginate_by * 10  # Allow for pagination
            )
        
        # Handle specific resource type requests
        if resource_type == 'Project':
            return service.get_all_projects(
                include_events=True,
                include_participants=True,
                include_documents=False
            )
        elif resource_type == 'Event':
            return service.get_all_events() if hasattr(service, 'get_all_events') else Resource.objects.none()
        elif resource_type == 'Person':
            return service.get_all_persons() if hasattr(service, 'get_all_persons') else Resource.objects.none()
        elif resource_type == 'Organization':
            return Resource.objects.none()  # Not implemented in original service
        elif resource_type == 'Document':
            return Resource.objects.none()  # Not implemented in original service
        
        # Default: get all projects as the primary resource type
        return service.get_all_projects(
            include_events=True,
            include_participants=True,
            include_documents=False
        )
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        service = CatalogNavigationService(self.request.user)
        
        # Add filter context
        context['current_type'] = self.kwargs.get('resource_type') or self.request.GET.get('type')
        context['current_org'] = self.kwargs.get('org_code') or self.request.GET.get('org')
        context['search_query'] = self.request.GET.get('q')
        
        # Add resource counts for navigation
        context['resource_counts'] = service.get_resource_counts_by_type()
        
        # Add available resource types
        context['resource_types'] = [
            {'key': 'Project', 'label': 'Projects', 'count': context['resource_counts'].get('projects', 0)},
            {'key': 'Event', 'label': 'Events', 'count': context['resource_counts'].get('events', 0)},
            {'key': 'Person', 'label': 'Persons', 'count': context['resource_counts'].get('persons', 0)},
            {'key': 'Organization', 'label': 'Organizations', 'count': context['resource_counts'].get('organizations', 0)},
            {'key': 'Document', 'label': 'Documents', 'count': context['resource_counts'].get('documents', 0)},
        ]
        
        return context


class HarmonizedResourceDetailView(GeneralLoginRequiredMixin, DetailView):
    """Detail view showing full resource graph."""
    
    template_name = 'catalog/resource_detail.html'
    context_object_name = 'resource'
    
    def get_object(self):
        # Get resource URI from URL path
        resource_uri = self.kwargs.get('resource_uri')
        if not resource_uri:
            raise Http404("Resource URI not provided")
        
        # Decode if needed (URLs might encode special characters)
        import urllib.parse
        resource_uri = urllib.parse.unquote(resource_uri)
        
        # Get resource with access control - authentication required
        try:
            from django.db.models import Q
            q = Q(uri=resource_uri)
            
            # Add organization filter if user has organization
            if hasattr(self.request.user, 'organization') and self.request.user.organization:
                org_filter = Q(organization=self.request.user.organization)
            else:
                org_filter = Q()
            
            public_filter = Q(
                public_access_level__in=['PUBLIC', 'RESTRICTED'],
                is_public_approved=True
            )
            
            resource = Resource.objects.filter(q & (org_filter | public_filter)).first()
            
            if not resource:
                raise Http404(f"Resource not found: {resource_uri}")
                
            return resource
            
        except Exception as e:
            raise Http404(f"Error retrieving resource: {str(e)}")
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        service = CatalogNavigationService(self.request.user)
        
        # Get full resource graph
        resource_graph = service.get_project_with_full_graph(
            self.object.uri, 
            depth=2
        )
        
        if resource_graph:
            context['resource_graph'] = resource_graph
            context['relationships'] = resource_graph.get('project', {}).get('relationships', {})
            context['related_resources'] = resource_graph.get('related_resources', {})
        
        # Add breadcrumb information
        context['breadcrumbs'] = [
            {'label': 'Catalog', 'url': '/catalog/'},
            {'label': 'Resources', 'url': '/catalog/resources/'},
            {'label': self.object.uri, 'url': None},  # Current page
        ]
        
        return context


class HarmonizedSearchView(GeneralLoginRequiredMixin, ListView):
    """Faceted search across harmonized resources."""
    
    template_name = 'catalog/search_results.html'
    context_object_name = 'results'
    paginate_by = 20
    
    def get_queryset(self):
        query = self.request.GET.get('q', '').strip()
        resource_type = self.request.GET.get('type', '').strip()
        
        service = FacetedSearchService(self.request.user)
        
        # Get facet filters
        facet_filters = {}
        for facet_key in ['projektart-calc', 'faechergruppe', 'rechtsstatus', 'originaltitel-sprache', 'eventname']:
            values = self.request.GET.getlist(facet_key)
            if values:
                facet_filters[facet_key] = values
        
        # Perform faceted search
        return service.search_with_facets(
            query=query,
            resource_type=resource_type,
            facet_filters=facet_filters,
            limit=self.paginate_by * 10  # Allow for pagination
        )
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        service = FacetedSearchService(self.request.user)
        
        # Add search context
        context['search_query'] = self.request.GET.get('q', '')
        context['selected_type'] = self.request.GET.get('type', '')
        
        # Add basic type selection
        base_service = CatalogNavigationService(self.request.user)
        context['resource_counts'] = base_service.get_resource_counts_by_type()
        context['available_types'] = [
            {'key': 'projects', 'label': 'Projects', 'count': context['resource_counts'].get('projects', 0)},
            {'key': 'events', 'label': 'Events', 'count': context['resource_counts'].get('events', 0)},
        ]
        
        # Add dynamic property data based on selected type
        selected_type = context['selected_type']
        if selected_type in ['projects', 'events']:
            # Get all properties and separate into searchable vs facetable
            all_properties = service.discover_and_cache_properties(selected_type)
            
            context['all_properties'] = all_properties  # For template access to labels
            context['searchable_properties'] = {
                key: prop_config for key, prop_config in all_properties.items()
                if prop_config['is_searchable']
            }
            
            context['facets'] = service.get_all_facet_values(selected_type)
            
            # Add currently selected search property
            context['selected_search_property'] = self.request.GET.get('search_property', 'all_properties')
            
            # Add currently selected facet values
            context['selected_facets'] = {}
            for prop_key, prop_config in all_properties.items():
                if prop_config['is_facetable']:
                    selected_values = self.request.GET.getlist(prop_key)
                    if selected_values:
                        context['selected_facets'][prop_key] = selected_values
        else:
            context['all_properties'] = {}
            context['searchable_properties'] = {}
            context['facets'] = {}
            context['selected_facets'] = {}
            context['selected_search_property'] = 'all_properties'
        
        # Add result statistics
        if hasattr(self, 'object_list') and self.object_list is not None:
            context['result_count'] = self.object_list.count() if hasattr(self.object_list, 'count') else len(self.object_list)
        else:
            context['result_count'] = 0
        
        return context


class LiveSearchFilterView(GeneralLoginRequiredMixin, CatalogSearchMixin, View):
    """HTMX endpoint for live search filtering."""
    
    def get(self, request, *args, **kwargs):
        """Handle live filter updates."""
        query = request.GET.get('q', '').strip()
        resource_type = request.GET.get('type', '').strip()
        search_property = request.GET.get('search_property', '').strip()
        
        service = FacetedSearchService(request.user)
        
        # Get all properties dynamically
        all_properties = service.discover_and_cache_properties(resource_type) if resource_type else {}
        
        # Get facet filters - only from facetable properties
        facet_filters = {}
        selected_facets = {}
        for prop_key, prop_config in all_properties.items():
            if prop_config['is_facetable']:
                values = request.GET.getlist(prop_key)
                if values:
                    facet_filters[prop_key] = values
                    selected_facets[prop_key] = values
        
        # Perform search
        results = service.search_with_facets(
            query=query,
            resource_type=resource_type,
            search_property=search_property,
            facet_filters=facet_filters,
            limit=50
        )
        
        # Get updated facets based on current filters
        facets = {}
        if resource_type in ['projects', 'events']:
            facets = service.get_all_facet_values(resource_type)
        
        # Get available types (for sidebar)
        base_service = CatalogNavigationService(request.user)
        resource_counts = base_service.get_resource_counts_by_type()
        available_types = [
            {'key': 'projects', 'label': 'Projects', 'count': resource_counts.get('projects', 0)},
            {'key': 'events', 'label': 'Events', 'count': resource_counts.get('events', 0)},
        ]
        
        # Prepare searchable properties
        searchable_properties = {
            key: prop_config for key, prop_config in all_properties.items()
            if prop_config['is_searchable']
        }
        
        # Render templates
        results_html = self.render_search_results_template(
            request, results, results.count(), query, resource_type, selected_facets
        )
        
        # Render sidebar with updated facets
        sidebar_html = self.render_search_sidebar_template(
            request, resource_type, all_properties, searchable_properties, 
            facets, selected_facets, search_property or 'all_properties', available_types
        )
        
        # Update the result count in the header
        count_html = f"""
        <div>
            <h2 class="text-xl font-semibold">
                {results.count()} result{'s' if results.count() != 1 else ''}
            </h2>
            {'<p class="text-sm text-base-content/60">Showing ' + resource_type + '</p>' if resource_type else ''}
        </div>
        """
        
        # Build OOB response with sidebar updates
        oob_updates = {
            'search-results': results_html,
            'result-count': count_html,
            'search-sidebar': sidebar_html,
        }
        
        return HttpResponse(self.build_oob_response("", oob_updates))

class Entity:
    @singledispatchmethod
    def __init__(self, arg):
        raise NotImplementedError("Not implemented for these arguments")

    @__init__.register
    def _(self, arg: Resource):
        self.uri = arg.uri
        self.init_helper(arg.id)

    @__init__.register
    def _(self, arg: Triple):
        self.uri = Resource.objects.get(id = arg.subject_id).uri
        self.init_helper(arg.subject_id)

    @__init__.register
    def _(self, arg: str):
        self.uri = arg
        subject = Resource.objects.get(uri=arg)
        self.init_helper(subject.id)

    def init_helper(self, subject_id):
        self.id = subject_id
        self.resources = {}
        for entity_field_triple in Triple.objects.filter(subject_id=subject_id):
            if Resource.objects.get(id=entity_field_triple.predicate_id).name not in self.resources:
                self.resources[Resource.objects.get(id=entity_field_triple.predicate_id).name] = [Resource.objects.get(id=entity_field_triple.object_id)]
            else:
                self.resources[Resource.objects.get(id=entity_field_triple.predicate_id).name].append(Resource.objects.get(id=entity_field_triple.object_id))
        self.properties = {}
        for entity_field_triple in Triple.objects.filter(subject_id=subject_id):
            if Resource.objects.get(id=entity_field_triple.predicate_id).name not in self.properties:
                self.properties[Resource.objects.get(id=entity_field_triple.predicate_id).name] = [Resource.objects.get(id=entity_field_triple.predicate_id)]
            else:
                self.properties[Resource.objects.get(id=entity_field_triple.predicate_id).name].append(Resource.objects.get(id=entity_field_triple.predicate_id))
        self.field_names = []
        for entity_field_triple in Triple.objects.filter(subject_id=subject_id):
            if Resource.objects.get(id=entity_field_triple.predicate_id).name not in self.field_names:
                self.field_names.append(Resource.objects.get(id=entity_field_triple.predicate_id).name)

    def __repr__(self):
        ret = {field_name : [resource.value for resource in self.resources[field_name]] if self.resources[field_name][0].resource_type == ResourceType.LITERAL else [resource.uri for resource in self.resources[field_name]] for field_name in self.field_names}
        return f"Entity with id: {self.id} \nvalues: {ret}"

    def __str__(self):
        return self.__repr__()

def split_breadcrumb(breadcrumb: str):
    return breadcrumb.split(">")[-1].strip()

def search_algo(search_string, search_fields = ["Bevorzugter Titel", "Bevorzugter Untertitel", "Schlagwort", "Beschreibung"]):
 #   title_predicates = Resource.objects.filter(name="Bevorzugter Titel")
  #  keyword_predicates = Resource.objects.filter(name="Schlagwort")
  #  description_predicates = Resource.objects.filter(name="Beschreibung")

    predicates = Resource.objects.filter(name__in=search_fields)


    query = Q()
    for predicate in predicates:
        query |= Q(predicate=predicate)

    if search_string == "":
        return  [Entity(triple) for triple in Triple.objects.filter(predicate=Resource.objects.filter(name="Bevorzugter Titel").last()).all()[:10]]
    
   # all_predicates = list(title_predicates) + list(keyword_predicates) + list(description_predicates)


    results = Triple.objects.filter(query).annotate(
        text_value=F('object__value')  # Get the actual text value
    ).annotate(
        similarity=TrigramSimilarity('text_value', search_string)
    ).filter(
        similarity__gt=0.1
    ).order_by('-similarity')[:10]
    
    return [Entity(triple) for triple in results]



# Hier wäre hier möglicher weise besonder gut
class Projekt_Entity:
    
    def __init__(self, proj: Entity):
        self.proj = proj

    @property
    def institution(self):
        return Entity(self.proj.resources["Einliefernde Hochschule"][0]).resources["Deutscher Name der Einliefernden Hochschule"][0].value

    @property
    def title(self):
        return self.proj.resources["Bevorzugter Titel"][0].value
        
    @property
    def subtitle(self):
        if "Bevorzugter Untertitel" in self.proj.resources:
            return self.proj.resources["Bevorzugter Untertitel"][0].value
        else:
            return ""

    @property
    def uri(self):
        return self.proj.uri
    
    def __calcActor(self):
        pred_im_ereignis = Im_ereignis_singleton().get_pred_im_ereignis(self.uri.split("/")[4])
        self.akteur_role_dict = {}
        self.min_date = 99999999999999
        self.max_date = -99999999999999
        if "Ereignis" in self.proj.resources:
            for ereignis_resource in self.proj.resources["Ereignis"]:
                
                ereignis = Entity(ereignis_resource)
                if "Ereignisbeginn" in ereignis.resources:
                    self.min_date = min(self.min_date, int(ereignis.resources["Ereignisbeginn"][0].value.split('-')[0]))
                if "Ereignisende" in ereignis.resources:
                    self.max_date = max(self.max_date, int(ereignis.resources["Ereignisende"][0].value.split('-')[0]))

                #these are needed as a work-around until cross table traversal is fixed
                #pred_im_ereignis = Resource.objects.get(uri=f"http://arkumu.org/data/{resource.uri.split("/")[4]}/properties/im-ereignis")
                triples_cross_table = Triple.objects.filter(predicate_id=pred_im_ereignis.id, object_id=ereignis.id)


                akteur_ereignis_cross_entries = [Entity(triple) for triple in triples_cross_table]

                for cross_entry in akteur_ereignis_cross_entries:
                    # Extract Akteur entity

                    akteur = Entity(cross_entry.resources["AkteurIn im Ereignis"][0])


                    # Process roles
                    rollen_entities = [
                        Entity(rolle) for rolle in cross_entry.resources["Rollen der AkteurIn im Ereignis"]
                    ]

                    rollen_names = []
                    for rolle in rollen_entities:
                        if "Deutscher Name der Rolle (Breadcrumb)" in rolle.resources:
                            rollen_names.append(split_breadcrumb(rolle.resources["Deutscher Name der Rolle (Breadcrumb)"][0].value))

                    if akteur.resources["Deutscher Name"][0].value not in self.akteur_role_dict:
                        self.akteur_role_dict[akteur.resources["Deutscher Name"][0].value] = set(rollen_names)
                    else:
                        self.akteur_role_dict[akteur.resources["Deutscher Name"][0].value] |= set(rollen_names)

    @property
    def date_range(self):
        if "min_date" not in self.__dict__ or "max_date" not in self.__dict__:
            self.__calcActor()

        if self.min_date == 99999999999999 and self.max_date == -99999999999999:
            return  "?"
        else: 
            return f"{self.min_date if self.min_date != 99999999999999 else "?"} bis {self.max_date if self.max_date != -99999999999999 else "?"}" if self.min_date != self.max_date else f"{self.min_date}"
        
    @property
    def authors(self):
        if "akteur_role_dict" not in self.__dict__:
            self.__calcActor()
        return self.akteur_role_dict

    @property
    def categories(self):
        project_categories = [Entity(proj_cat) for proj_cat in project.resources["Projektkategorie"]]
        return [split_breadcrumb(category.resources["Deutscher Name der Projektkategorie (Breadcrumb)"][0].value) for category in project_categories]
        

class Im_ereignis_singleton:
    _instance = None
    

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.data = {}
        return cls._instance

    def get_pred_im_ereignis(self, str):
        if str not in self.data:
                self.data.update({str: Resource.objects.get(uri=f"http://arkumu.org/data/{str}/properties/im-ereignis")})
        return self.data[str]
    
        
class DesignSearch:




    def design_search_results(request):
        query = request.GET.get('query', None)

       # triple = [ob.__dict__ for ob in Triple.objects.all()[:5]]
       # resource = [ob.__dict__ for ob in Resource.objects.all()[:5]]


        #TODO Python fixen das es schneller wird

     #  resource = Resource.objects.filter(name="Bevorzugter Titel").last()
      #  triples = Triple.objects.filter(predicate__id=resource.id)[:5]
       # projects = [Entity(triple) for triple in triples]
      #  prt2 = f"{search_algo(query)}"
        projects = search_algo(query)
    #    temp = resource
        results_ret = []
        for project in projects:
            resource = Resource.objects.get(id=project.id)
            source = Entity(project.resources["Einliefernde Hochschule"][0])

            source_name = source.resources["Deutscher Name der Einliefernden Hochschule"][0].value
            uri = "../projekt?projekt=" + resource.uri
            title = project.resources["Bevorzugter Titel"][0].value
            subtitle = ""
            try:
                subtitle = project.resources["Bevorzugter Untertitel"][0].value
            except: 
                pass
            results_temp_1 = {
                    "image":"images/main/card_1.png",
                    "institution":source_name,
                    "title":title,
                    "subtitle":subtitle,
                    "uri": uri
                    }
            results_temp_2 = {}

            

            pred_im_ereignis = Im_ereignis_singleton().get_pred_im_ereignis(resource.uri.split("/")[4])
            akteur_role_dict = {}
            min_date = 99999999999999
            max_date = -99999999999999
            if "Ereignis" in project.resources:
                for ereignis_resource in project.resources["Ereignis"]:
                    
                    ereignis = Entity(ereignis_resource)
                    if "Ereignisbeginn" in ereignis.resources:
                        min_date = min(min_date,int(ereignis.resources["Ereignisbeginn"][0].value.split('-')[0]))
                    if "Ereignisende" in ereignis.resources:
                        max_date = max(max_date, int(ereignis.resources["Ereignisende"][0].value.split('-')[0]))

                    #these are needed as a work-around until cross table traversal is fixed
                    #pred_im_ereignis = Resource.objects.get(uri=f"http://arkumu.org/data/{resource.uri.split("/")[4]}/properties/im-ereignis")
                    triples_cross_table = Triple.objects.filter(predicate_id=pred_im_ereignis.id, object_id=ereignis.id)


                    akteur_ereignis_cross_entries = [Entity(triple) for triple in triples_cross_table]

                    for cross_entry in akteur_ereignis_cross_entries:
                        # Extract Akteur entity

                        akteur = Entity(cross_entry.resources["AkteurIn im Ereignis"][0])


                        # Process roles
                        rollen_entities = [
                            Entity(rolle) for rolle in cross_entry.resources["Rollen der AkteurIn im Ereignis"]
                        ]

                        rollen_names = []
                        for rolle in rollen_entities:
                            if "Deutscher Name der Rolle (Breadcrumb)" in rolle.resources:
                                rollen_names.append(split_breadcrumb(rolle.resources["Deutscher Name der Rolle (Breadcrumb)"][0].value))

                        if akteur.resources["Deutscher Name"][0].value not in akteur_role_dict:
                            akteur_role_dict[akteur.resources["Deutscher Name"][0].value] = set(rollen_names)
                        else:
                            akteur_role_dict[akteur.resources["Deutscher Name"][0].value] |= set(rollen_names)

                for i, (name, value) in enumerate(akteur_role_dict.items()):
                    results_temp_2[f"contributor{i+1}_name"] = name
                    results_temp_2[f"contributor{i+1}_role"] = ", ".join(value)
                
                if (len(akteur_role_dict) > 4):
                    results_temp_2["additional_contributors"] = f"{len(akteur_role_dict)-4} weitere{'s' if len(akteur_role_dict)-4 == 1 else ''}"
            
            if min_date == 99999999999999 and max_date == -99999999999999:
                results_temp_2["year"] = "?"
            else: 
                results_temp_2["year"] = f"{min_date if min_date != 99999999999999 else "?"} bis {max_date if max_date != -99999999999999 else "?"}" if min_date != max_date else f"{min_date}"

            
            category_tags = []
            results_temp_3 = {}
            try:
                project_categories = [Entity(proj_cat) for proj_cat in project.resources["Projektkategorie"]]
                category_tags = [split_breadcrumb(category.resources["Deutscher Name der Projektkategorie (Breadcrumb)"][0].value) for category in project_categories]
                
                if (len(category_tags) > 4):
                    results_temp_3.update({
                        'additional_categories': f"{len(category_tags)-4} weitere{'r' if len(category_tags)-4 == 1 else ''}"
                    })

                for i, category in enumerate(category_tags):
                    results_temp_3.update({
                        f"category{i+1}": category
                    })
            except:
                pass
            
        
            results_temp_1.update(results_temp_2)
            results_temp_1.update(results_temp_3)
            results_ret.append(results_temp_1)
        


        # results_ret = [
        #     {"year":"2024",
        #      "image":"images/main/card_1.png",
        #      "institution":"Folkwang Universität der Kunst",
        #      "title":"Handmade in Ethiopia",
        #      "subtitle":"Projekt",
        #      "contributor1_name":"Johanna Schwer",
        #      "contributor1_role":"Betreuerin",
        #      "contributor2_name":"Judith Schanz",
        #      "contributor2_role":"Betreuerin",
        #      "contributor3_name":"Martina Allerbech",
        #      "contributor3_role":"Designerin, Beraterin",
        #      "category1":"Industrial Design",
        #      "category2":"Transformation Design",
        #      "button_text":"Projekt ansehen"
        #     },]
        context = {'query': query,
            'results': results_ret}
        
        
        return render(request, 'catalog/design_search_results.html', context)
    
class ProjektShow:
    
    def projekt(request):
        prt = "<Nothing to Print>"
        prt2 = "<Nothing to Print>"
        prt3 = "<Nothing to Print>"
        projekt_uri = request.GET.get('projekt', None)
        project_resource = Resource.objects.get(uri=projekt_uri)
        project = Entity(project_resource)
        #TODO Python fixen das es schneller wird
        
        prt3 = ""
        source = Entity(project.resources["Einliefernde Hochschule"][0])

        source_name = source.resources["Deutscher Name der Einliefernden Hochschule"][0].value

        title = project.resources["Bevorzugter Titel"][0].value
        subtitle = ""
        try:
            subtitle = project.resources["Bevorzugter Untertitel"][0].value
        except: 
            pass
        results_temp_1 = {
                "year":"2024",
                "image":"images/main/card_1.png",
                "institution":source_name,
                "title":title,
                "subtitle":subtitle
                }
        results_temp_2 = {}

        

        try:
            ereignis = Entity(project.resources["Ereignis"][0])
            pred_im_ereignis = Im_ereignis_singleton().get_pred_im_ereignis(projekt_uri.split("/")[4])
            triples_cross_table = Triple.objects.filter(predicate_id=pred_im_ereignis.id, object_id=ereignis.id)


            akteur_ereignis_cross_entries = [Entity(triple) for triple in triples_cross_table]
            results_temp_2 = {}

            for i, cross_entry in enumerate(akteur_ereignis_cross_entries, start=1):
                # Extract Akteur entity
                time1 = perf_counter()

                akteur = Entity(cross_entry.resources["AkteurIn im Ereignis"][0])

                prt3 += f"\n{perf_counter() - time1}"

                # Process roles
                rollen_entities = [
                    Entity(rolle) for rolle in cross_entry.resources["Rollen der AkteurIn im Ereignis"]
                ]

                rollen_names = [
                    split_breadcrumb(rolle.resources["Deutscher Name der Rolle (Breadcrumb)"][0].value)
                    if "Deutscher Name der Rolle (Breadcrumb)" in rolle.resources
                    else ""
                    for rolle in rollen_entities
                ]


                time1 = perf_counter()
                # Store results
                results_temp_2.update({
                    f"contributor{i}_name": akteur.resources["Deutscher Name"][0].value,
                    f"contributor{i}_role": ", ".join(rollen_names)
                })
        except BaseException as err:
            prt = err

        
        category_tags = []
        results_temp_3 = {}
        try:
            project_categories = [Entity(proj_cat) for proj_cat in project.resources["Projektkategorie"]]
            category_tags = [split_breadcrumb(category.resources["Deutscher Name der Projektkategorie (Breadcrumb)"][0].value) for category in project_categories]
            
            if (len(category_tags) > 4):
                results_temp_3.update({
                    'additional_categories': f"{len(category_tags)-4} weitere{'s' if len(category_tags)-4 == 1 else ''}"
                })

            for i, category in enumerate(category_tags):
                results_temp_3.update({
                    f"category{i+1}": category
                })
        except:
            pass
        
    
        results_temp_1.update(results_temp_2)
        results_temp_1.update(results_temp_3)
        results_ret = results_temp_1

        context = {'projekt': projekt_uri,
            'results': results_ret, "print": prt, "print2": prt2, "print3": prt3}
        
        
        return render(request, 'catalog/projekt.html', context)