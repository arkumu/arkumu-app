from django.conf import settings
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework.routers import SimpleRouter

from arkumu.users.api.views import UserViewSet
from arkumu.rest.views.import_viewsets import ImportViewSet
from arkumu.rest.views.canonical_uri_viewsets import CanonicalUriMappingViewSet
from arkumu.rest.views.catalog_viewsets import CatalogViewSet
from arkumu.rest.views.oai_viewsets import TailoredProbeViewSet

if settings.DEBUG:
    router = DefaultRouter()
    metadata_router = DefaultRouter()
else:
    router = SimpleRouter()
    metadata_router = SimpleRouter()

# User viewsets
router.register("users", UserViewSet)

# Import viewsets - explicitly set basename and viewset
if getattr(settings, "ENABLE_IMPORT_API", False):
    router.register(r'import', ImportViewSet, basename='import')

# Catalog viewsets
router.register(r'catalog', CatalogViewSet, basename='catalog')
router.register(r'oai-tailored-probe', TailoredProbeViewSet, basename='oai-tailored-probe')

# Metadata API sub-router
if getattr(settings, "ENABLE_CANONICAL_URI_API", False):
    metadata_router.register(r'canonical-uri', CanonicalUriMappingViewSet, basename='canonical-uri')

app_name = "api"
urlpatterns = [
    # Include main router URLs
    *router.urls,
    # Include metadata sub-router under /metadata/
    path('metadata/', include(metadata_router.urls)),
]
