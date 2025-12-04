"""Tailored OAI-PMH helpers extracted from the monolithic view module."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)
from uuid import UUID

from django.conf import settings
from django.db.models import DateTimeField, Value, F, Max
from django.db.models.functions import Coalesce, Greatest
from django.http import HttpRequest
from django.utils import timezone
from lxml import etree as ET

from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.oaipmh.oai_project import OAIProject
from arkumu.oaipmh.oai_project_tailored import (
    batch_fetch_curated_links,
    batch_fetch_dcp_folders,
    batch_fetch_graph_data,
)

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
    _metadata_xml_is_valid,
)
from .projects import _build_tailored_project_hint_from_resource
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
        .select_related("organization", "oai_publication", "project_index")
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


def _tailored_harvestable_page(
    queryset,
    *,
    cursor_position: Optional[str],
    page_size: int,
    include_hints: bool,
) -> HarvestPageResult:
    # Filter by projects that have OAIProjectMediaLink entries (the source of truth for OAI)
    ordered = queryset.filter(oai_media_links__isnull=False).distinct().order_by("effective_datestamp", "id")
    ordered = _apply_cursor_filter(
        ordered,
        _parse_cursor_position(cursor_position),
        field_name="effective_datestamp",
    )

    # Fetch page_size + 1 to check if there's more
    batch_resources = list(ordered[:page_size + 1])
    has_more = len(batch_resources) > page_size
    resources = batch_resources[:page_size]

    # Batch fetch curated links for building project hints
    project_ids = [UUID(str(r.id)) for r in resources]
    curated_links_by_project = batch_fetch_curated_links(project_ids)

    # Collect digital object IDs for graph data fetch
    all_digital_object_ids: List[str] = []
    for links in curated_links_by_project.values():
        for link in links:
            digital_obj = getattr(link, "digital_object", None)
            if digital_obj:
                obj_id = getattr(digital_obj, "id", None)
                if obj_id:
                    all_digital_object_ids.append(str(obj_id))

    # DCP data from curated links
    dcp_data = batch_fetch_dcp_folders(curated_links_by_project)
    prefetched_graph_data = batch_fetch_graph_data(all_digital_object_ids) if all_digital_object_ids else None

    project_hints: Dict[str, OAIProject] = {}
    last_cursor_position = cursor_position

    for resource in resources:
        last_cursor_position = _format_cursor_position(
            resource,
            field_name="effective_datestamp",
        )
        if include_hints:
            prefetched_links = curated_links_by_project.get(resource.id)
            project_hint = _build_tailored_project_hint_from_resource(
                resource,
                prefetched_curated_links=prefetched_links,
                prefetched_dcp_data=dcp_data,
                prefetched_graph_data=prefetched_graph_data,
            )
            if project_hint:
                project_hints[resource.uri] = project_hint

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

    page_size = base.tailored_resumption_service.page_size
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
        resumption_token_value = base.tailored_resumption_service.create_token(
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
    import time
    t0 = time.perf_counter()

    queryset = _tailored_resources_queryset(
        set_spec=set_spec,
        from_date=from_date,
        until_date=until_date,
    )
    t1 = time.perf_counter()
    logger.info("ListRecords timing: queryset build %.3fs", t1 - t0)

    cursor_marker = _dataset_marker_for_queryset(queryset, field_name="effective_datestamp")
    t2 = time.perf_counter()
    logger.info("ListRecords timing: dataset marker %.3fs", t2 - t1)

    if cursor_marker_from_token and cursor_marker_from_token != cursor_marker:
        return _error(oai, "badResumptionToken", "Dataset has changed; restart harvesting")

    page_size = base.tailored_resumption_service.page_size
    page = _tailored_harvestable_page(
        queryset,
        cursor_position=cursor_position_from_token,
        page_size=page_size,
        include_hints=True,
    )
    t3 = time.perf_counter()
    logger.info("ListRecords timing: page fetch %.3fs", t3 - t2)

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
            skip_validation=True,
        )

        record = ET.SubElement(list_records, "record")
        record.append(header)
        record.append(metadata)
        records_added += 1

    if records_added == 0 and offset == 0 and not page.has_more:
        return _error(oai, "noRecordsMatch", "No records found matching the criteria")

    resumption_token_value = None
    if page.has_more:
        next_offset = offset + records_added
        resumption_token_value = base.tailored_resumption_service.create_token(
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

    project_hint = _build_tailored_project_hint_from_resource(resource, force_live=True)
    if not project_hint or not project_hint.harvestable:
        return _error(oai, "idDoesNotExist", "Identifier not harvestable")

    marker_source = getattr(resource, "effective_datestamp", None) or getattr(resource, "updated_at", timezone.now())
    cursor_marker = f"tailored:{marker_source.isoformat()}"

    cache_enabled = bool(getattr(settings, "OAI_CACHE_TAILORED", False))
    cached_record = None
    if cache_enabled:
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
        skip_validation=True,
        force_live_rdf=True,  # GetRecord always uses live RDF for preview
    )

    record.append(header)
    record.append(metadata)

    header_xml = ET.tostring(header, encoding='utf-8').decode('utf-8')
    metadata_xml = ET.tostring(metadata, encoding='utf-8').decode('utf-8')
    if cache_enabled:
        _cache_record(
            resource,
            metadata_prefix,
            header_xml,
            metadata_xml,
            snapshot_marker=cursor_marker,
            cursor_marker=cursor_marker,
        )

    return oai
