from django.urls import path, include
from django.conf import settings
from rest_framework.routers import DefaultRouter, SimpleRouter

from arkumu.rest.views.import_viewsets import ImportViewSet, TestingViewSet
from arkumu.rest.views.upload_viewsets import UploadViewSet

app_name = 'rest'

# Create a router based on debug mode
router = DefaultRouter() if settings.DEBUG else SimpleRouter()

# Register ViewSets
router.register(r'import', ImportViewSet, basename='import')
router.register(r'testing', TestingViewSet, basename='testing')
router.register(r'upload', UploadViewSet, basename='upload')

urlpatterns = [
    # Include router URLs
    path('', include(router.urls)),
] 