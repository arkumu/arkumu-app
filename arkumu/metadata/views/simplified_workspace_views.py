"""
Simplified workspace views for metadata entry.

These views use the same infrastructure as the legacy workspace
(SchemaWorkspaceService, DatasetEntityForm, relationship handling)
but only show a subset of fields for a simplified user experience.
"""
from __future__ import annotations

import json
import logging
import uuid
from urllib.parse import urlsplit
from typing import Any, Dict, List, Optional, Tuple, Union, Set

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import render
from django.template.loader import render_to_string
from django.db.models import Q
from django.urls import reverse
from django.utils.html import escape
from django.utils.http import urlencode
from django.utils.text import slugify
from django.views import View
from django.views.decorators.http import require_http_methods

from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.schema_workspace import (
    DatasetEntityForm,
    SchemaWorkspaceService,
)
from arkumu.metadata.constants import (
    ACTOR_EVENT_ACTOR_DATASET,
    ACTOR_EVENT_ACTOR_SEARCH_PROPERTY,
    ACTOR_EVENT_FIELD_NAME,
    ACTOR_EVENT_FLAG_CONTEXT_SPECS,
    ACTOR_EVENT_JOIN_DATASET,
    ACTOR_EVENT_ROLE_CONTEXT_COLUMN,
    ACTOR_EVENT_ROLE_DATASET,
    ACTOR_EVENT_ROLE_PROPERTY_URI,
    ACTOR_EVENT_ROLE_SEARCH_PROPERTY,
)
from arkumu.metadata.services.entity_label_service import infer_entity_label as _infer_entity_label
from arkumu.metadata.utils.uri_placeholders import decode_placeholder_uri
from arkumu.users.models import Organization
from arkumu.storage.models import S3FileObject
from arkumu.metadata.models.resource import Resource, PublicAccessLevel
from arkumu.common.mixins.base_coordinator import BaseCoordinatorMixin
from arkumu.common.uri_utils import slugify_uri_part

logger = logging.getLogger(__name__)

_VISIBILITY_OPTION_DEFINITIONS: Tuple[Tuple[PublicAccessLevel, str], ...] = (
    (
        PublicAccessLevel.PRIVATE,
        "Private - Nur Organisation",
    ),
    (
        PublicAccessLevel.RESTRICTED,
        "Restricted - Authentifizierte Nutzer",
    ),
    (
        PublicAccessLevel.PUBLIC,
        "Public - Öffentlich im Katalog",
    ),
)
_VALID_VISIBILITY_VALUES: Set[str] = {level.value for level, _ in _VISIBILITY_OPTION_DEFINITIONS}


def _build_visibility_choices() -> List[Dict[str, str]]:
    return [
        {"value": level.value, "label": label}
        for level, label in _VISIBILITY_OPTION_DEFINITIONS
    ]


def _normalize_visibility_value(raw_value: Optional[str], fallback: Optional[str] = None) -> str:
    if raw_value in _VALID_VISIBILITY_VALUES:
        return raw_value
    if fallback in _VALID_VISIBILITY_VALUES:
        return fallback
    return PublicAccessLevel.PRIVATE.value


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
                    "name": ACTOR_EVENT_FIELD_NAME,
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
                    # Prefer human-friendly labels so configuration
                    # works across organizations with different local URIs.
                    # We search primarily by title and filename.
                    "search_property": ["Titel", "Dateiname"],
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
    "AkteurIn": [
        {
            "key": "identitaet",
            "title": "Identität",
            "badge": "Name und Identifikation",
            "fields": [
                "Deutscher Name",
                "Englischer Name",
                "Alternativer Name",
                "Vorangestellter Titel",
                "Nachgestellter Titel",
                "Geschlecht",
                "Nicht-öffentlicher Name",
                "Nicht-öffentlicher Name (Begründung)",
            ],
        },
        {
            "key": "lebensdaten",
            "title": "Lebensdaten & Orte",
            "badge": "Zeitliche Daten",
            "fields": [
                "Frühestes Geburtsdatum",
                "Spätestes Geburtsdatum",
                "Frühestes Sterbedatum",
                "Spätestes Sterbedatum",
                {
                    "name": "Geburtsort",
                    "search_property": "Ortsname",
                },
                {
                    "name": "Sterbeort",
                    "search_property": "Ortsname",
                },
                {
                    "name": "Gründungsort",
                    "search_property": "Ortsname",
                },
                {
                    "name": "Auflösungsort",
                    "search_property": "Ortsname",
                },
                "Wirkungsbeginn",
                "Wirkungsende",
                {
                    "name": "Wirkungsort",
                    "search_property": "Ortsname",
                },
            ],
        },
        {
            "key": "rollen-und-texte",
            "title": "Rollen & Beschreibungen",
            "badge": "Beteiligungen",
            "fields": [
                {
                    "name": "Beruf und Tätigkeit",
                    "search_property": "Bezeichnung",
                },
                "Deutsche Kurzbiografie",
                "Englische Kurzbiografie",
                "Deutscher Kommentar",
                "Englischer Kommentar",
                "Interner Kommentar",
            ],
        },
        {
            "key": "normdaten",
            "title": "Normdaten & Links",
            "badge": "Identifier",
            "fields": [
                "GND-Nummer",
                "VIAF-ID",
                "LCCN-ID",
                "OrcID",
                "Wikidata-ID",
                "Webseite der AkteurIn",
                "Andere Normdaten",
            ],
        },
    ],
    "Ort": [
        {
            "key": "grundinformationen",
            "title": "Grundinformationen",
            "badge": "Name & Kennungen",
            "fields": [
                "Deutscher Name des Ortes",
                "Wikidata-ID",
            ],
        },
    ],
    "Digitales_Objekt": [
        {
            "key": "basis",
            "title": "Basisdaten",
            "badge": "Datei & Typ",
            "fields": [
                "Dateiname",
                "Dateipfad",
                "Medientyp",
                "Objekttyp",
                "Entstehung",
                "Einlieferer",
                "Dateipaket",
            ],
        },
        {
            "key": "beschreibung",
            "title": "Beschreibung",
            "badge": "Inhalte",
            "fields": [
                "Deutsche inhaltliche Beschreibung",
                "Englische inhaltliche Beschreibung",
                "Bildbeschreibung (deutsch)",
                "Bildbeschreibung (englisch)",
                "Deutscher Kommentar",
                "Englischer Kommentar",
                "Interner Kommentar",
                "Projektkompilation",
                "Wesentliche Eigenschaften (deutsch)",
                "Wesentliche Eigenschaften (englisch)",
            ],
        },
        {
            "key": "technik",
            "title": "Technische Angaben",
            "badge": "Metadaten",
            "fields": [
                "EQ",
                "DCP-Art",
                "Tonformat",
                "Tonmischfassung",
                "Sprachfassung",
                "Originalsprache",
                "Untertitelsprache",
                "Systemvoraussetzungen",
                "Erhaltungstyp",
                "Lizenzstatus",
                "Anzeigestatus",
                "Derivatkopie-Nummer",
                "Wird im Loop abgespielt",
                "ist arkumu-Preview",
                "KHM-Internetfreigabestufe",
                "Datensatzerstellung beim Einlieferer",
                "Letzte Datensatzmodifikation beim Einlieferer",
            ],
        },
        {
            "key": "verknuepfungen",
            "title": "Verknüpfungen",
            "badge": "Bezüge",
            "fields": [
                {
                    "name": "Ereignisse",
                    "label": "Verknüpfte Ereignisse",
                },
                {
                    "name": "Sammlungen",
                    "label": "Verknüpfte Sammlungen",
                },
                {
                    "name": "Informationsträger",
                    "label": "Informationsträger",
                },
            ],
        },
    ],
    "Equipment_und_Software": [
        {
            "key": "produkt",
            "title": "Produktinformationen",
            "badge": "Bezeichnungen",
            "fields": [
                "Deutsche (Produkt-Bezeichnung)",
                "Englische (Produkt-Bezeichnung)",
                "Hersteller",
                "Equipmentart",
            ],
        },
        {
            "key": "beschreibung",
            "title": "Beschreibungen",
            "badge": "Texte",
            "fields": [
                "Deutsche Beschreibung",
                "Englische Beschreibung",
                "Andere Normdaten",
            ],
        },
        {
            "key": "normdaten",
            "title": "Kennungen",
            "badge": "Identifier",
            "fields": [
                "GND-Nummer",
                "Wikidata-ID",
            ],
        },
        {
            "key": "verknuepfungen",
            "title": "Verknüpfungen",
            "badge": "Einsatz",
            "fields": [
                {
                    "name": "Ereignisse",
                    "label": "Verknüpfte Ereignisse",
                },
                {
                    "name": "Sammlungen",
                    "label": "Verknüpfte Sammlungen",
                },
            ],
        },
    ],
    "Alternativer_Titel": [
        {
            "key": "titel",
            "title": "Titelinformationen",
            "badge": "Titel & Sprache",
            "fields": [
                "Alternativer Titel",
                {
                    "name": "Sprache des Alternativen Titels",
                    "search_property": "Deutscher Name der Sprache",
                },
                "Alternativer Untertitel",
                {
                    "name": "Sprache des Alternativen Untertitels",
                    "search_property": "Deutscher Name der Sprache",
                },
            ],
        },
    ],
}

PROJECT_LINK_FIELD_NAME = "Verknüpftes Projekt"
PROJECT_LINK_PROPERTY_URI = "http://arkumu.org/data/properties/verknuepftes-projekt"
PROJECT_DATASET_NAME = "Projekt"
DIGITAL_OBJECT_DATASET_NAME = "Digitales_Objekt"


UNIFIED_MASK_WORKSPACE_PATH = "/metadata/unified-mask-workspace/"
UNIFIED_MASK_ENTITY_MAP = {
    "project": "project",
    "projekt": "project",
    "ereignis": "event",
    "event": "event",
    "akteur": "actor",
    "actor": "actor",
    "ort": "place",
    "place": "place",
    "sammlung": "collection",
    "collection": "collection",
    "informationstraeger": "information_carrier",
    "informationstrager": "information_carrier",
    "information_carrier": "information_carrier",
    "schlagwort": "keyword",
    "keyword": "keyword",
    "digitales_objekt": "digital_object",
    "digital_object": "digital_object",
}

PREVIEW_PICKER_FIELD_SLUGS_BY_DATASET: Dict[str, Set[str]] = {
    PROJECT_DATASET_NAME: {"vorschaubild", "vorschaubild_uri"},
    DIGITAL_OBJECT_DATASET_NAME: {"dateipfad"},
}


def _build_metadata_entry_url(
    organization_code: str | None = None,
    entity: str | None = None,
) -> str:
    params: Dict[str, str] = {}
    if organization_code:
        params["organization"] = organization_code
    if entity:
        normalized_entity = UNIFIED_MASK_ENTITY_MAP.get(entity.lower(), entity.lower())
        params["entity"] = normalized_entity
    params.setdefault("phase", "create")
    if not params:
        return UNIFIED_MASK_WORKSPACE_PATH
    return f"{UNIFIED_MASK_WORKSPACE_PATH}?{urlencode(params)}"


def _redirect_to_metadata_entry(
    organization_code: str | None = None,
    entity: str | None = None,
) -> HttpResponseRedirect:
    return HttpResponseRedirect(_build_metadata_entry_url(organization_code, entity))
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

# Datasets where anchor fields should be visible/editable in simplified forms
SIMPLIFIED_VISIBLE_ANCHORS: Set[str] = {"Ort"}

# Field-level configuration extracted from sections (search_property, label, help_text)
SIMPLIFIED_FIELD_PROPS: Dict[str, Dict[str, Dict[str, Any]]] = {
    dataset: _extract_field_config(sections)
    for dataset, sections in SIMPLIFIED_SECTION_CONFIG.items()
}

def _configured_search_properties(field_config: Dict[str, Any]) -> List[str]:
    value = field_config.get("search_property")
    if not value:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item]
    return [str(value)]


def _filter_properties_for_config(
    properties: List[Dict[str, str]],
    configured_tokens: List[str],
) -> List[Dict[str, str]]:
    if not configured_tokens:
        return properties

    normalized_tokens = [token.lower() for token in configured_tokens]
    filtered: List[Dict[str, str]] = []
    seen_keys: set[tuple] = set()

    for token in normalized_tokens:
        for prop in properties:
            label = str(prop.get("label") or "").lower()
            column = str(prop.get("column") or "").lower()
            uri_value = str(prop.get("uri") or "").lower()
            if label == token or column == token or uri_value == token:
                prop_key = (prop.get("uri"), prop.get("label"), prop.get("column"))
                if prop_key not in seen_keys:
                    filtered.append(prop)
                    seen_keys.add(prop_key)
                break

    return filtered or properties


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
    entity_uri = request.GET.get("uri", "") or request.POST.get("entity_uri", "")
    if entity_uri and "/data/" in entity_uri:
        uri_parts = entity_uri.split("/")
        if len(uri_parts) >= 6 and uri_parts[3] == "data":
            uri_org_code = uri_parts[4]
            uri_organization = Organization.objects.filter(code=uri_org_code).first()
            if uri_organization:
                organization = uri_organization
                logger.info(f"Using organization from URI: {organization.code}")

    return organization


def _extract_manifest(mapping: Mapping) -> Dict[str, Any]:
    mapping_config = mapping.mapping_config or {}
    promoted = mapping_config.get("promoted_manifest") or {}
    if isinstance(promoted, dict):
        promoted_manifest = promoted.get("schema_manifest")
        if isinstance(promoted_manifest, dict) and promoted_manifest:
            return promoted_manifest
    schema_manifest = mapping_config.get("schema_manifest")
    if isinstance(schema_manifest, dict):
        return schema_manifest
    return {}


def _extract_entity_dataset_slug(entity_uri: str) -> str:
    if not entity_uri:
        return ""
    path_parts = [part for part in urlsplit(entity_uri).path.split("/") if part]
    try:
        entities_index = path_parts.index("entities")
    except ValueError:
        return ""
    if entities_index + 1 >= len(path_parts):
        return ""
    return slugify_uri_part(path_parts[entities_index + 1])


def _resolve_dataset_name_from_uri(
    schema_service: SchemaWorkspaceService,
    *,
    entity_uri: str,
    fallback_dataset_name: str,
) -> str:
    dataset_slug = _extract_entity_dataset_slug(entity_uri)
    if not dataset_slug:
        return fallback_dataset_name

    manifest = _extract_manifest(schema_service.mapping)
    for dataset_name in manifest.keys():
        if slugify_uri_part(dataset_name) == dataset_slug:
            return dataset_name
    return fallback_dataset_name


def _select_active_mapping_for_organization(
    organization: Organization,
    request: Optional[HttpRequest] = None,
) -> Optional[Mapping]:
    """
    Select the schema mapping for simplified views.

    Preference order:
    1. Active mapping (is_active=True)
    2. Session-selected mapping (if no active mapping exists)
    3. Newest mapping
    """
    queryset = Mapping.objects.filter(organization_id=organization.code).order_by("-created_at")
    if not queryset.exists():
        return None

    entity_uri = ""
    if request is not None:
        entity_uri = request.GET.get("uri", "") or request.POST.get("entity_uri", "")

    dataset_slug = _extract_entity_dataset_slug(entity_uri)
    if dataset_slug:
        for mapping in queryset:
            manifest = _extract_manifest(mapping)
            if any(slugify_uri_part(dataset_name) == dataset_slug for dataset_name in manifest.keys()):
                return mapping

    active_mapping = queryset.filter(is_active=True).first()
    if active_mapping:
        return active_mapping

    if request is not None:
        coordinator = BaseCoordinatorMixin()
        mapping_data = coordinator.get_current_mapping(request)
        if mapping_data:
            mapping = queryset.filter(id=mapping_data.get("id")).first()
            if mapping:
                return mapping

    return queryset.first()


def _get_schema_service(request: HttpRequest) -> Optional[SchemaWorkspaceService]:
    """Get SchemaWorkspaceService for the current organization."""
    organization = _get_organization(request)
    if not organization:
        return None

    mapping = _select_active_mapping_for_organization(organization, request)
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


ACTOR_EVENT_ROLE_CONTEXT_SLUG = slugify(ACTOR_EVENT_ROLE_CONTEXT_COLUMN).replace("-", "_")


def _context_slug(column_name: str) -> str:
    """Return a normalized slug for a context column label."""

    return slugify(str(column_name or "")).replace("-", "_")


def _ensure_actor_event_context_specs(field_meta: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Guarantee context specs for the actor/event join even if schema lacks them."""

    relationship = field_meta.get("join_relationship")
    if relationship is None:
        return field_meta.get("context_columns") or []

    join_dataset = getattr(relationship, "join_dataset", "") or ""
    other_dataset = getattr(relationship, "other_dataset", "") or ""
    if join_dataset != ACTOR_EVENT_JOIN_DATASET or other_dataset.lower() != ACTOR_EVENT_ROLE_DATASET.lower():
        return field_meta.get("context_columns") or []

    context_specs = list(field_meta.get("context_columns") or [])
    existing_columns = {spec.get("column") for spec in context_specs}

    if ACTOR_EVENT_ROLE_CONTEXT_COLUMN not in existing_columns:
        context_specs.append(
            {
                "column": ACTOR_EVENT_ROLE_CONTEXT_COLUMN,
                "property_uri": ACTOR_EVENT_ROLE_PROPERTY_URI,
                "slug": ACTOR_EVENT_ROLE_CONTEXT_SLUG,
            }
        )
        existing_columns.add(ACTOR_EVENT_ROLE_CONTEXT_COLUMN)

    for flag_spec in ACTOR_EVENT_FLAG_CONTEXT_SPECS:
        column_name = flag_spec.get("column") or ""
        if not column_name or column_name in existing_columns:
            continue
        context_specs.append(
            {
                "column": column_name,
                "property_uri": flag_spec.get("property_uri"),
                "slug": _context_slug(column_name),
            }
        )
        existing_columns.add(column_name)

    field_meta["context_columns"] = context_specs
    return context_specs


def _prop_attr(prop: Any, attr: str, default: str = "") -> str:
    if isinstance(prop, dict):
        return str(prop.get(attr, default) or "")
    return str(getattr(prop, attr, default) or "")


def _resolve_role_search_property_uri(schema_service: SchemaWorkspaceService) -> str:
    """Determine the property URI used for role search suggestions."""

    try:
        schema = schema_service.get_dataset_schema(ACTOR_EVENT_ROLE_DATASET)
    except ValueError:
        return ""

    for column_name, prop in (schema.get("properties", {}) or {}).items():
        label = _prop_attr(prop, "name", column_name)
        uri = _prop_attr(prop, "uri", "")
        if not uri:
            continue
        if label == ACTOR_EVENT_ROLE_SEARCH_PROPERTY or column_name == ACTOR_EVENT_ROLE_SEARCH_PROPERTY:
            return uri
    return ""


def _resolve_actor_search_property_uri(schema_service: SchemaWorkspaceService) -> str:
    """Return the property URI used for actor search suggestions."""

    try:
        schema = schema_service.get_dataset_schema(ACTOR_EVENT_ACTOR_DATASET)
    except ValueError:
        return ""

    for column_name, prop in (schema.get("properties", {}) or {}).items():
        label = _prop_attr(prop, "name", column_name)
        uri = _prop_attr(prop, "uri", "")
        if not uri:
            continue
        if label == ACTOR_EVENT_ACTOR_SEARCH_PROPERTY or column_name == ACTOR_EVENT_ACTOR_SEARCH_PROPERTY:
            return uri
    return ""


def _build_empty_actor_join_row(field_name: str, field_meta: Dict[str, Any]) -> Dict[str, Any]:
    """Create a blank join row for the actor participation widget."""

    slug = slugify(field_name) or field_name
    row_id = f"relationship-row-{slug}-{uuid.uuid4().hex[:8]}"
    input_id = f"input-{row_id}"
    suggestions_id = f"suggestions-{row_id}"
    context_specs = field_meta.get("context_columns") or []
    context_options = field_meta.get("context_options") or {}
    context_items: List[Dict[str, Any]] = []
    for spec in context_specs:
        column_name = spec.get("column") or spec.get("column_name") or ""
        slug_value = spec.get("slug") or _context_slug(column_name)
        options = context_options.get(column_name) or context_options.get(slug_value) or []
        context_items.append(
            {
                "label": column_name,
                "slug": slug_value,
                "value": "",
                "options": options,
            }
        )
    return {
        "row_id": row_id,
        "input_id": input_id,
        "suggestions_id": suggestions_id,
        "display_value": "",
        "stored_value": "",
        "suggestion_url": field_meta.get("base_suggestion_url", ""),
        "resource_id": None,
        "join_resource_id": None,
        "context": {},
        "context_items": context_items,
    }


def _extract_context_values(row_data: Dict[str, Any]) -> Dict[str, str]:
    """Combine stored context payloads into a slugged dictionary."""

    values: Dict[str, str] = {}
    raw_context = row_data.get("context") if isinstance(row_data.get("context"), dict) else {}
    for key, value in raw_context.items():
        normalized_key = _context_slug(str(key))
        cleaned = str(value or "")
        values[normalized_key] = cleaned
        values[str(key)] = cleaned

    for item in row_data.get("context_items", []) or []:
        slug_value = item.get("slug")
        label = item.get("label")
        cleaned = str(item.get("value") or "")
        if slug_value:
            values.setdefault(slug_value, cleaned)
        if label:
            values.setdefault(label, cleaned)
    return values


def _serialize_actor_participation_card(
    *,
    schema_service: SchemaWorkspaceService,
    field_name: str,
    row_data: Dict[str, Any],
    role_property_uri: str,
    actor_property_uri: str,
) -> Dict[str, Any]:
    """Transform a join row into the card context consumed by the template."""

    row_id = row_data.get("row_id") or f"actor-card-{uuid.uuid4().hex[:8]}"
    actor_input_id = row_data.get("input_id") or f"input-{row_id}"
    actor_hidden_input_id = row_data.get("hidden_input_id") or f"{actor_input_id}-hidden"
    actor_suggestions_id = row_data.get("suggestions_id") or f"suggestions-{row_id}"
    suggestion_url = row_data.get("suggestion_url") or ""
    if suggestion_url and actor_property_uri:
        connector = "&" if "?" in suggestion_url else "?"
        suggestion_url = f"{suggestion_url}{connector}{urlencode({'property': actor_property_uri})}"

    context_values = _extract_context_values(row_data)
    role_value = context_values.get(ACTOR_EVENT_ROLE_CONTEXT_SLUG) or context_values.get(ACTOR_EVENT_ROLE_CONTEXT_COLUMN, "")
    role_label = ""
    if role_value:
        role_label = _infer_entity_label(
            schema_service,
            role_value,
            ACTOR_EVENT_ROLE_DATASET,
        )

    flags: List[Dict[str, Any]] = []
    for flag_spec in ACTOR_EVENT_FLAG_CONTEXT_SPECS:
        column_label = flag_spec.get("column") or ""
        slug_value = _context_slug(column_label)
        flag_value = context_values.get(slug_value) or context_values.get(column_label) or ""
        flags.append(
            {
                "label": column_label,
                "input_name": f"{field_name}__context__{slug_value}[]",
                "value": flag_value,
                "choices": flag_spec.get("choices", []),
            }
        )

    actor_stored_value = row_data.get("stored_value", "")
    actor_display_value = row_data.get("display_value", "")
    if actor_stored_value and actor_property_uri:
        inferred_actor_label = _infer_entity_label(
            schema_service,
            actor_stored_value,
            ACTOR_EVENT_ACTOR_DATASET,
            display_property_uri=actor_property_uri,
        )
        if inferred_actor_label:
            actor_display_value = inferred_actor_label

    return {
        "row_id": row_id,
        "join_resource_id": row_data.get("join_resource_id"),
        "actor": {
            "input_id": actor_input_id,
            "hidden_input_id": actor_hidden_input_id,
            "suggestions_id": actor_suggestions_id,
            "suggestion_url": suggestion_url,
            "display_value": actor_display_value,
            "stored_value": actor_stored_value,
            "resource_id": row_data.get("resource_id"),
            "search_property": actor_property_uri,
        },
        "role": {
            "hidden_name": f"{field_name}__context__{ACTOR_EVENT_ROLE_CONTEXT_SLUG}[]",
            "hidden_input_id": f"{row_id}-role-hidden",
            "input_id": f"{row_id}-role-input",
            "suggestions_id": f"{row_id}-role-suggestions",
            "display_value": role_label,
            "value": role_value,
            "target_dataset": ACTOR_EVENT_ROLE_DATASET,
            "search_property": role_property_uri,
            "slug": ACTOR_EVENT_ROLE_CONTEXT_SLUG,
        },
        "flags": flags,
    }


def _build_actor_participation_widget_context(
    *,
    schema_service: SchemaWorkspaceService,
    dataset_name: str,
    field_name: str,
    field_meta: Dict[str, Any],
    join_rows: Optional[List[Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    """Return widget context for the AkteurIn↔Ereignis cards."""

    relationship = field_meta.get("join_relationship")
    if relationship is None:
        return None

    if relationship.join_dataset != ACTOR_EVENT_JOIN_DATASET:
        return None

    if dataset_name != "Ereignis":
        return None

    field_meta["context_columns"] = _ensure_actor_event_context_specs(field_meta)

    actor_property_uri = _resolve_actor_search_property_uri(schema_service)
    if actor_property_uri:
        actor_search_entry = {
            "uri": actor_property_uri,
            "label": ACTOR_EVENT_ACTOR_SEARCH_PROPERTY,
            "column": ACTOR_EVENT_ACTOR_SEARCH_PROPERTY,
        }
        existing_search_props = list(field_meta.get("search_properties") or [])
        if not any(prop.get("uri") == actor_property_uri for prop in existing_search_props):
            existing_search_props.insert(0, actor_search_entry)
        field_meta["search_properties"] = existing_search_props
        field_meta["selected_property"] = actor_property_uri

    rows: List[Dict[str, Any]] = list(join_rows or [])
    if not rows:
        rows.append(_build_empty_actor_join_row(field_name, field_meta))

    role_property_uri = _resolve_role_search_property_uri(schema_service)
    cards = [
        _serialize_actor_participation_card(
            schema_service=schema_service,
            field_name=field_name,
            row_data=row,
            role_property_uri=role_property_uri,
            actor_property_uri=actor_property_uri,
        )
        for row in rows
    ]

    return {
        "component": "actor_participation",
        "field_name": field_name,
        "dataset_name": dataset_name,
        "mapping_id": schema_service.mapping.id,
        "cards": cards,
        "add_url": reverse("metadata:actor_participation_card"),
    }


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
        context_specs = _ensure_actor_event_context_specs(field_meta)
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
        if widget == "TripleCreatorWidget" and not meta.get("fk_relationship"):
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


def _decode_plain_multi_values(raw_value: Any) -> List[str]:
    if raw_value is None:
        return []

    if isinstance(raw_value, str):
        trimmed = raw_value.strip()
        if not trimmed:
            return []
        if trimmed.startswith("["):
            try:
                loaded = json.loads(trimmed)
                if isinstance(loaded, list):
                    return [str(item).strip() for item in loaded if str(item).strip()]
            except json.JSONDecodeError:
                pass
        normalized = trimmed.replace("\r\n", "\n")
        if "\n" in normalized:
            parts = normalized.split("\n")
        elif ";" in normalized:
            parts = normalized.split(";")
        else:
            parts = [normalized]
        return [part.strip() for part in parts if part.strip()]

    if isinstance(raw_value, list):
        return [str(item).strip() for item in raw_value if str(item).strip()]

    return [str(raw_value).strip()] if str(raw_value).strip() else []


def _encode_plain_multi_values(raw_value: Any) -> str:
    values = _decode_plain_multi_values(raw_value)
    return json.dumps(values) if values else ""


def _normalize_plain_multi_value_fields(
    entity_data: Dict[str, Any],
    field_metadata: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    for field_name, meta in field_metadata.items():
        if not meta.get("is_multi_value"):
            continue
        if meta.get("fk_relationship"):
            continue
        raw_value = entity_data.get(field_name)
        if raw_value in (None, ""):
            entity_data[field_name] = ""
            continue
        serialized = _encode_plain_multi_values(raw_value)
        entity_data[field_name] = serialized
    return entity_data


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


def _resolve_simplified_template_dataset_name(
    dataset_name: str,
    *,
    fallback_dataset_name: str,
) -> str:
    """Use canonical simplified form templates for mapped datasets when needed."""
    if dataset_name in SIMPLIFIED_SECTION_CONFIG:
        return dataset_name
    return fallback_dataset_name


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


def _should_use_preview_picker(dataset_name: Optional[str], field_slug: str) -> bool:
    if not field_slug:
        return False
    dataset_key = dataset_name or ""
    return field_slug in PREVIEW_PICKER_FIELD_SLUGS_BY_DATASET.get(dataset_key, set())


def _link_verified_file_to_resource(
    *,
    resource_uri: str,
    file_key: str,
    organization_code: Optional[str],
    context_label: str,
) -> None:
    logger.info(
        "📷 %s link requested | resource=%s | key=%s | org=%s",
        context_label,
        resource_uri,
        file_key,
        organization_code,
    )

    if not resource_uri:
        logger.info("📷 %s link skipped: missing resource URI", context_label)
        return

    target_resource = Resource.objects.filter(uri=resource_uri).first()
    if target_resource is None:
        logger.warning("📷 %s link skipped: resource %s not found", context_label, resource_uri)
        return

    stale_queryset = S3FileObject.objects.filter(related_resource=target_resource)
    if file_key:
        stale_queryset = stale_queryset.exclude(s3_key=file_key)
    stale_count = stale_queryset.update(related_resource=None)
    if stale_count:
        logger.info("📷 Cleared %s stale %s link(s) for %s", stale_count, context_label, resource_uri)

    if not file_key:
        logger.info("📷 %s cleared for %s", context_label, resource_uri)
        return

    queryset = S3FileObject.objects.filter(status="verified", s3_key=file_key).order_by("-updated_at", "-created_at")
    if organization_code:
        queryset = queryset.filter(
            Q(organization__iexact=organization_code)
            | Q(related_resource__organization__code__iexact=organization_code)
        )
    file_obj = queryset.first()

    if file_obj is None:
        logger.warning("📷 %s link skipped: verified S3 key %s not found", context_label, file_key)
        return

    update_fields = ["related_resource"]
    if organization_code:
        new_org = organization_code.lower()
        if file_obj.organization != new_org:
            file_obj.organization = new_org
            update_fields.append("organization")

    file_obj.related_resource = target_resource
    file_obj.save(update_fields=update_fields)
    logger.info(
        "📷 %s linked | file=%s | resource=%s | org=%s",
        context_label,
        file_obj.s3_key,
        resource_uri,
        file_obj.organization,
    )


def _update_project_preview_link(
    *,
    project_uri: str,
    preview_key: str,
    organization_code: Optional[str],
) -> None:
    """Ensure the selected S3 object is linked to the project resource."""

    _link_verified_file_to_resource(
        resource_uri=project_uri,
        file_key=preview_key,
        organization_code=organization_code,
        context_label="Project preview",
    )


def _update_digital_object_file_link(
    *,
    digital_object_uri: str,
    file_key: str,
    organization_code: Optional[str],
) -> None:
    """Ensure the selected S3 object is linked to the digital object resource."""

    _link_verified_file_to_resource(
        resource_uri=digital_object_uri,
        file_key=file_key,
        organization_code=organization_code,
        context_label="Digital object file",
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

        if meta.get("is_join"):
            _ensure_actor_event_context_specs(meta)

        # Ensure common metadata keys exist for template access
        meta.setdefault("resolved_label", "")
        meta.setdefault("resolved_uri", "")
        meta["use_single_fk_widget"] = False

        field_slug = slugify(field.name or "")
        if _should_use_preview_picker(dataset_name, field_slug):
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
                configured_props = _configured_search_properties(field_config)

                if configured_props:
                    filtered_properties = _filter_properties_for_config(properties, configured_props)
                    if filtered_properties != properties:
                        meta["search_property_configured"] = True
                        first_prop = filtered_properties[0]
                        if first_prop.get("uri"):
                            meta["selected_property"] = first_prop["uri"]
                        logger.info(
                            f"🔒 Locked search to configured properties {configured_props} for {field.name}"
                        )
                    elif filtered_properties == properties:
                        logger.warning(
                            f"⚠️  Configured search_property {configured_props} not found for {field.name}"
                        )
                    properties = filtered_properties

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
        elif meta.get("is_join"):
            base_params = {"dataset": dataset_name, "column": field.name}
            base_url = f"{base_suggestion_url}?{urlencode(base_params)}"
            meta["base_suggestion_url"] = base_url
            logger.info(
                "🔗 Join field '%s': suggestion endpoint=%s (dataset=%s)",
                field.name,
                base_url,
                dataset_name,
            )

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
            configured_props = _configured_search_properties(field_config)

            # Ensure display_property is set for all triple creator widgets
            if not meta.get("display_property"):
                if configured_props:
                    search_props = meta.get("search_properties", [])
                    filtered_props = _filter_properties_for_config(search_props, configured_props)
                    if filtered_props:
                        meta["search_properties"] = filtered_props
                        meta["search_property_configured"] = True
                        meta["display_property"] = filtered_props[0].get("uri")
                        logger.info(
                            f"✅ Using configured search_property {configured_props} -> {filtered_props[0].get('uri')}"
                        )
                    if not meta.get("display_property"):
                        logger.warning(
                            f"⚠️  Configured search_property {configured_props} not found in search_properties"
                        )
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
            configured_props = _configured_search_properties(field_config)

            display_property_uri = None
            if configured_props:
                search_props = meta.get("search_properties", [])
                filtered_props = _filter_properties_for_config(search_props, configured_props)
                if filtered_props:
                    meta["search_properties"] = filtered_props
                    meta["search_property_configured"] = True
                    display_property_uri = filtered_props[0].get("uri")
                    if display_property_uri:
                        logger.info(
                            f"✅ Using configured search_property {configured_props} for {field.name}"
                        )
                if not display_property_uri:
                    logger.warning(
                        f"⚠️  Configured search_property {configured_props} not found, falling back to heuristic"
                    )
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
            configured_props = _configured_search_properties(field_config)

            # Use configured search property if available
            if not display_prop_uri and target_dataset:
                if configured_props:
                    search_props = meta.get("search_properties", [])
                    filtered_props = _filter_properties_for_config(search_props, configured_props)
                    if filtered_props:
                        meta["search_properties"] = filtered_props
                        meta["search_property_configured"] = True
                        first_prop = filtered_props[0]
                        display_prop_uri = first_prop.get("uri")
                        meta["display_property"] = display_prop_uri
                        meta["display_property_label"] = first_prop.get("label")
                        logger.info(
                            f"✅ Using configured search_property {configured_props} for {field.name}"
                        )
                    if not display_prop_uri:
                        logger.warning(
                            f"⚠️  Configured search_property {configured_props} not found, falling back to heuristic"
                        )

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

        actor_widget_context: Optional[Dict[str, Any]] = None

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
            actor_widget_context = _build_actor_participation_widget_context(
                schema_service=schema_service,
                dataset_name=dataset_name,
                field_name=field.name,
                field_meta=meta,
                join_rows=join_rows,
            )
            if actor_widget_context:
                widget_context = actor_widget_context
            else:
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

        elif meta.get("is_multi_value"):
            literal_values = _decode_plain_multi_values(
                form.initial.get(field.name, field.value())
            )
            textarea_value = "\n".join(literal_values)
            form_field = form.fields.get(field.name)
            if form_field:
                form_field.widget = forms.Textarea(
                    attrs={
                        "class": "textarea textarea-bordered w-full",
                        "rows": max(3, min(8, len(literal_values) + 1)),
                        "placeholder": "Ein Wert pro Zeile",
                    }
                )
                if not form.is_bound:
                    form.initial[field.name] = textarea_value
                    form_field.initial = textarea_value
            meta["plain_multi_value"] = True
            widget_context = None

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

    metadata_entry_entity = "project"

    def get(self, request: HttpRequest) -> HttpResponse:
        """Render the edit form with existing project data."""
        schema_service = _get_schema_service(request)
        if not schema_service:
            return HttpResponseRedirect("/metadata/"
                                        "workspace/legacy/")

        entity_uri = request.GET.get("uri", "")
        if not entity_uri:
            return HttpResponseBadRequest("Missing uri parameter")

        dataset_name = _resolve_dataset_name_from_uri(
            schema_service,
            entity_uri=entity_uri,
            fallback_dataset_name="Projekt",
        )
        template_dataset_name = _resolve_simplified_template_dataset_name(
            dataset_name,
            fallback_dataset_name="Projekt",
        )
        visible_fields = SIMPLIFIED_FIELD_CONFIG.get(template_dataset_name, [])

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
        tab_sections = _build_tab_sections(template_dataset_name, fields_with_metadata, relationship_fields_sorted)
        visibility_choices = _build_visibility_choices()
        current_visibility = _normalize_visibility_value(
            request.POST.get("visibility"),
            fallback=PublicAccessLevel.PRIVATE.value,
        )

        resource = Resource.objects.filter(uri=entity_uri).first()
        visibility_choices = _build_visibility_choices()
        current_visibility = _normalize_visibility_value(
            resource.public_access_level if resource else None,
            fallback=PublicAccessLevel.RESTRICTED.value,
        )

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
            "visibility_choices": visibility_choices,
            "current_visibility": current_visibility,
        }
        context["metadata_entry_return_url"] = _build_metadata_entry_url(
            schema_service.organization.code,
            self.metadata_entry_entity,
        )

        return render(request, "metadata/simplified_workspace/edit_project.html", context)

    def post(self, request: HttpRequest) -> HttpResponse:
        """Save the edited project data."""
        schema_service = _get_schema_service(request)
        if not schema_service:
            return HttpResponseRedirect("/metadata/workspace/legacy/")

        entity_uri = request.POST.get("entity_uri") or None

        if not entity_uri:
            return HttpResponseBadRequest("Missing entity_uri")

        dataset_name = _resolve_dataset_name_from_uri(
            schema_service,
            entity_uri=entity_uri,
            fallback_dataset_name="Projekt",
        )
        template_dataset_name = _resolve_simplified_template_dataset_name(
            dataset_name,
            fallback_dataset_name="Projekt",
        )

        resource = Resource.objects.filter(uri=entity_uri).first()

        # Get field metadata and augment with joins (for relationship handling)
        field_metadata = schema_service.get_field_metadata(dataset_name)
        if dataset_name == PROJECT_DATASET_NAME:
            field_metadata = _ensure_project_link_field(field_metadata)
        field_metadata, join_field_map = schema_service.augment_field_metadata_with_joins(
            dataset_name,
            field_metadata,
        )
        visible_fields = SIMPLIFIED_FIELD_CONFIG.get(template_dataset_name, [])
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
        tab_sections = _build_tab_sections(template_dataset_name, fields_with_metadata, relationship_fields_sorted)
        visibility_choices = _build_visibility_choices()
        current_visibility = _normalize_visibility_value(
            request.POST.get("visibility"),
            fallback=resource.public_access_level if resource else None,
        )

        if form.is_valid():
            try:
                entity_data = form.cleaned_entity_data()
                entity_data = _normalize_plain_multi_value_fields(entity_data, field_metadata)
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

                visibility = request.POST.get("visibility")
                if visibility in _VALID_VISIBILITY_VALUES:
                    resource_to_update = Resource.objects.filter(uri=saved_uri).first()
                    if resource_to_update and resource_to_update.public_access_level != visibility:
                        resource_to_update.public_access_level = visibility
                        resource_to_update.save(update_fields=["public_access_level"])
                        logger.info(f"✅ Updated visibility to {visibility} for {saved_uri}")

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
                return _redirect_to_metadata_entry(
                    schema_service.organization.code,
                    self.metadata_entry_entity,
                )

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
                    "visibility_choices": visibility_choices,
                    "current_visibility": current_visibility,
                }
                context["metadata_entry_return_url"] = _build_metadata_entry_url(
                    schema_service.organization.code,
                    self.metadata_entry_entity,
                )
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
                "visibility_choices": visibility_choices,
                "current_visibility": current_visibility,
            }
            context["metadata_entry_return_url"] = _build_metadata_entry_url(
                schema_service.organization.code,
                self.metadata_entry_entity,
            )
            return render(request, "metadata/simplified_workspace/edit_project.html", context)


class SimplifiedProjectCreateView(LoginRequiredMixin, View):
    """
    Simplified project create view using the same infrastructure as edit view.

    Shows only a subset of fields but uses the same relationship handling,
    URI resolution, and search capabilities as the full workspace.
    """

    metadata_entry_entity = "project"

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
            return _redirect_to_metadata_entry(entity=self.metadata_entry_entity)

        mapping = _select_active_mapping_for_organization(organization, request)

        if not mapping:
            return _redirect_to_metadata_entry(entity=self.metadata_entry_entity)

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
        visibility_choices = _build_visibility_choices()

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
        context["metadata_entry_return_url"] = _build_metadata_entry_url(
            schema_service.organization.code,
            self.metadata_entry_entity,
        )

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
            return _redirect_to_metadata_entry(entity=self.metadata_entry_entity)

        mapping = _select_active_mapping_for_organization(organization, request)

        if not mapping:
            return _redirect_to_metadata_entry(entity=self.metadata_entry_entity)

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
                entity_data = _normalize_plain_multi_value_fields(entity_data, field_metadata)
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
                visibility = request.POST.get("visibility")
                if visibility in _VALID_VISIBILITY_VALUES:
                    resource = Resource.objects.filter(uri=saved_uri).first()
                    if resource and resource.public_access_level != visibility:
                        resource.public_access_level = visibility
                        resource.save(update_fields=["public_access_level"])
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
                return _redirect_to_metadata_entry(
                    schema_service.organization.code,
                    self.metadata_entry_entity,
                )

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
                    "visibility_choices": visibility_choices,
                    "current_visibility": current_visibility,
                }
                context["metadata_entry_return_url"] = _build_metadata_entry_url(
                    schema_service.organization.code,
                    self.metadata_entry_entity,
                )
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
                "visibility_choices": visibility_choices,
                "current_visibility": current_visibility,
            }
            context["metadata_entry_return_url"] = _build_metadata_entry_url(
                schema_service.organization.code,
                self.metadata_entry_entity,
            )
            return render(request, "metadata/simplified_workspace/edit_project.html", context)


class SimplifiedEreignisCreateView(LoginRequiredMixin, View):
    """
    Simplified ereignis create view using the same infrastructure as edit view.

    Shows only a subset of fields but uses the same relationship handling,
    URI resolution, and search capabilities as the full workspace.
    """

    metadata_entry_entity = "ereignis"

    def get(self, request: HttpRequest) -> HttpResponse:
        """Render the create form for a new ereignis."""
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
            return _redirect_to_metadata_entry(entity=self.metadata_entry_entity)

        mapping = _select_active_mapping_for_organization(organization, request)

        if not mapping:
            return _redirect_to_metadata_entry(entity=self.metadata_entry_entity)

        schema_service = SchemaWorkspaceService(mapping=mapping, organization=organization)

        dataset_name = "Ereignis"
        visible_fields = SIMPLIFIED_FIELD_CONFIG.get(dataset_name, [])

        # Get field metadata from schema
        field_metadata = schema_service.get_field_metadata(dataset_name)

        # Augment with joins BEFORE filtering
        field_metadata, join_field_map = schema_service.augment_field_metadata_with_joins(
            dataset_name,
            field_metadata,
        )

        # Filter to only show simplified fields
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
            "title": "Neues Ereignis erstellen",
            "description": "Füge ein neues Ereignis hinzu.",
        }
        context["metadata_entry_return_url"] = _build_metadata_entry_url(
            schema_service.organization.code,
            self.metadata_entry_entity,
        )

        return render(request, "metadata/simplified_workspace/edit_ereignis.html", context)

    def post(self, request: HttpRequest) -> HttpResponse:
        """Save the new ereignis data."""
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
            return _redirect_to_metadata_entry(entity=self.metadata_entry_entity)

        mapping = _select_active_mapping_for_organization(organization, request)

        if not mapping:
            return _redirect_to_metadata_entry(entity=self.metadata_entry_entity)

        schema_service = SchemaWorkspaceService(mapping=mapping, organization=organization)

        dataset_name = "Ereignis"

        # Get field metadata and augment with joins
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
                entity_data = _normalize_plain_multi_value_fields(entity_data, field_metadata)
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

                logger.info(f"✅ Created ereignis: {saved_uri}")

                # Redirect back to metadata entry
                return _redirect_to_metadata_entry(
                    schema_service.organization.code,
                    self.metadata_entry_entity,
                )

            except Exception as e:
                logger.exception(f"❌ Error creating ereignis: {e}")
                # Re-render form with error
                context = {
                    "form": form,
                    "fields_with_metadata": fields_with_metadata,
                    "tab_sections": tab_sections,
                    "entity_uri": None,
                    "dataset_name": dataset_name,
                    "error": str(e),
                    "title": "Neues Ereignis erstellen",
                    "mapping_id": schema_service.mapping.id,
                }
                context["metadata_entry_return_url"] = _build_metadata_entry_url(
                    schema_service.organization.code,
                    self.metadata_entry_entity,
                )
                return render(request, "metadata/simplified_workspace/edit_ereignis.html", context)

        else:
            # Form validation failed
            logger.warning(f"Form validation failed: {form.errors}")
            context = {
                "form": form,
                "fields_with_metadata": fields_with_metadata,
                "tab_sections": tab_sections,
                "entity_uri": None,
                "dataset_name": dataset_name,
                "title": "Neues Ereignis erstellen",
                "mapping_id": schema_service.mapping.id,
            }
            context["metadata_entry_return_url"] = _build_metadata_entry_url(
                schema_service.organization.code,
                self.metadata_entry_entity,
            )
            return render(request, "metadata/simplified_workspace/edit_ereignis.html", context)


class SimplifiedEreignisEditView(LoginRequiredMixin, View):
    """
    Simplified ereignis edit view using legacy workspace infrastructure.

    Shows only a subset of fields but uses the same relationship handling,
    URI resolution, and search capabilities as the full workspace.
    """

    metadata_entry_entity = "ereignis"

    def get(self, request: HttpRequest) -> HttpResponse:
        """Render the edit form with existing ereignis data."""
        schema_service = _get_schema_service(request)
        if not schema_service:
            return _redirect_to_metadata_entry(entity=self.metadata_entry_entity)

        entity_uri = request.GET.get("uri", "")
        if not entity_uri:
            return HttpResponseBadRequest("Missing uri parameter")

        dataset_name = _resolve_dataset_name_from_uri(
            schema_service,
            entity_uri=entity_uri,
            fallback_dataset_name="Ereignis",
        )
        template_dataset_name = _resolve_simplified_template_dataset_name(
            dataset_name,
            fallback_dataset_name="Ereignis",
        )
        visible_fields = SIMPLIFIED_FIELD_CONFIG.get(template_dataset_name, [])

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
        tab_sections = _build_tab_sections(template_dataset_name, fields_with_metadata, relationship_fields_sorted)

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
        context["metadata_entry_return_url"] = _build_metadata_entry_url(
            schema_service.organization.code,
            self.metadata_entry_entity,
        )

        return render(request, "metadata/simplified_workspace/edit_ereignis.html", context)

    def post(self, request: HttpRequest) -> HttpResponse:
        """Save the edited ereignis data."""
        schema_service = _get_schema_service(request)
        if not schema_service:
            return _redirect_to_metadata_entry(entity=self.metadata_entry_entity)

        entity_uri = request.POST.get("entity_uri") or None

        if not entity_uri:
            return HttpResponseBadRequest("Missing entity_uri")

        dataset_name = _resolve_dataset_name_from_uri(
            schema_service,
            entity_uri=entity_uri,
            fallback_dataset_name="Ereignis",
        )
        template_dataset_name = _resolve_simplified_template_dataset_name(
            dataset_name,
            fallback_dataset_name="Ereignis",
        )

        # Get field metadata and augment with joins (for relationship handling)
        field_metadata = schema_service.get_field_metadata(dataset_name)
        field_metadata, join_field_map = schema_service.augment_field_metadata_with_joins(
            dataset_name,
            field_metadata,
        )
        visible_fields = SIMPLIFIED_FIELD_CONFIG.get(template_dataset_name, [])
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
        tab_sections = _build_tab_sections(template_dataset_name, fields_with_metadata, relationship_fields_sorted)

        if form.is_valid():
            try:
                entity_data = form.cleaned_entity_data()
                entity_data = _normalize_plain_multi_value_fields(entity_data, field_metadata)
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
                return _redirect_to_metadata_entry(
                    schema_service.organization.code,
                    self.metadata_entry_entity,
                )

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
                context["metadata_entry_return_url"] = _build_metadata_entry_url(
                    schema_service.organization.code,
                    self.metadata_entry_entity,
                )
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
            context["metadata_entry_return_url"] = _build_metadata_entry_url(
                schema_service.organization.code,
                self.metadata_entry_entity,
            )
            return render(request, "metadata/simplified_workspace/edit_ereignis.html", context)


class SimplifiedAkteurCreateView(LoginRequiredMixin, View):
    """
    Simplified akteur create view using the same infrastructure as edit view.

    Shows only a subset of fields but uses the same relationship handling,
    URI resolution, and search capabilities as the full workspace.
    """

    metadata_entry_entity = "akteur"

    def get(self, request: HttpRequest) -> HttpResponse:
        """Render the create form for a new akteur."""
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
            return _redirect_to_metadata_entry(entity=self.metadata_entry_entity)

        mapping = _select_active_mapping_for_organization(organization, request)

        if not mapping:
            return _redirect_to_metadata_entry(entity=self.metadata_entry_entity)

        schema_service = SchemaWorkspaceService(mapping=mapping, organization=organization)

        dataset_name = "AkteurIn"
        visible_fields = SIMPLIFIED_FIELD_CONFIG.get(dataset_name, [])

        # Get field metadata from schema
        field_metadata = schema_service.get_field_metadata(dataset_name)

        # Augment with joins BEFORE filtering
        field_metadata, join_field_map = schema_service.augment_field_metadata_with_joins(
            dataset_name,
            field_metadata,
        )

        # Filter to only show simplified fields
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
            "title": "Neue:n Akteur:in erstellen",
            "description": "Füge eine:n neue:n Akteur:in hinzu.",
        }
        context["metadata_entry_return_url"] = _build_metadata_entry_url(
            schema_service.organization.code,
            self.metadata_entry_entity,
        )

        return render(request, "metadata/simplified_workspace/edit_akteur.html", context)

    def post(self, request: HttpRequest) -> HttpResponse:
        """Save the new akteur data."""
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
            return _redirect_to_metadata_entry(entity=self.metadata_entry_entity)

        mapping = _select_active_mapping_for_organization(organization, request)

        if not mapping:
            return _redirect_to_metadata_entry(entity=self.metadata_entry_entity)

        schema_service = SchemaWorkspaceService(mapping=mapping, organization=organization)

        dataset_name = "AkteurIn"

        # Get field metadata and augment with joins
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
                entity_data = _normalize_plain_multi_value_fields(entity_data, field_metadata)
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

                logger.info(f"✅ Created akteur: {saved_uri}")

                # Redirect back to metadata entry
                return _redirect_to_metadata_entry(
                    schema_service.organization.code,
                    self.metadata_entry_entity,
                )

            except Exception as e:
                logger.exception(f"❌ Error creating akteur: {e}")
                # Re-render form with error
                context = {
                    "form": form,
                    "fields_with_metadata": fields_with_metadata,
                    "tab_sections": tab_sections,
                    "entity_uri": None,
                    "dataset_name": dataset_name,
                    "error": str(e),
                    "title": "Neue:n Akteur:in erstellen",
                    "mapping_id": schema_service.mapping.id,
                }
                context["metadata_entry_return_url"] = _build_metadata_entry_url(
                    schema_service.organization.code,
                    self.metadata_entry_entity,
                )
                return render(request, "metadata/simplified_workspace/edit_akteur.html", context)

        else:
            # Form validation failed
            logger.warning(f"Form validation failed: {form.errors}")
            context = {
                "form": form,
                "fields_with_metadata": fields_with_metadata,
                "tab_sections": tab_sections,
                "entity_uri": None,
                "dataset_name": dataset_name,
                "title": "Neue:n Akteur:in erstellen",
                "mapping_id": schema_service.mapping.id,
            }
            context["metadata_entry_return_url"] = _build_metadata_entry_url(
                schema_service.organization.code,
                self.metadata_entry_entity,
            )
            return render(request, "metadata/simplified_workspace/edit_akteur.html", context)


class SimplifiedAkteurEditView(LoginRequiredMixin, View):
    """
    Simplified akteur edit view using legacy workspace infrastructure.

    Shows only a subset of fields but uses the same relationship handling,
    URI resolution, and search capabilities as the full workspace.
    """

    metadata_entry_entity = "akteur"

    def get(self, request: HttpRequest) -> HttpResponse:
        """Render the edit form with existing akteur data."""
        schema_service = _get_schema_service(request)
        if not schema_service:
            return _redirect_to_metadata_entry(entity=self.metadata_entry_entity)

        entity_uri = request.GET.get("uri", "")
        if not entity_uri:
            return HttpResponseBadRequest("Missing uri parameter")

        dataset_name = _resolve_dataset_name_from_uri(
            schema_service,
            entity_uri=entity_uri,
            fallback_dataset_name="AkteurIn",
        )
        template_dataset_name = _resolve_simplified_template_dataset_name(
            dataset_name,
            fallback_dataset_name="AkteurIn",
        )
        visible_fields = SIMPLIFIED_FIELD_CONFIG.get(template_dataset_name, [])

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
            logger.info(f"Loading akteur: {entity_uri}")
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
            logger.exception(f"❌ Error loading akteur: {e}")

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
        tab_sections = _build_tab_sections(template_dataset_name, fields_with_metadata, relationship_fields_sorted)

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
            "title": "Akteur:in bearbeiten",
            "description": "Aktualisiere die wichtigsten Angaben für diese:n Akteur:in.",
        }
        context["metadata_entry_return_url"] = _build_metadata_entry_url(
            schema_service.organization.code,
            self.metadata_entry_entity,
        )

        return render(request, "metadata/simplified_workspace/edit_akteur.html", context)

    def post(self, request: HttpRequest) -> HttpResponse:
        """Save the edited akteur data."""
        schema_service = _get_schema_service(request)
        if not schema_service:
            return _redirect_to_metadata_entry(entity=self.metadata_entry_entity)

        entity_uri = request.POST.get("entity_uri") or None

        if not entity_uri:
            return HttpResponseBadRequest("Missing entity_uri")

        dataset_name = _resolve_dataset_name_from_uri(
            schema_service,
            entity_uri=entity_uri,
            fallback_dataset_name="AkteurIn",
        )
        template_dataset_name = _resolve_simplified_template_dataset_name(
            dataset_name,
            fallback_dataset_name="AkteurIn",
        )

        field_metadata = schema_service.get_field_metadata(dataset_name)
        field_metadata, join_field_map = schema_service.augment_field_metadata_with_joins(
            dataset_name,
            field_metadata,
        )
        visible_fields = SIMPLIFIED_FIELD_CONFIG.get(template_dataset_name, [])
        field_metadata = _filter_field_metadata(field_metadata, visible_fields)
        join_field_map = {
            name: relationship
            for name, relationship in join_field_map.items()
            if name in field_metadata
        }

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
        tab_sections = _build_tab_sections(template_dataset_name, fields_with_metadata, relationship_fields_sorted)

        if form.is_valid():
            try:
                entity_data = form.cleaned_entity_data()
                entity_data = _normalize_plain_multi_value_fields(entity_data, field_metadata)
                entity_data, join_payloads, multi_fk_payloads = _collect_relationship_payloads(
                    request,
                    entity_data,
                    field_metadata,
                    join_field_map,
                    entity_uri=entity_uri,
                )

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

                logger.info(f"✅ Saved akteur: {saved_uri} (created={created})")
                return _redirect_to_metadata_entry(
                    schema_service.organization.code,
                    self.metadata_entry_entity,
                )

            except Exception as e:
                logger.exception(f"❌ Error saving akteur: {e}")
                context = {
                    "form": form,
                    "fields_with_metadata": fields_with_metadata,
                    "tab_sections": tab_sections,
                    "entity_uri": entity_uri,
                    "dataset_name": dataset_name,
                    "error": str(e),
                    "title": "Akteur:in bearbeiten",
                    "mapping_id": schema_service.mapping.id,
                }
                context["metadata_entry_return_url"] = _build_metadata_entry_url(
                    schema_service.organization.code,
                    self.metadata_entry_entity,
                )
                return render(request, "metadata/simplified_workspace/edit_akteur.html", context)

        logger.warning(f"Form validation failed: {form.errors}")
        context = {
            "form": form,
            "fields_with_metadata": fields_with_metadata,
            "tab_sections": tab_sections,
            "entity_uri": entity_uri,
            "dataset_name": dataset_name,
            "title": "Akteur:in bearbeiten",
            "mapping_id": schema_service.mapping.id,
        }
        context["metadata_entry_return_url"] = _build_metadata_entry_url(
            schema_service.organization.code,
            self.metadata_entry_entity,
        )
        return render(request, "metadata/simplified_workspace/edit_akteur.html", context)


class _SimplifiedDatasetMixin:
    dataset_name: str = ""
    metadata_entry_entity: str = ""

    def _prepare_field_metadata(
        self,
        schema_service: SchemaWorkspaceService,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        try:
            field_metadata = schema_service.get_field_metadata(self.dataset_name)
        except ValueError as exc:
            raise MissingDatasetSchema(str(exc)) from exc
        if self.dataset_name == PROJECT_DATASET_NAME:
            field_metadata = _ensure_project_link_field(field_metadata)
        field_metadata, join_field_map = schema_service.augment_field_metadata_with_joins(
            self.dataset_name,
            field_metadata,
        )
        visible_fields = SIMPLIFIED_FIELD_CONFIG.get(self.dataset_name, [])
        if visible_fields:
            field_metadata = _filter_field_metadata(field_metadata, visible_fields)
        allowed_fields = set(field_metadata.keys())
        join_field_map = {
            name: relationship
            for name, relationship in (join_field_map or {}).items()
            if name in allowed_fields
        }
        return field_metadata, join_field_map

    def _build_tab_sections_for_form(
        self,
        form: DatasetEntityForm,
        field_metadata: Dict[str, Any],
        schema_service: SchemaWorkspaceService,
        *,
        entity_uri: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        fields_with_metadata = _enrich_fk_metadata(
            form=form,
            field_metadata=field_metadata,
            schema_service=schema_service,
            dataset_name=self.dataset_name,
            entity_uri=entity_uri,
        )
        relationship_fields = [
            item for item in fields_with_metadata if item["meta"].get("is_join")
        ]
        tab_sections = _build_tab_sections(
            self.dataset_name,
            fields_with_metadata,
            relationship_fields,
        )
        return fields_with_metadata, tab_sections


class _BaseSimplifiedCreateView(LoginRequiredMixin, _SimplifiedDatasetMixin, View):
    template_name: str = ""
    page_title: str = ""
    page_description: str = ""

    def _resolve_organization(self, request: HttpRequest) -> Optional[Organization]:
        org_code = request.GET.get("organization")
        if org_code:
            try:
                return Organization.objects.get(code=org_code)
            except Organization.DoesNotExist:
                return getattr(request.user, "organization", None)
        return getattr(request.user, "organization", None)

    def _get_schema_service(
        self,
        request: HttpRequest,
    ) -> Tuple[Optional[SchemaWorkspaceService], Optional[Organization]]:
        organization = self._resolve_organization(request)
        if not organization:
            return None, None

        mapping = _select_active_mapping_for_organization(organization, request)

        if not mapping:
            return None, organization

        try:
            schema_service = SchemaWorkspaceService(mapping=mapping, organization=organization)
        except ValueError as exc:
            messages.error(request, str(exc))
            return None, organization

        return schema_service, organization

    def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        schema_service, organization = self._get_schema_service(request)
        if not schema_service or not organization:
            return _redirect_to_metadata_entry(entity=self.metadata_entry_entity)

        try:
            field_metadata, join_field_map = self._prepare_field_metadata(schema_service)
        except MissingDatasetSchema as exc:
            messages.error(request, str(exc))
            return _redirect_to_metadata_entry(entity=self.metadata_entry_entity)
        form = DatasetEntityForm(
            field_metadata=field_metadata,
            initial=None,
            disable_anchors=False,
            hide_anchors=self.dataset_name not in SIMPLIFIED_VISIBLE_ANCHORS,
        )
        fields_with_metadata, tab_sections = self._build_tab_sections_for_form(
            form,
            field_metadata,
            schema_service,
        )

        context = {
            "form": form,
            "fields_with_metadata": fields_with_metadata,
            "tab_sections": tab_sections,
            "entity_uri": None,
            "entity_label": None,
            "dataset_name": self.dataset_name,
            "mapping_id": schema_service.mapping.id,
            "load_error": False,
            "read_only_relationships": [],
            "title": self.page_title,
            "description": self.page_description,
        }
        context["metadata_entry_return_url"] = _build_metadata_entry_url(
            schema_service.organization.code,
            self.metadata_entry_entity,
        )
        return render(request, self.template_name, context)

    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        schema_service, organization = self._get_schema_service(request)
        if not schema_service or not organization:
            return _redirect_to_metadata_entry(entity=self.metadata_entry_entity)

        try:
            field_metadata, join_field_map = self._prepare_field_metadata(schema_service)
        except MissingDatasetSchema as exc:
            messages.error(request, str(exc))
            return _redirect_to_metadata_entry(entity=self.metadata_entry_entity)
        form = DatasetEntityForm(
            request.POST,
            field_metadata=field_metadata,
            disable_anchors=False,
            hide_anchors=self.dataset_name not in SIMPLIFIED_VISIBLE_ANCHORS,
        )
        fields_with_metadata, tab_sections = self._build_tab_sections_for_form(
            form,
            field_metadata,
            schema_service,
        )

        if form.is_valid():
            try:
                entity_data = form.cleaned_entity_data()
                entity_data = _normalize_plain_multi_value_fields(entity_data, field_metadata)
                entity_data, join_payloads, multi_fk_payloads = _collect_relationship_payloads(
                    request,
                    entity_data,
                    field_metadata,
                    join_field_map,
                    entity_uri=None,
                )

                saved_uri, _created = schema_service.save_entity(
                    dataset_name=self.dataset_name,
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

                if self.dataset_name == DIGITAL_OBJECT_DATASET_NAME:
                    preview_field_name = _get_preview_field_name(fields_with_metadata)
                    if preview_field_name:
                        preview_key = form.cleaned_data.get(preview_field_name, "") or ""
                        _update_digital_object_file_link(
                            digital_object_uri=saved_uri,
                            file_key=preview_key,
                            organization_code=schema_service.organization.code,
                        )

                logger.info(f"✅ Created {self.dataset_name}: {saved_uri}")
                return _redirect_to_metadata_entry(
                    schema_service.organization.code,
                    self.metadata_entry_entity,
                )

            except Exception as exc:
                logger.exception("❌ Error creating %s", self.dataset_name, exc_info=True)
                context = {
                    "form": form,
                    "fields_with_metadata": fields_with_metadata,
                    "tab_sections": tab_sections,
                    "entity_uri": None,
                    "dataset_name": self.dataset_name,
                    "error": str(exc),
                    "title": self.page_title,
                    "description": self.page_description,
                    "mapping_id": schema_service.mapping.id,
                }
                context["metadata_entry_return_url"] = _build_metadata_entry_url(
                    schema_service.organization.code,
                    self.metadata_entry_entity,
                )
                return render(request, self.template_name, context)

        logger.warning("Form validation failed for %s: %s", self.dataset_name, form.errors)
        context = {
            "form": form,
            "fields_with_metadata": fields_with_metadata,
            "tab_sections": tab_sections,
            "entity_uri": None,
            "dataset_name": self.dataset_name,
            "title": self.page_title,
            "description": self.page_description,
            "mapping_id": schema_service.mapping.id,
        }
        context["metadata_entry_return_url"] = _build_metadata_entry_url(
            schema_service.organization.code,
            self.metadata_entry_entity,
        )
        return render(request, self.template_name, context)


class _BaseSimplifiedEditView(LoginRequiredMixin, _SimplifiedDatasetMixin, View):
    template_name: str = ""
    page_title: str = ""
    page_description: str = ""

    def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        schema_service = _get_schema_service(request)
        if not schema_service:
            return _redirect_to_metadata_entry(entity=self.metadata_entry_entity)

        entity_uri = request.GET.get("uri", "")
        if not entity_uri:
            return HttpResponseBadRequest("Missing uri parameter")

        try:
            field_metadata, join_field_map = self._prepare_field_metadata(schema_service)
        except MissingDatasetSchema as exc:
            messages.error(request, str(exc))
            return _redirect_to_metadata_entry(entity=self.metadata_entry_entity)

        initial_data: Optional[Dict[str, object]] = None
        entity_label: Optional[str] = None
        load_error = False
        try:
            initial_data = schema_service.load_entity_by_uri(self.dataset_name, entity_uri)
            if initial_data:
                entity_label = _infer_entity_label(schema_service, entity_uri, self.dataset_name)
            else:
                load_error = True
        except Exception:
            load_error = True
            logger.exception("❌ Error loading %s", entity_uri)

        show_anchors = self.dataset_name in SIMPLIFIED_VISIBLE_ANCHORS
        form = DatasetEntityForm(
            field_metadata=field_metadata,
            initial=initial_data,
            disable_anchors=not show_anchors,
            hide_anchors=not show_anchors,
        )

        read_only_relationships: List[Dict[str, Any]] = []
        if entity_uri:
            relationships = schema_service.collect_relationship_values(
                dataset_name=self.dataset_name,
                entity_uri=entity_uri,
                field_metadata=field_metadata,
                join_field_map=join_field_map,
            )
            from arkumu.metadata.views.schema_workspace_views import _apply_relationship_initials

            read_only_relationships = _apply_relationship_initials(
                service=schema_service,
                form=form,
                relationships=relationships,
            )

        fields_with_metadata, tab_sections = self._build_tab_sections_for_form(
            form,
            field_metadata,
            schema_service,
            entity_uri=entity_uri,
        )

        context = {
            "form": form,
            "fields_with_metadata": fields_with_metadata,
            "tab_sections": tab_sections,
            "entity_uri": entity_uri,
            "entity_label": entity_label,
            "dataset_name": self.dataset_name,
            "mapping_id": schema_service.mapping.id,
            "load_error": load_error,
            "read_only_relationships": read_only_relationships,
            "title": self.page_title,
            "description": self.page_description,
        }
        context["metadata_entry_return_url"] = _build_metadata_entry_url(
            schema_service.organization.code,
            self.metadata_entry_entity,
        )
        return render(request, self.template_name, context)

    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        schema_service = _get_schema_service(request)
        if not schema_service:
            return _redirect_to_metadata_entry(entity=self.metadata_entry_entity)

        entity_uri = request.POST.get("entity_uri") or None
        if not entity_uri:
            return HttpResponseBadRequest("Missing entity_uri")

        try:
            field_metadata, join_field_map = self._prepare_field_metadata(schema_service)
        except MissingDatasetSchema as exc:
            messages.error(request, str(exc))
            return _redirect_to_metadata_entry(entity=self.metadata_entry_entity)
        show_anchors = self.dataset_name in SIMPLIFIED_VISIBLE_ANCHORS
        form = DatasetEntityForm(
            request.POST,
            field_metadata=field_metadata,
            disable_anchors=not show_anchors,
            hide_anchors=not show_anchors,
        )
        fields_with_metadata, tab_sections = self._build_tab_sections_for_form(
            form,
            field_metadata,
            schema_service,
            entity_uri=entity_uri,
        )

        if form.is_valid():
            try:
                entity_data = form.cleaned_entity_data()
                entity_data = _normalize_plain_multi_value_fields(entity_data, field_metadata)
                entity_data, join_payloads, multi_fk_payloads = _collect_relationship_payloads(
                    request,
                    entity_data,
                    field_metadata,
                    join_field_map,
                    entity_uri=entity_uri,
                )

                saved_uri, _ = schema_service.save_entity(
                    dataset_name=self.dataset_name,
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

                if self.dataset_name == DIGITAL_OBJECT_DATASET_NAME:
                    preview_field_name = _get_preview_field_name(fields_with_metadata)
                    if preview_field_name:
                        preview_key = form.cleaned_data.get(preview_field_name, "") or ""
                        _update_digital_object_file_link(
                            digital_object_uri=saved_uri,
                            file_key=preview_key,
                            organization_code=schema_service.organization.code,
                        )

                logger.info(f"✅ Updated {self.dataset_name}: {saved_uri}")
                return _redirect_to_metadata_entry(
                    schema_service.organization.code,
                    self.metadata_entry_entity,
                )

            except Exception as exc:
                logger.exception("❌ Error updating %s", self.dataset_name, exc_info=True)
                context = {
                    "form": form,
                    "fields_with_metadata": fields_with_metadata,
                    "tab_sections": tab_sections,
                    "entity_uri": entity_uri,
                    "dataset_name": self.dataset_name,
                    "error": str(exc),
                    "title": self.page_title,
                    "description": self.page_description,
                    "mapping_id": schema_service.mapping.id,
                    "read_only_relationships": [],
                }
                context["metadata_entry_return_url"] = _build_metadata_entry_url(
                    schema_service.organization.code,
                    self.metadata_entry_entity,
                )
                return render(request, self.template_name, context)

        logger.warning("Form validation failed for %s: %s", self.dataset_name, form.errors)
        context = {
            "form": form,
            "fields_with_metadata": fields_with_metadata,
            "tab_sections": tab_sections,
            "entity_uri": entity_uri,
            "dataset_name": self.dataset_name,
            "title": self.page_title,
            "description": self.page_description,
            "mapping_id": schema_service.mapping.id,
            "read_only_relationships": [],
        }
        context["metadata_entry_return_url"] = _build_metadata_entry_url(
            schema_service.organization.code,
            self.metadata_entry_entity,
        )
        return render(request, self.template_name, context)


class SimplifiedOrtCreateView(_BaseSimplifiedCreateView):
    dataset_name = "Ort"
    metadata_entry_entity = "ort"
    template_name = "metadata/simplified_workspace/edit_ort.html"
    page_title = "Neuen Ort erstellen"
    page_description = "Pflege die wichtigsten Angaben zu diesem Ort."


class SimplifiedOrtEditView(_BaseSimplifiedEditView):
    dataset_name = "Ort"
    metadata_entry_entity = "ort"
    template_name = "metadata/simplified_workspace/edit_ort.html"
    page_title = "Ort bearbeiten"
    page_description = "Aktualisiere die wichtigsten Angaben zu diesem Ort."


class SimplifiedDigitalesObjektCreateView(_BaseSimplifiedCreateView):
    dataset_name = DIGITAL_OBJECT_DATASET_NAME
    metadata_entry_entity = "digitales_objekt"
    template_name = "metadata/simplified_workspace/edit_digitales_objekt.html"
    page_title = "Neues Digitales Objekt erstellen"
    page_description = "Füge ein neues digitales Objekt hinzu."


class SimplifiedDigitalesObjektEditView(_BaseSimplifiedEditView):
    dataset_name = DIGITAL_OBJECT_DATASET_NAME
    metadata_entry_entity = "digitales_objekt"
    template_name = "metadata/simplified_workspace/edit_digitales_objekt.html"
    page_title = "Digitales Objekt bearbeiten"
    page_description = "Aktualisiere die wichtigsten Angaben zu diesem digitalen Objekt."


class SimplifiedEquipmentSoftwareCreateView(_BaseSimplifiedCreateView):
    dataset_name = "Equipment_und_Software"
    metadata_entry_entity = "equipment_software"
    template_name = "metadata/simplified_workspace/edit_equipment_software.html"
    page_title = "Neues Equipment & Software erstellen"
    page_description = "Erfasse die wichtigsten Informationen zu dieser technischen Ressource."


class SimplifiedEquipmentSoftwareEditView(_BaseSimplifiedEditView):
    dataset_name = "Equipment_und_Software"
    metadata_entry_entity = "equipment_software"
    template_name = "metadata/simplified_workspace/edit_equipment_software.html"
    page_title = "Equipment & Software bearbeiten"
    page_description = "Aktualisiere die wichtigsten Informationen zu dieser technischen Ressource."


class SimplifiedAlternativerTitelCreateView(_BaseSimplifiedCreateView):
    dataset_name = "Alternativer_Titel"
    metadata_entry_entity = "alternativer_titel"
    template_name = "metadata/simplified_workspace/edit_alternativer_titel.html"
    page_title = "Neuen Alternativen Titel erstellen"
    page_description = "Erfasse einen neuen alternativen Titel."


class SimplifiedAlternativerTitelEditView(_BaseSimplifiedEditView):
    dataset_name = "Alternativer_Titel"
    metadata_entry_entity = "alternativer_titel"
    template_name = "metadata/simplified_workspace/edit_alternativer_titel.html"
    page_title = "Alternativen Titel bearbeiten"
    page_description = "Aktualisiere die Angaben zu diesem alternativen Titel."


class ActorParticipationCardView(LoginRequiredMixin, View):
    """HTMX endpoint to add a blank actor participation card."""

    def post(self, request: HttpRequest) -> HttpResponse:
        dataset_name = request.POST.get("dataset")
        field_name = request.POST.get("field_name")

        if not dataset_name or not field_name:
            return HttpResponseBadRequest("Missing dataset or field_name parameter")

        schema_service = _get_schema_service(request)
        if not schema_service:
            return HttpResponseBadRequest("Session expired")

        field_metadata = schema_service.get_field_metadata(dataset_name)
        field_metadata, _ = schema_service.augment_field_metadata_with_joins(
            dataset_name,
            field_metadata,
        )
        field_meta = field_metadata.get(field_name)
        if not field_meta or not field_meta.get("is_join"):
            return HttpResponseBadRequest("Unknown join field")

        if not field_meta.get("base_suggestion_url"):
            base_params = {"dataset": dataset_name, "column": field_name}
            base_url = f"{reverse('metadata:entity_workspace_field_values', args=[schema_service.mapping.id])}?{urlencode(base_params)}"
            field_meta["base_suggestion_url"] = base_url

        widget_context = _build_actor_participation_widget_context(
            schema_service=schema_service,
            dataset_name=dataset_name,
            field_name=field_name,
            field_meta=field_meta,
            join_rows=None,
        )
        if not widget_context or not widget_context.get("cards"):
            return HttpResponseBadRequest("Field does not support actor participation")

        card = widget_context["cards"][0]
        context = {
            "card": card,
            "widget": widget_context,
        }
        return render(
            request,
            "metadata/simplified_workspace/partials/_actor_participation_card.html",
            context,
        )


class ContextEntitySuggestionsView(LoginRequiredMixin, View):
    """Return suggestions for context (role) entity selectors via HTMX."""

    max_suggestions = 20

    def get(self, request: HttpRequest) -> HttpResponse:
        if request.GET.get("clear"):
            return HttpResponse("")

        dataset_name = request.GET.get("dataset")
        search_property = request.GET.get("search_property") or ""
        input_id = request.GET.get("input_id")
        hidden_id = request.GET.get("hidden_id")
        hidden_name = request.GET.get("hidden_name")
        target_id = request.GET.get("target_id")
        field_name = request.GET.get("field_name")
        context_slug = request.GET.get("context_slug")

        required = [dataset_name, input_id, hidden_id, hidden_name, target_id, field_name, context_slug]
        if any(not value for value in required):
            return HttpResponseBadRequest("Missing required parameters")

        schema_service = _get_schema_service(request)
        if not schema_service:
            return HttpResponseBadRequest("Session expired")

        query = request.GET.get("q", "").strip()

        from arkumu.metadata.views.schema_workspace_views import DatasetFieldValueOptionsView

        helper = DatasetFieldValueOptionsView()
        helper.max_suggestions = self.max_suggestions
        suggestions = helper._collect_dataset_entity_suggestions(  # pylint: disable=protected-access
            schema_service,
            dataset_name,
            query,
            search_property or None,
        )

        context = {
            "suggestions": suggestions[: self.max_suggestions],
            "input_id": input_id,
            "hidden_id": hidden_id,
            "hidden_name": hidden_name,
            "target_id": target_id,
            "dataset": dataset_name,
            "search_property": search_property,
            "field_name": field_name,
            "context_slug": context_slug,
        }
        return render(
            request,
            "metadata/simplified_workspace/partials/_context_entity_suggestions.html",
            context,
        )


class ContextEntitySelectView(LoginRequiredMixin, View):
    """Apply a role/context selection using HTMX out-of-band swaps."""

    ROLE_PLACEHOLDER = "Rolle wählen…"

    def post(self, request: HttpRequest) -> HttpResponse:
        dataset_name = request.POST.get("dataset")
        input_id = request.POST.get("input_id")
        hidden_id = request.POST.get("hidden_id")
        hidden_name = request.POST.get("hidden_name")
        target_id = request.POST.get("target_id")
        field_name = request.POST.get("field_name")
        context_slug = request.POST.get("context_slug")
        search_property = request.POST.get("search_property") or ""

        required = [dataset_name, input_id, hidden_id, hidden_name, target_id, field_name, context_slug]
        if any(not value for value in required):
            return HttpResponseBadRequest("Missing required parameters")

        schema_service = _get_schema_service(request)
        if not schema_service:
            return HttpResponseBadRequest("Session expired")

        raw_value = (request.POST.get("value") or "").strip()
        value, label_hint = decode_placeholder_uri(raw_value)
        value = value or raw_value
        label = (request.POST.get("label") or "").strip() or label_hint
        if value and not label:
            label = _infer_entity_label(schema_service, value, dataset_name)

        suggestion_url = reverse("metadata:simplified_context_entity_suggestions")
        query_params = urlencode(
            {
                "dataset": dataset_name,
                "search_property": search_property,
                "input_id": input_id,
                "hidden_id": hidden_id,
                "hidden_name": hidden_name,
                "target_id": target_id,
                "field_name": field_name,
                "context_slug": context_slug,
            }
        )
        hx_url = f"{suggestion_url}?{query_params}"

        hidden_input_html = (
            f'<input type="hidden" name="{escape(hidden_name)}" '
            f'id="{escape(hidden_id)}" value="{escape(value)}" hx-swap-oob="outerHTML">'
        )
        visible_input_html = (
            f'<input type="text" id="{escape(input_id)}" name="q" '
            f'class="input input-bordered w-full" placeholder="{self.ROLE_PLACEHOLDER}" '
            f'value="{escape(label)}" '
            f'hx-get="{escape(hx_url)}" hx-trigger="input changed delay:200ms" '
            f'hx-target="#{escape(target_id)}" hx-include="#{escape(hidden_id)}" '
            f'autocomplete="off" hx-swap-oob="outerHTML">'
        )
        dropdown_html = f'<div id="{escape(target_id)}" hx-swap-oob="innerHTML"></div>'

        response_html = "\n".join([hidden_input_html, visible_input_html, dropdown_html])
        return HttpResponse(response_html)
class MissingDatasetSchema(Exception):
    """Raised when no schema blueprint exists for the requested dataset."""
