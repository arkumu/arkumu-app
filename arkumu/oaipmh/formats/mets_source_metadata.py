"""
Utilities for embedding RDF/XML graphs inside METS ``sourceMD`` sections.

This module centralises the logic that converts Arkumu entity graphs into
RDF/XML so that both standalone RDF exports and METS serialisation can
reuse the same implementation.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import rdflib
from lxml import etree as ET

from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.services.canonical_graph_service import CanonicalGraphService
from arkumu.oaipmh.formats.dublin_core import DCTERMS_NS, DC_NS

RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS_NS = "http://www.w3.org/2000/01/rdf-schema#"

PROPERTY_NAMESPACE_PATTERN = re.compile(r"^(https?://arkumu\.org/data/)([^/]+/)?(properties/)")


def _normalize_predicate_uri(uri: Optional[str]) -> Optional[str]:
    if not uri:
        return None
    return PROPERTY_NAMESPACE_PATTERN.sub(r"\1\3", uri, count=1)


def _split_namespace(uri: str) -> tuple[str, str]:
    if "#" in uri:
        base, local = uri.rsplit("#", 1)
        return f"{base}#", local
    if "/" in uri:
        base, local = uri.rsplit("/", 1)
        if not local:
            return uri, ""
        if not base.endswith("/"):
            base = f"{base}/"
        return base, local
    return uri, ""


def _node_type(node: Dict[str, Any]) -> str:
    node_type = node.get("resource_type")
    if isinstance(node_type, ResourceType):
        return node_type.value
    return str(node_type).upper() if node_type else ""


def _is_literal(node: Dict[str, Any]) -> bool:
    return _node_type(node) == ResourceType.LITERAL.value


def _is_data_node(node: Dict[str, Any]) -> bool:
    return _node_type(node) in {ResourceType.IRI.value, ResourceType.ENTITY.value}


def build_rdf_graph(
    resource: Resource,
    *,
    graph_service: Optional[CanonicalGraphService] = None,
    graph_data: Optional[Dict[str, Any]] = None,
    use_institutional_predicates: bool = False,
) -> ET._Element:
    """
    Build an RDF/XML element representing the resource graph.

    Args:
        resource: The root resource whose graph should be serialised.
        graph_service: Optional canonical graph service to reuse in tests.
        graph_data: Optional pre-fetched graph data (from bulk fetch). If provided,
                    skips the per-entity graph query.
        use_institutional_predicates: If True, use predicate_uri (native) instead of
                    predicate_canonical (normalized). Used for institutional RDF.

    Returns:
        lxml element containing the RDF/XML serialisation.
    """
    org_code = resource.organization.code if resource.organization else None
    service = graph_service or CanonicalGraphService(org_code=org_code)

    skip_junction_fetch = graph_data is not None  # Pre-fetched data already has junctions

    if graph_data is None:
        graph_data = service.get_entity_graph(
            resource_uri=resource.uri,
            expand_neighbors=True,
            depth=2,
            restrict_to_org=bool(org_code),
        )

    # Fetch junction entities (Kreuztabelle) for events to include actor-role relationships
    # Actors already appear with deutscher-name from depth=2, but junctions add:
    # - ist-urheberin, leistungsschutz flags
    # - links to roles (akteurin-hat-rolle-im-ereignis)
    # Skip if graph_data was pre-fetched (rebuild already includes junctions)
    nodes = graph_data.get("nodes", {})
    edges = graph_data.get("edges", [])

    if not skip_junction_fetch:
        # Find event IDs from existing nodes
        event_ids: List[str] = [
            node_id
            for node_id, node in nodes.items()
            if node.get("uri") and "/ereignis" in node.get("uri", "").lower()
        ]

        if event_ids:
            junction_edges = service.fetch_junction_entities(event_ids)
            if junction_edges:
                # Add junction edges to the graph
                for edge in junction_edges:
                    edges.append(edge.__dict__)

                # Collect new nodes for junction entities and their linked resources
                new_nodes = service._collect_nodes_from_edges(junction_edges)
                for node_id, node_data in new_nodes.items():
                    if node_id not in nodes:
                        nodes[node_id] = node_data

    rdf_graph = rdflib.Graph()

    namespace_cache: Dict[str, rdflib.Namespace] = {
        RDF_NS: rdflib.Namespace(RDF_NS),
        RDFS_NS: rdflib.Namespace(RDFS_NS),
        DCTERMS_NS: rdflib.Namespace(DCTERMS_NS),
        DC_NS: rdflib.Namespace(DC_NS),
        "http://arkumu.org/data/properties/": rdflib.Namespace("http://arkumu.org/data/properties/"),
    }
    prefix_map: Dict[str, str] = {
        RDF_NS: "rdf",
        RDFS_NS: "rdfs",
        DCTERMS_NS: "dcterms",
        DC_NS: "dc",
        "http://arkumu.org/data/properties/": "arkumu",
    }
    used_prefixes = set(prefix_map.values())

    for ns_uri, prefix in prefix_map.items():
        rdf_graph.bind(prefix, namespace_cache[ns_uri], override=True)

    def _resolve_prefix(ns_uri: str) -> str:
        if ns_uri in prefix_map:
            return prefix_map[ns_uri]

        if ns_uri.startswith("http://arkumu.org/data/") and ns_uri.endswith("/properties/"):
            suffix = ns_uri[len("http://arkumu.org/data/"):-len("/properties/")].strip("/")
            if not suffix:
                candidate = "arkumu"
            else:
                # Use org code directly as prefix (e.g., "khm" not "khm_prop")
                parts = [part for part in suffix.split("/") if part]
                candidate = parts[-1] if parts else "arkumu"
        else:
            parsed = urlparse(ns_uri)
            host = parsed.netloc.split(":")[0].replace(".", "_")
            path_parts = [p for p in parsed.path.split("/") if p]
            candidate_parts = [part for part in (host, path_parts[-1] if path_parts else None) if part]
            candidate = "_".join(candidate_parts) if candidate_parts else "ns"

        candidate = re.sub(r"[^a-zA-Z0-9_]", "_", candidate).lower()
        if not candidate or not candidate[0].isalpha():
            candidate = f"ns_{candidate or 'namespace'}"

        base_candidate = candidate
        index = 1
        while candidate in used_prefixes:
            candidate = f"{base_candidate}{index}"
            index += 1

        prefix_map[ns_uri] = candidate
        used_prefixes.add(candidate)
        return candidate

    def _ensure_namespace(ns_uri: str) -> Optional[rdflib.Namespace]:
        if not ns_uri:
            return None
        if ns_uri in namespace_cache:
            return namespace_cache[ns_uri]

        prefix = _resolve_prefix(ns_uri)
        namespace = rdflib.Namespace(ns_uri)
        rdf_graph.bind(prefix, namespace, override=True)
        namespace_cache[ns_uri] = namespace
        return namespace

    def _node_info(node_id: str) -> Optional[Dict[str, Any]]:
        return nodes.get(node_id)

    for edge in edges:
        subj_node = _node_info(edge.get("subject_id"))
        obj_node = _node_info(edge.get("object_id"))
        if use_institutional_predicates:
            predicate_source = edge.get("predicate_uri")
            # Don't normalize institutional predicates - keep org prefix
            normalized_predicate = predicate_source
        else:
            predicate_source = edge.get("predicate_canonical") or edge.get("predicate_uri")
            normalized_predicate = _normalize_predicate_uri(predicate_source)

        if not subj_node or not obj_node or not normalized_predicate:
            continue

        if predicate_source and "defines" in predicate_source.lower():
            continue

        # Skip redundant digitales-objekt links from KHM junction tables
        # KHM data repeats all project DOs on every junction (grundereignis, kreuz-*)
        # Only keep digitales-objekt links from the project entity itself
        if predicate_source and "digitales-objekt" in predicate_source.lower():
            subj_uri_check = subj_node.get("uri") if subj_node else ""
            # Only apply to KHM - other orgs don't have this redundancy
            if subj_uri_check and "/data/khm/" in subj_uri_check:
                # Allow from projekt entities, skip from junctions
                if "/00-projekte/" not in subj_uri_check:
                    continue

        if not _is_data_node(subj_node):
            continue

        subj_uri = subj_node.get("uri")
        if not subj_uri:
            continue

        namespace_uri, local_name = _split_namespace(normalized_predicate)
        if not local_name:
            continue

        namespace = _ensure_namespace(namespace_uri)
        if not namespace:
            continue

        predicate_ref = namespace[local_name]
        subject_ref = rdflib.URIRef(subj_uri)

        if _is_literal(obj_node):
            literal_value = obj_node.get("value") or ""
            # Strip invalid XML control characters (0x00-0x08, 0x0B, 0x0C, 0x0E-0x1F)
            literal_value = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', literal_value)
            rdf_graph.add((subject_ref, predicate_ref, rdflib.Literal(literal_value)))
            continue

        if not _is_data_node(obj_node):
            continue

        obj_uri = obj_node.get("uri")
        if not obj_uri:
            continue

        rdf_graph.add((subject_ref, predicate_ref, rdflib.URIRef(obj_uri)))

    ET.register_namespace("rdf", RDF_NS)
    ET.register_namespace("rdfs", RDFS_NS)
    ET.register_namespace("dcterms", DCTERMS_NS)
    ET.register_namespace("dc", DC_NS)
    ET.register_namespace("arkumu", "http://arkumu.org/data/properties/")

    rdf_xml = rdf_graph.serialize(format="application/rdf+xml")
    rdf_element = ET.fromstring(rdf_xml.encode("utf-8"))
    return rdf_element
