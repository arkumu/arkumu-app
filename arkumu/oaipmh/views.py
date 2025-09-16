from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urlparse

from django.http import HttpRequest, HttpResponse
from django.views.decorators.http import require_GET
from django.core.cache import cache
from django.utils import timezone
import xml.etree.ElementTree as ET

from arkumu.metadata.models.resource import Resource
from arkumu.metadata.services.canonical_graph_service import CanonicalGraphService
from arkumu.users.models import Organization
from .formats.dublin_core import DublinCoreSerializer, DEFAULT_PREDICATE_MAP, DCTERMS_NS, OAI_DC_NS, DC_NS
from .formats.mets import METSSerializer
from .resumption import ResumptionTokenService
from arkumu.common.uri_utils import slugify_uri_part


# Minimal repository config (can be moved to settings)
REPO_NAME = "Arkumu Repository"
REPO_BASEURL = "/oai/"
REPO_ADMIN_EMAIL = "admin@example.org"
REPO_PROTOCOL_VERSION = "2.0"
REPO_EARLIEST_DATASTAMP = "1970-01-01T00:00:00Z"
REPO_DELETED_RECORD = "no"
REPO_GRANULARITY = "YYYY-MM-DDThh:mm:ssZ"
REPO_REPOSITORY_IDENTIFIER = "arkumu"

# Initialize resumption token service
resumption_service = ResumptionTokenService(page_size=100)


# Cache utilities
def _get_cache_key(cache_type: str, **kwargs) -> str:
    """Generate consistent cache keys for OAI-PMH responses."""
    if cache_type == "record":
        return f"oai:record:{kwargs['uri']}:{kwargs['metadata_prefix']}:{kwargs['timestamp']}"
    elif cache_type == "graph":
        return f"oai:graph:{kwargs['uri']}:{kwargs['timestamp']}"
    elif cache_type == "page":
        return f"oai:page:{kwargs['verb']}:{kwargs['metadata_prefix']}:{kwargs.get('set_spec', '')}:{kwargs.get('from_date', '')}:{kwargs.get('until_date', '')}:{kwargs['offset']}"
    return f"oai:{cache_type}:{':'.join(str(v) for v in kwargs.values())}"


def _get_cached_record(resource: Resource, metadata_prefix: str) -> Optional[Dict[str, Any]]:
    """Get cached OAI-PMH record if available."""
    timestamp = int(resource.updated_at.timestamp())
    cache_key = _get_cache_key(
        "record",
        uri=resource.uri,
        metadata_prefix=metadata_prefix,
        timestamp=timestamp
    )
    return cache.get(cache_key)


def _cache_record(resource: Resource, metadata_prefix: str, header_xml: str, metadata_xml: str):
    """Cache OAI-PMH record data."""
    timestamp = int(resource.updated_at.timestamp())
    cache_key = _get_cache_key(
        "record",
        uri=resource.uri,
        metadata_prefix=metadata_prefix,
        timestamp=timestamp
    )

    cached_record = {
        'header': header_xml,
        'metadata': metadata_xml,
        'timestamp': timestamp
    }

    # Cache for 4 hours
    cache.set(cache_key, cached_record, 4 * 3600)


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
            "xmlns:mets": "http://www.loc.gov/METS/",
            "xmlns:xlink": "http://www.w3.org/1999/xlink",
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
    import re
    # Find all xmlns:xsi declarations and keep only the first one
    xsi_pattern = r'xmlns:xsi="[^"]*"'
    matches = list(re.finditer(xsi_pattern, xml_str))
    if len(matches) > 1:
        # Remove all but the first occurrence
        for match in reversed(matches[1:]):  # Reverse to avoid index issues
            xml_str = xml_str[:match.start()] + xml_str[match.end():]

    # Do the same for other commonly duplicated namespaces
    for ns_prefix in ['xmlns:dc', 'xmlns:mets', 'xmlns:xlink']:
        pattern = rf'{re.escape(ns_prefix)}="[^"]*"'
        matches = list(re.finditer(pattern, xml_str))
        if len(matches) > 1:
            for match in reversed(matches[1:]):
                xml_str = xml_str[:match.start()] + xml_str[match.end():]

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
                earliest = earliest.replace(tzinfo=timezone.utc)
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
    if not has_resumption_param and (not metadata_prefix or metadata_prefix not in ["oai_dc", "mets"]):
        return _error(oai, "cannotDisseminateFormat", "Only oai_dc and mets are supported")

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
                from_dt = datetime.fromisoformat(from_date.replace('Z', '+00:00')) if 'T' in from_date else datetime.strptime(from_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                until_dt = datetime.fromisoformat(until_date.replace('Z', '+00:00')) if 'T' in until_date else datetime.strptime(until_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
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

    # Check for cached page response first
    list_cache_key = _get_cache_key(
        "page",
        verb="ListIdentifiers",
        metadata_prefix=metadata_prefix,
        set_spec=set_spec,
        from_date=from_date,
        until_date=until_date,
        offset=offset
    )

    cached_page = cache.get(list_cache_key)
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

    # Cache for 2 hours
    cache.set(list_cache_key, list_page_data, 2 * 3600)

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


def _get_resources_queryset(set_spec: Optional[str] = None, from_date: Optional[str] = None, until_date: Optional[str] = None, metadata_prefix: Optional[str] = None):
    """Build a filtered queryset for harvestable resources."""
    # For both Dublin Core and METS: expose only project entities as primary records
    # Each project will have rich metadata assembled from its complete graph
    queryset = Resource.objects.filter(
        uri__regex=r'/entities/projekt/[0-9]+$'
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


def _build_metadata_element(resource: Resource, metadata_prefix: str) -> ET.Element:
    """Build metadata element for different formats."""
    metadata = ET.Element("metadata")

    if metadata_prefix == "oai_dc":
        # Build Dublin Core metadata
        org_code = resource.organization.code if resource.organization else None
        if not org_code:
            return metadata  # Empty metadata if no organization

        # Get rich graph with canonical URI support and deep traversal
        svc = CanonicalGraphService(org_code=org_code)
        graph = svc.get_entity_graph(
            resource.uri,
            include_incoming=True,
            expand_neighbors=True,  # Enable deep traversal
            depth=2,  # Traverse 2 hops for richer metadata
            predicate_canon_whitelist=[
                # Core Dublin Core mappings (canonical predicates)
                "http://arkumu.org/data/properties/bevorzugter-titel",
                "http://arkumu.org/data/properties/alternativer-titel",
                "http://arkumu.org/data/properties/beschreibung",
                "http://arkumu.org/data/properties/kuenstler",
                "http://arkumu.org/data/properties/sprache-des-bevorzugten-titels",
                "http://arkumu.org/data/properties/schlagwort",
                "http://arkumu.org/data/properties/projektkategorie",
                "http://arkumu.org/data/properties/projektart",
                "http://arkumu.org/data/properties/datensatz-id-beim-einlieferer",
                "http://arkumu.org/data/properties/rechtsstatus",
                "http://arkumu.org/data/properties/ereignisort",
                "http://arkumu.org/data/properties/datensatzerstellung-beim-einlieferer",
                # Actor relationships
                "http://arkumu.org/data/properties/akteurin",
                "http://arkumu.org/data/properties/urheber",
                # Related project relationships
                "http://arkumu.org/data/properties/ausgangsprojekt",
                # File relationships
                "http://arkumu.org/data/properties/dateiname",
                "http://arkumu.org/data/properties/dateipfad",
            ]
        )
        dc = _build_dc_metadata_from_entity_graph(graph, resource)

        # Include both canonical URI (if available) and original URI as identifiers
        identifiers = list(dc.get("dc:identifier", []))

        # Use canonical URI as primary identifier if available
        if resource.canonical_uri and resource.canonical_uri not in identifiers:
            identifiers.append(resource.canonical_uri)

        # Always include the original URI as an identifier
        if resource.uri and resource.uri not in identifiers:
            identifiers.append(resource.uri)

        if identifiers:
            dc["dc:identifier"] = identifiers

        # Integrate file access URLs for Rosetta (dc:relation)
        try:
            # Defer heavy imports and handle absence gracefully
            from arkumu.storage.models.s3_file_objects import S3FileObject
            from arkumu.storage.services.rosetta_export_service import RosettaExportService

            # Limit number of relations to avoid oversized records
            file_qs = S3FileObject.objects.filter(related_resource=resource).order_by("created_at")[:10]
            if file_qs:
                export_svc = RosettaExportService()
                relation_urls: List[str] = []
                for f in file_qs:
                    try:
                        access = export_svc.prepare_file_for_harvest(f)
                        url = access.get("url")
                        if url:
                            relation_urls.append(url)
                        elif f.s3_url:
                            relation_urls.append(f.s3_url)
                    except Exception:
                        # On any error generating presigned URL, fall back to stored S3 URL if present
                        if getattr(f, "s3_url", None):
                            relation_urls.append(f.s3_url)
                if relation_urls:
                    dc_rel = list(dc.get("dc:relation", []))
                    # De-duplicate while preserving order
                    seen = set(dc_rel)
                    for u in relation_urls:
                        if u not in seen:
                            dc_rel.append(u)
                            seen.add(u)
                    dc["dc:relation"] = dc_rel
        except Exception:
            # If storage integration is not available, skip silently
            pass

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
        # Build METS metadata with complete project graph as RDF/XML
        org_code = resource.organization.code if resource.organization else None
        if not org_code:
            return metadata  # Empty metadata if no organization

        # Get complete graph for the project with canonical URI support
        svc = CanonicalGraphService(org_code=org_code)
        graph = svc.get_entity_graph(
            resource.uri,
            include_incoming=True,
            expand_neighbors=True,
            depth=3,  # Deeper traversal for complete METS representation
            restrict_to_org=True  # Keep it organization-scoped for security
        )

        # Build METS container
        mets_root = ET.SubElement(
            metadata,
            "{http://www.loc.gov/METS/}mets",
            {
                "xmlns:mets": "http://www.loc.gov/METS/",
                "xmlns:rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
                "xmlns:arkumu": "http://arkumu.org/data/",
                "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
            },
        )

        # Add METS header
        mets_header = ET.SubElement(mets_root, "{http://www.loc.gov/METS/}metsHdr")
        mets_header.set("CREATEDATE", timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ"))

        # Add descriptive metadata section with RDF/XML
        dmd_sec = ET.SubElement(mets_root, "{http://www.loc.gov/METS/}dmdSec")
        dmd_sec.set("ID", "DMD1")

        md_wrap = ET.SubElement(dmd_sec, "{http://www.loc.gov/METS/}mdWrap")
        md_wrap.set("MDTYPE", "OTHER")
        md_wrap.set("OTHERMDTYPE", "RDF")

        xml_data = ET.SubElement(md_wrap, "{http://www.loc.gov/METS/}xmlData")

        # Build RDF/XML representation of the complete graph
        rdf_root = ET.SubElement(xml_data, "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF")

        # Get edges and group by subject
        edges = graph.get("edges", [])
        root_id = graph.get("root_id")

        # Group edges by subject_id to create RDF descriptions
        subjects = {}
        for edge in edges:
            subject_id = edge.get("subject_id")
            if subject_id not in subjects:
                subjects[subject_id] = []
            subjects[subject_id].append(edge)

        # Create RDF Description for each subject
        for subject_id, subject_edges in subjects.items():
            # Use resource URI if available, otherwise use subject_id
            # For the root, use the project URI
            if subject_id == root_id:
                subject_uri = resource.uri
            else:
                # Try to find object_uri from edges that reference this subject as object
                subject_uri = None
                for edge in edges:
                    if edge.get("object_id") == subject_id and edge.get("object_uri"):
                        subject_uri = edge.get("object_uri")
                        break
                if not subject_uri:
                    subject_uri = f"urn:uuid:{subject_id}"  # Fallback

            # Create RDF Description
            description = ET.SubElement(
                rdf_root,
                "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}Description"
            )
            description.set("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about", subject_uri)

            # Add properties as RDF triples
            for edge in subject_edges:
                predicate_uri = edge.get("predicate_canonical") or edge.get("predicate_uri")
                if predicate_uri:
                    # Create property element with proper namespace
                    local_name = predicate_uri.split("/")[-1] if "/" in predicate_uri else predicate_uri

                    # Sanitize local name for valid XML element names
                    # XML element names cannot start with numbers or contain # symbols
                    import re
                    local_name = re.sub(r'^[0-9]', '_', local_name)  # Prefix with _ if starts with number
                    local_name = re.sub(r'[#:]', '_', local_name)    # Replace # and : with _
                    local_name = re.sub(r'[^a-zA-Z0-9_-]', '_', local_name)  # Replace invalid chars with _

                    # Use canonical namespace if available
                    if edge.get("predicate_canonical"):
                        namespace_base = "/".join(edge.get("predicate_canonical").split("/")[:-1]) + "/"
                    else:
                        namespace_base = "http://arkumu.org/data/properties/"

                    prop_elem = ET.SubElement(description, f"{{{namespace_base}}}{local_name}")

                    # Handle literal values
                    if edge.get("object_value") is not None:
                        prop_elem.text = str(edge.get("object_value"))

                    # Handle object references
                    elif edge.get("object_uri"):
                        prop_elem.set("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource", edge.get("object_uri"))

            # Add rdf:type for the project
            if subject_id == root_id:
                type_elem = ET.SubElement(
                    description,
                    "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}type"
                )
                type_elem.set(
                    "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource",
                    "http://arkumu.org/data/types/projekt"
                )

        # Add fileSec and structMap sections for file integration
        try:
            from arkumu.storage.models.s3_file_objects import S3FileObject

            # Get files linked to this project resource
            project_files = S3FileObject.objects.filter(related_resource=resource).order_by("s3_key")[:50]  # Limit to 50 files

            if project_files:
                # Add fileSec section
                file_sec = ET.SubElement(mets_root, "{http://www.loc.gov/METS/}fileSec")
                file_grp = ET.SubElement(file_sec, "{http://www.loc.gov/METS/}fileGrp")
                file_grp.set("USE", "DEFAULT")

                # Add structMap section
                struct_map = ET.SubElement(mets_root, "{http://www.loc.gov/METS/}structMap")
                struct_map.set("TYPE", "LOGICAL")

                # Main project div
                main_div = ET.SubElement(struct_map, "{http://www.loc.gov/METS/}div")
                main_div.set("TYPE", "project")

                # Set project label from graph metadata if available
                project_title = None
                for edge in edges:
                    if edge.get("subject_id") == root_id:
                        predicate_canonical = edge.get("predicate_canonical") or edge.get("predicate_uri")
                        if predicate_canonical == "http://arkumu.org/data/properties/bevorzugter-titel":
                            if edge.get("object_value"):
                                project_title = str(edge.get("object_value"))
                                break

                if project_title:
                    main_div.set("LABEL", project_title)
                else:
                    main_div.set("LABEL", f"Project {resource.uri.split('/')[-1] if resource.uri else 'Unknown'}")

                # Add files to both fileSec and structMap
                file_counter = 1
                for s3_file in project_files:
                    # Add to fileSec
                    file_elem = ET.SubElement(file_grp, "{http://www.loc.gov/METS/}file")
                    file_id = f"FILE_{file_counter:03d}"
                    file_elem.set("ID", file_id)
                    file_elem.set("MIMETYPE", s3_file.content_type or "application/octet-stream")
                    file_elem.set("SIZE", str(s3_file.file_size_bytes))

                    # Add FLocat pointing to the S3 key path (for Rosetta NFS access)
                    flocat = ET.SubElement(file_elem, "{http://www.loc.gov/METS/}FLocat")
                    flocat.set("LOCTYPE", "OTHER")
                    flocat.set("OTHERLOCTYPE", "FILESYSTEM")  # Indicates NFS/filesystem access
                    flocat.set("{http://www.w3.org/1999/xlink}href", s3_file.s3_key)  # Relative path for both S3 and NFS
                    flocat.set("{http://www.w3.org/1999/xlink}type", "simple")

                    # Add to structMap
                    file_div = ET.SubElement(main_div, "{http://www.loc.gov/METS/}div")
                    file_div.set("TYPE", "file")
                    file_div.set("LABEL", s3_file.file_name)

                    # Link to file via fptr
                    fptr = ET.SubElement(file_div, "{http://www.loc.gov/METS/}fptr")
                    fptr.set("FILEID", file_id)

                    file_counter += 1

        except Exception as e:
            # If file integration fails, don't break the entire METS response
            pass

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


def _build_dc_metadata_from_entity_graph(graph: Dict[str, Any], resource: Optional[Any] = None) -> Dict[str, List[str]]:
    """Build rich Dublin Core metadata from complete graph traversal with canonical URI support."""
    root_id = graph.get("root_id")
    edges = graph.get("edges", [])
    nodes = graph.get("nodes", {})

    # Initialize Dublin Core dictionary
    dc_dict = {
        "dc:title": [],
        "dc:creator": [],
        "dc:contributor": [],
        "dc:subject": [],
        "dc:description": [],
        "dc:date": [],
        "dc:type": [],
        "dc:language": [],
        "dc:relation": [],
        "dc:coverage": [],
        "dc:rights": [],
        "dc:identifier": []
    }

    # Helper functions with canonical URI support
    def get_canonical_predicate(edge: Dict[str, Any]) -> str:
        """Get canonical predicate URI with fallback."""
        return edge.get("predicate_canonical") or edge.get("predicate_uri")

    def get_entity_rich_data(entity_id: str, entity_uri: str) -> Dict[str, str]:
        """Extract rich data for an entity from the complete graph."""
        entity_data = {"name": None, "type": None, "language_code": None, "description": None}

        # Find all edges where this entity is the subject
        entity_edges = [e for e in edges if e.get("subject_id") == entity_id]

        # Name priority order for different entity types
        name_predicates = [
            "http://arkumu.org/data/properties/deutscher-name",
            "http://arkumu.org/data/properties/englischer-name",
            "http://arkumu.org/data/properties/bevorzugter-titel",
            "http://arkumu.org/data/properties/bezeichnung",
            "http://arkumu.org/data/properties/deutscher-name-der-sprache",
            "http://arkumu.org/data/properties/englischer-name-der-sprache",
            "http://arkumu.org/data/properties/deutscher-name-der-projektart",
            "http://arkumu.org/data/properties/englischer-name-der-projektart",
            "http://arkumu.org/data/properties/deutscher-name-der-projektkategorie-breadcrumb",
            "http://arkumu.org/data/properties/englischer-name-der-projektkategorie-breadcrumb",
            # Description predicates
            "http://arkumu.org/data/properties/deutsche-beschreibung",
            "http://arkumu.org/data/properties/englische-beschreibung",
            "http://arkumu.org/data/properties/beschreibung",
        ]

        # Extract name/content with preference for canonical predicates
        for predicate in name_predicates:
            for edge in entity_edges:
                edge_predicate = get_canonical_predicate(edge)
                if edge_predicate == predicate:
                    # Use our enhanced value extractor
                    value = get_actual_value(edge)
                    if value:
                        if "beschreibung" in predicate:
                            entity_data["description"] = value
                        else:
                            entity_data["name"] = value
                        break
            if entity_data["name"] or entity_data["description"]:
                break

        # For description entities, prioritize getting the actual description text
        if "/beschreibung/" in entity_uri and not entity_data["description"]:
            for edge in entity_edges:
                value = get_actual_value(edge)
                if value and len(str(value).strip()) > 10:  # Reasonable description length
                    entity_data["description"] = value
                    break

        # Extract language ISO code for language entities
        if "/sprache/" in entity_uri:
            for edge in entity_edges:
                edge_predicate = get_canonical_predicate(edge)
                if edge_predicate == "http://arkumu.org/data/properties/iso-639-1-code":
                    value = get_actual_value(edge)
                    if value:
                        entity_data["language_code"] = value
                        break

        # For Wikidata entities (Q-IDs), try to get readable labels
        if entity_uri and entity_uri.startswith("http://www.wikidata.org/entity/Q"):
            qid = entity_uri.split("/")[-1]
            # Look for wikidata labels in the graph
            for edge in entity_edges:
                edge_predicate = get_canonical_predicate(edge)
                if "label" in edge_predicate.lower() or "name" in edge_predicate.lower():
                    value = get_actual_value(edge)
                    if value:
                        entity_data["name"] = value
                        break
            # Fallback to Q-ID if no label found
            if not entity_data["name"]:
                entity_data["name"] = qid

        # Fallback to URI fragment if no name found
        if not entity_data["name"] and not entity_data["description"] and entity_uri:
            if "/" in entity_uri:
                fragment = entity_uri.split("/")[-1]
                if fragment.startswith("Q") and fragment[1:].isdigit():
                    # Keep Wikidata Q-IDs as is for now
                    entity_data["name"] = fragment
                else:
                    entity_data["name"] = fragment.replace("-", " ").title()
            else:
                entity_data["name"] = entity_uri

        return entity_data

    # Process ALL edges in the graph (not just root edges) for richer metadata
    serializer = DublinCoreSerializer(predicate_map=DEFAULT_PREDICATE_MAP)

    # 1. Process direct properties of the project (both literals and literal resources)
    def get_actual_value(edge: Dict[str, Any]) -> Optional[str]:
        """Get the actual string value from an edge, handling both direct values and literal resources."""
        # First try direct object_value
        if edge.get("object_value") is not None:
            return str(edge.get("object_value"))

        # Then try to get value from literal resource node
        object_id = edge.get("object_id")
        if object_id and object_id in nodes:
            node = nodes[object_id]
            if node.get("resource_type") == "LITERAL" and node.get("value"):
                return str(node.get("value"))

        return None

    # Process all direct edges from root (both literal values and literal resources)
    root_direct_edges = [
        e for e in edges if e.get("subject_id") == root_id
    ]

    # Use our enhanced value extractor
    basic_dc = serializer.serialize_from_triples(
        root_direct_edges,
        get_predicate=get_canonical_predicate,
        get_object_value=get_actual_value
    )

    # Merge basic DC metadata (only non-None values)
    for key, values in basic_dc.items():
        if key in dc_dict:
            # Filter out None values and empty strings
            valid_values = [v for v in values if v is not None and str(v).strip()]
            dc_dict[key].extend(valid_values)

    # 2. Process relationships to other entities with deep traversal
    relationship_edges = [
        e for e in edges if e.get("subject_id") == root_id and e.get("object_uri") is not None
    ]

    for edge in relationship_edges:
        predicate = get_canonical_predicate(edge)
        object_uri = edge.get("object_uri")
        object_id = edge.get("object_id")

        if predicate and object_uri and object_id:
            # Check if this predicate maps to a Dublin Core field
            dc_field = serializer.predicate_map.get(predicate)
            if dc_field:
                # Get rich entity data from the graph
                entity_data = get_entity_rich_data(object_id, object_uri)

                # Choose the best content based on the field type
                content = None
                if dc_field == "description":
                    # For descriptions, prefer the description content over name
                    content = entity_data.get("description") or entity_data.get("name")
                elif dc_field == "language" and entity_data.get("language_code"):
                    # For languages, use ISO code if available
                    content = entity_data["language_code"]
                else:
                    # For other fields, use name
                    content = entity_data.get("name")

                if content:
                    dc_key = f"dc:{dc_field}"
                    if dc_key not in dc_dict:
                        dc_dict[dc_key] = []
                    dc_dict[dc_key].append(content)

            # Enhanced actor/contributor processing with role distinction
            elif "/akteurin/" in object_uri:
                entity_data = get_entity_rich_data(object_id, object_uri)
                entity_name = entity_data.get("name")
                if entity_name:
                    # Determine creator vs contributor based on canonical predicate semantics
                    if (predicate in [
                        "http://arkumu.org/data/properties/urheber",
                        "http://arkumu.org/data/properties/kuenstler",
                        "http://arkumu.org/data/properties/autor"
                    ]):
                        dc_dict["dc:creator"].append(entity_name)
                    else:
                        dc_dict["dc:contributor"].append(entity_name)

            # Handle related projects with richer metadata
            elif "/projekt/" in object_uri and object_uri != (resource.uri if resource else None):
                entity_data = get_entity_rich_data(object_id, object_uri)
                entity_name = entity_data.get("name")
                if entity_name:
                    dc_dict["dc:relation"].append(f"Related project: {entity_name}")

    # 3. Traverse neighboring entities for additional metadata
    # Look for entities that reference our project for more context
    incoming_edges = [
        e for e in edges if e.get("object_id") == root_id and e.get("subject_id") != root_id
    ]

    for edge in incoming_edges:
        predicate = get_canonical_predicate(edge)
        subject_id = edge.get("subject_id")
        subject_uri = edge.get("object_uri")  # This would be in nodes

        # Find subject URI from nodes if not directly available
        if not subject_uri and subject_id in nodes:
            subject_uri = nodes[subject_id].get("uri")

        if subject_uri and predicate:
            # Add projects that reference this project
            if "/projekt/" in subject_uri:
                entity_data = get_entity_rich_data(subject_id, subject_uri)
                entity_name = entity_data.get("name")
                if entity_name:
                    dc_dict["dc:relation"].append(f"Referenced by: {entity_name}")

    # Clean up and deduplicate with intelligent filtering
    for key in dc_dict:
        # Remove duplicates while preserving order
        unique_values = list(dict.fromkeys(dc_dict[key]))

        # Filter out problematic values
        filtered_values = []
        for item in unique_values:
            if not item or not str(item).strip():
                continue

            item_str = str(item).strip()

            # Skip obvious hash/ID values (hexadecimal patterns)
            if len(item_str) == 16 and all(c in '0123456789ABCDEFabcdef' for c in item_str):
                continue

            # Skip very short meaningless values for descriptions
            if key == "dc:description" and len(item_str) < 10:
                continue

            # Skip pure numbers for non-identifier fields
            if key not in ["dc:identifier"] and item_str.isdigit():
                continue

            filtered_values.append(item)

        dc_dict[key] = filtered_values

    # Remove empty fields
    dc_dict = {k: v for k, v in dc_dict.items() if v}

    return dc_dict


def _list_records(oai: ET.Element, request: HttpRequest) -> ET.Element:
    """Implement ListRecords verb with complete metadata and pagination."""
    metadata_prefix = request.GET.get("metadataPrefix")
    set_spec = request.GET.get("set")
    from_date = request.GET.get("from")
    until_date = request.GET.get("until")
    resumption_token = request.GET.get("resumptionToken")
    has_resumption_param = "resumptionToken" in request.GET

    # Validate metadata format
    if not has_resumption_param and (not metadata_prefix or metadata_prefix not in ["oai_dc", "mets"]):
        return _error(oai, "cannotDisseminateFormat", "Only oai_dc and mets are supported")

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
                from_dt = datetime.fromisoformat(from_date.replace('Z', '+00:00')) if 'T' in from_date else datetime.strptime(from_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                until_dt = datetime.fromisoformat(until_date.replace('Z', '+00:00')) if 'T' in until_date else datetime.strptime(until_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
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

    # Check for cached page response first
    page_cache_key = _get_cache_key(
        "page",
        verb="ListRecords",
        metadata_prefix=metadata_prefix,
        set_spec=set_spec,
        from_date=from_date,
        until_date=until_date,
        offset=offset
    )

    cached_page = cache.get(page_cache_key)
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

    # Cache for 2 hours (shorter than individual records for freshness)
    cache.set(page_cache_key, page_data, 2 * 3600)

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
            if metadata_prefix not in ["oai_dc", "mets"]:
                return _xml_response(_error(oai, "cannotDisseminateFormat", "Only oai_dc and mets are supported"))

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
