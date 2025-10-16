"""
Service layer for the project overview workspace listing.

Provides annotated project querysets, filter parsing helpers, relationship
expansion, and publish/unpublish orchestration for the HTMX management UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Optional, Sequence, Tuple
from uuid import UUID

from django.core.exceptions import PermissionDenied
from django.db.models import (
    BooleanField,
    Case,
    CharField,
    Count,
    Exists,
    IntegerField,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Value,
    When,
)
from django.db.models.functions import Coalesce, Cast, Substr
from django.utils import timezone

from arkumu.metadata.canonical import canonical_uri, predicate_candidates
from arkumu.metadata.models.resource import PublicAccessLevel, Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.users.models import User


IS_PART_OF_URI = "http://purl.org/dc/terms/isPartOf"

EVENT_PREDICATE_URIS: Tuple[str, ...] = (canonical_uri("event"),)
DIGITAL_PREDICATE_URIS: Tuple[str, ...] = (canonical_uri("digital_object"),)
ACTOR_DIRECT_PREDICATE_URIS: Tuple[str, ...] = tuple(
    predicate_candidates("project_actor", canonical_uri("actor"))
)
ACTOR_IN_EVENT_URI = canonical_uri("actor_in_event")
EVENT_START_LITERAL_URIS: Tuple[str, ...] = (
    "http://arkumu.org/data/properties/ereignisbeginn",
)
EVENT_END_LITERAL_URIS: Tuple[str, ...] = (
    "http://arkumu.org/data/properties/ereignisende",
)


STATUS_LABELS = {
    "blocked": "Blockiert",
    "pending": "Wartet auf Freigabe",
    "draft": "Entwurf",
    "published": "Veröffentlicht",
}

STATUS_BADGE_STYLES = {
    "blocked": "badge-error",
    "pending": "badge-warning",
    "draft": "badge-ghost",
    "published": "badge-success",
}


@dataclass(frozen=True)
class ProjectWorkspaceFilters:
    """Normalized filters extracted from query parameters or caller input."""

    search: Optional[str] = None
    organization_code: Optional[str] = None
    dataset: Optional[str] = None
    statuses: Tuple[str, ...] = ()
    has_events: Optional[bool] = None
    has_actors: Optional[bool] = None
    has_digital: Optional[bool] = None
    year_start: Optional[int] = None
    year_end: Optional[int] = None
    updated_after: Optional[datetime] = None
    page: int = 1
    page_size: int = 25

    @classmethod
    def from_query_params(cls, params: dict[str, str]) -> "ProjectWorkspaceFilters":
        """Parse raw query params into a strongly typed filter object."""

        def _parse_bool(value: Optional[str]) -> Optional[bool]:
            if value is None or value == "":
                return None
            if value.lower() in {"1", "true", "yes", "on"}:
                return True
            if value.lower() in {"0", "false", "no", "off"}:
                return False
            return None

        def _parse_int(value: Optional[str]) -> Optional[int]:
            if value is None or value == "":
                return None
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
            if not value:
                return None
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None

        raw_status = params.get("status") or params.get("statuses")
        statuses: Tuple[str, ...]
        if raw_status:
            tokens = [token.strip().lower() for token in raw_status.split(",")]
            statuses = tuple(sorted({token for token in tokens if token in STATUS_LABELS}))
        else:
            statuses = ()

        return cls(
            search=(params.get("q") or params.get("search") or None),
            organization_code=params.get("organization") or None,
            statuses=statuses,
            dataset=params.get("dataset") or None,
            has_events=_parse_bool(params.get("has_events")),
            has_actors=_parse_bool(params.get("has_actors")),
            has_digital=_parse_bool(params.get("has_digital")),
            year_start=_parse_int(params.get("year_start")),
            year_end=_parse_int(params.get("year_end")),
            updated_after=_parse_datetime(params.get("updated_after")),
            page=max(1, _parse_int(params.get("page")) or 1),
            page_size=min(max(1, _parse_int(params.get("page_size")) or 25), 100),
        )


def _predicate_filter(path: str, uris: Sequence[str]) -> Q:
    """Return a predicate filter that matches canonical or literal URIs."""

    return Q(**{f"{path}__predicate__canonical_uri__in": uris}) | Q(
        **{f"{path}__predicate__uri__in": uris}
    )


def _triple_predicate_filter(uris: Sequence[str]) -> Q:
    """Predicate filter for direct Triple querysets."""

    return Q(predicate__canonical_uri__in=uris) | Q(predicate__uri__in=uris)


class ProjectWorkspaceListingService:
    """Aggregate entity metadata for the workspace overview."""

    DEFAULT_DATASET = "Projekt"

    def __init__(self, user: User, dataset_name: Optional[str] = None) -> None:
        self.user = user
        self._set_dataset(dataset_name or self.DEFAULT_DATASET)

    def _set_dataset(self, dataset_name: str) -> None:
        self.dataset_name = dataset_name
        self._dataset_name_lower = dataset_name.lower()
        self._is_project_dataset = self._dataset_name_lower == self.DEFAULT_DATASET.lower()

    # ------------------------------------------------------------------ #
    # Query construction
    # ------------------------------------------------------------------ #
    def get_queryset(self, filters: ProjectWorkspaceFilters) -> QuerySet[Resource]:
        """
        Return annotated project queryset suitable for pagination.
        """

        if filters.dataset:
            self._set_dataset(filters.dataset)

        queryset = (
            Resource.objects.filter(resource_type=ResourceType.ENTITY)
            .filter(subject_triples__predicate__uri=IS_PART_OF_URI)
            .filter(self._dataset_filter())
            .distinct()
            .select_related("organization", "public_approved_by")
        )

        queryset = self._apply_access_scope(queryset, filters)
        queryset = self._annotate_metrics(queryset)
        queryset = self._apply_filters(queryset, filters)

        return queryset.order_by("-updated_at", "uri")

    # ------------------------------------------------------------------ #
    # Publishing orchestration
    # ------------------------------------------------------------------ #
    def publish(self, project: Resource) -> Resource:
        """Approve a project for public catalog display."""

        self._validate_resource(project)

        if not self.user.has_role_permission("can_transfer_to_public"):
            raise PermissionDenied("Dir fehlen die Rechte zum Veröffentlichen.")
        if not self.user.has_role_permission("can_approve_public_access"):
            raise PermissionDenied("Dir fehlen die Freigabe-Rechte für den öffentlichen Katalog.")
        if project.is_externally_linked:
            raise PermissionDenied("Projekt ist extern verknüpft und kann nicht veröffentlicht werden.")

        now = timezone.now()
        project.public_access_level = PublicAccessLevel.PUBLIC
        project.is_public_approved = True
        project.public_approved_at = now
        project.public_approved_by = self.user
        project.is_public = True
        project.save(
            update_fields=[
                "public_access_level",
                "is_public_approved",
                "public_approved_at",
                "public_approved_by",
                "is_public",
                "updated_at",
            ]
        )

        if self._is_project_dataset:
            self._schedule_snapshot_refresh()
        return project

    def unpublish(self, project: Resource) -> Resource:
        """Revert a project back to restricted workspace visibility."""

        self._validate_resource(project)

        if not self.user.has_role_permission("can_transfer_to_public"):
            raise PermissionDenied("Dir fehlen die Rechte zum Entveröffentlichen.")
        if not self.user.has_role_permission("can_approve_public_access"):
            raise PermissionDenied("Dir fehlen die Freigabe-Rechte für den öffentlichen Katalog.")
        if project.is_externally_linked:
            raise PermissionDenied("Projekt ist extern verknüpft und kann nicht entveröffentlicht werden.")

        project.public_access_level = PublicAccessLevel.RESTRICTED
        project.is_public_approved = False
        project.public_approved_at = None
        project.public_approved_by = None
        project.is_public = False
        project.save(
            update_fields=[
                "public_access_level",
                "is_public_approved",
                "public_approved_at",
                "public_approved_by",
                "is_public",
                "updated_at",
            ]
        )

        if self._is_project_dataset:
            self._schedule_snapshot_refresh()
        return project

    # ------------------------------------------------------------------ #
    # Detail helpers
    # ------------------------------------------------------------------ #
    def project_from_id(self, project_id: UUID) -> Resource:
        """Return project resource ensuring dataset membership."""

        project = Resource.objects.select_related("organization").filter(id=project_id).first()
        if not project:
            raise PermissionDenied("Projekt wurde nicht gefunden.")
        self._validate_resource(project)
        if not project.can_user_view(self.user):
            raise PermissionDenied("Dir fehlt die Berechtigung für dieses Projekt.")
        return project

    def list_events(self, project: Resource) -> List[dict]:
        """Return detailed event metadata for the project detail drawer."""

        if not self._is_project_dataset:
            return []

        event_triples = (
            Triple.objects.filter(
                subject=project,
            )
            .filter(_predicate_filter("predicate", EVENT_PREDICATE_URIS))
            .select_related("object")
        )

        events: List[dict] = []
        for triple in event_triples:
            event = triple.object
            if event is None:
                continue

            event_data = {
                "id": str(event.id),
                "uri": event.uri,
                "title": self._first_literal(event, ("http://arkumu.org/data/properties/ereignisname",)),
                "start": self._first_literal(
                    event, ("http://arkumu.org/data/properties/ereignisbeginn",)
                ),
                "end": self._first_literal(
                    event, ("http://arkumu.org/data/properties/ereignisende",)
                ),
                "actors": self._collect_event_actors(event),
                "digital_objects": self._collect_event_digital_objects(event),
            }

            if not event_data["title"]:
                event_data["title"] = event.name or event.value or event.uri
            events.append(event_data)

        return events

    def list_digital_objects(self, project: Resource) -> List[dict]:
        """Return digital objects directly linked from the project."""

        if not self._is_project_dataset:
            return []

        triples = (
            Triple.objects.filter(subject=project)
            .filter(_predicate_filter("predicate", DIGITAL_PREDICATE_URIS))
            .select_related("object")
        )
        results: List[dict] = []
        for triple in triples:
            obj = triple.object
            if obj is None:
                continue
            results.append(
                {
                    "id": str(obj.id),
                    "uri": obj.uri,
                    "label": obj.name or obj.value or obj.uri,
                }
            )
        return results

    def populate_actor_counts(self, projects: Sequence[Resource]) -> None:
        """Hydrate actor counts for the provided project resources."""

        if not self._is_project_dataset:
            for project in projects:
                project.actors_count = getattr(project, "actors_count", 0)
                project.has_actor_edges = getattr(project, "has_actor_edges", False)
            return

        project_ids = [project.id for project in projects if getattr(project, "id", None)]
        if not project_ids:
            return

        direct_counts = (
            Triple.objects.filter(subject_id__in=project_ids)
            .filter(_triple_predicate_filter(ACTOR_DIRECT_PREDICATE_URIS))
            .filter(object__resource_type=ResourceType.ENTITY)
            .values("subject_id")
            .annotate(total=Count("object_id", distinct=True))
        )
        direct_map = {row["subject_id"]: row["total"] for row in direct_counts}

        event_counts = (
            Triple.objects.filter(_triple_predicate_filter((ACTOR_IN_EVENT_URI,)))
            .filter(object__resource_type=ResourceType.ENTITY)
            .filter(
                Q(subject__object_triples__predicate__canonical_uri__in=EVENT_PREDICATE_URIS)
                | Q(subject__object_triples__predicate__uri__in=EVENT_PREDICATE_URIS)
            )
            .filter(subject__object_triples__subject_id__in=project_ids)
            .values("subject__object_triples__subject_id")
            .annotate(total=Count("object_id", distinct=True))
        )
        event_map = {
            row["subject__object_triples__subject_id"]: row["total"] for row in event_counts
        }

        for project in projects:
            total = direct_map.get(project.id, 0) + event_map.get(project.id, 0)
            project.actors_count = total
            project.has_actor_edges = project.has_actor_edges or total > 0

    # ------------------------------------------------------------------ #
    # Private utilities
    # ------------------------------------------------------------------ #
    def _dataset_filter(self) -> Q:
        dataset_ids = list(
            Resource.objects.filter(
                name__iexact=self.dataset_name, resource_type=ResourceType.IRI
            ).values_list("id", flat=True)
        )
        if dataset_ids:
            return Q(subject_triples__object_id__in=dataset_ids)
        # Fallback for freshly minted datasets where canonical name differs slightly
        slug = self.dataset_name.lower()
        return Q(subject_triples__object__name__icontains=self.dataset_name) | Q(
            subject_triples__object__uri__icontains=f"/datasets/{slug}"
        )

    def _apply_access_scope(
        self,
        queryset: QuerySet[Resource],
        filters: ProjectWorkspaceFilters,
    ) -> QuerySet[Resource]:
        """Restrict queryset to resources visible for the current user."""

        user = self.user
        if not user.is_authenticated:
            return queryset.filter(
                public_access_level=PublicAccessLevel.PUBLIC, is_public_approved=True
            )

        if user.role == "system_admin":
            return queryset

        organization_code = filters.organization_code
        if not organization_code:
            if user.organization:
                organization_code = user.organization.code

        if organization_code and organization_code != "all":
            queryset = queryset.filter(organization__code__iexact=organization_code)
        elif organization_code == "all":
            if not user.has_role_permission("can_view_cross_university_public"):
                if user.organization:
                    queryset = queryset.filter(organization=user.organization)
                else:
                    queryset = queryset.none()
        else:
            if user.organization:
                queryset = queryset.filter(organization=user.organization)

        public_filter = Q(
            public_access_level__in=[PublicAccessLevel.PUBLIC, PublicAccessLevel.RESTRICTED],
            is_public_approved=True,
        )
        if user.organization:
            org_filter = Q(organization=user.organization)
            queryset = queryset.filter(public_filter | org_filter)
        else:
            queryset = queryset.filter(public_filter)
        return queryset

    def _annotate_metrics(self, queryset: QuerySet[Resource]) -> QuerySet[Resource]:
        """Attach status flags and related entity counters."""

        integer_zero = Value(0, output_field=IntegerField())
        boolean_false = Value(False, output_field=BooleanField())

        if self._is_project_dataset:
            events_qs = (
                Triple.objects.filter(subject=OuterRef("pk"))
                .filter(_triple_predicate_filter(EVENT_PREDICATE_URIS))
                .filter(object__resource_type=ResourceType.ENTITY)
                .values()
                .annotate(total=Count("object_id", distinct=True))
                .values("total")
            )
            digital_qs = (
                Triple.objects.filter(subject=OuterRef("pk"))
                .filter(_triple_predicate_filter(DIGITAL_PREDICATE_URIS))
                .filter(object__resource_type=ResourceType.ENTITY)
                .values()
                .annotate(total=Count("object_id", distinct=True))
                .values("total")
            )
            base_event_ids = (
                Triple.objects.filter(subject=OuterRef("pk"))
                .filter(_triple_predicate_filter(EVENT_PREDICATE_URIS))
                .values("object_id")
            )
            events_expr = Coalesce(Subquery(events_qs, output_field=IntegerField()), integer_zero)
            digital_expr = Coalesce(
                Subquery(digital_qs, output_field=IntegerField()), integer_zero
            )
            direct_actor_exists = (
                Triple.objects.filter(subject=OuterRef("pk"))
                .filter(_triple_predicate_filter(ACTOR_DIRECT_PREDICATE_URIS))
                .filter(object__resource_type=ResourceType.ENTITY)
            )
            event_actor_exists = (
                Triple.objects.filter(subject__in=Subquery(base_event_ids))
                .filter(_triple_predicate_filter((ACTOR_IN_EVENT_URI,)))
                .filter(object__resource_type=ResourceType.ENTITY)
            )
            has_actor_case = Case(
                When(Exists(direct_actor_exists) | Exists(event_actor_exists), then=Value(True)),
                default=boolean_false,
                output_field=BooleanField(),
            )
        else:
            events_expr = integer_zero
            digital_expr = integer_zero
            has_actor_case = boolean_false

        status_case = Case(
            When(is_externally_linked=True, then=Value("blocked")),
            When(
                public_access_level=PublicAccessLevel.PUBLIC,
                is_public_approved=True,
                then=Value("published"),
            ),
            When(
                public_access_level=PublicAccessLevel.PUBLIC,
                is_public_approved=False,
                then=Value("pending"),
            ),
            default=Value("draft"),
            output_field=CharField(),
        )

        status_label_expr = Case(
            *[
                When(status_code=code, then=Value(label))
                for code, label in STATUS_LABELS.items()
            ],
            default=Value(STATUS_LABELS["draft"]),
            output_field=CharField(),
        )
        status_badge_expr = Case(
            *[
                When(status_code=code, then=Value(STATUS_BADGE_STYLES[code]))
                for code in STATUS_BADGE_STYLES
            ],
            default=Value(STATUS_BADGE_STYLES["draft"]),
            output_field=CharField(),
        )

        queryset = queryset.annotate(
            events_count=events_expr,
            digital_objects_count=digital_expr,
            has_actor_edges=has_actor_case,
            status_code=status_case,
        )

        queryset = queryset.annotate(
            actors_count=integer_zero,
            is_publishable=Case(
                When(status_code__in=["draft", "pending"], then=Value(True)),
                default=Value(False),
                output_field=BooleanField(),
            ),
            display_title=Coalesce("name", "value", "uri", output_field=CharField()),
            status_label=status_label_expr,
            status_css=status_badge_expr,
        )
        return queryset

    def _apply_filters(
        self,
        queryset: QuerySet[Resource],
        filters: ProjectWorkspaceFilters,
    ) -> QuerySet[Resource]:
        """Apply user-driven filters to the annotated queryset."""

        if filters.search:
            term = filters.search.strip()
            queryset = queryset.filter(
                Q(name__icontains=term)
                | Q(value__icontains=term)
                | Q(uri__icontains=term)
                | Q(display_title__icontains=term)
                | Q(subject_triples__object__value__icontains=term)
            ).distinct()

        if filters.statuses:
            queryset = queryset.filter(status_code__in=filters.statuses)

        if filters.has_events is True:
            queryset = queryset.filter(events_count__gt=0)
        elif filters.has_events is False:
            queryset = queryset.filter(events_count=0)

        if filters.has_actors is True:
            queryset = queryset.filter(has_actor_edges=True)
        elif filters.has_actors is False:
            queryset = queryset.filter(has_actor_edges=False)

        if filters.has_digital is True:
            queryset = queryset.filter(digital_objects_count__gt=0)
        elif filters.has_digital is False:
            queryset = queryset.filter(digital_objects_count=0)

        if filters.updated_after:
            queryset = queryset.filter(updated_at__gte=filters.updated_after)

        if filters.year_start is not None or filters.year_end is not None:
            queryset = queryset.filter(
                self._year_range_predicate(filters.year_start, filters.year_end)
            )

        return queryset

    def _year_range_predicate(self, year_start: Optional[int], year_end: Optional[int]) -> Q:
        """Build predicate restricting projects by event start/end ISO years."""

        if not self._is_project_dataset:
            return Q()

        if year_start is None and year_end is None:
            return Q()

        event_ids = Triple.objects.filter(
            subject=OuterRef("pk"),
        ).filter(_predicate_filter("predicate", EVENT_PREDICATE_URIS))

        base_event_ids = Subquery(event_ids.values("object_id"))

        predicates: List[Q] = []
        if year_start is not None:
            start_subquery = (
                Triple.objects.filter(
                    subject__in=base_event_ids,
                )
                .filter(
                    Q(predicate__uri__in=EVENT_START_LITERAL_URIS)
                    | Q(predicate__canonical_uri__in=EVENT_START_LITERAL_URIS)
                )
                .annotate(year=Cast(Substr("object__value", 1, 4), IntegerField()))
                .filter(year__gte=year_start)
            )
            predicates.append(Q(Exists(start_subquery)))

        if year_end is not None:
            end_subquery = (
                Triple.objects.filter(
                    subject__in=base_event_ids,
                )
                .filter(
                    Q(predicate__uri__in=EVENT_END_LITERAL_URIS)
                    | Q(predicate__canonical_uri__in=EVENT_END_LITERAL_URIS)
                )
                .annotate(year=Cast(Substr("object__value", 1, 4), IntegerField()))
                .filter(year__lte=year_end)
            )
            predicates.append(Q(Exists(end_subquery)))

        predicate = Q()
        for item in predicates:
            predicate &= item
        return predicate

    def _schedule_snapshot_refresh(self) -> None:
        """Queue a background refresh for the public snapshot."""

        try:
            from arkumu.cache.tasks import warm_cross_institutional_projects_cache

            warm_cross_institutional_projects_cache.schedule(
                delay=0, kwargs={"force_refresh": True}
            )
        except Exception:
            # Snapshot refresh is a best-effort operation; avoid blocking the UI.
            pass

    def _first_literal(self, resource: Resource, predicate_uris: Iterable[str]) -> Optional[str]:
        """Return the first literal string matching any predicate."""

        triple = (
            Triple.objects.filter(subject=resource, object__resource_type=ResourceType.LITERAL)
            .filter(
                Q(predicate__uri__in=tuple(predicate_uris))
                | Q(predicate__canonical_uri__in=tuple(predicate_uris))
            )
            .select_related("object")
            .first()
        )
        if triple and triple.object:
            return triple.object.value
        return None

    def _collect_event_actors(self, event: Resource) -> List[dict]:
        """Collect actors linked to the given event."""

        if not self._is_project_dataset:
            return []

        triples = (
            Triple.objects.filter(subject=event)
            .filter(
                Q(predicate__uri=ACTOR_IN_EVENT_URI)
                | Q(predicate__canonical_uri=ACTOR_IN_EVENT_URI)
            )
            .select_related("object")
        )
        results: List[dict] = []
        for triple in triples:
            actor = triple.object
            if not actor:
                continue
            results.append(
                {
                    "id": str(actor.id),
                    "uri": actor.uri,
                    "label": actor.name or actor.value or actor.uri,
                }
            )
        return results

    def _collect_event_digital_objects(self, event: Resource) -> List[dict]:
        """Collect digital objects linked through event nodes."""

        triples = (
            Triple.objects.filter(subject=event)
            .filter(_predicate_filter("predicate", DIGITAL_PREDICATE_URIS))
            .select_related("object")
        )
        results: List[dict] = []
        for triple in triples:
            obj = triple.object
            if obj is None:
                continue
            results.append(
                {"id": str(obj.id), "uri": obj.uri, "label": obj.name or obj.value or obj.uri}
            )
        return results

    def enrich_project_metadata(self, projects: Sequence[Resource]) -> None:
        """Extract human-readable metadata from project triples."""

        if not projects:
            return

        # Define predicate URIs for common metadata fields
        label_predicates = [
            "http://arkumu.org/data/properties/bevorzugter-titel",
            "http://arkumu.org/data/properties/titel",
            "http://purl.org/dc/terms/title",
            "http://www.w3.org/2000/01/rdf-schema#label",
        ]

        description_predicates = [
            "http://arkumu.org/data/properties/beschreibung",
            "http://purl.org/dc/terms/description",
        ]

        start_predicates = [
            "http://arkumu.org/data/properties/projektbeginn",
        ]

        end_predicates = [
            "http://arkumu.org/data/properties/projektende",
        ]

        project_ids = [p.id for p in projects]

        # Bulk fetch all relevant triples
        all_predicates = label_predicates + description_predicates + start_predicates + end_predicates
        triples = Triple.objects.filter(
            subject_id__in=project_ids,
            object__resource_type=ResourceType.LITERAL
        ).filter(
            Q(predicate__uri__in=all_predicates) |
            Q(predicate__canonical_uri__in=all_predicates)
        ).select_related('object', 'predicate')

        # Group triples by project
        project_triples = {}
        for triple in triples:
            project_triples.setdefault(triple.subject_id, []).append(triple)

        # Enrich each project
        for project in projects:
            project_triple_list = project_triples.get(project.id, [])

            # Extract title
            title = self._extract_first_literal(project_triple_list, label_predicates)
            project.display_title = title or project.name or project.uri.split('/')[-1]

            # Extract description (truncated)
            desc = self._extract_first_literal(project_triple_list, description_predicates)
            project.display_description = (desc[:150] + '...') if desc and len(desc) > 150 else desc

            # Extract dates
            project.display_start = self._extract_first_literal(project_triple_list, start_predicates)
            project.display_end = self._extract_first_literal(project_triple_list, end_predicates)

    def _extract_first_literal(self, triples: List[Triple], predicate_uris: List[str]) -> Optional[str]:
        """Extract first matching literal value from a list of triples."""
        for triple in triples:
            pred_uri = triple.predicate.canonical_uri or triple.predicate.uri
            if pred_uri in predicate_uris and triple.object:
                value = triple.object.value or getattr(triple.object, "literal_value", None)
                if value:
                    return str(value)
        return None

    def _validate_resource(self, project: Resource) -> None:
        """Ensure the resource is an entity belonging to the active dataset."""

        if project.resource_type != ResourceType.ENTITY:
            raise PermissionDenied("Nur Entitäten können verwaltet werden.")
        dataset_filter: Q
        dataset_resources = Resource.objects.filter(
            name__iexact=self.dataset_name,
            resource_type=ResourceType.IRI,
        )
        if dataset_resources.exists():
            dataset_filter = Q(predicate__uri=IS_PART_OF_URI, object__in=dataset_resources)
        else:
            dataset_filter = Q(predicate__uri=IS_PART_OF_URI)
        if not project.subject_triples.filter(dataset_filter).exists():
            raise PermissionDenied("Ressource ist keinem passenden Dataset zugeordnet.")
        if not project.can_user_view(self.user):
            raise PermissionDenied("Dir fehlt die Berechtigung für dieses Projekt.")


__all__ = [
    "ProjectWorkspaceFilters",
    "ProjectWorkspaceListingService",
    "STATUS_LABELS",
    "STATUS_BADGE_STYLES",
]
