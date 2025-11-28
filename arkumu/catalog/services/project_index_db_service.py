from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from django.db import transaction
from django.utils import timezone

from arkumu.catalog.models import ProjectDetailIndex, ProjectIndex, ProjectRecordIndex
from arkumu.catalog.services.project_detail_index_service import ProjectDetailIndexService
from arkumu.common.hash_utils import generate_value_hash
from arkumu.metadata.models import PublicAccessLevel, Resource
from arkumu.projects import ProjectDigitalObject, ProjectRecord
from arkumu.projects.services import ProjectSnapshotService

logger = logging.getLogger(__name__)


# Canonical URIs for graph-based index building
class _CanonicalURIs:
    # Project properties
    PROJECT_TYPE = "http://arkumu.org/data/types/projekt"
    TITLE = "http://arkumu.org/data/properties/bevorzugter-titel"
    SUBTITLE = "http://arkumu.org/data/properties/bevorzugter-untertitel"
    DESCRIPTION = "http://arkumu.org/data/properties/kurzbeschreibung"
    DESCRIPTION_ENTITY = "http://arkumu.org/data/properties/beschreibung"  # Nested description entity
    IMAGE = "http://arkumu.org/data/properties/vorschaubild"
    EVENT = "http://arkumu.org/data/properties/ereignis"
    INSTITUTION = "http://arkumu.org/data/properties/einliefernde-hochschule"
    CATEGORY = "http://arkumu.org/data/properties/projektkategorie"
    DIGITAL_OBJECT = "http://arkumu.org/data/properties/digitales-objekt"
    PROJECT_TYPE_LINK = "http://arkumu.org/data/properties/projektart"
    CATCHPHRASE = "http://arkumu.org/data/properties/schlagwort"

    # Event properties
    EVENT_START = "http://arkumu.org/data/properties/ereignisbeginn"
    EVENT_END = "http://arkumu.org/data/properties/ereignisende"
    EVENT_ACTOR_JUNCTION = "http://arkumu.org/data/properties/akteurinnen-am-ereignis"  # Legacy junction (not in use)
    EVENT_DIRECT_ACTOR_FUK = "http://arkumu.org/data/properties/ereignis-hat-akteurin"  # FUK direct event->actor
    EVENT_DIRECT_ACTOR_KHM = "http://arkumu.org/data/properties/akteurin-im-ereignis"  # KHM/HMT direct event->actor
    EVENT_NAME = "http://arkumu.org/data/properties/name-des-ereignisses"  # Legacy event name
    EVENT_NAME_ALT = "http://arkumu.org/data/properties/ereignisname"  # Canonical event name
    EVENT_LOCATION = "http://arkumu.org/data/properties/ereignisort"
    EVENT_DESCRIPTION = "http://arkumu.org/data/properties/ereignisbeschreibung"

    # Actor junction properties
    ACTOR_LINK = "http://arkumu.org/data/properties/akteurin-im-ereignis"
    ACTOR_ROLE = "http://arkumu.org/data/properties/rolle"

    # Actor properties
    ACTOR_NAME = "http://arkumu.org/data/properties/deutscher-name"

    # Institution properties
    INSTITUTION_NAME = "http://arkumu.org/data/properties/deutscher-name-der-einliefernden-hochschule"

    # Category properties
    CATEGORY_NAME = "http://arkumu.org/data/properties/deutscher-name-der-projektkategorie-breadcrumb"
    CATEGORY_SLUG = "http://arkumu.org/data/properties/slug-der-projektkategorie"

    # Project type properties
    PROJECT_TYPE_NAME = "http://arkumu.org/data/properties/deutscher-name-der-projektart"

    # Catchphrase properties
    CATCHPHRASE_NAME = "http://arkumu.org/data/properties/deutscher-name-des-schlagworts"

    # Digital object properties
    DO_PATH = "http://arkumu.org/data/properties/dateipfad"

    # Predicate whitelists for efficient graph queries
    @classmethod
    def project_predicates(cls) -> List[str]:
        return [
            cls.TITLE,
            cls.SUBTITLE,
            cls.DESCRIPTION,
            cls.DESCRIPTION_ENTITY,
            cls.IMAGE,
            cls.EVENT,
            cls.INSTITUTION,
            cls.CATEGORY,
            cls.DIGITAL_OBJECT,
            cls.PROJECT_TYPE_LINK,
            cls.CATCHPHRASE,
        ]

    @classmethod
    def neighbor_predicates(cls) -> List[str]:
        return [
            cls.EVENT_START,
            cls.EVENT_END,
            cls.EVENT_ACTOR_JUNCTION,
            cls.EVENT_DIRECT_ACTOR_FUK,
            cls.EVENT_DIRECT_ACTOR_KHM,
            cls.EVENT_NAME,
            cls.EVENT_NAME_ALT,
            cls.EVENT_LOCATION,
            cls.EVENT_DESCRIPTION,
            cls.ACTOR_LINK,
            cls.ACTOR_ROLE,
            cls.ACTOR_NAME,
            cls.INSTITUTION_NAME,
            cls.CATEGORY_NAME,
            cls.CATEGORY_SLUG,
            cls.PROJECT_TYPE_NAME,
            cls.CATCHPHRASE_NAME,
            cls.DO_PATH,
            cls.DESCRIPTION_ENTITY,  # For nested description text
        ]


def _as_uuid(value: Optional[str]) -> Optional[uuid.UUID]:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _display_path(obj: ProjectDigitalObject) -> Optional[str]:
    if obj.access_url:
        return obj.access_url
    if obj.path:
        return obj.path
    if obj.storage_key:
        return obj.storage_key
    return None


def _coerce_year(raw: Optional[str]) -> Optional[int]:
    if not raw:
        return None
    token = str(raw).strip()
    if not token:
        return None
    # Trim ISO date parts if present
    if "-" in token:
        token = token.split("-")[0]
    match = re.search(r"\d{4}", token)
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


class ProjectIndexDbService:
    """Materialize ProjectRecord data into derived DB-backed index tables."""

    def __init__(self, *, now=None) -> None:
        self.snapshot_service = ProjectSnapshotService()
        self.detail_service = ProjectDetailIndexService()
        self.now = now or timezone.now()

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #

    def rebuild(
        self,
        *,
        project_uris: Optional[Sequence[str]] = None,
        force_snapshot: bool = False,
    ) -> Dict[str, int]:
        """Rebuild index tables from ProjectRecord instances."""

        if project_uris:
            records = self._records_for_uris(project_uris)
        else:
            snapshot = self.snapshot_service.get_cross_institutional_snapshot(
                force_refresh=force_snapshot,
                include_non_public=True,
            )
            records = list(snapshot.projects)

        resources = self._resource_map(records)
        source_version = self._source_version(resources.values(), records)
        prune_missing = not bool(project_uris)

        return self._write_indexes(
            records,
            resources,
            source_version,
            prune_missing=prune_missing,
        )

    # ------------------------------------------------------------------ #
    # Internals                                                          #
    # ------------------------------------------------------------------ #

    def _records_for_uris(self, uris: Sequence[str]) -> List[ProjectRecord]:
        seen: set[str] = set()
        records: List[ProjectRecord] = []

        for uri in uris:
            normalized = (uri or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            record = self.detail_service.get_record(normalized)
            if record:
                records.append(record)
            else:
                logger.warning("ProjectIndexDbService: record not found for uri=%s", normalized)
        return records

    def _resource_map(self, records: Sequence[ProjectRecord]) -> Dict[uuid.UUID, Resource]:
        ids: List[uuid.UUID] = []
        for record in records:
            subject_uuid = _as_uuid(getattr(record, "subject_id", None))
            if subject_uuid:
                ids.append(subject_uuid)

        if not ids:
            return {}

        return Resource.objects.in_bulk(ids)

    def _source_version(
        self,
        resources: Iterable[Resource],
        records: Sequence[ProjectRecord],
    ) -> str:
        tokens: List[str] = [str(len(records))]
        for resource in resources:
            updated = getattr(resource, "updated_at", None)
            token = f"{resource.id}"
            if updated:
                token = f"{token}:{updated.isoformat()}"
            tokens.append(token)

        if not tokens:
            return ""

        return generate_value_hash("|".join(sorted(tokens)))

    def _write_indexes(
        self,
        records: Sequence[ProjectRecord],
        resource_map: Dict[uuid.UUID, Resource],
        source_version: str,
        *,
        prune_missing: bool,
    ) -> Dict[str, int]:
        built_at = self.now
        seen_ids: set[uuid.UUID] = set()
        index_rows: List[ProjectIndex] = []
        record_rows: List[ProjectRecordIndex] = []

        for record in records:
            subject_uuid = _as_uuid(getattr(record, "subject_id", None))
            if not subject_uuid:
                logger.warning("ProjectIndexDbService: missing subject_id for uri=%s", record.uri)
                continue
            resource = resource_map.get(subject_uuid)
            if not resource:
                logger.warning(
                    "ProjectIndexDbService: resource not found for subject_id=%s (uri=%s)",
                    subject_uuid,
                    record.uri,
                )
                continue

            defaults_index = self._index_defaults(record, resource, built_at, source_version)
            defaults_record = self._record_defaults(record, resource, built_at, source_version)

            index_rows.append(ProjectIndex(project_resource=resource, **defaults_index))
            record_rows.append(ProjectRecordIndex(project_resource=resource, **defaults_record))
            seen_ids.add(resource.id)

        with transaction.atomic():
            if not index_rows and not record_rows:
                if prune_missing:
                    ProjectIndex.objects.all().delete()
                    ProjectRecordIndex.objects.all().delete()
                return {"projects_index": 0, "project_records": 0}

            if index_rows:
                ProjectIndex.objects.bulk_create(
                    index_rows,
                    update_conflicts=True,
                    unique_fields=["project_resource"],
                    update_fields=[
                        "uri",
                        "org_code",
                        "public_access_level",
                        "is_public_approved",
                        "is_derived",
                        "title",
                        "subtitle",
                        "image",
                        "institution_label",
                        "categories",
                        "actor_names",
                        "digital_object_paths",
                        "year_range",
                        "source_updated_at",
                        "built_at",
                        "source_version",
                    ],
                )

            if record_rows:
                ProjectRecordIndex.objects.bulk_create(
                    record_rows,
                    update_conflicts=True,
                    unique_fields=["project_resource"],
                    update_fields=[
                        "uri",
                        "org_code",
                        "public_access_level",
                        "is_public_approved",
                        "is_derived",
                        "title",
                        "subtitle",
                        "description",
                        "institution_label",
                        "institution_codes",
                        "category_labels",
                        "category_slugs",
                        "actor_names",
                        "year_values",
                        "project_type_label",
                        "catchphrase_labels",
                        "image",
                        "digital_object_paths",
                        "reference_only",
                        "harvestable",
                        "ownership_filtered",
                        "record_jsonb",
                        "source_updated_at",
                        "built_at",
                        "source_version",
                    ],
                )

            if prune_missing and seen_ids:
                ProjectIndex.objects.exclude(project_resource_id__in=seen_ids).delete()
                ProjectRecordIndex.objects.exclude(project_resource_id__in=seen_ids).delete()

        return {
            "projects_index": len(index_rows),
            "project_records": len(record_rows),
        }

    def _index_defaults(
        self,
        record: ProjectRecord,
        resource: Resource,
        built_at,
        source_version: str,
    ) -> Dict[str, object]:
        return {
            "uri": record.uri,
            "org_code": self._org_code(resource),
            "public_access_level": getattr(resource, "public_access_level", PublicAccessLevel.RESTRICTED),
            "is_public_approved": bool(getattr(resource, "is_public_approved", False)),
            "is_derived": bool(getattr(resource, "is_public", False)),
            "title": record.title or "",
            "subtitle": record.subtitle or "",
            "image": record.image or "",
            "institution_label": self._institution_label(record),
            "categories": self._category_tokens(record),
            "actor_names": self._actor_names(record),
            "digital_object_paths": self._digital_object_paths(record),
            "year_range": record.year_range or self._derive_year_range(record) or "",
            "source_updated_at": getattr(resource, "updated_at", None),
            "built_at": built_at,
            "source_version": source_version,
        }

    def _record_defaults(
        self,
        record: ProjectRecord,
        resource: Resource,
        built_at,
        source_version: str,
    ) -> Dict[str, object]:
        return {
            "uri": record.uri,
            "org_code": self._org_code(resource),
            "public_access_level": getattr(resource, "public_access_level", PublicAccessLevel.RESTRICTED),
            "is_public_approved": bool(getattr(resource, "is_public_approved", False)),
            "is_derived": bool(getattr(resource, "is_public", False)),
            "title": record.title or "",
            "subtitle": record.subtitle or "",
            "description": record.description or "",
            "institution_label": self._institution_label(record),
            "institution_codes": list(record.institution_codes or []),
            "category_labels": self._category_labels(record),
            "category_slugs": list(record.category_slugs or []),
            "actor_names": self._actor_names(record),
            "year_values": self._year_values(record),
            "project_type_label": getattr(getattr(record, "project_type", None), "label", "") or "",
            "catchphrase_labels": [cp.label for cp in (record.catchphrases or []) if getattr(cp, "label", None)],
            "image": record.image or "",
            "digital_object_paths": self._digital_object_paths(record),
            "reference_only": bool(getattr(record, "reference_only", False)),
            "harvestable": bool(getattr(record, "harvestable", True)),
            "ownership_filtered": bool(getattr(record, "ownership_filtered", False)),
            "record_jsonb": record.to_dict(),
            "source_updated_at": getattr(resource, "updated_at", None),
            "built_at": built_at,
            "source_version": source_version,
        }

    @staticmethod
    def _org_code(resource: Resource) -> str:
        organization = getattr(resource, "organization", None)
        code = getattr(organization, "code", "") if organization else ""
        return str(code or "").strip().lower()

    @staticmethod
    def _institution_label(record: ProjectRecord) -> str:
        institution = getattr(record, "institution", None)
        label = getattr(institution, "label", "") if institution else ""
        return str(label or "").strip()

    def _category_tokens(self, record: ProjectRecord) -> List[str]:
        tokens: List[str] = []
        for category in getattr(record, "categories", []) or []:
            label = getattr(category, "label", None)
            slug = getattr(category, "slug", None)
            token = label or slug
            if not token:
                continue
            normalized = str(token).strip()
            if normalized and normalized not in tokens:
                tokens.append(normalized)
        return tokens

    def _category_labels(self, record: ProjectRecord) -> List[str]:
        labels: List[str] = []
        for category in getattr(record, "categories", []) or []:
            label = getattr(category, "label", None)
            if not label:
                continue
            normalized = str(label).strip()
            if normalized and normalized not in labels:
                labels.append(normalized)
        return labels

    def _actor_names(self, record: ProjectRecord) -> List[str]:
        names: List[str] = []
        for actor in getattr(record, "actors", []) or []:
            name = getattr(actor, "name", None) if actor else None
            if not name:
                continue
            normalized = str(name).strip()
            if normalized and normalized not in names:
                names.append(normalized)
        return names

    def _digital_object_paths(self, record: ProjectRecord) -> List[str]:
        paths: List[str] = []
        for obj in getattr(record, "digital_objects", []) or []:
            path = _display_path(obj)
            if not path:
                continue
            normalized = str(path).strip()
            if normalized and normalized not in paths:
                paths.append(normalized)
        return paths

    def _year_values(self, record: ProjectRecord) -> List[int]:
        values: set[int] = set()
        for event in getattr(record, "events", []) or []:
            for candidate in (getattr(event, "start", None), getattr(event, "end", None)):
                year = _coerce_year(candidate)
                if year:
                    values.add(year)

        year_range = getattr(record, "year_range", None)
        if year_range:
            for match in re.findall(r"\d{4}", str(year_range)):
                try:
                    values.add(int(match))
                except ValueError:
                    continue

        return sorted(values)

    def _derive_year_range(self, record: ProjectRecord) -> Optional[str]:
        years = self._year_values(record)
        if not years:
            return None
        if len(years) == 1:
            return str(years[0])
        return f"{min(years)} bis {max(years)}"

    # ------------------------------------------------------------------ #
    # Graph-based rebuild (efficient canonical graph -> DB tables)       #
    # ------------------------------------------------------------------ #

    def rebuild_from_graph(
        self,
        *,
        project_uris: Optional[Sequence[str]] = None,
    ) -> Dict[str, int]:
        """Rebuild index tables directly from the canonical graph.

        This bypasses ProjectRecord/Snapshot materialization for efficiency.
        Queries the triple store once and bulk-writes to index tables.
        """
        from arkumu.metadata.services.canonical_graph_service import CanonicalGraphService

        graph_service = CanonicalGraphService(org_code=None)
        graph = graph_service.get_project_graph(
            dataset_name="Projekt",
            type_canonical_uri=_CanonicalURIs.PROJECT_TYPE,
            predicate_canon_whitelist=_CanonicalURIs.project_predicates(),
            expand_neighbors=True,
            neighbor_predicate_canon_whitelist=_CanonicalURIs.neighbor_predicates(),
        )

        subject_ids: List[str] = graph.get("subjects", []) or []
        if not subject_ids:
            logger.warning("rebuild_from_graph: no project subjects found")
            return {"projects_index": 0, "project_records": 0}

        # Filter to specific URIs if requested
        if project_uris:
            uri_set = {uri.strip() for uri in project_uris if uri}
            nodes = graph.get("nodes", {}) or {}
            subject_ids = [
                sid for sid in subject_ids
                if nodes.get(sid, {}).get("uri") in uri_set
            ]

        # Build efficient lookup structures
        edges = graph.get("edges", []) or []
        nodes = graph.get("nodes", {}) or {}
        edges_by_subject = self._build_edge_index(edges)

        # Fetch 2nd level neighbors: actors linked from events via direct links
        # FUK uses direct event->actor links, so we need to also fetch actor properties
        self._expand_second_level_actors(edges_by_subject, nodes, graph_service)

        # Batch-fetch Resources for visibility and org info
        resource_map = self._fetch_resources_batch(subject_ids)

        # Build index rows from graph
        built_at = self.now
        source_version = generate_value_hash(f"graph:{built_at.isoformat()}:{len(subject_ids)}")
        prune_missing = not bool(project_uris)

        return self._write_indexes_from_graph(
            subject_ids=subject_ids,
            edges_by_subject=edges_by_subject,
            nodes=nodes,
            resource_map=resource_map,
            built_at=built_at,
            source_version=source_version,
            prune_missing=prune_missing,
        )

    def _build_edge_index(
        self,
        edges: List[Dict[str, Any]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Index edges by subject_id for O(1) lookup."""
        index: Dict[str, List[Dict[str, Any]]] = {}
        for edge in edges:
            subject_id = edge.get("subject_id")
            if subject_id:
                index.setdefault(str(subject_id), []).append(edge)
        return index

    def _fetch_resources_batch(
        self,
        subject_ids: Sequence[str],
    ) -> Dict[uuid.UUID, Resource]:
        """Batch-fetch Resource objects for visibility info."""
        uuids: List[uuid.UUID] = []
        for sid in subject_ids:
            uid = _as_uuid(sid)
            if uid:
                uuids.append(uid)
        if not uuids:
            return {}
        return Resource.objects.select_related("organization").in_bulk(uuids)

    def _write_indexes_from_graph(
        self,
        *,
        subject_ids: Sequence[str],
        edges_by_subject: Dict[str, List[Dict[str, Any]]],
        nodes: Dict[str, Dict[str, Any]],
        resource_map: Dict[uuid.UUID, Resource],
        built_at,
        source_version: str,
        prune_missing: bool,
    ) -> Dict[str, int]:
        """Transform graph data into ProjectIndex, ProjectRecordIndex, and ProjectDetailIndex rows."""
        seen_ids: Set[uuid.UUID] = set()
        index_rows: List[ProjectIndex] = []
        record_rows: List[ProjectRecordIndex] = []
        detail_rows: List[ProjectDetailIndex] = []

        for subject_id in subject_ids:
            subject_uuid = _as_uuid(subject_id)
            if not subject_uuid:
                continue

            resource = resource_map.get(subject_uuid)
            if not resource:
                logger.debug("rebuild_from_graph: resource not found for %s", subject_id)
                continue

            # Convert to string for dict lookups (nodes/edges are keyed by string)
            subject_id_str = str(subject_id)

            node = nodes.get(subject_id_str, {})
            project_uri = node.get("uri") or node.get("canonical_uri")
            if not project_uri:
                continue

            subject_edges = edges_by_subject.get(subject_id_str, [])

            # Extract fields from graph
            title = self._first_literal(subject_edges, _CanonicalURIs.TITLE)
            if not title:
                # Skip projects without title
                continue

            subtitle = self._first_literal(subject_edges, _CanonicalURIs.SUBTITLE)
            # Try direct description first, then nested beschreibung entity
            description = self._first_literal(subject_edges, _CanonicalURIs.DESCRIPTION)
            if not description:
                description = self._extract_nested_description(
                    subject_edges, edges_by_subject, nodes
                )
            image = self._first_literal(subject_edges, _CanonicalURIs.IMAGE)

            # Institution
            institution_label = self._extract_institution_label(
                subject_edges, edges_by_subject, nodes
            )
            institution_uri = self._extract_institution_uri(
                subject_edges, nodes
            )

            # Categories
            categories = self._extract_categories(
                subject_edges, edges_by_subject, nodes
            )

            # Category slugs
            category_slugs = self._extract_category_slugs(
                subject_edges, edges_by_subject, nodes
            )

            # Build structured categories for detail index
            categories_structured = self._extract_categories_structured(
                subject_edges, edges_by_subject, nodes
            )

            # Project type
            project_type_label = self._extract_project_type_label(
                subject_edges, edges_by_subject, nodes
            )

            # Catchphrases
            catchphrase_labels = self._extract_catchphrase_labels(
                subject_edges, edges_by_subject, nodes
            )

            # Actors from events (names only for card index)
            actor_names = self._extract_actor_names(
                subject_edges, edges_by_subject, nodes
            )

            # Actors with roles for detail view
            actors_structured = self._extract_actors_structured(
                subject_edges, edges_by_subject, nodes
            )

            # Events with full data for detail view
            events_structured = self._extract_events_structured(
                subject_edges, edges_by_subject, nodes
            )

            # Year range from events
            year_range = self._extract_year_range(
                subject_edges, edges_by_subject
            )

            # Year values as list
            year_values = self._extract_year_values(
                subject_edges, edges_by_subject
            )

            # Digital object paths
            digital_object_paths = self._extract_digital_object_paths(
                subject_edges, edges_by_subject, nodes
            )

            # Digital objects structured
            digital_objects_structured = self._extract_digital_objects_structured(
                subject_edges, edges_by_subject, nodes
            )

            org_code = self._org_code(resource)
            institution_codes = [org_code] if org_code else []

            # Build ProjectIndex row
            index_row = ProjectIndex(
                project_resource=resource,
                uri=project_uri,
                org_code=org_code,
                public_access_level=getattr(resource, "public_access_level", PublicAccessLevel.RESTRICTED),
                is_public_approved=bool(getattr(resource, "is_public_approved", False)),
                is_derived=bool(getattr(resource, "is_public", False)),
                title=title or "",
                subtitle=subtitle or "",
                image=image or "",
                institution_label=institution_label or "",
                categories=categories,
                actor_names=actor_names,
                digital_object_paths=digital_object_paths,
                year_range=year_range or "",
                source_updated_at=getattr(resource, "updated_at", None),
                built_at=built_at,
                source_version=source_version,
            )
            index_rows.append(index_row)

            # Build record_jsonb for ProjectRecordIndex
            record_jsonb = self._build_record_jsonb_from_graph(
                project_uri=project_uri,
                subject_id=subject_id_str,
                title=title or "",
                subtitle=subtitle or "",
                description=description or "",
                image=image or "",
                institution_label=institution_label or "",
                categories=categories,
                category_slugs=category_slugs,
                actor_names=actor_names,
                year_range=year_range or "",
                project_type_label=project_type_label or "",
                catchphrase_labels=catchphrase_labels,
                digital_object_paths=digital_object_paths,
                institution_codes=institution_codes,
            )

            # Build ProjectRecordIndex row
            record_row = ProjectRecordIndex(
                project_resource=resource,
                uri=project_uri,
                org_code=org_code,
                public_access_level=getattr(resource, "public_access_level", PublicAccessLevel.RESTRICTED),
                is_public_approved=bool(getattr(resource, "is_public_approved", False)),
                is_derived=bool(getattr(resource, "is_public", False)),
                title=title or "",
                subtitle=subtitle or "",
                description=description or "",
                institution_label=institution_label or "",
                institution_codes=institution_codes,
                category_labels=categories,
                category_slugs=category_slugs,
                actor_names=actor_names,
                year_values=year_values,
                project_type_label=project_type_label or "",
                catchphrase_labels=catchphrase_labels,
                image=image or "",
                digital_object_paths=digital_object_paths,
                reference_only=False,
                harvestable=True,
                ownership_filtered=False,
                record_jsonb=record_jsonb,
                source_updated_at=getattr(resource, "updated_at", None),
                built_at=built_at,
                source_version=source_version,
            )
            record_rows.append(record_row)

            # Build ProjectDetailIndex row with structured data
            detail_row = ProjectDetailIndex(
                project_resource=resource,
                uri=project_uri,
                org_code=org_code,
                public_access_level=getattr(resource, "public_access_level", PublicAccessLevel.RESTRICTED),
                is_public_approved=bool(getattr(resource, "is_public_approved", False)),
                title=title or "",
                subtitle=subtitle or "",
                description=description or "",
                image=image or "",
                institution_label=institution_label or "",
                institution_uri=institution_uri or "",
                project_type_label=project_type_label or "",
                year_range=year_range or "",
                categories=categories_structured,
                actors=actors_structured,
                events=events_structured,
                digital_objects=digital_objects_structured,
                alternative_titles=[],
                catchphrases=[{"label": c} for c in catchphrase_labels],
                properties={},
                status={},
                authority={},
                submitter={},
                licenses={},
                rights_status={},
                reference_only=False,
                harvestable=True,
                ownership_filtered=False,
                source_updated_at=getattr(resource, "updated_at", None),
                built_at=built_at,
                source_version=source_version,
            )
            detail_rows.append(detail_row)
            seen_ids.add(resource.id)

        # Bulk write
        with transaction.atomic():
            if not index_rows and not record_rows and not detail_rows:
                if prune_missing:
                    ProjectIndex.objects.all().delete()
                    ProjectRecordIndex.objects.all().delete()
                    ProjectDetailIndex.objects.all().delete()
                return {"projects_index": 0, "project_records": 0, "project_details": 0}

            if index_rows:
                ProjectIndex.objects.bulk_create(
                    index_rows,
                    update_conflicts=True,
                    unique_fields=["project_resource"],
                    update_fields=[
                        "uri",
                        "org_code",
                        "public_access_level",
                        "is_public_approved",
                        "is_derived",
                        "title",
                        "subtitle",
                        "image",
                        "institution_label",
                        "categories",
                        "actor_names",
                        "digital_object_paths",
                        "year_range",
                        "source_updated_at",
                        "built_at",
                        "source_version",
                    ],
                )

            if record_rows:
                ProjectRecordIndex.objects.bulk_create(
                    record_rows,
                    update_conflicts=True,
                    unique_fields=["project_resource"],
                    update_fields=[
                        "uri",
                        "org_code",
                        "public_access_level",
                        "is_public_approved",
                        "is_derived",
                        "title",
                        "subtitle",
                        "description",
                        "institution_label",
                        "institution_codes",
                        "category_labels",
                        "category_slugs",
                        "actor_names",
                        "year_values",
                        "project_type_label",
                        "catchphrase_labels",
                        "image",
                        "digital_object_paths",
                        "reference_only",
                        "harvestable",
                        "ownership_filtered",
                        "record_jsonb",
                        "source_updated_at",
                        "built_at",
                        "source_version",
                    ],
                )

            if detail_rows:
                ProjectDetailIndex.objects.bulk_create(
                    detail_rows,
                    update_conflicts=True,
                    unique_fields=["project_resource"],
                    update_fields=[
                        "uri",
                        "org_code",
                        "public_access_level",
                        "is_public_approved",
                        "title",
                        "subtitle",
                        "description",
                        "image",
                        "institution_label",
                        "institution_uri",
                        "project_type_label",
                        "year_range",
                        "categories",
                        "actors",
                        "events",
                        "digital_objects",
                        "alternative_titles",
                        "catchphrases",
                        "properties",
                        "status",
                        "authority",
                        "submitter",
                        "licenses",
                        "rights_status",
                        "reference_only",
                        "harvestable",
                        "ownership_filtered",
                        "source_updated_at",
                        "built_at",
                        "source_version",
                    ],
                )

            if prune_missing and seen_ids:
                ProjectIndex.objects.exclude(project_resource_id__in=seen_ids).delete()
                ProjectRecordIndex.objects.exclude(project_resource_id__in=seen_ids).delete()
                ProjectDetailIndex.objects.exclude(project_resource_id__in=seen_ids).delete()

        logger.info(
            "rebuild_from_graph: wrote %d ProjectIndex, %d ProjectRecordIndex, %d ProjectDetailIndex rows (prune=%s)",
            len(index_rows),
            len(record_rows),
            len(detail_rows),
            prune_missing,
        )
        return {
            "projects_index": len(index_rows),
            "project_records": len(record_rows),
            "project_details": len(detail_rows),
        }

    # ------------------------------------------------------------------ #
    # Graph field extraction helpers                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _canonical(edge: Dict[str, Any]) -> Optional[str]:
        """Get canonical predicate URI from edge."""
        return edge.get("predicate_canonical") or edge.get("predicate_uri")

    def _first_literal(
        self,
        edges: Iterable[Dict[str, Any]],
        predicate: str,
    ) -> Optional[str]:
        """Get first literal value for predicate."""
        for edge in edges:
            if self._canonical(edge) == predicate:
                value = edge.get("object_value")
                if value:
                    return str(value)
        return None

    def _related_ids(
        self,
        edges: Iterable[Dict[str, Any]],
        predicate: str,
    ) -> List[str]:
        """Get all related object IDs for predicate."""
        results: List[str] = []
        for edge in edges:
            if self._canonical(edge) == predicate:
                obj_id = edge.get("object_id")
                if obj_id:
                    results.append(str(obj_id))
        return results

    def _expand_second_level_actors(
        self,
        edges_by_subject: Dict[str, List[Dict[str, Any]]],
        nodes: Dict[str, Dict[str, Any]],
        graph_service: Any,
    ) -> None:
        """Fetch 2nd level neighbor data: actors linked from events via direct links.

        FUK uses ereignis-hat-akteurin, KHM/HMT use akteurin-im-ereignis.
        Actors are 2 hops from projects. This method fetches actor properties separately.
        """
        # Collect all actor IDs linked from events via direct links (both patterns)
        actor_ids: Set[str] = set()
        direct_actor_uris = (_CanonicalURIs.EVENT_DIRECT_ACTOR_FUK, _CanonicalURIs.EVENT_DIRECT_ACTOR_KHM)
        for subject_id, subject_edges in edges_by_subject.items():
            for edge in subject_edges:
                predicate = self._canonical(edge)
                if predicate in direct_actor_uris:
                    actor_id = edge.get("object_id")
                    if actor_id:
                        actor_ids.add(str(actor_id))

        if not actor_ids:
            return

        logger.debug("_expand_second_level_actors: fetching %d actors", len(actor_ids))

        # Also collect actor-event junction IDs (akteurin-im-ereignis links)
        # so we can get roles
        actor_junction_predicates = [
            _CanonicalURIs.ACTOR_NAME,
            _CanonicalURIs.ACTOR_LINK,  # akteurin-im-ereignis
            _CanonicalURIs.ACTOR_ROLE,
        ]

        # Fetch actor edges
        actor_edges = graph_service._fetch_triples_for_subjects(
            list(actor_ids),
            actor_junction_predicates,
        )

        # Add actor edges to the index
        for edge in actor_edges:
            edge_dict = edge.__dict__ if hasattr(edge, "__dict__") else edge
            subject_id = str(edge_dict.get("subject_id", ""))
            if subject_id:
                edges_by_subject.setdefault(subject_id, []).append(edge_dict)

        # Also fetch actor-event junction edges for roles
        junction_ids: Set[str] = set()
        for edge_dict in actor_edges:
            if isinstance(edge_dict, dict):
                predicate = edge_dict.get("predicate_canonical") or edge_dict.get("predicate_uri")
            else:
                predicate = getattr(edge_dict, "predicate_canonical", None) or getattr(edge_dict, "predicate_uri", None)
            if predicate == _CanonicalURIs.ACTOR_LINK:
                obj_id = edge_dict.get("object_id") if isinstance(edge_dict, dict) else getattr(edge_dict, "object_id", None)
                if obj_id:
                    junction_ids.add(str(obj_id))

        if junction_ids:
            junction_edges = graph_service._fetch_triples_for_subjects(
                list(junction_ids),
                [_CanonicalURIs.ACTOR_ROLE],
            )
            for edge in junction_edges:
                edge_dict = edge.__dict__ if hasattr(edge, "__dict__") else edge
                subject_id = str(edge_dict.get("subject_id", ""))
                if subject_id:
                    edges_by_subject.setdefault(subject_id, []).append(edge_dict)

    def _extract_nested_description(
        self,
        subject_edges: List[Dict[str, Any]],
        edges_by_subject: Dict[str, List[Dict[str, Any]]],
        nodes: Dict[str, Dict[str, Any]],
    ) -> Optional[str]:
        """Extract description from nested beschreibung entity (canonical model)."""
        desc_ids = self._related_ids(subject_edges, _CanonicalURIs.DESCRIPTION_ENTITY)
        if not desc_ids:
            return None

        desc_id = desc_ids[0]
        desc_edges = edges_by_subject.get(desc_id, [])

        # The beschreibung entity has a beschreibung property with the text
        description = self._first_literal(desc_edges, _CanonicalURIs.DESCRIPTION_ENTITY)
        return description

    def _extract_institution_label(
        self,
        subject_edges: List[Dict[str, Any]],
        edges_by_subject: Dict[str, List[Dict[str, Any]]],
        nodes: Dict[str, Dict[str, Any]],
    ) -> str:
        """Extract institution label from project's institution relation."""
        inst_ids = self._related_ids(subject_edges, _CanonicalURIs.INSTITUTION)
        if not inst_ids:
            return ""

        inst_id = inst_ids[0]
        inst_edges = edges_by_subject.get(inst_id, [])
        label = self._first_literal(inst_edges, _CanonicalURIs.INSTITUTION_NAME)
        if label:
            return label

        # Fallback to node name
        inst_node = nodes.get(inst_id, {})
        return inst_node.get("name") or inst_node.get("value") or ""

    def _extract_categories(
        self,
        subject_edges: List[Dict[str, Any]],
        edges_by_subject: Dict[str, List[Dict[str, Any]]],
        nodes: Dict[str, Dict[str, Any]],
    ) -> List[str]:
        """Extract category labels from project's category relations."""
        cat_ids = self._related_ids(subject_edges, _CanonicalURIs.CATEGORY)
        categories: List[str] = []
        seen: Set[str] = set()

        for cat_id in cat_ids:
            cat_edges = edges_by_subject.get(cat_id, [])
            label = self._first_literal(cat_edges, _CanonicalURIs.CATEGORY_NAME)
            if not label:
                cat_node = nodes.get(cat_id, {})
                label = cat_node.get("name") or cat_node.get("value")

            if label:
                normalized = str(label).strip()
                if normalized and normalized not in seen:
                    categories.append(normalized)
                    seen.add(normalized)

        return categories

    def _extract_actor_names(
        self,
        subject_edges: List[Dict[str, Any]],
        edges_by_subject: Dict[str, List[Dict[str, Any]]],
        nodes: Dict[str, Dict[str, Any]],
    ) -> List[str]:
        """Extract actor names via two patterns:
        1. FUK: event -> junction (akteurinnen-am-ereignis) -> actor (akteurin-im-ereignis)
        2. KHM/HMT: event -> actor directly (akteurin-im-ereignis)
        """
        event_ids = self._related_ids(subject_edges, _CanonicalURIs.EVENT)
        actor_names: List[str] = []
        seen: Set[str] = set()

        def _add_actor_name(actor_id: str) -> None:
            actor_edges = edges_by_subject.get(actor_id, [])
            name = self._first_literal(actor_edges, _CanonicalURIs.ACTOR_NAME)
            if not name:
                actor_node = nodes.get(actor_id, {})
                name = actor_node.get("name") or actor_node.get("value")
            if name:
                normalized = str(name).strip()
                if normalized and normalized not in seen:
                    actor_names.append(normalized)
                    seen.add(normalized)

        for event_id in event_ids:
            event_edges = edges_by_subject.get(event_id, [])

            # Pattern 1: FUK junction path (akteurinnen-am-ereignis -> akteurin-im-ereignis)
            junction_ids = self._related_ids(event_edges, _CanonicalURIs.EVENT_ACTOR_JUNCTION)
            for junction_id in junction_ids:
                junction_edges = edges_by_subject.get(junction_id, [])
                actor_ids = self._related_ids(junction_edges, _CanonicalURIs.ACTOR_LINK)
                for actor_id in actor_ids:
                    _add_actor_name(actor_id)

            # Pattern 2: Direct actor links on event
            # FUK uses ereignis-hat-akteurin, KHM/HMT use akteurin-im-ereignis
            for direct_uri in (_CanonicalURIs.EVENT_DIRECT_ACTOR_FUK, _CanonicalURIs.EVENT_DIRECT_ACTOR_KHM):
                direct_actor_ids = self._related_ids(event_edges, direct_uri)
                for actor_id in direct_actor_ids:
                    _add_actor_name(actor_id)

        return actor_names

    def _extract_year_range(
        self,
        subject_edges: List[Dict[str, Any]],
        edges_by_subject: Dict[str, List[Dict[str, Any]]],
    ) -> str:
        """Extract year range from project's events."""
        event_ids = self._related_ids(subject_edges, _CanonicalURIs.EVENT)
        years: Set[int] = set()

        for event_id in event_ids:
            event_edges = edges_by_subject.get(event_id, [])
            start = self._first_literal(event_edges, _CanonicalURIs.EVENT_START)
            end = self._first_literal(event_edges, _CanonicalURIs.EVENT_END)

            for val in (start, end):
                year = _coerce_year(val)
                if year:
                    years.add(year)

        if not years:
            return ""
        if len(years) == 1:
            return str(list(years)[0])
        return f"{min(years)} bis {max(years)}"

    def _extract_digital_object_paths(
        self,
        subject_edges: List[Dict[str, Any]],
        edges_by_subject: Dict[str, List[Dict[str, Any]]],
        nodes: Dict[str, Dict[str, Any]],
    ) -> List[str]:
        """Extract digital object paths from project's DO relations."""
        do_ids = self._related_ids(subject_edges, _CanonicalURIs.DIGITAL_OBJECT)
        paths: List[str] = []
        seen: Set[str] = set()

        for do_id in do_ids:
            do_edges = edges_by_subject.get(do_id, [])
            path = self._first_literal(do_edges, _CanonicalURIs.DO_PATH)
            if path:
                normalized = str(path).strip()
                if normalized and normalized not in seen:
                    paths.append(normalized)
                    seen.add(normalized)

        return paths

    def _extract_category_slugs(
        self,
        subject_edges: List[Dict[str, Any]],
        edges_by_subject: Dict[str, List[Dict[str, Any]]],
        nodes: Dict[str, Dict[str, Any]],
    ) -> List[str]:
        """Extract category slugs from project's category relations."""
        cat_ids = self._related_ids(subject_edges, _CanonicalURIs.CATEGORY)
        slugs: List[str] = []
        seen: Set[str] = set()

        for cat_id in cat_ids:
            cat_edges = edges_by_subject.get(cat_id, [])
            slug = self._first_literal(cat_edges, _CanonicalURIs.CATEGORY_SLUG)
            if not slug:
                # Derive slug from URI if not explicitly set
                cat_node = nodes.get(cat_id, {})
                uri = cat_node.get("uri") or ""
                if uri:
                    slug = uri.rstrip("/").split("/")[-1]

            if slug:
                normalized = str(slug).strip().lower()
                if normalized and normalized not in seen:
                    slugs.append(normalized)
                    seen.add(normalized)

        return slugs

    def _extract_project_type_label(
        self,
        subject_edges: List[Dict[str, Any]],
        edges_by_subject: Dict[str, List[Dict[str, Any]]],
        nodes: Dict[str, Dict[str, Any]],
    ) -> str:
        """Extract project type label from project's type relation."""
        type_ids = self._related_ids(subject_edges, _CanonicalURIs.PROJECT_TYPE_LINK)
        if not type_ids:
            return ""

        type_id = type_ids[0]
        type_edges = edges_by_subject.get(type_id, [])
        label = self._first_literal(type_edges, _CanonicalURIs.PROJECT_TYPE_NAME)
        if label:
            return label

        # Fallback to node name
        type_node = nodes.get(type_id, {})
        return type_node.get("name") or type_node.get("value") or ""

    def _extract_catchphrase_labels(
        self,
        subject_edges: List[Dict[str, Any]],
        edges_by_subject: Dict[str, List[Dict[str, Any]]],
        nodes: Dict[str, Dict[str, Any]],
    ) -> List[str]:
        """Extract catchphrase/keyword labels from project's catchphrase relations."""
        cp_ids = self._related_ids(subject_edges, _CanonicalURIs.CATCHPHRASE)
        labels: List[str] = []
        seen: Set[str] = set()

        for cp_id in cp_ids:
            cp_edges = edges_by_subject.get(cp_id, [])
            label = self._first_literal(cp_edges, _CanonicalURIs.CATCHPHRASE_NAME)
            if not label:
                cp_node = nodes.get(cp_id, {})
                label = cp_node.get("name") or cp_node.get("value")

            if label:
                normalized = str(label).strip()
                if normalized and normalized not in seen:
                    labels.append(normalized)
                    seen.add(normalized)

        return labels

    def _extract_year_values(
        self,
        subject_edges: List[Dict[str, Any]],
        edges_by_subject: Dict[str, List[Dict[str, Any]]],
    ) -> List[int]:
        """Extract year values as list from project's events."""
        event_ids = self._related_ids(subject_edges, _CanonicalURIs.EVENT)
        years: Set[int] = set()

        for event_id in event_ids:
            event_edges = edges_by_subject.get(event_id, [])
            start = self._first_literal(event_edges, _CanonicalURIs.EVENT_START)
            end = self._first_literal(event_edges, _CanonicalURIs.EVENT_END)

            for val in (start, end):
                year = _coerce_year(val)
                if year:
                    years.add(year)

        return sorted(years)

    def _build_record_jsonb_from_graph(
        self,
        *,
        project_uri: str,
        subject_id: str,
        title: str,
        subtitle: str,
        description: str,
        image: str,
        institution_label: str,
        categories: List[str],
        category_slugs: List[str],
        actor_names: List[str],
        year_range: str,
        project_type_label: str,
        catchphrase_labels: List[str],
        digital_object_paths: List[str],
        institution_codes: List[str],
    ) -> Dict[str, Any]:
        """Build a JSON-serializable dict for record_jsonb field."""
        return {
            "uri": project_uri,
            "subject_id": subject_id,
            "title": title,
            "subtitle": subtitle,
            "description": description,
            "image": image,
            "year_range": year_range,
            "institution": {"label": institution_label} if institution_label else None,
            "institution_codes": institution_codes,
            "project_type": {"label": project_type_label} if project_type_label else None,
            "categories": [{"label": c, "slug": s} for c, s in zip(categories, category_slugs or categories)],
            "actors": [{"name": n, "roles": []} for n in actor_names],
            "catchphrases": [{"label": c} for c in catchphrase_labels],
            "digital_objects": [{"path": p} for p in digital_object_paths],
            "events": [],
            "alternative_titles": [],
            "category_slugs": category_slugs,
        }

    # ------------------------------------------------------------------ #
    # Structured data extractors for ProjectDetailIndex                   #
    # ------------------------------------------------------------------ #

    def _extract_institution_uri(
        self,
        subject_edges: List[Dict[str, Any]],
        nodes: Dict[str, Dict[str, Any]],
    ) -> str:
        """Extract institution URI from project's institution relation."""
        inst_ids = self._related_ids(subject_edges, _CanonicalURIs.INSTITUTION)
        if not inst_ids:
            return ""
        inst_node = nodes.get(inst_ids[0], {})
        return inst_node.get("uri") or ""

    def _extract_categories_structured(
        self,
        subject_edges: List[Dict[str, Any]],
        edges_by_subject: Dict[str, List[Dict[str, Any]]],
        nodes: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, str]]:
        """Extract category data as structured dicts for ProjectDetailIndex."""
        cat_ids = self._related_ids(subject_edges, _CanonicalURIs.CATEGORY)
        categories: List[Dict[str, str]] = []

        for cat_id in cat_ids:
            cat_edges = edges_by_subject.get(cat_id, [])
            cat_node = nodes.get(cat_id, {})

            label = self._first_literal(cat_edges, _CanonicalURIs.CATEGORY_NAME)
            if not label:
                label = cat_node.get("name") or cat_node.get("value") or ""

            slug = self._first_literal(cat_edges, _CanonicalURIs.CATEGORY_SLUG)
            if not slug:
                uri = cat_node.get("uri") or ""
                slug = uri.rstrip("/").split("/")[-1] if uri else ""

            uri = cat_node.get("uri") or ""

            if label:
                categories.append({
                    "label": str(label).strip(),
                    "uri": uri,
                    "slug": str(slug).strip().lower() if slug else "",
                })

        return categories

    def _extract_actors_structured(
        self,
        subject_edges: List[Dict[str, Any]],
        edges_by_subject: Dict[str, List[Dict[str, Any]]],
        nodes: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Extract actor data with roles as structured dicts for ProjectDetailIndex."""
        event_ids = self._related_ids(subject_edges, _CanonicalURIs.EVENT)
        actors: List[Dict[str, Any]] = []
        seen_names: Set[str] = set()

        for event_id in event_ids:
            event_edges = edges_by_subject.get(event_id, [])

            # Try junction table approach first (akteurinnen-am-ereignis)
            junction_ids = self._related_ids(event_edges, _CanonicalURIs.EVENT_ACTOR_JUNCTION)

            for junction_id in junction_ids:
                junction_edges = edges_by_subject.get(junction_id, [])
                actor_ids = self._related_ids(junction_edges, _CanonicalURIs.ACTOR_LINK)

                # Get role from junction
                role = self._first_literal(junction_edges, _CanonicalURIs.ACTOR_ROLE)

                for actor_id in actor_ids:
                    actor_edges = edges_by_subject.get(actor_id, [])
                    actor_node = nodes.get(actor_id, {})

                    name = self._first_literal(actor_edges, _CanonicalURIs.ACTOR_NAME)
                    if not name:
                        name = actor_node.get("name") or actor_node.get("value")

                    if name:
                        normalized = str(name).strip()
                        if normalized not in seen_names:
                            actors.append({
                                "name": normalized,
                                "roles": [role] if role else [],
                                "uri": actor_node.get("uri") or "",
                            })
                            seen_names.add(normalized)

            # Also try direct event->actor links (both FUK and KHM/HMT patterns)
            for direct_uri in (_CanonicalURIs.EVENT_DIRECT_ACTOR_FUK, _CanonicalURIs.EVENT_DIRECT_ACTOR_KHM):
                direct_actor_ids = self._related_ids(event_edges, direct_uri)
                for actor_id in direct_actor_ids:
                    actor_edges = edges_by_subject.get(actor_id, [])
                    actor_node = nodes.get(actor_id, {})

                    name = self._first_literal(actor_edges, _CanonicalURIs.ACTOR_NAME)
                    if not name:
                        name = actor_node.get("name") or actor_node.get("value")

                    # Get role from actor's junction link (akteurin-im-ereignis -> role)
                    actor_junction_ids = self._related_ids(actor_edges, _CanonicalURIs.ACTOR_LINK)
                    role = None
                    for aj_id in actor_junction_ids:
                        aj_edges = edges_by_subject.get(aj_id, [])
                        role = self._first_literal(aj_edges, _CanonicalURIs.ACTOR_ROLE)
                        if role:
                            break

                    if name:
                        normalized = str(name).strip()
                        if normalized not in seen_names:
                            actors.append({
                                "name": normalized,
                                "roles": [role] if role else [],
                                "uri": actor_node.get("uri") or "",
                            })
                            seen_names.add(normalized)

        return actors

    def _extract_events_structured(
        self,
        subject_edges: List[Dict[str, Any]],
        edges_by_subject: Dict[str, List[Dict[str, Any]]],
        nodes: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Extract event data as structured dicts for ProjectDetailIndex."""
        event_ids = self._related_ids(subject_edges, _CanonicalURIs.EVENT)
        events: List[Dict[str, Any]] = []

        for event_id in event_ids:
            event_edges = edges_by_subject.get(event_id, [])
            event_node = nodes.get(event_id, {})

            # Try primary event name, then alternative
            event_name = self._first_literal(event_edges, _CanonicalURIs.EVENT_NAME)
            if not event_name:
                event_name = self._first_literal(event_edges, _CanonicalURIs.EVENT_NAME_ALT)
            if not event_name:
                event_name = event_node.get("name") or event_node.get("value") or ""

            start = self._first_literal(event_edges, _CanonicalURIs.EVENT_START)
            end = self._first_literal(event_edges, _CanonicalURIs.EVENT_END)
            location = self._first_literal(event_edges, _CanonicalURIs.EVENT_LOCATION)

            # Extract actors for this event
            event_actors = self._extract_event_actors(event_edges, edges_by_subject, nodes)

            # Build display date
            if start and end:
                display_date = start if start == end else f"{start} – {end}"
            else:
                display_date = start or end or None

            events.append({
                "id": event_id,
                "uri": event_node.get("uri") or "",
                "name": event_name,
                "start": start,
                "end": end,
                "location": location,
                "actors": event_actors,
                "display_date": display_date,
            })

        return events

    def _extract_event_actors(
        self,
        event_edges: List[Dict[str, Any]],
        edges_by_subject: Dict[str, List[Dict[str, Any]]],
        nodes: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Extract actors for a specific event."""
        actors: List[Dict[str, Any]] = []
        seen_names: Set[str] = set()

        # Try junction table approach (akteurinnen-am-ereignis)
        junction_ids = self._related_ids(event_edges, _CanonicalURIs.EVENT_ACTOR_JUNCTION)

        for junction_id in junction_ids:
            junction_edges = edges_by_subject.get(junction_id, [])
            actor_ids = self._related_ids(junction_edges, _CanonicalURIs.ACTOR_LINK)
            role = self._first_literal(junction_edges, _CanonicalURIs.ACTOR_ROLE)

            for actor_id in actor_ids:
                actor_edges = edges_by_subject.get(actor_id, [])
                actor_node = nodes.get(actor_id, {})

                name = self._first_literal(actor_edges, _CanonicalURIs.ACTOR_NAME)
                if not name:
                    name = actor_node.get("name") or actor_node.get("value")

                if name:
                    normalized = str(name).strip()
                    if normalized not in seen_names:
                        actors.append({
                            "name": normalized,
                            "roles": [role] if role else [],
                        })
                        seen_names.add(normalized)

        # Also try direct event->actor links (both FUK and KHM/HMT patterns)
        for direct_uri in (_CanonicalURIs.EVENT_DIRECT_ACTOR_FUK, _CanonicalURIs.EVENT_DIRECT_ACTOR_KHM):
            direct_actor_ids = self._related_ids(event_edges, direct_uri)
            for actor_id in direct_actor_ids:
                actor_edges = edges_by_subject.get(actor_id, [])
                actor_node = nodes.get(actor_id, {})

                name = self._first_literal(actor_edges, _CanonicalURIs.ACTOR_NAME)
                if not name:
                    name = actor_node.get("name") or actor_node.get("value")

                # Get role from actor's junction link
                actor_junction_ids = self._related_ids(actor_edges, _CanonicalURIs.ACTOR_LINK)
                role = None
                for aj_id in actor_junction_ids:
                    aj_edges = edges_by_subject.get(aj_id, [])
                    role = self._first_literal(aj_edges, _CanonicalURIs.ACTOR_ROLE)
                    if role:
                        break

                if name:
                    normalized = str(name).strip()
                    if normalized not in seen_names:
                        actors.append({
                            "name": normalized,
                            "roles": [role] if role else [],
                        })
                        seen_names.add(normalized)

        return actors

    def _extract_digital_objects_structured(
        self,
        subject_edges: List[Dict[str, Any]],
        edges_by_subject: Dict[str, List[Dict[str, Any]]],
        nodes: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, str]]:
        """Extract digital object data as structured dicts for ProjectDetailIndex."""
        do_ids = self._related_ids(subject_edges, _CanonicalURIs.DIGITAL_OBJECT)
        objects: List[Dict[str, str]] = []

        for do_id in do_ids:
            do_edges = edges_by_subject.get(do_id, [])
            do_node = nodes.get(do_id, {})

            path = self._first_literal(do_edges, _CanonicalURIs.DO_PATH)
            if path:
                objects.append({
                    "path": str(path).strip(),
                    "uri": do_node.get("uri") or "",
                })

        return objects
