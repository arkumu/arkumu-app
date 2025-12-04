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
    ACTOR_ROLE_PREDICATES: Tuple[str, ...] = (
        CardURIs.ROLE_GERMAN_NAME,
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

        if backend in ("db", "graph"):
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
                self._add_role_fields(card, uri)
                cards.append(card)
                ProjectCardCache.set(uri, card)

        return cards, total

    def _add_role_fields(self, card: dict, uri: str) -> None:
        """Add role fields to card dictionary."""
        # Extract actor names from card
        actor_names = []
        for i in range(1, 5):
            name_key = f"contributor{i}_name"
            if name_key in card and card[name_key]:
                actor_names.append(card[name_key])

        if not actor_names:
            return

        # Get roles for these actors in this project
        roles = self._get_roles_for_project(uri, actor_names)

        # Add roles to card
        for i, name in enumerate(actor_names):
            role = roles.get(name, "")
            card[f"contributor{i+1}_role"] = role

    def _get_roles_for_project(self, uri: str, actor_names: List[str]) -> dict:
        """Get roles for actors in a specific project."""
        roles = {}
        project_resource = Resource.objects.filter(uri=uri).first()
        if not project_resource:
            return roles

        # Get events for this project
        event_ids = Triple.objects.filter(
            subject=project_resource,
            predicate__uri=CardURIs.EVENT
        ).values_list('object_id', flat=True)

        if not event_ids:
            return roles

        # Get actor-event links
        actor_link_ids = Triple.objects.filter(
            subject_id__in=event_ids,
            predicate__uri=CardURIs.ACTOR_IN_EVENT
        ).values_list('object_id', flat=True)

        if not actor_link_ids:
            return roles

        # Get roles for these actor-event links
        role_triples = Triple.objects.filter(
            subject_id__in=actor_link_ids,
            predicate__uri=CardURIs.ROLE_LINK
        ).select_related('object')

        # Map actor names to roles
        for triple in role_triples:
            role_name = triple.object.value if triple.object else ""
            # Find the actor name associated with this role
            actor_triple = Triple.objects.filter(
                subject=triple.subject,
                predicate__uri=CardURIs.ACTOR_LINK
            ).select_related('object').first()

            if actor_triple and actor_triple.object and actor_triple.object.value in actor_names:
                roles[actor_triple.object.value] = role_name

        return roles

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
                # Fetch URIs with their org codes to batch schema lookups
                uri_org_pairs = list(
                    Resource.objects.filter(id__in=project_ids)
                    .select_related("organization")
                    .values_list("uri", "organization__code")
                )

                # Pre-cache schemas by org to avoid repeated lookups
                schema_cache: dict = {}
                schema_service = self.detail_service.snapshot_service.schema_service
                for _, org_code in uri_org_pairs:
                    if org_code and org_code not in schema_cache:
                        try:
                            schema_cache[org_code] = schema_service.get_card_schema(org_code)
                        except Exception:
                            pass

                for uri, org_code in uri_org_pairs:
                    if ProjectCardCache.get(uri):
                        continue
                    cached_schema = schema_cache.get(org_code) if org_code else None
                    record = self.detail_service.get_record(uri, card_schema=cached_schema)
                    if record:
                        card = record.to_card_dict()

                        self._add_role_fields(card, uri)
                        ProjectCardCache.set(uri, card)
            except OperationalError:
                logger.warning("ProjectCardSearchService: preload skipped (DB not ready)")
            except Exception:
                logger.exception("ProjectCardSearchService: preload failed")
            finally:
                self._preload_in_progress = False

        threading.Thread(target=_preload, daemon=True).start()
