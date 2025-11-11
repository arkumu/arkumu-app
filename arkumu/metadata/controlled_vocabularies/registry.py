"""
Shared configuration describing canonical controlled vocabularies.

The registry centralises the mapping between CSV columns, RDF predicates,
field requirements, and input semantics so multiple code paths (import
pipeline, forms, services) can rely on a single source of truth.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, Optional, Sequence

SKOS_ALT_LABEL_URI = "http://www.w3.org/2004/02/skos/core#altLabel"
SKOS_BROADER_URI = "http://www.w3.org/2004/02/skos/core#broader"
XSD_BOOLEAN_URI = "http://www.w3.org/2001/XMLSchema#boolean"


@dataclass(frozen=True)
class ColumnConfig:
    """Describe how a single logical column maps to RDF triples."""

    predicate_uri: str
    value_type: str = "literal"  # literal, boolean, iri, reference
    language: Optional[str] = None
    datatype: Optional[str] = None
    split: bool = False
    split_delimiter: str = ","
    transform: Optional[Callable[[str], str]] = None
    label: Optional[str] = None
    help_text: Optional[str] = None
    required: bool = False

    def form_label(self, column: str) -> str:
        return self.label or column


@dataclass(frozen=True)
class VocabularyConfig:
    """Configuration for a controlled vocabulary namespace."""

    filename: str
    class_uri: str
    display_name: str
    label_priority: Sequence[str]
    columns: Dict[str, ColumnConfig]
    slug_prefix: Optional[str] = None  # Optional suggested slug prefix (e.g. role-)


VOCABULARY_REGISTRY: Dict[str, VocabularyConfig] = {
    "event_types": VocabularyConfig(
        filename="Event_Types_canonical.csv",
        class_uri="http://arkumu.org/data/types/ereignistyp",
        display_name="Event Types",
        label_priority=("German Name", "English Name"),
        columns={
            "English Name": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/englischer-name-des-ereignistyps",
                language="en",
                required=True,
            ),
            "English Synonyms": ColumnConfig(
                predicate_uri=SKOS_ALT_LABEL_URI,
                language="en",
                split=True,
                help_text="Provide one synonym per line.",
            ),
            "German Name": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/deutscher-name-des-ereignistyps",
                language="de",
                required=True,
            ),
            "German Synonyms": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/synonyme",
                language="de",
                split=True,
                help_text="Ein Synonym pro Zeile angeben.",
            ),
            "Wikidata ID": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/wikidata-id",
            ),
            "GND ID": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/gnd-nummer",
            ),
            "AAT ID": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/aat-id",
            ),
            "LIDO Terminology ID": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/lido-terminologie-id",
            ),
        },
        slug_prefix="event-type-",
    ),
    "project_types": VocabularyConfig(
        filename="Project_Types_canonical.csv",
        class_uri="http://arkumu.org/data/types/projektart",
        display_name="Project Types",
        label_priority=("German Name", "English Name"),
        columns={
            "English Name": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/englischer-name-der-projektart",
                language="en",
                required=True,
            ),
            "German Name": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/deutscher-name-der-projektart",
                language="de",
                required=True,
            ),
            "Wikidata ID": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/wikidata-id",
            ),
        },
        slug_prefix="project-type-",
    ),
    "project_categories": VocabularyConfig(
        filename="Project_Categories_canonical.csv",
        class_uri="http://arkumu.org/data/types/projektkategorie",
        display_name="Project Categories",
        label_priority=("German Name", "English Name"),
        columns={
            "English Name": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/englischer-name",
                language="en",
                required=True,
            ),
            "English Synonyms": ColumnConfig(
                predicate_uri=SKOS_ALT_LABEL_URI,
                language="en",
                split=True,
                help_text="Provide one synonym per line.",
            ),
            "German Name": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/deutscher-name",
                language="de",
                required=True,
            ),
            "German Synonyms": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/synonyme",
                language="de",
                split=True,
                help_text="Ein Synonym pro Zeile angeben.",
            ),
            "Parent Project Category": ColumnConfig(
                predicate_uri=SKOS_BROADER_URI,
                value_type="reference",
                label="Parent category",
                help_text="Optional übergeordnete Kategorie auswählen.",
            ),
            "German Breadcrumb": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/deutscher-name-der-projektkategorie-breadcrumb",
                language="de",
            ),
            "English Breadcrumb": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/englischer-name-der-projektkategorie-breadcrumb",
                language="en",
            ),
            "Wikidata ID": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/wikidata-id",
            ),
            "GND ID": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/gnd-nummer",
            ),
            "AAT ID": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/aat-id",
            ),
            "filmportal.de Category ID": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/filmportal-kategorie-id",
                label="filmportal.de Category ID",
            ),
        },
        slug_prefix="project-category-",
    ),
    "roles": VocabularyConfig(
        filename="Roles_canonical.csv",
        class_uri="http://arkumu.org/data/types/rolle",
        display_name="Roles",
        label_priority=("German Name", "English Name"),
        columns={
            "German Name": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/deutscher-name",
                language="de",
                required=True,
            ),
            "German Synonyms": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/synonyme",
                language="de",
                split=True,
                help_text="Ein Synonym pro Zeile angeben.",
            ),
            "English Name": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/englischer-name",
                language="en",
                required=True,
            ),
            "English Synonyms": ColumnConfig(
                predicate_uri=SKOS_ALT_LABEL_URI,
                language="en",
                split=True,
                help_text="Provide one synonym per line.",
            ),
            "Wikidata ID": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/wikidata-id",
            ),
            "GND ID (male)": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/gnd-nummer-maennlich",
                label="GND ID (male)",
            ),
            "GND ID (female)": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/gnd-nummer-weiblich",
                label="GND ID (female)",
            ),
            "GND ID (group)": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/gnd-nummer-gruppe",
                label="GND ID (group)",
            ),
            "AAT ID": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/aat-id",
            ),
            "Parent Role": ColumnConfig(
                predicate_uri=SKOS_BROADER_URI,
                value_type="reference",
                label="Parent role",
            ),
            "German Breadcrumb": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/deutscher-name-der-rolle-breadcrumb",
                language="de",
            ),
            "English Breadcrumb": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/englischer-name-der-rolle-breadcrumb",
                language="en",
            ),
            'Pre-selects "ist Urheber:in" automatically': ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/waehlt-ist-urheber-in-automatisch-aus",
                value_type="boolean",
                datatype=XSD_BOOLEAN_URI,
                help_text='Wenn aktiviert, wird die Beziehung "ist Urheber:in" automatisch gesetzt.',
            ),
            'Pre-selects "besitzt Leistungsschutzrechte" automatically': ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/waehlt-besitzt-leistungsschutzrechte-automatisch-aus",
                value_type="boolean",
                datatype=XSD_BOOLEAN_URI,
                help_text='Wenn aktiviert, wird die Beziehung "besitzt Leistungsschutzrechte" automatisch gesetzt.',
            ),
        },
        slug_prefix="role-",
    ),
    "equipment_types": VocabularyConfig(
        filename="Equipment_Types_canonical.csv",
        class_uri="http://arkumu.org/data/types/equipmentart",
        display_name="Equipment Types",
        label_priority=("German Name", "English Name"),
        columns={
            "English Name": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/englischer-name-der-equipmentart",
                language="en",
                required=True,
            ),
            "German Name": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/deutscher-name-der-equipmentart",
                language="de",
                required=True,
            ),
            "Wikidata ID": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/wikidata-id",
            ),
            "GND ID": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/gnd-nummer",
            ),
            "AAT ID": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/aat-id",
            ),
        },
        slug_prefix="equipment-type-",
    ),
    "information_storage_medium_types": VocabularyConfig(
        filename="Information_Storage_Medium_Types_canonical.csv",
        class_uri="http://arkumu.org/data/types/informationstraegertyp",
        display_name="Information Storage Medium Types",
        label_priority=("German Name", "English Name"),
        columns={
            "English Name": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/englischer-name",
                language="en",
                required=True,
            ),
            "English Synonyms": ColumnConfig(
                predicate_uri=SKOS_ALT_LABEL_URI,
                language="en",
                split=True,
                help_text="Provide one synonym per line.",
            ),
            "German Name": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/deutscher-name",
                language="de",
                required=True,
            ),
            "German Synonyms": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/synonyme",
                language="de",
                split=True,
                help_text="Ein Synonym pro Zeile angeben.",
            ),
            "Parent Information Storage Medium Type": ColumnConfig(
                predicate_uri=SKOS_BROADER_URI,
                value_type="reference",
                label="Parent type",
            ),
            "German Breadcrumb": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/deutscher-name-des-informationstraegertyps-breadcrumb",
                language="de",
            ),
            "English Breadcrumb": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/englischer-name-des-informationstraegertyps-breadcrumb",
                language="en",
            ),
            "Wikidata ID": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/wikidata-id",
            ),
            "GND ID": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/gnd-nummer",
            ),
            "AAT ID": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/aat-id",
            ),
            "PBCore Link": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/pbcore-link",
                value_type="iri",
                help_text="Full URL to the PBCore vocabulary entry.",
            ),
        },
        slug_prefix="information-storage-medium-type-",
    ),
    "organisational_units": VocabularyConfig(
        filename="Organisational_Units_canonical.csv",
        class_uri="http://arkumu.org/data/types/organisationseinheit",
        display_name="Organisational Units",
        label_priority=("German Name", "English Name"),
        columns={
            "English Name": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/englischer-name",
                language="en",
                required=True,
            ),
            "German Name": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/deutscher-name",
                language="de",
                required=True,
            ),
            "Parent Organisational Unit": ColumnConfig(
                predicate_uri=SKOS_BROADER_URI,
                value_type="reference",
                label="Parent organisational unit",
            ),
            "German Breadcrumb": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/deutscher-name-der-organisationseinheit-breadcrumb",
                language="de",
            ),
            "English Breadcrumb": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/englischer-name-der-organisationseinheit-breadcrumb",
                language="en",
            ),
            "German Description": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/deutsche-beschreibung",
                language="de",
                help_text="Freitextbeschreibung auf Deutsch.",
            ),
            "English Description": ColumnConfig(
                predicate_uri="http://arkumu.org/data/properties/englische-beschreibung",
                language="en",
                help_text="Free-text description in English.",
            ),
        },
        slug_prefix="organisational-unit-",
    ),
}


def get_vocabulary_config(key: str) -> VocabularyConfig:
    try:
        return VOCABULARY_REGISTRY[key]
    except KeyError as exc:
        raise KeyError(f"Unknown controlled vocabulary '{key}'") from exc


def list_vocabulary_keys() -> Sequence[str]:
    return list(VOCABULARY_REGISTRY.keys())


def iter_vocabulary_configs() -> Iterable[tuple[str, VocabularyConfig]]:
    return VOCABULARY_REGISTRY.items()


_COLUMN_FIELD_PATTERN = re.compile(r"[^0-9a-zA-Z]+")


def column_to_field_name(column: str) -> str:
    return _COLUMN_FIELD_PATTERN.sub("_", column).strip("_").lower()


def field_name_to_column(config: VocabularyConfig, field_name: str) -> Optional[str]:
    for column in config.columns.keys():
        if column_to_field_name(column) == field_name:
            return column
    return None
