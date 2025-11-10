"""Tabular views for displaying RDF entity data (FUK) in a table with pagination."""

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.db.models import CharField, Exists, OuterRef, Subquery
from django.db.models.functions import Coalesce, Lower
from django.shortcuts import render
from django.urls import reverse
from django.utils.text import slugify

from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.models.mappings import Mapping
from arkumu.users.models import Organization
from arkumu.common.mixins.base_coordinator import BaseCoordinatorMixin
from arkumu.catalog.services.project_views import CardURIs, ProjectURIs
from arkumu.metadata.schema_workspace.services import SchemaWorkspaceService
from arkumu.metadata.services.entity_label_service import EntityLabelResolver


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Column mapping helpers
# ---------------------------------------------------------------------------

_PROPERTY_NAMESPACE_CODES: Tuple[str, ...] = ("fuk", "det", "rsh", "hmt", "khm")


def _normalize_match_token(raw: str) -> str:
    """Normalize predicate tokens for comparisons."""
    return raw.strip().lower()


def _expand_property_variants(*values: str) -> List[str]:
    """
    Expand canonical property URIs into organization-specific variants.

    DigiKunst predicates appear as both canonical and archive-scoped URIs, so we
    need to recognise both forms when mapping triples to table columns.
    """
    expanded: Set[str] = set()
    for value in values:
        if not value:
            continue
        expanded.add(value)
        lower_value = value.lower()
        for needle, segment in (("/data/properties/", "properties"), ("/data/types/", "types")):
            if needle in lower_value:
                suffix = value.split(needle, 1)[1]
                for code in _PROPERTY_NAMESPACE_CODES:
                    expanded.add(f"http://arkumu.org/data/{code}/{segment}/{suffix}")
    return list(expanded)


_PREFERRED_LABEL_URIS: Set[str] = set()
for canonical_uri in (
    CardURIs.CATEGORY_GERMAN_NAME,
    CardURIs.INSTITUTION_GERMAN_NAME,
    CardURIs.TITLE,
    CardURIs.SUBTITLE,
    ProjectURIs.ALTERNATIVE_TITLE_VALUE,
    ProjectURIs.EVENT_NAME,
):
    _PREFERRED_LABEL_URIS.update(_expand_property_variants(canonical_uri))

_PREFERRED_LABEL_TOKENS: Set[str] = {_normalize_match_token(uri) for uri in _PREFERRED_LABEL_URIS}
_LABEL_TOKEN_HINTS: Tuple[str, ...] = ("name", "titel", "title", "label", "bezeichnung")


def _build_column_specs(columns_config: List[Any]) -> List[Dict[str, Any]]:
    """
    Convert raw column configuration into normalized specs.

    Specs contain:
        - label: table header / result key
        - matchers: normalized predicate tokens for matching triples
        - raw_matchers: original matcher strings (URIs/aliases)
        - sort_predicates: predicate URIs used for sorting
        - sortable: whether the column supports sorting
        - slug: slugified label for query params
    """
    specs: List[Dict[str, Any]] = []
    for column in columns_config:
        if isinstance(column, str):
            specs.append(
                {
                    "label": column,
                    "matchers": {_normalize_match_token(column)},
                    "raw_matchers": [],
                    "sort_predicates": [],
                    "sortable": False,
                    "sort_key": None,
                    "slug": slugify(str(column)),
                }
            )
            continue

        label = column.get("label") or column.get("name")
        if not label:
            continue

        matchers: Set[str] = set()
        for candidate in column.get("matchers", []):
            matchers.add(_normalize_match_token(candidate))
        for alias in column.get("aliases", []):
            matchers.add(_normalize_match_token(alias))
        matchers.add(_normalize_match_token(label))

        sort_predicates = column.get("sort_predicates", column.get("matchers", []))

        specs.append(
            {
                "label": label,
                "matchers": matchers,
                "raw_matchers": column.get("matchers", []),
                "sort_predicates": sort_predicates,
                "sortable": column.get("sortable", True),
                "sort_key": column.get("sort_key"),
                "slug": slugify(str(label)),
            }
        )
    return specs


def _predicate_tokens(predicate: Resource) -> Set[str]:
    """Collect normalized predicate attributes used for column matching."""
    tokens: Set[str] = set()
    for attr in ("canonical_uri", "uri", "name", "value"):
        value = getattr(predicate, attr, None)
        if value:
            tokens.add(_normalize_match_token(value))
    return tokens


def _initial_resource_label(res: Resource) -> str | None:
    """Return immediate label for a resource without additional queries."""
    if res.name:
        return res.name
    if res.value:
        return res.value
    return None


def _fallback_uri_segment(res: Resource) -> str:
    """Fallback display value derived from the resource URI."""
    if res.uri:
        last_segment = res.uri.rstrip('/').split('/')[-1]
        return last_segment.replace('-', ' ').replace('_', ' ')
    return str(res.id)


def _is_preferred_label_predicate(tokens: Set[str]) -> bool:
    """Determine whether predicate tokens indicate a display label."""
    if tokens & _PREFERRED_LABEL_TOKENS:
        return True
    for token in tokens:
        for hint in _LABEL_TOKEN_HINTS:
            if hint in token:
                return True
    return False


def _build_entity_label_map(entities: List[Resource]) -> Dict[Any, str]:
    """Resolve display labels for entity resources via preferred literal predicates."""
    label_map: Dict[Any, str] = {}
    if not entities:
        return label_map

    pending_ids: List[Any] = []
    for entity in entities:
        base_label = _initial_resource_label(entity)
        if base_label:
            label_map[entity.id] = base_label
        else:
            pending_ids.append(entity.id)

    if not pending_ids:
        return label_map

    label_triples = list(
        Triple.objects.filter(
            subject_id__in=pending_ids,
            object__resource_type=ResourceType.LITERAL,
        )
        .select_related("predicate", "object")
    )

    # First pass: capture preferred predicates only
    for triple in label_triples:
        subject_id = triple.subject_id
        if subject_id in label_map:
            continue
        label_value = triple.object.value or triple.object.name
        if not label_value:
            continue
        predicate_tokens = _predicate_tokens(triple.predicate)
        if _is_preferred_label_predicate(predicate_tokens):
            label_map[subject_id] = label_value

    # Second pass: fall back to any literal for remaining entities
    for triple in label_triples:
        subject_id = triple.subject_id
        if subject_id in label_map:
            continue
        label_value = triple.object.value or triple.object.name
        if label_value:
            label_map[subject_id] = label_value

    # Final fallback to URI fragments
    for entity in entities:
        if entity.id not in label_map:
            label_map[entity.id] = _fallback_uri_segment(entity)

    return label_map


def _apply_subject_sort(
    queryset,
    sort_spec: Optional[Dict[str, Any]],
    sort_order: str,
) :
    """Apply ordering to the base queryset according to selected column."""
    default_field = 'uri'
    if not sort_spec:
        return queryset.order_by(default_field)

    order = '-' if sort_order == 'desc' else ''
    sort_key = sort_spec.get('sort_key')

    if sort_key == 'visibility':
        field = f"{order}public_access_level"
        return queryset.order_by(field, default_field)

    if sort_key == 'organization':
        field = f"{order}organization__name"
        return queryset.order_by(field, default_field)

    if sort_key == 'uri':
        field = f"{order}uri"
        return queryset.order_by(field)

    predicates = [
        candidate for candidate in sort_spec.get('sort_predicates', [])
        if isinstance(candidate, str) and candidate.lower().startswith('http')
    ]

    if sort_key == 'boolean':
        if not predicates:
            return queryset.order_by(f"{order}{default_field}")
        exists_qs = Triple.objects.filter(
            subject_id=OuterRef('pk'),
            predicate__uri__in=predicates,
            object__value__isnull=False,
        )
        queryset = queryset.annotate(has_sort_flag=Exists(exists_qs))
        field = f"{order}has_sort_flag"
        return queryset.order_by(field, default_field)

    if predicates:
        coalesced_value = Coalesce(
            'object__value',
            'object__name',
            'object__uri',
            output_field=CharField(),
        )
        sort_subquery = (
            Triple.objects.filter(
                subject_id=OuterRef('pk'),
                predicate__uri__in=predicates,
            )
            .annotate(
                sort_text=Lower(coalesced_value, output_field=CharField()),
            )
            .order_by('sort_text')
            .values('sort_text')[:1]
        )
        queryset = queryset.annotate(column_sort_value=Subquery(sort_subquery, output_field=CharField()))
        field = f"{order}column_sort_value"
        return queryset.order_by(field, default_field)

    return queryset.order_by(f"{order}{default_field}")


PROJECT_COLUMN_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "label": "Bevorzugter Titel",
        "matchers": _expand_property_variants(
            CardURIs.TITLE,
            "Bevorzugter Titel",
        ),
    },
    {
        "label": "Projektart",
        "matchers": _expand_property_variants(
            ProjectURIs.PROJECT_TYPE_FIELD,
            "Projektart",
        ),
    },
    {
        "label": "Projektkategorie",
        "matchers": _expand_property_variants(
            CardURIs.CATEGORY,
            "Projektkategorie",
        ),
    },
    {
        "label": "Einliefernde Hochschule",
        "matchers": _expand_property_variants(
            CardURIs.INSTITUTION,
            "Einliefernde Hochschule",
            "Hochschule",
        ),
    },
    {
        "label": "Schlagworte",
        "matchers": _expand_property_variants(
            ProjectURIs.CATCHPHRASE,
            "Schlagwort",
        ),
    },
    {
        "label": "Signatur beim Einlieferer",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/signatur-beim-einlieferer",
            "http://arkumu.org/data/properties/signatur",
            "Signatur beim Einlieferer",
        ),
    },
    {
        "label": "Angegebene Nutzungsrechte",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/angegebene-nutzungsrechte",
            "Angegebene Nutzungsrechte",
        ),
    },
    {
        "label": "Projektstatus",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/projektstatus",
            "http://arkumu.org/data/properties/anzeigestatus",
            "http://arkumu.org/data/properties/status",
            "Projektstatus",
            "Anzeigestatus",
        ),
    },
]

# Akteur (Actor) column definitions
AKTEUR_COLUMN_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "label": "Deutscher Name",
        "matchers": _expand_property_variants(
            CardURIs.ACTOR_GERMAN_NAME,
            "Deutscher Name",
        ),
    },
    {
        "label": "Englischer Name",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/englischer-name",
            "Englischer Name",
        ),
    },
    {
        "label": "Beruf und Tätigkeit",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/beruf-und-taetigkeit",
            "Beruf und Tätigkeit",
        ),
    },
    {
        "label": "Geschlecht",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/geschlecht",
            "Geschlecht",
        ),
    },
    {
        "label": "Geburtsort",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/geburtsort",
            "Geburtsort",
        ),
    },
    {
        "label": "Sterbeort",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/sterbeort",
            "Sterbeort",
        ),
    },
    {
        "label": "Wirkungsbeginn",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/wirkungsbeginn",
            "Wirkungsbeginn",
        ),
    },
    {
        "label": "Wirkungsende",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/wirkungsende",
            "Wirkungsende",
        ),
    },
    {
        "label": "Wikidata-ID",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/wikidata-id",
            "Wikidata-ID",
        ),
    },
]

# Akteur Relation column definitions
AKTEUR_RELATION_COLUMN_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "label": "akteur1",
        "matchers": _expand_property_variants(
            CardURIs.ACTOR_IN_EVENT,
            "http://arkumu.org/data/properties/akteur1",
            "http://arkumu.org/data/properties/akteurin",
            "akteur1",
        ),
    },
    {
        "label": "artDerRelation",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/art-der-relation",
            "http://arkumu.org/data/properties/relationstyp",
            "artDerRelation",
            "Art der Relation",
        ),
    },
    {
        "label": "akteur2",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/akteur2",
            "http://arkumu.org/data/properties/verwandter-akteur",
            "akteur2",
        ),
    },
]

# Digitales Objekt column definitions
DIGITALES_OBJEKT_COLUMN_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "label": "S3-Link",
        "matchers": [],
        "sort_predicates": _expand_property_variants(
            ProjectURIs.DIGITAL_OBJECT_PATH,
            "http://arkumu.org/data/properties/dateipfad",
            "Dateipfad",
        ),
        "sort_key": "boolean",
    },
    {
        "label": "Dateiname",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/dateiname",
            "http://arkumu.org/data/properties/original-dateiname",
            "Dateiname",
        ),
    },
    {
        "label": "Dateipfad",
        "matchers": _expand_property_variants(
            ProjectURIs.DIGITAL_OBJECT_PATH,
            "http://arkumu.org/data/properties/dateipfad",
            "Dateipfad",
        ),
    },
    {
        "label": "Medientyp",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/medientyp",
            "Medientyp",
        ),
    },
    {
        "label": "Lizenzstatus",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/lizenzstatus",
            "Lizenzstatus",
        ),
    },
    {
        "label": "Anzeigestatus",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/anzeigestatus",
            "Anzeigestatus",
        ),
    },
    {
        "label": "Einlieferer",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/einlieferer",
            "Einlieferer",
        ),
    },
    {
        "label": "Entstehung",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/entstehung",
            "Entstehung",
        ),
    },
    {
        "label": "Tonformat",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/tonformat",
            "Tonformat",
        ),
    },
    {
        "label": "Wesentliche Eigenschaften (deutsch)",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/wesentliche-eigenschaften-deutsch",
            "Wesentliche Eigenschaften (deutsch)",
        ),
    },
]

# Equipment Software column definitions
EQUIPMENT_SOFTWARE_COLUMN_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "label": "Deutsche Produkt-Bezeichnung",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/deutscher-name",
            "http://arkumu.org/data/properties/name-de",
            "Deutsche (Produkt-) Bezeichnung",
        ),
    },
    {
        "label": "Englische Produkt-Bezeichnung",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/englischer-name",
            "http://arkumu.org/data/properties/name-en",
            "Englische (Produkt-) Bezeichnung",
        ),
    },
    {
        "label": "Equipmentart",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/equipmentart",
            "http://arkumu.org/data/properties/equipment-art",
            "Equipmentart",
        ),
    },
    {
        "label": "Hersteller",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/hersteller",
            "http://arkumu.org/data/properties/manufacturer",
            "Hersteller",
        ),
    },
    {
        "label": "Deutsche Beschreibung",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/deutsche-beschreibung",
            "Deutsche Beschreibung",
        ),
    },
    {
        "label": "GND-Nummer",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/gnd-nummer",
            "GND-Nummer",
        ),
    },
    {
        "label": "Wikidata-ID",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/wikidata-id",
            "Wikidata-ID",
        ),
    },
]

# Equipmentart column definitions
EQUIPMENTART_COLUMN_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "label": "Deutscher Name der Equipmentart",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/deutscher-name-der-equipmentart",
            "Deutscher Name der Equipmentart",
        ),
    },
    {
        "label": "Englischer Name der Equipmentart",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/englischer-name-der-equipmentart",
            "Englischer Name der Equipmentart",
        ),
    },
    {
        "label": "Equipmentart-ID",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/equipmentart-id",
            "Equipmentart-ID",
        ),
    },
    {
        "label": "AAT-ID",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/aat-id",
            "AAT-ID",
        ),
    },
    {
        "label": "GND-Nummer",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/gnd-nummer",
            "GND-Nummer",
        ),
    },
    {
        "label": "Wikidata-ID",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/wikidata-id",
            "Wikidata-ID",
        ),
    },
]

# Ereignis (Event) column definitions
EREIGNIS_COLUMN_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "label": "Ereignisname",
        "matchers": _expand_property_variants(
            ProjectURIs.EVENT_NAME,
            "http://arkumu.org/data/properties/ereignisname",
            "Ereignisname",
        ),
    },
    {
        "label": "Ereignistyp",
        "matchers": _expand_property_variants(
            ProjectURIs.EVENT_TYPE,
            "http://arkumu.org/data/properties/ereignistyp",
            "Ereignistyp",
        ),
    },
    {
        "label": "Beginn",
        "matchers": _expand_property_variants(
            CardURIs.EVENT_START,
            "http://arkumu.org/data/properties/ereignisbeginn",
            "Beginn",
        ),
    },
    {
        "label": "Ende",
        "matchers": _expand_property_variants(
            CardURIs.EVENT_END,
            "http://arkumu.org/data/properties/ereignisende",
            "Ende",
        ),
    },
    {
        "label": "Ereignisort",
        "matchers": _expand_property_variants(
            ProjectURIs.EVENT_LOCATION,
            "http://arkumu.org/data/properties/ereignisort",
            "Ereignisort",
        ),
    },
    {
        "label": "Ereignisbeschreibung",
        "matchers": _expand_property_variants(
            ProjectURIs.EVENT_DESCRIPTION,
            "http://arkumu.org/data/properties/ereignisbeschreibung",
            "Ereignisbeschreibung",
        ),
    },
    {
        "label": "Projektbeziehungen",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/ereignis",
            "Projektbeziehungen",
        ),
    },
]

# Ereignis Relation column definitions
EREIGNIS_RELATION_COLUMN_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "label": "ereignis1",
        "matchers": _expand_property_variants(
            CardURIs.EVENT,
            "http://arkumu.org/data/properties/ereignis1",
            "ereignis1",
        ),
    },
    {
        "label": "artDerRelation",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/art-der-relation",
            "artDerRelation",
        ),
    },
    {
        "label": "ereignis2",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/ereignis2",
            "ereignis2",
        ),
    },
]

# Informationstraeger column definitions
INFORMATIONSTRAEGER_COLUMN_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "label": "Deutsche (Produkt-) Bezeichnung",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/deutsche-produkt-bezeichnung",
            "Deutsche (Produkt-) Bezeichnung",
        ),
    },
    {
        "label": "Englische (Produkt-) Bezeichnung",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/englische-produkt-bezeichnung",
            "Englische (Produkt-) Bezeichnung",
        ),
    },
    {
        "label": "Informationsträgertyp",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/informationstraegertyp",
            "Informationsträgertyp",
        ),
    },
    {
        "label": "Aufbewahrungsort",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/aufbewahrungsort",
            "Aufbewahrungsort",
        ),
    },
    {
        "label": "BesitzerIn",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/besitzerin",
            "BesitzerIn",
        ),
    },
    {
        "label": "EigentümerIn",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/eigentuemerin",
            "EigentümerIn",
        ),
    },
    {
        "label": "Externe Inventar-Signaturnummer",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/externe-inventar-signaturnummern",
            "http://arkumu.org/data/properties/externe-inventarsignatur",
            "Externe Inventar-Signaturnummer",
        ),
    },
    {
        "label": "Erhaltungszustand (deutsch)",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/erhaltungszustand-deutsch",
            "Erhaltungszustand (deutsch)",
        ),
    },
    {
        "label": "Maße",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/masse",
            "Maße",
        ),
    },
    {
        "label": "Provenienz",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/provenienz",
            "Provenienz",
        ),
    },
]

# Organisationseinheit column definitions
ORGANISATIONSEINHEIT_COLUMN_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "label": "name_de",
        "matchers": _expand_property_variants(
            CardURIs.INSTITUTION_GERMAN_NAME,
            "http://arkumu.org/data/properties/deutscher-name",
            "name_de",
        ),
    },
    {
        "label": "name_en",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/englischer-name",
            "name_en",
        ),
    },
    {
        "label": "hochschule",
        "matchers": _expand_property_variants(
            CardURIs.INSTITUTION,
            "hochschule",
        ),
    },
]

# Ort (Place) column definitions
ORT_COLUMN_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "label": "Deutscher Name des Ortes",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/deutscher-name-des-ortes",
            "Deutscher Name des Ortes",
        ),
    },
    {
        "label": "Ort-ID",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/ort-id",
            "Ort-ID",
        ),
    },
    {
        "label": "Wikidata-ID",
        "matchers": _expand_property_variants(
            ProjectURIs.EVENT_LOCATION_WIKIDATA,
            "http://arkumu.org/data/properties/wikidata-id",
            "http://arkumu.org/data/properties/wikidata-item",
            "Wikidata-ID",
        ),
    },
    {
        "label": "Ortshierarchie",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/hierarchie",
            "http://arkumu.org/data/properties/location-hierarchy",
            "Ortshierarchie",
        ),
    },
    {
        "label": "Ort-Kategorie",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/ort-kategorie",
            "http://arkumu.org/data/properties/location-category",
            "Ort-Kategorie",
        ),
    },
]

# Physisches Objekt column definitions
PHYSISCHES_OBJEKT_COLUMN_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "label": "Deutsche Bezeichnung",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/deutsche-bezeichnung",
            "Deutsche Bezeichnung",
        ),
    },
    {
        "label": "Englische Bezeichnung",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/englische-bezeichnung",
            "Englische Bezeichnung",
        ),
    },
    {
        "label": "Aufbewahrungsort",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/aufbewahrungsort",
            "Aufbewahrungsort",
        ),
    },
    {
        "label": "BesitzerIn",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/besitzerin",
            "BesitzerIn",
        ),
    },
    {
        "label": "Externe Inventar-Signaturnummer",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/externe-inventar-signaturnummern",
            "Externe Inventar-Signaturnummer",
        ),
    },
    {
        "label": "Materialschlagwort",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/materialschlagwort",
            "Materialschlagwort",
        ),
    },
    {
        "label": "Maße",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/masse",
            "Maße",
        ),
    },
    {
        "label": "Provenienz",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/provenienz",
            "Provenienz",
        ),
    },
]

# Projekt Eigenschaftswert column definitions (with order override)
PROJEKT_EIGENSCHAFTSWERT_COLUMN_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "label": "projekt",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/projekt",
            CardURIs.TITLE,
            "projekt",
        ),
    },
    {
        "label": "eigenschaft",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/eigenschaft",
            "http://arkumu.org/data/properties/property",
            "eigenschaft",
        ),
    },
    {
        "label": "wert",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/wert",
            "http://arkumu.org/data/properties/value",
            "wert",
        ),
    },
]

# Projekt Relation column definitions
PROJEKT_RELATION_COLUMN_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "label": "projekt1",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/projekt1",
            "projekt1",
        ),
    },
    {
        "label": "artDerRelation",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/art-der-relation",
            "artDerRelation",
        ),
    },
    {
        "label": "projekt2",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/projekt2",
            "projekt2",
        ),
    },
]

# Sammlung column definitions
SAMMLUNG_COLUMN_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "label": "bezeichnung_de",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/deutscher-name-der-sammlung",
            "http://arkumu.org/data/properties/bezeichnung-de",
            "bezeichnung_de",
        ),
    },
    {
        "label": "bezeichnung_en",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/englischer-name-der-sammlung",
            "http://arkumu.org/data/properties/bezeichnung-en",
            "bezeichnung_en",
        ),
    },
    {
        "label": "sammlungsArt",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/sammlungsart",
            "http://arkumu.org/data/properties/collection-type",
            "sammlungsArt",
        ),
    },
]

# Schlagwort (Keyword) column definitions
SCHLAGWORT_COLUMN_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "label": "label_de",
        "matchers": _expand_property_variants(
            ProjectURIs.CATCHPHRASE,
            "http://arkumu.org/data/properties/schlagwort",
            "http://arkumu.org/data/properties/label-de",
            "label_de",
        ),
    },
    {
        "label": "label_en",
        "matchers": _expand_property_variants(
            "http://arkumu.org/data/properties/englischer-name",
            "http://arkumu.org/data/properties/label-en",
            "label_en",
        ),
    },
    {
        "label": "wikidataItem",
        "matchers": _expand_property_variants(
            ProjectURIs.CATCHPHRASE_WIKIDATA,
            "http://arkumu.org/data/properties/wikidata-id",
            "wikidataItem",
        ),
    },
]


# Entity configuration - based on DigiKunst tabular view columns documentation
# uri_contains patterns match actual slugified dataset names from schema manifests (FUK/RSH/DET)
ENTITY_CONFIG: Dict[str, Dict] = {
    'akteur': {
        'uri_contains': '/entities/akteurin/',
        'dataset_name': 'AkteurIn',
        'columns': AKTEUR_COLUMN_DEFINITIONS,
    },
    'akteur_relation': {
        'uri_contains': '/entities/akteurin-akteurin-kreuztabelle/',
        'dataset_name': 'AkteurIn_AkteurIn_Kreuztabelle',
        'columns': AKTEUR_RELATION_COLUMN_DEFINITIONS,
    },
    'bestehender_lizenzvertrag': {
        'uri_contains': '/entities/bestehender-lizenzvertrag/',
        'dataset_name': 'Bestehender_Lizenzvertrag',
        'columns': [],  # Inherits default Fields plugin ordering
    },
    'digitales_objekt': {
        'uri_contains': '/entities/digitales-objekt/',
        'dataset_name': 'Digitales_Objekt',
        'columns': DIGITALES_OBJEKT_COLUMN_DEFINITIONS,
    },
    'eigenschaft': {
        'uri_contains': '/entities/eigenschaft/',
        'dataset_name': 'Eigenschaft',
        'columns': [],  # Inherits default Fields plugin ordering
    },
    'equipment_software': {
        'uri_contains': '/entities/equipment-und-software/',
        'dataset_name': 'Equipment_und_Software',
        'columns': EQUIPMENT_SOFTWARE_COLUMN_DEFINITIONS,
    },
    'equipmentart': {
        'uri_contains': '/entities/equipmentart/',
        'dataset_name': 'Equipmentart',
        'columns': EQUIPMENTART_COLUMN_DEFINITIONS,
    },
    'ereignis': {
        'uri_contains': '/entities/ereignis/',
        'dataset_name': 'Ereignis',
        'columns': EREIGNIS_COLUMN_DEFINITIONS,
    },
    'ereignis_beschreibung': {
        'uri_contains': '/entities/ereignisbeschreibung/',
        'dataset_name': 'Ereignisbeschreibung',
        'columns': [],  # Inherits default Fields plugin ordering
    },
    'ereignis_eigenschaftswert': {
        'uri_contains': '/entities/ereigniseigenschaft-kreuztabelle/',
        'dataset_name': 'Ereigniseigenschaft_Kreuztabelle',
        'columns': [],  # Inherits default Fields plugin ordering
    },
    'ereignis_relation': {
        'uri_contains': '/entities/ereignis-ereignis-kreuztabelle/',
        'dataset_name': 'Ereignis_Ereignis_Kreuztabelle',
        'columns': EREIGNIS_RELATION_COLUMN_DEFINITIONS,
    },
    'ereignis_rolle': {
        'uri_contains': '/entities/ereignis-rolle/',
        'dataset_name': 'Ereignis Rolle',
        'columns': [],  # Inherits default Fields plugin ordering
    },
    'informationstraeger': {
        'uri_contains': '/entities/informationstraeger/',
        'dataset_name': 'Informationsträger',
        'columns': INFORMATIONSTRAEGER_COLUMN_DEFINITIONS,
    },
    'informationstraeger_eigenschaftswert': {
        'uri_contains': '/entities/informationstraegereigenschaft/',
        'dataset_name': 'Informationsträgereigenschaft',
        'columns': [],  # Inherits default Fields plugin ordering
    },
    'inhaltswarnung': {
        'uri_contains': '/entities/inhaltswarnung/',
        'dataset_name': 'Inhaltswarnung',
        'columns': [],  # Inherits default Fields plugin ordering
    },
    'organisationseinheit': {
        'uri_contains': '/entities/organisationseinheit/',
        'dataset_name': 'Organisationseinheit',
        'columns': ORGANISATIONSEINHEIT_COLUMN_DEFINITIONS,
    },
    'ort': {
        'uri_contains': '/entities/ort/',
        'dataset_name': 'Ort',
        'columns': ORT_COLUMN_DEFINITIONS,
    },
    'physisches_objekt': {
        'uri_contains': '/entities/physisches-objekt/',
        'dataset_name': 'Physisches_Objekt',
        'columns': PHYSISCHES_OBJEKT_COLUMN_DEFINITIONS,
    },
    'produkt_id': {
        'uri_contains': '/entities/produktid-kreuztabelle/',
        'dataset_name': 'ProduktID_Kreuztabelle',
        'columns': [],  # Inherits default Fields plugin ordering
    },
    'project': {
        'uri_contains': '/entities/projekt/',
        'dataset_name': 'Projekt',
        'columns': PROJECT_COLUMN_DEFINITIONS,
    },
    'projekt_beschreibung': {
        'uri_contains': '/entities/beschreibung/',
        'dataset_name': 'Beschreibung',
        'columns': [],  # Inherits default Fields plugin ordering
    },
    'projekt_eigenschaftswert': {
        'uri_contains': '/entities/projekteigenschaft-kreuztabelle/',
        'dataset_name': 'Projekteigenschaft_Kreuztabelle',
        'columns': PROJEKT_EIGENSCHAFTSWERT_COLUMN_DEFINITIONS,
    },
    'projekt_relation': {
        'uri_contains': '/entities/projekt-projekt-kreuztabelle/',
        'dataset_name': 'Projekt_Projekt_Kreuztabelle',
        'columns': PROJEKT_RELATION_COLUMN_DEFINITIONS,
    },
    'sammlung': {
        'uri_contains': '/entities/sammlung/',
        'dataset_name': 'Sammlung',
        'columns': SAMMLUNG_COLUMN_DEFINITIONS,
    },
    'schlagwort': {
        'uri_contains': '/entities/schlagwort/',
        'dataset_name': 'Schlagwort',
        'columns': SCHLAGWORT_COLUMN_DEFINITIONS,
    },
    # Legacy/alternative names for compatibility
    'event': {
        'uri_contains': '/entities/ereignis/',
        'dataset_name': 'Ereignis',
        'columns': EREIGNIS_COLUMN_DEFINITIONS,
    },
    'actor': {
        'uri_contains': '/entities/akteurin/',
        'dataset_name': 'AkteurIn',
        'columns': AKTEUR_COLUMN_DEFINITIONS,
    },
    'digital_object': {
        'uri_contains': '/entities/digitales-objekt/',
        'dataset_name': 'Digitales_Objekt',
        'columns': DIGITALES_OBJEKT_COLUMN_DEFINITIONS,
    },
}

EDIT_URL_NAMES: Dict[str, str] = {
    'project': 'metadata:edit_project',
    'ereignis': 'metadata:edit_ereignis',
    'akteur': 'metadata:edit_akteur',
    'actor': 'metadata:edit_actor',
    'digital_object': 'metadata:edit_digital_object',
    'digitales_objekt': 'metadata:edit_digital_object',
    'equipment_software': 'metadata:edit_equipment_software',
    'ort': 'metadata:edit_ort',
}

ENTITY_PARAM_MAP: Dict[str, str] = {
    'project': 'project',
    'ereignis': 'ereignis',
    'event': 'ereignis',
    'akteur': 'akteur',
    'actor': 'akteur',
    'digital_object': 'digitales_objekt',
    'digitales_objekt': 'digitales_objekt',
    'equipment_software': 'equipment_software',
    'ort': 'ort',
}


def _entity_has_actions(entity_type: Optional[str]) -> bool:
    return bool(entity_type) and entity_type in EDIT_URL_NAMES


def _resolve_current_org(request, override_code: Optional[str] = None) -> Organization | None:
    coord = BaseCoordinatorMixin()
    if override_code:
        coord.set_current_organization(request, override_code.lower())
    current = coord.get_current_organization(request)
    if current and 'code' in current:
        try:
            return Organization.objects.get(code=current['code'])
        except Organization.DoesNotExist:
            pass
    try:
        return Organization.objects.get(code__iexact='fuk')
    except Organization.DoesNotExist:
        return None


def _display_for_resource(
    res: Resource,
    entity_labels: Dict[Any, str],
    resolver: Optional[EntityLabelResolver] = None,
) -> str:
    if res.resource_type == ResourceType.LITERAL:
        return res.value or res.name or ''

    fallback = _fallback_uri_segment(res) if res.uri else ''

    label = None
    if res.name:
        label = res.name
    elif res.value:
        label = res.value
    elif entity_labels:
        label = entity_labels.get(res.id)

    needs_resolution = (
        resolver is not None
        and res.resource_type == ResourceType.ENTITY
        and (not label or label.strip() == '' or (fallback and label == fallback))
    )
    if needs_resolution:
        try:
            resolved = resolver.label_for_resource(res)
        except Exception:
            logger.debug("Failed to resolve label for %s", res.uri, exc_info=True)
        else:
            if resolved:
                label = resolved
                entity_labels[res.id] = resolved

    if label:
        return label
    if fallback:
        return fallback
    return str(res.id)


def _resolve_entities_through_junction_tables(
    subject_ids: List[Any],
    org: Organization,
    junction_table_pattern: str,
    source_predicate_uri_patterns: List[str],
    target_predicate_uri_patterns: List[str],
) -> Dict[str, List[Resource]]:
    """
    Resolve related entities through junction (Kreuztabelle) tables.
    
    Args:
        subject_ids: List of subject entity IDs to find relationships for
        org: Organization for filtering
        junction_table_pattern: URI pattern to match junction table entities (e.g., '/entities/akteurin-akteurin-kreuztabelle/')
        source_predicate_uri_patterns: List of predicate URI patterns that point FROM the subject (e.g., ['ausgangsakteurin'])
        target_predicate_uri_patterns: List of predicate URI patterns that point TO the related entity (e.g., ['verknuepfter-akteurin'])
    
    Returns:
        Dict mapping subject_id (as string) to list of related entity Resources
    """
    if not subject_ids:
        return {}
    
    related_entities_map: Dict[str, List[Resource]] = defaultdict(list)
    
    # Find junction table entities that reference our subjects
    # Query for triples where junction entities have properties pointing to our subjects
    junction_entities = Resource.objects.for_organization(org).filter(
        uri__icontains=junction_table_pattern,
        resource_type=ResourceType.ENTITY
    )
    
    if not junction_entities.exists():
        return related_entities_map
    
    junction_ids = [j.id for j in junction_entities]
    
    # Find triples where junction entities point to our subjects via source predicates
    source_triples = Triple.objects.filter(
        subject_id__in=junction_ids,
        object_id__in=subject_ids,
    ).select_related('predicate', 'subject', 'object')
    
    # Build map: junction_entity_id -> subject_id (for subjects referenced via source predicate)
    junction_to_subject: Dict[str, Any] = {}
    source_predicate_matchers = set()
    for uri_pattern in source_predicate_uri_patterns:
        for code in _PROPERTY_NAMESPACE_CODES:
            source_predicate_matchers.add(uri_pattern.lower())
            # Also try organization-specific variants
            if 'properties' in uri_pattern or 'data/properties' not in uri_pattern:
                for seg in ('properties', 'data/properties'):
                    source_predicate_matchers.add(f"http://arkumu.org/data/{code}/{seg}/{uri_pattern}".lower())
    
    for triple in source_triples:
        pred_uri_lower = triple.predicate.uri.lower()
        pred_name_lower = triple.predicate.uri.split('/')[-1].lower() if '/' in triple.predicate.uri else ''
        
        # Check if this predicate matches any source pattern
        matches_source = False
        for pattern in source_predicate_uri_patterns:
            if pattern.lower() in pred_uri_lower or pattern.lower() in pred_name_lower:
                matches_source = True
                break
        
        if matches_source:
            junction_to_subject[str(triple.subject_id)] = triple.object_id
    
    if not junction_to_subject:
        return related_entities_map
    
    # Now find triples where these junction entities point to related entities via target predicates
    target_triples = Triple.objects.filter(
        subject_id__in=list(junction_to_subject.keys()),
        object__resource_type=ResourceType.ENTITY,
    ).select_related('predicate', 'object')
    
    target_predicate_matchers = set()
    for uri_pattern in target_predicate_uri_patterns:
        for code in _PROPERTY_NAMESPACE_CODES:
            target_predicate_matchers.add(uri_pattern.lower())
            if 'properties' in uri_pattern or 'data/properties' not in uri_pattern:
                for seg in ('properties', 'data/properties'):
                    target_predicate_matchers.add(f"http://arkumu.org/data/{code}/{seg}/{uri_pattern}".lower())
    
    for triple in target_triples:
        pred_uri_lower = triple.predicate.uri.lower()
        pred_name_lower = triple.predicate.uri.split('/')[-1].lower() if '/' in triple.predicate.uri else ''
        
        # Check if this predicate matches any target pattern
        matches_target = False
        for pattern in target_predicate_uri_patterns:
            if pattern.lower() in pred_uri_lower or pattern.lower() in pred_name_lower:
                matches_target = True
                break
        
        if matches_target and str(triple.subject_id) in junction_to_subject:
            subject_id = junction_to_subject[str(triple.subject_id)]
            related_entity = triple.object
            related_entities_map[str(subject_id)].append(related_entity)
    
    return related_entities_map


def _build_rows_for_subjects(
    subjects: List[Resource],
    column_specs: List[Dict[str, Any]],
    entity_type: str = None,
    org: Organization = None,
    label_resolver: Optional[EntityLabelResolver] = None,
) -> Tuple[List[Dict[str, str]], List[Dict[str, object]]]:
    """
    Build table rows for given subject resources.
    
    Also resolves relationships through junction (Kreuztabelle) tables for main entity types.

    Returns (rows, columns_meta). columns_meta contains [{'name': label, 'is_fk': bool}]
    """
    add_actions = _entity_has_actions(entity_type)

    if not subjects:
        columns = [
            {
                'name': spec['label'],
                'is_fk': False,
                'slug': spec.get('slug'),
                'sortable': spec.get('sortable', False),
            }
            for spec in column_specs
        ]
        if add_actions:
            columns.insert(0, {'name': 'Aktionen', 'is_fk': False, 'slug': None, 'sortable': False})
            columns.insert(1, {'name': 'Sichtbarkeit', 'is_fk': False, 'slug': slugify("Sichtbarkeit"), 'sortable': True})
        return [], columns

    subject_ids = [s.id for s in subjects]
    triples = (
        Triple.objects
        .filter(subject_id__in=subject_ids)
        .select_related('predicate', 'object')
    )

    # Group triples by subject
    by_subject: Dict[str, List[Triple]] = defaultdict(list)
    for t in triples:
        by_subject[str(t.subject_id)].append(t)

    entity_objects = {
        t.object_id: t.object
        for t in triples
        if t.object.resource_type != ResourceType.LITERAL
    }
    
    # Resolve relationships through junction tables based on entity type
    junction_related: Dict[str, List[Resource]] = {}
    if entity_type and org:
        if entity_type == 'akteur':
            # Find related actors through AkteurIn_AkteurIn_Kreuztabelle
            junction_related = _resolve_entities_through_junction_tables(
                subject_ids, org,
                '/entities/akteurin-akteurin-kreuztabelle/',
                ['ausgangsakteurin', 'akteur1'],
                ['verknuepfter-akteurin', 'verknuepfte-akteurin', 'akteur2'],
            )
            entity_objects.update({r.id: r for related_list in junction_related.values() for r in related_list})
        elif entity_type == 'ereignis':
            # Find related events through Ereignis_Ereignis_Kreuztabelle
            junction_related = _resolve_entities_through_junction_tables(
                subject_ids, org,
                '/entities/ereignis-ereignis-kreuztabelle/',
                ['ausgangsereignis', 'ereignis1'],
                ['verknuepftes-ereignis', 'ereignis2'],
            )
            entity_objects.update({r.id: r for related_list in junction_related.values() for r in related_list})
        elif entity_type == 'project':
            # Find related projects through Projekt_Projekt_Kreuztabelle
            junction_related = _resolve_entities_through_junction_tables(
                subject_ids, org,
                '/entities/projekt-projekt-kreuztabelle/',
                ['ausgangsprojekt', 'projekt1'],
                ['verknuepftes-projekt', 'projekt2'],
            )
            entity_objects.update({r.id: r for related_list in junction_related.values() for r in related_list})
    
    entity_labels = _build_entity_label_map(list(entity_objects.values()))

    # Track if a column is FK (any non-literal object for that predicate name)
    column_is_fk: Dict[str, bool] = {spec['label']: False for spec in column_specs}

    rows: List[Dict[str, str]] = []
    if add_actions:
        edit_url = reverse(EDIT_URL_NAMES[entity_type])
        entity_param_value = ENTITY_PARAM_MAP.get(entity_type)

    for s in subjects:
        row: Dict[str, str] = {spec['label']: '' for spec in column_specs}
        
        # Add direct triples
        for t in by_subject.get(str(s.id), []):
            predicate_tokens = _predicate_tokens(t.predicate)
            matched_spec = None
            for spec in column_specs:
                if predicate_tokens & spec['matchers']:
                    matched_spec = spec
                    break
            if not matched_spec:
                continue
            label = matched_spec['label']
            val = _display_for_resource(t.object, entity_labels, label_resolver)
            # If multiple values, concatenate with semicolon
            if row[label]:
                row[label] = f"{row[label]}; {val}"
            else:
                row[label] = val
            if t.object.resource_type != ResourceType.LITERAL:
                column_is_fk[label] = True
        
        # Add related entities from junction tables (for specific columns if they match)
        related_entities = junction_related.get(str(s.id), [])
        if related_entities:
            # Try to match related entities to column specs
            # For now, we'll add them to columns that might represent relationships
            # This could be enhanced to be more specific based on entity type and column definitions
            for related in related_entities:
                related_label = _display_for_resource(related, entity_labels, label_resolver)
                # Look for columns that might represent relationships
                # This is a heuristic - could be made more specific
                for spec in column_specs:
                    spec_label_lower = spec['label'].lower()
                    # If column name suggests it might be a relationship/related entity column
                    if any(keyword in spec_label_lower for keyword in ['relation', 'related', 'verknuepf', 'beziehung']):
                        if row[spec['label']]:
                            row[spec['label']] = f"{row[spec['label']]}; {related_label}"
                        else:
                            row[spec['label']] = related_label
                        column_is_fk[spec['label']] = True
                        break
        
        if entity_type in {"digital_object", "digitales_objekt"} and "S3-Link" in row:
            has_s3_path = bool(row.get("Dateipfad"))
            row["S3-Link"] = "Ja" if has_s3_path else "Nein"

        if add_actions:
            if s.uri:
                query_params = {'uri': s.uri}
                if entity_param_value:
                    query_params['entity'] = entity_param_value
                query = urlencode(query_params)
                row['Aktionen'] = {
                    "href": f"{edit_url}?{query}",
                    "label": "Bearbeiten",
                }
            else:
                row['Aktionen'] = None

        rows.append(row)

    columns_meta = [
        {
            'name': spec['label'],
            'is_fk': column_is_fk.get(spec['label'], False),
            'slug': spec.get('slug'),
            'sortable': spec.get('sortable', False),
        }
        for spec in column_specs
    ]

    if add_actions:
        columns_meta.insert(0, {'name': 'Aktionen', 'is_fk': False, 'slug': None, 'sortable': False})
        # Add visibility column after actions for project entities
        visibility_slug = slugify("Sichtbarkeit")
        columns_meta.insert(1, {'name': 'Sichtbarkeit', 'is_fk': False, 'slug': visibility_slug, 'sortable': True})
        # Add visibility to rows
        for row, subject_res in zip(rows, subjects):
            visibility_label = {
                'private': 'Private',
                'restricted': 'Restricted',
                'public': 'Public'
            }.get(subject_res.public_access_level, subject_res.public_access_level)
            row['Sichtbarkeit'] = visibility_label

    return rows, columns_meta


def _tabular_view(request, entity_type: str):
    cfg = ENTITY_CONFIG.get(entity_type)
    if not cfg:
        return render(request, 'metadata/tabular/error.html', {
            'error': f'Unknown entity type: {entity_type}'
        })

    override_code = request.GET.get('organization')
    org = _resolve_current_org(request, override_code)
    if not org:
        return render(request, 'metadata/tabular/error.html', {
            'error': 'Organization not selected'
        })

    uri_contains = cfg['uri_contains']
    desired_columns = cfg['columns']
    column_specs = _build_column_specs(desired_columns)
    add_actions = _entity_has_actions(entity_type)
    sort_specs = list(column_specs)
    visibility_spec = {
        'label': 'Sichtbarkeit',
        'matchers': set(),
        'raw_matchers': [],
        'sort_predicates': [],
        'sortable': True,
        'sort_key': 'visibility',
        'slug': slugify("Sichtbarkeit"),
    }
    if add_actions:
        sort_specs.append(visibility_spec)

    # Query organization resources for this entity by URI pattern
    subjects_qs = (
        Resource.objects
        .for_organization(org)
        .exclude(resource_type=ResourceType.LITERAL)
        .filter(uri__icontains=uri_contains)
    )

    sort_slug = request.GET.get('sort')
    requested_order = request.GET.get('order', 'asc')
    sort_order = 'desc' if requested_order == 'desc' else 'asc'
    sort_spec = next(
        (spec for spec in sort_specs if spec.get('slug') == sort_slug and spec.get('sortable')),
        None,
    )
    subjects_qs = _apply_subject_sort(subjects_qs, sort_spec, sort_order)

    # Paginate subjects
    page_number = request.GET.get('page', 1)
    paginator = Paginator(subjects_qs, 20)
    page_obj = paginator.get_page(page_number)

    label_resolver: Optional[EntityLabelResolver] = None
    try:
        mapping = Mapping.get_active_for_organization(org)
    except Exception:
        mapping = None
        logger.debug("Failed to load mapping for org %s", org.code, exc_info=True)

    if mapping:
        try:
            schema_service = SchemaWorkspaceService(mapping=mapping, organization=org)
        except Exception:
            logger.debug(
                "Failed to initialize schema workspace service for org %s",
                org.code,
                exc_info=True,
            )
        else:
            label_resolver = EntityLabelResolver(schema_service)

    # Build rows for current page
    rows, columns_meta = _build_rows_for_subjects(
        list(page_obj.object_list),
        column_specs,
        entity_type=entity_type,
        org=org,
        label_resolver=label_resolver,
    )

    # Replace page_obj.object_list with row dicts while preserving pagination metadata
    # We need to create a new page object with the same pagination metadata but different object_list
    from django.core.paginator import Page
    
    # Create a list that matches the pagination structure
    # We can't directly modify page_obj, so we create a custom page-like object
    class RowPage:
        def __init__(self, original_page, rows_list):
            self._original_page = original_page
            self._rows = rows_list
            # Delegate pagination metadata to original page
            self.number = original_page.number
            self.paginator = original_page.paginator
            self.has_previous = original_page.has_previous
            self.has_next = original_page.has_next
            self.previous_page_number = original_page.previous_page_number
            self.next_page_number = original_page.next_page_number
            self.start_index = original_page.start_index
            self.end_index = original_page.end_index
        
        def __iter__(self):
            return iter(self._rows)
        
        def __len__(self):
            return len(self._rows)
        
        def __getitem__(self, index):
            return self._rows[index]
    
    rows_page = RowPage(page_obj, rows)

    # Map entity_type to URL name for pagination links
    entity_type_to_url = {
        'project': 'metadata:tabular_projects',
        'event': 'metadata:tabular_ereignis',
        'actor': 'metadata:tabular_akteur',
        'digital_object': 'metadata:tabular_digitales_objekt',
        'akteur': 'metadata:tabular_akteur',
        'ereignis': 'metadata:tabular_ereignis',
        'digitales_objekt': 'metadata:tabular_digitales_objekt',
        'physisches_objekt': 'metadata:tabular_physisches_objekt',
        'informationstraeger': 'metadata:tabular_informationstraeger',
        'ort': 'metadata:tabular_ort',
        'sammlung': 'metadata:tabular_sammlung',
        'equipment_software': 'metadata:tabular_equipment_software',
        'equipmentart': 'metadata:tabular_equipmentart',
    }
    url_name = entity_type_to_url.get(entity_type, 'metadata:tabular_projects')
    
    base_query = request.GET.copy()
    for key in ("sort", "order", "page"):
        base_query.pop(key, None)
    preserved_query = base_query.urlencode()

    context = {
        'entity_type': entity_type,
        'dataset_name': cfg['dataset_name'],
        'columns': columns_meta,
        'page_obj': rows_page,
        'url_name': url_name,  # URL name for pagination links
        'organization_code': org.code if org else None,
        'current_sort': {
            'column': sort_spec['slug'] if sort_spec else '',
            'order': sort_order,
        },
        'preserved_query': preserved_query,
    }

    # Embed compact table inside other pages
    if request.GET.get('embed'):
        return render(request, 'metadata/tabular/embed_table.html', context)

    if request.headers.get('HX-Request'):
        return render(request, 'metadata/tabular/partials/table_rows.html', context)

    return render(request, 'metadata/tabular/table.html', context)


# View functions for all entity types
def project_table_view(request):
    return _tabular_view(request, 'project')

def event_table_view(request):
    return _tabular_view(request, 'event')

def actor_table_view(request):
    return _tabular_view(request, 'actor')

def digital_object_table_view(request):
    return _tabular_view(request, 'digital_object')

# DigiKunst entity views
def akteur_table_view(request):
    return _tabular_view(request, 'akteur')

def akteur_relation_table_view(request):
    return _tabular_view(request, 'akteur_relation')

def bestehender_lizenzvertrag_table_view(request):
    return _tabular_view(request, 'bestehender_lizenzvertrag')

def digitales_objekt_table_view(request):
    return _tabular_view(request, 'digitales_objekt')

def eigenschaft_table_view(request):
    return _tabular_view(request, 'eigenschaft')

def equipment_software_table_view(request):
    return _tabular_view(request, 'equipment_software')

def equipmentart_table_view(request):
    return _tabular_view(request, 'equipmentart')

def ereignis_table_view(request):
    return _tabular_view(request, 'ereignis')

def ereignis_beschreibung_table_view(request):
    return _tabular_view(request, 'ereignis_beschreibung')

def ereignis_eigenschaftswert_table_view(request):
    return _tabular_view(request, 'ereignis_eigenschaftswert')

def ereignis_relation_table_view(request):
    return _tabular_view(request, 'ereignis_relation')

def ereignis_rolle_table_view(request):
    return _tabular_view(request, 'ereignis_rolle')

def informationstraeger_table_view(request):
    return _tabular_view(request, 'informationstraeger')

def informationstraeger_eigenschaftswert_table_view(request):
    return _tabular_view(request, 'informationstraeger_eigenschaftswert')

def inhaltswarnung_table_view(request):
    return _tabular_view(request, 'inhaltswarnung')

def organisationseinheit_table_view(request):
    return _tabular_view(request, 'organisationseinheit')

def ort_table_view(request):
    return _tabular_view(request, 'ort')

def physisches_objekt_table_view(request):
    return _tabular_view(request, 'physisches_objekt')

def produkt_id_table_view(request):
    return _tabular_view(request, 'produkt_id')

def projekt_beschreibung_table_view(request):
    return _tabular_view(request, 'projekt_beschreibung')

def projekt_eigenschaftswert_table_view(request):
    return _tabular_view(request, 'projekt_eigenschaftswert')

def projekt_relation_table_view(request):
    return _tabular_view(request, 'projekt_relation')

def sammlung_table_view(request):
    return _tabular_view(request, 'sammlung')

def schlagwort_table_view(request):
    return _tabular_view(request, 'schlagwort')
