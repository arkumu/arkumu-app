from django.urls import path
from django.views.generic import TemplateView
from django.contrib.auth.decorators import login_required

from .views.cards import GraphSearchView
from .views.catalog_view import CatalogView
from .views.project_view import ProjectTabView, ProjectView
from .views.explorer import (
    CatalogExplorerView,
    CatalogExplorerPropertiesView,
    CatalogExplorerLiteralsView
)
from arkumu.users.mixins import general_login_required

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
    path('projekt/tab/', login_required(ProjectTabView.as_view()), name='projekt_tab'),
    path('browse/', general_login_required(CatalogView.as_view()), name='browse'),
    path('components/', login_required(TemplateView.as_view(template_name="catalog/components.html")), name='components'),
    path('university/', login_required(TemplateView.as_view(template_name="catalog/university_page.html")), name='university_page'),
    path('documentation/', login_required(TemplateView.as_view(template_name="catalog/documentation.html")), name='documentation'),
    path('impressum/', login_required(TemplateView.as_view(template_name="catalog/impressum.html")), name='impressum'),
    path('datenschutz/', login_required(TemplateView.as_view(template_name="catalog/datenschutz.html")), name='datenschutz'),
    path('university_page_FUK/', login_required(TemplateView.as_view(template_name="catalog/university_pages/university_page_FUK.html")), name='university_page_FUK'),
    path('university_page_RSH/', login_required(TemplateView.as_view(template_name="catalog/university_pages/university_page_RSH.html")), name='university_page_RSH'),
]
