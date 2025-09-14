from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

from django.http import HttpRequest, HttpResponse
from django.views.decorators.http import require_GET
import xml.etree.ElementTree as ET

from arkumu.metadata.models.resource import Resource
from arkumu.metadata.services.canonical_graph_service import CanonicalGraphService
from .formats.dublin_core import DublinCoreSerializer, DEFAULT_PREDICATE_MAP, DCTERMS_NS, OAI_DC_NS, DC_NS


# Minimal repository config (can be moved to settings)
REPO_NAME = "Arkumu Repository"
REPO_BASEURL = "/oai/"
REPO_ADMIN_EMAIL = "admin@example.org"
REPO_PROTOCOL_VERSION = "2.0"
REPO_EARLIEST_DATASTAMP = "1970-01-01T00:00:00Z"
REPO_DELETED_RECORD = "no"
REPO_GRANULARITY = "YYYY-MM-DDThh:mm:ssZ"


def _oai_envelope(request: HttpRequest) -> ET.Element:
    oai = ET.Element(
        "OAI-PMH",
        {
            "xmlns": "http://www.openarchives.org/OAI/2.0/",
            "xmlns:oai_dc": OAI_DC_NS,
            "xmlns:dc": DC_NS,
            "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
            "xsi:schemaLocation": " ".join(
                [
                    "http://www.openarchives.org/OAI/2.0/",
                    "http://www.openarchives.org/OAI/2.0/OAI-PMH.xsd",
                ]
            ),
        },
    )
    responseDate = ET.SubElement(oai, "responseDate")
    responseDate.text = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    req = ET.SubElement(oai, "request")
    req.text = request.build_absolute_uri(REPO_BASEURL)
    return oai


def _error(oai: ET.Element, code: str, message: str) -> ET.Element:
    e = ET.SubElement(oai, "error", {"code": code})
    e.text = message
    return oai


def _xml_response(elem: ET.Element) -> HttpResponse:
    data = ET.tostring(elem, encoding="utf-8", xml_declaration=True)
    return HttpResponse(data, content_type="text/xml")


def _identify(oai: ET.Element) -> ET.Element:
    identify = ET.SubElement(oai, "Identify")
    ET.SubElement(identify, "repositoryName").text = REPO_NAME
    ET.SubElement(identify, "baseURL").text = REPO_BASEURL
    ET.SubElement(identify, "protocolVersion").text = REPO_PROTOCOL_VERSION
    ET.SubElement(identify, "adminEmail").text = REPO_ADMIN_EMAIL
    ET.SubElement(identify, "earliestDatestamp").text = REPO_EARLIEST_DATASTAMP
    ET.SubElement(identify, "deletedRecord").text = REPO_DELETED_RECORD
    ET.SubElement(identify, "granularity").text = REPO_GRANULARITY
    return oai


def _parse_identifier(identifier: str) -> str:
    # Minimal parsing: accept raw resource URI or an oai:*:* where last ':' part is the URI (URL-escaped)
    if identifier.startswith("oai:"):
        parts = identifier.split(":")
        if len(parts) >= 3:
            return unquote(parts[-1])
    return identifier


def _build_dc_metadata_from_entity_graph(graph: Dict[str, Any]) -> Dict[str, List[str]]:
    root_id = graph.get("root_id")
    edges = graph.get("edges", [])

    # Build triples from edges where subject is the root and object is literal
    def pred(e: Dict[str, Any]) -> str:
        return e.get("predicate_canonical") or e.get("predicate_uri")

    def obj_value(e: Dict[str, Any]) -> Optional[str]:
        return e.get("object_value")

    root_literal_edges = [
        e for e in edges if e.get("subject_id") == root_id and e.get("object_value") is not None
    ]

    serializer = DublinCoreSerializer(predicate_map=DEFAULT_PREDICATE_MAP)
    dc_dict = serializer.serialize_from_triples(
        root_literal_edges, get_predicate=pred, get_object_value=obj_value
    )
    return dc_dict


@require_GET
def oai_endpoint(request: HttpRequest) -> HttpResponse:
    verb = request.GET.get("verb", "").strip()
    oai = _oai_envelope(request)

    if not verb:
        return _xml_response(_error(oai, "badVerb", "Missing verb"))

    if verb == "Identify":
        return _xml_response(_identify(oai))

    if verb == "GetRecord":
        identifier = request.GET.get("identifier")
        metadata_prefix = request.GET.get("metadataPrefix")
        if not identifier or not metadata_prefix:
            return _xml_response(_error(oai, "badArgument", "identifier and metadataPrefix are required"))
        if metadata_prefix != "oai_dc":
            return _xml_response(_error(oai, "cannotDisseminateFormat", "Only oai_dc is supported"))

        # Resolve Arkumu resource by identifier
        resource_uri = _parse_identifier(identifier)
        resource = Resource.objects.filter(uri=resource_uri).select_related("organization").only("id", "uri", "organization").first()
        if not resource:
            return _xml_response(_error(oai, "idDoesNotExist", "Identifier not found"))

        # Build canonical entity graph for the resource's org
        org_code = resource.organization.code if resource.organization else None
        if not org_code:
            return _xml_response(_error(oai, "idDoesNotExist", "Resource has no organization"))

        svc = CanonicalGraphService(org_code=org_code)
        graph = svc.get_entity_graph(resource_uri, include_incoming=True, expand_neighbors=False)

        # Crosswalk to oai_dc
        dc = _build_dc_metadata_from_entity_graph(graph)

        # Build OAI response
        get_record = ET.SubElement(oai, "GetRecord")
        record = ET.SubElement(get_record, "record")
        header = ET.SubElement(record, "header")
        ET.SubElement(header, "identifier").text = identifier
        ET.SubElement(header, "datestamp").text = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        metadata = ET.SubElement(record, "metadata")
        # oai_dc container
        dc_root = ET.SubElement(
            metadata,
            "{http://www.openarchives.org/OAI/2.0/oai_dc/}dc",
            {
                "xmlns:oai_dc": OAI_DC_NS,
                "xmlns:dc": DC_NS,
                "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
                "xsi:schemaLocation": " ".join(
                    [
                        OAI_DC_NS,
                        "http://www.openarchives.org/OAI/2.0/oai_dc.xsd",
                    ]
                ),
            },
        )
        for key, values in dc.items():  # key like 'dc:title'
            term = key.split(":", 1)[-1]
            for v in values:
                ET.SubElement(dc_root, f"{{{DC_NS}}}{term}").text = v

        return _xml_response(oai)

    # Minimal: unsupported verbs
    return _xml_response(_error(oai, "badVerb", "Unsupported verb"))

