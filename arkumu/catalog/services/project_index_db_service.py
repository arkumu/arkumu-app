from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from django.db import transaction
from django.utils import timezone

from arkumu.catalog.models import ProjectIndex
from arkumu.catalog.services.project_detail_index_service import ProjectDetailIndexService
from arkumu.catalog.services.triple_relationship_service import TripleRelationshipService
from arkumu.common.hash_utils import generate_value_hash
from arkumu.metadata.models import PublicAccessLevel, Resource, ResourceType
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
    DESCRIPTION_DE = "http://arkumu.org/data/properties/deutsche-beschreibung"
    DESCRIPTION_DE_CONTENT = "http://arkumu.org/data/properties/deutsche-inhaltliche-beschreibung"
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

    # Actor junction properties (FUK uses junction table that links TO events/actors)
    JUNCTION_TO_EVENT = "http://arkumu.org/data/properties/im-ereignis"  # junction -> event (FUK)
    JUNCTION_TO_PROJECT = "http://arkumu.org/data/properties/projekt"  # junction -> project (KHM)
    ACTOR_LINK = "http://arkumu.org/data/properties/akteurin-im-ereignis"  # junction -> actor
    ACTOR_ROLE = "http://arkumu.org/data/properties/rollen-der-akteurin-im-ereignis"  # junction -> rolle

    # Actor properties
    ACTOR_NAME = "http://arkumu.org/data/properties/deutscher-name"

    # Role properties (rolle entity -> name)
    ROLE_GERMAN_NAME = "http://arkumu.org/data/properties/deutscher-name-der-rolle-breadcrumb"

    # Institution properties
    INSTITUTION_NAME = "http://arkumu.org/data/properties/deutscher-name-der-einliefernden-hochschule"

    # Category properties
    CATEGORY_NAME = "http://arkumu.org/data/properties/deutscher-name-der-projektkategorie-breadcrumb"
    CATEGORY_SLUG = "http://arkumu.org/data/properties/slug-der-projektkategorie"
    CATEGORY_WIKIDATA = "http://arkumu.org/data/properties/wikidata-id"

    # Schlagwort properties (fallback for orgs that map categories to schlagwort)
    SCHLAGWORT_NAME = "http://arkumu.org/data/properties/deutscher-name-des-schlagworts"
    SCHLAGWORT_WIKIDATA_LABEL = "http://arkumu.org/data/properties/deutsches-wikidata-label"

    # Project type properties
    PROJECT_TYPE_NAME = "http://arkumu.org/data/properties/deutscher-name-der-projektart"

    # Catchphrase properties
    CATCHPHRASE_NAME = "http://arkumu.org/data/properties/deutscher-name-des-schlagworts"

    # Digital object properties (for image path resolution)
    DO_PATH = "http://arkumu.org/data/properties/dateipfad"

    # License properties
    LICENSE_EXISTING = "http://arkumu.org/data/properties/bestehender-lizenzvertrag"
    LICENSE_NEW = "http://arkumu.org/data/properties/neuer-lizenzvertrag-digi-kunst-formular"
    LICENSE_USAGE_RIGHTS = "http://arkumu.org/data/properties/angegebene-nutzungsrechte"
    LICENSE_SPECIAL_TERMS = "http://arkumu.org/data/properties/sonderregelung"
    LICENSE_OTHER_DOCS = "http://arkumu.org/data/properties/weiteres-rechtsdokument"
    LICENSE_FILE_REQUEST = "http://arkumu.org/data/properties/dateiabfragedokument"

    # Property metadata URIs
    PROPERTY_LANGUAGE_TITLE = "http://arkumu.org/data/properties/sprache-des-bevorzugten-titels"
    PROPERTY_LANGUAGE_SUBTITLE = "http://arkumu.org/data/properties/sprache-des-bevorzugten-untertitels"
    PROPERTY_DAUER_FREITEXT = "http://arkumu.org/data/properties/dauer-freitext"
    PROPERTY_PRODUKTIONSFORMAT = "http://arkumu.org/data/properties/produktionsformat"
    PROPERTY_INSTRUMENTIERUNG = "http://arkumu.org/data/properties/instrumentierung"
    PROPERTY_ASPECT_RATIO = "http://arkumu.org/data/properties/aspect-ratio-bildseitenverhaeltnis"
    PROPERTY_ABSPIELGESCHWINDIGKEIT = "http://arkumu.org/data/properties/abspielgeschwindigkeit"
    PROPERTY_FERNSEHNORM = "http://arkumu.org/data/properties/fernsehnorm"
    PROPERTY_BILDFREQUENZ = "http://arkumu.org/data/properties/bildfrequenz"

    # Status/signatur URIs
    STATUS_SIGNATUR = "http://arkumu.org/data/properties/externe-inventar-signaturnummer"
    STATUS_SIGNATUR_EINLIEFERER = "http://arkumu.org/data/properties/signatur-beim-einlieferer"
    STATUS_DATENSATZ_ID = "http://arkumu.org/data/properties/datensatz-id-beim-einlieferer"

    # Authority/normdaten URIs
    AUTHORITY_WIKIDATA = "http://arkumu.org/data/properties/wikidata-id"
    AUTHORITY_GND = "http://arkumu.org/data/properties/gnd-nummer"
    AUTHORITY_EXTERNE_WEBSEITE = "http://arkumu.org/data/properties/externe-projektwebseite"

    # Predicate whitelists for efficient graph queries
    @classmethod
    def project_predicates(cls) -> List[str]:
        return [
            cls.TITLE,
            cls.SUBTITLE,
            cls.DESCRIPTION,
            cls.DESCRIPTION_ENTITY,
            cls.DESCRIPTION_DE,
            cls.DESCRIPTION_DE_CONTENT,
            cls.EVENT_DESCRIPTION,  # KHM maps project descriptions to this
            cls.IMAGE,
            cls.EVENT,
            cls.INSTITUTION,
            cls.CATEGORY,
            cls.DIGITAL_OBJECT,
            cls.PROJECT_TYPE_LINK,
            cls.CATCHPHRASE,
            # License properties
            cls.LICENSE_EXISTING,
            cls.LICENSE_NEW,
            cls.LICENSE_USAGE_RIGHTS,
            cls.LICENSE_SPECIAL_TERMS,
            cls.LICENSE_OTHER_DOCS,
            cls.LICENSE_FILE_REQUEST,
            # Property metadata
            cls.PROPERTY_LANGUAGE_TITLE,
            cls.PROPERTY_LANGUAGE_SUBTITLE,
            cls.PROPERTY_DAUER_FREITEXT,
            cls.PROPERTY_PRODUKTIONSFORMAT,
            cls.PROPERTY_INSTRUMENTIERUNG,
            cls.PROPERTY_ASPECT_RATIO,
            cls.PROPERTY_ABSPIELGESCHWINDIGKEIT,
            cls.PROPERTY_FERNSEHNORM,
            cls.PROPERTY_BILDFREQUENZ,
            # Status
            cls.STATUS_SIGNATUR,
            cls.STATUS_SIGNATUR_EINLIEFERER,
            cls.STATUS_DATENSATZ_ID,
            # Authority
            cls.AUTHORITY_WIKIDATA,
            cls.AUTHORITY_GND,
            cls.AUTHORITY_EXTERNE_WEBSEITE,
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
            cls.ROLE_GERMAN_NAME,  # For rolle entity name lookup
            cls.ACTOR_NAME,
            cls.INSTITUTION_NAME,
            cls.CATEGORY_NAME,
            cls.CATEGORY_SLUG,
            cls.CATEGORY_WIKIDATA,
            cls.SCHLAGWORT_NAME,
            cls.SCHLAGWORT_WIKIDATA_LABEL,
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

            defaults = self._unified_defaults(record, resource, built_at, source_version)
            index_rows.append(ProjectIndex(project_resource=resource, **defaults))
            seen_ids.add(resource.id)

        with transaction.atomic():
            if not index_rows:
                if prune_missing:
                    ProjectIndex.objects.all().delete()
                return {"project_index": 0}

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
                    "description",
                    "image",
                    "year_range",
                    "institution_label",
                    "institution_uri",
                    "institution_codes",
                    "project_type_label",
                    "category_labels",
                    "category_slugs",
                    "actor_names",
                    "year_values",
                    "catchphrase_labels",
                    "digital_object_paths",
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
                    "record_jsonb",
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

        return {"project_index": len(index_rows)}

    def _unified_defaults(
        self,
        record: ProjectRecord,
        resource: Resource,
        built_at,
        source_version: str,
    ) -> Dict[str, object]:
        """Build defaults for the unified ProjectIndex model."""
        org_code = self._org_code(resource)
        institution_label = self._institution_label(record)
        category_labels = self._category_labels(record)
        actor_names = self._actor_names(record)
        digital_object_paths = self._digital_object_paths(record)
        year_values = self._year_values(record)
        catchphrase_labels = [
            cp.label for cp in (record.catchphrases or []) if getattr(cp, "label", None)
        ]

        # Build structured data for detail views
        categories_structured = [
            {"label": cat.label, "uri": getattr(cat, "uri", ""), "slug": getattr(cat, "slug", "")}
            for cat in (record.categories or [])
            if getattr(cat, "label", None)
        ]
        actors_structured = [
            {"name": act.name, "roles": list(getattr(act, "roles", []) or []), "uri": getattr(act, "uri", "")}
            for act in (record.actors or [])
            if getattr(act, "name", None)
        ]
        events_structured = [
            {
                "id": getattr(evt, "id", ""),
                "name": getattr(evt, "name", ""),
                "start": getattr(evt, "start", ""),
                "end": getattr(evt, "end", ""),
                "location": getattr(evt, "location", ""),
                "actors": [
                    {"name": a.name, "roles": list(getattr(a, "roles", []) or [])}
                    for a in (getattr(evt, "actors", []) or [])
                    if getattr(a, "name", None)
                ],
            }
            for evt in (record.events or [])
        ]
        digital_objects_structured = [
            {"path": _display_path(obj) or "", "uri": getattr(obj, "uri", "")}
            for obj in (record.digital_objects or [])
        ]

        return {
            "uri": record.uri,
            "org_code": org_code,
            "public_access_level": getattr(resource, "public_access_level", PublicAccessLevel.RESTRICTED),
            "is_public_approved": bool(getattr(resource, "is_public_approved", False)),
            "is_derived": bool(getattr(resource, "is_public", False)),
            # Core display fields
            "title": record.title or "",
            "subtitle": record.subtitle or "",
            "description": record.description or "",
            "image": record.image or "",
            "year_range": record.year_range or self._derive_year_range(record) or "",
            # Relationships
            "institution_label": institution_label,
            "institution_uri": getattr(getattr(record, "institution", None), "uri", "") or "",
            "institution_codes": list(record.institution_codes or []) or ([org_code] if org_code else []),
            "project_type_label": getattr(getattr(record, "project_type", None), "label", "") or "",
            # Flat arrays for search
            "category_labels": category_labels,
            "category_slugs": list(record.category_slugs or []),
            "actor_names": actor_names,
            "year_values": year_values,
            "catchphrase_labels": catchphrase_labels,
            "digital_object_paths": digital_object_paths,
            # Structured JSON for detail views
            "categories": categories_structured,
            "actors": actors_structured,
            "events": events_structured,
            "digital_objects": digital_objects_structured,
            "alternative_titles": [
                {"value": t.value} for t in (getattr(record, "alternative_titles", []) or [])
                if getattr(t, "value", None)
            ],
            "catchphrases": [{"label": c} for c in catchphrase_labels],
            # Metadata bundles (empty for snapshot-based rebuild)
            "properties": {},
            "status": {},
            "authority": {},
            "submitter": {},
            "licenses": {},
            "rights_status": {},
            # Full record JSON
            "record_jsonb": record.to_dict(),
            # Flags
            "reference_only": bool(getattr(record, "reference_only", False)),
            "harvestable": bool(getattr(record, "harvestable", True)),
            "ownership_filtered": bool(getattr(record, "ownership_filtered", False)),
            # Metadata
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
            return {"project_index": 0}

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

        # Discover junction entities for FUK/KHM data models (batch pre-fetch)
        project_subject_id_set = set(str(sid) for sid in subject_ids)
        self._expand_event_junctions(edges_by_subject, nodes, project_subject_id_set)

        # Build reverse indexes for O(1) junction lookup
        self._junctions_by_event: Dict[str, List[str]] = {}
        self._junctions_by_project: Dict[str, List[str]] = {}
        for subj_id, subj_edges in edges_by_subject.items():
            for edge in subj_edges:
                pred = self._canonical(edge)
                obj_id = edge.get("object_id")
                if pred == _CanonicalURIs.JUNCTION_TO_EVENT and obj_id:
                    self._junctions_by_event.setdefault(obj_id, []).append(subj_id)
                elif pred == _CanonicalURIs.JUNCTION_TO_PROJECT and obj_id:
                    self._junctions_by_project.setdefault(obj_id, []).append(subj_id)

        # PRE-COMPUTE all fields for all projects in ONE pass
        logger.debug("rebuild_from_graph: pre-computing all fields for %d projects", len(subject_ids))
        self._project_cache = self._batch_precompute_all_fields(
            subject_ids, edges_by_subject, nodes
        )
        logger.debug("rebuild_from_graph: all fields pre-computed for %d projects", len(self._project_cache))

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
        """Transform graph data into unified ProjectIndex rows."""
        seen_ids: Set[uuid.UUID] = set()
        index_rows: List[ProjectIndex] = []
        total = len(subject_ids)

        for idx, subject_id in enumerate(subject_ids):
            if idx % 500 == 0:
                logger.debug("_write_indexes_from_graph: processing %d/%d", idx, total)
            subject_uuid = _as_uuid(subject_id)
            if not subject_uuid:
                continue

            resource = resource_map.get(subject_uuid)
            if not resource:
                logger.debug("rebuild_from_graph: resource not found for %s", subject_id)
                continue

            subject_id_str = str(subject_id)
            node = nodes.get(subject_id_str, {})
            project_uri = node.get("uri") or node.get("canonical_uri")
            if not project_uri:
                continue

            # Use pre-computed cache (O(1) lookup) - all fields extracted in batch
            cached = self._project_cache.get(subject_id_str, {})
            if not cached:
                continue

            # Get edges for property/status/authority extractors (not pre-computed)
            subject_edges = edges_by_subject.get(subject_id_str, [])

            title = cached.get("title")
            if not title:
                continue

            subtitle = cached.get("subtitle")
            description = cached.get("description")
            image = cached.get("image")
            institution_label = cached.get("institution_label", "")
            institution_uri = cached.get("institution_uri", "")
            category_labels = cached.get("category_labels", [])
            category_slugs = cached.get("category_slugs", [])
            categories_structured = cached.get("categories_structured", [])
            project_type_label = cached.get("project_type_label", "")
            catchphrase_labels = cached.get("catchphrase_labels", [])
            actor_names = cached.get("actor_names", [])
            actors_structured = cached.get("actors_structured", [])
            events_structured = cached.get("events_structured", [])
            year_range = cached.get("year_range", "")
            year_values = cached.get("year_values", [])
            digital_object_paths = cached.get("digital_object_paths", [])
            digital_objects_structured = cached.get("digital_objects_structured", [])

            org_code = self._org_code(resource)
            institution_codes = [org_code] if org_code else []

            # Build record_jsonb
            record_jsonb = self._build_record_jsonb_from_graph(
                project_uri=project_uri,
                subject_id=subject_id_str,
                title=title or "",
                subtitle=subtitle or "",
                description=description or "",
                image=image or "",
                institution_label=institution_label or "",
                categories=category_labels,
                category_slugs=category_slugs,
                actor_names=actor_names,
                year_range=year_range or "",
                project_type_label=project_type_label or "",
                catchphrase_labels=catchphrase_labels,
                digital_object_paths=digital_object_paths,
                institution_codes=institution_codes,
            )

            # Build unified ProjectIndex row
            index_row = ProjectIndex(
                project_resource=resource,
                uri=project_uri,
                org_code=org_code,
                public_access_level=getattr(resource, "public_access_level", PublicAccessLevel.RESTRICTED),
                is_public_approved=bool(getattr(resource, "is_public_approved", False)),
                is_derived=bool(getattr(resource, "is_public", False)),
                # Core display fields
                title=title or "",
                subtitle=subtitle or "",
                description=description or "",
                image=image or "",
                year_range=year_range or "",
                # Relationships
                institution_label=institution_label or "",
                institution_uri=institution_uri or "",
                institution_codes=institution_codes,
                project_type_label=project_type_label or "",
                # Flat arrays for search
                category_labels=category_labels,
                category_slugs=category_slugs,
                actor_names=actor_names,
                year_values=year_values,
                catchphrase_labels=catchphrase_labels,
                digital_object_paths=digital_object_paths,
                # Structured JSON for detail views
                categories=categories_structured,
                actors=actors_structured,
                events=events_structured,
                digital_objects=digital_objects_structured,
                alternative_titles=[],
                catchphrases=[{"label": c} for c in catchphrase_labels],
                # Metadata bundles
                properties=self._extract_properties(subject_edges),
                status=self._extract_status(subject_edges),
                authority=self._extract_authority(subject_edges),
                submitter={},
                licenses=self._extract_licenses(subject_edges),
                rights_status={},
                # Full record JSON
                record_jsonb=record_jsonb,
                # Flags
                reference_only=False,
                harvestable=True,
                ownership_filtered=False,
                # Metadata
                source_updated_at=getattr(resource, "updated_at", None),
                built_at=built_at,
                source_version=source_version,
            )
            index_rows.append(index_row)
            seen_ids.add(resource.id)

        # Bulk write
        with transaction.atomic():
            if not index_rows:
                if prune_missing:
                    ProjectIndex.objects.all().delete()
                return {"project_index": 0}

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
                    "description",
                    "image",
                    "year_range",
                    "institution_label",
                    "institution_uri",
                    "institution_codes",
                    "project_type_label",
                    "category_labels",
                    "category_slugs",
                    "actor_names",
                    "year_values",
                    "catchphrase_labels",
                    "digital_object_paths",
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
                    "record_jsonb",
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

        logger.info("rebuild_from_graph: wrote %d ProjectIndex rows (prune=%s)", len(index_rows), prune_missing)
        return {"project_index": len(index_rows)}

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

    def _get_role_names_from_junction(
        self,
        junction_edges: List[Dict[str, Any]],
        edges_by_subject: Dict[str, List[Dict[str, Any]]],
    ) -> List[str]:
        """Extract role names from junction edges.

        Supports two patterns:
        1. FUK: junction -> rollen-der-akteurin-im-ereignis -> rolle entity
                rolle entity -> deutscher-name-der-rolle-breadcrumb -> name literal
        2. KHM/HMT: junction -> rollen-der-akteurin-im-ereignis -> literal value directly
        """
        roles: List[str] = []

        for edge in junction_edges:
            if self._canonical(edge) != _CanonicalURIs.ACTOR_ROLE:
                continue

            # Pattern 2: KHM/HMT - role stored as literal value directly
            literal_value = edge.get("object_value")
            if literal_value:
                role_name = str(literal_value).strip()
                if role_name and role_name not in roles:
                    roles.append(role_name)
                continue

            # Pattern 1: FUK - role is entity link, need two-step lookup
            role_id = edge.get("object_id")
            if role_id:
                role_edges = edges_by_subject.get(str(role_id), [])
                role_name = self._first_literal(role_edges, _CanonicalURIs.ROLE_GERMAN_NAME)
                if role_name:
                    # Extract final part after '>' if breadcrumb format
                    if '>' in role_name:
                        role_name = role_name.split('>')[-1].strip()
                    if role_name and role_name not in roles:
                        roles.append(role_name)

        return roles

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

            # Fetch rolle entity edges (ACTOR_ROLE is now a link to rolle entities)
            rolle_ids: Set[str] = set()
            for edge in junction_edges:
                edge_dict = edge.__dict__ if hasattr(edge, "__dict__") else edge
                obj_id = edge_dict.get("object_id") if isinstance(edge_dict, dict) else getattr(edge_dict, "object_id", None)
                if obj_id:
                    rolle_ids.add(str(obj_id))

            if rolle_ids:
                rolle_edges = graph_service._fetch_triples_for_subjects(
                    list(rolle_ids),
                    [_CanonicalURIs.ROLE_GERMAN_NAME],
                )
                for edge in rolle_edges:
                    edge_dict = edge.__dict__ if hasattr(edge, "__dict__") else edge
                    subject_id = str(edge_dict.get("subject_id", ""))
                    if subject_id:
                        edges_by_subject.setdefault(subject_id, []).append(edge_dict)

    def _expand_event_junctions(
        self,
        edges_by_subject: Dict[str, List[Dict[str, Any]]],
        nodes: Dict[str, Dict[str, Any]],
        project_subject_ids: Optional[Set[str]] = None,
    ) -> None:
        """Discover and expand junction entities that link TO events or projects.

        Supports two patterns:
        1. FUK: Junction -> im-ereignis -> Event (akteurin-ereignis-kreuztabelle)
        2. KHM: Junction -> projekt -> Project (kreuz-projekte-personen)

        Both patterns have:
        - Junction -> akteurin-im-ereignis -> Actor
        - Junction -> rollen-der-akteurin-im-ereignis -> Rolle (or literal)

        This method queries the database to find junctions and adds their edges.
        """
        from arkumu.metadata.models import Triple

        # Collect event IDs from the graph (events are neighbors of projects)
        event_ids: Set[str] = set()
        for subject_id, subject_edges in edges_by_subject.items():
            for edge in subject_edges:
                predicate = self._canonical(edge)
                if predicate == _CanonicalURIs.EVENT:
                    event_id = edge.get("object_id")
                    if event_id:
                        event_ids.add(str(event_id))

        junction_ids: Set[str] = set()

        # Pattern 1: FUK - junctions that link TO events via im-ereignis
        if event_ids:
            logger.debug("_expand_event_junctions: finding junctions for %d events", len(event_ids))

            junction_triples = Triple.objects.filter(
                predicate__canonical_uri=_CanonicalURIs.JUNCTION_TO_EVENT,
                object_id__in=[_as_uuid(eid) for eid in event_ids if _as_uuid(eid)],
            ).select_related("subject", "predicate", "object")

            for t in junction_triples:
                junction_id = str(t.subject_id)
                junction_ids.add(junction_id)
                # Add the im-ereignis edge to the graph
                edges_by_subject.setdefault(junction_id, []).append({
                    "subject_id": junction_id,
                    "predicate_canonical": _CanonicalURIs.JUNCTION_TO_EVENT,
                    "object_id": str(t.object_id) if t.object_id else None,
                })

        # Pattern 2: KHM - junctions that link TO projects via projekt
        if project_subject_ids:
            logger.debug("_expand_event_junctions: finding junctions for %d projects", len(project_subject_ids))

            project_junction_triples = Triple.objects.filter(
                predicate__canonical_uri=_CanonicalURIs.JUNCTION_TO_PROJECT,
                object_id__in=[_as_uuid(pid) for pid in project_subject_ids if _as_uuid(pid)],
            ).select_related("subject", "predicate", "object")

            for t in project_junction_triples:
                junction_id = str(t.subject_id)
                junction_ids.add(junction_id)
                # Add the projekt edge to the graph
                edges_by_subject.setdefault(junction_id, []).append({
                    "subject_id": junction_id,
                    "predicate_canonical": _CanonicalURIs.JUNCTION_TO_PROJECT,
                    "object_id": str(t.object_id) if t.object_id else None,
                })

        if not junction_ids:
            logger.debug("_expand_event_junctions: no junctions found")
            return

        logger.debug("_expand_event_junctions: found %d junctions", len(junction_ids))

        # Fetch junction edges: actor links and role links
        junction_edge_triples = Triple.objects.filter(
            subject_id__in=[_as_uuid(jid) for jid in junction_ids if _as_uuid(jid)],
            predicate__canonical_uri__in=[
                _CanonicalURIs.ACTOR_LINK,
                _CanonicalURIs.ACTOR_ROLE,
            ],
        ).select_related("predicate", "object")

        rolle_ids: Set[str] = set()
        actor_ids: Set[str] = set()

        for t in junction_edge_triples:
            junction_id = str(t.subject_id)
            pred_canonical = t.predicate.canonical_uri

            # Check if object is a literal (KHM pattern) or entity (FUK pattern)
            # For literals, object.resource_type == 'LITERAL' and value is in object.value
            is_literal = t.object.resource_type == ResourceType.LITERAL if t.object else False
            object_value = t.object.value if (t.object and is_literal) else None

            edge_dict = {
                "subject_id": junction_id,
                "predicate_canonical": pred_canonical,
                "object_id": str(t.object_id) if t.object_id and not is_literal else None,
                "object_value": object_value,
            }
            edges_by_subject.setdefault(junction_id, []).append(edge_dict)

            # Collect rolle and actor IDs for further expansion (only for entity links)
            if pred_canonical == _CanonicalURIs.ACTOR_ROLE and t.object_id and not is_literal:
                rolle_ids.add(str(t.object_id))
            if pred_canonical == _CanonicalURIs.ACTOR_LINK and t.object_id:
                actor_ids.add(str(t.object_id))

        # Fetch rolle entity name edges
        if rolle_ids:
            rolle_name_triples = Triple.objects.filter(
                subject_id__in=[_as_uuid(rid) for rid in rolle_ids if _as_uuid(rid)],
                predicate__canonical_uri=_CanonicalURIs.ROLE_GERMAN_NAME,
            ).select_related("predicate", "object")

            for t in rolle_name_triples:
                rolle_id = str(t.subject_id)
                edges_by_subject.setdefault(rolle_id, []).append({
                    "subject_id": rolle_id,
                    "predicate_canonical": _CanonicalURIs.ROLE_GERMAN_NAME,
                    "object_value": t.object.value if t.object else None,
                })

        # Fetch actor name edges (for actors found via junctions)
        if actor_ids:
            actor_name_triples = Triple.objects.filter(
                subject_id__in=[_as_uuid(aid) for aid in actor_ids if _as_uuid(aid)],
                predicate__canonical_uri=_CanonicalURIs.ACTOR_NAME,
            ).select_related("predicate", "object", "subject")

            for t in actor_name_triples:
                actor_id = str(t.subject_id)
                edges_by_subject.setdefault(actor_id, []).append({
                    "subject_id": actor_id,
                    "predicate_canonical": _CanonicalURIs.ACTOR_NAME,
                    "object_value": t.object.value if t.object else None,
                })
                # Also add to nodes
                nodes.setdefault(actor_id, {})["uri"] = t.subject.uri if t.subject else ""

        logger.debug(
            "_expand_event_junctions: added %d junction edges, %d rolle edges, %d actor edges",
            len(junction_ids), len(rolle_ids), len(actor_ids)
        )

    def _batch_precompute_all_fields(
        self,
        subject_ids: Sequence[str],
        edges_by_subject: Dict[str, List[Dict[str, Any]]],
        nodes: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        """Pre-compute ALL fields for ALL projects in ONE pass.

        Returns a dict: project_id -> {all extracted fields}

        This is MUCH faster than extracting per-project because we:
        1. Iterate each project's edges only ONCE
        2. Extract all related entity data in single passes
        3. Use pre-built indexes for O(1) junction lookups
        """
        result: Dict[str, Dict[str, Any]] = {}

        # Build event_to_projects mapping for actor extraction
        event_to_projects: Dict[str, Set[str]] = {}

        # PASS 1: Extract all direct project fields in ONE iteration per project
        for sid in subject_ids:
            sid_str = str(sid)
            subject_edges = edges_by_subject.get(sid_str, [])

            # Initialize project data
            proj = {
                "title": None,
                "subtitle": None,
                "description": None,
                "image": None,
                "image_entity_id": None,  # For vorschaubild → digital object lookup
                "institution_id": None,
                "institution_label": "",
                "institution_uri": "",
                "category_ids": [],
                "category_labels": [],
                "category_slugs": [],
                "categories_structured": [],
                "project_type_id": None,
                "project_type_label": "",
                "catchphrase_ids": [],
                "catchphrase_labels": [],
                "event_ids": [],
                "events_structured": [],
                "year_values": set(),
                "year_range": "",
                "do_ids": [],
                "digital_object_paths": [],
                "digital_objects_structured": [],
                "actor_names": set(),
                "actors_structured": {},
            }

            # Single pass through project edges
            for edge in subject_edges:
                pred = self._canonical(edge)
                obj_id = edge.get("object_id")
                obj_val = edge.get("object_value")

                if pred == _CanonicalURIs.TITLE and not proj["title"]:
                    proj["title"] = obj_val
                elif pred == _CanonicalURIs.SUBTITLE and not proj["subtitle"]:
                    proj["subtitle"] = obj_val
                elif pred == _CanonicalURIs.DESCRIPTION and not proj["description"]:
                    proj["description"] = obj_val
                elif pred == _CanonicalURIs.DESCRIPTION_DE_CONTENT and not proj["description"]:
                    proj["description"] = obj_val
                elif pred == _CanonicalURIs.DESCRIPTION_DE and not proj["description"]:
                    proj["description"] = obj_val
                elif pred == _CanonicalURIs.EVENT_DESCRIPTION and not proj["description"]:
                    proj["description"] = obj_val
                elif pred == _CanonicalURIs.IMAGE and not proj["image"]:
                    if obj_val:
                        # Normalize path: backslashes → forward slashes, spaces → underscores
                        proj["image"] = obj_val.replace("\\", "/").replace(" ", "_")
                    elif obj_id:
                        # vorschaubild points to entity (digital object) - resolve later
                        proj["image_entity_id"] = obj_id
                elif pred == _CanonicalURIs.INSTITUTION and obj_id:
                    proj["institution_id"] = obj_id
                elif pred == _CanonicalURIs.CATEGORY and obj_id:
                    proj["category_ids"].append(obj_id)
                elif pred == _CanonicalURIs.CATCHPHRASE and obj_id:
                    proj["catchphrase_ids"].append(obj_id)
                elif pred == _CanonicalURIs.PROJECT_TYPE_LINK and obj_id:
                    proj["project_type_id"] = obj_id
                elif pred == _CanonicalURIs.EVENT and obj_id:
                    proj["event_ids"].append(obj_id)
                    event_to_projects.setdefault(obj_id, set()).add(sid_str)
                elif pred == _CanonicalURIs.DIGITAL_OBJECT and obj_id:
                    proj["do_ids"].append(obj_id)
                elif pred == _CanonicalURIs.DESCRIPTION_ENTITY and obj_id and not proj["description"]:
                    # Nested description
                    desc_edges = edges_by_subject.get(obj_id, [])
                    for de in desc_edges:
                        if self._canonical(de) == _CanonicalURIs.DESCRIPTION_ENTITY:
                            proj["description"] = de.get("object_value")
                            break

            result[sid_str] = proj

        # PASS 2: Resolve related entity names (institution, categories, etc.)
        for sid_str, proj in result.items():
            # Institution
            if proj["institution_id"]:
                inst_edges = edges_by_subject.get(proj["institution_id"], [])
                for e in inst_edges:
                    if self._canonical(e) == _CanonicalURIs.INSTITUTION_NAME:
                        proj["institution_label"] = e.get("object_value") or ""
                        break
                if not proj["institution_label"]:
                    inst_node = nodes.get(proj["institution_id"], {})
                    proj["institution_label"] = inst_node.get("name") or inst_node.get("value") or ""
                inst_node = nodes.get(proj["institution_id"], {})
                proj["institution_uri"] = inst_node.get("uri") or ""

            # Image path from vorschaubild entity (digital object → dateipfad)
            if not proj["image"] and proj["image_entity_id"]:
                img_edges = edges_by_subject.get(proj["image_entity_id"], [])
                for e in img_edges:
                    if self._canonical(e) == _CanonicalURIs.DO_PATH:
                        raw_path = e.get("object_value") or ""
                        # Normalize path: backslashes → forward slashes, spaces → underscores
                        proj["image"] = raw_path.replace("\\", "/").replace(" ", "_")
                        break

            # Categories
            seen_cats = set()
            for cat_id in proj["category_ids"]:
                cat_edges = edges_by_subject.get(cat_id, [])
                cat_node = nodes.get(cat_id, {})
                label = None
                slug = None
                wikidata = None
                for e in cat_edges:
                    p = self._canonical(e)
                    if p == _CanonicalURIs.CATEGORY_NAME:
                        label = e.get("object_value")
                    elif p == _CanonicalURIs.SCHLAGWORT_NAME:
                        label = label or e.get("object_value")
                    elif p == _CanonicalURIs.SCHLAGWORT_WIKIDATA_LABEL:
                        label = label or e.get("object_value")
                    elif p == _CanonicalURIs.CATEGORY_SLUG:
                        slug = e.get("object_value")
                    elif p == _CanonicalURIs.CATEGORY_WIKIDATA:
                        wikidata = e.get("object_value")
                if not label:
                    label = cat_node.get("name") or cat_node.get("value")
                if not slug:
                    uri = cat_node.get("uri") or ""
                    if uri:
                        slug = uri.rstrip("/").split("/")[-1]
                if label and label not in seen_cats:
                    proj["category_labels"].append(label)
                    seen_cats.add(label)
                    if slug:
                        proj["category_slugs"].append(slug.lower())
                    proj["categories_structured"].append({
                        "label": label,
                        "uri": cat_node.get("uri") or "",
                        "slug": slug or "",
                        "wikidata": wikidata or "",
                    })

            # Catchphrases (same structure as categories for some orgs)
            seen_catch = set()
            for catch_id in proj["catchphrase_ids"]:
                catch_edges = edges_by_subject.get(catch_id, [])
                catch_node = nodes.get(catch_id, {})
                label = None
                for e in catch_edges:
                    p = self._canonical(e)
                    if p == _CanonicalURIs.CATCHPHRASE_NAME:
                        label = e.get("object_value")
                        break
                    elif p == _CanonicalURIs.SCHLAGWORT_NAME:
                        label = e.get("object_value")
                    elif p == _CanonicalURIs.SCHLAGWORT_WIKIDATA_LABEL:
                        label = label or e.get("object_value")
                if not label:
                    label = catch_node.get("name") or catch_node.get("value")
                if label and label not in seen_catch:
                    proj["catchphrase_labels"].append(label)
                    seen_catch.add(label)

            # Project type
            if proj["project_type_id"]:
                pt_edges = edges_by_subject.get(proj["project_type_id"], [])
                for e in pt_edges:
                    if self._canonical(e) == _CanonicalURIs.PROJECT_TYPE_NAME:
                        proj["project_type_label"] = e.get("object_value") or ""
                        break
                if not proj["project_type_label"]:
                    pt_node = nodes.get(proj["project_type_id"], {})
                    proj["project_type_label"] = pt_node.get("name") or pt_node.get("value") or ""

            # Events and years
            for event_id in proj["event_ids"]:
                event_edges = edges_by_subject.get(event_id, [])
                event_node = nodes.get(event_id, {})
                event_name = None
                start = None
                end = None
                location = None
                for e in event_edges:
                    p = self._canonical(e)
                    if p == _CanonicalURIs.EVENT_NAME:
                        event_name = e.get("object_value")
                    elif p == _CanonicalURIs.EVENT_NAME_ALT and not event_name:
                        event_name = e.get("object_value")
                    elif p == _CanonicalURIs.EVENT_START:
                        start = e.get("object_value")
                    elif p == _CanonicalURIs.EVENT_END:
                        end = e.get("object_value")
                    elif p == _CanonicalURIs.EVENT_LOCATION:
                        location = e.get("object_value")
                if not event_name:
                    event_name = event_node.get("name") or event_node.get("value") or ""
                # Extract years
                for val in (start, end):
                    year = _coerce_year(val)
                    if year:
                        proj["year_values"].add(year)
                # Build display date
                if start and end:
                    display_date = start if start == end else f"{start} - {end}"
                else:
                    display_date = start or end
                proj["events_structured"].append({
                    "id": event_id,
                    "uri": event_node.get("uri") or "",
                    "name": event_name,
                    "start": start,
                    "end": end,
                    "location": location,
                    "display_date": display_date,
                    "actors": [],  # Will be filled in actor pass
                })

            # Digital objects
            seen_paths = set()
            for do_id in proj["do_ids"]:
                do_edges = edges_by_subject.get(do_id, [])
                do_node = nodes.get(do_id, {})
                path = None
                for e in do_edges:
                    if self._canonical(e) == _CanonicalURIs.DO_PATH:
                        path = e.get("object_value")
                        break
                if path and path not in seen_paths:
                    proj["digital_object_paths"].append(path)
                    seen_paths.add(path)
                    proj["digital_objects_structured"].append({
                        "path": path,
                        "uri": do_node.get("uri") or "",
                    })

            # Year range
            years = sorted(proj["year_values"])
            if years:
                if len(years) == 1:
                    proj["year_range"] = str(years[0])
                else:
                    proj["year_range"] = f"{min(years)} bis {max(years)}"
            proj["year_values"] = years

        # PASS 3: Extract actors via junctions (using pre-built indexes)
        def get_actor_info(actor_id: str) -> Tuple[str, str]:
            actor_edges = edges_by_subject.get(actor_id, [])
            name = None
            for e in actor_edges:
                if self._canonical(e) == _CanonicalURIs.ACTOR_NAME:
                    name = e.get("object_value")
                    break
            if not name:
                actor_node = nodes.get(actor_id, {})
                name = actor_node.get("name") or actor_node.get("value")
            actor_node = nodes.get(actor_id, {})
            return name or "", actor_node.get("uri") or ""

        def add_actor(proj: Dict, name: str, uri: str, roles: List[str]) -> None:
            if not name:
                return
            normalized = str(name).strip()
            if not normalized:
                return
            proj["actor_names"].add(normalized)
            if normalized not in proj["actors_structured"]:
                proj["actors_structured"][normalized] = {
                    "name": normalized,
                    "roles": set(roles),
                    "uri": uri,
                }
            else:
                proj["actors_structured"][normalized]["roles"].update(roles)

        # Process junctions via events (FUK pattern)
        for event_id, project_ids in event_to_projects.items():
            event_edges = edges_by_subject.get(event_id, [])
            forward_junctions = self._related_ids(event_edges, _CanonicalURIs.EVENT_ACTOR_JUNCTION)
            reverse_junctions = self._junctions_by_event.get(event_id, [])
            all_junctions = set(forward_junctions) | set(reverse_junctions)

            for junction_id in all_junctions:
                junction_edges = edges_by_subject.get(junction_id, [])
                actor_ids = self._related_ids(junction_edges, _CanonicalURIs.ACTOR_LINK)
                roles = self._get_role_names_from_junction(junction_edges, edges_by_subject)
                for actor_id in actor_ids:
                    name, uri = get_actor_info(actor_id)
                    for pid in project_ids:
                        if pid in result:
                            add_actor(result[pid], name, uri, roles)

            # Direct event->actor links
            for direct_pred in (_CanonicalURIs.EVENT_DIRECT_ACTOR_FUK, _CanonicalURIs.EVENT_DIRECT_ACTOR_KHM):
                direct_actors = self._related_ids(event_edges, direct_pred)
                for actor_id in direct_actors:
                    name, uri = get_actor_info(actor_id)
                    for pid in project_ids:
                        if pid in result:
                            add_actor(result[pid], name, uri, [])

        # Process junctions via projects (KHM pattern)
        for project_id, junction_ids in self._junctions_by_project.items():
            if project_id not in result:
                continue
            proj = result[project_id]
            for junction_id in junction_ids:
                junction_edges = edges_by_subject.get(junction_id, [])
                actor_ids = self._related_ids(junction_edges, _CanonicalURIs.ACTOR_LINK)
                roles = self._get_role_names_from_junction(junction_edges, edges_by_subject)
                for actor_id in actor_ids:
                    name, uri = get_actor_info(actor_id)
                    add_actor(proj, name, uri, roles)

        # PASS 4: Finalize - convert sets to lists
        for sid_str, proj in result.items():
            proj["actor_names"] = list(proj["actor_names"])
            proj["actors_structured"] = [
                {"name": v["name"], "roles": list(v["roles"]), "uri": v["uri"]}
                for v in proj["actors_structured"].values()
            ]
            # Clean up temp fields
            del proj["institution_id"]
            del proj["category_ids"]
            del proj["catchphrase_ids"]
            del proj["project_type_id"]
            del proj["event_ids"]
            del proj["do_ids"]

        return result

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
        """Extract category labels from project's category and schlagwort relations.

        Checks both projektkategorie and schlagwort predicates since some orgs
        (like KHM) use schlagwort for categorization while others (FUK) use
        projektkategorie.
        """
        # Get IDs from both projektkategorie and schlagwort predicates
        cat_ids = self._related_ids(subject_edges, _CanonicalURIs.CATEGORY)
        schlagwort_ids = self._related_ids(subject_edges, _CanonicalURIs.CATCHPHRASE)

        categories: List[str] = []
        seen: Set[str] = set()

        def _is_invalid_label(value: str) -> bool:
            """Check if a label is invalid (numeric-only or numeric list)."""
            cleaned = value.strip()
            # Skip empty
            if not cleaned:
                return True
            # Skip pure numbers
            if cleaned.isdigit():
                return True
            # Skip Q-IDs (Wikidata identifiers)
            if cleaned.startswith("Q") and cleaned[1:].isdigit():
                return True
            # Skip numeric lists like "205,232"
            if all(c.isdigit() or c in ",. " for c in cleaned):
                return True
            return False

        def _extract_label(entity_id: str) -> Optional[str]:
            """Try multiple canonical URIs to find a label."""
            entity_edges = edges_by_subject.get(entity_id, [])

            # Try projektkategorie breadcrumb name first (FUK)
            label = self._first_literal(entity_edges, _CanonicalURIs.CATEGORY_NAME)
            if label and not _is_invalid_label(label):
                return label

            # Try schlagwort german name (KHM)
            label = self._first_literal(entity_edges, _CanonicalURIs.SCHLAGWORT_NAME)
            if label and not _is_invalid_label(label):
                return label

            # Try FUK schlagwort wikidata label
            label = self._first_literal(entity_edges, _CanonicalURIs.SCHLAGWORT_WIKIDATA_LABEL)
            if label and not _is_invalid_label(label):
                return label

            # Try Wikidata lookup if Q-ID is available
            wikidata_id = self._first_literal(entity_edges, _CanonicalURIs.CATEGORY_WIKIDATA)
            if wikidata_id:
                label = self._lookup_wikidata_label(wikidata_id)
                if label and not _is_invalid_label(label):
                    return label

            # Fallback to node name (skip if invalid)
            entity_node = nodes.get(entity_id, {})
            fallback = entity_node.get("name") or entity_node.get("value")
            if fallback and not _is_invalid_label(str(fallback)):
                return fallback

            return None

        # Process projektkategorie entities
        for cat_id in cat_ids:
            label = _extract_label(cat_id)
            if label:
                normalized = str(label).strip()
                if normalized and normalized not in seen:
                    categories.append(normalized)
                    seen.add(normalized)

        # Process schlagwort entities (for orgs like KHM that use schlagwort as categories)
        for sw_id in schlagwort_ids:
            label = _extract_label(sw_id)
            if label:
                normalized = str(label).strip()
                if normalized and normalized not in seen:
                    categories.append(normalized)
                    seen.add(normalized)

        return categories

    def _lookup_wikidata_label(self, wikidata_id: str) -> Optional[str]:
        """Look up Wikidata label from ExternalSourcesEntity table."""
        if not wikidata_id:
            return None

        # Normalize Q-ID format
        qid = wikidata_id.strip()
        if not qid.startswith("Q"):
            qid = f"Q{qid}"

        try:
            from arkumu.metadata.models import ExternalSourcesEntity

            entry = ExternalSourcesEntity.objects.filter(
                data_id=qid,
                property="label_de",
                source=ExternalSourcesEntity.SourceEnum.WIKIDATA,
            ).first()

            if entry and entry.datum:
                return entry.datum
        except Exception:
            pass

        return None

    def _extract_actor_names(
        self,
        subject_edges: List[Dict[str, Any]],
        edges_by_subject: Dict[str, List[Dict[str, Any]]],
        nodes: Dict[str, Dict[str, Any]],
        project_subject_id: Optional[str] = None,
    ) -> List[str]:
        """Extract actor names via multiple patterns:
        1. FUK: event -> junction (akteurinnen-am-ereignis) -> actor (akteurin-im-ereignis)
        2. FUK: junction -> im-ereignis -> event (reverse lookup)
        3. KHM: junction -> projekt -> project (project-based junctions)
        4. Direct: event -> actor directly (ereignis-hat-akteurin or akteurin-im-ereignis)
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

        # Collect all junction IDs using pre-built indexes (O(1) lookup)
        all_junction_ids: Set[str] = set()

        for event_id in event_ids:
            event_edges = edges_by_subject.get(event_id, [])

            # Pattern 1: FUK forward junction path (akteurinnen-am-ereignis)
            junction_ids = self._related_ids(event_edges, _CanonicalURIs.EVENT_ACTOR_JUNCTION)
            all_junction_ids.update(junction_ids)

            # Pattern 2: FUK reverse lookup using pre-built index
            if hasattr(self, '_junctions_by_event'):
                all_junction_ids.update(self._junctions_by_event.get(event_id, []))

            # Pattern 4: Direct actor links on event
            for direct_uri in (_CanonicalURIs.EVENT_DIRECT_ACTOR_FUK, _CanonicalURIs.EVENT_DIRECT_ACTOR_KHM):
                direct_actor_ids = self._related_ids(event_edges, direct_uri)
                for actor_id in direct_actor_ids:
                    _add_actor_name(actor_id)

        # Pattern 3: KHM - junctions via project using pre-built index
        if project_subject_id and hasattr(self, '_junctions_by_project'):
            all_junction_ids.update(self._junctions_by_project.get(project_subject_id, []))

        # Process all junctions to extract actor names
        for junction_id in all_junction_ids:
            junction_edges = edges_by_subject.get(junction_id, [])
            actor_ids = self._related_ids(junction_edges, _CanonicalURIs.ACTOR_LINK)
            for actor_id in actor_ids:
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
        """Extract category data as structured dicts for ProjectDetailIndex.

        Checks both projektkategorie and schlagwort predicates.
        """
        cat_ids = self._related_ids(subject_edges, _CanonicalURIs.CATEGORY)
        schlagwort_ids = self._related_ids(subject_edges, _CanonicalURIs.CATCHPHRASE)
        categories: List[Dict[str, str]] = []
        seen_labels: Set[str] = set()

        def _is_invalid_label(value: str) -> bool:
            """Check if a label is invalid (numeric-only or numeric list)."""
            cleaned = value.strip()
            if not cleaned:
                return True
            if cleaned.isdigit():
                return True
            if cleaned.startswith("Q") and cleaned[1:].isdigit():
                return True
            if all(c.isdigit() or c in ",. " for c in cleaned):
                return True
            return False

        def _process_entity(entity_id: str) -> None:
            entity_edges = edges_by_subject.get(entity_id, [])
            entity_node = nodes.get(entity_id, {})

            # Try multiple canonical URIs to find a label
            label = self._first_literal(entity_edges, _CanonicalURIs.CATEGORY_NAME)
            if not label or _is_invalid_label(label):
                label = self._first_literal(entity_edges, _CanonicalURIs.SCHLAGWORT_NAME)
            if not label or _is_invalid_label(label):
                label = self._first_literal(entity_edges, _CanonicalURIs.SCHLAGWORT_WIKIDATA_LABEL)
            if not label or _is_invalid_label(label):
                # Try Wikidata lookup
                wikidata_id = self._first_literal(entity_edges, _CanonicalURIs.CATEGORY_WIKIDATA)
                if wikidata_id:
                    label = self._lookup_wikidata_label(wikidata_id)
            if not label or _is_invalid_label(label):
                # Fallback to node name (skip if invalid)
                fallback = entity_node.get("name") or entity_node.get("value")
                if fallback and not _is_invalid_label(str(fallback)):
                    label = fallback
                else:
                    label = None

            if not label:
                return

            normalized_label = str(label).strip()
            if not normalized_label or normalized_label in seen_labels:
                return

            slug = self._first_literal(entity_edges, _CanonicalURIs.CATEGORY_SLUG)
            if not slug:
                uri = entity_node.get("uri") or ""
                slug = uri.rstrip("/").split("/")[-1] if uri else ""

            uri = entity_node.get("uri") or ""

            categories.append({
                "label": normalized_label,
                "uri": uri,
                "slug": str(slug).strip().lower() if slug else "",
            })
            seen_labels.add(normalized_label)

        # Process projektkategorie entities
        for cat_id in cat_ids:
            _process_entity(cat_id)

        # Process schlagwort entities
        for sw_id in schlagwort_ids:
            _process_entity(sw_id)

        return categories

    def _extract_actors_structured(
        self,
        subject_edges: List[Dict[str, Any]],
        edges_by_subject: Dict[str, List[Dict[str, Any]]],
        nodes: Dict[str, Dict[str, Any]],
        project_subject_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Extract actor data with roles as structured dicts for ProjectDetailIndex.

        Supports two patterns:
        1. FUK: junction -> im-ereignis -> event (find via event_ids)
        2. KHM: junction -> projekt -> project (find via project_subject_id)
        """
        event_ids = self._related_ids(subject_edges, _CanonicalURIs.EVENT)
        actors: List[Dict[str, Any]] = []
        seen_names: Set[str] = set()

        # Collect all junction IDs using pre-built indexes (O(1) lookup)
        all_junction_ids: Set[str] = set()

        # Pattern 1: FUK - junctions via events
        for event_id in event_ids:
            event_edges = edges_by_subject.get(event_id, [])

            # Try junction table approach first (akteurinnen-am-ereignis, event -> junction)
            junction_ids = self._related_ids(event_edges, _CanonicalURIs.EVENT_ACTOR_JUNCTION)
            all_junction_ids.update(junction_ids)

            # Also find junctions via pre-built index (FUK: junction -> im-ereignis -> event)
            if hasattr(self, '_junctions_by_event'):
                all_junction_ids.update(self._junctions_by_event.get(event_id, []))

        # Pattern 2: KHM - junctions via project using pre-built index
        if project_subject_id and hasattr(self, '_junctions_by_project'):
            all_junction_ids.update(self._junctions_by_project.get(project_subject_id, []))

        # Process all junctions
        for junction_id in all_junction_ids:
            junction_edges = edges_by_subject.get(junction_id, [])
            actor_ids = self._related_ids(junction_edges, _CanonicalURIs.ACTOR_LINK)

            # Get roles from junction (supports both entity links and literals)
            roles = self._get_role_names_from_junction(junction_edges, edges_by_subject)

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
                            "roles": roles,
                            "uri": actor_node.get("uri") or "",
                        })
                        seen_names.add(normalized)

        # Also try direct event->actor links (both FUK and KHM/HMT patterns)
        for event_id in event_ids:
            event_edges = edges_by_subject.get(event_id, [])
            for direct_uri in (_CanonicalURIs.EVENT_DIRECT_ACTOR_FUK, _CanonicalURIs.EVENT_DIRECT_ACTOR_KHM):
                direct_actor_ids = self._related_ids(event_edges, direct_uri)
                for actor_id in direct_actor_ids:
                    actor_edges = edges_by_subject.get(actor_id, [])
                    actor_node = nodes.get(actor_id, {})

                    name = self._first_literal(actor_edges, _CanonicalURIs.ACTOR_NAME)
                    if not name:
                        name = actor_node.get("name") or actor_node.get("value")

                    # Get roles from actor's junction links via rolle entities
                    actor_junction_ids = self._related_ids(actor_edges, _CanonicalURIs.ACTOR_LINK)
                    roles: List[str] = []
                    for aj_id in actor_junction_ids:
                        aj_edges = edges_by_subject.get(aj_id, [])
                        aj_roles = self._get_role_names_from_junction(aj_edges, edges_by_subject)
                        roles.extend(aj_roles)

                    if name:
                        normalized = str(name).strip()
                        if normalized not in seen_names:
                            actors.append({
                                "name": normalized,
                                "roles": roles,
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
            event_actors = self._extract_event_actors(event_id, event_edges, edges_by_subject, nodes)

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
        event_id: str,
        event_edges: List[Dict[str, Any]],
        edges_by_subject: Dict[str, List[Dict[str, Any]]],
        nodes: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Extract actors for a specific event."""
        actors: List[Dict[str, Any]] = []
        seen_names: Set[str] = set()

        # Try junction table approach (akteurinnen-am-ereignis, event -> junction)
        junction_ids = self._related_ids(event_edges, _CanonicalURIs.EVENT_ACTOR_JUNCTION)

        # Also find junctions via reverse lookup (FUK: junction -> im-ereignis -> event)
        for subject_id, subject_edges in edges_by_subject.items():
            for edge in subject_edges:
                if (self._canonical(edge) == _CanonicalURIs.JUNCTION_TO_EVENT
                        and edge.get("object_id") == event_id):
                    if subject_id not in junction_ids:
                        junction_ids.append(subject_id)

        for junction_id in junction_ids:
            junction_edges = edges_by_subject.get(junction_id, [])
            actor_ids = self._related_ids(junction_edges, _CanonicalURIs.ACTOR_LINK)
            roles = self._get_role_names_from_junction(junction_edges, edges_by_subject)

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
                            "roles": roles,
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

                # Get roles from actor's junction links via rolle entities
                actor_junction_ids = self._related_ids(actor_edges, _CanonicalURIs.ACTOR_LINK)
                roles: List[str] = []
                for aj_id in actor_junction_ids:
                    aj_edges = edges_by_subject.get(aj_id, [])
                    aj_roles = self._get_role_names_from_junction(aj_edges, edges_by_subject)
                    roles.extend(aj_roles)

                if name:
                    normalized = str(name).strip()
                    if normalized not in seen_names:
                        actors.append({
                            "name": normalized,
                            "roles": roles,
                        })
                        seen_names.add(normalized)

        return actors

    def _extract_licenses(
        self,
        subject_edges: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Extract license metadata from project edges."""
        licenses: Dict[str, Any] = {}

        # bestehende_vertraege (list)
        existing = self._all_literals(subject_edges, _CanonicalURIs.LICENSE_EXISTING)
        if existing:
            licenses["bestehende_vertraege"] = existing

        # neuer_lizenzvertrag (single)
        new_license = self._first_literal(subject_edges, _CanonicalURIs.LICENSE_NEW)
        if new_license:
            licenses["neuer_lizenzvertrag"] = new_license

        # angegebene_nutzungsrechte (single)
        usage = self._first_literal(subject_edges, _CanonicalURIs.LICENSE_USAGE_RIGHTS)
        if usage:
            licenses["angegebene_nutzungsrechte"] = usage

        # sonderregelungen (list)
        special = self._all_literals(subject_edges, _CanonicalURIs.LICENSE_SPECIAL_TERMS)
        if special:
            licenses["sonderregelungen"] = special

        # weitere_rechtsdokumente (list)
        other_docs = self._all_literals(subject_edges, _CanonicalURIs.LICENSE_OTHER_DOCS)
        if other_docs:
            licenses["weitere_rechtsdokumente"] = other_docs

        # dateiabfrage_dokument (single)
        file_req = self._first_literal(subject_edges, _CanonicalURIs.LICENSE_FILE_REQUEST)
        if file_req:
            licenses["dateiabfrage_dokument"] = file_req

        return licenses

    def _extract_properties(
        self,
        subject_edges: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Extract property metadata from project edges."""
        properties: Dict[str, Any] = {}

        # sprachen (list) - from title and subtitle languages
        sprachen: List[str] = []
        lang_title = self._first_literal(subject_edges, _CanonicalURIs.PROPERTY_LANGUAGE_TITLE)
        if lang_title:
            sprachen.append(lang_title)
        lang_subtitle = self._first_literal(subject_edges, _CanonicalURIs.PROPERTY_LANGUAGE_SUBTITLE)
        if lang_subtitle and lang_subtitle not in sprachen:
            sprachen.append(lang_subtitle)

        if sprachen:
            properties["sprachen"] = ", ".join(sprachen)

        # dauer_freitext
        dauer = self._first_literal(subject_edges, _CanonicalURIs.PROPERTY_DAUER_FREITEXT)
        if dauer:
            properties["dauer_freitext"] = dauer

        # produktionsformat
        produktionsformat = self._first_literal(subject_edges, _CanonicalURIs.PROPERTY_PRODUKTIONSFORMAT)
        if produktionsformat:
            properties["produktionsformat"] = produktionsformat

        # instrumentierung
        instrumentierung = self._first_literal(subject_edges, _CanonicalURIs.PROPERTY_INSTRUMENTIERUNG)
        if instrumentierung:
            properties["instrumentierung"] = instrumentierung

        # aspect_ratio
        aspect = self._first_literal(subject_edges, _CanonicalURIs.PROPERTY_ASPECT_RATIO)
        if aspect:
            properties["aspect_ratio"] = aspect

        # abspielgeschwindigkeit
        abspiel = self._first_literal(subject_edges, _CanonicalURIs.PROPERTY_ABSPIELGESCHWINDIGKEIT)
        if abspiel:
            properties["abspielgeschwindigkeit"] = abspiel

        # fernsehnorm
        fernsehnorm = self._first_literal(subject_edges, _CanonicalURIs.PROPERTY_FERNSEHNORM)
        if fernsehnorm:
            properties["fernsehnorm"] = fernsehnorm

        # bildfrequenz
        bildfrequenz = self._first_literal(subject_edges, _CanonicalURIs.PROPERTY_BILDFREQUENZ)
        if bildfrequenz:
            properties["bildfrequenz"] = bildfrequenz

        return properties

    def _extract_status(
        self,
        subject_edges: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Extract status metadata from project edges."""
        status: Dict[str, Any] = {}

        # signatur
        signatur = self._first_literal(subject_edges, _CanonicalURIs.STATUS_SIGNATUR)
        if signatur:
            status["signatur"] = signatur

        # signatur_beim_einlieferer
        signatur_einl = self._first_literal(subject_edges, _CanonicalURIs.STATUS_SIGNATUR_EINLIEFERER)
        if signatur_einl:
            status["signatur_beim_einlieferer"] = signatur_einl

        # datensatz_id_beim_einlieferer
        datensatz_id = self._first_literal(subject_edges, _CanonicalURIs.STATUS_DATENSATZ_ID)
        if datensatz_id:
            status["datensatz_id_beim_einlieferer"] = datensatz_id

        return status

    def _extract_authority(
        self,
        subject_edges: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Extract authority/normdaten metadata from project edges."""
        authority: Dict[str, Any] = {}

        # wikidata_ids
        wikidata = self._all_literals(subject_edges, _CanonicalURIs.AUTHORITY_WIKIDATA)
        if wikidata:
            authority["wikidata_ids"] = ", ".join(wikidata)

        # gnd_ids
        gnd = self._all_literals(subject_edges, _CanonicalURIs.AUTHORITY_GND)
        if gnd:
            authority["gnd_ids"] = ", ".join(gnd)

        # externe_webseiten
        externe = self._all_literals(subject_edges, _CanonicalURIs.AUTHORITY_EXTERNE_WEBSEITE)
        if externe:
            authority["externe_webseiten"] = ", ".join(externe)

        return authority

    def _all_literals(
        self,
        edges: Iterable[Dict[str, Any]],
        predicate: str,
    ) -> List[str]:
        """Get all literal values for predicate."""
        results: List[str] = []
        for edge in edges:
            if self._canonical(edge) == predicate:
                value = edge.get("object_value")
                if value:
                    val_str = str(value).strip()
                    if val_str and val_str not in results:
                        results.append(val_str)
        return results

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

    def _get_actors_via_service(
        self,
        subject_id: str,
        subject_edges: List[Dict[str, Any]],
        org_code: Optional[str] = None,
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
        """Get actors using TripleRelationshipService (proven, handles all org patterns).

        Returns:
            Tuple of (actor_names, actors_structured)
        """
        # Get event IDs from graph edges
        event_ids = self._related_ids(subject_edges, _CanonicalURIs.EVENT)

        triple_service = TripleRelationshipService(organization_code=org_code)
        actors_payload = triple_service.get_actor_relationships(
            subject_id,
            event_predicate=_CanonicalURIs.EVENT,
            actor_link_predicate=_CanonicalURIs.ACTOR_LINK,
            role_link_predicate=_CanonicalURIs.ACTOR_ROLE,
            actor_name_predicate=_CanonicalURIs.ACTOR_NAME,
            role_name_predicate=_CanonicalURIs.ROLE_GERMAN_NAME,
            event_ids=list(event_ids) if event_ids else None,
            organization_code=org_code,
        )

        actor_names: List[str] = []
        actors_structured: List[Dict[str, Any]] = []
        seen_names: Set[str] = set()

        for payload in actors_payload:
            name = payload.get("name")
            if not name:
                continue
            normalized = str(name).strip()
            if normalized in seen_names:
                continue
            seen_names.add(normalized)

            roles = list(payload.get("roles", []))
            actor_names.append(normalized)
            actors_structured.append({
                "name": normalized,
                "roles": roles,
                "uri": "",  # Service doesn't return URI, leave empty
            })

        return actor_names, actors_structured
