"""OAI-PMH endpoint using pre-serialized snapshot records.

Reads from OAISnapshotRecord table for fast response times.
Simple offset-based pagination with snapshot timestamp validation.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone as dt_timezone
from typing import Optional
from urllib.parse import urlencode

from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from lxml import etree as ET

from arkumu.users.mixins import general_login_required

from arkumu.oaipmh.models import OAISnapshotMeta, OAISnapshotRecord
from arkumu.users.models import Organization

logger = logging.getLogger(__name__)

# OAI-PMH namespaces
OAI_NS = "http://www.openarchives.org/OAI/2.0/"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

# Repository configuration
REPO_NAME = "Arkumu Repository"
REPO_ADMIN_EMAIL = "mondaca@uni-koeln.de"
REPO_PROTOCOL_VERSION = "2.0"
REPO_DELETED_RECORD = "no"
REPO_GRANULARITY = "YYYY-MM-DDThh:mm:ssZ"

# Pagination
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 500

SUPPORTED_METADATA_FORMATS = {
    "oai_dc": {
        "schema": "http://www.openarchives.org/OAI/2.0/oai_dc.xsd",
        "namespace": "http://www.openarchives.org/OAI/2.0/oai_dc/",
    },
    "mets": {
        "schema": "http://www.loc.gov/standards/mets/mets.xsd",
        "namespace": "http://www.loc.gov/METS/",
    },
}


def _build_oai_response(request: HttpRequest, verb: str) -> ET._Element:
    """Create base OAI-PMH response envelope."""
    nsmap = {
        None: OAI_NS,
        "xsi": XSI_NS,
    }
    root = ET.Element(ET.QName(OAI_NS, "OAI-PMH"), nsmap=nsmap)
    root.set(
        ET.QName(XSI_NS, "schemaLocation"),
        f"{OAI_NS} http://www.openarchives.org/OAI/2.0/OAI-PMH.xsd",
    )

    response_date = ET.SubElement(root, ET.QName(OAI_NS, "responseDate"))
    response_date.text = datetime.now(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    request_elem = ET.SubElement(root, ET.QName(OAI_NS, "request"))
    request_elem.text = request.build_absolute_uri(request.path)
    request_elem.set("verb", verb)

    return root


def _error_response(request: HttpRequest, verb: str, code: str, message: str) -> HttpResponse:
    """Build OAI-PMH error response."""
    root = _build_oai_response(request, verb)
    error = ET.SubElement(root, ET.QName(OAI_NS, "error"))
    error.set("code", code)
    error.text = message

    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return HttpResponse(xml_bytes, content_type="application/xml")


def _get_base_url(request: HttpRequest) -> str:
    """Get the base URL for OAI requests."""
    return request.build_absolute_uri(request.path)


def _parse_resumption_token(token: str) -> tuple[int, str]:
    """Parse resumption token into (offset, snapshot_marker).

    Token format: <offset>:<snapshot_timestamp>
    """
    if ":" not in token:
        raise ValueError("Invalid token format")

    parts = token.split(":", 1)
    offset = int(parts[0])
    marker = parts[1]
    return offset, marker


def _build_resumption_token(offset: int, marker: str, total: int, cursor: int) -> ET._Element:
    """Build resumptionToken element."""
    token_elem = ET.Element(ET.QName(OAI_NS, "resumptionToken"))
    token_elem.set("completeListSize", str(total))
    token_elem.set("cursor", str(cursor))
    token_elem.text = f"{offset}:{marker}"
    return token_elem


@general_login_required
@csrf_exempt
@require_http_methods(["GET", "POST"])
def oai_snapshot_handler(request: HttpRequest) -> HttpResponse:
    """Main OAI-PMH endpoint handler."""
    params = request.GET if request.method == "GET" else request.POST
    verb = params.get("verb", "")

    if not verb:
        return _error_response(request, "", "badVerb", "Missing verb parameter")

    handlers = {
        "Identify": _handle_identify,
        "ListMetadataFormats": _handle_list_metadata_formats,
        "ListSets": _handle_list_sets,
        "ListIdentifiers": _handle_list_identifiers,
        "ListRecords": _handle_list_records,
        "GetRecord": _handle_get_record,
    }

    handler = handlers.get(verb)
    if not handler:
        return _error_response(request, verb, "badVerb", f"Unknown verb: {verb}")

    return handler(request, params)


def _handle_identify(request: HttpRequest, params: dict) -> HttpResponse:
    """Handle Identify verb."""
    root = _build_oai_response(request, "Identify")
    identify = ET.SubElement(root, ET.QName(OAI_NS, "Identify"))

    ET.SubElement(identify, ET.QName(OAI_NS, "repositoryName")).text = REPO_NAME
    ET.SubElement(identify, ET.QName(OAI_NS, "baseURL")).text = _get_base_url(request)
    ET.SubElement(identify, ET.QName(OAI_NS, "protocolVersion")).text = REPO_PROTOCOL_VERSION
    ET.SubElement(identify, ET.QName(OAI_NS, "adminEmail")).text = REPO_ADMIN_EMAIL

    meta = OAISnapshotMeta.get_current()
    earliest = "1970-01-01T00:00:00Z"
    if meta:
        earliest = meta.generated_at.strftime("%Y-%m-%dT%H:%M:%SZ")

    ET.SubElement(identify, ET.QName(OAI_NS, "earliestDatestamp")).text = earliest
    ET.SubElement(identify, ET.QName(OAI_NS, "deletedRecord")).text = REPO_DELETED_RECORD
    ET.SubElement(identify, ET.QName(OAI_NS, "granularity")).text = REPO_GRANULARITY

    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return HttpResponse(xml_bytes, content_type="application/xml")


def _handle_list_metadata_formats(request: HttpRequest, params: dict) -> HttpResponse:
    """Handle ListMetadataFormats verb."""
    identifier = params.get("identifier")

    if identifier:
        record = OAISnapshotRecord.objects.filter(uri=identifier).first()
        if not record:
            return _error_response(request, "ListMetadataFormats", "idDoesNotExist", "Record not found")

    root = _build_oai_response(request, "ListMetadataFormats")
    list_elem = ET.SubElement(root, ET.QName(OAI_NS, "ListMetadataFormats"))

    for prefix, info in SUPPORTED_METADATA_FORMATS.items():
        fmt = ET.SubElement(list_elem, ET.QName(OAI_NS, "metadataFormat"))
        ET.SubElement(fmt, ET.QName(OAI_NS, "metadataPrefix")).text = prefix
        ET.SubElement(fmt, ET.QName(OAI_NS, "schema")).text = info["schema"]
        ET.SubElement(fmt, ET.QName(OAI_NS, "metadataNamespace")).text = info["namespace"]

    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return HttpResponse(xml_bytes, content_type="application/xml")


def _handle_list_sets(request: HttpRequest, params: dict) -> HttpResponse:
    """Handle ListSets verb - returns organizations as sets."""
    root = _build_oai_response(request, "ListSets")
    list_elem = ET.SubElement(root, ET.QName(OAI_NS, "ListSets"))

    orgs = Organization.objects.filter(oai_snapshot_records__isnull=False).distinct()
    for org in orgs:
        set_elem = ET.SubElement(list_elem, ET.QName(OAI_NS, "set"))
        ET.SubElement(set_elem, ET.QName(OAI_NS, "setSpec")).text = org.code
        ET.SubElement(set_elem, ET.QName(OAI_NS, "setName")).text = org.name or org.code

    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return HttpResponse(xml_bytes, content_type="application/xml")


def _handle_get_record(request: HttpRequest, params: dict) -> HttpResponse:
    """Handle GetRecord verb."""
    identifier = params.get("identifier")
    metadata_prefix = params.get("metadataPrefix")

    if not identifier:
        return _error_response(request, "GetRecord", "badArgument", "Missing identifier")
    if not metadata_prefix:
        return _error_response(request, "GetRecord", "badArgument", "Missing metadataPrefix")
    if metadata_prefix not in SUPPORTED_METADATA_FORMATS:
        return _error_response(request, "GetRecord", "cannotDisseminateFormat", f"Unsupported format: {metadata_prefix}")

    record = OAISnapshotRecord.objects.filter(uri=identifier).first()
    if not record:
        return _error_response(request, "GetRecord", "idDoesNotExist", "Record not found")

    root = _build_oai_response(request, "GetRecord")
    get_record = ET.SubElement(root, ET.QName(OAI_NS, "GetRecord"))

    record_elem = ET.SubElement(get_record, ET.QName(OAI_NS, "record"))

    # Add pre-serialized header
    header_elem = ET.fromstring(record.header_xml)
    record_elem.append(header_elem)

    # Add pre-serialized metadata
    metadata_xml = record.metadata_dc_xml if metadata_prefix == "oai_dc" else record.metadata_mets_xml
    if metadata_xml:
        metadata_elem = ET.fromstring(metadata_xml)
        record_elem.append(metadata_elem)

    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return HttpResponse(xml_bytes, content_type="application/xml")


def _handle_list_identifiers(request: HttpRequest, params: dict) -> HttpResponse:
    """Handle ListIdentifiers verb."""
    return _handle_list_common(request, params, include_metadata=False)


def _handle_list_records(request: HttpRequest, params: dict) -> HttpResponse:
    """Handle ListRecords verb."""
    return _handle_list_common(request, params, include_metadata=True)


def _handle_list_common(
    request: HttpRequest,
    params: dict,
    include_metadata: bool,
) -> HttpResponse:
    """Common handler for ListIdentifiers and ListRecords."""
    verb = "ListRecords" if include_metadata else "ListIdentifiers"

    resumption_token = params.get("resumptionToken")
    metadata_prefix = params.get("metadataPrefix")
    set_spec = params.get("set")
    from_date = params.get("from")
    until_date = params.get("until")

    # Get current snapshot metadata
    meta = OAISnapshotMeta.get_current()
    if not meta:
        return _error_response(request, verb, "noRecordsMatch", "No snapshot available")

    snapshot_marker = meta.generated_at.isoformat()

    # Parse resumption token or validate initial request
    offset = 0
    if resumption_token:
        try:
            offset, token_marker = _parse_resumption_token(resumption_token)
            if token_marker != snapshot_marker:
                return _error_response(
                    request, verb, "badResumptionToken",
                    "Snapshot has changed; restart harvesting"
                )
        except (ValueError, TypeError):
            return _error_response(request, verb, "badResumptionToken", "Invalid resumption token")
    else:
        if not metadata_prefix:
            return _error_response(request, verb, "badArgument", "Missing metadataPrefix")
        if metadata_prefix not in SUPPORTED_METADATA_FORMATS:
            return _error_response(request, verb, "cannotDisseminateFormat", f"Unsupported format: {metadata_prefix}")

    # For resumption, we need to remember the metadata_prefix
    if resumption_token and not metadata_prefix:
        metadata_prefix = "oai_dc"  # Default for resumed requests

    # Build queryset
    qs = OAISnapshotRecord.objects.all()

    if set_spec:
        org = Organization.objects.filter(code=set_spec).first()
        if not org:
            return _error_response(request, verb, "noRecordsMatch", f"Unknown set: {set_spec}")
        qs = qs.filter(organization=org)

    if from_date:
        try:
            from_dt = datetime.fromisoformat(from_date.replace("Z", "+00:00"))
            qs = qs.filter(datestamp__gte=from_dt)
        except ValueError:
            return _error_response(request, verb, "badArgument", f"Invalid from date: {from_date}")

    if until_date:
        try:
            until_dt = datetime.fromisoformat(until_date.replace("Z", "+00:00"))
            qs = qs.filter(datestamp__lte=until_dt)
        except ValueError:
            return _error_response(request, verb, "badArgument", f"Invalid until date: {until_date}")

    total_count = qs.count()
    if total_count == 0:
        return _error_response(request, verb, "noRecordsMatch", "No records match the request")

    # Get page of records
    page_size = DEFAULT_PAGE_SIZE
    records = list(qs.order_by("position")[offset : offset + page_size])

    # Build response
    root = _build_oai_response(request, verb)
    list_elem = ET.SubElement(root, ET.QName(OAI_NS, verb))

    for record in records:
        record_elem = ET.SubElement(list_elem, ET.QName(OAI_NS, "record"))

        # Add pre-serialized header
        try:
            header_elem = ET.fromstring(record.header_xml)
            record_elem.append(header_elem)
        except ET.XMLSyntaxError:
            logger.warning("Invalid header XML for %s", record.uri)
            continue

        # Add metadata if ListRecords
        if include_metadata:
            metadata_xml = record.metadata_dc_xml if metadata_prefix == "oai_dc" else record.metadata_mets_xml
            if metadata_xml:
                try:
                    metadata_elem = ET.fromstring(metadata_xml)
                    record_elem.append(metadata_elem)
                except ET.XMLSyntaxError:
                    logger.warning("Invalid metadata XML for %s", record.uri)

    # Add resumption token if more records
    next_offset = offset + len(records)
    if next_offset < total_count:
        token_elem = _build_resumption_token(next_offset, snapshot_marker, total_count, offset)
        list_elem.append(token_elem)
    elif resumption_token:
        # Empty token to signal completion
        token_elem = ET.SubElement(list_elem, ET.QName(OAI_NS, "resumptionToken"))
        token_elem.set("completeListSize", str(total_count))
        token_elem.set("cursor", str(offset))

    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return HttpResponse(xml_bytes, content_type="application/xml")
