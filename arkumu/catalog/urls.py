from django.urls import path
from django.views.generic import TemplateView
from django.contrib.auth.decorators import login_required

from .views.cards import GraphSearchView
from .views.catalog_view import CatalogView
from .views.project_view import ProjectView
from .views.explorer import (
    CatalogExplorerView,
    CatalogExplorerPropertiesView,
    CatalogExplorerLiteralsView
)

app_name = 'catalog'

urlpatterns = [
    # Explorer views - Graph-based catalog exploration
    path('', CatalogExplorerView.as_view(), name='overview'),
    path('explorer/', CatalogExplorerView.as_view(), name='explorer'),
    path('explorer/properties/', CatalogExplorerPropertiesView.as_view(), name='explorer_properties'),
    path('explorer/literals/', CatalogExplorerLiteralsView.as_view(), name='explorer_literals'),

    # Search functionality using CanonicalGraphService with canonical URIs
    path('search_cards/', login_required(GraphSearchView.as_view()), name='search_cards'),
    path('projekt/', login_required(ProjectView.as_view()), name='projekt'),
    path('browse/', login_required(CatalogView.as_view()), name='browse'),
    path('components/', login_required(TemplateView.as_view(template_name="catalog/components.html")), name='components'),
    path('documentation/', login_required(TemplateView.as_view(template_name="catalog/documentation.html")), name='documentation'),
]
