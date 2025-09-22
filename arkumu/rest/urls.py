from django.urls import path, include
from django.conf import settings
from rest_framework.routers import DefaultRouter, SimpleRouter

from arkumu.rest.views.import_viewsets import ImportViewSet
from arkumu.rest.views.upload_viewsets import UploadViewSet
from arkumu.rest.views.canonical_uri_viewsets import CanonicalUriMappingViewSet

app_name = 'rest'

# Create a router based on debug mode
router = DefaultRouter() if settings.DEBUG else SimpleRouter()

# Register ViewSets
if getattr(settings, 'ENABLE_IMPORT_API', False):
    router.register(r'import', ImportViewSet, basename='import')

router.register(r'upload', UploadViewSet, basename='upload')

if getattr(settings, 'ENABLE_CANONICAL_URI_API', False):
    router.register(r'canonical-uri', CanonicalUriMappingViewSet, basename='canonical-uri')

urlpatterns = [
    # Include router URLs
    path('', include(router.urls)),
] 
