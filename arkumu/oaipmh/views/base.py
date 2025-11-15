from __future__ import annotations

import logging
from datetime import timezone as dt_timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union
from urllib.parse import unquote, urlparse

from django.conf import settings
from django.http import HttpRequest
from django.utils import timezone
from lxml import etree as ET

from django.db.models import Q, Exists, OuterRef, DateTimeField, Value, F, Max
from django.db.models.functions import Coalesce, Greatest

from arkumu.metadata.models.resource import Resource, PublicAccessLevel
from arkumu.users.models import Organization
from arkumu.oaipmh.constants import XSI_NS
from arkumu.oaipmh.validation import rosetta_mets_validator
from arkumu.oaipmh.formats.dublin_core import DCTERMS_NS, OAI_DC_NS, DC_NS
from arkumu.oaipmh.resumption import ResumptionTokenService
from arkumu.cache.services import OAICacheService
from arkumu.oaipmh import schema_utils
from .config import (
    EVENT_COPYRIGHT_RIGHTS_URIS,
    EVENT_COPYRIGHT_TYPE_LABEL,
    EVENT_NEIGHBOURING_RIGHTS_URIS,
    EVENT_NEIGHBOURING_TYPE_LABEL,
    HARVESTABLE_FILE_STATUSES,
    METS_LEGACY_SCHEMA_FILE,
    METS_NS,
    METS_NSMAP,
    METS_PROFILE_VERSION,
    METS_SCHEMA_FILE,
    METS_SCHEMA_URL,
    OAI_NS,
    REPO_ADMIN_EMAIL,
    REPO_BASEURL,
    REPO_DELETED_RECORD,
    REPO_EARLIEST_DATASTAMP,
    REPO_GRANULARITY,
    REPO_NAME,
    REPO_PROTOCOL_VERSION,
    REPO_REPOSITORY_IDENTIFIER,
    SCHEMA_DESCRIPTION_NS,
    SIMPLIFIED_LICENSE_LABEL,
    SIMPLIFIED_LICENSE_NOTE,
    SUPPORTED_METADATA_FORMATS,
    XML_NS,
    _DIGITAL_OBJECT_ORG_DEFAULT,
    _DIGITAL_OBJECT_URI_REGEX,
    _PROJECT_TYPE_URIS,
    _RDF_TYPE_URI,
    _TAILORED_MIN_DATETIME,
    _curated_links_enabled,
    _db_mode_enabled,
    _enforce_basic_auth,
    _force_curated_links,
    _force_db_mode,
    _force_tailored_mode,
    _tailored_mode_enabled,
)
from .harvest import (
    _dataset_marker_for_queryset,
    _get_resources_queryset,
    _harvestable_page_from_db,
    _harvestable_snapshot_projects,
    _parse_from_datestamp,
    _parse_until_datestamp,
    _restrict_to_harvestable_files,
    _validate_datestamp,
)
from .metadata import (
    _build_metadata_element,
    _build_record_header,
    _format_datestamp,
    _metadata_element_is_valid,
    _metadata_xml_is_valid,
)




# Namespace helpers for Rosetta METS output
# Namespace helpers for Rosetta METS output









# Initialize services
resumption_service = ResumptionTokenService(page_size=10)
oai_cache = OAICacheService()

# Register stable namespace prefixes so ElementTree uses human-friendly tags
ET.register_namespace("oai_dc", OAI_DC_NS)
ET.register_namespace("dc", DC_NS)
ET.register_namespace("dcterms", DCTERMS_NS)

logger = logging.getLogger(__name__)


def _error(oai: ET._Element, code: str, message: str) -> ET._Element:
    """Attach an OAI-PMH error to the response envelope."""
    error_elem = ET.SubElement(oai, "error", {"code": code})
    error_elem.text = message
    return oai


def _get_cached_record(
    resource: Resource,
    metadata_prefix: str,
    *,
    snapshot_marker: str = "",
    cursor_marker: str = "",
) -> Optional[Dict[str, Any]]:
    """Get cached OAI-PMH record if available."""
    profile_version = METS_PROFILE_VERSION if metadata_prefix == "mets" else ""
    return oai_cache.get_cached_record(
        resource,
        metadata_prefix,
        profile_version=profile_version,
        snapshot_marker=snapshot_marker,
        cursor_marker=cursor_marker,
    )


def _cache_record(
    resource: Resource,
    metadata_prefix: str,
    header_xml: str,
    metadata_xml: str,
    *,
    snapshot_marker: str = "",
    cursor_marker: str = "",
):
    """Cache OAI-PMH record data."""
    profile_version = METS_PROFILE_VERSION if metadata_prefix == "mets" else ""
    oai_cache.cache_record(
        resource,
        metadata_prefix,
        header_xml,
        metadata_xml,
        profile_version=profile_version,
        snapshot_marker=snapshot_marker,
        cursor_marker=cursor_marker,
    )


def _identify(oai: ET._Element, request: HttpRequest) -> ET._Element:
    request_elem = oai.find(f"{{{OAI_NS}}}request")
    if request_elem is not None and not request_elem.get("verb"):
        request_elem.set("verb", "Identify")
    identify = ET.SubElement(oai, "Identify")
    ET.SubElement(identify, "repositoryName").text = REPO_NAME
    # Absolute baseURL per spec
    absolute_base = request.build_absolute_uri(request.path)
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
                earliest = earliest.replace(tzinfo=dt_timezone.utc)
            ET.SubElement(identify, "earliestDatestamp").text = _format_datestamp(earliest)
        else:
            ET.SubElement(identify, "earliestDatestamp").text = REPO_EARLIEST_DATASTAMP
    except Exception:
        ET.SubElement(identify, "earliestDatestamp").text = REPO_EARLIEST_DATASTAMP

    ET.SubElement(identify, "deletedRecord").text = REPO_DELETED_RECORD
    ET.SubElement(identify, "granularity").text = REPO_GRANULARITY

    schema_bundle = schema_utils.build_schema_url_bundle(request)
    if schema_bundle:
        description = ET.SubElement(identify, "description")
        schema_info = ET.SubElement(
            description,
            ET.QName(SCHEMA_DESCRIPTION_NS, "schemaInfo"),
            nsmap={"arkschema": SCHEMA_DESCRIPTION_NS},
        )
        schema_info.set("snapshot", schema_bundle.snapshot_tag)
        for variant, format_map in schema_bundle.urls.items():
            for fmt, urls in format_map.items():
                schema_elem = ET.SubElement(
                    schema_info,
                    ET.QName(SCHEMA_DESCRIPTION_NS, "schema"),
                )
                schema_elem.set("type", variant)
                schema_elem.set("format", fmt)
                schema_elem.set("latest", urls.get("latest", ""))
                schema_elem.set("snapshot", urls.get("snapshot", ""))

    return oai


def _list_metadata_formats(oai: ET._Element, identifier: Optional[str] = None) -> ET._Element:
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
    ET.SubElement(mets_format, "schema").text = METS_SCHEMA_URL
    ET.SubElement(mets_format, "metadataNamespace").text = METS_NS

    return oai


def _list_sets(oai: ET._Element) -> ET._Element:
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
                ET.QName(OAI_DC_NS, "dc"),
                nsmap={
                    "oai_dc": OAI_DC_NS,
                    "dc": DC_NS,
                    "xsi": XSI_NS,
                },
            )
            oai_dc.set(
                ET.QName(XSI_NS, "schemaLocation"),
                f"{OAI_DC_NS} http://www.openarchives.org/OAI/2.0/oai_dc.xsd",
            )
            ET.SubElement(oai_dc, ET.QName(DC_NS, "description")).text = (
                f"Resources from {org.name} (domain: {org.domain})"
            )

    return oai


def _list_identifiers(oai: ET._Element, params) -> ET._Element:
    """Implement ListIdentifiers verb with pagination."""
    metadata_prefix = params.get("metadataPrefix")
    set_spec = params.get("set")
    from_date = params.get("from")
    until_date = params.get("until")
    resumption_token = params.get("resumptionToken")
    has_resumption_param = "resumptionToken" in params

    # Validate metadata format
    if not has_resumption_param and (not metadata_prefix or metadata_prefix not in SUPPORTED_METADATA_FORMATS):
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

        if from_date and until_date:
            from_has_time = 'T' in from_date
            until_has_time = 'T' in until_date
            if from_has_time != until_has_time:
                return _error(oai, "badArgument", "'from' and 'until' must have the same granularity")

            try:
                from_dt = _parse_from_datestamp(from_date)
                until_dt = _parse_until_datestamp(until_date)
                if from_dt >= until_dt:
                    return _error(oai, "badArgument", "'from' date must be earlier than 'until' date")
            except ValueError:
                pass  # Already validated above

    # Handle resumption token
    offset = 0
    cursor_marker_from_token: Optional[str] = None
    cursor_position_from_token: Optional[str] = None
    if has_resumption_param:
        if not resumption_token or not resumption_token.strip():
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
        cursor_marker_from_token = token_data.get("cursor") or token_data.get("snapshot")
        cursor_position_from_token = token_data.get("cursor_position")

    db_mode = _db_mode_enabled()
    tailored_mode = _tailored_mode_enabled()
    if db_mode:
        if tailored_mode:
            from . import tailored

            return tailored._list_identifiers_tailored(
                oai,
                metadata_prefix=metadata_prefix,
                set_spec=set_spec,
                from_date=from_date,
                until_date=until_date,
                offset=offset,
                cursor_marker_from_token=cursor_marker_from_token,
                cursor_position_from_token=cursor_position_from_token,
            )
        return _list_identifiers_db(
            oai,
            metadata_prefix=metadata_prefix,
            set_spec=set_spec,
            from_date=from_date,
            until_date=until_date,
            offset=offset,
            cursor_marker_from_token=cursor_marker_from_token,
            cursor_position_from_token=cursor_position_from_token,
        )

    snapshot, harvestable_projects = _harvestable_snapshot_projects()
    snapshot_version = snapshot.generated_at.isoformat()

    if cursor_marker_from_token and cursor_marker_from_token != snapshot_version:
        return _error(oai, "badResumptionToken", "Snapshot has changed; restart harvesting")

    allowed_uris = list(harvestable_projects.keys())

    if not allowed_uris:
        return _error(oai, "noRecordsMatch", "No harvestable projects available")

    # Build resource queryset
    queryset = _get_resources_queryset(set_spec, from_date, until_date, metadata_prefix, allowed_uris=allowed_uris)

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
        offset=offset,
        snapshot_marker=snapshot_version,
        cursor_marker=snapshot_version,
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
            until_date=until_date,
            snapshot_marker=snapshot_version,
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
        offset=offset,
        snapshot_marker=snapshot_version,
        cursor_marker=snapshot_version,
    )

    return oai


def _list_identifiers_db(
    oai: ET._Element,
    *,
    metadata_prefix: str,
    set_spec: Optional[str],
    from_date: Optional[str],
    until_date: Optional[str],
    offset: int,
    cursor_marker_from_token: Optional[str],
    cursor_position_from_token: Optional[str],
) -> ET._Element:
    queryset = _get_resources_queryset(set_spec, from_date, until_date, metadata_prefix, allowed_uris=None)
    cursor_marker = _dataset_marker_for_queryset(queryset)

    if cursor_marker_from_token and cursor_marker_from_token != cursor_marker:
        return _error(oai, "badResumptionToken", "Dataset has changed; restart harvesting")

    page_size = resumption_service.page_size
    cached_page = oai_cache.get_cached_page(
        verb='ListIdentifiers',
        metadata_prefix=metadata_prefix,
        set_spec=set_spec or '',
        from_date=from_date or '',
        until_date=until_date or '',
        offset=offset,
        snapshot_marker=cursor_marker,
        cursor_marker=cursor_marker,
    )
    if cached_page:
        list_identifiers = ET.SubElement(oai, "ListIdentifiers")
        for record_data in cached_page['headers']:
            header = ET.fromstring(record_data)
            list_identifiers.append(header)
        if cached_page.get('resumption_token'):
            resumption_elem = ET.SubElement(list_identifiers, "resumptionToken")
            resumption_elem.text = cached_page['resumption_token']
        return oai

    page = _harvestable_page_from_db(
        queryset,
        cursor_position=cursor_position_from_token,
        page_size=page_size,
        include_hints=False,
    )
    resources = page.resources

    if offset == 0 and not resources:
        return _error(oai, "noRecordsMatch", "No records found matching the criteria")

    list_identifiers = ET.SubElement(oai, "ListIdentifiers")
    headers_data: List[str] = []
    for resource in resources:
        header = _build_record_header(resource)
        list_identifiers.append(header)
        headers_data.append(ET.tostring(header, encoding='utf-8').decode('utf-8'))

    resumption_token_value = None
    if page.has_more:
        next_offset = offset + len(resources)
        resumption_token_value = resumption_service.create_token(
            offset=next_offset,
            verb="ListIdentifiers",
            metadata_prefix=metadata_prefix,
            set_spec=set_spec,
            from_date=from_date,
            until_date=until_date,
            cursor_marker=cursor_marker,
            cursor_position=page.cursor_position,
        )
        resumption_elem = ET.SubElement(list_identifiers, "resumptionToken")
        resumption_elem.text = resumption_token_value

    list_page_data = {
        'headers': headers_data,
        'resumption_token': resumption_token_value,
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
        offset=offset,
        snapshot_marker=cursor_marker,
        cursor_marker=cursor_marker,
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




































_RIGHTS_STATUS_PROTECTED_EN = "Protected by German Urheberrecht and/oder Leistungsschutzrecht."
_RIGHTS_STATUS_FREE_EN = "Free of German Urheberrecht and Leistungsschutzrecht protection."

_RIGHTS_DISCLAIMER_PROTECTED_DE = (
    "Das Projekt/Werk ist durch das deutsche Urheberrecht und Leistungsschutzrecht geschützt. Einige Digitale Objekte können auch noch "
    "durch Verwertungsrechte geschützt sein. Überprüfen Sie daher bitte alle verknüpften Ereignisse sorgfältig, bevor Sie die bereitgestellten Medien weiterverwenden."
)
_RIGHTS_DISCLAIMER_PROTECTED_EN = (
    "The Project/Work is protected by German Urheberrecht and/oder Leistungsschutzrecht. "
    "Some digital objects may also be protected by exploitation rights. Therefore, please "
    "check all linked events thoroughly before further use of the media provided."
)

_RIGHTS_DISCLAIMER_FREE_DE = (
    "Das Projekt/Werk ist frei nach dem deutschen Urheberrecht und Leistungsschutzrecht. Dennoch können einige "
    "Digitale Objekte, referenziert über Ereignisse, immer noch dem urheberrechtlichen, leistungsschutzrechtlichen "
    "oder verwertungsrechtlichen Schutz unterliegen. Überprüfen Sie daher bitte alle verknüpften Ereignisse "
    "sorgfältig, bevor Sie die bereitgestellten Medien weiterverwenden."
)
_RIGHTS_DISCLAIMER_FREE_EN = (
    "The Project/Work is free under German Urheberrecht and Leistungsschutzrecht. However, some digital objects, "
    "referenced via events, may still be subject to German Urheberrecht, German Leistungsschutzrecht or exploitation "
    "rights protection. Therefore, please check all linked events thoroughly before further use of the media provided."
)


































def _list_records(oai: ET._Element, params, request: Optional[HttpRequest] = None) -> ET._Element:
    """Implement ListRecords verb with complete metadata and pagination."""
    metadata_prefix = params.get("metadataPrefix")
    set_spec = params.get("set")
    from_date = params.get("from")
    until_date = params.get("until")
    resumption_token = params.get("resumptionToken")
    has_resumption_param = "resumptionToken" in params

    # Validate metadata format
    if not has_resumption_param and (not metadata_prefix or metadata_prefix not in SUPPORTED_METADATA_FORMATS):
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

        if from_date and until_date:
            from_has_time = 'T' in from_date
            until_has_time = 'T' in until_date
            if from_has_time != until_has_time:
                return _error(oai, "badArgument", "'from' and 'until' must have the same granularity")

            try:
                from_dt = _parse_from_datestamp(from_date)
                until_dt = _parse_until_datestamp(until_date)
                if from_dt >= until_dt:
                    return _error(oai, "badArgument", "'from' date must be earlier than 'until' date")
            except ValueError:
                pass  # Already validated above

    # Handle resumption token
    offset = 0
    snapshot_marker_from_token: Optional[str] = None
    cursor_marker_from_token: Optional[str] = None
    cursor_position_from_token: Optional[str] = None
    if has_resumption_param:
        if not resumption_token or not resumption_token.strip():
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
        cursor_marker_from_token = token_data.get("cursor") or token_data.get("snapshot")
        snapshot_marker_from_token = token_data.get("snapshot")
        cursor_position_from_token = token_data.get("cursor_position")

    db_mode = _db_mode_enabled()
    tailored_mode = _tailored_mode_enabled()
    if db_mode:
        if tailored_mode:
            from . import tailored

            return tailored._list_records_tailored(
                oai,
                metadata_prefix=metadata_prefix,
                set_spec=set_spec,
                from_date=from_date,
                until_date=until_date,
                offset=offset,
                cursor_marker_from_token=cursor_marker_from_token,
                cursor_position_from_token=cursor_position_from_token,
                request=request,
            )
        return _list_records_db(
            oai,
            metadata_prefix=metadata_prefix,
            set_spec=set_spec,
            from_date=from_date,
            until_date=until_date,
            offset=offset,
            cursor_marker_from_token=cursor_marker_from_token,
            cursor_position_from_token=cursor_position_from_token,
            request=request,
        )

    snapshot, harvestable_projects = _harvestable_snapshot_projects()
    snapshot_version = snapshot.generated_at.isoformat()

    effective_marker = cursor_marker_from_token or snapshot_marker_from_token
    if effective_marker and effective_marker != snapshot_version:
        return _error(oai, "badResumptionToken", "Snapshot has changed; restart harvesting")

    allowed_uris = list(harvestable_projects.keys())

    if not allowed_uris:
        return _error(oai, "noRecordsMatch", "No harvestable projects available")

    # Build resource queryset
    queryset = _get_resources_queryset(
        set_spec,
        from_date,
        until_date,
        metadata_prefix,
        allowed_uris=allowed_uris,
    )

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
        offset=offset,
        snapshot_marker=snapshot_version,
        cursor_marker=snapshot_version,
    )
    if cached_page and not (
        metadata_prefix == 'mets'
        and any(
            not _metadata_xml_is_valid(record_data['metadata'])
            for record_data in cached_page.get('records', [])
        )
    ):
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
    records_added = 0

    for resource in resources:
        # Try to get cached record first
        cached_record = _get_cached_record(
            resource,
            metadata_prefix,
            snapshot_marker=snapshot_version,
            cursor_marker=snapshot_version,
        )

        if cached_record and metadata_prefix == 'mets' and not _metadata_xml_is_valid(
            cached_record['metadata'],
            resource_uri=getattr(resource, 'uri', None),
        ):
            cached_record = None

        if cached_record:
            # Use cached record
            record = ET.SubElement(list_records, "record")
            header = ET.fromstring(cached_record['header'])
            metadata = ET.fromstring(cached_record['metadata'])
            record.append(header)
            record.append(metadata)
            records_data.append(cached_record)
            records_added += 1
            continue

        project_hint = harvestable_projects.get(resource.uri)
        if not project_hint:
            logger.debug(
                "Skipping resource %s because no harvestable project was resolved",
                getattr(resource, 'uri', 'unknown'),
            )
            continue

        # Build record and cache it
        header = _build_record_header(resource)
        metadata = _build_metadata_element(
            resource,
            metadata_prefix,
            project_hint=project_hint,
            request=request,
        )

        if metadata_prefix == 'mets' and not _metadata_element_is_valid(
            metadata,
            resource_uri=getattr(resource, 'uri', None),
        ):
            logger.info(
                "Skipping resource %s for METS harvest because the METS payload failed validation",
                getattr(resource, 'uri', 'unknown'),
            )
            continue

        record = ET.SubElement(list_records, "record")
        record.append(header)
        record.append(metadata)

        # Cache individual record
        header_xml = ET.tostring(header, encoding='utf-8').decode('utf-8')
        metadata_xml = ET.tostring(metadata, encoding='utf-8').decode('utf-8')
        _cache_record(
            resource,
            metadata_prefix,
            header_xml,
            metadata_xml,
            snapshot_marker=snapshot_version,
            cursor_marker=snapshot_version,
        )

        records_data.append({
            'header': header_xml,
            'metadata': metadata_xml,
            'timestamp': int(resource.updated_at.timestamp())
        })
        records_added += 1

    if records_added == 0 and offset == 0 and not has_more:
        return _error(oai, "noRecordsMatch", "No records found matching the criteria")

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
            until_date=until_date,
            snapshot_marker=snapshot_version,
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
        offset=offset,
        snapshot_marker=snapshot_version,
        cursor_marker=snapshot_version,
    )

    return oai


def _list_records_db(
    oai: ET._Element,
    *,
    metadata_prefix: str,
    set_spec: Optional[str],
    from_date: Optional[str],
    until_date: Optional[str],
    offset: int,
    cursor_marker_from_token: Optional[str],
    cursor_position_from_token: Optional[str],
    request: Optional[HttpRequest] = None,
) -> ET._Element:
    queryset = _get_resources_queryset(
        set_spec,
        from_date,
        until_date,
        metadata_prefix,
        allowed_uris=None,
    )
    cursor_marker = _dataset_marker_for_queryset(queryset)

    if cursor_marker_from_token and cursor_marker_from_token != cursor_marker:
        return _error(oai, "badResumptionToken", "Dataset has changed; restart harvesting")

    page_size = resumption_service.page_size
    cached_page = None
    if not _db_mode_enabled():
        cached_page = oai_cache.get_cached_page(
            verb='ListRecords',
            metadata_prefix=metadata_prefix,
            set_spec=set_spec or '',
            from_date=from_date or '',
            until_date=until_date or '',
            offset=offset,
            snapshot_marker=cursor_marker,
            cursor_marker=cursor_marker,
        )
        if cached_page and not (
            metadata_prefix == 'mets'
            and any(
                not _metadata_xml_is_valid(record_data['metadata'])
                for record_data in cached_page.get('records', [])
            )
        ):
            list_records = ET.SubElement(oai, "ListRecords")
            for record_data in cached_page['records']:
                record = ET.SubElement(list_records, "record")
                header = ET.fromstring(record_data['header'])
                metadata = ET.fromstring(record_data['metadata'])
                record.append(header)
                record.append(metadata)
            if cached_page.get('resumption_token'):
                resumption_elem = ET.SubElement(list_records, "resumptionToken")
                resumption_elem.text = cached_page['resumption_token']
            return oai

    page = _harvestable_page_from_db(
        queryset,
        cursor_position=cursor_position_from_token,
        page_size=page_size,
        include_hints=True,
    )
    resources = page.resources

    if offset == 0 and not resources:
        return _error(oai, "noRecordsMatch", "No records found matching the criteria")

    list_records = ET.SubElement(oai, "ListRecords")
    records_data: List[Dict[str, str]] = []
    records_added = 0

    for resource in resources:
        project_hint = page.project_hints.get(resource.uri)
        if not project_hint:
            continue

        header = _build_record_header(resource)
        metadata = _build_metadata_element(
            resource,
            metadata_prefix,
            project_hint=project_hint,
            request=request,
        )

        if metadata_prefix == 'mets' and not _metadata_element_is_valid(
            metadata,
            resource_uri=getattr(resource, 'uri', None),
        ):
            continue

        record = ET.SubElement(list_records, "record")
        record.append(header)
        record.append(metadata)

        header_xml = ET.tostring(header, encoding='utf-8').decode('utf-8')
        metadata_xml = ET.tostring(metadata, encoding='utf-8').decode('utf-8')
        if not _db_mode_enabled():
            _cache_record(
                resource,
                metadata_prefix,
                header_xml,
                metadata_xml,
                snapshot_marker=cursor_marker,
                cursor_marker=cursor_marker,
            )
        records_data.append({
            'header': header_xml,
            'metadata': metadata_xml,
            'timestamp': int(resource.updated_at.timestamp())
        })
        records_added += 1

    if records_added == 0 and offset == 0 and not page.has_more:
        return _error(oai, "noRecordsMatch", "No records found matching the criteria")

    resumption_token_value = None
    if page.has_more:
        next_offset = offset + records_added
        resumption_token_value = resumption_service.create_token(
            offset=next_offset,
            verb="ListRecords",
            metadata_prefix=metadata_prefix,
            set_spec=set_spec,
            from_date=from_date,
            until_date=until_date,
            cursor_marker=cursor_marker,
            cursor_position=page.cursor_position,
        )
        resumption_elem = ET.SubElement(list_records, "resumptionToken")
        resumption_elem.text = resumption_token_value

    page_payload = {
        'records': records_data,
        'resumption_token': resumption_token_value,
        'count': len(records_data),
        'cached_at': timezone.now().isoformat()
    }

    if not _db_mode_enabled():
        oai_cache.cache_page(
            verb='ListRecords',
            metadata_prefix=metadata_prefix,
            page_data=page_payload,
            set_spec=set_spec or '',
            from_date=from_date or '',
            until_date=until_date or '',
            offset=offset,
            snapshot_marker=cursor_marker,
            cursor_marker=cursor_marker,
        )

    return oai
