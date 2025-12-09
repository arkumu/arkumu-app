"""Tailored OAI-PMH helpers extracted from the monolithic view module.

This module implements a publication-first approach where OAIProjectPublication
is the source of truth for approved projects. This enables:
- Fast ListIdentifiers without joining media links
- Efficient batch fetching of curated links only for approved projects
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID

from django.conf import settings
from django.db.models import Q
from django.http import HttpRequest
from django.utils import timezone
from lxml import etree as ET

from arkumu.metadata.models.resource import Resource
from arkumu.oaipmh.models import OAIProjectPublication
from arkumu.oaipmh.oai_project import OAIProject
from arkumu.oaipmh.oai_project_tailored import (
    batch_fetch_curated_links,
    batch_fetch_dcp_folders,
    batch_fetch_graph_data,
)

from . import base
from .base import _cache_record, _get_cached_record
from .harvest import (
    _parse_from_datestamp,
    _parse_until_datestamp,
)
from .metadata import (
    _build_identifier,
    _build_metadata_element,
    _build_record_header,
    _format_datestamp,
    _metadata_xml_is_valid,
)
from .projects import _build_tailored_project_hint_from_resource
from .router import _error

logger = logging.getLogger(__name__)

__all__ = [
    "_approved_publications_queryset",
    "_list_identifiers_tailored",
    "_list_records_tailored",
    "_get_record_tailored",
]


@dataclass
class PublicationPageResult:
    """Result of fetching a page of approved publications."""
    publications: List[OAIProjectPublication]
    has_more: bool
    cursor_position: Optional[str]


def _approved_publications_queryset(
    set_spec: Optional[str] = None,
    from_date: Optional[str] = None,
    until_date: Optional[str] = None,
):
    """Build queryset starting from approved OAIProjectPublication records.

    This is the publication-first approach - OAIProjectPublication is the source
    of truth for what projects are approved for OAI harvesting.

    The publication's updated_at serves as the effective datestamp since it reflects:
    - When approval status changed
    - When media links were modified (via signal updates)
    """
    queryset = (
        OAIProjectPublication.objects
        .filter(is_approved=True)
        .filter(project__organization__is_active=True)
        .select_related("project", "project__organization")
        .order_by("updated_at", "project_id")
    )

    if set_spec:
        queryset = queryset.filter(project__organization__code__iexact=set_spec)

    if from_date:
        try:
            from_dt = _parse_from_datestamp(from_date)
            queryset = queryset.filter(updated_at__gte=from_dt)
        except ValueError:
            pass

    if until_date:
        try:
            until_dt = _parse_until_datestamp(until_date)
            queryset = queryset.filter(updated_at__lt=until_dt)
        except ValueError:
            pass

    return queryset


def _format_publication_cursor(pub: OAIProjectPublication) -> str:
    """Format cursor position from publication for pagination."""
    return f"{pub.updated_at.isoformat()}|{pub.project_id}"


def _parse_publication_cursor(token: Optional[str]) -> Optional[tuple[datetime, str]]:
    """Parse cursor position back to (timestamp, project_id)."""
    if not token:
        return None
    try:
        timestamp_str, pk_str = token.rsplit("|", 1)
        return datetime.fromisoformat(timestamp_str), pk_str
    except ValueError:
        return None


def _apply_publication_cursor(
    queryset,
    cursor_state: Optional[tuple[datetime, str]],
):
    """Apply cursor-based filtering to publication queryset."""
    if not cursor_state:
        return queryset
    timestamp, project_id = cursor_state
    return queryset.filter(
        Q(updated_at__gt=timestamp)
        | (Q(updated_at=timestamp) & Q(project_id__gt=project_id))
    )


def _publication_dataset_marker(queryset) -> str:
    """Get marker for detecting dataset changes during pagination."""
    latest = (
        queryset
        .order_by("-updated_at", "-project_id")
        .values_list("updated_at", "project_id")
        .first()
    )
    if not latest or latest[0] is None:
        return "empty"
    return latest[0].isoformat()


def _build_header_from_publication(pub: OAIProjectPublication) -> ET._Element:
    """Build OAI record header directly from publication (fast path)."""
    header = ET.Element("header")
    ET.SubElement(header, "identifier").text = _build_identifier(pub.project.uri)
    ET.SubElement(header, "datestamp").text = _format_datestamp(pub.updated_at)
    if pub.project.organization:
        ET.SubElement(header, "setSpec").text = pub.project.organization.code
    return header


def _fetch_publication_page(
    queryset,
    *,
    cursor_position: Optional[str],
    page_size: int,
) -> PublicationPageResult:
    """Fetch a page of approved publications with cursor-based pagination."""
    ordered = _apply_publication_cursor(
        queryset,
        _parse_publication_cursor(cursor_position),
    )

    batch = list(ordered[:page_size + 1])
    has_more = len(batch) > page_size
    publications = batch[:page_size]

    last_cursor = cursor_position
    if publications:
        last_cursor = _format_publication_cursor(publications[-1])

    return PublicationPageResult(
        publications=publications,
        has_more=has_more,
        cursor_position=last_cursor,
    )


def _fetch_project_hints_for_publications(
    publications: List[OAIProjectPublication],
) -> Dict[str, OAIProject]:
    """Batch fetch curated links and build project hints for approved publications.

    This is only called for ListRecords where we need full metadata.
    ListIdentifiers skips this entirely for fast header-only responses.
    """
    if not publications:
        return {}

    project_ids = [UUID(str(pub.project_id)) for pub in publications]
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

    dcp_data = batch_fetch_dcp_folders(curated_links_by_project)
    prefetched_graph_data = batch_fetch_graph_data(all_digital_object_ids) if all_digital_object_ids else None

    project_hints: Dict[str, OAIProject] = {}
    for pub in publications:
        resource = pub.project
        prefetched_links = curated_links_by_project.get(resource.id)
        project_hint = _build_tailored_project_hint_from_resource(
            resource,
            prefetched_curated_links=prefetched_links,
            prefetched_dcp_data=dcp_data,
            prefetched_graph_data=prefetched_graph_data,
        )
        if project_hint:
            project_hints[resource.uri] = project_hint

    return project_hints


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
    """List identifiers using publication-first approach (fast, no media link joins)."""
    queryset = _approved_publications_queryset(
        set_spec=set_spec,
        from_date=from_date,
        until_date=until_date,
    )
    cursor_marker = _publication_dataset_marker(queryset)

    if cursor_marker_from_token and cursor_marker_from_token != cursor_marker:
        return _error(oai, "badResumptionToken", "Dataset has changed; restart harvesting")

    page_size = base.tailored_resumption_service.page_size
    page = _fetch_publication_page(
        queryset,
        cursor_position=cursor_position_from_token,
        page_size=page_size,
    )

    if offset == 0 and not page.publications:
        return _error(oai, "noRecordsMatch", "No records found matching the criteria")

    list_identifiers = ET.SubElement(oai, "ListIdentifiers")
    for pub in page.publications:
        header = _build_header_from_publication(pub)
        list_identifiers.append(header)

    if page.has_more:
        next_offset = offset + len(page.publications)
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
    """List records using publication-first approach.

    Flow:
    1. Query approved publications (fast, indexed)
    2. Fetch page of publications
    3. Batch fetch curated links only for approved project IDs
    4. Build metadata for each record
    """
    import time
    t_start = time.perf_counter()

    # Check if this is first DB hit (connection establishment)
    from django.db import connection
    t0 = time.perf_counter()
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    t_db_init = time.perf_counter()
    logger.debug("ListRecords timing: DB connection check %.3fs", t_db_init - t0)

    queryset = _approved_publications_queryset(
        set_spec=set_spec,
        from_date=from_date,
        until_date=until_date,
    )
    t1 = time.perf_counter()
    logger.debug("ListRecords timing: queryset build %.3fs", t1 - t_db_init)

    cursor_marker = _publication_dataset_marker(queryset)
    t2 = time.perf_counter()
    logger.debug("ListRecords timing: dataset marker %.3fs (first ORM query)", t2 - t1)

    if cursor_marker_from_token and cursor_marker_from_token != cursor_marker:
        return _error(oai, "badResumptionToken", "Dataset has changed; restart harvesting")

    page_size = base.tailored_resumption_service.page_size
    page = _fetch_publication_page(
        queryset,
        cursor_position=cursor_position_from_token,
        page_size=page_size,
    )
    t3 = time.perf_counter()
    logger.debug("ListRecords timing: page fetch %.3fs", t3 - t2)

    if offset == 0 and not page.publications:
        return _error(oai, "noRecordsMatch", "No records found matching the criteria")

    # Batch fetch project hints only for this page of approved publications
    project_hints = _fetch_project_hints_for_publications(page.publications)
    t4 = time.perf_counter()
    logger.debug("ListRecords timing: project hints %.3fs", t4 - t3)

    list_records = ET.SubElement(oai, "ListRecords")
    records_added = 0

    for pub in page.publications:
        resource = pub.project
        project_hint = project_hints.get(resource.uri)
        if not project_hint:
            continue

        header = _build_header_from_publication(pub)
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
    """Get single record using publication-first lookup."""
    # Look up via approved publication
    pub = (
        OAIProjectPublication.objects
        .filter(is_approved=True, project__uri=resource_uri)
        .select_related("project", "project__organization")
        .first()
    )
    if not pub:
        return _error(oai, "idDoesNotExist", "Identifier not approved for tailored OAI")

    resource = pub.project
    project_hint = _build_tailored_project_hint_from_resource(resource, force_live=True)
    if not project_hint or not project_hint.harvestable:
        return _error(oai, "idDoesNotExist", "Identifier not harvestable")

    cursor_marker = f"tailored:{pub.updated_at.isoformat()}"

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
    record_elem = ET.SubElement(get_record, "record")

    if cached_record:
        header_elem = ET.fromstring(cached_record['header'])
        metadata_elem = ET.fromstring(cached_record['metadata'])
        record_elem.append(header_elem)
        record_elem.append(metadata_elem)
        return oai

    header = _build_header_from_publication(pub)
    metadata = _build_metadata_element(
        resource,
        metadata_prefix,
        project_hint=project_hint,
        request=request,
        skip_validation=True,
        force_live_rdf=True,
    )

    record_elem.append(header)
    record_elem.append(metadata)

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
