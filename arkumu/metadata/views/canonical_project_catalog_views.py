from __future__ import annotations

import logging
from typing import Any, Dict, List, Sequence

from django.db.models import Q
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from arkumu.catalog.services.project_views import CardURIs
from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.services.canonical_graph_service import (
    CanonicalGraphService,
    RDF_TYPE_URI,
)
from arkumu.projects.services import ProjectSnapshotService
from arkumu.users.mixins import general_login_required
from arkumu.users.models import Organization

logger = logging.getLogger(__name__)

PROJECT_TYPE_CANONICAL_URI = CardURIs.PROJECT_TYPE
PROJECT_TITLE_CANONICAL_URI = CardURIs.TITLE
PROJECT_ID_CANONICAL_URIS: Sequence[str] = (
    "http://arkumu.org/data/properties/projekt-id",
    "http://arkumu.org/data/properties/projekt-projekt-id",
)


def _literal_map(subject_ids: Sequence[str], predicate_uris: Sequence[str]) -> Dict[str, str]:
    """Return a first-seen literal value per subject for the given predicates."""
    if not subject_ids or not predicate_uris:
        return {}

    triples = (
        Triple.objects.filter(
            subject_id__in=subject_ids,
            object__resource_type=ResourceType.LITERAL,
        )
        .filter(
            Q(predicate__canonical_uri__in=predicate_uris)
            | Q(predicate__uri__in=predicate_uris)
        )
        .select_related("object")
        .only("subject_id", "object__value", "object__name", "object__uri")
    )

    values: Dict[str, str] = {}
    for triple in triples:
        subject_id = str(triple.subject_id)
        if subject_id in values:
            continue
        obj = triple.object
        values[subject_id] = obj.value or obj.name or obj.uri or ""
    return values


def _id_predicates_from_manifest(mapping: Optional[Mapping]) -> List[str]:
    """Try to extract project ID property URIs from the schema manifest (dataset 'Projekt')."""
    if not mapping:
        return []

    manifest = (mapping.mapping_config or {}).get("schema_manifest") or {}
    project_dataset = manifest.get("Projekt") or manifest.get("Projects")
    if not isinstance(project_dataset, dict):
        return []

    predicates: List[str] = []
    for prop in (project_dataset.get("properties") or {}).values():
        if not isinstance(prop, dict):
            continue
        cand = prop.get("canonical_uri") or prop.get("uri")
        if not cand:
            continue
        if "projekt-id" in cand or "project-id" in cand:
            predicates.append(cand)
    return predicates


def _projects_for_org(org: Organization, mapping: Optional[Mapping]) -> List[Dict[str, Any]]:
    """Collect lightweight project rows (id + title) for a single organization."""
    type_filter = (
        Q(object__canonical_uri=PROJECT_TYPE_CANONICAL_URI)
        | Q(object__uri=PROJECT_TYPE_CANONICAL_URI)
    )
    subject_ids = list(
        Triple.objects.filter(
            predicate__uri=RDF_TYPE_URI,
            subject__organization=org,
        )
        .filter(type_filter)
        .values_list("subject_id", flat=True)
        .distinct()
    )

    subject_str_ids = [str(sid) for sid in subject_ids]
    if not subject_str_ids:
        return []

    id_predicates: List[str] = list(PROJECT_ID_CANONICAL_URIS)
    id_predicates.extend(_id_predicates_from_manifest(mapping))
    id_predicates = [pred for pred in dict.fromkeys(id_predicates) if pred]

    id_map = _literal_map(subject_str_ids, id_predicates)
    title_map = _literal_map(subject_str_ids, (PROJECT_TITLE_CANONICAL_URI,))

    resources = {
        str(res.id): res
        for res in Resource.objects.filter(id__in=subject_str_ids).only("id", "uri", "name", "value")
    }

    rows: List[Dict[str, Any]] = []
    for sid in subject_str_ids:
        res = resources.get(sid)
        if not res:
            continue
        title = title_map.get(sid) or res.name or res.value or res.uri or "(unlabeled project)"
        project_identifier = id_map.get(sid) or res.uri or res.canonical_uri or res.value or res.name or res.uri or ""
        rows.append(
            {
                "id": sid,
                "uri": res.uri,
                "project_id": project_identifier,
                "title": title,
            }
        )

    rows.sort(key=lambda r: r["title"].lower())
    return rows


@general_login_required
def canonical_project_catalog_view(request: HttpRequest) -> HttpResponse:
    """List projects per institution (id + title) with on-demand record assembly."""
    organizations_qs = Organization.objects.filter(is_active=True).order_by("name")
    selected_org_code = request.GET.get("org") or None
    selected_org = organizations_qs.filter(code=selected_org_code).first() if selected_org_code else None
    search_query = (request.GET.get("q") or "").strip()
    try:
        page_number = int(request.GET.get("page") or 1)
        if page_number < 1:
            page_number = 1
    except ValueError:
        page_number = 1

    display_orgs = [selected_org] if selected_org else list(organizations_qs)

    org_rows: List[Dict[str, Any]] = []
    total_projects = 0

    for org in display_orgs:
        mapping = Mapping.get_active_for_organization(org)
        projects = _projects_for_org(org, mapping) if mapping else []
        total_projects += len(projects)

        org_rows.append(
            {
                "org": org,
                "has_mapping": mapping is not None,
                "projects": projects,
            }
        )

    all_rows: List[Dict[str, Any]] = []
    for row in org_rows:
        for project in row["projects"]:
            all_rows.append(
                {
                    **project,
                    "org_code": row["org"].code,
                    "org_name": row["org"].name,
                }
            )

    if search_query:
        sq = search_query.lower()
        all_rows = [
            p
            for p in all_rows
            if sq in (p.get("title") or "").lower()
            or sq in (p.get("project_id") or "").lower()
        ]

    paginator = Paginator(all_rows, 20)
    page_obj = paginator.get_page(page_number)

    context = {
        "organizations": org_rows,
        "all_orgs": organizations_qs,
        "selected_org": selected_org,
        "search_query": search_query,
        "page_obj": page_obj,
        "stats": {
            "org_count": len(display_orgs),
            "project_count": paginator.count,
        },
    }

    return render(request, "metadata/canonical_project_catalog.html", context)


@general_login_required
def canonical_project_record_htmx(request: HttpRequest) -> HttpResponse:
    """
    HTMX endpoint: build a ProjectRecord for a single project using the canonical graph.
    """
    org_code = request.GET.get("org")
    project_id = request.GET.get("project_id")

    if not org_code or not project_id:
        return HttpResponse("Missing parameters", status=400)

    org = Organization.objects.filter(code=org_code).first()
    if not org:
        return HttpResponse("Organization not found", status=404)

    mapping = Mapping.get_active_for_organization(org)
    if not mapping:
        return HttpResponse("No active mapping for this organization", status=404)

    resource = Resource.objects.filter(id=project_id, organization=org).first()
    if not resource:
        return HttpResponse("Project not found", status=404)

    try:
        graph_service = CanonicalGraphService(org_code=org.code, mapping_id=str(mapping.id))
        graph = graph_service.get_entity_graph(
            resource_uri=resource.uri,
            include_incoming=False,
            expand_neighbors=True,
            depth=2,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Failed to build canonical graph for project %s (%s)", resource.uri, org.code)
        return HttpResponse("Unable to build graph for this project", status=500)

    root_id = graph.get("root_id")
    if not root_id:
        return HttpResponse("Project graph missing root node", status=404)
    root_id = str(root_id)

    graph_payload = {
        "subjects": [root_id],
        "nodes": graph.get("nodes", {}),
        "edges": graph.get("edges", []),
        "counts": graph.get("counts", {}),
    }

    edges = graph_payload["edges"] or []
    nodes = graph_payload["nodes"] or {}
    predicate_map: Dict[tuple, Dict[str, Any]] = {}
    MAX_VALUES = 15

    for edge in edges:
        subj = str(edge.get("subject_id") or edge.get("subject") or edge.get("s"))
        if subj != root_id:
            continue

        canonical = edge.get("predicate_canonical")
        uri = edge.get("predicate_uri")
        signature = (canonical or "", uri or "")

        row = predicate_map.setdefault(
            signature,
            {"canonical": canonical or "", "uri": uri or "", "values": []},
        )

        obj_id = str(edge.get("object_id") or "")
        value_label = ""
        if edge.get("object_type") == ResourceType.LITERAL:
            value_label = edge.get("object_value") or ""
        else:
            node = nodes.get(obj_id) or {}
            value_label = (
                node.get("name")
                or node.get("value")
                or node.get("uri")
                or edge.get("object_uri")
                or ""
            )

        if value_label:
            row["values"].append(value_label)

    predicate_rows: List[Dict[str, Any]] = []
    for row in predicate_map.values():
        values = row.get("values") or []
        if len(values) > MAX_VALUES:
            row["extra_count"] = len(values) - MAX_VALUES
            row["values"] = values[:MAX_VALUES]
            row["truncated"] = True
        else:
            row["truncated"] = False
            row["extra_count"] = 0
        predicate_rows.append(row)

    predicate_rows.sort(key=lambda row: (row["canonical"] or row["uri"]))

    try:
        snapshot_service = ProjectSnapshotService(relationship_org_code=org.code)
        card_schema = snapshot_service._get_card_schema()
        records = snapshot_service._graph_to_records(graph_payload, card_schema)
        record = records[0] if records else None
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to assemble project record for %s (%s)", resource.uri, org.code)
        return HttpResponse("Unable to assemble project record", status=500)

    if not record:
        return HttpResponse("Project record could not be built", status=404)

    return render(
        request,
        "metadata/partials/canonical_project_record.html",
        {
            "record": record,
            "predicate_rows": predicate_rows,
        },
    )
