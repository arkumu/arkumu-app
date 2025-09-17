from django.urls import path
from django.views.generic import TemplateView
from django.contrib.auth.decorators import login_required

from .views import (
    Card,
    ProjektShow
)
from .views_explorer import (
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

    # Design showcase pages with local catalog templates - login required
    path('search_cards', login_required(Card.search_cards), name='search_cards'),
    path('projekt', login_required(ProjektShow.projekt), name='projekt'),
    path('design/', login_required(TemplateView.as_view(template_name="catalog/design.html")), name='design'),
    path('components/', login_required(TemplateView.as_view(template_name="catalog/components.html")), name='components'),
    path('documentation/', login_required(TemplateView.as_view(template_name="catalog/documentation.html")), name='documentation'),
    #path('projekt/', login_required(TemplateView.as_view(template_name="catalog/projekt.html")), name='projekt'),
    
    # Development/Explorer views for testing faceted search
    path('explorer/', CatalogExplorerView.as_view(), name='explorer'),
    path('explorer/properties/', CatalogExplorerPropertiesView.as_view(), name='explorer_properties'),
    path('explorer/literals/', CatalogExplorerLiteralsView.as_view(), name='explorer_literals'),
]