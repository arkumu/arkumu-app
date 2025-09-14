from django.urls import path
from django.views.generic import TemplateView
from django.contrib.auth.decorators import login_required

from .views import (
    CatalogOverviewView,
    HarmonizedResourceListView,
    HarmonizedResourceDetailView,
    HarmonizedSearchView,
    LiveSearchFilterView
)
from .views_explorer import (
    CatalogExplorerView,
    CatalogExplorerAPIView
)

app_name = 'catalog'

urlpatterns = [
    # Main catalog views - redirect to search as primary interface
    path('', HarmonizedSearchView.as_view(), name='overview'),
    path('resources/', HarmonizedResourceListView.as_view(), name='resource_list'),
    path('resources/<path:resource_uri>/', HarmonizedResourceDetailView.as_view(), name='resource_detail'),
    path('search/', HarmonizedSearchView.as_view(), name='search'),
    path('live-filter/', LiveSearchFilterView.as_view(), name='live_filter'),
    
    # Type-specific views
    path('projects/', HarmonizedResourceListView.as_view(), {'resource_type': 'Project'}, name='projects'),  
    path('events/', HarmonizedResourceListView.as_view(), {'resource_type': 'Event'}, name='events'),
    path('persons/', HarmonizedResourceListView.as_view(), {'resource_type': 'Person'}, name='persons'),
    path('organizations/', HarmonizedResourceListView.as_view(), {'resource_type': 'Organization'}, name='organizations'),
    path('documents/', HarmonizedResourceListView.as_view(), {'resource_type': 'Document'}, name='documents'),
    
    # Organization-specific views
    path('org/<str:org_code>/', HarmonizedResourceListView.as_view(), name='org_resources'),
    
    # Design showcase pages with local catalog templates - login required
    path('design/', login_required(TemplateView.as_view(template_name="catalog/design.html")), name='design'),
    path('components/', login_required(TemplateView.as_view(template_name="catalog/components.html")), name='components'),
    path('documentation/', login_required(TemplateView.as_view(template_name="catalog/documentation.html")), name='documentation'),
    path('projekt/', login_required(TemplateView.as_view(template_name="catalog/projekt.html")), name='projekt'),

    # Development/Explorer views for testing faceted search
    path('explorer/', CatalogExplorerView.as_view(), name='explorer'),
    path('explorer/api/', CatalogExplorerAPIView.as_view(), name='explorer_api'),
]