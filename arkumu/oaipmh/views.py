from __future__ import annotations

import base64
import binascii
import logging
import mimetypes
import re
from datetime import datetime, timezone as dt_timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union
from urllib.parse import unquote, urlparse

from django.conf import settings
from django.contrib.auth import authenticate
from django.http import HttpRequest, HttpResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from lxml import etree as ET

from django.db.models import Q

from arkumu.metadata.models.resource import Resource, PublicAccessLevel
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.services.canonical_graph_service import CanonicalGraphService
from arkumu.users.models import Organization
from arkumu.projects import ProjectDigitalObject, ProjectEvent, ProjectRecord, ProjectSnapshot
from arkumu.projects.fixity import parse_fixity
from arkumu.projects.services import ProjectSnapshotService
from arkumu.oaipmh.constants import (
    DNX_NS,
    METS_NS as DEFAULT_METS_NS,
    METS_SCHEMA_URL as DEFAULT_METS_SCHEMA_URL,
    XLINK_NS,
    XSI_NS,
)
from arkumu.oaipmh.validation import rosetta_mets_validator
from .formats.dublin_core import DCTERMS_NS, OAI_DC_NS, DC_NS
from .resumption import ResumptionTokenService
from arkumu.common.uri_utils import slugify_uri_part
from arkumu.cache.services import OAICacheService
from arkumu.storage.models.s3_file_objects import S3FileObject
from arkumu.oaipmh.oai_project import (
    HARVESTABLE_STORAGE_STATUSES,
    NormalizedDigitalObject,
    OAIProject,
    OAIProjectBuilder,
)
from arkumu.oaipmh.formats.mets_source_metadata import build_rdf_graph


# Minimal repository config (can be moved to settings)
REPO_NAME = "Arkumu Repository"
REPO_BASEURL = "/oai/"
REPO_ADMIN_EMAIL = "mondaca@uni-koeln.de"
REPO_PROTOCOL_VERSION = "2.0"
REPO_EARLIEST_DATASTAMP = "1970-01-01T00:00:00Z"
REPO_DELETED_RECORD = "no"
REPO_GRANULARITY = "YYYY-MM-DDThh:mm:ssZ"
REPO_REPOSITORY_IDENTIFIER = "arkumu"

METS_NS = DEFAULT_METS_NS
OAI_NS = "http://www.openarchives.org/OAI/2.0/"
METS_SCHEMA_URL = DEFAULT_METS_SCHEMA_URL
XML_NS = "http://www.w3.org/XML/1998/namespace"
SUPPORTED_METADATA_FORMATS = ["oai_dc", "mets"]
METS_PROFILE_VERSION = "LOC-METS"
METS_SCHEMA_FILE = Path(settings.BASE_DIR) / "arkumu/oaipmh/schema/mets.xsd"
METS_LEGACY_SCHEMA_FILE = METS_SCHEMA_FILE
HARVESTABLE_FILE_STATUSES = HARVESTABLE_STORAGE_STATUSES

METS_NSMAP = {
    'mets': METS_NS,
    'dc': DC_NS,
    'dcterms': DCTERMS_NS,
    'xlink': XLINK_NS,
    'xsi': XSI_NS,
    None: DNX_NS
}

_DIGITAL_OBJECT_ORG_DEFAULT = ("fuk", "det", "rsh")
_DIGITAL_OBJECT_URI_REGEX = r'/entities/digitales-objekt/[0-9]+$'


def _digital_object_orgs() -> set[str]:
    configured = getattr(settings, "OAI_DIGITAL_OBJECT_LINK_ORGS", _DIGITAL_OBJECT_ORG_DEFAULT)
    return {
        str(code).lower().strip()
        for code in configured
        if code
    }


def _metadata_element_is_valid(
    metadata_elem: ET._Element,
    *,
    resource_uri: Optional[str] = None,
) -> bool:
    """Check that a metadata wrapper contains a schema-valid METS payload."""

    result = rosetta_mets_validator.validate_metadata_element(
        metadata_elem,
        resource_uri=resource_uri,
    )
    return result.is_valid


def _metadata_xml_is_valid(
    metadata_xml: str,
    *,
    resource_uri: Optional[str] = None,
) -> bool:
    """Parse and validate cached METS metadata stored as XML text."""

    result = rosetta_mets_validator.validate_metadata_xml(
        metadata_xml,
        resource_uri=resource_uri,
    )
    return result.is_valid

# Namespace helpers for Rosetta METS output


def _register_rosetta_namespaces() -> None:
    """Register namespace prefixes required for Rosetta METS serialization."""
    ET.register_namespace('mets', METS_NS)
    ET.register_namespace('dc', DC_NS)
    ET.register_namespace('dcterms', DCTERMS_NS)
    ET.register_namespace('xlink', XLINK_NS)
    ET.register_namespace('xsi', XSI_NS)


def _create_dnx_element(
    parent: ET._Element,
    tag: str,
    attrib: Optional[Dict[str, str]] = None,
    text: Optional[str] = None,
) -> ET._Element:
    """Create a DNX element that renders without an explicit namespace prefix."""

    # Use the same library as the parent element
    # Check if parent has the lxml-specific nsmap attribute
    elem = ET.SubElement(parent, ET.QName(DNX_NS, tag), attrib or {})

    if text is not None:
        elem.text = str(text)

    return elem


def _infer_representation_type(obj: NormalizedDigitalObject) -> str:
    """Heuristically map digital objects onto Rosetta representation buckets."""
    hint_parts = [
        getattr(obj, 'storage_key', None) or getattr(obj, 'path', None) or '',
        getattr(obj, 'original_path', None) or getattr(obj, 'path', None) or '',
        getattr(obj, 'file_name', None) or '',
        getattr(obj, 'rosetta_path', None) or '',
    ]
    hint = " ".join(hint_parts).lower()

    if any(token in hint for token in ("preservation", "master")):
        return "PRESERVATION_MASTER"

    if any(token in hint for token in ("derivate", "derivative", "modified", "preview", "service")):
        return "MODIFIED_MASTER"

    if any(token in hint for token in ("access", "web", "thumbnail", "delivery")):
        return "MODIFIED_MASTER_02"

    if obj.content_type and obj.content_type.lower() in {"application/pdf", "application/vnd.ms-powerpoint"}:
        return "MODIFIED_MASTER"

    return "PRESERVATION_MASTER"


def _group_digital_objects_for_rosetta(objects: List[NormalizedDigitalObject]) -> List[tuple[str, List[NormalizedDigitalObject]]]:
    """Return preservation master files grouped for Rosetta representations."""

    preservation_objects = [
        obj for obj in objects
        if _infer_representation_type(obj) == "PRESERVATION_MASTER"
    ]

    if preservation_objects:
        return [("PRESERVATION_MASTER", preservation_objects)]

    if objects:
        # Fallback to all objects to avoid emitting an empty representation when heuristics failed.
        return [("PRESERVATION_MASTER", objects)]

    return []

# Initialize services
resumption_service = ResumptionTokenService(page_size=10)
oai_cache = OAICacheService()
snapshot_service = ProjectSnapshotService()
project_builder = OAIProjectBuilder()

# Register stable namespace prefixes so ElementTree uses human-friendly tags
ET.register_namespace("oai_dc", OAI_DC_NS)
ET.register_namespace("dc", DC_NS)
ET.register_namespace("dcterms", DCTERMS_NS)

logger = logging.getLogger(__name__)


def _enforce_basic_auth(request: HttpRequest) -> Optional[HttpResponse]:
    """Enforce optional HTTP Basic Auth for the OAI endpoint."""

    # Allow trusted internal proxies (e.g., staff previews) to bypass auth
    if request.META.get("HTTP_X_INTERNAL_OAI_BYPASS") == "1":
        return None

    if not getattr(settings, "OAI_BASIC_AUTH_ENABLED", False):
        return None

    allowed_users = getattr(settings, "OAI_BASIC_AUTH_ALLOWED_USERS", [])
    if not allowed_users:
        return None

    auth_header = request.META.get("HTTP_AUTHORIZATION", "")
    if auth_header.startswith("Basic "):
        encoded = auth_header.split(" ", 1)[1].strip()
        try:
            decoded = base64.b64decode(encoded).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            decoded = ""
        if decoded:
            input_username, _, input_password = decoded.partition(":")
            if input_username and input_password:
                user = authenticate(request=request, username=input_username, password=input_password)
                if user is not None and user.is_active and user.username in allowed_users:
                    return None

    response = HttpResponse(status=401)
    response["WWW-Authenticate"] = 'Basic realm="Arkumu OAI"'
    return response


def _get_cached_record(
    resource: Resource,
    metadata_prefix: str,
    *,
    snapshot_marker: str = "",
) -> Optional[Dict[str, Any]]:
    """Get cached OAI-PMH record if available."""
    profile_version = METS_PROFILE_VERSION if metadata_prefix == "mets" else ""
    return oai_cache.get_cached_record(
        resource,
        metadata_prefix,
        profile_version=profile_version,
        snapshot_marker=snapshot_marker,
    )


def _cache_record(
    resource: Resource,
    metadata_prefix: str,
    header_xml: str,
    metadata_xml: str,
    *,
    snapshot_marker: str = "",
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
    )


def _restrict_to_harvestable_files(queryset):
    """Limit queryset to resources with at least one linked S3 object ready for harvest."""

    s3_condition = (
        Q(s3fileobject__status__in=HARVESTABLE_FILE_STATUSES)
        & Q(s3fileobject__s3_key__isnull=False)
        & ~Q(s3fileobject__s3_key__exact="")
    )

    rosetta_orgs = {
        code.lower().strip()
        for code in getattr(settings, "OAI_ROSETTA_HARVESTABLE_ORGS", ())
        if code
    }

    rosetta_condition = Q()
    for code in rosetta_orgs:
        rosetta_condition |= Q(organization__code__iexact=code)

    event_file_event_ids = S3FileObject.objects.filter(
        status__in=HARVESTABLE_FILE_STATUSES,
        related_resource__uri__regex=r'/entities/ereignis/[0-9]+$',
    ).values('related_resource_id')

    project_ids_via_events = Triple.objects.filter(
        predicate__uri__endswith='/properties/ereignis',
        object_id__in=event_file_event_ids,
    ).values('subject_id')

    project_event_condition = Q(pk__in=project_ids_via_events)

    digital_object_orgs = _digital_object_orgs()
    has_digital_condition = False
    digital_object_condition = Q()
    if digital_object_orgs:
        digital_object_resource_ids = S3FileObject.objects.filter(
            status__in=HARVESTABLE_FILE_STATUSES,
            related_resource__uri__regex=_DIGITAL_OBJECT_URI_REGEX,
            related_resource__organization__code__in=digital_object_orgs,
        ).values_list('related_resource_id', flat=True)

        digital_object_ids = list(digital_object_resource_ids)
        if digital_object_ids:
            digital_links = Triple.objects.filter(
                predicate__uri__endswith='/properties/digitales-objekt',
                object_id__in=digital_object_ids,
            )

            direct_project_ids = set(
                digital_links.filter(
                    subject__uri__contains='/entities/projekt/'
                ).values_list('subject_id', flat=True)
            )

            event_link_ids = list(
                digital_links.filter(
                    subject__uri__contains='/entities/ereignis/'
                ).values_list('subject_id', flat=True)
            )

            project_ids_via_events = set()
            if event_link_ids:
                project_ids_via_events.update(
                    Triple.objects.filter(
                        predicate__uri__endswith='/properties/ereignis',
                        object_id__in=event_link_ids,
                    ).values_list('subject_id', flat=True)
                )

            all_project_ids = direct_project_ids | project_ids_via_events
            if all_project_ids:
                digital_object_condition = Q(pk__in=list(all_project_ids)) & Q(
                    organization__code__in=digital_object_orgs
                )
                has_digital_condition = True

    event_condition = project_event_condition
    if digital_object_orgs:
        event_condition = project_event_condition & ~Q(organization__code__in=digital_object_orgs)

    combined_condition = s3_condition | event_condition
    if rosetta_orgs:
        combined_condition |= rosetta_condition
    if has_digital_condition:
        combined_condition |= digital_object_condition

    queryset = queryset.filter(combined_condition)

    return queryset.distinct()
def _fallback_record_from_storage(resource: Resource) -> Optional[ProjectRecord]:
    """Construct a minimal ProjectRecord using linked S3 files."""

    if not isinstance(resource, Resource) or getattr(resource, 'pk', None) is None:
        return None

    direct_files = S3FileObject.objects.filter(
        related_resource=resource,
        status__in=HARVESTABLE_FILE_STATUSES,
        s3_key__isnull=False,
    ).exclude(s3_key="")

    resource_org_code = None
    if getattr(resource, "organization", None) and getattr(resource.organization, "code", None):
        resource_org_code = resource.organization.code.lower().strip()

    digital_files = S3FileObject.objects.none()
    digital_object_ids: set[int] = set(
        Triple.objects.filter(
            subject=resource,
            predicate__uri__endswith='/properties/digitales-objekt',
        ).values_list('object_id', flat=True)
    )
    digital_object_orgs = _digital_object_orgs()
    is_digital_only = resource_org_code and resource_org_code in digital_object_orgs
    if is_digital_only:
        event_ids_linked_to_project = list(
            Triple.objects.filter(
                subject=resource,
                predicate__uri__endswith='/properties/ereignis',
            ).values_list('object_id', flat=True)
        )
        if event_ids_linked_to_project:
            event_digital_ids = Triple.objects.filter(
                subject_id__in=event_ids_linked_to_project,
                predicate__uri__endswith='/properties/digitales-objekt',
            ).values_list('object_id', flat=True)
            digital_object_ids.update(event_digital_ids)

    if digital_object_ids:
        digital_files = S3FileObject.objects.filter(
            related_resource_id__in=list(digital_object_ids),
            status__in=HARVESTABLE_FILE_STATUSES,
            s3_key__isnull=False,
        ).exclude(s3_key="")

    event_ids = Triple.objects.filter(
        subject=resource,
        predicate__uri__endswith='/properties/ereignis',
    ).values_list('object_id', flat=True)

    event_files = S3FileObject.objects.none()
    if not is_digital_only:
        event_files = S3FileObject.objects.filter(
            related_resource_id__in=event_ids,
            status__in=HARVESTABLE_FILE_STATUSES,
            s3_key__isnull=False,
        ).exclude(s3_key="")

    files = list(direct_files)
    if is_digital_only and digital_files.exists():
        files.extend(
            list(
                digital_files.exclude(
                    id__in=direct_files.values('id')
                )
            )
        )
    if not is_digital_only:
        files.extend(
            list(
                event_files.exclude(
                    id__in=direct_files.values('id')
                ).exclude(
                    id__in=digital_files.values('id')
                )
            )
        )

    if not files:
        return None

    digital_objects: List[ProjectDigitalObject] = []
    for file_obj in files:
        fixity = parse_fixity(getattr(file_obj, 'sha256_checksum', None))
        digital_objects.append(
            ProjectDigitalObject(
                path=file_obj.s3_key,
                storage_key=file_obj.s3_key,
                file_name=file_obj.file_name,
                content_type=file_obj.content_type,
                size_bytes=file_obj.file_size_bytes,
                checksum=fixity.digest,
                checksum_algorithm=fixity.algorithm,
                checksum_provenance='s3' if fixity.digest else None,
                access_url=file_obj.s3_url,
            )
        )

    title = getattr(resource, 'value', None) or getattr(resource, 'name', None) or resource.uri

    return ProjectRecord(
        subject_id=str(resource.id),
        uri=resource.uri,
        title=title,
        digital_objects=digital_objects,
        institution_codes=[resource.organization.code] if resource.organization else [],
    )


def _oai_envelope(request: HttpRequest) -> ET._Element:
    nsmap = {
        None: OAI_NS,
        "xsi": XSI_NS,
    }

    oai = ET.Element(ET.QName(nsmap[None], "OAI-PMH"), nsmap=nsmap)
    oai.set(f"{{{XSI_NS}}}schemaLocation", " ".join(
            [
                "http://www.openarchives.org/OAI/2.0/",
                "http://www.openarchives.org/OAI/2.0/OAI-PMH.xsd",
            ]
        ),
    )

    response_date = ET.SubElement(oai, ET.QName(OAI_NS, "responseDate"))
    response_date.text = timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ")

    req = ET.SubElement(oai, ET.QName(OAI_NS, "request"))
    req.text = request.build_absolute_uri(REPO_BASEURL)
    return oai


def _error(oai: ET._Element, code: str, message: str) -> ET._Element:
    e = ET.SubElement(oai, "error", {"code": code})
    e.text = message
    return oai


def _xml_response(elem: ET._Element) -> HttpResponse:
    data = ET.tostring(elem, encoding="utf-8", xml_declaration=True)
    return HttpResponse(data, content_type="text/xml")

def _identify(oai: ET._Element, request: HttpRequest) -> ET._Element:
    request_elem = oai.find(f"{{{OAI_NS}}}request")
    if request_elem is not None and not request_elem.get("verb"):
        request_elem.set("verb", "Identify")
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
    snapshot_marker_from_token: Optional[str] = None
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
        snapshot_marker_from_token = token_data.get("snapshot")

    snapshot, harvestable_projects = _harvestable_snapshot_projects()
    snapshot_version = snapshot.generated_at.isoformat()

    if snapshot_marker_from_token and snapshot_marker_from_token != snapshot_version:
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


def _parse_from_datestamp(date_str: str) -> datetime:
    """Parse a 'from' datestamp into an inclusive datetime."""
    if 'T' in date_str:
        return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
    dt = datetime.strptime(date_str, '%Y-%m-%d').replace(tzinfo=dt_timezone.utc)
    return dt


def _parse_until_datestamp(date_str: str) -> datetime:
    """Parse an 'until' datestamp and return an exclusive upper bound."""
    if 'T' in date_str:
        base = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        return base + timedelta(seconds=1)
    base = datetime.strptime(date_str, '%Y-%m-%d').replace(tzinfo=dt_timezone.utc)
    return base + timedelta(days=1)


def _get_resources_queryset(
    set_spec: Optional[str] = None,
    from_date: Optional[str] = None,
    until_date: Optional[str] = None,
    metadata_prefix: Optional[str] = None,
    allowed_uris: Optional[Sequence[str]] = None,
):
    """Build a filtered queryset for harvestable resources."""
    # For both Dublin Core and METS: expose only project entities as primary records
    # Each project will have rich metadata assembled from its complete graph
    access_clause = Q(public_access_level=PublicAccessLevel.RESTRICTED) | (
        Q(public_access_level=PublicAccessLevel.PUBLIC) & Q(is_public_approved=True)
    )

    if allowed_uris is not None:
        uris = list(dict.fromkeys(allowed_uris))
        if not uris:
            return Resource.objects.none()
        queryset = (
            Resource.objects.filter(uri__in=uris)
            .filter(access_clause)
            .select_related('organization')
            .order_by('updated_at', 'id')
        )
    else:
        queryset = (
            Resource.objects.filter(
                Q(uri__regex=r'/entities/projekt/[0-9]+$') & access_clause
            )
            .select_related('organization')
            .order_by('updated_at', 'id')
        )

    queryset = _restrict_to_harvestable_files(queryset)

    # Filter by set (organization)
    if set_spec:
        queryset = queryset.filter(organization__code__iexact=set_spec, organization__is_active=True)

    # Temporal filtering with proper OAI-PMH date validation
    if from_date:
        try:
            from_dt = _parse_from_datestamp(from_date)
            queryset = queryset.filter(updated_at__gte=from_dt)
        except ValueError:
            pass  # Invalid date format, ignore

    if until_date:
        try:
            until_dt = _parse_until_datestamp(until_date)
            queryset = queryset.filter(updated_at__lt=until_dt)
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


def _build_record_header(resource: Resource) -> ET._Element:
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


def _candidate_projects_for_resource(
    resource: Resource,
    primary_project: Optional[OAIProject] = None,
) -> List[OAIProject]:
    """Return snapshot and fallback OAI projects in priority order."""

    candidates: List[OAIProject] = []
    seen: set[str] = set()

    if primary_project is not None:
        candidates.append(primary_project)
        seen.add(primary_project.uri)
    else:
        record = _get_snapshot_record(resource)
        if record:
            project = project_builder.from_project_record(record)
            candidates.append(project)
            seen.add(project.uri)

    fallback_record = _fallback_record_from_storage(resource)
    if fallback_record:
        fallback_project = project_builder.from_project_record(fallback_record)
        if fallback_project.uri not in seen:
            candidates.append(fallback_project)

    return candidates


def _harvestable_snapshot_projects() -> tuple[ProjectSnapshot, Dict[str, OAIProject]]:
    """Build a mapping of harvestable projects keyed by project URI."""

    snapshot = snapshot_service.get_cross_institutional_snapshot()
    harvestable: Dict[str, OAIProject] = {}

    for record in snapshot.projects:
        project = project_builder.from_project_record(record)
        if project.harvestable:
            harvestable[project.uri] = project

    org_counts = {}
    for proj in harvestable.values():
        org = proj.institution_code or 'unknown'
        org_counts[org] = org_counts.get(org, 0) + 1
    logger.info("OAI harvestable projects: %d total from snapshot, by org: %s", len(harvestable), dict(sorted(org_counts.items())))

    if not harvestable:
        fallback_records: List[ProjectRecord] = []
        fallback_resources = (
            Resource.objects.filter(
                s3fileobject__status__in=HARVESTABLE_FILE_STATUSES,
                s3fileobject__s3_key__isnull=False,
            )
            .exclude(s3fileobject__s3_key="")
            .distinct()
        )

        for resource in fallback_resources:
            record = _fallback_record_from_storage(resource)
            if not record:
                continue
            project = project_builder.from_project_record(record)
            if not project.harvestable:
                continue
            harvestable[project.uri] = project
            fallback_records.append(record)

        if fallback_records:
            snapshot = ProjectSnapshot(
                projects=list(snapshot.projects) + fallback_records,
                counts=snapshot.counts,
                generated_at=snapshot.generated_at,
            )

    return snapshot, harvestable


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
    """Return the reference as-is; S3 keys already encode the desired path."""
    return value


def _guess_mime_type(obj: Any) -> Optional[str]:
    """Derive a MIME type from explicit metadata or file extension."""
    content_type = getattr(obj, 'content_type', None)
    if content_type:
        return content_type

    candidates = [
        getattr(obj, 'file_name', None),
        getattr(obj, 'access_url', None),
        getattr(obj, 'path', None),
        getattr(obj, 'storage_key', None),
    ]
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


def _rights_metadata_from_status(status: Optional[str]) -> Optional[Dict[str, Any]]:
    """Return translation and disclaimers derived from a rights status literal."""
    if not status:
        return None

    normalized = status.strip()
    if not normalized:
        return None

    simplified = normalized.lower().replace('ß', 'ss')
    if 'frei' in simplified:
        return {
            "status_de": normalized,
            "status_en": _RIGHTS_STATUS_FREE_EN,
            "disclaimers_de": [_RIGHTS_DISCLAIMER_FREE_DE],
            "disclaimers_en": [_RIGHTS_DISCLAIMER_FREE_EN],
        }
    if 'gesch' in simplified:
        return {
            "status_de": normalized,
            "status_en": _RIGHTS_STATUS_PROTECTED_EN,
            "disclaimers_de": [_RIGHTS_DISCLAIMER_PROTECTED_DE],
            "disclaimers_en": [_RIGHTS_DISCLAIMER_PROTECTED_EN],
        }

    return None


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


def _default_rights_metadata(resource: Resource, record: ProjectRecord) -> Optional[Dict[str, Any]]:
    """Provide organization-specific fallback rights metadata when literals are absent."""
    org_code = (resource.organization.code or "").lower().strip() if resource.organization and resource.organization.code else None

    if org_code in {"khm", "hmt"}:
        status_de = getattr(record, "rights_status", None) or "Urheberrechtlich und/oder Leistungsschutzrechtlich geschützt"
        return {
            "status_de": status_de,
            "status_en": _RIGHTS_STATUS_PROTECTED_EN,
            "disclaimers_de": [_RIGHTS_DISCLAIMER_PROTECTED_DE],
            "disclaimers_en": [_RIGHTS_DISCLAIMER_PROTECTED_EN],
        }

    return None


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


def _build_dc_payload_from_project(project: OAIProject, resource: Resource) -> Dict[str, List[str]]:
    payload: Dict[str, List[str]] = {}

    record = project.record

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
        for actor in getattr(event, "actors", []) or []:
            actor_name = getattr(actor, "name", None)
            roles = [role for role in getattr(actor, "roles", []) or [] if role]
            if actor_name:
                if roles:
                    role_label = ", ".join(sorted(set(roles)))
                    _add_dc_value(payload, 'contributor', f"{actor_name} ({role_label})")
                else:
                    _add_dc_value(payload, 'contributor', actor_name)
            elif roles:
                _add_dc_value(payload, 'contributor', ", ".join(sorted(set(roles))))

    if record.year_range:
        _add_dc_value(payload, 'date', record.year_range)

    rights_meta = _rights_metadata_from_status(getattr(record, "rights_status", None))

    if resource.canonical_uri:
        _add_dc_value(payload, 'identifier', resource.canonical_uri)
    _add_dc_value(payload, 'identifier', resource.uri)
    _add_dc_value(payload, 'identifier', record.uri)

    if getattr(resource, 'updated_at', None):
        _add_dc_value(payload, 'dateSubmitted', _format_datestamp(resource.updated_at), namespace='dcterms')

    for code in record.institution_codes:
        _add_dc_value(payload, 'isPartOf', code.upper(), namespace='dcterms')
    for label in _collect_collection_labels(resource, record):
        _add_dc_value(payload, 'isPartOf', label, namespace='dcterms')

    if project.digital_objects:
        formats_added: set[str] = set(payload.get('dc:format', []))
        for obj in project.digital_objects:
            if obj.content_type:
                if obj.content_type not in formats_added:
                    _add_dc_value(payload, 'format', obj.content_type)
                    formats_added.add(obj.content_type)

        if not payload.get('dc:format'):
            for obj in project.digital_objects:
                guess = _guess_mime_type(obj)
                if guess and guess not in formats_added:
                    _add_dc_value(payload, 'format', guess)
                    formats_added.add(guess)

    if not payload.get('dc:language'):
        language = _default_language_for_resource(resource, record)
        if language:
            _add_dc_value(payload, 'language', language)

    license_rights: set[str] = set()
    for obj in project.digital_objects:
        license_info = getattr(obj, "license", None)
        if license_info and getattr(license_info, "rights_statement", None):
            normalized = str(license_info.rights_statement).strip()
            if normalized:
                license_rights.add(normalized)
    for rights_value in sorted(license_rights):
        _add_dc_value(payload, 'rights', rights_value)

    if not rights_meta:
        rights_meta = _default_rights_metadata(resource, record)

    if rights_meta:
        _add_dc_value(payload, 'rights', rights_meta.get("status_de"))
        _add_dc_value(payload, 'rights', rights_meta.get("status_en"))
        for text in rights_meta.get("disclaimers_de", []):
            _add_dc_value(payload, 'rights', text)
        for text in rights_meta.get("disclaimers_en", []):
            _add_dc_value(payload, 'rights', text)
    elif not payload.get('dc:rights'):
        rights = _rights_label_for_resource(resource)
        if rights:
            _add_dc_value(payload, 'rights', rights)

    return payload


def _build_dc_payload_from_record(record: ProjectRecord, resource: Resource) -> Dict[str, List[str]]:
    """Compatibility wrapper to build DC payloads from legacy ProjectRecord inputs."""

    project = project_builder.from_project_record(record)
    return _build_dc_payload_from_project(project, resource)


def _append_dc_metadata(metadata: ET._Element, dc_payload: Dict[str, List[str]]) -> ET._Element:
    dc_root = ET.SubElement(
        metadata,
        ET.QName(OAI_DC_NS, "dc"),
        nsmap={
            "oai_dc": OAI_DC_NS,
            "dc": DC_NS,
            "dcterms": DCTERMS_NS,
            "xsi": XSI_NS,
        },
    )
    dc_root.set(
        ET.QName(XSI_NS, "schemaLocation"),
        " ".join([
            OAI_DC_NS,
            "http://www.openarchives.org/OAI/2.0/oai_dc.xsd",
        ]),
    )

    for key, values in dc_payload.items():
        namespace, term = key.split(":", 1)
        ns_uri = DC_NS if namespace == 'dc' else DCTERMS_NS
        for value in values:
            ET.SubElement(dc_root, ET.QName(ns_uri, term)).text = value
    return dc_root


def _append_arkumu_identifier(dc_parent: ET._Element, resource: Resource) -> None:
    """Append Arkumu-specific DC identifier based on OAI header identifier."""
    identifier_value = _build_identifier(resource.uri)
    existing = [
        elem for elem in dc_parent.findall(ET.QName(DC_NS, "identifier"))
        if elem.text == identifier_value and elem.get(ET.QName(XML_NS, "type")) == "arkumu-ID"
    ]
    if existing:
        return

    identifier_elem = ET.SubElement(dc_parent, ET.QName(DC_NS, "identifier"))
    identifier_elem.text = identifier_value
    identifier_elem.set(ET.QName(XML_NS, "type"), "arkumu-ID")


def _build_mets_from_project(
    project: OAIProject,
    resource: Resource,
    dc_payload: Dict[str, List[str]],
) -> ET._Element:
    _register_rosetta_namespaces()

    record = project.record

    mets_root = ET.Element(ET.QName(METS_NS, "mets"), nsmap=METS_NSMAP)
    mets_root.set(f"{{{XSI_NS}}}schemaLocation", f"{METS_NS} {METS_SCHEMA_URL}")

    dmd_sec = ET.SubElement(mets_root, ET.QName(METS_NS, "dmdSec"), {"ID": "ie-dmd"})
    md_wrap = ET.SubElement(dmd_sec, ET.QName(METS_NS, "mdWrap"), {"MDTYPE": "DC"})
    xml_data = ET.SubElement(md_wrap, ET.QName(METS_NS, "xmlData"))
    dc_record = ET.SubElement(xml_data, ET.QName(DC_NS, "record"))
    for key, values in dc_payload.items():
        namespace, term = key.split(":", 1)
        ns_uri = DC_NS if namespace == 'dc' else DCTERMS_NS
        for value in values:
            ET.SubElement(dc_record, ET.QName(ns_uri, term)).text = value
    _append_arkumu_identifier(dc_record, resource)

    ie_amd = ET.SubElement(mets_root, ET.QName(METS_NS, "amdSec"), {"ID": "ie-amd"})
    tech_md = ET.SubElement(ie_amd, ET.QName(METS_NS, "techMD"), {"ID": "ie-amd-tech"})
    tech_wrap = ET.SubElement(tech_md, ET.QName(METS_NS, "mdWrap"), {"MDTYPE": "OTHER", "OTHERMDTYPE": "dnx"})
    tech_xml = ET.SubElement(tech_wrap, ET.QName(METS_NS, "xmlData"))
    tech_dnx = _create_dnx_element(tech_xml, "dnx")
    # Add objectIdentifier section (required by Rosetta)
    # Rosetta does not expect placeholder keys when no identifier is available.
    _create_dnx_element(tech_dnx, "section", {"id": "objectIdentifier"})

    rights_md = ET.SubElement(ie_amd, ET.QName(METS_NS, "rightsMD"), {"ID": "ie-amd-rights"})
    rights_wrap = ET.SubElement(rights_md, ET.QName(METS_NS, "mdWrap"), {"MDTYPE": "OTHER", "OTHERMDTYPE": "dnx"})
    rights_xml = ET.SubElement(rights_wrap, ET.QName(METS_NS, "xmlData"))
    rights_dnx = _create_dnx_element(rights_xml, "dnx")
    _create_dnx_element(rights_dnx, "section", {"id": "accessRightsPolicy"})

    source_md = ET.SubElement(ie_amd, ET.QName(METS_NS, "sourceMD"), {"ID": "ie-amd-source-OTHER"})
    source_wrap = ET.SubElement(
        source_md,
        ET.QName(METS_NS, "mdWrap"),
        {
            "MDTYPE": "OTHER",
            "OTHERMDTYPE": "RDF",
            "MIMETYPE": "application/rdf+xml",
        },
    )
    source_xml = ET.SubElement(source_wrap, ET.QName(METS_NS, "xmlData"))
    org_code = resource.organization.code if resource.organization else None
    try:
        rdf_service = CanonicalGraphService(org_code=org_code)
        rdf_element = build_rdf_graph(resource, graph_service=rdf_service)
        source_xml.append(rdf_element)
    except Exception:
        logger.exception("Failed to build RDF metadata for %s", getattr(resource, "uri", "unknown"))

    digiprov_md = ET.SubElement(ie_amd, ET.QName(METS_NS, "digiprovMD"), {"ID": "ie-amd-digiprov"})
    digiprov_wrap = ET.SubElement(digiprov_md, ET.QName(METS_NS, "mdWrap"), {"MDTYPE": "OTHER", "OTHERMDTYPE": "dnx"})
    digiprov_xml = ET.SubElement(digiprov_wrap, ET.QName(METS_NS, "xmlData"))
    _create_dnx_element(digiprov_xml, "dnx")

    harvestable_objects = [
        obj for obj in project.digital_objects
        if obj.harvestable and obj.preferred_location
    ]
    rep_groups = _group_digital_objects_for_rosetta(harvestable_objects)

    file_sec_entries: List[Dict[str, Any]] = []

    events_by_uri: Dict[str, ProjectEvent] = {}
    for event in record.events:
        if event.uri:
            events_by_uri[event.uri] = event

    event_file_map: Dict[str, ProjectEvent] = {}

    def _remember_event_mapping(key: Optional[str], event_obj: ProjectEvent) -> None:
        if not key:
            return
        normalized = key.strip()
        event_file_map.setdefault(normalized, event_obj)
        if normalized != key:
            event_file_map.setdefault(key, event_obj)

    if events_by_uri:
        event_files_qs = (
            S3FileObject.objects.filter(
                related_resource__uri__in=list(events_by_uri.keys()),
                status__in=HARVESTABLE_FILE_STATUSES,
            )
            .select_related('related_resource')
        )
        for file_obj in event_files_qs:
            related = getattr(file_obj, 'related_resource', None)
            related_uri = getattr(related, 'uri', None)
            if not related_uri:
                continue
            event_obj = events_by_uri.get(related_uri)
            if not event_obj:
                continue
            candidates = [
                getattr(file_obj, 's3_key', None),
                getattr(file_obj, 'original_path', None),
                getattr(file_obj, 'file_name', None),
            ]
            for candidate in candidates:
                _remember_event_mapping(candidate, event_obj)

    def _object_keys(obj: NormalizedDigitalObject) -> List[str]:
        keys: List[str] = []
        sources = [
            obj.storage_key,
            obj.original_path,
            obj.rosetta_path,
            obj.preferred_location,
            obj.file_name,
        ]
        for source in sources:
            if not source:
                continue
            stripped = source.strip()
            keys.append(stripped)
            if stripped != source:
                keys.append(source)
        return keys

    def _event_for_object(obj: NormalizedDigitalObject) -> Optional[ProjectEvent]:
        for candidate in _object_keys(obj):
            event_obj = event_file_map.get(candidate)
            if event_obj:
                return event_obj
        return None

    file_counter = 1

    for rep_index, (rep_type, objects) in enumerate(rep_groups, start=1):
        rep_id = f"rep{rep_index}"

        rep_amd = ET.SubElement(mets_root, ET.QName(METS_NS, "amdSec"), {"ID": f"{rep_id}-amd"})
        rep_tech = ET.SubElement(rep_amd, ET.QName(METS_NS, "techMD"), {"ID": f"{rep_id}-amd-tech"})
        rep_wrap = ET.SubElement(rep_tech, ET.QName(METS_NS, "mdWrap"), {"MDTYPE": "OTHER", "OTHERMDTYPE": "dnx"})
        rep_xml = ET.SubElement(rep_wrap, ET.QName(METS_NS, "xmlData"))
        rep_dnx = _create_dnx_element(rep_xml, "dnx")
        section = _create_dnx_element(rep_dnx, "section", {"id": "generalRepCharacteristics"})
        rec = _create_dnx_element(section, "record")
        _create_dnx_element(rec, "key", {"id": "preservationType"}, rep_type)
        _create_dnx_element(rec, "key", {"id": "usageType"}, "VIEW")

        rep_files: List[Dict[str, Any]] = []

        for file_index, obj in enumerate(objects, start=1):
            file_id = f"fid-{rep_index}-{file_index}"
            file_counter += 1
            preferred_location = obj.preferred_location or ""
            file_label_source = obj.file_name or preferred_location or obj.original_path or f"Digital Object {file_index}"
            label_normalized = _normalize_reference(file_label_source)
            file_label = label_normalized or file_label_source
            if obj.file_name:
                file_label = obj.file_name

            file_amd = ET.SubElement(mets_root, ET.QName(METS_NS, "amdSec"), {"ID": f"{file_id}-amd"})
            file_tech = ET.SubElement(file_amd, ET.QName(METS_NS, "techMD"), {"ID": f"{file_id}-amd-tech"})
            file_wrap = ET.SubElement(file_tech, ET.QName(METS_NS, "mdWrap"), {"MDTYPE": "OTHER", "OTHERMDTYPE": "dnx"})
            file_xml = ET.SubElement(file_wrap, ET.QName(METS_NS, "xmlData"))
            file_dnx = _create_dnx_element(file_xml, "dnx")
            characteristics_section = _create_dnx_element(file_dnx, "section", {"id": "objectCharacteristics"})
            characteristics_record = _create_dnx_element(characteristics_section, "record")
            _create_dnx_element(characteristics_record, "key", {"id": "objectType"}, "FILE")

            general_keys: List[tuple[str, str]] = []
            label_value = obj.file_name or file_label
            if label_value:
                general_keys.append(("label", label_value))
            if obj.file_name:
                general_keys.append(("fileOriginalName", obj.file_name))
            if preferred_location:
                general_keys.append(("fileOriginalPath", preferred_location))
            elif obj.storage_key:
                general_keys.append(("fileOriginalPath", obj.storage_key))
            elif obj.original_path:
                general_keys.append(("fileOriginalPath", obj.original_path))
            if obj.content_type:
                general_keys.append(("fileMIMEType", obj.content_type))
            if obj.size_bytes is not None:
                general_keys.append(("fileSizeBytes", str(obj.size_bytes)))

            if general_keys:
                general_section = _create_dnx_element(file_dnx, "section", {"id": "generalFileCharacteristics"})
                general_record = _create_dnx_element(general_section, "record")
                for key_id, value in general_keys:
                    _create_dnx_element(general_record, "key", {"id": key_id}, value)

            checksum_algorithm, checksum_value = obj.checksum_tuple()
            checksum_label = obj.checksum_label() if checksum_algorithm else None
            fallback_label = checksum_label or ("MD5" if obj.source == "s3" else "SHA-256")
            if checksum_value:
                fixity_section = _create_dnx_element(file_dnx, "section", {"id": "fileFixity"})
                fixity_record = _create_dnx_element(fixity_section, "record")
                _create_dnx_element(
                    fixity_record,
                    "key",
                    {"id": "fixityType"},
                    fallback_label,
                )
                _create_dnx_element(
                    fixity_record,
                    "key",
                    {"id": "fixityValue"},
                    checksum_value,
                )
                if checksum_label and checksum_label != fallback_label:
                    _create_dnx_element(
                        fixity_record,
                        "key",
                        {"id": "fixityAlgorithm"},
                        checksum_label,
                    )

            license_info = getattr(obj, "license", None)

            if license_info and license_info.uri:
                file_rights = ET.SubElement(file_amd, ET.QName(METS_NS, "rightsMD"), {"ID": f"{file_id}-amd-rights"})
                file_rights_wrap = ET.SubElement(file_rights, ET.QName(METS_NS, "mdWrap"), {"MDTYPE": "OTHER", "OTHERMDTYPE": "dnx"})
                file_rights_xml = ET.SubElement(file_rights_wrap, ET.QName(METS_NS, "xmlData"))
                file_rights_dnx = _create_dnx_element(file_rights_xml, "dnx")
                rights_section = _create_dnx_element(file_rights_dnx, "section", {"id": "linkingRightsStatementIdentifier"})
                rights_record = _create_dnx_element(rights_section, "record")
                _create_dnx_element(
                    rights_record,
                    "key",
                    {"id": "linkingRightsStatementIdentifierType"},
                    "URI",
                )
                _create_dnx_element(
                    rights_record,
                    "key",
                    {"id": "linkingRightsStatementIdentifierValue"},
                    license_info.uri,
                )

            file_source = ET.SubElement(file_amd, ET.QName(METS_NS, "sourceMD"), {"ID": f"{file_id}-amd-source-dc"})
            file_source_wrap = ET.SubElement(file_source, ET.QName(METS_NS, "mdWrap"), {"MDTYPE": "DC"})
            file_source_xml = ET.SubElement(file_source_wrap, ET.QName(METS_NS, "xmlData"))
            file_source_record = ET.SubElement(file_source_xml, ET.QName(DC_NS, "record"))

            if obj.uuid:
                identifier_elem = ET.SubElement(file_source_record, ET.QName(DC_NS, "identifier"))
                identifier_elem.text = obj.uuid
                identifier_elem.set(ET.QName(XML_NS, "type"), "Digital-Object-ID")

            file_title = obj.file_name or file_label
            if file_title:
                title_elem = ET.SubElement(file_source_record, ET.QName(DC_NS, "title"))
                title_elem.text = file_title
                title_elem.set(ET.QName(XML_NS, "type"), "file-name")

            if obj.genesis_type:
                genesis_elem = ET.SubElement(file_source_record, ET.QName(DC_NS, "type"))
                genesis_elem.text = obj.genesis_type
                genesis_elem.set(ET.QName(XML_NS, "type"), "genesis-type")

            if obj.media_type:
                media_elem = ET.SubElement(file_source_record, ET.QName(DC_NS, "type"))
                media_elem.text = obj.media_type
                media_elem.set(ET.QName(XML_NS, "type"), "media-type")

            if obj.content_type:
                mimetype_elem = ET.SubElement(file_source_record, ET.QName(DC_NS, "type"))
                mimetype_elem.text = obj.content_type
                mimetype_elem.set(ET.QName(XML_NS, "type"), "mimetype")

            if obj.significant_properties_de:
                sig_de_elem = ET.SubElement(file_source_record, ET.QName(DC_NS, "description"))
                sig_de_elem.text = obj.significant_properties_de
                sig_de_elem.set(ET.QName(XML_NS, "type"), "significant-properties-german")

            if obj.significant_properties_en:
                sig_en_elem = ET.SubElement(file_source_record, ET.QName(DC_NS, "description"))
                sig_en_elem.text = obj.significant_properties_en
                sig_en_elem.set(ET.QName(XML_NS, "type"), "significant-properties-english")

            if license_info and license_info.label_de:
                lic_de_elem = ET.SubElement(file_source_record, ET.QName(DCTERMS_NS, "license"))
                lic_de_elem.text = license_info.label_de
                lic_de_elem.set(ET.QName(XML_NS, "lang"), "ger")

            if license_info and license_info.label_en:
                lic_en_elem = ET.SubElement(file_source_record, ET.QName(DCTERMS_NS, "license"))
                lic_en_elem.text = license_info.label_en
                lic_en_elem.set(ET.QName(XML_NS, "lang"), "eng")

            if license_info and license_info.uri:
                lic_uri_elem = ET.SubElement(file_source_record, ET.QName(DCTERMS_NS, "license"))
                lic_uri_elem.text = license_info.uri
                lic_uri_elem.set(ET.QName(XML_NS, "type"), "dcterms:URI")

            raw_path = (
                obj.storage_key
                or obj.original_path
                or obj.rosetta_path
                or preferred_location
            )
            path_parts: List[str] = []
            if raw_path:
                path_parts = [part for part in raw_path.strip('/').split('/') if part]
            if len(path_parts) > 1:
                folder_segments = [
                    segment
                    for segment in path_parts[:-1]
                    if segment and segment.casefold() != "data"
                ]
            else:
                folder_segments = []

            rep_files.append({
                "file_id": file_id,
                "label": file_label,
                "object": obj,
                "rep_id": rep_id,
                "rep_type": rep_type,
                "event": _event_for_object(obj),
                "folders": folder_segments,
                "order": file_index,
            })
        file_sec_entries.append({
            "rep_id": rep_id,
            "rep_type": rep_type,
            "files": rep_files,
        })

    file_sec = ET.SubElement(mets_root, ET.QName(METS_NS, "fileSec"))

    project_title = record.title or record.subtitle or record.uri or "Project"

    for entry in file_sec_entries:
        rep_id = entry["rep_id"]
        rep_type = entry["rep_type"]
        file_grp = ET.SubElement(
            file_sec,
            ET.QName(METS_NS, "fileGrp"),
            {
                "USE": "VIEW",
                "ID": rep_id,
                "ADMID": f"{rep_id}-amd",
            },
        )

        for position, file_info in enumerate(entry["files"], start=1):
            obj = file_info["object"]
            file_id = file_info["file_id"]
            attrs: Dict[str, Any] = {
                "ID": file_id,
                "ADMID": f"{file_id}-amd",
            }
            if obj.content_type:
                attrs["MIMETYPE"] = obj.content_type
            # Rosetta profile forbids CHECKSUM attributes on mets:file; fixity lives in DNX

            file_elem = ET.SubElement(file_grp, ET.QName(METS_NS, "file"), attrs)
            href = obj.preferred_location or obj.access_url or ""
            normalized_href = _normalize_reference(href)
            if normalized_href:
                href = normalized_href
            if href:
                flocat_attrs = {
                    "LOCTYPE": "URL",
                    f"{{{XLINK_NS}}}href": href,
                    f"{{{XLINK_NS}}}type": "simple",
                }
                ET.SubElement(file_elem, ET.QName(METS_NS, "FLocat"), flocat_attrs)

        struct_map = ET.SubElement(
            mets_root,
            ET.QName(METS_NS, "structMap"),
            {"ID": f"{rep_id}-1", "TYPE": "LOGICAL"},
        )

        # Root div has no attributes per Rosetta example
        project_div = ET.SubElement(
            struct_map,
            ET.QName(METS_NS, "div"),
        )

        # Representation div also simplified per Rosetta example
        rep_div = project_div

        def _event_key(event_obj: Optional[ProjectEvent]) -> str:
            if event_obj is None:
                return "__project__"
            if event_obj.uri:
                return f"uri:{event_obj.uri}"
            if event_obj.id:
                return f"id:{event_obj.id}"
            if event_obj.name:
                return f"name:{event_obj.name}"
            return f"event:{id(event_obj)}"

        event_order: List[str] = []
        files_by_event: Dict[str, List[Dict[str, Any]]] = {}
        event_meta: Dict[str, Optional[ProjectEvent]] = {}

        for event in record.events:
            key = _event_key(event)
            event_order.append(key)
            files_by_event.setdefault(key, [])
            event_meta[key] = event

        for file_info in entry["files"]:
            event_obj = file_info.get("event")
            key = _event_key(event_obj)
            if key not in files_by_event:
                event_order.append(key)
            files_by_event.setdefault(key, []).append(file_info)
            event_meta.setdefault(key, event_obj)

        folder_nodes: Dict[str, Dict[tuple[str, ...], ET._Element]] = {}

        def _event_label(event_obj: Optional[ProjectEvent]) -> str:
            if event_obj is None:
                return "Projektdateien"
            return event_obj.name or event_obj.location or event_obj.uri or "Ereignis"

        event_position = 1
        for key in event_order:
            event_files = files_by_event.get(key)
            if not event_files:
                continue
            event_obj = event_meta.get(key)
            event_label = _event_label(event_obj)
            # Event div - simplified per Rosetta example (no ORDER on intermediate divs)
            event_div = ET.SubElement(
                rep_div,
                ET.QName(METS_NS, "div"),
                {
                    "LABEL": event_label,
                    "ORDERLABEL": event_label,
                },
            )
            folder_nodes[key] = {}
            event_position += 1

            for file_info in event_files:
                parent = event_div
                folder_key_prefix: List[str] = []
                for segment in file_info.get("folders", []):
                    folder_key_prefix.append(segment)
                    folder_key = tuple(folder_key_prefix)
                    existing = folder_nodes[key].get(folder_key)
                    if not existing:
                        existing = ET.SubElement(
                            parent,
                            ET.QName(METS_NS, "div"),
                            {
                                "LABEL": segment,
                                "ORDERLABEL": segment,
                            },
                        )
                        folder_nodes[key][folder_key] = existing
                    parent = existing

                # File div per Rosetta example - TYPE="FILE", LABEL, ORDERLABEL (no ORDER)
                file_div = ET.SubElement(
                    parent,
                    ET.QName(METS_NS, "div"),
                    {
                        "TYPE": "FILE",
                        "LABEL": file_info["label"],
                        "ORDERLABEL": file_info["label"],
                    },
                )
                ET.SubElement(file_div, ET.QName(METS_NS, "fptr"), {"FILEID": file_info["file_id"]})
    return mets_root


def _build_metadata_element(
    resource: Resource,
    metadata_prefix: str,
    project_hint: Optional[OAIProject] = None,
) -> ET._Element:
    """Build metadata element for different formats."""
    metadata = ET.Element("metadata")

    projects = _candidate_projects_for_resource(resource, primary_project=project_hint)

    if not projects:
        logger.warning("No snapshot record found for %s", getattr(resource, 'uri', 'unknown'))
        return metadata

    if metadata_prefix == "oai_dc":
        project = projects[0]
        dc_payload = _build_dc_payload_from_project(project, resource)
        dc_root = _append_dc_metadata(metadata, dc_payload)
        _append_arkumu_identifier(dc_root, resource)
    elif metadata_prefix == "mets":
        for project in projects:
            if not project.harvestable:
                continue

            dc_payload = _build_dc_payload_from_project(project, resource)
            mets_root = _build_mets_from_project(project, resource, dc_payload)

            candidate_wrapper = ET.Element("metadata")
            candidate_wrapper.append(ET.fromstring(ET.tostring(mets_root)))

            validation = rosetta_mets_validator.validate_metadata_element(
                candidate_wrapper,
                resource_uri=getattr(resource, "uri", None),
            )

            if not validation.is_valid:
                issues = getattr(validation, "issues", [])
                if not isinstance(issues, (list, tuple)):
                    issues = [issues] if issues else []
                messages: List[str] = []
                for issue in issues:
                    if issue is None:
                        continue
                    message = getattr(issue, "message", None)
                    messages.append(str(message) if message is not None else str(issue))
                issue_summary = "; ".join(messages) or "unknown reason"
                logger.warning(
                    "Generated METS payload failed validation for %s: %s; trying next candidate",
                    getattr(resource, "uri", "unknown"),
                    issue_summary,
                )
                continue

            mets_bytes = ET.tostring(mets_root, encoding="utf-8")
            metadata.append(ET.fromstring(mets_bytes))
            break
    elif metadata_prefix == "rdf":
        rdf_service = CanonicalGraphService(
            org_code=resource.organization.code if resource.organization else None
        )
        rdf_element = build_rdf_graph(resource, graph_service=rdf_service)
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


def _list_records(oai: ET._Element, params) -> ET._Element:
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
        snapshot_marker_from_token = token_data.get("snapshot")

    snapshot, harvestable_projects = _harvestable_snapshot_projects()
    snapshot_version = snapshot.generated_at.isoformat()

    if snapshot_marker_from_token and snapshot_marker_from_token != snapshot_version:
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
    )

    return oai


@csrf_exempt
@require_http_methods(["GET", "POST"])
def oai_endpoint(request: HttpRequest) -> HttpResponse:
    auth_response = _enforce_basic_auth(request)
    if auth_response is not None:
        return auth_response

    try:
        params = request.GET.copy()
        if request.method == "POST":
            post_data = request.POST.copy()
            for key in post_data:
                params.setlist(key, post_data.getlist(key))

        verb = params.get("verb", "").strip()
        oai = _oai_envelope(request)

        request_elem = oai.find("request")
        if request_elem is not None:
            if verb:
                request_elem.set("verb", verb)
            for param, value in params.items():
                if param == "verb":
                    continue
                if value:
                    request_elem.set(param, value)

        # Check for illegal arguments first
        valid_verbs = ["Identify", "ListMetadataFormats", "ListSets", "ListIdentifiers", "ListRecords", "GetRecord"]
        all_args = set(params.keys())

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
            identifier = params.get("identifier")
            return _xml_response(_list_metadata_formats(oai, identifier))

        if verb == "ListSets":
            return _xml_response(_list_sets(oai))

        if verb == "ListIdentifiers":
            # Exclusive argument checking
            has_resumption_param = "resumptionToken" in params
            if has_resumption_param and len([k for k in params.keys() if k != "verb" and k != "resumptionToken"]) > 0:
                return _xml_response(_error(oai, "badArgument", "resumptionToken cannot be combined with other arguments"))

            # Required argument checking
            if not has_resumption_param and not params.get("metadataPrefix"):
                return _xml_response(_error(oai, "badArgument", "metadataPrefix is required"))

            return _xml_response(_list_identifiers(oai, params))

        if verb == "ListRecords":
            # Exclusive argument checking
            has_resumption_param = "resumptionToken" in params
            if has_resumption_param and len([k for k in params.keys() if k != "verb" and k != "resumptionToken"]) > 0:
                return _xml_response(_error(oai, "badArgument", "resumptionToken cannot be combined with other arguments"))

            # Required argument checking
            if not has_resumption_param and not params.get("metadataPrefix"):
                return _xml_response(_error(oai, "badArgument", "metadataPrefix is required"))

            return _xml_response(_list_records(oai, params))

        if verb == "GetRecord":
            identifier = params.get("identifier")
            metadata_prefix = params.get("metadataPrefix")
            if not identifier or not metadata_prefix:
                return _xml_response(_error(oai, "badArgument", "identifier and metadataPrefix are required"))
            if metadata_prefix not in SUPPORTED_METADATA_FORMATS:
                return _xml_response(_error(oai, "cannotDisseminateFormat", "Only oai_dc and mets are supported"))

            # Resolve Arkumu resource by identifier
            resource_uri = _parse_identifier(identifier)

            access_clause = Q(public_access_level=PublicAccessLevel.RESTRICTED) | (
                Q(public_access_level=PublicAccessLevel.PUBLIC) & Q(is_public_approved=True)
            )

            # Filter to only project entities
            resource_qs = (
                Resource.objects.filter(
                    uri=resource_uri,
                    uri__regex=r'/entities/projekt/[0-9]+$',
                )
                .filter(access_clause)
                .select_related("organization")
            )
            resource = _restrict_to_harvestable_files(resource_qs).first()

            if not resource:
                fallback_qs = (
                    Resource.objects.filter(uri=resource_uri)
                    .filter(access_clause)
                    .select_related("organization")
                )
                resource = _restrict_to_harvestable_files(fallback_qs).first()

            if not resource:
                return _xml_response(_error(oai, "idDoesNotExist", "Identifier not found"))

            if not resource.organization:
                return _xml_response(_error(oai, "idDoesNotExist", "Resource has no organization"))

            snapshot = snapshot_service.get_cross_institutional_snapshot()
            snapshot_marker = snapshot.generated_at.isoformat()
            project_hint: Optional[OAIProject] = None
            snapshot_record = snapshot_service.get_record_by_uri(resource.uri)
            if snapshot_record:
                project_hint = project_builder.from_project_record(snapshot_record)

            # Check cache first
            cached_record = _get_cached_record(
                resource,
                metadata_prefix,
                snapshot_marker=snapshot_marker,
            )
            if cached_record and metadata_prefix == 'mets' and not _metadata_xml_is_valid(
                cached_record['metadata'],
                resource_uri=getattr(resource, 'uri', None),
            ):
                cached_record = None

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
            metadata = _build_metadata_element(
                resource,
                metadata_prefix,
                project_hint=project_hint,
            )

            if metadata_prefix == 'mets' and not _metadata_element_is_valid(
                metadata,
                resource_uri=getattr(resource, 'uri', None),
            ):
                return _xml_response(_error(oai, "idDoesNotExist", "Identifier not available for METS dissemination"))

            record.append(metadata)

            # Cache the record for future requests
            _cache_record(
                resource,
                metadata_prefix,
                ET.tostring(header, encoding="unicode"),
                ET.tostring(metadata, encoding="unicode"),
                snapshot_marker=snapshot_marker,
            )

            return _xml_response(oai)

        # This should never be reached due to earlier validation
        return _xml_response(_error(oai, "badVerb", "Unsupported verb"))

    except Exception as e:
        # Global exception handler for any unexpected errors
        logger.exception("Unhandled error in OAI endpoint", exc_info=e)
        oai = _oai_envelope(request)
        return _xml_response(_error(oai, "internalError", f"Internal server error: {str(e)}"))
