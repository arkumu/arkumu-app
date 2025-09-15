from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

from django.http import HttpRequest, HttpResponse
from django.views.decorators.http import require_GET
import xml.etree.ElementTree as ET

from arkumu.metadata.models.resource import Resource, PublicAccessLevel
from arkumu.metadata.services.canonical_graph_service import CanonicalGraphService
from arkumu.users.models import Organization
from .formats.dublin_core import DublinCoreSerializer, DEFAULT_PREDICATE_MAP, DCTERMS_NS, OAI_DC_NS, DC_NS
from .formats.mets import METSSerializer
from .resumption import ResumptionTokenService


# Minimal repository config (can be moved to settings)
REPO_NAME = "Arkumu Repository"
REPO_BASEURL = "/oai/"
REPO_ADMIN_EMAIL = "admin@example.org"
REPO_PROTOCOL_VERSION = "2.0"
REPO_EARLIEST_DATASTAMP = "1970-01-01T00:00:00Z"
REPO_DELETED_RECORD = "no"
REPO_GRANULARITY = "YYYY-MM-DDThh:mm:ssZ"

# Initialize resumption token service
resumption_service = ResumptionTokenService(page_size=100)


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


def _list_metadata_formats(oai: ET.Element) -> ET.Element:
    list_metadata_formats = ET.SubElement(oai, "ListMetadataFormats")

    # Dublin Core format (mandatory)
    metadata_format = ET.SubElement(list_metadata_formats, "metadataFormat")
    ET.SubElement(metadata_format, "metadataPrefix").text = "oai_dc"
    ET.SubElement(metadata_format, "schema").text = "http://www.openarchives.org/OAI/2.0/oai_dc.xsd"
    ET.SubElement(metadata_format, "metadataNamespace").text = OAI_DC_NS

    # METS format for complete graphs
    mets_format = ET.SubElement(list_metadata_formats, "metadataFormat")
    ET.SubElement(mets_format, "metadataPrefix").text = "mets"
    ET.SubElement(mets_format, "schema").text = "http://www.loc.gov/standards/mets/mets.xsd"
    ET.SubElement(mets_format, "metadataNamespace").text = "http://www.loc.gov/METS/"

    return oai


def _list_sets(oai: ET.Element) -> ET.Element:
    list_sets = ET.SubElement(oai, "ListSets")

    # Use organizations as sets
    organizations = Organization.objects.filter(is_active=True).order_by('code')

    for org in organizations:
        set_elem = ET.SubElement(list_sets, "set")
        ET.SubElement(set_elem, "setSpec").text = org.code
        ET.SubElement(set_elem, "setName").text = org.name
        if org.domain:
            set_description = ET.SubElement(set_elem, "setDescription")
            oai_dc = ET.SubElement(
                set_description,
                "{http://www.openarchives.org/OAI/2.0/oai_dc/}dc",
                {
                    "xmlns:oai_dc": OAI_DC_NS,
                    "xmlns:dc": DC_NS,
                    "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
                    "xsi:schemaLocation": f"{OAI_DC_NS} http://www.openarchives.org/OAI/2.0/oai_dc.xsd",
                },
            )
            ET.SubElement(oai_dc, f"{{{DC_NS}}}description").text = f"Resources from {org.name} (domain: {org.domain})"

    return oai


def _list_identifiers(oai: ET.Element, request: HttpRequest) -> ET.Element:
    """Implement ListIdentifiers verb with pagination."""
    metadata_prefix = request.GET.get("metadataPrefix")
    set_spec = request.GET.get("set")
    from_date = request.GET.get("from")
    until_date = request.GET.get("until")
    resumption_token = request.GET.get("resumptionToken")

    # Validate metadata format
    if not resumption_token and (not metadata_prefix or metadata_prefix not in ["oai_dc", "mets"]):
        return _error(oai, "cannotDisseminateFormat", "Only oai_dc and mets are supported")

    # Validate date parameters
    if not resumption_token:
        if from_date:
            error_msg = _validate_datestamp(from_date)
            if error_msg:
                return _error(oai, "badArgument", f"Invalid 'from' parameter: {error_msg}")

        if until_date:
            error_msg = _validate_datestamp(until_date)
            if error_msg:
                return _error(oai, "badArgument", f"Invalid 'until' parameter: {error_msg}")

        # Validate date range
        if from_date and until_date:
            try:
                from_dt = datetime.fromisoformat(from_date.replace('Z', '+00:00')) if 'T' in from_date else datetime.strptime(from_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                until_dt = datetime.fromisoformat(until_date.replace('Z', '+00:00')) if 'T' in until_date else datetime.strptime(until_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                if from_dt > until_dt:
                    return _error(oai, "badArgument", "'from' date must be earlier than 'until' date")
            except ValueError:
                pass  # Already validated above

    # Handle resumption token
    offset = 0
    if resumption_token:
        if not resumption_token.strip():
            return _error(oai, "badResumptionToken", "Empty resumption token")

        is_valid, token_data, error_msg = resumption_service.parse_token(resumption_token)
        if not is_valid:
            return _error(oai, "badResumptionToken", error_msg or "Invalid resumption token")

        # Extract parameters from token
        offset = token_data.get("offset", 0)
        metadata_prefix = token_data.get("metadata_prefix", "oai_dc")
        set_spec = token_data.get("set")
        from_date = token_data.get("from")
        until_date = token_data.get("until")

    # Build resource queryset
    queryset = _get_resources_queryset(set_spec, from_date, until_date)

    # Get page of resources
    page_size = resumption_service.page_size
    resources = list(queryset[offset:offset + page_size + 1])  # Get one extra to check if more exist

    has_more = len(resources) > page_size
    if has_more:
        resources = resources[:-1]  # Remove the extra record

    # Check if no records match
    if offset == 0 and not resources:
        return _error(oai, "noRecordsMatch", "No records found matching the criteria")

    # Build response
    list_identifiers = ET.SubElement(oai, "ListIdentifiers")

    for resource in resources:
        header = _build_record_header(resource)
        list_identifiers.append(header)

    # Add resumption token if needed
    if has_more:
        next_offset = offset + page_size
        new_token = resumption_service.create_token(
            offset=next_offset,
            verb="ListIdentifiers",
            metadata_prefix=metadata_prefix,
            set_spec=set_spec,
            from_date=from_date,
            until_date=until_date
        )
        resumption_elem = ET.SubElement(list_identifiers, "resumptionToken")
        resumption_elem.text = new_token

    return oai


def _parse_identifier(identifier: str) -> str:
    """Parse OAI identifier to extract resource URI."""
    if identifier.startswith("oai:arkumu:resource:"):
        # New format: oai:arkumu:resource:{url_encoded_uri}
        return unquote(identifier[len("oai:arkumu:resource:"):])
    elif identifier.startswith("oai:"):
        # Legacy format: oai:*:* where last ':' part is the URI (URL-escaped)
        parts = identifier.split(":")
        if len(parts) >= 3:
            return unquote(parts[-1])
    return identifier


def _get_resources_queryset(set_spec: Optional[str] = None, from_date: Optional[str] = None, until_date: Optional[str] = None):
    """Build a filtered queryset for harvestable resources."""
    # Only public approved resources are harvestable
    queryset = Resource.objects.filter(
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True
    ).select_related('organization').order_by('updated_at', 'id')

    # Filter by set (organization)
    if set_spec:
        queryset = queryset.filter(organization__code=set_spec, organization__is_active=True)

    # Temporal filtering with proper OAI-PMH date validation
    if from_date:
        try:
            # Support both YYYY-MM-DD and YYYY-MM-DDThh:mm:ssZ formats
            if 'T' in from_date:
                from_dt = datetime.fromisoformat(from_date.replace('Z', '+00:00'))
            else:
                from_dt = datetime.strptime(from_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
            queryset = queryset.filter(updated_at__gte=from_dt)
        except ValueError:
            pass  # Invalid date format, ignore

    if until_date:
        try:
            # Support both YYYY-MM-DD and YYYY-MM-DDThh:mm:ssZ formats
            if 'T' in until_date:
                until_dt = datetime.fromisoformat(until_date.replace('Z', '+00:00'))
            else:
                until_dt = datetime.strptime(until_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                # For date-only format, include the entire day
                until_dt = until_dt.replace(hour=23, minute=59, second=59)
            queryset = queryset.filter(updated_at__lte=until_dt)
        except ValueError:
            pass  # Invalid date format, ignore

    return queryset


def _format_datestamp(dt: datetime) -> str:
    """Format datetime as OAI-PMH datestamp."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate_datestamp(date_str: str) -> Optional[str]:
    """Validate OAI-PMH datestamp format. Returns error message if invalid."""
    if not date_str:
        return None

    try:
        # Support both YYYY-MM-DD and YYYY-MM-DDThh:mm:ssZ formats
        if 'T' in date_str:
            datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        else:
            datetime.strptime(date_str, '%Y-%m-%d')
        return None  # Valid
    except ValueError:
        return "Invalid date format. Use YYYY-MM-DD or YYYY-MM-DDThh:mm:ssZ"


def _build_identifier(resource_uri: str) -> str:
    """Build OAI identifier from resource URI."""
    from urllib.parse import quote
    return f"oai:arkumu:resource:{quote(resource_uri)}"


def _build_record_header(resource: Resource) -> ET.Element:
    """Build OAI record header."""
    header = ET.Element("header")
    ET.SubElement(header, "identifier").text = _build_identifier(resource.uri)
    ET.SubElement(header, "datestamp").text = _format_datestamp(resource.updated_at)
    if resource.organization:
        ET.SubElement(header, "setSpec").text = resource.organization.code
    return header


def _build_metadata_element(resource: Resource, metadata_prefix: str) -> ET.Element:
    """Build metadata element for different formats."""
    metadata = ET.Element("metadata")

    if metadata_prefix == "oai_dc":
        # Build Dublin Core metadata
        org_code = resource.organization.code if resource.organization else None
        if not org_code:
            return metadata  # Empty metadata if no organization

        svc = CanonicalGraphService(org_code=org_code)
        graph = svc.get_entity_graph(resource.uri, include_incoming=True, expand_neighbors=False)
        dc = _build_dc_metadata_from_entity_graph(graph)

        # oai_dc container
        dc_root = ET.SubElement(
            metadata,
            "{http://www.openarchives.org/OAI/2.0/oai_dc/}dc",
            {
                "xmlns:oai_dc": OAI_DC_NS,
                "xmlns:dc": DC_NS,
                "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
                "xsi:schemaLocation": " ".join([
                    OAI_DC_NS,
                    "http://www.openarchives.org/OAI/2.0/oai_dc.xsd",
                ]),
            },
        )
        for key, values in dc.items():  # key like 'dc:title'
            term = key.split(":", 1)[-1]
            for v in values:
                ET.SubElement(dc_root, f"{{{DC_NS}}}{term}").text = v

    elif metadata_prefix == "mets":
        # Build METS metadata with complete graph
        org_code = resource.organization.code if resource.organization else None
        if not org_code:
            return metadata  # Empty metadata if no organization

        mets_serializer = METSSerializer(org_code=org_code)
        mets_xml = mets_serializer.serialize_resource(resource.uri, include_complete_graph=True)

        # Parse the METS XML and embed it
        try:
            mets_tree = ET.fromstring(mets_xml)
            metadata.append(mets_tree)
        except ET.ParseError:
            pass  # If METS parsing fails, return empty metadata

    return metadata


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


def _list_records(oai: ET.Element, request: HttpRequest) -> ET.Element:
    """Implement ListRecords verb with complete metadata and pagination."""
    metadata_prefix = request.GET.get("metadataPrefix")
    set_spec = request.GET.get("set")
    from_date = request.GET.get("from")
    until_date = request.GET.get("until")
    resumption_token = request.GET.get("resumptionToken")

    # Validate metadata format
    if not resumption_token and (not metadata_prefix or metadata_prefix not in ["oai_dc", "mets"]):
        return _error(oai, "cannotDisseminateFormat", "Only oai_dc and mets are supported")

    # Validate date parameters
    if not resumption_token:
        if from_date:
            error_msg = _validate_datestamp(from_date)
            if error_msg:
                return _error(oai, "badArgument", f"Invalid 'from' parameter: {error_msg}")

        if until_date:
            error_msg = _validate_datestamp(until_date)
            if error_msg:
                return _error(oai, "badArgument", f"Invalid 'until' parameter: {error_msg}")

        # Validate date range
        if from_date and until_date:
            try:
                from_dt = datetime.fromisoformat(from_date.replace('Z', '+00:00')) if 'T' in from_date else datetime.strptime(from_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                until_dt = datetime.fromisoformat(until_date.replace('Z', '+00:00')) if 'T' in until_date else datetime.strptime(until_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                if from_dt > until_dt:
                    return _error(oai, "badArgument", "'from' date must be earlier than 'until' date")
            except ValueError:
                pass  # Already validated above

    # Handle resumption token
    offset = 0
    if resumption_token:
        if not resumption_token.strip():
            return _error(oai, "badResumptionToken", "Empty resumption token")

        is_valid, token_data, error_msg = resumption_service.parse_token(resumption_token)
        if not is_valid:
            return _error(oai, "badResumptionToken", error_msg or "Invalid resumption token")

        # Extract parameters from token
        offset = token_data.get("offset", 0)
        metadata_prefix = token_data.get("metadata_prefix", "oai_dc")
        set_spec = token_data.get("set")
        from_date = token_data.get("from")
        until_date = token_data.get("until")

    # Build resource queryset
    queryset = _get_resources_queryset(set_spec, from_date, until_date)

    # Get page of resources
    page_size = resumption_service.page_size
    resources = list(queryset[offset:offset + page_size + 1])  # Get one extra to check if more exist

    has_more = len(resources) > page_size
    if has_more:
        resources = resources[:-1]  # Remove the extra record

    # Check if no records match
    if offset == 0 and not resources:
        return _error(oai, "noRecordsMatch", "No records found matching the criteria")

    # Build response
    list_records = ET.SubElement(oai, "ListRecords")

    for resource in resources:
        record = ET.SubElement(list_records, "record")

        # Add header
        header = _build_record_header(resource)
        record.append(header)

        # Add metadata
        metadata = _build_metadata_element(resource, metadata_prefix)
        record.append(metadata)

    # Add resumption token if needed
    if has_more:
        next_offset = offset + page_size
        new_token = resumption_service.create_token(
            offset=next_offset,
            verb="ListRecords",
            metadata_prefix=metadata_prefix,
            set_spec=set_spec,
            from_date=from_date,
            until_date=until_date
        )
        resumption_elem = ET.SubElement(list_records, "resumptionToken")
        resumption_elem.text = new_token

    return oai


@require_GET
def oai_endpoint(request: HttpRequest) -> HttpResponse:
    try:
        verb = request.GET.get("verb", "").strip()
        oai = _oai_envelope(request)

        # Check for illegal arguments first
        valid_verbs = ["Identify", "ListMetadataFormats", "ListSets", "ListIdentifiers", "ListRecords", "GetRecord"]
        all_args = set(request.GET.keys())

        if not verb:
            return _xml_response(_error(oai, "badVerb", "Missing verb"))

        if verb not in valid_verbs:
            return _xml_response(_error(oai, "badVerb", f"Illegal verb: {verb}"))

        # Check for illegal arguments by verb
        legal_args = {
            "Identify": set(),
            "ListMetadataFormats": {"identifier"},  # Optional
            "ListSets": {"resumptionToken"},  # Optional
            "ListIdentifiers": {"metadataPrefix", "from", "until", "set", "resumptionToken"},
            "ListRecords": {"metadataPrefix", "from", "until", "set", "resumptionToken"},
            "GetRecord": {"identifier", "metadataPrefix"}
        }

        # Always allow 'verb' parameter
        allowed_args = legal_args.get(verb, set()) | {"verb"}
        illegal_args = all_args - allowed_args

        if illegal_args:
            return _xml_response(_error(oai, "badArgument", f"Illegal argument(s): {', '.join(illegal_args)}"))

        if verb == "Identify":
            return _xml_response(_identify(oai))

        if verb == "ListMetadataFormats":
            return _xml_response(_list_metadata_formats(oai))

        if verb == "ListSets":
            return _xml_response(_list_sets(oai))

        if verb == "ListIdentifiers":
            # Exclusive argument checking
            resumption_token = request.GET.get("resumptionToken")
            if resumption_token and len([k for k in request.GET.keys() if k != "verb" and k != "resumptionToken"]) > 0:
                return _xml_response(_error(oai, "badArgument", "resumptionToken cannot be combined with other arguments"))

            # Required argument checking
            if not resumption_token and not request.GET.get("metadataPrefix"):
                return _xml_response(_error(oai, "badArgument", "metadataPrefix is required"))

            return _xml_response(_list_identifiers(oai, request))

        if verb == "ListRecords":
            # Exclusive argument checking
            resumption_token = request.GET.get("resumptionToken")
            if resumption_token and len([k for k in request.GET.keys() if k != "verb" and k != "resumptionToken"]) > 0:
                return _xml_response(_error(oai, "badArgument", "resumptionToken cannot be combined with other arguments"))

            # Required argument checking
            if not resumption_token and not request.GET.get("metadataPrefix"):
                return _xml_response(_error(oai, "badArgument", "metadataPrefix is required"))

            return _xml_response(_list_records(oai, request))

        if verb == "GetRecord":
            identifier = request.GET.get("identifier")
            metadata_prefix = request.GET.get("metadataPrefix")
            if not identifier or not metadata_prefix:
                return _xml_response(_error(oai, "badArgument", "identifier and metadataPrefix are required"))
            if metadata_prefix not in ["oai_dc", "mets"]:
                return _xml_response(_error(oai, "cannotDisseminateFormat", "Only oai_dc and mets are supported"))

            # Resolve Arkumu resource by identifier
            resource_uri = _parse_identifier(identifier)
            resource = Resource.objects.filter(
                uri=resource_uri,
                public_access_level=PublicAccessLevel.PUBLIC,
                is_public_approved=True
            ).select_related("organization").first()

            if not resource:
                return _xml_response(_error(oai, "idDoesNotExist", "Identifier not found"))

            if not resource.organization:
                return _xml_response(_error(oai, "idDoesNotExist", "Resource has no organization"))

            # Build OAI response
            get_record = ET.SubElement(oai, "GetRecord")
            record = ET.SubElement(get_record, "record")

            # Add header
            header = _build_record_header(resource)
            record.append(header)

            # Add metadata
            metadata = _build_metadata_element(resource, metadata_prefix)
            record.append(metadata)

            return _xml_response(oai)

        # This should never be reached due to earlier validation
        return _xml_response(_error(oai, "badVerb", "Unsupported verb"))

    except Exception as e:
        # Global exception handler for any unexpected errors
        oai = _oai_envelope(request)
        return _xml_response(_error(oai, "internalError", f"Internal server error: {str(e)}"))

