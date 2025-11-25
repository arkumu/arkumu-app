"""DB-backed project card search to avoid snapshot scans."""

from __future__ import annotations

import logging
from typing import List, Optional, Sequence, Tuple

from django.conf import settings
from django.db.models import Q

from arkumu.catalog.services.project_views import CardURIs
from arkumu.catalog.services.project_detail_index_service import ProjectDetailIndexService
from arkumu.catalog.services.project_index_service import ProjectIndexService
from arkumu.metadata.models import Resource, ResourceType, Triple
from .project_card_cache import ProjectCardCache
from django.db import OperationalError
import threading
import time

logger = logging.getLogger(__name__)


class ProjectCardSearchService:
    """Find projects by title/subtitle/category/actor names and hydrate card dicts."""

    TITLE_PREDICATES: Tuple[str, ...] = (
        CardURIs.TITLE,
        CardURIs.SUBTITLE,
    )
    CATEGORY_LABEL_PREDICATES: Tuple[str, ...] = (
        CardURIs.CATEGORY_GERMAN_NAME,
        CardURIs.CATEGORY_SYNONYMS,
    )
    ACTOR_NAME_PREDICATES: Tuple[str, ...] = (
        CardURIs.ACTOR_GERMAN_NAME,
    )

    def __init__(self) -> None:
        self.detail_service = ProjectDetailIndexService()
        self._preload_in_progress = False

    def search_cards(
        self,
        query: Optional[str],
        *,
        org_code: Optional[str],
        page: int,
        page_size: int,
    ) -> Tuple[List[dict], int]:
        """Return card dicts and total count without using the snapshot."""
        backend = getattr(settings, "PROJECT_INDEX_BACKEND", "snapshot")

        if backend == "db":
            index_service = ProjectIndexService(backend="db")
            cards = index_service.get_cards(query=query, organ_code=org_code)
            total = len(cards)

            start = max(page - 1, 0) * page_size
            end = start + page_size
            return cards[start:end], total

        project_uris = self._search_project_uris(query, org_code=org_code)
        total = len(project_uris)

        start = max(page - 1, 0) * page_size
        end = start + page_size
        page_uris = project_uris[start:end]

        cards: List[dict] = []
        for uri in page_uris:
            cached = ProjectCardCache.get(uri)
            if cached:
                cards.append(cached)
                continue
            record = self.detail_service.get_record(uri)
            if record:
                card = record.to_card_dict()
                cards.append(card)
                ProjectCardCache.set(uri, card)

        return cards, total

    def _search_project_uris(
        self,
        query: Optional[str],
        *,
        org_code: Optional[str],
    ) -> List[str]:
        """Resolve matching project URIs via Triple/Resource queries."""
        if not query and not org_code:
            return []

        org_filter = Q()
        if org_code:
            org_filter = Q(subject__organization__code__iexact=org_code)

        # Start with title/subtitle matches (project subject -> literal)
        project_ids: List[str] = []
        if query:
            literal_ids = self._literal_ids(query)
            if literal_ids:
                title_projects = (
                    Triple.objects.filter(
                        self._predicate_filter(self.TITLE_PREDICATES),
                        object_id__in=literal_ids,
                        subject__resource_type=ResourceType.ENTITY,
                    )
                    .filter(org_filter)
                    .values_list("subject_id", flat=True)
                )
                project_ids.extend(title_projects)

                # Categories: category labels -> project category links
                category_ids = (
                    Triple.objects.filter(
                        self._predicate_filter(self.CATEGORY_LABEL_PREDICATES),
                        object_id__in=literal_ids,
                        subject__resource_type=ResourceType.ENTITY,
                    ).values_list("subject_id", flat=True)
                )
                if category_ids:
                    category_projects = (
                        Triple.objects.filter(
                            self._predicate_filter((CardURIs.CATEGORY,)),
                            object_id__in=category_ids,
                            subject__resource_type=ResourceType.ENTITY,
                        )
                        .filter(org_filter)
                        .values_list("subject_id", flat=True)
                    )
                    project_ids.extend(category_projects)

                # Actors: actor names -> actor-event links -> project events
                actor_ids = (
                    Triple.objects.filter(
                        self._predicate_filter(self.ACTOR_NAME_PREDICATES),
                        object_id__in=literal_ids,
                        subject__resource_type=ResourceType.ENTITY,
                    ).values_list("subject_id", flat=True)
                )
                if actor_ids:
                    actor_link_ids = (
                        Triple.objects.filter(
                            self._predicate_filter((CardURIs.ACTOR_IN_EVENT,)),
                            object_id__in=actor_ids,
                        ).values_list("subject_id", flat=True)
                    )
                    if actor_link_ids:
                        actor_projects = (
                            Triple.objects.filter(
                                self._predicate_filter((CardURIs.EVENT,)),
                                object_id__in=actor_link_ids,
                                subject__resource_type=ResourceType.ENTITY,
                            )
                            .filter(org_filter)
                            .values_list("subject_id", flat=True)
                        )
                        project_ids.extend(actor_projects)

        # If only org filter is present, gather all projects for that org using title predicate as anchor
        if org_code and not query:
            org_projects = (
                Triple.objects.filter(
                    self._predicate_filter(self.TITLE_PREDICATES),
                    subject__resource_type=ResourceType.ENTITY,
                )
                .filter(org_filter)
                .values_list("subject_id", flat=True)
            )
            project_ids.extend(org_projects)

        # Deduplicate while preserving original order
        seen = set()
        unique_ids: List[str] = []
        for pid in project_ids:
            if pid in seen:
                continue
            seen.add(pid)
            unique_ids.append(pid)

        if not unique_ids:
            return []

        # Resolve URIs for the project resources
        return list(
            Resource.objects.filter(id__in=unique_ids)
            .order_by("id")
            .values_list("uri", flat=True)
        )

    @staticmethod
    def _literal_ids(query: str) -> Sequence[str]:
        return list(
            Resource.objects.filter(
                resource_type=ResourceType.LITERAL,
                value__icontains=query,
            ).values_list("id", flat=True)
        )

    @staticmethod
    def _predicate_filter(predicates: Sequence[str]) -> Q:
        return Q(predicate__canonical_uri__in=predicates) | Q(predicate__uri__in=predicates)

    def preload_cache_async(self) -> None:
        """Lightweight preload of the card cache for search pages."""
        if self._preload_in_progress:
            return
        self._preload_in_progress = True

        def _preload():
            try:
                # Small delay to let DB finish startup in containerized envs
                time.sleep(1.0)
                # Fetch candidate project URIs via title predicate only to limit scope
                project_ids = (
                    Triple.objects.filter(
                        self._predicate_filter(self.TITLE_PREDICATES),
                        subject__resource_type=ResourceType.ENTITY,
                    )
                    .values_list("subject_id", flat=True)
                    .distinct()
                )
                uris = list(
                    Resource.objects.filter(id__in=project_ids).values_list("uri", flat=True)
                )
                for uri in uris:
                    if ProjectCardCache.get(uri):
                        continue
                    record = self.detail_service.get_record(uri)
                    if record:
                        ProjectCardCache.set(uri, record.to_card_dict())
            except OperationalError:
                logger.warning("ProjectCardSearchService: preload skipped (DB not ready)")
            except Exception:
                logger.exception("ProjectCardSearchService: preload failed")
            finally:
                self._preload_in_progress = False

        threading.Thread(target=_preload, daemon=True).start()
