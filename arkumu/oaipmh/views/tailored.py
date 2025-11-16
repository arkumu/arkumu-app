"""Tailored OAI-PMH helpers extracted from the monolithic view module."""

from __future__ import annotations

from typing import Dict, List, Optional

from django.db.models import DateTimeField, Value, F, Max
from django.db.models.functions import Coalesce, Greatest
from django.http import HttpRequest
from django.utils import timezone
from lxml import etree as ET

from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.oaipmh.oai_project import OAIProject

from . import base
from .config import _TAILORED_MIN_DATETIME
from .base import _cache_record, _get_cached_record
from .harvest import (
    HarvestPageResult,
    _apply_cursor_filter,
    _dataset_marker_for_queryset,
    _project_type_filter,
    _format_cursor_position,
    _parse_cursor_position,
    _parse_from_datestamp,
    _parse_until_datestamp,
)
from .metadata import (
    _build_metadata_element,
    _build_record_header,
    _metadata_element_is_valid,
    _metadata_xml_is_valid,
)
from .projects import _build_project_hint_from_resource
from .router import _error

__all__ = [
    "_tailored_resources_queryset",
    "_tailored_harvestable_page",
    "_list_identifiers_tailored",
    "_list_records_tailored",
    "_get_record_tailored",
]


def _tailored_resources_queryset(
    set_spec: Optional[str] = None,
    from_date: Optional[str] = None,
    until_date: Optional[str] = None,
):
    """Build queryset limited to curated, approved projects for tailored OAI harvests."""

    project_type_clause = _project_type_filter()
    queryset = (
        Resource.objects.filter(
            resource_type=ResourceType.ENTITY,
            organization__is_active=True,
            oai_media_links__isnull=False,
            oai_publication__is_approved=True,
        )
        .select_related("organization", "oai_publication")
    )
    if project_type_clause is not None:
        queryset = queryset.filter(project_type_clause).distinct()
    else:
        queryset = queryset.filter(uri__regex=r'/entities/projekt/[0-9]+$')

    queryset = queryset.annotate(latest_link_update=Max("oai_media_links__updated_at"))
    effective_expr = Greatest(
        F("updated_at"),
        Coalesce(
            F("oai_publication__updated_at"),
            Value(_TAILORED_MIN_DATETIME, output_field=DateTimeField()),
        ),
        Coalesce(
            F("latest_link_update"),
            Value(_TAILORED_MIN_DATETIME, output_field=DateTimeField()),
        ),
    )
    queryset = queryset.annotate(effective_datestamp=effective_expr).order_by("effective_datestamp", "id")

    if set_spec:
        queryset = queryset.filter(organization__code__iexact=set_spec)

    if from_date:
        try:
            from_dt = _parse_from_datestamp(from_date)
            queryset = queryset.filter(effective_datestamp__gte=from_dt)
        except ValueError:
            pass

    if until_date:
        try:
            until_dt = _parse_until_datestamp(until_date)
            queryset = queryset.filter(effective_datestamp__lt=until_dt)
        except ValueError:
            pass

    return queryset


def _has_more_tailored_harvestables(queryset, cursor_position: Optional[str]) -> bool:
    cursor_state = _parse_cursor_position(cursor_position)
    if cursor_state is None:
        return False

    ordered = queryset.order_by("effective_datestamp", "id")
    lookahead_qs = _apply_cursor_filter(
        ordered,
        cursor_state,
        field_name="effective_datestamp",
    )
    iterator = lookahead_qs.iterator(chunk_size=100)
    for resource in iterator:
        project_hint = _build_project_hint_from_resource(resource)
        if project_hint and project_hint.harvestable:
            return True
    return False


def _tailored_harvestable_page(
    queryset,
    *,
    cursor_position: Optional[str],
    page_size: int,
    include_hints: bool,
) -> HarvestPageResult:
    ordered = queryset.order_by("effective_datestamp", "id")
    ordered = _apply_cursor_filter(
        ordered,
        _parse_cursor_position(cursor_position),
        field_name="effective_datestamp",
    )

    iterator = ordered.iterator(chunk_size=max(page_size * 10, 100))
    resources: List[Resource] = []
    project_hints: Dict[str, OAIProject] = {}
    last_cursor_position = cursor_position

    for resource in iterator:
        last_cursor_position = _format_cursor_position(
            resource,
            field_name="effective_datestamp",
        )
        project_hint = _build_project_hint_from_resource(resource)
        if not project_hint or not project_hint.harvestable:
            continue
        if include_hints:
            project_hints[resource.uri] = project_hint
        resources.append(resource)
        if len(resources) == page_size:
            break

    has_more = False
    if resources:
        has_more = _has_more_tailored_harvestables(ordered, last_cursor_position)

    return HarvestPageResult(
        resources=resources,
        project_hints=project_hints,
        has_more=has_more,
        cursor_position=last_cursor_position,
    )


def _list_identifiers_tailored(
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
    queryset = _tailored_resources_queryset(
        set_spec=set_spec,
        from_date=from_date,
        until_date=until_date,
    )
    cursor_marker = _dataset_marker_for_queryset(queryset, field_name="effective_datestamp")

    if cursor_marker_from_token and cursor_marker_from_token != cursor_marker:
        return _error(oai, "badResumptionToken", "Dataset has changed; restart harvesting")

    page_size = base.resumption_service.page_size
    page = _tailored_harvestable_page(
        queryset,
        cursor_position=cursor_position_from_token,
        page_size=page_size,
        include_hints=False,
    )
    resources = page.resources

    if offset == 0 and not resources:
        return _error(oai, "noRecordsMatch", "No records found matching the criteria")

    list_identifiers = ET.SubElement(oai, "ListIdentifiers")
    for resource in resources:
        header = _build_record_header(resource)
        list_identifiers.append(header)

    resumption_token_value = None
    if page.has_more:
        next_offset = offset + len(resources)
        resumption_token_value = base.resumption_service.create_token(
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

    return oai


def _list_records_tailored(
    oai: ET._Element,
    *,
    metadata_prefix: str,
    set_spec: Optional[str],
    from_date: Optional[str],
    until_date: Optional[str],
    offset: int,
    cursor_marker_from_token: Optional[str],
    cursor_position_from_token: Optional[str],
    request: HttpRequest,
) -> ET._Element:
    queryset = _tailored_resources_queryset(
        set_spec=set_spec,
        from_date=from_date,
        until_date=until_date,
    )
    cursor_marker = _dataset_marker_for_queryset(queryset, field_name="effective_datestamp")

    if cursor_marker_from_token and cursor_marker_from_token != cursor_marker:
        return _error(oai, "badResumptionToken", "Dataset has changed; restart harvesting")

    page_size = base.resumption_service.page_size
    page = _tailored_harvestable_page(
        queryset,
        cursor_position=cursor_position_from_token,
        page_size=page_size,
        include_hints=True,
    )
    resources = page.resources

    if offset == 0 and not resources:
        return _error(oai, "noRecordsMatch", "No records found matching the criteria")

    list_records = ET.SubElement(oai, "ListRecords")
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
        records_added += 1

    if records_added == 0 and offset == 0 and not page.has_more:
        return _error(oai, "noRecordsMatch", "No records found matching the criteria")

    resumption_token_value = None
    if page.has_more:
        next_offset = offset + records_added
        resumption_token_value = base.resumption_service.create_token(
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

    return oai


def _get_record_tailored(
    oai: ET._Element,
    *,
    resource_uri: str,
    metadata_prefix: str,
    request: HttpRequest,
) -> ET._Element:
    queryset = _tailored_resources_queryset()
    resource = queryset.filter(uri=resource_uri).first()
    if not resource:
        return _error(oai, "idDoesNotExist", "Identifier not approved for tailored OAI")

    project_hint = _build_project_hint_from_resource(resource)
    if not project_hint or not project_hint.harvestable:
        return _error(oai, "idDoesNotExist", "Identifier not harvestable")

    marker_source = getattr(resource, "effective_datestamp", None) or getattr(resource, "updated_at", timezone.now())
    cursor_marker = f"tailored:{marker_source.isoformat()}"

    cached_record = _get_cached_record(
        resource,
        metadata_prefix,
        snapshot_marker=cursor_marker,
        cursor_marker=cursor_marker,
    )
    if cached_record and metadata_prefix == 'mets' and not _metadata_xml_is_valid(
        cached_record['metadata'],
        resource_uri=getattr(resource, 'uri', None),
    ):
        cached_record = None

    get_record = ET.SubElement(oai, "GetRecord")
    record = ET.SubElement(get_record, "record")

    if cached_record:
        header_elem = ET.fromstring(cached_record['header'])
        metadata_elem = ET.fromstring(cached_record['metadata'])
        record.append(header_elem)
        record.append(metadata_elem)
        return oai

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
        return _error(oai, "idDoesNotExist", "Identifier not available for METS dissemination")

    record.append(header)
    record.append(metadata)

    header_xml = ET.tostring(header, encoding='utf-8').decode('utf-8')
    metadata_xml = ET.tostring(metadata, encoding='utf-8').decode('utf-8')
    _cache_record(
        resource,
        metadata_prefix,
        header_xml,
        metadata_xml,
        snapshot_marker=cursor_marker,
        cursor_marker=cursor_marker,
    )

    return oai
