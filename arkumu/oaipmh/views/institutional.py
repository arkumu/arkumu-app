"""Institution-specific RDF helpers extracted from the monolithic OAI views."""

from __future__ import annotations

from collections import OrderedDict
from typing import Dict, List, Optional

from django.conf import settings
from lxml import etree as ET

from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.services.institutional_graph_service import InstitutionalGraphService
from arkumu.oaipmh.formats.mets_source_metadata import RDF_NS
from arkumu.oaipmh.oai_project import OAIProject

import re

_KHM_HMT_LICENSE_ORGS: set[str] = {"khm", "hmt"}

# XML 1.0 allows: #x9 | #xA | #xD | [#x20-#xD7FF] | [#xE000-#xFFFD] | [#x10000-#x10FFFF]
# This pattern matches characters that are NOT allowed
_INVALID_XML_CHARS = re.compile(
    r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F\uFFFE\uFFFF]"
)


def _sanitize_xml_text(value: Optional[str]) -> Optional[str]:
    """Remove characters that are invalid in XML 1.0."""
    if not value:
        return value
    return _INVALID_XML_CHARS.sub("", value)


def _split_namespace(uri: str) -> tuple[str, str]:
    if "#" in uri:
        base, local = uri.rsplit("#", 1)
        return f"{base}#", local
    if "/" in uri:
        base, local = uri.rsplit("/", 1)
        if not base.endswith("/"):
            base = f"{base}/"
        return base, local
    return uri, ""


def _should_emit_institutional_rdf(org_code: Optional[str]) -> bool:
    configured = {
        str(code).strip().lower()
        for code in getattr(settings, "OAI_INSTITUTIONAL_RDF_ORGS", ())
        if code
    }
    normalized = (org_code or "").strip().lower()
    return normalized in configured


def build_institutional_rdf_from_graph(
    nodes: Dict[str, dict],
    edges: List[dict],
    org_code: str,
) -> Optional[ET._Element]:
    """Build institutional RDF element from pre-loaded graph data.

    This is the core RDF building logic, separated for reuse by both
    GetRecord (live queries) and ProjectIndex (pre-loaded batch data).
    """
    if not nodes or not edges:
        return None

    namespaces = OrderedDict()
    for edge in edges:
        ns_uri, _ = _split_namespace(edge.get("predicate_uri", ""))
        if ns_uri:
            namespaces.setdefault(ns_uri, None)

    nsmap = OrderedDict({"rdf": RDF_NS})
    preferred_namespace = f"http://arkumu.org/data/{org_code}/properties/"
    prefix_index = 1
    for ns_uri in namespaces.keys():
        if ns_uri == preferred_namespace:
            prefix = org_code
        else:
            prefix = f"ns{prefix_index}"
            prefix_index += 1
        nsmap[prefix] = ns_uri
        namespaces[ns_uri] = prefix

    root = ET.Element(ET.QName(RDF_NS, "RDF"), nsmap=nsmap)

    description_map: Dict[str, ET._Element] = {}
    for node_id, node in nodes.items():
        uri = node.get("uri")
        if not uri or node.get("resource_type") != ResourceType.ENTITY:
            continue
        description = ET.SubElement(root, ET.QName(RDF_NS, "Description"))
        description.set(ET.QName(RDF_NS, "about"), uri)
        description_map[node_id] = description

    for edge in edges:
        subject_elem = description_map.get(edge.get("subject_id"))
        if subject_elem is None:
            continue
        predicate_uri = edge.get("predicate_uri")
        ns_uri, local_name = _split_namespace(predicate_uri or "")
        if not ns_uri or not local_name:
            continue
        element = ET.SubElement(subject_elem, ET.QName(ns_uri, local_name))

        obj_node = nodes.get(edge.get("object_id") or "")
        if not obj_node:
            continue
        obj_type = obj_node.get("resource_type")
        if obj_type == ResourceType.LITERAL:
            raw_value = obj_node.get("value") or edge.get("object_value")
            element.text = _sanitize_xml_text(raw_value)
        else:
            obj_uri = obj_node.get("uri")
            if not obj_uri:
                continue
            element.set(ET.QName(RDF_NS, "resource"), obj_uri)

    return root if len(root) else None


def _build_institutional_rdf_element(
    resource: Resource,
    *,
    require_org_opt_in: bool = True,
) -> Optional[ET._Element]:
    """Build institutional RDF by querying the graph service.

    Used for GetRecord where we don't have pre-loaded graph data.
    """
    organization = getattr(resource, "organization", None)
    if not organization or not getattr(organization, "code", None):
        return None
    org_code = str(organization.code).strip().lower()
    if require_org_opt_in and not _should_emit_institutional_rdf(org_code):
        return None

    graph_service = InstitutionalGraphService(org_code=org_code)
    try:
        graph = graph_service.get_entity_graph(
            resource.uri,
            include_incoming=True,
            expand_neighbors=True,
            depth=2,
        )
    except ValueError:
        return None

    nodes = graph.get("nodes") or {}
    edges = list(graph.get("edges") or [])
    if not nodes or not edges:
        return None

    # Fetch junction entities (Kreuztabelle) for related entities
    # This adds actor-role relationships and other n-ary data
    traverser = graph_service._get_traverser()
    if traverser:
        # Get all entity IDs from the graph to find junctions pointing to them
        entity_ids = [
            node_id for node_id, node in nodes.items()
            if node.get("resource_type") == ResourceType.ENTITY
        ]
        if entity_ids:
            junction_edges = graph_service.fetch_junction_entities(entity_ids)
            if junction_edges:
                edges.extend(junction_edges)
                # Add new nodes from junction edges
                new_nodes = graph_service._collect_nodes_from_edges(junction_edges)
                for node_id, node_data in new_nodes.items():
                    if node_id not in nodes:
                        nodes[node_id] = node_data

    return build_institutional_rdf_from_graph(nodes, edges, org_code)


def _normalized_org_code(
    resource: Resource,
    project: Optional[OAIProject] = None,
) -> Optional[str]:
    candidates: List[Optional[str]] = []
    org = getattr(resource, "organization", None)
    candidates.append(getattr(org, "code", None))
    if project is not None:
        candidates.append(getattr(project, "institution_code", None))
        institution = getattr(project.record, "institution", None) if getattr(project, "record", None) else None
        candidates.append(getattr(institution, "code", None))
    for candidate in candidates:
        if not candidate:
            continue
        normalized = str(candidate).strip().lower()
        if normalized:
            return normalized
    return None


def _should_apply_khm_hmt_license_rights(resource: Resource, project: Optional[OAIProject] = None) -> bool:
    code = _normalized_org_code(resource, project)
    return code in _KHM_HMT_LICENSE_ORGS
