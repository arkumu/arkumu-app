"""
Catalog ViewSet for REST API endpoints.
"""

import logging
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from arkumu.catalog.services.catalog_insights_service import CatalogInsightsService
from arkumu.metadata.models import Resource
from arkumu.rest.catalog_serializers import (
    KeywordSerializer,
    ProjectPreviewSerializer,
    PopularKeywordsQuerySerializer,
    RandomProjectsQuerySerializer
)

logger = logging.getLogger(__name__)


class CatalogViewSet(viewsets.GenericViewSet):
    """
    ViewSet for catalog-related endpoints.

    Provides endpoints for popular keywords and random project discovery.
    """

    # Required by DRF even though we only use custom actions
    queryset = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.catalog_service = CatalogInsightsService()

    def get_queryset(self):
        """Override to provide empty queryset since we only use custom actions."""
        return Resource.objects.none()

    @extend_schema(
        operation_id='catalog_popular_keywords',
        summary='Get popular keywords',
        description='Returns a list of popular keywords/categories sorted by usage count.',
        parameters=[
            OpenApiParameter(
                name='limit',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                default=100,
                description='Maximum number of keywords to return (default 100, max 200)'
            )
        ],
        responses={
            200: KeywordSerializer(many=True),
            400: dict
        },
        tags=['Catalog']
    )
    @action(
        detail=False,
        methods=['get'],
        url_path='keywords/popular',
        url_name='popular-keywords'
    )
    def popular_keywords(self, request):
        """
        Get popular keywords/categories from catalog data.

        Returns a list of keywords with their labels and usage counts,
        sorted by count in descending order.
        """
        # Validate query parameters
        query_serializer = PopularKeywordsQuerySerializer(data=request.query_params)
        if not query_serializer.is_valid():
            return Response(
                {"errors": query_serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        validated_data = query_serializer.validated_data
        limit = validated_data.get('limit', 100)

        try:
            # Get popular keywords from service
            keywords = self.catalog_service.get_popular_keywords(limit=limit)

            # Serialize and return
            serializer = KeywordSerializer(keywords, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error fetching popular keywords: {e}")
            return Response(
                {"error": "Failed to fetch popular keywords"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @extend_schema(
        operation_id='catalog_random_projects',
        summary='Get random projects',
        description='Returns random project preview cards with optional filters.',
        parameters=[
            OpenApiParameter(
                name='limit',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                default=10,
                description='Maximum number of projects to return (default 10, max 50)'
            ),
            OpenApiParameter(
                name='keyword_id',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Filter by keyword/category ID'
            ),
            OpenApiParameter(
                name='category',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Filter by category name'
            ),
            OpenApiParameter(
                name='university',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Filter by university'
            ),
            OpenApiParameter(
                name='year',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Filter by year'
            )
        ],
        responses={
            200: ProjectPreviewSerializer(many=True),
            400: dict
        },
        tags=['Catalog']
    )
    @action(
        detail=False,
        methods=['get'],
        url_path='projects/random',
        url_name='random-projects'
    )
    def random_projects(self, request):
        """
        Get random projects with optional filters.

        Returns a random sample of project preview cards that can be
        filtered by keyword, category, university, or year.
        """
        # Validate query parameters
        query_serializer = RandomProjectsQuerySerializer(data=request.query_params)
        if not query_serializer.is_valid():
            return Response(
                {"errors": query_serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        validated_data = query_serializer.validated_data

        try:
            # Get random projects from service
            projects = self.catalog_service.get_random_projects(
                limit=validated_data.get('limit', 10),
                keyword_id=validated_data.get('keyword_id'),
                category=validated_data.get('category'),
                university=validated_data.get('university'),
                year=validated_data.get('year')
            )

            # Serialize and return
            serializer = ProjectPreviewSerializer(projects, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except ValueError as e:
            # Handle invalid filter values
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Error fetching random projects: {e}")
            return Response(
                {"error": "Failed to fetch random projects"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )