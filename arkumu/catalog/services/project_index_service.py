"""Project index service for catalog cards and detail views.

This service provides a thin abstraction over different potential backends
for project cards and detail records.

Current backends:
    - "snapshot": wraps ProjectSnapshotService and ProjectRecord (default).
    - "graph": internal, experimental backend based on CanonicalGraphService
      that builds cards directly from the canonical project graph.

Callers should only use the high-level methods so we can improve internals
without touching the views.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, TYPE_CHECKING
import logging

from django.conf import settings
from django.core.cache import cache
from django.db.models import Q

from arkumu.projects import ProjectRecord, ProjectSnapshot
from arkumu.metadata.models import Resource, PublicAccessLevel
from arkumu.metadata.services.canonical_graph_service import CanonicalGraphService
from arkumu.catalog.services.schema_manifest_service import CardSchema, CARD_SCHEMA_TEMPLATE
from arkumu.catalog.models import ProjectIndex, ProjectRecordIndex

if TYPE_CHECKING:
    # Only imported for type checking to avoid circular imports at runtime.
    from arkumu.projects.services import ProjectSnapshotService  # pragma: no cover

logger = logging.getLogger(__name__)


class ProjectIndexService:
    """High-level read API for project cards and detail records.

    The default backend is the existing ProjectSnapshotService. Future
    backends (graph-only, Polars, etc.) should keep the same public
    interface so catalog views do not depend on snapshot internals.
    """

    def __init__(
        self,
        *,
        backend: Optional[str] = None,
        snapshot_service_class: Optional[type["ProjectSnapshotService"]] = None,
    ) -> None:
        if backend is None:
            backend = getattr(settings, "PROJECT_INDEX_BACKEND", "snapshot")
        self.backend = backend
        self.snapshot_service_class = snapshot_service_class

    # ------------------------------------------------------------------
    # Snapshot-backed helpers
    # ------------------------------------------------------------------

    def get_snapshot(self, *, force_refresh: bool = False) -> ProjectSnapshot:
        """Return the current snapshot for snapshot-backed index."""
        if self.backend != "snapshot":
            raise NotImplementedError(f"Backend '{self.backend}' is not implemented yet")

        service_cls = self.snapshot_service_class
        if service_cls is None:
            # Lazy import to avoid circular dependency during Django startup.
            from arkumu.projects.services import ProjectSnapshotService as _SnapshotService

            service_cls = _SnapshotService

        service = service_cls()
        snapshot = service.get_cross_institutional_snapshot(force_refresh=force_refresh)
        return snapshot

    def _get_all_records(self, *, force_refresh: bool = False) -> List[ProjectRecord]:
        snapshot = self.get_snapshot(force_refresh=force_refresh)
        records = snapshot.projects
        logger.info(
            "ProjectIndexService: snapshot generated %s with %d projects (force_refresh=%s)",
            snapshot.generated_at.isoformat(),
            len(records),
            force_refresh,
        )
        return list(records)

    def _filter_records(
        self,
        records: Sequence[ProjectRecord],
        *,
        query: Optional[str] = None,
        organ_code: Optional[str] = None,
    ) -> List[ProjectRecord]:
        """Apply simple text and institution filters to a list of records."""

        normalized_query = (query or "").strip()
        normalized_organ = (organ_code or "").strip()

        filtered: List[ProjectRecord] = list(records)

        if normalized_query:
            filtered = [record for record in filtered if record.matches_query(normalized_query)]

        if normalized_organ:
            filtered = [record for record in filtered if record.matches_institution(normalized_organ)]

        logger.info(
            "ProjectIndexService: filtered to %d records (query='%s', organ_code='%s')",
            len(filtered),
            normalized_query,
            normalized_organ,
        )
        return filtered

    # ------------------------------------------------------------------
    # Graph-backed helpers (experimental)
    # ------------------------------------------------------------------

    def _build_card_predicate_whitelists(
        self,
        card_schema: CardSchema,
    ) -> Dict[str, List[str]]:
        """Derive simple predicate whitelists for project and neighbors."""

        project_predicates: set[str] = set()
        neighbor_predicates: set[str] = set()

        for section_name, section in card_schema.sections.items():
            for prop in section.properties.values():
                uri = getattr(prop, "canonical_uri", None)
                if not uri:
                    continue
                normalized = str(uri).strip()
                if not normalized:
                    continue
                if section_name == "project":
                    project_predicates.add(normalized)
                else:
                    neighbor_predicates.add(normalized)

        # Minimal extras for project subjects that are not explicit card properties
        extra_project_predicates: Sequence[str] = [
            # Project -> event relationship
            "http://arkumu.org/data/properties/ereignis",
        ]
        for uri in extra_project_predicates:
            normalized = str(uri).strip()
            if normalized:
                project_predicates.add(normalized)

        # Extra neighbor predicates for actor extraction
        extra_neighbor_predicates: Sequence[str] = [
            # Event -> actor junction (legacy, not in use)
            "http://arkumu.org/data/properties/akteurinnen-am-ereignis",
            # Direct event -> actor links (KHM/HMT)
            "http://arkumu.org/data/properties/akteurin-im-ereignis",
            # Direct event -> actor links (FUK)
            "http://arkumu.org/data/properties/ereignis-hat-akteurin",
            # Actor name
            "http://arkumu.org/data/properties/deutscher-name",
        ]
        for uri in extra_neighbor_predicates:
            normalized = str(uri).strip()
            if normalized:
                neighbor_predicates.add(normalized)

        return {
            "project": sorted(project_predicates),
            "neighbor": sorted(neighbor_predicates),
        }

    def _get_public_subject_ids(self, subject_ids: Sequence[str]) -> List[str]:
        """Filter project subject IDs to those approved for public display."""
        if not subject_ids:
            return []

        approved_ids = {
            str(resource_id)
            for resource_id in Resource.objects.filter(
                id__in=list(subject_ids),
                public_access_level=PublicAccessLevel.PUBLIC,
                is_public_approved=True,
            ).values_list("id", flat=True)
        }
        return sorted(approved_ids)

    @staticmethod
    def _canonical(edge: Dict[str, Any]) -> Optional[str]:
        if not edge:
            return None
        return edge.get("predicate_canonical") or edge.get("predicate_uri")

    def _first_literal(
        self,
        edges: Iterable[Dict[str, Any]],
        predicate: Optional[str],
    ) -> Optional[str]:
        if not predicate:
            return None
        for edge in edges:
            if self._canonical(edge) == predicate and edge.get("object_value"):
                return str(edge["object_value"])
        return None

    def _related_ids(
        self,
        edges: Iterable[Dict[str, Any]],
        predicate: Optional[str],
    ) -> List[str]:
        if not predicate:
            return []
        results: List[str] = []
        for edge in edges:
            if self._canonical(edge) == predicate and edge.get("object_id"):
                results.append(str(edge["object_id"]))
        return results

    @staticmethod
    def _derive_year_range_from_pairs(
        events: Iterable[Dict[str, Optional[str]]],
    ) -> Optional[str]:
        for event in events:
            start = event.get("start")
            end = event.get("end")
            if start and end:
                start_year = start.split("-")[0] if "-" in start else start
                end_year = end.split("-")[0] if "-" in end else end
                return start_year if start_year == end_year else f"{start_year} bis {end_year}"
            if start:
                return start.split("-")[0] if "-" in start else start
            if end:
                return end.split("-")[0] if "-" in end else end
        return None

    def _build_cards_from_graph(
        self,
        graph: Dict[str, Any],
        card_schema: CardSchema,
    ) -> List[Dict[str, Any]]:
        """Project a canonical project graph directly into card dictionaries."""

        nodes: Dict[str, Dict[str, Any]] = graph.get("nodes", {}) or {}
        edges: List[Dict[str, Any]] = graph.get("edges", []) or []
        subject_ids: Sequence[str] = graph.get("subjects", []) or []

        # Restrict to public projects only
        public_subjects = set(self._get_public_subject_ids(subject_ids))
        if not public_subjects:
            return []

        edges_by_subject: Dict[str, List[Dict[str, Any]]] = {}
        for edge in edges:
            subject_id = (
                edge.get("subject_id")
                or edge.get("subject")
                or edge.get("s")
            )
            if subject_id is None:
                continue
            key = str(subject_id)
            edges_by_subject.setdefault(key, []).append(edge)

        def _property(section_name: str, prop_name: str) -> Optional[Any]:
            section = card_schema.sections.get(section_name)
            if not section:
                return None
            return section.properties.get(prop_name)

        title_prop = _property("project", "title")
        subtitle_prop = _property("project", "subtitle")
        image_prop = _property("project", "image")
        event_prop = _property("project", "event")
        institution_prop = _property("project", "institution")
        category_prop = _property("project", "category")

        event_start_prop = _property("event", "start")
        event_end_prop = _property("event", "end")

        # Actor extraction properties
        actor_link_prop = _property("actor_event", "actor_link")
        actor_name_prop = _property("actor", "name")
        # Event -> actor junction canonical URI (not in schema, hardcoded)
        event_actor_junction_uri = "http://arkumu.org/data/properties/akteurinnen-am-ereignis"

        institution_name_prop = _property("institution", "german_name")
        category_name_prop = _property("project_category", "german_name")
        category_wikidata_prop = _property("project_category", "wikidata_id")

        cards: List[Dict[str, Any]] = []

        for subject_id in subject_ids:
            subject_key = str(subject_id)
            if subject_key not in public_subjects:
                continue

            node = nodes.get(subject_key) or {}
            project_uri = (
                node.get("uri")
                or node.get("canonical_uri")
                or node.get("value")
            )
            if not project_uri:
                continue

            subject_edges = edges_by_subject.get(subject_key, [])

            title = self._first_literal(
                subject_edges,
                getattr(title_prop, "canonical_uri", None),
            )
            if not title:
                # Skip projects without a title for card purposes.
                continue

            subtitle = self._first_literal(
                subject_edges,
                getattr(subtitle_prop, "canonical_uri", None),
            )
            image = self._first_literal(
                subject_edges,
                getattr(image_prop, "canonical_uri", None),
            )

            # Institution label (first institution only, as in card view)
            institution_label: str = ""
            institution_ids = self._related_ids(
                subject_edges,
                getattr(institution_prop, "canonical_uri", None),
            )
            if institution_ids:
                inst_id = institution_ids[0]
                inst_node = nodes.get(inst_id) or {}
                inst_edges = edges_by_subject.get(inst_id, [])
                institution_label = (
                    self._first_literal(
                        inst_edges,
                        getattr(institution_name_prop, "canonical_uri", None),
                    )
                    or inst_node.get("name")
                    or inst_node.get("value")
                    or ""
                )

            # Year range from events (if any)
            event_ids = self._related_ids(
                subject_edges,
                getattr(event_prop, "canonical_uri", None),
            )
            event_ranges: List[Dict[str, Optional[str]]] = []
            for event_id in event_ids:
                event_edges = edges_by_subject.get(event_id, [])
                start_val = self._first_literal(
                    event_edges,
                    getattr(event_start_prop, "canonical_uri", None),
                )
                end_val = self._first_literal(
                    event_edges,
                    getattr(event_end_prop, "canonical_uri", None),
                )
                event_ranges.append({"start": start_val, "end": end_val})

            year_range = self._derive_year_range_from_pairs(event_ranges) or ""

            # Extract actors - handle two patterns:
            # 1. FUK: Event -> Junction (akteurinnen-am-ereignis) -> Actor (akteurin-im-ereignis)
            # 2. KHM: Event -> Actor directly (akteurin-im-ereignis)
            actor_names: List[str] = []
            seen_actors: set = set()
            actor_link_uri = getattr(actor_link_prop, "canonical_uri", None)
            actor_name_uri = getattr(actor_name_prop, "canonical_uri", None)

            def _extract_actor_name(actor_id: str) -> Optional[str]:
                actor_edges = edges_by_subject.get(actor_id, [])
                name = self._first_literal(actor_edges, actor_name_uri)
                if not name:
                    actor_node = nodes.get(actor_id) or {}
                    name = actor_node.get("name") or actor_node.get("value")
                return name

            for event_id in event_ids:
                event_edges = edges_by_subject.get(event_id, [])

                # Pattern 1: Try junction path first (FUK)
                junction_ids = self._related_ids(event_edges, event_actor_junction_uri)
                for junction_id in junction_ids:
                    junction_edges = edges_by_subject.get(junction_id, [])
                    actor_ids = self._related_ids(junction_edges, actor_link_uri)
                    for actor_id in actor_ids:
                        actor_name = _extract_actor_name(actor_id)
                        if actor_name:
                            normalized = str(actor_name).strip()
                            if normalized and normalized not in seen_actors:
                                actor_names.append(normalized)
                                seen_actors.add(normalized)

                # Pattern 2: Direct actor links on event
                # KHM/HMT use akteurin-im-ereignis, FUK uses ereignis-hat-akteurin
                fuk_direct_uri = "http://arkumu.org/data/properties/ereignis-hat-akteurin"
                for direct_uri in (actor_link_uri, fuk_direct_uri):
                    if not direct_uri:
                        continue
                    direct_actor_ids = self._related_ids(event_edges, direct_uri)
                    for actor_id in direct_actor_ids:
                        actor_name = _extract_actor_name(actor_id)
                        if actor_name:
                            normalized = str(actor_name).strip()
                            if normalized and normalized not in seen_actors:
                                actor_names.append(normalized)
                                seen_actors.add(normalized)

            # Categories: use Wikidata IDs if available, otherwise fall back to labels
            categories: List[str] = []
            category_ids = self._related_ids(
                subject_edges,
                getattr(category_prop, "canonical_uri", None),
            )
            for cat_id in category_ids:
                cat_edges = edges_by_subject.get(cat_id, [])
                qid = self._first_literal(
                    cat_edges,
                    getattr(category_wikidata_prop, "canonical_uri", None),
                )
                if qid:
                    token = str(qid).strip().upper()
                    if token and token not in categories:
                        categories.append(token)
                    continue

                cat_label = self._first_literal(
                    cat_edges,
                    getattr(category_name_prop, "canonical_uri", None),
                )
                if not cat_label:
                    cat_node = nodes.get(cat_id) or {}
                    cat_label = (
                        cat_node.get("name")
                        or cat_node.get("value")
                        or None
                    )
                if cat_label:
                    token = str(cat_label).strip()
                    if token and token not in categories:
                        categories.append(token)

            card: Dict[str, Any] = {
                "uri": project_uri,
                "title": title or "",
                "subtitle": subtitle or "",
                "image": image or "images/main/card_1.png",
                "institution": institution_label or "",
                "categories": categories,
                "year_range": year_range,
                # Digital objects are omitted in the graph backend for now;
                # callers still see a consistent 'digital_objects' key.
                "digital_objects": [],
            }

            # Add contributor fields (actor names)
            for idx, name in enumerate(actor_names[:4]):
                if name:
                    card[f"contributor{idx + 1}_name"] = name
            if len(actor_names) > 4:
                card["additional_contributors"] = f"{len(actor_names) - 4} weitere"

            # Add category fields for template compatibility
            for idx, category in enumerate(categories[:4]):
                card[f"category{idx + 1}"] = category
            if len(categories) > 4:
                card["additional_categories"] = f"{len(categories) - 4} weitere"

            cards.append(card)

        return cards

    def _get_graph_cards(self, *, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Build or return cached cards from the canonical project graph."""

        cache_key = "arkumu:project_index:graph_cards"
        if not force_refresh:
            cached = cache.get(cache_key)
            if isinstance(cached, list):
                return cached

        card_schema = CARD_SCHEMA_TEMPLATE
        whitelist = self._build_card_predicate_whitelists(card_schema)
        project_predicates = whitelist["project"] or None
        neighbor_predicates = whitelist["neighbor"] or None

        graph_service = CanonicalGraphService(org_code=None)
        graph = graph_service.get_project_graph(
            dataset_name="Projekt",
            type_canonical_uri="http://arkumu.org/data/types/projekt",
            predicate_canon_whitelist=project_predicates,
            expand_neighbors=True,
            neighbor_predicate_canon_whitelist=neighbor_predicates,
            # Use depth 2 to traverse: Event -> Junction -> Actor
            neighbor_depth=2,
        )

        cards = self._build_cards_from_graph(graph, card_schema)

        ttl = getattr(settings, "PROJECT_CARD_INDEX_TTL_SECONDS", 3600)
        try:
            cache.set(cache_key, cards, ttl)
        except Exception:
            # Cache failures must not break card generation.
            logger.warning("ProjectIndexService: failed to cache graph cards", exc_info=True)

        return cards

    # ------------------------------------------------------------------
    # Public card/detail API
    # ------------------------------------------------------------------

    def get_cards(
        self,
        *,
        query: Optional[str] = None,
        organ_code: Optional[str] = None,
        categories: Optional[List[str]] = None,
        actors: Optional[List[str]] = None,
        force_refresh: bool = False,
    ) -> List[Dict[str, Any]]:
        """Return card dictionaries for projects matching the filters."""

        if self.backend == "snapshot":
            records = self._get_all_records(force_refresh=force_refresh)
            filtered_records = self._filter_records(
                records,
                query=query,
                organ_code=organ_code,
            )
            cards = [record.to_card_dict() for record in filtered_records]
            logger.info(
                "ProjectIndexService[snapshot]: materialized %d cards (query='%s', organ_code='%s')",
                len(cards),
                (query or "").strip(),
                (organ_code or "").strip(),
            )
            return cards

        if self.backend == "db":
            base_qs = ProjectIndex.objects.filter(
                public_access_level=PublicAccessLevel.PUBLIC,
                is_public_approved=True,
            )

            if organ_code:
                base_qs = base_qs.filter(org_code__iexact=organ_code.strip())

            if query:
                normalized_query = query.strip()
                base_qs = base_qs.filter(
                    Q(title__icontains=normalized_query)
                    | Q(subtitle__icontains=normalized_query)
                    | Q(institution_label__icontains=normalized_query)
                )

            # Filter by categories (ArrayField overlap)
            if categories:
                base_qs = base_qs.filter(category_labels__overlap=categories)

            # Filter by actor names (ArrayField contains)
            if actors:
                # Use overlap to match any of the actor names
                base_qs = base_qs.filter(actor_names__overlap=[a.strip() for a in actors])

            cards = [entry.to_card_dict() for entry in base_qs.order_by("title")]
            logger.info(
                "ProjectIndexService[db]: materialized %d cards (query='%s', organ_code='%s', categories=%s, actors=%s)",
                len(cards),
                (query or "").strip(),
                (organ_code or "").strip(),
                categories,
                actors,
            )
            return cards

        if self.backend == "graph":
            # Experimental: build cards from canonical project graph with caching.
            cards = self._get_graph_cards(force_refresh=force_refresh)

            # Apply simple filters on top of graph-derived cards.
            normalized_query = (query or "").strip().lower()
            normalized_organ = (organ_code or "").strip().lower()

            def _matches(card: Dict[str, Any]) -> bool:
                if normalized_query:
                    # Collect actor names from contributor fields
                    actor_names = [
                        card.get(f"contributor{i}_name")
                        for i in range(1, 5)
                        if card.get(f"contributor{i}_name")
                    ]
                    haystack = " ".join(
                        filter(
                            None,
                            [
                                card.get("title"),
                                card.get("subtitle"),
                                card.get("institution"),
                                " ".join(card.get("categories") or []),
                                " ".join(actor_names),
                            ],
                        )
                    ).lower()
                    if normalized_query not in haystack:
                        return False
                if normalized_organ:
                    instit = (card.get("institution") or "").lower()
                    if normalized_organ not in instit:
                        return False
                return True

            filtered = [card for card in cards if _matches(card)]
            logger.info(
                "ProjectIndexService[graph]: materialized %d cards (query='%s', organ_code='%s')",
                len(filtered),
                (query or "").strip(),
                (organ_code or "").strip(),
            )
            return filtered

        raise NotImplementedError(f"Unsupported project index backend: {self.backend}")

    def get_card_by_uri(
        self,
        uri: str,
        *,
        force_refresh: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Return a single card dict for the given project URI."""

        if not uri:
            return None

        if self.backend == "snapshot":
            records = self._get_all_records(force_refresh=force_refresh)
            for record in records:
                if record.uri == uri:
                    return record.to_card_dict()
            return None

        if self.backend == "db":
            try:
                entry = ProjectIndex.objects.get(
                    uri=uri,
                    public_access_level=PublicAccessLevel.PUBLIC,
                    is_public_approved=True,
                )
                return entry.to_card_dict()
            except ProjectIndex.DoesNotExist:
                return None

        if self.backend == "graph":
            # For now, rely on full card set and filter in memory.
            cards = self.get_cards(force_refresh=force_refresh)
            for card in cards:
                if card.get("uri") == uri:
                    return card
            return None

        raise NotImplementedError(f"Unsupported project index backend: {self.backend}")

    def get_record_by_uri(
        self,
        uri: str,
        *,
        force_refresh: bool = False,
    ) -> Optional[ProjectRecord]:
        """Return the full ProjectRecord for the given project URI."""

        if not uri:
            return None

        if self.backend == "snapshot":
            records = self._get_all_records(force_refresh=force_refresh)
            for record in records:
                if record.uri == uri:
                    return record
            return None

        if self.backend == "db":
            try:
                entry = ProjectRecordIndex.objects.get(
                    uri=uri,
                    public_access_level=PublicAccessLevel.PUBLIC,
                    is_public_approved=True,
                )
                return entry.to_record()
            except ProjectRecordIndex.DoesNotExist:
                return None

        if self.backend == "graph":
            # Graph backend currently does not build full ProjectRecord.
            raise NotImplementedError("Graph backend does not support full ProjectRecord lookup yet")

        raise NotImplementedError(f"Unsupported project index backend: {self.backend}")
