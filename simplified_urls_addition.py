# Add these URLs to arkumu/metadata/urls.py

# Simplified Resource Management URLs (replace complex harmonization)
from arkumu.metadata.views.simplified_resource_views import (
    UnifiedResourceView, 
    ResourceDashboardView,
    search_resources,
    quick_link_resources,
    resource_link_form,
    delete_triple,
    get_predicates
)

# Add to urlpatterns:
urlpatterns = [
    # ... existing patterns ...
    
    # Simplified Resource Management
    path('resources/create/', UnifiedResourceView.as_view(), name='create_resource'),
    path('resources/dashboard/', ResourceDashboardView.as_view(), name='resource_dashboard'),
    
    # HTMX endpoints
    path('api/search-resources/', search_resources, name='search_resources'),
    path('api/quick-link/', quick_link_resources, name='quick_link_resources'),
    path('api/resources/<uuid:resource_id>/link-form/', resource_link_form, name='resource_link_form'),
    path('api/triples/<uuid:triple_id>/delete/', delete_triple, name='delete_triple'),
    path('api/predicates/', get_predicates, name='get_predicates'),
    
    # ... rest of existing patterns ...
]