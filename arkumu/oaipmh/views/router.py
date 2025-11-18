"""HTTP router and endpoint definitions for Arkumu OAI-PMH views."""

from __future__ import annotations

import logging
from typing import Optional

from django.db.models import Q
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from lxml import etree as ET

from arkumu.metadata.models.resource import PublicAccessLevel, Resource
from arkumu.oaipmh.oai_project import OAIProject
from arkumu.users.mixins import general_login_required

from arkumu.oaipmh import schema_utils
from .config import (
    OAI_NS,
    SUPPORTED_METADATA_FORMATS,
    XSI_NS,
    _curated_media_links_active,
    _db_mode_enabled,
    _decode_basic_credentials,
    _enforce_basic_auth,
    _force_curated_links,
    _force_db_mode,
    _force_tailored_mode,
    _tailored_mode_enabled,
)
from .harvest import _project_type_filter, _restrict_to_harvestable_files
from .metadata import (
    _build_metadata_element,
    _build_record_header,
    _metadata_element_is_valid,
    _metadata_xml_is_valid,
)
from .projects import (
    _build_project_hint_from_resource,
    project_builder,
    snapshot_service,
)
from .base import (
    _cache_record,
    _error,
    _get_cached_record,
    _identify,
    _list_identifiers,
    _list_metadata_formats,
    _list_records,
    _list_sets,
    _parse_identifier,
)
from arkumu.oaipmh.tailored_probe import (
    TailoredProbeError,
    TailoredProbeOptions,
    collect_probe_stats,
)

logger = logging.getLogger(__name__)

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
    req.text = request.build_absolute_uri(request.path)
    return oai
def _xml_response(elem: ET._Element) -> HttpResponse:
    data = ET.tostring(elem, encoding="utf-8", xml_declaration=True)
    return HttpResponse(data, content_type="text/xml")


def _query_flag(request: HttpRequest, name: str, default: bool = False) -> bool:
    raw_value = request.GET.get(name)
    if raw_value is None:
        return default
    return str(raw_value).lower() in {"1", "true", "yes", "on"}


def _build_probe_options_from_request(request: HttpRequest) -> TailoredProbeOptions:
    base_url = request.GET.get("base_url")
    if base_url:
        base_url = base_url.rstrip("/")
    else:
        base_url = request.build_absolute_uri("/").rstrip("/")

    set_spec = request.GET.get("set") or request.GET.get("set_spec")
    from_date = request.GET.get("from") or request.GET.get("from_date")
    until_date = request.GET.get("until") or request.GET.get("until_date")

    credentials = _decode_basic_credentials(request.META.get("HTTP_AUTHORIZATION", ""))
    basic_auth = None
    if credentials:
        basic_auth = f"{credentials[0]}:{credentials[1]}"

    return TailoredProbeOptions(
        base_url=base_url,
        verb=request.GET.get("verb", "ListIdentifiers"),
        metadata_prefix=request.GET.get("metadataPrefix", "oai_dc"),
        set_spec=set_spec,
        from_date=from_date,
        until_date=until_date,
        basic_auth=basic_auth,
        internal_bypass=request.META.get("HTTP_X_INTERNAL_OAI_BYPASS") == "1",
        pause_for_dataset_change=_query_flag(request, "pause_for_dataset_change"),
        run_tailored_resume=not _query_flag(request, "skip_tailored_resume"),
        run_db_check=not _query_flag(request, "skip_db"),
        run_snapshot_check=not _query_flag(request, "skip_snapshot"),
    )
def _handle_oai_request(request: HttpRequest) -> HttpResponse:
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

            return _xml_response(_list_records(oai, params, request))

        if verb == "GetRecord":
            identifier = params.get("identifier")
            metadata_prefix = params.get("metadataPrefix")
            if not identifier or not metadata_prefix:
                return _xml_response(_error(oai, "badArgument", "identifier and metadataPrefix are required"))
            if metadata_prefix not in SUPPORTED_METADATA_FORMATS:
                return _xml_response(_error(oai, "cannotDisseminateFormat", "Only oai_dc and mets are supported"))

            # Resolve Arkumu resource by identifier
            resource_uri = _parse_identifier(identifier)

            if _tailored_mode_enabled():
                from . import tailored

                return _xml_response(
                    tailored._get_record_tailored(
                        oai,
                        resource_uri=resource_uri,
                        metadata_prefix=metadata_prefix,
                        request=request,
                    )
                )

            access_clause = Q(public_access_level=PublicAccessLevel.RESTRICTED) | (
                Q(public_access_level=PublicAccessLevel.PUBLIC) & Q(is_public_approved=True)
            )

            db_mode_active = _db_mode_enabled()

            def _project_from_resource(res: Optional[Resource]) -> Optional[OAIProject]:
                if not res:
                    return None
                if db_mode_active:
                    return _build_project_hint_from_resource(res)
                record = snapshot_service.get_record_by_uri(res.uri)
                if not record:
                    return None
                return project_builder.from_project_record(
                    record,
                    skip_shared_event_filter=_db_mode_enabled(),
                    skip_format_exclusion=_db_mode_enabled(),
                    use_curated_media_links=_curated_media_links_active(),
                )

            project_type_clause = _project_type_filter()

            # Filter to only project entities
            resource_qs = (
                Resource.objects.filter(uri=resource_uri)
                .filter(access_clause)
                .select_related("organization")
            )
            if project_type_clause is not None:
                resource_qs = resource_qs.filter(project_type_clause).distinct()
            else:
                resource_qs = resource_qs.filter(uri__regex=r'/entities/projekt/[0-9]+$')
            resource = resource_qs.first()

            snapshot_marker: Optional[str] = None
            if not db_mode_active:
                snapshot = snapshot_service.get_cross_institutional_snapshot()
                snapshot_marker = snapshot.generated_at.isoformat()
            project_hint: Optional[OAIProject] = None

            if resource:
                project_candidate = _project_from_resource(resource)
                if project_candidate and project_candidate.harvestable:
                    project_hint = project_candidate
                else:
                    resource = None

            if resource is None:
                restricted = _restrict_to_harvestable_files(resource_qs)
                resource = restricted.first()
                if resource:
                    project_hint = project_hint or _project_from_resource(resource)

            if not resource:
                fallback_qs = (
                    Resource.objects.filter(uri=resource_uri)
                    .filter(access_clause)
                    .select_related("organization")
                )
                fallback_resource = fallback_qs.first()
                if fallback_resource:
                    fallback_project = _project_from_resource(fallback_resource)
                    if fallback_project and fallback_project.harvestable:
                        resource = fallback_resource
                        project_hint = fallback_project
                if not resource:
                    resource = _restrict_to_harvestable_files(fallback_qs).first()
                    if resource:
                        project_hint = project_hint or _project_from_resource(resource)

            if not resource:
                return _xml_response(_error(oai, "idDoesNotExist", "Identifier not found"))

            if not resource.organization:
                return _xml_response(_error(oai, "idDoesNotExist", "Resource has no organization"))

            if project_hint is None:
                project_hint = _project_from_resource(resource)

            if db_mode_active:
                marker_source = getattr(resource, "updated_at", None) or timezone.now()
                snapshot_marker = f"db:{marker_source.isoformat()}"

            if snapshot_marker is None:
                snapshot_marker = timezone.now().isoformat()

            # Check cache first
            cached_record = _get_cached_record(
                resource,
                metadata_prefix,
                snapshot_marker=snapshot_marker,
                cursor_marker=snapshot_marker,
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
                request=request,
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
                cursor_marker=snapshot_marker,
            )

            return _xml_response(oai)

        # This should never be reached due to earlier validation
        return _xml_response(_error(oai, "badVerb", "Unsupported verb"))

    except Exception as e:
        # Global exception handler for any unexpected errors
        logger.exception("Unhandled error in OAI endpoint", exc_info=e)
        oai = _oai_envelope(request)
        return _xml_response(_error(oai, "internalError", f"Internal server error: {str(e)}"))
@csrf_exempt
@require_http_methods(["GET", "POST"])
def oai_endpoint(request: HttpRequest) -> HttpResponse:
    """Snapshot-based OAI endpoint - always uses pre-built snapshots, never DB mode."""
    with _force_db_mode(False):
        return _handle_oai_request(request)
@general_login_required
@csrf_exempt
@require_http_methods(["GET", "POST"])
def oai_db_endpoint(request: HttpRequest) -> HttpResponse:
    with _force_db_mode(True):
        return _handle_oai_request(request)
@general_login_required
@csrf_exempt
@require_http_methods(["GET", "POST"])
def oai_tailored_endpoint(request: HttpRequest) -> HttpResponse:
    with _force_db_mode(True), _force_curated_links(True), _force_tailored_mode(True):
        return _handle_oai_request(request)


@csrf_exempt
@require_http_methods(["GET"])
def oai_tailored_stats(request: HttpRequest) -> HttpResponse:
    """Return JSON stats summarizing tailored OAI resumption token checks."""

    auth_response = _enforce_basic_auth(request)
    if auth_response is not None:
        return auth_response

    try:
        options = _build_probe_options_from_request(request)
        stats = collect_probe_stats(options)
    except TailoredProbeError as exc:
        return JsonResponse({"error": str(exc)}, status=502)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Failed to assemble tailored OAI stats", exc_info=exc)
        return JsonResponse({"error": "internal server error"}, status=500)

    return JsonResponse(stats.to_dict())
@general_login_required
@require_http_methods(["GET"])
def oai_schema_download(request: HttpRequest, snapshot: str, variant: str, ext: str) -> HttpResponse:
    snapshot_info = schema_utils.get_snapshot(snapshot)
    if not snapshot_info:
        raise Http404("Schema snapshot not found.")
    fmt = schema_utils.format_from_extension(ext)
    variant_key = schema_utils.resolve_variant_key(variant)
    if not fmt or not variant_key:
        raise Http404("Unknown schema variant or format.")
    try:
        file_path = snapshot_info.file_path(variant_key, fmt)
    except FileNotFoundError:
        raise Http404("Schema file is unavailable.")

    content_type = schema_utils.SCHEMA_FORMATS[fmt]["content_type"]
    response = FileResponse(file_path.open("rb"), content_type=content_type)
    response["Content-Disposition"] = f'inline; filename="{file_path.name}"'
    response["Cache-Control"] = "public, max-age=3600"
    return response
