from __future__ import annotations

import logging
import mimetypes
import re
from pathlib import Path
from datetime import datetime, timezone as dt_timezone
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urlparse

from django.http import HttpRequest, HttpResponse
from django.views.decorators.http import require_GET
from django.utils import timezone
import xml.etree.ElementTree as ET

from django.db.models import Q

from arkumu.metadata.models.resource import Resource, PublicAccessLevel, ResourceType
from arkumu.users.models import Organization
from arkumu.projects import ProjectDigitalObject, ProjectRecord
from arkumu.projects.services import ProjectSnapshotService
from arkumu.metadata.services.canonical_graph_service import CanonicalGraphService
from .formats.dublin_core import DCTERMS_NS, OAI_DC_NS, DC_NS
from .resumption import ResumptionTokenService
from arkumu.common.uri_utils import slugify_uri_part
from arkumu.cache.services import OAICacheService
from .authentication import oai_authentication_required
import rdflib


# Minimal repository config (can be moved to settings)
REPO_NAME = "Arkumu Repository"
REPO_BASEURL = "/oai/"
REPO_ADMIN_EMAIL = "admin@example.org"
REPO_PROTOCOL_VERSION = "2.0"
REPO_EARLIEST_DATASTAMP = "1970-01-01T00:00:00Z"
REPO_DELETED_RECORD = "no"
REPO_GRANULARITY = "YYYY-MM-DDThh:mm:ssZ"
REPO_REPOSITORY_IDENTIFIER = "arkumu"

ROSETTA_METS_NS = "http://www.exlibrisgroup.com/xsd/dps/rosettaMets"
ROSETTA_DNX_NS = "http://www.exlibrisgroup.com/dps/dnx"
ROSETTA_XLINK_NS = "http://www.w3.org/1999/xlink"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS_NS = "http://www.w3.org/2000/01/rdf-schema#"
SUPPORTED_METADATA_FORMATS = ["oai_dc", "mets", "rdf"]
ROSETTA_METS_PROFILE_VERSION = "2025-09-23"

PROPERTY_NAMESPACE_PATTERN = re.compile(r"^(https?://arkumu\.org/data/)([^/]+/)?(properties/)")

# Initialize services
resumption_service = ResumptionTokenService(page_size=100)
oai_cache = OAICacheService()
snapshot_service = ProjectSnapshotService()

logger = logging.getLogger(__name__)


def _get_cached_record(resource: Resource, metadata_prefix: str) -> Optional[Dict[str, Any]]:
    """Get cached OAI-PMH record if available."""
    profile_version = ROSETTA_METS_PROFILE_VERSION if metadata_prefix == "mets" else ""
    return oai_cache.get_cached_record(resource, metadata_prefix, profile_version=profile_version)


def _cache_record(resource: Resource, metadata_prefix: str, header_xml: str, metadata_xml: str):
    """Cache OAI-PMH record data."""
    profile_version = ROSETTA_METS_PROFILE_VERSION if metadata_prefix == "mets" else ""
    oai_cache.cache_record(resource, metadata_prefix, header_xml, metadata_xml, profile_version=profile_version)


def _oai_envelope(request: HttpRequest) -> ET.Element:
    # Register namespaces to control prefixes consistently
    ET.register_namespace("", "http://www.openarchives.org/OAI/2.0/")
    ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")

    oai = ET.Element(
        "OAI-PMH",
            {
                "xmlns": "http://www.openarchives.org/OAI/2.0/",
                "xmlns:oai_dc": "http://www.openarchives.org/OAI/2.0/oai_dc/",
                "xmlns:dc": "http://purl.org/dc/elements/1.1/",
                "xmlns:dcterms": DCTERMS_NS,
                "xmlns:mets": ROSETTA_METS_NS,
                "xmlns:xlink": ROSETTA_XLINK_NS,
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
    responseDate.text = timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ")

    req = ET.SubElement(oai, "request")
    req.text = request.build_absolute_uri(REPO_BASEURL)
    return oai


def _error(oai: ET.Element, code: str, message: str) -> ET.Element:
    e = ET.SubElement(oai, "error", {"code": code})
    e.text = message
    return oai


def _xml_response(elem: ET.Element) -> HttpResponse:
    data = ET.tostring(elem, encoding="utf-8", xml_declaration=True)

    # Clean up duplicate namespace declarations in XML string
    # This is needed because ElementTree can create duplicates when embedding
    # elements with conflicting namespace declarations
    xml_str = data.decode("utf-8")

    # Remove duplicate xmlns:xsi declarations
    # Find all xmlns:xsi declarations and keep only the first one
    xsi_pattern = r'xmlns:xsi="[^"]*"'
    matches = list(re.finditer(xsi_pattern, xml_str))
    if len(matches) > 1:
        # Remove all but the first occurrence
        for match in reversed(matches[1:]):  # Reverse to avoid index issues
            xml_str = xml_str[:match.start()] + xml_str[match.end():]

    # Do the same for other commonly duplicated namespaces
    for ns_prefix in ['xmlns:dc', 'xmlns:dcterms', 'xmlns:mets', 'xmlns:xlink']:
        pattern = rf'{re.escape(ns_prefix)}="[^"]*"'
        matches = list(re.finditer(pattern, xml_str))
        if len(matches) > 1:
            for match in reversed(matches[1:]):
                xml_str = xml_str[:match.start()] + xml_str[match.end():]

    canonical_ns_map = {
        ROSETTA_METS_NS: 'mets',
        DC_NS: 'dc',
        DCTERMS_NS: 'dcterms',
        ROSETTA_XLINK_NS: 'xlink',
        ROSETTA_DNX_NS: '',
    }

    alias_pattern = re.compile(r'\s+xmlns:(ns\d+)="([^"]+)"')
    alias_matches = list(alias_pattern.finditer(xml_str))
    for match in reversed(alias_matches):
        alias, uri = match.groups()
        if uri not in canonical_ns_map:
            continue

        xml_str = xml_str[:match.start()] + xml_str[match.end():]
        replacement_prefix = canonical_ns_map[uri]
        if replacement_prefix:
            xml_str = re.sub(rf'\b{alias}:', f'{replacement_prefix}:', xml_str)
        else:
            xml_str = re.sub(rf'\b{alias}:', '', xml_str)
            default_declaration = f'xmlns="{uri}"'
            if default_declaration not in xml_str:
                xml_str = xml_str.replace('<mets:mets', f'<mets:mets {default_declaration}', 1)

    default_declaration = f'xmlns="{ROSETTA_DNX_NS}"'
    if '<mets:mets' in xml_str and default_declaration not in xml_str:
        xml_str = xml_str.replace('<mets:mets', f'<mets:mets {default_declaration}', 1)

# ElementTree naturally uses single quotes, keep them

    return HttpResponse(xml_str.encode("utf-8"), content_type="text/xml")


def _identify(oai: ET.Element, request: HttpRequest) -> ET.Element:
    identify = ET.SubElement(oai, "Identify")
    ET.SubElement(identify, "repositoryName").text = REPO_NAME
    # Absolute baseURL per spec
    absolute_base = request.build_absolute_uri(REPO_BASEURL)
    ET.SubElement(identify, "baseURL").text = absolute_base
    ET.SubElement(identify, "protocolVersion").text = REPO_PROTOCOL_VERSION
    ET.SubElement(identify, "adminEmail").text = REPO_ADMIN_EMAIL

    # Compute earliestDatestamp from harvestable resources; fallback to configured default
    try:
        earliest = (
            Resource.objects
            .order_by("updated_at")
            .values_list("updated_at", flat=True)
            .first()
        )
        if earliest is not None:
            # Ensure timezone-aware UTC before formatting
            if earliest.tzinfo is None:
                earliest = earliest.replace(tzinfo=dt_dt_timezone.utc)
            ET.SubElement(identify, "earliestDatestamp").text = _format_datestamp(earliest)
        else:
            ET.SubElement(identify, "earliestDatestamp").text = REPO_EARLIEST_DATASTAMP
    except Exception:
        ET.SubElement(identify, "earliestDatestamp").text = REPO_EARLIEST_DATASTAMP

    ET.SubElement(identify, "deletedRecord").text = REPO_DELETED_RECORD
    ET.SubElement(identify, "granularity").text = REPO_GRANULARITY

    # Add <description> with oai-identifier declaration
    try:
        desc = ET.SubElement(identify, "description")
        oai_ident = ET.SubElement(
            desc,
            "{http://www.openarchives.org/OAI/2.0/oai-identifier}oai-identifier",
            {
                "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation": (
                    "http://www.openarchives.org/OAI/2.0/oai-identifier "
                    "http://www.openarchives.org/OAI/2.0/oai-identifier.xsd"
                )
            },
        )
        ET.SubElement(oai_ident, "{http://www.openarchives.org/OAI/2.0/oai-identifier}scheme").text = "oai"
        ET.SubElement(
            oai_ident,
            "{http://www.openarchives.org/OAI/2.0/oai-identifier}repositoryIdentifier",
        ).text = REPO_REPOSITORY_IDENTIFIER
        ET.SubElement(
            oai_ident, "{http://www.openarchives.org/OAI/2.0/oai-identifier}delimiter"
        ).text = ":"

        # Build a sample identifier; prefer a real resource if available
        sample_uri: Optional[str] = (
            Resource.objects
            .order_by("id")
            .values_list("uri", flat=True)
            .first()
        )
        if not sample_uri:
            sample_uri = "https://example.org/entities/sample"
        ET.SubElement(
            oai_ident, "{http://www.openarchives.org/OAI/2.0/oai-identifier}sampleIdentifier"
        ).text = _build_identifier(sample_uri)
    except Exception:
        # Non-fatal if description cannot be built
        pass

    return oai


def _list_metadata_formats(oai: ET.Element, identifier: Optional[str] = None) -> ET.Element:
    # If identifier is provided, validate it exists
    if identifier:
        resource_uri = _parse_identifier(identifier)
        resource = Resource.objects.filter(
            uri=resource_uri
        ).first()

        if not resource:
            return _error(oai, "idDoesNotExist", "Identifier not found")

    list_metadata_formats = ET.SubElement(oai, "ListMetadataFormats")

    # Dublin Core format (mandatory)
    metadata_format = ET.SubElement(list_metadata_formats, "metadataFormat")
    ET.SubElement(metadata_format, "metadataPrefix").text = "oai_dc"
    ET.SubElement(metadata_format, "schema").text = "http://www.openarchives.org/OAI/2.0/oai_dc.xsd"
    ET.SubElement(metadata_format, "metadataNamespace").text = OAI_DC_NS

    # METS format for complete graphs
    mets_format = ET.SubElement(list_metadata_formats, "metadataFormat")
    ET.SubElement(mets_format, "metadataPrefix").text = "mets"
    ET.SubElement(mets_format, "schema").text = ROSETTA_METS_NS
    ET.SubElement(mets_format, "metadataNamespace").text = ROSETTA_METS_NS

    # RDF/XML format for canonical graph export
    rdf_format = ET.SubElement(list_metadata_formats, "metadataFormat")
    ET.SubElement(rdf_format, "metadataPrefix").text = "rdf"
    ET.SubElement(rdf_format, "schema").text = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    ET.SubElement(rdf_format, "metadataNamespace").text = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"

    return oai


def _list_sets(oai: ET.Element) -> ET.Element:
    list_sets = ET.SubElement(oai, "ListSets")

    # Use organizations as sets - show all organizations
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
    has_resumption_param = "resumptionToken" in request.GET

    # Validate metadata format
    if not has_resumption_param and (not metadata_prefix or metadata_prefix not in SUPPORTED_METADATA_FORMATS):
        return _error(oai, "cannotDisseminateFormat", "Only oai_dc, mets, and rdf are supported")

    # Validate date parameters
    if not has_resumption_param:
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
                from_dt = datetime.fromisoformat(from_date.replace('Z', '+00:00')) if 'T' in from_date else datetime.strptime(from_date, '%Y-%m-%d').replace(tzinfo=dt_timezone.utc)
                until_dt = datetime.fromisoformat(until_date.replace('Z', '+00:00')) if 'T' in until_date else datetime.strptime(until_date, '%Y-%m-%d').replace(tzinfo=dt_timezone.utc)
                if from_dt > until_dt:
                    return _error(oai, "badArgument", "'from' date must be earlier than 'until' date")
            except ValueError:
                pass  # Already validated above

    # Handle resumption token
    offset = 0
    if has_resumption_param:
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
    queryset = _get_resources_queryset(set_spec, from_date, until_date, metadata_prefix)

    # Get page of resources
    page_size = resumption_service.page_size
    resources = list(queryset[offset:offset + page_size + 1])  # Get one extra to check if more exist

    has_more = len(resources) > page_size
    if has_more:
        resources = resources[:-1]  # Remove the extra record

    # Check if no records match
    if offset == 0 and not resources:
        return _error(oai, "noRecordsMatch", "No records found matching the criteria")

    cached_page = oai_cache.get_cached_page(
        verb='ListIdentifiers',
        metadata_prefix=metadata_prefix,
        set_spec=set_spec or '',
        from_date=from_date or '',
        until_date=until_date or '',
        offset=offset
    )
    if cached_page:
        # Rebuild from cached data
        list_identifiers = ET.SubElement(oai, "ListIdentifiers")

        for record_data in cached_page['headers']:
            header = ET.fromstring(record_data)
            list_identifiers.append(header)

        # Add cached resumption token if present
        if cached_page.get('resumption_token'):
            resumption_elem = ET.SubElement(list_identifiers, "resumptionToken")
            resumption_elem.text = cached_page['resumption_token']

        return oai

    # Build response (cache miss)
    list_identifiers = ET.SubElement(oai, "ListIdentifiers")
    headers_data = []  # For caching

    for resource in resources:
        header = _build_record_header(resource)
        list_identifiers.append(header)

        # Cache header data
        header_xml = ET.tostring(header, encoding='utf-8').decode('utf-8')
        headers_data.append(header_xml)

    # Add resumption token if needed
    resumption_token = None
    if has_more:
        next_offset = offset + page_size
        resumption_token = resumption_service.create_token(
            offset=next_offset,
            verb="ListIdentifiers",
            metadata_prefix=metadata_prefix,
            set_spec=set_spec,
            from_date=from_date,
            until_date=until_date
        )
        resumption_elem = ET.SubElement(list_identifiers, "resumptionToken")
        resumption_elem.text = resumption_token

    # Cache the complete page for future requests
    list_page_data = {
        'headers': headers_data,
        'resumption_token': resumption_token,
        'count': len(headers_data),
        'cached_at': timezone.now().isoformat()
    }

    oai_cache.cache_page(
        verb='ListIdentifiers',
        metadata_prefix=metadata_prefix,
        page_data=list_page_data,
        set_spec=set_spec or '',
        from_date=from_date or '',
        until_date=until_date or '',
        offset=offset
    )

    return oai


def _parse_identifier(identifier: str) -> str:
    """Parse OAI identifier to extract resource URI."""
    if identifier == "oai:arkumu:resource:":
        # Special case: empty resource part
        return ""
    elif identifier.startswith("oai:arkumu:resource:"):
        # New format: oai:arkumu:resource:{url_encoded_uri}
        resource_part = identifier[len("oai:arkumu:resource:"):]
        return unquote(resource_part)
    elif identifier.startswith("oai:"):
        # Legacy format: oai:*:* where last ':' part is the URI (URL-escaped)
        parts = identifier.split(":")
        if len(parts) >= 3:
            last_part = parts[-1]
            if last_part:  # Non-empty last part
                return unquote(last_part)
            else:  # Empty last part, return as-is (e.g., "oai:arkumu:")
                return identifier
        # For incomplete identifiers like "oai:", return as-is
        return identifier
    return identifier


def _get_resources_queryset(
    set_spec: Optional[str] = None,
    from_date: Optional[str] = None,
    until_date: Optional[str] = None,
    metadata_prefix: Optional[str] = None,
):
    """Build a filtered queryset for harvestable resources."""
    # For both Dublin Core and METS: expose only project entities as primary records
    # Each project will have rich metadata assembled from its complete graph
    access_clause = Q(public_access_level=PublicAccessLevel.RESTRICTED) | (
        Q(public_access_level=PublicAccessLevel.PUBLIC) & Q(is_public_approved=True)
    )

    queryset = (
        Resource.objects.filter(
            Q(uri__regex=r'/entities/projekt/[0-9]+$') & access_clause
        )
        .select_related('organization')
        .order_by('updated_at', 'id')
    )

    if not queryset.exists():
        queryset = (
            Resource.objects.filter(access_clause)
            .select_related('organization')
            .order_by('updated_at', 'id')
        )

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
                from_dt = datetime.strptime(from_date, '%Y-%m-%d').replace(tzinfo=dt_timezone.utc)
            queryset = queryset.filter(updated_at__gte=from_dt)
        except ValueError:
            pass  # Invalid date format, ignore

    if until_date:
        try:
            # Support both YYYY-MM-DD and YYYY-MM-DDThh:mm:ssZ formats
            if 'T' in until_date:
                until_dt = datetime.fromisoformat(until_date.replace('Z', '+00:00'))
            else:
                until_dt = datetime.strptime(until_date, '%Y-%m-%d').replace(tzinfo=dt_timezone.utc)
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
    if date_str is None or date_str == "":
        return None

    # Handle whitespace-only strings
    if date_str.strip() != date_str or not date_str.strip():
        return "Invalid date format. Use YYYY-MM-DD or YYYY-MM-DDThh:mm:ssZ"

    try:
        if 'T' in date_str:
            # Strict validation for datetime format: YYYY-MM-DDThh:mm:ssZ
            if not date_str.endswith('Z'):
                return "Invalid date format. Use YYYY-MM-DD or YYYY-MM-DDThh:mm:ssZ"
            # Parse without Z and check strict format
            dt_part = date_str[:-1]  # Remove Z
            import re
            if not re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$', dt_part):
                raise ValueError("Invalid format")
            datetime.strptime(dt_part, '%Y-%m-%dT%H:%M:%S')
        else:
            # Strict validation for date format: YYYY-MM-DD
            # Check that format is exactly YYYY-MM-DD with zero padding
            import re
            if not re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
                raise ValueError("Invalid format")
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


def _get_snapshot_record(resource: Resource) -> Optional[ProjectRecord]:
    """Lookup project record for the resource via cached snapshot."""

    project_uri = getattr(resource, 'uri', None)
    if not project_uri:
        return None

    record = snapshot_service.get_record_by_uri(project_uri)
    if record:
        return record

    try:
        snapshot_service.refresh_cross_institutional_snapshot()
    except Exception:
        logger.exception("Failed to refresh project snapshot while building OAI metadata for %s", project_uri)
        return None

    return snapshot_service.get_record_by_uri(project_uri)


def _add_dc_value(
    payload: Dict[str, List[str]],
    term: str,
    value: Optional[str],
    namespace: str = 'dc',
) -> None:
    if value is None:
        return
    normalized = str(value).strip()
    if not normalized:
        return
    key = f"{namespace}:{term}"
    entries = payload.setdefault(key, [])
    if normalized not in entries:
        entries.append(normalized)


def _normalize_reference(value: Optional[str]) -> Optional[str]:
    """Normalize filesystem-like references for Rosetta consumption."""
    if not value:
        return value
    trimmed = value.strip()
    if not trimmed:
        return None
    if trimmed.startswith(('http://', 'https://')):
        return trimmed
    # Replace Windows separators and collapse duplicate slashes
    normalized = trimmed.replace('\\', '/').strip()
    while '//' in normalized:
        normalized = normalized.replace('//', '/')
    if normalized.startswith('./'):
        normalized = normalized[2:]
    normalized = normalized.lstrip('/')
    return normalized or None


def _guess_mime_type(obj: ProjectDigitalObject) -> Optional[str]:
    """Derive a MIME type from explicit metadata or file extension."""
    if obj.content_type:
        return obj.content_type
    candidates = [obj.file_name, obj.access_url, obj.path, obj.storage_key]
    for candidate in candidates:
        if not candidate:
            continue
        guess, _ = mimetypes.guess_type(candidate)
        if guess:
            return guess
    return None


def _default_language_for_resource(resource: Resource, record: ProjectRecord) -> Optional[str]:
    """Return a best-effort ISO-639-3 language code for the record."""
    org_code = resource.organization.code.lower() if resource.organization and resource.organization.code else None
    organization_defaults = {
        'fuk': 'deu',
        'khm': 'deu',
        'rsh': 'deu',
        'hmt': 'deu',
        'det': 'deu',
    }
    return organization_defaults.get(org_code)


def _rights_label_for_resource(resource: Resource) -> Optional[str]:
    """Translate public access configuration to a human readable rights statement."""
    mapping = {
        PublicAccessLevel.PUBLIC: "Open Access",
        PublicAccessLevel.RESTRICTED: "Restricted Access",
        PublicAccessLevel.PRIVATE: "Internal Access Only",
    }
    level = getattr(resource, 'public_access_level', None)
    if not level:
        return None
    return mapping.get(level)


def _collect_collection_labels(resource: Resource, record: ProjectRecord) -> List[str]:
    """Return descriptive collection strings suitable for dc:collection."""
    labels: List[str] = []
    if record.institution and record.institution.label:
        labels.append(record.institution.label)
    if record.institution_codes:
        labels.extend(code.upper() for code in record.institution_codes if code)
    org = getattr(resource, 'organization', None)
    if org:
        if org.name and org.name not in labels:
            labels.append(org.name)
        display_name = org.get_organization_type_display_name()
        if display_name and display_name not in labels:
            labels.append(display_name)
    return labels


def _build_dc_payload_from_record(record: ProjectRecord, resource: Resource) -> Dict[str, List[str]]:
    payload: Dict[str, List[str]] = {}

    _add_dc_value(payload, 'title', record.title)
    for alt in record.alternative_titles:
        _add_dc_value(payload, 'title', getattr(alt, 'value', None))

    _add_dc_value(payload, 'description', record.description)

    if record.institution and record.institution.label:
        _add_dc_value(payload, 'publisher', record.institution.label)
        _add_dc_value(payload, 'contributor', record.institution.label)

    for actor in record.actors:
        name = getattr(actor, 'name', None)
        if name:
            _add_dc_value(payload, 'creator', name)
        if getattr(actor, 'roles', None):
            for role in actor.roles:
                _add_dc_value(payload, 'contributor', f"{name} ({role})" if name else role)

    if record.project_type and record.project_type.label:
        _add_dc_value(payload, 'type', record.project_type.label)

    for category in record.categories:
        _add_dc_value(payload, 'subject', getattr(category, 'label', None))

    for catchphrase in record.catchphrases:
        _add_dc_value(payload, 'subject', getattr(catchphrase, 'label', None))

    for event in record.events:
        if event.start:
            _add_dc_value(payload, 'date', event.start)
        if event.end and event.end != event.start:
            _add_dc_value(payload, 'date', event.end)
        if event.location:
            _add_dc_value(payload, 'coverage', event.location)
        if event.country:
            _add_dc_value(payload, 'coverage', event.country)

    if record.year_range:
        _add_dc_value(payload, 'date', record.year_range)

    if resource.canonical_uri:
        _add_dc_value(payload, 'identifier', resource.canonical_uri)
    _add_dc_value(payload, 'identifier', resource.uri)
    _add_dc_value(payload, 'identifier', record.uri)

    if getattr(resource, 'updated_at', None):
        _add_dc_value(payload, 'dateSubmitted', _format_datestamp(resource.updated_at), namespace='dcterms')

    for code in record.institution_codes:
        _add_dc_value(payload, 'isPartOf', code.upper())

    formats_before = set(payload.get('dc:format', []))

    for obj in record.digital_objects:
        display = obj.access_url or obj.storage_key or obj.path
        normalized_display = _normalize_reference(display) or display
        if normalized_display:
            _add_dc_value(payload, 'relation', normalized_display)
        if obj.file_name:
            _add_dc_value(payload, 'identifier', obj.file_name)
        if obj.storage_key:
            _add_dc_value(payload, 'identifier', obj.storage_key)
        if obj.content_type:
            _add_dc_value(payload, 'format', obj.content_type)

    if not payload.get('dc:format'):
        for obj in record.digital_objects:
            guess = _guess_mime_type(obj)
            if guess:
                _add_dc_value(payload, 'format', guess)

    if not payload.get('dc:language'):
        language = _default_language_for_resource(resource, record)
        if language:
            _add_dc_value(payload, 'language', language)

    if not payload.get('dc:rights'):
        rights = _rights_label_for_resource(resource)
        if rights:
            _add_dc_value(payload, 'rights', rights)

    if not payload.get('dc:collection'):
        for label in _collect_collection_labels(resource, record):
            _add_dc_value(payload, 'collection', label)

    return payload


def _append_dc_metadata(metadata: ET.Element, dc_payload: Dict[str, List[str]]) -> None:
    dc_root = ET.SubElement(
        metadata,
        "{http://www.openarchives.org/OAI/2.0/oai_dc/}dc",
        {
            "xmlns:oai_dc": OAI_DC_NS,
            "xmlns:dc": DC_NS,
            "xmlns:dcterms": DCTERMS_NS,
            "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
            "xsi:schemaLocation": " ".join([
                OAI_DC_NS,
                "http://www.openarchives.org/OAI/2.0/oai_dc.xsd",
            ]),
        },
    )

    for key, values in dc_payload.items():
        namespace, term = key.split(":", 1)
        ns_uri = DC_NS if namespace == 'dc' else DCTERMS_NS
        for value in values:
            ET.SubElement(dc_root, f"{{{ns_uri}}}{term}").text = value


def _build_mets_from_record(
    record: ProjectRecord,
    resource: Resource,
    dc_payload: Dict[str, List[str]],
) -> ET.Element:
    ET.register_namespace('mets', ROSETTA_METS_NS)
    ET.register_namespace('dc', DC_NS)
    ET.register_namespace('dcterms', DCTERMS_NS)
    ET.register_namespace('xlink', ROSETTA_XLINK_NS)
    ET.register_namespace('xsi', XSI_NS)

    mets_root = ET.Element(f"{{{ROSETTA_METS_NS}}}mets")
    mets_root.set('xmlns', ROSETTA_DNX_NS)

    timestamp = timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    mets_hdr = ET.SubElement(
        mets_root,
        f"{{{ROSETTA_METS_NS}}}metsHdr",
        {
            "CREATEDATE": timestamp,
            "LASTMODDATE": timestamp,
        },
    )
    agent = ET.SubElement(
        mets_hdr,
        f"{{{ROSETTA_METS_NS}}}agent",
        {
            "ROLE": "CREATOR",
            "TYPE": "OTHER",
            "OTHERTYPE": "SOFTWARE",
        },
    )
    ET.SubElement(agent, f"{{{ROSETTA_METS_NS}}}name").text = "Arkumu OAI-PMH Provider"

    dmd_sec = ET.SubElement(mets_root, f"{{{ROSETTA_METS_NS}}}dmdSec", {"ID": "ie-dmd"})
    md_wrap = ET.SubElement(dmd_sec, f"{{{ROSETTA_METS_NS}}}mdWrap", {"MDTYPE": "DC"})
    xml_data = ET.SubElement(md_wrap, f"{{{ROSETTA_METS_NS}}}xmlData")
    dc_record = ET.SubElement(xml_data, f"{{{DC_NS}}}record")
    for key, values in dc_payload.items():
        namespace, term = key.split(":", 1)
        ns_uri = DC_NS if namespace == 'dc' else DCTERMS_NS
        for value in values:
            ET.SubElement(dc_record, f"{{{ns_uri}}}{term}").text = value

    ie_amd = ET.SubElement(mets_root, f"{{{ROSETTA_METS_NS}}}amdSec", {"ID": "ie-amd"})
    tech_md = ET.SubElement(ie_amd, f"{{{ROSETTA_METS_NS}}}techMD", {"ID": "ie-amd-tech"})
    tech_wrap = ET.SubElement(
        tech_md,
        f"{{{ROSETTA_METS_NS}}}mdWrap",
        {"MDTYPE": "OTHER", "OTHERMDTYPE": "dnx"},
    )
    tech_xml = ET.SubElement(tech_wrap, f"{{{ROSETTA_METS_NS}}}xmlData")
    ET.SubElement(tech_xml, "dnx")

    rights_md = ET.SubElement(ie_amd, f"{{{ROSETTA_METS_NS}}}rightsMD", {"ID": "ie-amd-rights"})
    rights_wrap = ET.SubElement(
        rights_md,
        f"{{{ROSETTA_METS_NS}}}mdWrap",
        {"MDTYPE": "OTHER", "OTHERMDTYPE": "dnx"},
    )
    rights_xml = ET.SubElement(rights_wrap, f"{{{ROSETTA_METS_NS}}}xmlData")
    rights_dnx = ET.SubElement(rights_xml, "dnx")
    ET.SubElement(rights_dnx, "section", {"id": "accessRightsPolicy"})

    source_md = ET.SubElement(ie_amd, f"{{{ROSETTA_METS_NS}}}sourceMD", {"ID": "ie-amd-source-OTHER"})
    source_wrap = ET.SubElement(
        source_md,
        f"{{{ROSETTA_METS_NS}}}mdWrap",
        {"MDTYPE": "OTHER", "OTHERMDTYPE": "Text"},
    )
    source_xml = ET.SubElement(source_wrap, f"{{{ROSETTA_METS_NS}}}xmlData")
    epicur = ET.SubElement(
        source_xml,
        "epicur",
        {
            f"{{{XSI_NS}}}schemaLocation": "urn:nbn:de:1111-2004033116 http://www.persistent-identifier.de/xepicur/version1.0/xepicur.xsd",
        },
    )
    administrative = ET.SubElement(epicur, "administrative_data")
    delivery = ET.SubElement(administrative, "delivery")
    ET.SubElement(delivery, "update_status", {"type": "urn_new"})
    epicur_record = ET.SubElement(epicur, "record")

    digiprov_md = ET.SubElement(ie_amd, f"{{{ROSETTA_METS_NS}}}digiprovMD", {"ID": "ie-amd-digiprov"})
    digiprov_wrap = ET.SubElement(
        digiprov_md,
        f"{{{ROSETTA_METS_NS}}}mdWrap",
        {"MDTYPE": "OTHER", "OTHERMDTYPE": "dnx"},
    )
    digiprov_xml = ET.SubElement(digiprov_wrap, f"{{{ROSETTA_METS_NS}}}xmlData")
    ET.SubElement(digiprov_xml, "dnx")

    file_sec = ET.SubElement(mets_root, f"{{{ROSETTA_METS_NS}}}fileSec")

    def _append_epicur_resource(obj: ProjectDigitalObject, *, role: str = "secondary", type_attr: Optional[str] = None, target: Optional[str] = None) -> None:
        href = obj.access_url or obj.path or obj.storage_key
        if not href:
            return
        if not href.startswith(('http://', 'https://')):
            normalized = _normalize_reference(href)
            if normalized:
                href = normalized
        resource_elem = ET.SubElement(epicur_record, "resource")
        identifier_attrs = {"scheme": "url", "origin": "original"}
        if type_attr:
            identifier_attrs["type"] = type_attr
        if role != "secondary":
            identifier_attrs["role"] = role
        if target:
            identifier_attrs["target"] = target
        ET.SubElement(resource_elem, "identifier", identifier_attrs).text = href
        if obj.content_type:
            ET.SubElement(resource_elem, "format", {"scheme": "imt"}).text = obj.content_type

    digital_objects = record.digital_objects or []
    for index, obj in enumerate(digital_objects, start=1):
        rep_id = f"rep{index}"
        file_id = f"fid{index}-1"

        rep_amd = ET.SubElement(mets_root, f"{{{ROSETTA_METS_NS}}}amdSec", {"ID": f"{rep_id}-amd"})
        rep_tech = ET.SubElement(rep_amd, f"{{{ROSETTA_METS_NS}}}techMD", {"ID": f"{rep_id}-amd-tech"})
        rep_wrap = ET.SubElement(
            rep_tech,
            f"{{{ROSETTA_METS_NS}}}mdWrap",
            {"MDTYPE": "OTHER", "OTHERMDTYPE": "dnx"},
        )
        rep_xml = ET.SubElement(rep_wrap, f"{{{ROSETTA_METS_NS}}}xmlData")
        rep_dnx = ET.SubElement(rep_xml, "dnx")
        section = ET.SubElement(rep_dnx, "section", {"id": "generalRepCharacteristics"})
        rec = ET.SubElement(section, "record")
        preservation_type = "PRESERVATION_MASTER" if index == 1 else "MODIFIED_MASTER"
        ET.SubElement(rec, "key", {"id": "preservationType"}).text = preservation_type
        ET.SubElement(rec, "key", {"id": "usageType"}).text = "VIEW"

        if index == 1:
            _append_epicur_resource(obj, role="primary", type_attr="frontpage")
        _append_epicur_resource(obj, target="transfer")

        file_grp = ET.SubElement(
            file_sec,
            f"{{{ROSETTA_METS_NS}}}fileGrp",
            {
                "USE": "VIEW",
                "ID": rep_id,
                "ADMID": f"{rep_id}-amd",
            },
        )

        file_attrs: Dict[str, Any] = {
            "ID": file_id,
            "ADMID": f"{file_id}-amd",
        }
        if obj.content_type:
            file_attrs["MIMETYPE"] = obj.content_type
        if obj.size_bytes:
            file_attrs["SIZE"] = str(obj.size_bytes)

        file_elem = ET.SubElement(file_grp, f"{{{ROSETTA_METS_NS}}}file", file_attrs)
        href = obj.access_url or obj.storage_key or obj.path
        if href:
            is_url = href.startswith(('http://', 'https://'))
            if not is_url:
                normalized = _normalize_reference(href)
                if normalized:
                    href = normalized
            loctype = "URL" if is_url else "URL"
            flocat_attrs = {
                "LOCTYPE": loctype,
                f"{{{ROSETTA_XLINK_NS}}}href": href,
                f"{{{ROSETTA_XLINK_NS}}}type": "simple",
            }
            ET.SubElement(file_elem, f"{{{ROSETTA_METS_NS}}}FLocat", flocat_attrs)

        file_amd = ET.SubElement(mets_root, f"{{{ROSETTA_METS_NS}}}amdSec", {"ID": f"{file_id}-amd"})
        file_tech = ET.SubElement(file_amd, f"{{{ROSETTA_METS_NS}}}techMD", {"ID": f"{file_id}-amd-tech"})
        file_wrap = ET.SubElement(
            file_tech,
            f"{{{ROSETTA_METS_NS}}}mdWrap",
            {"MDTYPE": "OTHER", "OTHERMDTYPE": "dnx"},
        )
        file_xml = ET.SubElement(file_wrap, f"{{{ROSETTA_METS_NS}}}xmlData")
        ET.SubElement(file_xml, "dnx")

        label_source = obj.file_name or obj.storage_key or obj.path or f"Digital Object {index}"
        label_normalized = _normalize_reference(label_source)
        label = label_normalized or label_source

        struct_map = ET.SubElement(
            mets_root,
            f"{{{ROSETTA_METS_NS}}}structMap",
            {"ID": f"{rep_id}-1", "TYPE": "LOGICAL"},
        )
        struct_root = ET.SubElement(struct_map, f"{{{ROSETTA_METS_NS}}}div")
        div = ET.SubElement(
            struct_root,
            f"{{{ROSETTA_METS_NS}}}div",
            {
                "ORDERLABEL": label,
                "TYPE": "FILE",
                "LABEL": label,
            },
        )
        ET.SubElement(div, f"{{{ROSETTA_METS_NS}}}fptr", {"FILEID": file_id})

    return mets_root


def _build_rdf_from_resource(resource: Resource) -> ET.Element:
    """Generate RDF/XML metadata element for a resource graph."""

    org_code = resource.organization.code if resource.organization else None
    graph_service = CanonicalGraphService(org_code=org_code)
    graph_data = graph_service.get_entity_graph(
        resource_uri=resource.uri,
        expand_neighbors=True,
        depth=2,
        restrict_to_org=bool(org_code),
    )

    rdf_graph = rdflib.Graph()
    nodes = graph_data.get("nodes", {})

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
        "http://arkumu.org/data/properties/": "ark",
    }
    used_prefixes = set(prefix_map.values())

    for ns_uri, prefix in prefix_map.items():
        rdf_graph.bind(prefix, namespace_cache[ns_uri], override=True)

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

    def _resolve_prefix(ns_uri: str) -> str:
        if ns_uri in prefix_map:
            return prefix_map[ns_uri]

        if ns_uri.startswith("http://arkumu.org/data/") and ns_uri.endswith("/properties/"):
            suffix = ns_uri[len("http://arkumu.org/data/"):-len("/properties/")].strip("/")
            if not suffix:
                candidate = "ark_prop"
            else:
                parts = [part for part in suffix.split("/") if part]
                candidate = f"{parts[-1]}_prop" if len(parts) >= 1 else "ark_prop"
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

    def _node_type(node: Dict[str, Any]) -> str:
        node_type = node.get("resource_type")
        if isinstance(node_type, ResourceType):
            return node_type.value
        return str(node_type).upper() if node_type else ""

    def _is_literal(node: Dict[str, Any]) -> bool:
        return _node_type(node) == ResourceType.LITERAL.value

    def _is_data_node(node: Dict[str, Any]) -> bool:
        return _node_type(node) in {ResourceType.IRI.value, ResourceType.ENTITY.value}

    for edge in graph_data.get("edges", []):
        subj_node = _node_info(edge.get("subject_id"))
        obj_node = _node_info(edge.get("object_id"))
        predicate_source = edge.get("predicate_canonical") or edge.get("predicate_uri")
        normalized_predicate = _normalize_predicate_uri(predicate_source)

        if not subj_node or not obj_node or not normalized_predicate:
            continue

        if predicate_source and "defines" in predicate_source.lower():
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
    ET.register_namespace("ark", "http://arkumu.org/data/properties/")

    rdf_xml = rdf_graph.serialize(format="application/rdf+xml")
    rdf_element = ET.fromstring(rdf_xml.encode("utf-8"))
    return rdf_element


def _build_metadata_element(resource: Resource, metadata_prefix: str) -> ET.Element:
    """Build metadata element for different formats."""
    metadata = ET.Element("metadata")

    record = _get_snapshot_record(resource)
    if not record:
        logger.warning("No snapshot record found for %s", getattr(resource, 'uri', 'unknown'))
        return metadata

    if metadata_prefix == "oai_dc":
        dc_payload = _build_dc_payload_from_record(record, resource)
        _append_dc_metadata(metadata, dc_payload)
    elif metadata_prefix == "mets":
        dc_payload = _build_dc_payload_from_record(record, resource)
        mets_root = _build_mets_from_record(record, resource, dc_payload)
        metadata.append(mets_root)
    elif metadata_prefix == "rdf":
        rdf_element = _build_rdf_from_resource(resource)
        metadata.append(rdf_element)

    return metadata


def _mint_arkumu_pid(resource: Resource) -> Optional[str]:
    """Mint an Arkumu local persistent identifier for a resource.

    Format: "arkumu-{org}-{local_id}"
    where local_id is derived from the typical entity URI pattern:
    .../entities/{project_id}/{item_id}

    Returns None when required parts are missing.
    """
    try:
        org_code = (resource.organization.code if resource.organization else None)
        uri = getattr(resource, "uri", None)
        if not org_code or not uri:
            return None

        # Parse URI path and attempt to extract project and item id
        path = urlparse(uri).path or ""
        parts = [p for p in path.strip("/").split("/") if p]

        # Look for the common pattern: .../entities/{project_id}/{item_id}
        project_id = None
        item_id = None
        try:
            ent_idx = parts.index("entities")
            # Expect at least two parts after 'entities'
            if len(parts) > ent_idx + 2:
                project_id = parts[ent_idx + 1]
                item_id = parts[ent_idx + 2]
            elif len(parts) > ent_idx + 1:
                # Fallback: if only one part, use it as project and try last as item
                project_id = parts[ent_idx + 1]
                item_id = parts[-1] if len(parts) - 1 > ent_idx + 1 else None
        except ValueError:
            # 'entities' not present; fallback to last two segments if available
            if len(parts) >= 2:
                project_id = parts[-2]
                item_id = parts[-1]

        if not project_id or not item_id:
            return None

        # Normalize components
        project_slug = slugify_uri_part(project_id)
        item_slug = slugify_uri_part(item_id)
        org_slug = slugify_uri_part(org_code)

        if not project_slug or not item_slug or not org_slug:
            return None

        local_id = f"{project_slug}-{item_slug}"
        return f"arkumu-{org_slug}-{local_id}"
    except Exception:
        return None


def _list_records(oai: ET.Element, request: HttpRequest) -> ET.Element:
    """Implement ListRecords verb with complete metadata and pagination."""
    metadata_prefix = request.GET.get("metadataPrefix")
    set_spec = request.GET.get("set")
    from_date = request.GET.get("from")
    until_date = request.GET.get("until")
    resumption_token = request.GET.get("resumptionToken")
    has_resumption_param = "resumptionToken" in request.GET

    # Validate metadata format
    if not has_resumption_param and (not metadata_prefix or metadata_prefix not in SUPPORTED_METADATA_FORMATS):
        return _error(oai, "cannotDisseminateFormat", "Only oai_dc, mets, and rdf are supported")

    # Validate date parameters
    if not has_resumption_param:
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
                from_dt = datetime.fromisoformat(from_date.replace('Z', '+00:00')) if 'T' in from_date else datetime.strptime(from_date, '%Y-%m-%d').replace(tzinfo=dt_timezone.utc)
                until_dt = datetime.fromisoformat(until_date.replace('Z', '+00:00')) if 'T' in until_date else datetime.strptime(until_date, '%Y-%m-%d').replace(tzinfo=dt_timezone.utc)
                if from_dt > until_dt:
                    return _error(oai, "badArgument", "'from' date must be earlier than 'until' date")
            except ValueError:
                pass  # Already validated above

    # Handle resumption token
    offset = 0
    if has_resumption_param:
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
    queryset = _get_resources_queryset(set_spec, from_date, until_date, metadata_prefix)

    # Get page of resources
    page_size = resumption_service.page_size
    resources = list(queryset[offset:offset + page_size + 1])  # Get one extra to check if more exist

    has_more = len(resources) > page_size
    if has_more:
        resources = resources[:-1]  # Remove the extra record

    # Check if no records match
    if offset == 0 and not resources:
        return _error(oai, "noRecordsMatch", "No records found matching the criteria")

    cached_page = oai_cache.get_cached_page(
        verb='ListRecords',
        metadata_prefix=metadata_prefix,
        set_spec=set_spec or '',
        from_date=from_date or '',
        until_date=until_date or '',
        offset=offset
    )
    if cached_page:
        # Rebuild from cached data
        list_records = ET.SubElement(oai, "ListRecords")

        for record_data in cached_page['records']:
            record = ET.SubElement(list_records, "record")
            # Parse cached XML strings back to elements
            header = ET.fromstring(record_data['header'])
            metadata = ET.fromstring(record_data['metadata'])
            record.append(header)
            record.append(metadata)

        # Add cached resumption token if present
        if cached_page.get('resumption_token'):
            resumption_elem = ET.SubElement(list_records, "resumptionToken")
            resumption_elem.text = cached_page['resumption_token']

        return oai

    # Build response (cache miss)
    list_records = ET.SubElement(oai, "ListRecords")
    records_data = []  # For caching

    for resource in resources:
        record = ET.SubElement(list_records, "record")

        # Try to get cached record first
        cached_record = _get_cached_record(resource, metadata_prefix)

        if cached_record:
            # Use cached record
            header = ET.fromstring(cached_record['header'])
            metadata = ET.fromstring(cached_record['metadata'])
            record.append(header)
            record.append(metadata)
            records_data.append(cached_record)
        else:
            # Build record and cache it
            header = _build_record_header(resource)
            metadata = _build_metadata_element(resource, metadata_prefix)
            record.append(header)
            record.append(metadata)

            # Cache individual record
            header_xml = ET.tostring(header, encoding='utf-8').decode('utf-8')
            metadata_xml = ET.tostring(metadata, encoding='utf-8').decode('utf-8')
            _cache_record(resource, metadata_prefix, header_xml, metadata_xml)

            records_data.append({
                'header': header_xml,
                'metadata': metadata_xml,
                'timestamp': int(resource.updated_at.timestamp())
            })

    # Add resumption token if needed
    resumption_token = None
    if has_more:
        next_offset = offset + page_size
        resumption_token = resumption_service.create_token(
            offset=next_offset,
            verb="ListRecords",
            metadata_prefix=metadata_prefix,
            set_spec=set_spec,
            from_date=from_date,
            until_date=until_date
        )
        resumption_elem = ET.SubElement(list_records, "resumptionToken")
        resumption_elem.text = resumption_token

    # Cache the complete page for future requests
    page_data = {
        'records': records_data,
        'resumption_token': resumption_token,
        'count': len(records_data),
        'cached_at': timezone.now().isoformat()
    }

    oai_cache.cache_page(
        verb='ListRecords',
        metadata_prefix=metadata_prefix,
        page_data=page_data,
        set_spec=set_spec or '',
        from_date=from_date or '',
        until_date=until_date or '',
        offset=offset
    )

    return oai


@require_GET
@oai_authentication_required
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
            return _xml_response(_identify(oai, request))

        if verb == "ListMetadataFormats":
            identifier = request.GET.get("identifier")
            return _xml_response(_list_metadata_formats(oai, identifier))

        if verb == "ListSets":
            return _xml_response(_list_sets(oai))

        if verb == "ListIdentifiers":
            # Exclusive argument checking
            has_resumption_param = "resumptionToken" in request.GET
            if has_resumption_param and len([k for k in request.GET.keys() if k != "verb" and k != "resumptionToken"]) > 0:
                return _xml_response(_error(oai, "badArgument", "resumptionToken cannot be combined with other arguments"))

            # Required argument checking
            if not has_resumption_param and not request.GET.get("metadataPrefix"):
                return _xml_response(_error(oai, "badArgument", "metadataPrefix is required"))

            return _xml_response(_list_identifiers(oai, request))

        if verb == "ListRecords":
            # Exclusive argument checking
            has_resumption_param = "resumptionToken" in request.GET
            if has_resumption_param and len([k for k in request.GET.keys() if k != "verb" and k != "resumptionToken"]) > 0:
                return _xml_response(_error(oai, "badArgument", "resumptionToken cannot be combined with other arguments"))

            # Required argument checking
            if not has_resumption_param and not request.GET.get("metadataPrefix"):
                return _xml_response(_error(oai, "badArgument", "metadataPrefix is required"))

            return _xml_response(_list_records(oai, request))

        if verb == "GetRecord":
            identifier = request.GET.get("identifier")
            metadata_prefix = request.GET.get("metadataPrefix")
            if not identifier or not metadata_prefix:
                return _xml_response(_error(oai, "badArgument", "identifier and metadataPrefix are required"))
            if metadata_prefix not in SUPPORTED_METADATA_FORMATS:
                return _xml_response(_error(oai, "cannotDisseminateFormat", "Only oai_dc, mets, and rdf are supported"))

            # Resolve Arkumu resource by identifier
            resource_uri = _parse_identifier(identifier)

            # Filter to only project entities
            resource = Resource.objects.filter(
                uri=resource_uri,
                uri__regex=r'/entities/projekt/[0-9]+$'
            ).select_related("organization").first()

            if not resource:
                return _xml_response(_error(oai, "idDoesNotExist", "Identifier not found"))

            if not resource.organization:
                return _xml_response(_error(oai, "idDoesNotExist", "Resource has no organization"))

            # Check cache first
            cached_record = _get_cached_record(resource, metadata_prefix)
            if cached_record:
                # Build OAI response from cache
                get_record = ET.SubElement(oai, "GetRecord")
                record = ET.SubElement(get_record, "record")

                # Parse cached XML strings back to elements
                header_elem = ET.fromstring(cached_record['header'])
                metadata_elem = ET.fromstring(cached_record['metadata'])

                record.append(header_elem)
                record.append(metadata_elem)
                return _xml_response(oai)

            # Build OAI response (not cached)
            get_record = ET.SubElement(oai, "GetRecord")
            record = ET.SubElement(get_record, "record")

            # Add header
            header = _build_record_header(resource)
            record.append(header)

            # Add metadata
            metadata = _build_metadata_element(resource, metadata_prefix)
            record.append(metadata)

            # Cache the record for future requests
            _cache_record(
                resource,
                metadata_prefix,
                ET.tostring(header, encoding="unicode"),
                ET.tostring(metadata, encoding="unicode")
            )

            return _xml_response(oai)

        # This should never be reached due to earlier validation
        return _xml_response(_error(oai, "badVerb", "Unsupported verb"))

    except Exception as e:
        # Global exception handler for any unexpected errors
        oai = _oai_envelope(request)
        return _xml_response(_error(oai, "internalError", f"Internal server error: {str(e)}"))
