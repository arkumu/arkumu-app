from django.conf import settings
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework.routers import SimpleRouter

from arkumu.users.api.views import UserViewSet
from arkumu.rest.views.import_viewsets import ImportViewSet, TestingViewSet
from arkumu.rest.views.canonical_uri_viewsets import CanonicalUriMappingViewSet
from arkumu.rest.views.catalog_viewsets import CatalogViewSet

if settings.DEBUG:
    router = DefaultRouter()
    metadata_router = DefaultRouter()
else:
    router = SimpleRouter()
    metadata_router = SimpleRouter()

# User viewsets
router.register("users", UserViewSet)

# Import viewsets - explicitly set basename and viewset
router.register(r'import', ImportViewSet, basename='import')
router.register(r'testing', TestingViewSet, basename='testing')

# Catalog viewsets
router.register(r'catalog', CatalogViewSet, basename='catalog')

# Metadata API sub-router
metadata_router.register(r'canonical-uri', CanonicalUriMappingViewSet, basename='canonical-uri')

app_name = "api"
urlpatterns = [
    # Include main router URLs
    *router.urls,
    # Include metadata sub-router under /metadata/
    path('metadata/', include(metadata_router.urls)),
]
