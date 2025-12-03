"""RDF serializer for project graph data.

Separates RDF serialization concerns from ProjectRecord data class.
Takes pre-loaded graph data and produces canonical or institutional RDF/XML.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from lxml import etree as ET

from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.oaipmh.formats.mets_source_metadata import RDF_NS, build_rdf_graph
from arkumu.oaipmh.views.institutional import build_institutional_rdf_from_graph


class ProjectRdfSerializer:
    """Serializes project graph data to RDF/XML.

    Usage:
        # With pre-loaded graph data (bulk mode)
        serializer = ProjectRdfSerializer(graph_data, org_code="fuk")
        canonical_xml = serializer.to_canonical_rdf()
        institutional_xml = serializer.to_institutional_rdf()

        # With resource (on-demand mode)
        serializer = ProjectRdfSerializer.from_resource(resource)
        canonical_xml = serializer.to_canonical_rdf()
    """

    def __init__(
        self,
        graph_data: Dict[str, Any],
        org_code: Optional[str] = None,
        resource: Optional[Resource] = None,
    ):
        """Initialize serializer with graph data.

        Args:
            graph_data: Dict with 'nodes' and 'edges' from graph service.
            org_code: Organization code for institutional RDF namespace.
            resource: Optional Resource for on-demand graph fetching.
        """
        self.graph_data = graph_data
        self.org_code = (org_code or "").strip().lower()
        self.resource = resource

    @classmethod
    def from_resource(
        cls,
        resource: Resource,
        depth: int = 2,
    ) -> "ProjectRdfSerializer":
        """Create serializer by fetching graph data for a resource.

        Args:
            resource: The resource to fetch graph data for.
            depth: Graph traversal depth.

        Returns:
            ProjectRdfSerializer with fetched graph data.
        """
        from arkumu.metadata.services.canonical_graph_service import CanonicalGraphService

        org = getattr(resource, "organization", None)
        org_code = str(getattr(org, "code", "") or "").strip().lower() if org else ""

        graph_service = CanonicalGraphService(org_code=org_code or None)
        graph_data = graph_service.get_entity_graph(
            resource_uri=resource.uri,
            expand_neighbors=True,
            depth=depth,
            restrict_to_org=bool(org_code),
        )

        return cls(graph_data=graph_data, org_code=org_code, resource=resource)

    def to_canonical_rdf(self) -> Optional[str]:
        """Serialize to canonical RDF/XML.

        Uses predicate_canonical from graph edges for normalized predicates.

        Returns:
            RDF/XML string or None if no valid graph data.
        """
        if not self.graph_data or not self.graph_data.get("edges"):
            return None

        if not self.resource:
            return None

        try:
            rdf_element = build_rdf_graph(
                self.resource,
                graph_data=self.graph_data,
                use_institutional_predicates=False,
            )
            return ET.tostring(rdf_element, encoding="unicode")
        except Exception:
            return None

    def to_institutional_rdf(self) -> Optional[str]:
        """Serialize to institutional RDF/XML.

        Uses predicate_uri from graph edges for institution-specific predicates.

        Returns:
            RDF/XML string or None if no valid graph data.
        """
        if not self.graph_data:
            return None

        nodes = self.graph_data.get("nodes") or {}
        edges = self.graph_data.get("edges") or []

        if not nodes or not edges:
            return None

        if not self.org_code:
            return None

        try:
            rdf_element = build_institutional_rdf_from_graph(nodes, edges, self.org_code)
            if rdf_element is None:
                return None
            return ET.tostring(rdf_element, encoding="unicode")
        except Exception:
            return None


def serialize_canonical_rdf(
    resource: Resource,
    graph_data: Optional[Dict[str, Any]] = None,
) -> str:
    """Convenience function for canonical RDF serialization.

    Args:
        resource: The resource to serialize.
        graph_data: Optional pre-fetched graph data.

    Returns:
        RDF/XML string or empty string on error.
    """
    if graph_data:
        serializer = ProjectRdfSerializer(
            graph_data=graph_data,
            resource=resource,
        )
    else:
        serializer = ProjectRdfSerializer.from_resource(resource)

    return serializer.to_canonical_rdf() or ""


def serialize_institutional_rdf(
    resource: Resource,
    graph_data: Optional[Dict[str, Any]] = None,
    org_code: Optional[str] = None,
) -> str:
    """Convenience function for institutional RDF serialization.

    Args:
        resource: The resource to serialize.
        graph_data: Optional pre-fetched graph data.
        org_code: Organization code (extracted from resource if not provided).

    Returns:
        RDF/XML string or empty string on error.
    """
    if not org_code:
        org = getattr(resource, "organization", None)
        org_code = str(getattr(org, "code", "") or "").strip().lower() if org else ""

    if graph_data:
        serializer = ProjectRdfSerializer(
            graph_data=graph_data,
            org_code=org_code,
            resource=resource,
        )
    else:
        serializer = ProjectRdfSerializer.from_resource(resource)

    return serializer.to_institutional_rdf() or ""
