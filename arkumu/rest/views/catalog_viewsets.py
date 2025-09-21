"""Catalog ViewSet for REST API endpoints."""

import logging
from typing import Any, Dict, List, Optional
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
    ProjectRecordSerializer,
    PopularKeywordsQuerySerializer,
    RandomProjectsQuerySerializer,
    ProjectListQuerySerializer,
)
from arkumu.projects import ProjectRecord
from arkumu.projects.services import ProjectSnapshotService

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
        self._snapshot_records: Optional[List[ProjectRecord]] = None
        self._records_by_slug: Dict[str, ProjectRecord] = {}

    def get_queryset(self):
        """Override to provide empty queryset since we only use custom actions."""
        return Resource.objects.none()

    # ------------------------------------------------------------------
    # Snapshot-backed project endpoints
    # ------------------------------------------------------------------

    def _load_snapshot_records(self) -> List[ProjectRecord]:
        """Load project snapshot records once per request cycle."""
        if self._snapshot_records is None:
            snapshot = ProjectSnapshotService().get_cross_institutional_snapshot()
            self._snapshot_records = list(snapshot.projects)
            self._records_by_slug = {
                self._record_slug(record): record for record in self._snapshot_records
            }
        return self._snapshot_records

    @staticmethod
    def _record_slug(record: ProjectRecord) -> str:
        return record.uri.rstrip('/').split('/')[-1]

    def _record_to_payload(self, record: ProjectRecord) -> Dict[str, Any]:
        """Convert ProjectRecord dataclass to API payload."""
        alternative_title = (
            record.alternative_titles[0].value if record.alternative_titles else None
        )
        descriptions = [record.description] if record.description else []
        image = record.image
        if not image and record.digital_objects:
            image = record.digital_objects[0].path

        categories = [item.label for item in record.categories if item.label]
        category_slugs = [item.slug for item in record.categories if item.slug]
        actors = []
        for actor in record.actors:
            if not actor:
                continue
            if isinstance(actor, dict):
                name = actor.get('name')
                roles = actor.get('roles') or []
            else:
                name = getattr(actor, 'name', None)
                roles = list(getattr(actor, 'roles', []) or [])
            if not name:
                continue
            actors.append({
                'name': name,
                'roles': roles,
            })
        catchphrases = [item.label for item in record.catchphrases if item.label]
        digital_objects = [item.path for item in record.digital_objects if item.path]

        events: List[Dict[str, Any]] = []
        for event in record.events:
            event_actors = []
            for actor in (event.actors or []):
                if not actor:
                    continue
                if isinstance(actor, dict):
                    name = actor.get('name')
                    roles = actor.get('roles') or []
                else:
                    name = getattr(actor, 'name', None)
                    roles = list(getattr(actor, 'roles', []) or [])
                if not name:
                    continue
                event_actors.append({'name': name, 'roles': roles})

            events.append({
                'id': event.id,
                'uri': event.uri,
                'name': event.name,
                'description': event.description,
                'location': event.location,
                'location_id': event.location_id,
                'country': event.country,
                'type': event.type,
                'start': event.start,
                'end': event.end,
                'latitude': event.latitude,
                'longitude': event.longitude,
                'actors': event_actors,
            })

        return {
            'uri': record.uri,
            'slug': self._record_slug(record),
            'title': record.title,
            'subtitle': record.subtitle,
            'alternative_title': alternative_title,
            'descriptions': descriptions,
            'image': image,
            'institution': record.institution.label if record.institution else None,
            'institution_codes': record.institution_codes,
            'project_type': record.project_type.label if record.project_type else None,
            'year_range': record.year_range,
            'categories': categories,
            'category_slugs': category_slugs,
            'actors': actors,
            'catchphrases': catchphrases,
            'digital_objects': digital_objects,
            'events': events,
        }

    @extend_schema(
        operation_id='catalog_project_list',
        summary='List project snapshot records',
        description='Returns cached project records with optional filters and pagination.',
        parameters=[
            OpenApiParameter(
                name='limit',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Maximum number of projects to return (default 25, max 200)'
            ),
            OpenApiParameter(
                name='offset',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Offset into the result set for pagination'
            ),
            OpenApiParameter(
                name='institution',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Filter by institution code or label substring (case-insensitive)'
            ),
            OpenApiParameter(
                name='category',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Filter by category slug or label substring (case-insensitive)'
            ),
            OpenApiParameter(
                name='year',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Filter by project year (derived from events)'
            ),
            OpenApiParameter(
                name='search',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Case-insensitive substring search across title, subtitle and description'
            ),
        ],
        responses={
            200: ProjectRecordSerializer(many=True),
            400: dict,
        },
        tags=['Catalog']
    )
    @action(
        detail=False,
        methods=['get'],
        url_path='projects',
        url_name='projects'
    )
    def list_projects(self, request):
        query_serializer = ProjectListQuerySerializer(data=request.query_params)
        if not query_serializer.is_valid():
            return Response({'errors': query_serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        params = query_serializer.validated_data
        records = self._load_snapshot_records()

        filtered = self._filter_records(
            records,
            institution=params.get('institution'),
            category=params.get('category'),
            year=params.get('year'),
            search=params.get('search'),
        )

        offset = params.get('offset', 0)
        limit = params.get('limit', 25)
        sliced = filtered[offset: offset + limit]

        payload = [self._record_to_payload(record) for record in sliced]
        serializer = ProjectRecordSerializer(payload, many=True)
        return Response(
            {
                'count': len(filtered),
                'results': serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        operation_id='catalog_project_detail',
        summary='Retrieve project snapshot detail',
        description='Return the cached snapshot record for a given project slug.',
        parameters=[
            OpenApiParameter(
                name='slug',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.PATH,
                required=True,
                description='Project slug (last path component of the project URI)'
            ),
        ],
        responses={
            200: ProjectRecordSerializer(),
            404: dict,
        },
        tags=['Catalog']
    )
    @action(
        detail=False,
        methods=['get'],
        url_path='project/(?P<slug>[^/]+)',
        url_name='project-detail'
    )
    def project_detail(self, request, slug: str):
        records = self._load_snapshot_records()
        record = self._records_by_slug.get(slug)
        if not record:
            return Response({'error': 'Project not found'}, status=status.HTTP_404_NOT_FOUND)

        serializer = ProjectRecordSerializer(self._record_to_payload(record))
        return Response(serializer.data, status=status.HTTP_200_OK)

    def _filter_records(
        self,
        records: List[ProjectRecord],
        *,
        institution: Optional[str],
        category: Optional[str],
        year: Optional[int],
        search: Optional[str],
    ) -> List[ProjectRecord]:
        institution_filter = institution.lower().strip() if institution else None
        category_filter = category.lower().strip() if category else None
        search_filter = search.lower().strip() if search else None

        filtered: List[ProjectRecord] = []
        for record in records:
            if institution_filter:
                labels = [record.institution.label] if record.institution else []
                codes = record.institution_codes or []
                match = any(institution_filter in (label or '').lower() for label in labels)
                match = match or any(institution_filter in code.lower() for code in codes)
                if not match:
                    continue

            if category_filter:
                slugs = [item.slug or '' for item in record.categories]
                labels = [item.label or '' for item in record.categories]
                if not any(category_filter in slug.lower() for slug in slugs) and not any(
                    category_filter in label.lower() for label in labels
                ):
                    continue

            if year is not None:
                record_year = None
                if record.year_range:
                    record_year = record.year_range.split(' ')[0]
                for event in record.events:
                    if event.start:
                        record_year = event.start.split('-')[0]
                        break
                if not record_year or str(year) != str(record_year):
                    continue

            if search_filter:
                haystack = ' '.join(
                    filter(
                        None,
                        [
                            record.title,
                            record.subtitle,
                            record.description,
                            *(cp.label for cp in record.catchphrases if cp.label),
                        ],
                    )
                ).lower()
                if search_filter not in haystack:
                    continue

            filtered.append(record)

        return filtered

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
