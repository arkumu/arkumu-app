"""
Simplified workspace views for metadata entry.

These views use the same infrastructure as the legacy workspace
(SchemaWorkspaceService, DatasetEntityForm, relationship handling)
but only show a subset of fields for a simplified user experience.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple, Union

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import render
from django.template.loader import render_to_string
from django.db.models import Q
from django.utils.text import slugify
from django.views import View
from django.views.decorators.http import require_http_methods

from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.schema_workspace import (
    DatasetEntityForm,
    SchemaWorkspaceService,
)
from arkumu.metadata.services.entity_label_service import infer_entity_label as _infer_entity_label
from arkumu.metadata.utils.uri_placeholders import decode_placeholder_uri
from arkumu.users.models import Organization
from arkumu.storage.models import S3FileObject
from arkumu.metadata.models.resource import Resource

logger = logging.getLogger(__name__)


# Section configuration shared by simplified edit views. Each section defines
# label metadata plus the ordered list of fields shown within the tab.
SIMPLIFIED_SECTION_CONFIG: Dict[str, List[Dict[str, Any]]] = {
    "Projekt": [
        {
            "key": "grundinformationen",
            "title": "Grundinformationen",
            "badge": "Titel und Identifikation",
            "fields": [
                "Bevorzugter Titel",
                {
                    "name": "Sprache des bevorzugten Titels",
                    "search_property": "Sprachbezeichnung",
                },
                "Bevorzugter Untertitel",
                {
                    "name": "Sprache des bevorzugten Untertitels",
                    "search_property": "Sprachbezeichnung",
                },
                "Alternativer Titel-Set",
            ],
        },
        {
            "key": "beschreibungen",
            "title": "Beschreibungen und Kommentare",
            "badge": "Texte",
            "fields": [
                "Beschreibung",
                "Deutscher Kommentar",
                "Englischer Kommentar",
                "Interner Kommentar",
                "Inhaltswarnung",
            ],
        },
        {
            "key": "klassifikation",
            "title": "Klassifikation",
            "badge": "Kategorien",
            "fields": [
                {
                    "name": "Projektart",
                    "search_property": "Bezeichnung",
                },
                {
                    "name": "Projektkategorie",
                    "search_property": "Bezeichnung",
                },
                {
                    "name": "Schlagwort",
                    "search_property": "Bezeichnung",
                },
                {
                    "name": "Organisationseinheit",
                    "search_property": "Bezeichnung",
                },
            ],
        },
        {
            "key": "normdaten",
            "title": "Normdaten und Links",
            "badge": "Kennungen",
            "fields": [
                "Wikidata-ID",
                "GND-Nummer",
                "Andere Normdaten",
                "Externe Projektwebseite",
            ],
        },
        {
            "key": "ereignisse",
            "title": "Verknüpfte Ereignisse & Projekte",
            "badge": "Verweise",
            "fields": [
                {
                    "name": "Ereignis",
                    "label": "Verknüpfte Ereignisse",
                    "help_text": "Ereignisse auswählen, die diesem Projekt zugeordnet sind.",
                    "search_property": "Ereignisname",
                },
                {
                    "name": "Vorschaubild",
                    "search_property": "Titel",
                },
                {
                    "name": "projekt-hat-teil",
                    "label": "Projekt hat Teil",
                    "help_text": "Projekte auswählen, die als Teil dieses Projekts geführt werden.",
                    "search_property": "Bevorzugter Titel",
                },
            {
                    "name": "projekt-ist-teil-von",
                    "label": "Projekt ist Teil von",
                    "help_text": "Übergeordnete Projekte auswählen, zu denen dieses Projekt gehört.",
                    "search_property": "Bevorzugter Titel",
                },
                {
                    "name": "projekt-hat-bezug-zu",
                    "label": "Projekt hat Bezug zu",
                    "help_text": "Weitere Projekte verknüpfen, zu denen ein thematischer Bezug besteht.",
                    "search_property": "Bevorzugter Titel",
                },
                {
                    "name": "projekt-basiert-auf",
                    "label": "Projekt basiert auf",
                    "help_text": "Quellenprojekte angeben, auf denen dieses Projekt aufbaut.",
                    "search_property": "Bevorzugter Titel",
                },
                {
                    "name": "projekt-ist-vorbereitend-fuer",
                    "label": "Projekt ist vorbereitend für",
                    "help_text": "Folgeprojekte angeben, die mit diesem Projekt vorbereitet werden.",
                    "search_property": "Bevorzugter Titel",
                },
            ],
        },
        {
            "key": "verwaltung",
            "title": "Verwaltung und Signaturen",
            "badge": "Administrative Daten",
            "fields": [
                "Rechtsstatus",
                "Signatur beim Einlieferer",
                "Werkverzeichnis-Nummer",
            ],
        },
    ],
    "Ereignis": [
        {
            "key": "grundinformationen",
            "title": "Grundinformationen",
            "badge": "Typ und Name",
            "fields": [
                {
                    "name": "Ereignistyp",
                    "search_property": "Bezeichnung",
                },
                "Ereignisname",
            ],
        },
        {
            "key": "akteure",
            "title": "Akteur:innen & Rollen",
            "badge": "Beteiligte",
            "fields": [
                {
                    "name": "ereignis-hat-akteurin",
                    "label": "Verknüpfte Akteur:innen",
                    "help_text": "Wähle Akteur:innen und ihre Rollen im Ereignis aus.",
                    "search_property": "Deutscher Name",
                },
            ],
        },
        {
            "key": "zeit-ort",
            "title": "Zeit und Ort",
            "badge": "Zeitliche und räumliche Daten",
            "fields": [
                "Ereignisbeginn",
                "Ereignisende",
                {
                    "name": "Ereignisort",
                    "search_property": "Ortsname",
                },
            ],
        },
        {
            "key": "beschreibung",
            "title": "Beschreibung",
            "badge": "Textuelle Informationen",
            "fields": [
                "Ereignisbeschreibung",
            ],
        },
        {
            "key": "objekte-medien",
            "title": "Verknüpfte Objekte & Medien",
            "badge": "Sammlungsobjekte",
            "fields": [
                {
                    "name": "Physisches Objekt",
                    "label": "Physische Objekte",
                    "search_property": "Bezeichnung",
                },
                {
                    "name": "Informationsträger",
                    "label": "Informationsträger",
                    "search_property": "Bezeichnung",
                },
            ],
        },
        {
            "key": "digitale-objekte",
            "title": "Digitale Objekte",
            "badge": "Medien",
            "fields": [
                {
                    "name": "Digitales Objekt",
                    "label": "Digitale Objekte",
                    "search_property": "Titel",
                },
            ],
        },
        {
            "key": "technische-ressourcen",
            "title": "Technische Ressourcen",
            "badge": "Equipment & Software",
            "fields": [
                {
                    "name": "Equipment und Software",
                    "search_property": "Bezeichnung",
                },
            ],
        },
    ],
}

PROJECT_LINK_FIELD_NAME = "Verknüpftes Projekt"
PROJECT_LINK_PROPERTY_URI = "http://arkumu.org/data/properties/verknuepftes-projekt"
PROJECT_DATASET_NAME = "Projekt"
PROJECT_TRIPLE_PREDICATE_SLUGS = {
    "projekt-hat-teil",
    "projekt-ist-teil-von",
    "projekt-hat-bezug-zu",
    "projekt-basiert-auf",
    "projekt-ist-vorbereitend-fuer",
}


def _flatten_section_fields(section_config: List[Dict[str, Any]]) -> List[str]:
    """Flatten section definitions to a list of field names."""
    names: List[str] = []
    for section in section_config:
        for field in section.get("fields", []):
            if isinstance(field, dict):
                names.append(field.get("name", ""))
            else:
                names.append(str(field))
    return [name for name in names if name]


def _extract_field_config(section_config: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Extract field-level configuration (search_property, label, help_text) from sections."""
    config: Dict[str, Dict[str, Any]] = {}
    for section in section_config:
        for field in section.get("fields", []):
            if isinstance(field, dict):
                field_name = field.get("name", "")
                if field_name:
                    config[field_name] = field
    return config


# Backwards compatible mapping used for metadata filtering logic.
SIMPLIFIED_FIELD_CONFIG: Dict[str, List[str]] = {
    dataset: _flatten_section_fields(sections)
    for dataset, sections in SIMPLIFIED_SECTION_CONFIG.items()
}

# Field-level configuration extracted from sections (search_property, label, help_text)
SIMPLIFIED_FIELD_PROPS: Dict[str, Dict[str, Dict[str, Any]]] = {
    dataset: _extract_field_config(sections)
    for dataset, sections in SIMPLIFIED_SECTION_CONFIG.items()
}


def _ensure_project_link_field(metadata: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Ensure the project metadata always includes a multi-value field for linked projects.

    Some mappings omit the `Verknüpftes Projekt` property from their schema manifest.
    The schema workspace service now provides a fallback join relationship, so no
    additional metadata synthesis is required here.
    """
    return metadata


def _get_organization(request: HttpRequest) -> Optional[Organization]:
    """Get organization from user or from URI parameter."""
    # First try user's organization
    organization = getattr(request.user, "organization", None)

    # If editing, extract org from URI
    entity_uri = request.GET.get("uri", "")
    if entity_uri and "/data/" in entity_uri:
        uri_parts = entity_uri.split("/")
        if len(uri_parts) >= 6 and uri_parts[3] == "data":
            uri_org_code = uri_parts[4]
            uri_organization = Organization.objects.filter(code=uri_org_code).first()
            if uri_organization:
                organization = uri_organization
                logger.info(f"Using organization from URI: {organization.code}")

    return organization


def _get_schema_service(request: HttpRequest) -> Optional[SchemaWorkspaceService]:
    """Get SchemaWorkspaceService for the current organization."""
    organization = _get_organization(request)
    if not organization:
        return None

    mapping = Mapping.objects.filter(organization_id=organization.code).order_by("-created_at").first()
    if not mapping:
        logger.error(f"No mapping found for organization {organization.code}")
        return None

    logger.info(f"Using mapping {mapping.id} for organization {organization.code}")
    return SchemaWorkspaceService(mapping=mapping, organization=organization)


def _normalize_uri_list(values: List[str]) -> List[str]:
    """Normalize a list of raw URI values, removing placeholders and duplicates."""
    normalized: List[str] = []
    seen = set()
    for raw in values:
        cleaned = str(raw or "").strip()
        if not cleaned:
            continue
        canonical, _ = decode_placeholder_uri(cleaned)
        if canonical and canonical not in seen:
            normalized.append(canonical)
            seen.add(canonical)
    return normalized


def _collect_relationship_payloads(
    request: HttpRequest,
    entity_data: Dict[str, Any],
    field_metadata: Dict[str, Dict[str, Any]],
    join_field_map: Dict[str, Any],
    entity_uri: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, List[Dict[str, Any]]], Dict[str, List[str]]]:
    """
    Extract join and multi-FK payloads from the POST body, mirroring legacy behaviour.

    Returns the sanitized entity_data plus dictionaries mapping field names to
    join payload records (URI + optional context) and multi-FK URI lists.
    """
    filtered_join_map = {
        name: relationship
        for name, relationship in (join_field_map or {}).items()
        if name in field_metadata
    }

    join_payloads: Dict[str, List[Dict[str, Any]]] = {}
    multi_fk_payloads: Dict[str, List[str]] = {}

    for field_name, relationship in filtered_join_map.items():
        array_key = f"{field_name}[]"
        entity_data.pop(field_name, None)
        raw_values = request.POST.getlist(array_key)
        field_meta = field_metadata.get(field_name, {})
        context_specs = field_meta.get("context_columns") or []
        context_values_by_slug: Dict[str, List[str]] = {}
        for context_spec in context_specs:
            column_name = context_spec.get("column") or context_spec.get("column_name") or ""
            slug = context_spec.get("slug") or slugify(column_name).replace("-", "_")
            context_key = f"{field_name}__context__{slug}[]"
            context_values_by_slug[slug] = request.POST.getlist(context_key)

        records: List[Dict[str, Any]] = []
        for index, raw_value in enumerate(raw_values):
            cleaned_value = str(raw_value or "").strip()
            if not cleaned_value:
                continue
            canonical_value, _ = decode_placeholder_uri(cleaned_value)
            if not canonical_value:
                continue

            context_payload: Dict[str, str] = {}
            for context_spec in context_specs:
                column_name = context_spec.get("column") or context_spec.get("column_name") or ""
                slug = context_spec.get("slug") or slugify(column_name).replace("-", "_")
                values = context_values_by_slug.get(slug, [])
                context_value = values[index] if index < len(values) else ""
                context_payload[column_name] = str(context_value or "").strip()

            records.append(
                {
                    "uri": canonical_value,
                    "context": context_payload,
                }
            )

        join_payloads[field_name] = records

    canonical_entity_uri = None
    if entity_uri:
        canonical_entity_uri, _ = decode_placeholder_uri(entity_uri)
        canonical_entity_uri = canonical_entity_uri or entity_uri

    if canonical_entity_uri:
        for field_name, records in list(join_payloads.items()):
            filtered_records = []
            for record in records:
                uri = record.get("uri")
                if not uri:
                    continue
                if uri in {canonical_entity_uri, entity_uri}:
                    continue
                filtered_records.append(record)
            join_payloads[field_name] = filtered_records

    for field_name, meta in field_metadata.items():
        if field_name in join_payloads:
            continue

        # Skip TripleCreatorWidget fields - they are managed via HTMX endpoints
        widget = meta.get("widget")
        if widget == "TripleCreatorWidget":
            logger.info(f"⏭️  Skipping TripleCreatorWidget field: {field_name}")
            continue

        fk_info = meta.get("fk_relationship") or {}
        if not fk_info or not meta.get("is_multi_value"):
            continue

        array_key = f"{field_name}[]"
        entity_data.pop(field_name, None)
        raw_array = request.POST.getlist(array_key)
        if raw_array:
            multi_fk_payloads[field_name] = _normalize_uri_list(raw_array)
        else:
            multi_fk_payloads[field_name] = []

    if canonical_entity_uri:
        for field_name, uris in list(multi_fk_payloads.items()):
            filtered = [
                uri
                for uri in uris
                if uri
                and uri != canonical_entity_uri
                and uri != entity_uri
            ]
            multi_fk_payloads[field_name] = filtered

    return entity_data, join_payloads, multi_fk_payloads


def _build_tab_sections(
    dataset_name: str,
    fields_with_metadata: List[Dict[str, Any]],
    relationship_fields: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Group enriched field metadata into UI sections."""
    sections_config = SIMPLIFIED_SECTION_CONFIG.get(dataset_name, [])
    field_lookup = {item["field"].name: item for item in fields_with_metadata}
    for rel_item in relationship_fields or []:
        field_lookup[rel_item["field"].name] = rel_item
    tab_sections: List[Dict[str, Any]] = []

    for index, section in enumerate(sections_config):
        section_fields: List[Dict[str, Any]] = []
        for field_entry in section.get("fields", []):
            if isinstance(field_entry, dict):
                field_name = field_entry.get("name", "")
                overrides = field_entry
            else:
                field_name = str(field_entry)
                overrides = {}

            if not field_name:
                continue

            item = field_lookup.get(field_name)
            if not item:
                continue

            item_copy = dict(item)
            label_override = overrides.get("label")
            help_override = overrides.get("help_text")

            if label_override:
                item_copy["label_override"] = label_override
            if help_override:
                item_copy["help_text_override"] = help_override

            section_fields.append(item_copy)

        if not section_fields:
            continue

        section_identifier = section.get("key") or section.get("title") or f"section-{index}"
        section_slug = slugify(section_identifier) or f"section-{index}"

        tab_sections.append(
            {
                "id": section_slug,
                "title": section.get("title", section_identifier),
                "badge": section.get("badge"),
                "description": section.get("description"),
                "fields": section_fields,
            }
        )

    return tab_sections


def _filter_field_metadata(
    field_metadata: Dict[str, Any],
    visible_fields: List[str]
) -> Dict[str, Any]:
    """Filter field metadata to only include visible fields."""
    filtered = {}
    for field_name, metadata in field_metadata.items():
        if field_name in visible_fields:
            filtered[field_name] = metadata
        else:
            logger.debug(f"Hiding field: {field_name}")

    logger.info(f"Filtered {len(field_metadata)} fields to {len(filtered)} visible fields")
    return filtered


def _select_primary_search_property(meta: Dict[str, Any]) -> Optional[str]:
    """Pick a single search property to use for simplified multi-select widgets."""
    existing = meta.get("selected_property")
    if existing:
        return str(existing)

    fk_info = meta.get("fk_relationship") or {}
    if meta.get("is_external_ontology") and fk_info.get("target_property_uri"):
        return str(fk_info.get("target_property_uri"))

    search_properties = meta.get("search_properties") or []
    preferred_tokens = ("name", "titel", "title", "label", "bezeichnung", "beschreibung")

    for prop in search_properties:
        column = str(prop.get("column") or "").lower()
        if any(token in column for token in preferred_tokens):
            uri = prop.get("uri")
            if uri:
                return str(uri)

    for prop in search_properties:
        uri = prop.get("uri")
        if uri:
            return str(uri)

    return None


def _select_display_property(meta: Dict[str, Any]) -> Optional[str]:
    """Choose the best property for human-readable labels."""
    display_uri = meta.get("display_property")
    if display_uri:
        return str(display_uri)

    search_properties = meta.get("search_properties") or []
    # Prefer "bevorzugter" titles over "alternativer" titles
    preferred_tokens = ("bevorzugter", "label", "name", "bezeichnung", "titel", "title", "beschreibung")

    for prop in search_properties:
        column = str(prop.get("column") or "").lower()
        if any(token in column for token in preferred_tokens):
            uri = prop.get("uri")
            if uri:
                return str(uri)

    for prop in search_properties:
        uri = prop.get("uri")
        if uri:
            return str(uri)

    return None


def _resolve_preview_file_metadata(
    *,
    selected_uri: str,
    organization_code: Optional[str],
    fallback_label: str = "",
) -> Tuple[str, str]:
    """Return (label, key) for a verified S3 file linked to the URI."""

    if not selected_uri:
        return "", ""

    queryset = (
        S3FileObject.objects.filter(
            status="verified",
            s3_key=selected_uri,
        )
        .order_by("-updated_at", "-created_at")
    )

    if organization_code:
        queryset = queryset.filter(
            Q(organization__iexact=organization_code)
            | Q(related_resource__organization__code__iexact=organization_code)
        )

    file_obj = queryset.first()
    if not file_obj:
        return fallback_label, ""

    label = file_obj.file_name or fallback_label or file_obj.s3_key
    return label or fallback_label, file_obj.s3_key or selected_uri


def _extract_single_uri(value: Union[str, Dict[str, Any], List[Any], None]) -> str:
    """Normalize various form value representations to a single URI string."""

    if not value:
        return ""

    if isinstance(value, str):
        trimmed = value.strip()
        if not trimmed:
            return ""
        if trimmed.startswith("["):
            try:
                parsed = json.loads(trimmed)
            except json.JSONDecodeError:
                return trimmed
            return _extract_single_uri(parsed)
        return trimmed

    if isinstance(value, dict):
        uri = value.get("uri") or value.get("value")
        return str(uri or "").strip()

    if isinstance(value, list):
        for item in value:
            candidate = _extract_single_uri(item)
            if candidate:
                return candidate
        return ""

    return str(value).strip()


def _get_preview_field_name(fields_with_metadata: List[Dict[str, Any]]) -> Optional[str]:
    for item in fields_with_metadata:
        preview_meta = item.get("meta", {}).get("preview_picker")
        if preview_meta:
            return preview_meta.get("field_name") or getattr(item.get("field"), "name", None)
    return None


def _update_project_preview_link(
    *,
    project_uri: str,
    preview_key: str,
    organization_code: Optional[str],
) -> None:
    """Ensure the selected S3 object is linked to the project resource."""

    logger.info(
        "📷 Preview link requested | project=%s | key=%s | org=%s",
        project_uri,
        preview_key,
        organization_code,
    )

    if not project_uri:
        logger.info("📷 Preview link skipped: missing project URI")
        return

    project_resource = Resource.objects.filter(uri=project_uri).first()
    if project_resource is None:
        logger.warning("📷 Preview link skipped: project resource %s not found", project_uri)
        return

    # Clear previous links that no longer match
    stale_queryset = S3FileObject.objects.filter(related_resource=project_resource)
    if preview_key:
        stale_queryset = stale_queryset.exclude(s3_key=preview_key)
    stale_count = stale_queryset.update(related_resource=None)
    if stale_count:
        logger.info("📷 Cleared %s stale preview link(s) for %s", stale_count, project_uri)

    if not preview_key:
        logger.info("📷 Preview cleared for %s", project_uri)
        return

    file_obj = (
        S3FileObject.objects.filter(status="verified", s3_key=preview_key)
        .order_by("-updated_at", "-created_at")
        .first()
    )

    if file_obj is None:
        logger.warning("📷 Preview link skipped: verified S3 key %s not found", preview_key)
        return

    update_fields = ["related_resource"]
    if organization_code:
        new_org = organization_code.lower()
        if file_obj.organization != new_org:
            file_obj.organization = new_org
            update_fields.append("organization")

    file_obj.related_resource = project_resource
    file_obj.save(update_fields=update_fields)
    logger.info(
        "📷 Preview linked | file=%s | project=%s | org=%s",
        file_obj.s3_key,
        project_uri,
        file_obj.organization,
    )


def _enrich_fk_metadata(
    form: DatasetEntityForm,
    field_metadata: Dict[str, Any],
    schema_service: SchemaWorkspaceService,
    dataset_name: str,
    entity_uri: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Enrich FK field metadata with resolved labels and search URLs.

    This mirrors the logic from schema_workspace_views.py lines 419-620.
    For single FK fields, resolves the URI to a human-readable label
    and provides search/autocomplete functionality.
    """
    from django.urls import reverse
    from django.utils.http import urlencode
    from django.utils.text import slugify

    fields_with_metadata: List[Dict[str, Any]] = []

    # Build base suggestion URL for autocomplete
    base_suggestion_url = reverse(
        "metadata:entity_workspace_field_values",
        args=[schema_service.mapping.id],
    )

    for index, field in enumerate(form):
        meta = dict(field_metadata.get(field.name, {}))
        widget_before = meta.get("widget")
        if "projekt" in field.name and "teil" in field.name:
            logger.info(f"🔍 Field {field.name} initial widget: {widget_before}")
        fk_info = meta.get("fk_relationship") or {}
        target_dataset = fk_info.get("target_dataset") if fk_info else None

        # Ensure common metadata keys exist for template access
        meta.setdefault("resolved_label", "")
        meta.setdefault("resolved_uri", "")
        meta["use_single_fk_widget"] = False

        field_slug = slugify(field.name or "")
        if field_slug in {"vorschaubild", "vorschaubild_uri"}:
            organization = getattr(schema_service, "organization", None)
            org_code = getattr(organization, "code", None)
            raw_value = form.data.get(field.name) if form.is_bound else None
            if not raw_value:
                raw_value = form.initial.get(field.name, field.value())
            selected_uri = _extract_single_uri(raw_value)
            fallback_label = meta.get("resolved_label") or ""
            label, key = _resolve_preview_file_metadata(
                selected_uri=selected_uri,
                organization_code=org_code,
                fallback_label=fallback_label,
            )

            meta["preview_picker"] = {
                "selected_uri": selected_uri,
                "selected_label": label,
                "selected_key": key,
                "organization_code": org_code or "",
                "field_name": field.name,
            }
            meta["input_id"] = field.auto_id or f"id_{slugify(field.name) or index}"
            meta["target_id"] = None
            meta["search_url"] = None

            fields_with_metadata.append(
                {
                    "field": field,
                    "meta": meta,
                    "search_url": None,
                    "target_id": None,
                    "initial_labels": [],
                    "widget_context": None,
                    "rows": [],
                }
            )
            continue

        # Build search properties for target dataset
        if target_dataset:
            try:
                target_schema = schema_service.get_dataset_schema(target_dataset)
                properties: List[Dict[str, str]] = []
                for column, prop in (target_schema.get("properties", {}) or {}).items():
                    uri = getattr(prop, "uri", None)
                    if not uri:
                        continue
                    label = getattr(prop, "name", column) or column
                    properties.append({"uri": uri, "label": label, "column": column})
                properties.sort(key=lambda item: item["label"].lower())

                # Get configured search_property from field config
                field_config = SIMPLIFIED_FIELD_PROPS.get(dataset_name, {}).get(field.name, {})
                configured_search_property = field_config.get("search_property")

                # If search_property is configured, only include that one property
                if configured_search_property:
                    filtered_properties = [
                        prop for prop in properties
                        if prop.get("label") == configured_search_property or prop.get("column") == configured_search_property
                    ]
                    if filtered_properties:
                        meta["search_properties"] = filtered_properties
                        meta["search_property_configured"] = True
                        logger.info(f"🔒 Locked search to configured property '{configured_search_property}' for {field.name}")
                    else:
                        # Configured property not found, show all but warn
                        meta["search_properties"] = properties
                        logger.warning(f"⚠️  Configured search_property '{configured_search_property}' not found for {field.name}")
                else:
                    # No configuration, show all properties
                    meta["search_properties"] = properties
            except ValueError:
                logger.warning(f"Could not load schema for target dataset: {target_dataset}")
                meta["search_properties"] = []

        # Build search URL and target ID for autocomplete
        search_url: Optional[str] = None
        target_id: Optional[str] = None

        if fk_info:
            target_id = f"field-suggestions-{index}-{slugify(field.name) or index}"
            input_id = field.auto_id or f"id_{slugify(field.name) or index}"
            meta["input_id"] = input_id
            meta["target_id"] = target_id

            base_params = {"dataset": dataset_name, "column": field.name}
            base_url = f"{base_suggestion_url}?{urlencode(base_params)}"
            query_params = {"input_id": input_id, "target_id": target_id}
            search_url = base_url + "&" + urlencode(query_params)
            meta["search_url"] = search_url
            meta["base_suggestion_url"] = base_url
            logger.info(f"🔍 FK field '{field.name}': search_url={search_url}, target_id={target_id}")

        widget_name = str(meta.get("widget") or "")
        if widget_name != "TripleCreatorWidget":
            candidate_property_uris = [
                meta.get("property_uri"),
                fk_info.get("source_property_uri") if fk_info else None,
                fk_info.get("source_canonical_property") if fk_info else None,
            ]
            normalized_candidates = {
                str(uri)
                for uri in candidate_property_uris
                if uri
            }
            candidate_slugs = {
                str(uri).rstrip("/").split("/")[-1]
                for uri in normalized_candidates
            }
            if candidate_slugs.intersection(PROJECT_TRIPLE_PREDICATE_SLUGS) and target_dataset == "Projekt":
                widget_name = "TripleCreatorWidget"
                meta["widget"] = widget_name

        if widget_name == "TripleCreatorWidget":
            # Get configured search_property from field config
            field_config = SIMPLIFIED_FIELD_PROPS.get(dataset_name, {}).get(field.name, {})
            configured_search_property = field_config.get("search_property")

            # Ensure display_property is set for all triple creator widgets
            if not meta.get("display_property"):
                if configured_search_property:
                    # Look up the property URI for the configured search property name
                    search_props = meta.get("search_properties", [])
                    for prop in search_props:
                        if prop.get("label") == configured_search_property or prop.get("column") == configured_search_property:
                            meta["display_property"] = prop.get("uri")
                            logger.info(f"✅ Using configured search_property '{configured_search_property}' -> {prop.get('uri')}")
                            break
                    if not meta.get("display_property"):
                        logger.warning(f"⚠️  Configured search_property '{configured_search_property}' not found in search_properties")
                        meta["display_property"] = _select_display_property(meta)
                else:
                    # Fallback to heuristic selection
                    meta["display_property"] = _select_display_property(meta)

            property_uri = (
                meta.get("property_uri")
                or fk_info.get("source_property_uri")
                or fk_info.get("source_canonical_property")
            )
            slug = slugify(field.name) or field.name
            list_id = f"triple-list-{slug}"
            suggestions_id = f"triple-suggestions-{slug}"
            input_id = f"triple-input-{slug}"
            display_prop = meta.get("display_property") or ""
            logger.info(f"🎯 Triple creator for {field.name}: display_property={display_prop}, predicate={property_uri}")

            widget_context = {
                "component": "triple_creator",
                "field_name": field.name,
                "mapping_id": schema_service.mapping.id,
                "subject_uri": entity_uri or "",
                "predicate_uri": property_uri or "",
                "target_dataset": target_dataset or "",
                "property_uri": property_uri or "",
                "display_property": display_prop,
                "list_id": list_id,
                "suggestions_id": suggestions_id,
                "input_id": input_id,
                "component_id": f"triple-component-{slug}",
                "suggestions_url": reverse(
                    "metadata:entity_workspace_triple_suggestions",
                    args=[schema_service.mapping.id],
                ),
                "triples": [],
                "disabled": not (entity_uri and property_uri),
            }

            if entity_uri and property_uri:
                triples = schema_service.list_triple_relationships(
                    subject_uri=entity_uri,
                    predicate_uri=property_uri,
                    target_dataset=target_dataset,
                    display_property_uri=meta.get("display_property"),
                )
                widget_context["triples"] = triples

            form.initial[field.name] = ""
            if hasattr(field, "form"):
                field.form.initial[field.name] = ""
            if field.name in form.fields:
                form.fields[field.name].initial = ""

            fields_with_metadata.append({
                "field": field,
                "meta": meta,
                "search_url": search_url,
                "target_id": target_id,
                "initial_labels": [],
                "widget_context": widget_context,
                "rows": [],
            })
            continue

        # Prepare data for multi-value FK fields using legacy relationship rows
        initial_labels: List[Dict[str, str]] = []
        context_specs = meta.get("context_columns") or []
        if context_specs:
            context_options: Dict[str, List[str]] = {}
            for spec in context_specs:
                column_name = spec.get("column") or spec.get("column_name") or ""
                property_uri = spec.get("property_uri")
                options = schema_service.get_context_value_options(property_uri)
                context_options[column_name] = options
            meta["context_options"] = context_options

        join_rows: List[Dict[str, Any]] = []
        if fk_info and meta.get("is_multi_value"):
            raw_initial = form.initial.get(field.name, field.value())
            parsed_values: List[Any]
            if isinstance(raw_initial, str) and raw_initial:
                try:
                    loaded = json.loads(raw_initial)
                    parsed_values = loaded if isinstance(loaded, list) else [raw_initial]
                except (TypeError, ValueError, json.JSONDecodeError):
                    parsed_values = [raw_initial]
            elif isinstance(raw_initial, list):
                parsed_values = raw_initial
            else:
                parsed_values = []

            # Get configured search_property from field config
            field_config = SIMPLIFIED_FIELD_PROPS.get(dataset_name, {}).get(field.name, {})
            configured_search_property = field_config.get("search_property")

            display_property_uri = None
            if configured_search_property:
                # Look up the property URI for the configured search property name
                search_props = meta.get("search_properties", [])
                for prop in search_props:
                    if prop.get("label") == configured_search_property or prop.get("column") == configured_search_property:
                        display_property_uri = prop.get("uri")
                        logger.info(f"✅ Using configured search_property '{configured_search_property}' for {field.name}")
                        break
                if not display_property_uri:
                    logger.warning(f"⚠️  Configured search_property '{configured_search_property}' not found, falling back to heuristic")
                    display_property_uri = _select_display_property(meta)
            else:
                # Fallback to heuristic selection
                display_property_uri = _select_display_property(meta)

            if display_property_uri:
                meta["display_property"] = display_property_uri

            normalized: List[Dict[str, str]] = []
            for entry in parsed_values:
                if isinstance(entry, dict):
                    uri = (entry.get("uri") or entry.get("value") or "").strip()
                else:
                    uri = str(entry).strip()
                if not uri:
                    continue
                label = _infer_entity_label(
                    schema_service,
                    uri,
                    target_dataset,
                    display_property_uri=display_property_uri,
                )

                resource_entry = {"label": label, "uri": uri}
                # Try to get resource ID for graph view
                from arkumu.metadata.models.resource import Resource
                target_resource = Resource.objects.filter(uri=uri).first()
                if target_resource:
                    resource_entry["resource_id"] = str(target_resource.id)
                normalized.append(resource_entry)

            if normalized:
                labelled_json = json.dumps(normalized)
                form.initial[field.name] = labelled_json
                if hasattr(field, "form"):
                    field.form.initial[field.name] = labelled_json
                initial_labels.extend(normalized)
                logger.info(f"✅ Resolved multi-value FK field '{field.name}': {len(normalized)} values")
        # Handle single FK fields (not multi-value)
        elif fk_info and not meta.get("is_multi_value"):
            meta["use_single_fk_widget"] = True
            raw_value = form.initial.get(field.name, field.value())
            raw_value_str = str(raw_value).strip() if raw_value else ""
            display_prop_uri = meta.get("display_property")

            # Get configured search_property from field config
            field_config = SIMPLIFIED_FIELD_PROPS.get(dataset_name, {}).get(field.name, {})
            configured_search_property = field_config.get("search_property")

            # Use configured search property if available
            if not display_prop_uri and target_dataset:
                if configured_search_property:
                    # Look up the property URI for the configured search property name
                    search_props = meta.get("search_properties", [])
                    for prop in search_props:
                        if prop.get("label") == configured_search_property or prop.get("column") == configured_search_property:
                            display_prop_uri = prop.get("uri")
                            meta["display_property"] = display_prop_uri
                            meta["display_property_label"] = prop.get("label")
                            logger.info(f"✅ Using configured search_property '{configured_search_property}' for {field.name}")
                            break
                    if not display_prop_uri:
                        logger.warning(f"⚠️  Configured search_property '{configured_search_property}' not found, falling back to heuristic")

                # Fallback to auto-select best display property if not set
                if not display_prop_uri:
                    preferred_names = ["name", "titel", "title", "label", "bezeichnung", "beschreibung"]
                    for prop in meta.get("search_properties", []):
                        prop_name_lower = prop.get("column", "").lower()
                        if any(pref in prop_name_lower for pref in preferred_names):
                            display_prop_uri = prop.get("uri")
                            meta["display_property"] = display_prop_uri
                            meta["display_property_label"] = prop.get("label")
                            logger.info(f"Auto-selected display property for {field.name}: {meta['display_property_label']}")
                            break

            resolved_label = ""
            if raw_value_str and target_dataset:
                resolved_label = _infer_entity_label(
                    schema_service,
                    raw_value_str,
                    target_dataset,
                    display_property_uri=display_prop_uri,
                )

            canonical_value = ""
            label_hint = ""
            if raw_value_str:
                canonical_value, label_hint = decode_placeholder_uri(raw_value_str)

            # Prefer canonical URI if available, otherwise fall back to raw value
            uri_value = canonical_value or raw_value_str
            display_value = resolved_label or label_hint or raw_value_str

            meta["resolved_uri"] = uri_value
            meta["resolved_label"] = display_value

            # Keep the form's initial value in sync so validation errors redisplay the label
            if display_value and field.name in form.fields:
                form.fields[field.name].initial = display_value
            if display_value:
                form.initial[field.name] = display_value

        elif meta.get("is_join"):
            raw_initial = form.initial.get(field.name, field.value())
            try:
                parsed = json.loads(raw_initial) if raw_initial else []
            except (TypeError, ValueError, json.JSONDecodeError):
                parsed = [raw_initial] if raw_initial else []

            if isinstance(parsed, list):
                for entry in parsed:
                    if isinstance(entry, dict):
                        label = entry.get("label") or entry.get("uri") or ""
                        uri = (entry.get("uri") or entry.get("related_uri") or "").strip()
                        resource_id = entry.get("resource_id")
                        join_resource_id = entry.get("join_resource_id")
                        context_payload = entry.get("context") if isinstance(entry.get("context"), dict) else {}
                    else:
                        label = str(entry)
                        uri = str(entry)
                        resource_id = None
                        join_resource_id = None
                        context_payload = {}
                    if not uri:
                        continue
                    initial_entry = {
                        "label": label or uri,
                        "uri": uri,
                        "resource_id": resource_id,
                        "join_resource_id": join_resource_id,
                        "context": context_payload,
                    }
                    initial_labels.append(initial_entry)

            import uuid
            rows: List[Dict[str, Any]] = []
            if initial_labels:
                for entry in initial_labels:
                    row_id = f"relationship-row-{slugify(field.name) or field.name}-{uuid.uuid4().hex[:8]}"
                    input_id = f"input-{row_id}"
                    suggestions_id = f"suggestions-{row_id}"
                    context_payload = entry.get("context") if isinstance(entry.get("context"), dict) else {}
                    row_data = {
                        "row_id": row_id,
                        "input_id": input_id,
                        "suggestions_id": suggestions_id,
                        "display_value": entry.get("label", ""),
                        "stored_value": entry.get("uri", ""),
                        "suggestion_url": meta.get("base_suggestion_url", ""),
                        "resource_id": entry.get("resource_id"),
                        "join_resource_id": entry.get("join_resource_id"),
                        "context": context_payload,
                    }
                    rows.append(row_data)
            else:
                row_id = f"relationship-row-{slugify(field.name) or field.name}-{uuid.uuid4().hex[:8]}"
                input_id = f"input-{row_id}"
                suggestions_id = f"suggestions-{row_id}"
                rows.append({
                    "row_id": row_id,
                    "input_id": input_id,
                    "suggestions_id": suggestions_id,
                    "display_value": "",
                    "stored_value": "",
                    "suggestion_url": meta.get("base_suggestion_url", ""),
                    "context": {},
                })
            if context_specs:
                context_options_map = meta.get("context_options") or {}
                for row_data in rows:
                    normalized_context = row_data.get("context") if isinstance(row_data.get("context"), dict) else {}
                    context_items: List[Dict[str, Any]] = []
                    for spec in context_specs:
                        column_name = spec.get("column") or spec.get("column_name") or ""
                        slug = spec.get("slug") or slugify(column_name).replace("-", "_")
                        value = (
                            normalized_context.get(slug)
                            or normalized_context.get(column_name)
                            or ""
                        )
                        options = context_options_map.get(column_name) or context_options_map.get(slug) or []
                        context_items.append(
                            {
                                "label": column_name,
                                "slug": slug,
                                "value": value,
                                "options": options,
                            }
                        )
                    row_data["context_items"] = context_items
            else:
                for row_data in rows:
                    row_data.setdefault("context_items", [])
            join_rows = rows

        # Build widget context for multi-value fields using relationship rows
        widget_context = None
        if fk_info and meta.get("is_multi_value"):
            primary_property_uri = _select_primary_search_property(meta)

            import uuid

            rows: List[Dict[str, str]] = []
            if initial_labels:
                for entry in initial_labels:
                    row_id = f"relationship-row-{slugify(field.name) or field.name}-{uuid.uuid4().hex[:8]}"
                    input_id = f"input-{row_id}"
                    suggestions_id = f"suggestions-{row_id}"
                    rows.append(
                        {
                            "row_id": row_id,
                            "input_id": input_id,
                            "suggestions_id": suggestions_id,
                            "display_value": entry.get("label", ""),
                            "stored_value": entry.get("uri", ""),
                            "suggestion_url": meta.get("base_suggestion_url", ""),
                            "resource_id": entry.get("resource_id"),
                        }
                    )
            else:
                row_id = f"relationship-row-{slugify(field.name) or field.name}-{uuid.uuid4().hex[:8]}"
                input_id = f"input-{row_id}"
                suggestions_id = f"suggestions-{row_id}"
                rows.append(
                    {
                        "row_id": row_id,
                        "input_id": input_id,
                        "suggestions_id": suggestions_id,
                        "display_value": "",
                        "stored_value": "",
                        "suggestion_url": meta.get("base_suggestion_url", ""),
                    }
                )

            property_select_id = f"relationship-property-{slugify(field.name) or field.name}"
            meta["selected_property"] = primary_property_uri or ""

            # Ensure hidden form field does not submit stale JSON payloads
            form.initial[field.name] = ""
            if hasattr(field, "form"):
                field.form.initial[field.name] = ""
            if field.name in form.fields:
                form.fields[field.name].initial = ""
                widget_attrs = getattr(form.fields[field.name].widget, "attrs", None)
                if isinstance(widget_attrs, dict):
                    widget_attrs["value"] = ""

            widget_context = {
                "field_name": field.name,
                "dataset_name": dataset_name,
                "mapping_id": schema_service.mapping.id,
                "rows": rows,
                "search_properties": meta.get("search_properties", []),
                "selected_property": primary_property_uri or "",
                "property_select_id": property_select_id,
            }
        elif meta.get("is_join"):
            property_select_id = f"relationship-property-{slugify(field.name) or field.name}"
            widget_context = {
                "field_name": field.name,
                "dataset_name": dataset_name,
                "mapping_id": schema_service.mapping.id,
                "rows": join_rows,
                "search_properties": meta.get("search_properties", []),
                "selected_property": meta.get("selected_property", ""),
                "property_select_id": property_select_id,
            }

        rows_for_item = []
        if meta.get("is_join"):
            rows_for_item = join_rows
        elif widget_context:
            rows_for_item = widget_context.get("rows", [])

        fields_with_metadata.append({
            "field": field,
            "meta": meta,
            "search_url": search_url,
            "target_id": target_id,
            "initial_labels": initial_labels,
            "widget_context": widget_context,
            "rows": rows_for_item,
        })

    return fields_with_metadata


class SimplifiedProjectEditView(LoginRequiredMixin, View):
    """
    Simplified project edit view using legacy workspace infrastructure.

    Shows only a subset of fields but uses the same relationship handling,
    URI resolution, and search capabilities as the full workspace.
    """

    def get(self, request: HttpRequest) -> HttpResponse:
        """Render the edit form with existing project data."""
        schema_service = _get_schema_service(request)
        if not schema_service:
            return HttpResponseRedirect("/metadata/metadata-entry/")

        entity_uri = request.GET.get("uri", "")
        if not entity_uri:
            return HttpResponseBadRequest("Missing uri parameter")

        dataset_name = "Projekt"
        visible_fields = SIMPLIFIED_FIELD_CONFIG.get(dataset_name, [])

        # Get field metadata from schema
        field_metadata = schema_service.get_field_metadata(dataset_name)
        if dataset_name == PROJECT_DATASET_NAME:
            field_metadata = _ensure_project_link_field(field_metadata)

        # Augment with joins BEFORE filtering (to convert multi-value FKs to relationships)
        field_metadata, join_field_map = schema_service.augment_field_metadata_with_joins(
            dataset_name,
            field_metadata,
        )

        # Filter to only show simplified fields (AFTER augmentation)
        field_metadata = _filter_field_metadata(field_metadata, visible_fields)

        # Load existing entity data (same as legacy workspace)
        initial_data: Optional[Dict[str, object]] = None
        entity_label: Optional[str] = None
        load_error = False

        try:
            logger.info(f"=" * 80)
            logger.info(f"Loading project: {entity_uri}")
            logger.info(f"=" * 80)

            loaded = schema_service.load_entity_by_uri(dataset_name, entity_uri)
            if loaded:
                initial_data = loaded
                entity_label = _infer_entity_label(schema_service, entity_uri, dataset_name)
                logger.info(f"✅ Loaded {len(loaded)} fields")
                logger.info(f"   Entity label: {entity_label}")
            else:
                load_error = True
                logger.warning(f"❌ No data loaded for {entity_uri}")
        except Exception as e:
            load_error = True
            logger.exception(f"❌ Error loading project: {e}")

        # Create form with loaded data (same as legacy workspace)
        form = DatasetEntityForm(
            field_metadata=field_metadata,
            initial=initial_data,
            disable_anchors=True,  # We're editing, not creating
        )

        # Collect relationship values (same as legacy workspace)
        read_only_relationships: List[Dict[str, Any]] = []
        if entity_uri:
            relationships = schema_service.collect_relationship_values(
                dataset_name=dataset_name,
                entity_uri=entity_uri,
                field_metadata=field_metadata,
                join_field_map=join_field_map,
            )
            # Apply relationship initial values to form
            from arkumu.metadata.views.schema_workspace_views import _apply_relationship_initials
            read_only_relationships = _apply_relationship_initials(
                service=schema_service,
                form=form,
                relationships=relationships,
            )

        # Enrich FK field metadata with resolved labels (same as legacy workspace)
        fields_with_metadata = _enrich_fk_metadata(
            form=form,
            field_metadata=field_metadata,
            schema_service=schema_service,
            dataset_name=dataset_name,
            entity_uri=entity_uri,
        )
        relationship_fields_sorted = [
            item for item in fields_with_metadata if item["meta"].get("is_join")
        ]
        tab_sections = _build_tab_sections(dataset_name, fields_with_metadata, relationship_fields_sorted)

        # Render the form
        context = {
            "form": form,
            "fields_with_metadata": fields_with_metadata,
            "tab_sections": tab_sections,
            "entity_uri": entity_uri,
            "entity_label": entity_label,
            "dataset_name": dataset_name,
            "mapping_id": schema_service.mapping.id,
            "load_error": load_error,
            "read_only_relationships": read_only_relationships,
            "title": "Projekt bearbeiten",
            "description": "Aktualisiere die wichtigsten Angaben für dieses Projekt.",
        }

        return render(request, "metadata/simplified_workspace/edit_project.html", context)

    def post(self, request: HttpRequest) -> HttpResponse:
        """Save the edited project data."""
        schema_service = _get_schema_service(request)
        if not schema_service:
            return HttpResponseRedirect("/metadata/metadata-entry/")

        dataset_name = "Projekt"
        entity_uri = request.POST.get("entity_uri") or None

        if not entity_uri:
            return HttpResponseBadRequest("Missing entity_uri")

        # Get field metadata and augment with joins (for relationship handling)
        field_metadata = schema_service.get_field_metadata(dataset_name)
        if dataset_name == PROJECT_DATASET_NAME:
            field_metadata = _ensure_project_link_field(field_metadata)
        field_metadata, join_field_map = schema_service.augment_field_metadata_with_joins(
            dataset_name,
            field_metadata,
        )
        visible_fields = SIMPLIFIED_FIELD_CONFIG.get(dataset_name, [])
        field_metadata = _filter_field_metadata(field_metadata, visible_fields)
        join_field_map = {
            name: relationship
            for name, relationship in join_field_map.items()
            if name in field_metadata
        }

        # Create form with POST data
        form = DatasetEntityForm(
            request.POST,
            field_metadata=field_metadata,
            disable_anchors=True,
        )

        fields_with_metadata = _enrich_fk_metadata(
            form=form,
            field_metadata=field_metadata,
            schema_service=schema_service,
            dataset_name=dataset_name,
            entity_uri=entity_uri,
        )
        relationship_fields_sorted = [
            item for item in fields_with_metadata if item["meta"].get("is_join")
        ]
        tab_sections = _build_tab_sections(dataset_name, fields_with_metadata, relationship_fields_sorted)

        if form.is_valid():
            try:
                entity_data = form.cleaned_entity_data()
                entity_data, join_payloads, multi_fk_payloads = _collect_relationship_payloads(
                    request,
                    entity_data,
                    field_metadata,
                    join_field_map,
                    entity_uri=entity_uri,
                )

                # Save entity (includes FK fields and relationships)
                saved_uri, created = schema_service.save_entity(
                    dataset_name=dataset_name,
                    entity_data=entity_data,
                    entity_uri=entity_uri,
                )

                for field_name, related_records in join_payloads.items():
                    relationship = join_field_map.get(field_name)
                    if relationship is None:
                        continue
                    schema_service.sync_join_relationship(
                        entity_uri=saved_uri,
                        relationship=relationship,
                        related_items=related_records,
                    )

                for field_name, related_uris in multi_fk_payloads.items():
                    meta = field_metadata.get(field_name, {})
                    property_uri = meta.get("property_uri")
                    if not property_uri:
                        continue
                    schema_service.save_multi_fk_relationship(
                        entity_uri=saved_uri,
                        property_uri=property_uri,
                        related_uris=related_uris,
                    )

                preview_field_name = _get_preview_field_name(fields_with_metadata)
                preview_key = ""
                if preview_field_name:
                    preview_key = form.cleaned_data.get(preview_field_name, "") or ""
                _update_project_preview_link(
                    project_uri=saved_uri,
                    preview_key=preview_key,
                    organization_code=schema_service.organization.code,
                )

                logger.info(f"✅ Saved project: {saved_uri} (created={created})")

                # Redirect back to metadata entry
                return HttpResponseRedirect("/metadata/metadata-entry/?organization=" + schema_service.organization.code)

            except Exception as e:
                logger.exception(f"❌ Error saving project: {e}")
                # Re-render form with error
                context = {
                    "form": form,
                    "fields_with_metadata": fields_with_metadata,
                    "tab_sections": tab_sections,
                    "entity_uri": entity_uri,
                    "dataset_name": dataset_name,
                    "error": str(e),
                    "title": "Projekt bearbeiten",
                    "mapping_id": schema_service.mapping.id,
                }
                return render(request, "metadata/simplified_workspace/edit_project.html", context)

        else:
            # Form validation failed
            logger.warning(f"Form validation failed: {form.errors}")
            context = {
                "form": form,
                "fields_with_metadata": fields_with_metadata,
                "tab_sections": tab_sections,
                "entity_uri": entity_uri,
                "dataset_name": dataset_name,
                "title": "Projekt bearbeiten",
                "mapping_id": schema_service.mapping.id,
            }
            return render(request, "metadata/simplified_workspace/edit_project.html", context)


class SimplifiedProjectCreateView(LoginRequiredMixin, View):
    """
    Simplified project create view using the same infrastructure as edit view.

    Shows only a subset of fields but uses the same relationship handling,
    URI resolution, and search capabilities as the full workspace.
    """

    def get(self, request: HttpRequest) -> HttpResponse:
        """Render the create form for a new project."""
        # Get organization from query parameter or user
        org_code = request.GET.get("organization")
        if org_code:
            try:
                organization = Organization.objects.get(code=org_code)
            except Organization.DoesNotExist:
                organization = getattr(request.user, "organization", None)
        else:
            organization = getattr(request.user, "organization", None)

        if not organization:
            return HttpResponseRedirect("/metadata/metadata-entry/")

        # Get mapping using workspace coordinator (gets promoted/derived mapping from session)
        from arkumu.common.mixins.base_coordinator import BaseCoordinatorMixin
        workspace_coordinator = BaseCoordinatorMixin()

        queryset = Mapping.objects.filter(organization_id=organization.code).order_by("-created_at")
        mapping_data = workspace_coordinator.get_current_mapping(request)
        if mapping_data:
            mapping = queryset.filter(id=mapping_data.get("id")).first()
        else:
            mapping = queryset.first()

        if not mapping:
            return HttpResponseRedirect("/metadata/metadata-entry/")

        schema_service = SchemaWorkspaceService(mapping=mapping, organization=organization)

        dataset_name = "Projekt"
        visible_fields = SIMPLIFIED_FIELD_CONFIG.get(dataset_name, [])

        # Debug logging
        logger.info(f"🔍 Create view - Organization: {organization.code}")
        logger.info(f"🔍 Create view - Mapping: {mapping.id}")
        logger.info(f"🔍 Create view - Visible fields count: {len(visible_fields)}")

        # Get field metadata from schema
        field_metadata = schema_service.get_field_metadata(dataset_name)
        if dataset_name == PROJECT_DATASET_NAME:
            field_metadata = _ensure_project_link_field(field_metadata)

        # Augment with joins BEFORE filtering (to convert multi-value FKs to relationships)
        field_metadata, join_field_map = schema_service.augment_field_metadata_with_joins(
            dataset_name,
            field_metadata,
        )

        # Filter to only show simplified fields (AFTER augmentation)
        field_metadata = _filter_field_metadata(field_metadata, visible_fields)

        # Create empty form (no initial data)
        form = DatasetEntityForm(
            field_metadata=field_metadata,
            initial=None,
            disable_anchors=False,  # Enable anchors for creating
        )

        # Enrich FK field metadata with resolved labels
        fields_with_metadata = _enrich_fk_metadata(
            form=form,
            field_metadata=field_metadata,
            schema_service=schema_service,
            dataset_name=dataset_name,
            entity_uri=None,
        )
        relationship_fields_sorted = [
            item for item in fields_with_metadata if item["meta"].get("is_join")
        ]
        tab_sections = _build_tab_sections(dataset_name, fields_with_metadata, relationship_fields_sorted)

        # Get visibility choices
        from arkumu.metadata.models.resource import PublicAccessLevel
        visibility_choices = [
            {"value": PublicAccessLevel.PRIVATE.value, "label": "Private - Nur Organisation"},
            {"value": PublicAccessLevel.RESTRICTED.value, "label": "Restricted - Authentifizierte Nutzer"},
            {"value": PublicAccessLevel.PUBLIC.value, "label": "Public - Öffentlich im Katalog"},
        ]

        # Render the form
        context = {
            "form": form,
            "fields_with_metadata": fields_with_metadata,
            "tab_sections": tab_sections,
            "entity_uri": None,
            "entity_label": None,
            "dataset_name": dataset_name,
            "mapping_id": schema_service.mapping.id,
            "load_error": False,
            "read_only_relationships": [],
            "title": "Neues Projekt erstellen",
            "description": "Füge ein neues Projekt hinzu.",
            "visibility_choices": visibility_choices,
            "current_visibility": PublicAccessLevel.PRIVATE.value,  # Default to private
        }

        return render(request, "metadata/simplified_workspace/edit_project.html", context)

    def post(self, request: HttpRequest) -> HttpResponse:
        """Save the new project data."""
        # Get organization from query parameter or user (same as GET)
        org_code = request.GET.get("organization")
        if org_code:
            try:
                organization = Organization.objects.get(code=org_code)
            except Organization.DoesNotExist:
                organization = getattr(request.user, "organization", None)
        else:
            organization = getattr(request.user, "organization", None)

        if not organization:
            return HttpResponseRedirect("/metadata/metadata-entry/")

        # Get mapping using workspace coordinator (gets promoted/derived mapping from session)
        from arkumu.common.mixins.base_coordinator import BaseCoordinatorMixin
        workspace_coordinator = BaseCoordinatorMixin()

        queryset = Mapping.objects.filter(organization_id=organization.code).order_by("-created_at")
        mapping_data = workspace_coordinator.get_current_mapping(request)
        if mapping_data:
            mapping = queryset.filter(id=mapping_data.get("id")).first()
        else:
            mapping = queryset.first()

        if not mapping:
            return HttpResponseRedirect("/metadata/metadata-entry/")

        schema_service = SchemaWorkspaceService(mapping=mapping, organization=organization)

        dataset_name = "Projekt"

        # Get field metadata and augment with joins (for relationship handling)
        field_metadata = schema_service.get_field_metadata(dataset_name)
        if dataset_name == PROJECT_DATASET_NAME:
            field_metadata = _ensure_project_link_field(field_metadata)
        field_metadata, join_field_map = schema_service.augment_field_metadata_with_joins(
            dataset_name,
            field_metadata,
        )
        visible_fields = SIMPLIFIED_FIELD_CONFIG.get(dataset_name, [])
        field_metadata = _filter_field_metadata(field_metadata, visible_fields)
        join_field_map = {
            name: relationship
            for name, relationship in join_field_map.items()
            if name in field_metadata
        }

        # Create form with POST data
        form = DatasetEntityForm(
            request.POST,
            field_metadata=field_metadata,
            disable_anchors=False,
        )

        fields_with_metadata = _enrich_fk_metadata(
            form=form,
            field_metadata=field_metadata,
            schema_service=schema_service,
            dataset_name=dataset_name,
            entity_uri=None,
        )
        relationship_fields_sorted = [
            item for item in fields_with_metadata if item["meta"].get("is_join")
        ]
        tab_sections = _build_tab_sections(dataset_name, fields_with_metadata, relationship_fields_sorted)

        if form.is_valid():
            try:
                entity_data = form.cleaned_entity_data()
                entity_data, join_payloads, multi_fk_payloads = _collect_relationship_payloads(
                    request,
                    entity_data,
                    field_metadata,
                    join_field_map,
                    entity_uri=None,
                )

                # Save entity (creates new entity with auto-generated URI)
                saved_uri, created = schema_service.save_entity(
                    dataset_name=dataset_name,
                    entity_data=entity_data,
                    entity_uri=None,
                )

                for field_name, related_records in join_payloads.items():
                    relationship = join_field_map.get(field_name)
                    if relationship is None:
                        continue
                    schema_service.sync_join_relationship(
                        entity_uri=saved_uri,
                        relationship=relationship,
                        related_items=related_records,
                    )

                for field_name, related_uris in multi_fk_payloads.items():
                    meta = field_metadata.get(field_name, {})
                    property_uri = meta.get("property_uri")
                    if not property_uri:
                        continue
                    schema_service.save_multi_fk_relationship(
                        entity_uri=saved_uri,
                        property_uri=property_uri,
                        related_uris=related_uris,
                    )

                # Set visibility on the Resource
                visibility = request.POST.get("visibility", "private")
                resource = Resource.objects.filter(uri=saved_uri).first()
                if resource:
                    resource.public_access_level = visibility
                    resource.save()
                    logger.info(f"✅ Set visibility to {visibility} for {saved_uri}")

                preview_field_name = _get_preview_field_name(fields_with_metadata)
                preview_key = ""
                if preview_field_name:
                    preview_key = form.cleaned_data.get(preview_field_name, "") or ""
                _update_project_preview_link(
                    project_uri=saved_uri,
                    preview_key=preview_key,
                    organization_code=schema_service.organization.code,
                )

                logger.info(f"✅ Created project: {saved_uri}")

                # Redirect back to metadata entry
                return HttpResponseRedirect("/metadata/metadata-entry/?organization=" + schema_service.organization.code)

            except Exception as e:
                logger.exception(f"❌ Error creating project: {e}")
                # Re-render form with error
                context = {
                    "form": form,
                    "fields_with_metadata": fields_with_metadata,
                    "tab_sections": tab_sections,
                    "entity_uri": None,
                    "dataset_name": dataset_name,
                    "error": str(e),
                    "title": "Neues Projekt erstellen",
                    "mapping_id": schema_service.mapping.id,
                }
                return render(request, "metadata/simplified_workspace/edit_project.html", context)

        else:
            # Form validation failed
            logger.warning(f"Form validation failed: {form.errors}")
            context = {
                "form": form,
                "fields_with_metadata": fields_with_metadata,
                "tab_sections": tab_sections,
                "entity_uri": None,
                "dataset_name": dataset_name,
                "title": "Neues Projekt erstellen",
                "mapping_id": schema_service.mapping.id,
            }
            return render(request, "metadata/simplified_workspace/edit_project.html", context)


class SimplifiedEreignisEditView(LoginRequiredMixin, View):
    """
    Simplified ereignis edit view using legacy workspace infrastructure.

    Shows only a subset of fields but uses the same relationship handling,
    URI resolution, and search capabilities as the full workspace.
    """

    def get(self, request: HttpRequest) -> HttpResponse:
        """Render the edit form with existing ereignis data."""
        schema_service = _get_schema_service(request)
        if not schema_service:
            return HttpResponseRedirect("/metadata/metadata-entry/")

        entity_uri = request.GET.get("uri", "")
        if not entity_uri:
            return HttpResponseBadRequest("Missing uri parameter")

        dataset_name = "Ereignis"
        visible_fields = SIMPLIFIED_FIELD_CONFIG.get(dataset_name, [])

        # Get field metadata from schema
        field_metadata = schema_service.get_field_metadata(dataset_name)

        # Augment with joins BEFORE filtering (to convert multi-value FKs to relationships)
        field_metadata, join_field_map = schema_service.augment_field_metadata_with_joins(
            dataset_name,
            field_metadata,
        )

        # Filter to only show simplified fields (AFTER augmentation)
        field_metadata = _filter_field_metadata(field_metadata, visible_fields)

        # Load existing entity data (same as legacy workspace)
        initial_data: Optional[Dict[str, object]] = None
        entity_label: Optional[str] = None
        load_error = False

        try:
            logger.info(f"=" * 80)
            logger.info(f"Loading ereignis: {entity_uri}")
            logger.info(f"=" * 80)

            loaded = schema_service.load_entity_by_uri(dataset_name, entity_uri)
            if loaded:
                initial_data = loaded
                entity_label = _infer_entity_label(schema_service, entity_uri, dataset_name)
                logger.info(f"✅ Loaded {len(loaded)} fields")
                logger.info(f"   Entity label: {entity_label}")
            else:
                load_error = True
                logger.warning(f"❌ No data loaded for {entity_uri}")
        except Exception as e:
            load_error = True
            logger.exception(f"❌ Error loading ereignis: {e}")

        # Create form with loaded data (same as legacy workspace)
        form = DatasetEntityForm(
            field_metadata=field_metadata,
            initial=initial_data,
            disable_anchors=True,  # We're editing, not creating
        )

        # Collect relationship values (same as legacy workspace)
        read_only_relationships: List[Dict[str, Any]] = []
        if entity_uri:
            relationships = schema_service.collect_relationship_values(
                dataset_name=dataset_name,
                entity_uri=entity_uri,
                field_metadata=field_metadata,
                join_field_map=join_field_map,
            )
            # Apply relationship initial values to form
            from arkumu.metadata.views.schema_workspace_views import _apply_relationship_initials
            read_only_relationships = _apply_relationship_initials(
                service=schema_service,
                form=form,
                relationships=relationships,
            )

        # Enrich FK field metadata with resolved labels (same as legacy workspace)
        fields_with_metadata = _enrich_fk_metadata(
            form=form,
            field_metadata=field_metadata,
            schema_service=schema_service,
            dataset_name=dataset_name,
            entity_uri=entity_uri,
        )
        relationship_fields_sorted = [
            item for item in fields_with_metadata if item["meta"].get("is_join")
        ]
        tab_sections = _build_tab_sections(dataset_name, fields_with_metadata, relationship_fields_sorted)

        # Render the form
        context = {
            "form": form,
            "fields_with_metadata": fields_with_metadata,
            "tab_sections": tab_sections,
            "entity_uri": entity_uri,
            "entity_label": entity_label,
            "dataset_name": dataset_name,
            "mapping_id": schema_service.mapping.id,
            "load_error": load_error,
            "read_only_relationships": read_only_relationships,
            "title": "Ereignis bearbeiten",
            "description": "Aktualisiere die wichtigsten Angaben für dieses Ereignis.",
        }

        return render(request, "metadata/simplified_workspace/edit_ereignis.html", context)

    def post(self, request: HttpRequest) -> HttpResponse:
        """Save the edited ereignis data."""
        schema_service = _get_schema_service(request)
        if not schema_service:
            return HttpResponseRedirect("/metadata/metadata-entry/")

        dataset_name = "Ereignis"
        entity_uri = request.POST.get("entity_uri") or None

        if not entity_uri:
            return HttpResponseBadRequest("Missing entity_uri")

        # Get field metadata and augment with joins (for relationship handling)
        field_metadata = schema_service.get_field_metadata(dataset_name)
        field_metadata, join_field_map = schema_service.augment_field_metadata_with_joins(
            dataset_name,
            field_metadata,
        )
        visible_fields = SIMPLIFIED_FIELD_CONFIG.get(dataset_name, [])
        field_metadata = _filter_field_metadata(field_metadata, visible_fields)
        join_field_map = {
            name: relationship
            for name, relationship in join_field_map.items()
            if name in field_metadata
        }

        # Create form with POST data
        form = DatasetEntityForm(
            request.POST,
            field_metadata=field_metadata,
            disable_anchors=True,
        )

        fields_with_metadata = _enrich_fk_metadata(
            form=form,
            field_metadata=field_metadata,
            schema_service=schema_service,
            dataset_name=dataset_name,
            entity_uri=entity_uri,
        )
        relationship_fields_sorted = [
            item for item in fields_with_metadata if item["meta"].get("is_join")
        ]
        tab_sections = _build_tab_sections(dataset_name, fields_with_metadata, relationship_fields_sorted)

        if form.is_valid():
            try:
                entity_data = form.cleaned_entity_data()
                entity_data, join_payloads, multi_fk_payloads = _collect_relationship_payloads(
                    request,
                    entity_data,
                    field_metadata,
                    join_field_map,
                    entity_uri=entity_uri,
                )

                # Save entity (includes FK fields and relationships)
                saved_uri, created = schema_service.save_entity(
                    dataset_name=dataset_name,
                    entity_data=entity_data,
                    entity_uri=entity_uri,
                )

                for field_name, related_records in join_payloads.items():
                    relationship = join_field_map.get(field_name)
                    if relationship is None:
                        continue
                    schema_service.sync_join_relationship(
                        entity_uri=saved_uri,
                        relationship=relationship,
                        related_items=related_records,
                    )

                for field_name, related_uris in multi_fk_payloads.items():
                    meta = field_metadata.get(field_name, {})
                    property_uri = meta.get("property_uri")
                    if not property_uri:
                        continue
                    schema_service.save_multi_fk_relationship(
                        entity_uri=saved_uri,
                        property_uri=property_uri,
                        related_uris=related_uris,
                    )

                logger.info(f"✅ Saved ereignis: {saved_uri} (created={created})")

                # Redirect back to metadata entry
                return HttpResponseRedirect("/metadata/metadata-entry/?organization=" + schema_service.organization.code)

            except Exception as e:
                logger.exception(f"❌ Error saving ereignis: {e}")
                # Re-render form with error
                context = {
                    "form": form,
                    "fields_with_metadata": fields_with_metadata,
                    "tab_sections": tab_sections,
                    "entity_uri": entity_uri,
                    "dataset_name": dataset_name,
                    "error": str(e),
                    "title": "Ereignis bearbeiten",
                    "mapping_id": schema_service.mapping.id,
                }
                return render(request, "metadata/simplified_workspace/edit_ereignis.html", context)

        else:
            # Form validation failed
            logger.warning(f"Form validation failed: {form.errors}")
            context = {
                "form": form,
                "fields_with_metadata": fields_with_metadata,
                "tab_sections": tab_sections,
                "entity_uri": entity_uri,
                "dataset_name": dataset_name,
                "title": "Ereignis bearbeiten",
                "mapping_id": schema_service.mapping.id,
            }
            return render(request, "metadata/simplified_workspace/edit_ereignis.html", context)
