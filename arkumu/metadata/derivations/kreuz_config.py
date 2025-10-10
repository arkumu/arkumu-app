"""Configuration for Kreuz (cross-table) derivations.

This module enumerates the canonical predicates exposed by known Kreuz datasets
and defines reusable derivation patterns that the management command can apply
without hard-coding dataset-specific logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, Sequence, Tuple

# Canonical predicate URIs used across Kreuz datasets.
PROJECT = "http://arkumu.org/data/properties/projekt"
EVENT = "http://arkumu.org/data/properties/ereignis"
DIGITAL_OBJECT = "http://arkumu.org/data/properties/digitales-objekt"
INFORMATION_CARRIER = "http://arkumu.org/data/properties/informationstraeger"
KEYWORD = "http://arkumu.org/data/properties/schlagwort"
EQUIPMENT = "http://arkumu.org/data/properties/equipment-und-software"
ACTOR = "http://arkumu.org/data/properties/akteurin"
ACTOR_IN_EVENT = "http://arkumu.org/data/properties/akteurin-im-ereignis"
ROLE_IN_EVENT = "http://arkumu.org/data/properties/rollen-der-akteurin-im-ereignis"

# RDF structural predicate used to associate junction rows with dataset resources.
DCTERMS_IS_PART_OF = "http://purl.org/dc/terms/isPartOf"


@dataclass(frozen=True)
class DerivedTripleRecipe:
    """Declarative instruction for emitting a derived triple."""

    subject_property: str
    object_property: str
    predicate_uri: str
    description: str = ""


@dataclass(frozen=True)
class DerivationPattern:
    """Group of derived triple recipes activated by a canonical predicate set."""

    name: str
    required_properties: Tuple[str, ...]
    recipes: Tuple[DerivedTripleRecipe, ...]
    description: str = ""


@dataclass(frozen=True)
class DatasetProfile:
    """Metadata describing canonical predicates for a Kreuz dataset."""

    name: str
    canonical_predicates: Tuple[str, ...]
    pattern_names: Tuple[str, ...] | None = None
    notes: Tuple[str, ...] = ()


DERIVATION_PATTERNS: Dict[str, DerivationPattern] = {
    "project_event": DerivationPattern(
        name="project_event",
        required_properties=(PROJECT, EVENT),
        recipes=(
            DerivedTripleRecipe(
                subject_property=PROJECT,
                object_property=EVENT,
                predicate_uri=EVENT,
                description="Project references an Event",
            ),
            DerivedTripleRecipe(
                subject_property=EVENT,
                object_property=PROJECT,
                predicate_uri=PROJECT,
                description="Event references a Project",
            ),
        ),
        description="Bilateral project-event relationships",
    ),
    "event_digital_object": DerivationPattern(
        name="event_digital_object",
        required_properties=(EVENT, DIGITAL_OBJECT),
        recipes=(
            DerivedTripleRecipe(
                subject_property=EVENT,
                object_property=DIGITAL_OBJECT,
                predicate_uri=DIGITAL_OBJECT,
                description="Event references a Digital Object",
            ),
        ),
        description="Event-to-digital-object linkage",
    ),
    "project_digital_object": DerivationPattern(
        name="project_digital_object",
        required_properties=(PROJECT, DIGITAL_OBJECT),
        recipes=(
            DerivedTripleRecipe(
                subject_property=PROJECT,
                object_property=DIGITAL_OBJECT,
                predicate_uri=DIGITAL_OBJECT,
                description="Project references a Digital Object",
            ),
        ),
        description="Direct project-to-digital-object linkage",
    ),
    "project_event_digital_bridge": DerivationPattern(
        name="project_event_digital_bridge",
        required_properties=(PROJECT, EVENT, DIGITAL_OBJECT),
        recipes=(
            DerivedTripleRecipe(
                subject_property=PROJECT,
                object_property=DIGITAL_OBJECT,
                predicate_uri=DIGITAL_OBJECT,
                description="Project references Digital Objects via junction",
            ),
        ),
        description="Ensures project↔digital-object edges when all three predicates are present",
    ),
    "project_information_carrier": DerivationPattern(
        name="project_information_carrier",
        required_properties=(PROJECT, INFORMATION_CARRIER),
        recipes=(
            DerivedTripleRecipe(
                subject_property=PROJECT,
                object_property=INFORMATION_CARRIER,
                predicate_uri=INFORMATION_CARRIER,
                description="Project references an Information Carrier",
            ),
        ),
        description="Project-to-information-carrier linkage",
    ),
    "event_information_carrier": DerivationPattern(
        name="event_information_carrier",
        required_properties=(EVENT, INFORMATION_CARRIER),
        recipes=(
            DerivedTripleRecipe(
                subject_property=EVENT,
                object_property=INFORMATION_CARRIER,
                predicate_uri=INFORMATION_CARRIER,
                description="Event references an Information Carrier",
            ),
        ),
        description="Event-to-information-carrier linkage",
    ),
    "project_keyword": DerivationPattern(
        name="project_keyword",
        required_properties=(PROJECT, KEYWORD),
        recipes=(
            DerivedTripleRecipe(
                subject_property=PROJECT,
                object_property=KEYWORD,
                predicate_uri=KEYWORD,
                description="Project references a Keyword",
            ),
        ),
        description="Project-to-keyword linkage",
    ),
    "project_equipment": DerivationPattern(
        name="project_equipment",
        required_properties=(PROJECT, EQUIPMENT),
        recipes=(
            DerivedTripleRecipe(
                subject_property=PROJECT,
                object_property=EQUIPMENT,
                predicate_uri=EQUIPMENT,
                description="Project references Equipment/Software",
            ),
        ),
        description="Project-to-equipment linkage",
    ),
    "event_equipment": DerivationPattern(
        name="event_equipment",
        required_properties=(EVENT, EQUIPMENT),
        recipes=(
            DerivedTripleRecipe(
                subject_property=EVENT,
                object_property=EQUIPMENT,
                predicate_uri=EQUIPMENT,
                description="Event references Equipment/Software",
            ),
        ),
        description="Event-to-equipment linkage",
    ),
    "project_actor": DerivationPattern(
        name="project_actor",
        required_properties=(PROJECT, ACTOR),
        recipes=(
            DerivedTripleRecipe(
                subject_property=PROJECT,
                object_property=ACTOR,
                predicate_uri=ACTOR,
                description="Project references an Actor",
            ),
        ),
        description="Project-to-actor linkage",
    ),
    "event_actor": DerivationPattern(
        name="event_actor",
        required_properties=(EVENT, ACTOR_IN_EVENT),
        recipes=(
            DerivedTripleRecipe(
                subject_property=EVENT,
                object_property=ACTOR_IN_EVENT,
                predicate_uri=ACTOR_IN_EVENT,
                description="Event references an Actor role",
            ),
        ),
        description="Event-to-actor linkage via role junction",
    ),
    "project_event_actor_bridge": DerivationPattern(
        name="project_event_actor_bridge",
        required_properties=(PROJECT, EVENT, ACTOR_IN_EVENT),
        recipes=(
            DerivedTripleRecipe(
                subject_property=PROJECT,
                object_property=ACTOR_IN_EVENT,
                predicate_uri=ACTOR_IN_EVENT,
                description="Project references an Actor through event junction",
            ),
        ),
        description="Derives project-to-actor edges when project/event/actor are co-located",
    ),
}


KREUZ_DATASET_PROFILES: Dict[str, Dict[str, DatasetProfile]] = {
    "khm": {
        "01_grundereignis": DatasetProfile(
            name="01_Grundereignis",
            canonical_predicates=(PROJECT, EVENT, DIGITAL_OBJECT),
            pattern_names=("project_digital_object",),
            notes=("Derive project↔digital links directly from event rows",),
        ),
        "02_kreuz_projekte_personen": DatasetProfile(
            name="02_Kreuz_Projekte_Personen",
            canonical_predicates=(PROJECT, ACTOR),
            pattern_names=("project_actor",),
            notes=("Links KHM projects to persons/actors",),
        ),
        "04_kreuz_betreuende_projekte": DatasetProfile(
            name="04_Kreuz_Betreuende_Projekte",
            canonical_predicates=(PROJECT, ACTOR),
            pattern_names=("project_actor",),
            notes=("Supervisor assignments for projects",),
        ),
        "07_kreuz_projekte_keywords": DatasetProfile(
            name="07_Kreuz_Projekte_Keywords",
            canonical_predicates=(PROJECT, KEYWORD),
            pattern_names=("project_keyword",),
        ),
        "09_kreuz_projekte_informationstraeger": DatasetProfile(
            name="09_Kreuz_Projekte_Informationsträger",
            canonical_predicates=(PROJECT, INFORMATION_CARRIER),
            pattern_names=("project_information_carrier",),
        ),
        "11_kreuz_digitaleobjekte_proj": DatasetProfile(
            name="11_Kreuz_DigitaleObjekte_Proj",
            canonical_predicates=(PROJECT, DIGITAL_OBJECT),
            pattern_names=("project_digital_object",),
        ),
        "16_kreuz_events_projekte": DatasetProfile(
            name="16_Kreuz_Events_Projekte",
            canonical_predicates=(PROJECT, EVENT),
            pattern_names=("project_event",),
            notes=("Project↔Event junction (may include additional context)",),
        ),
        "18_kreuz_projekte_equipmentssoftware": DatasetProfile(
            name="18_Kreuz_Projekte_EquipmentSoftware",
            canonical_predicates=(PROJECT, EQUIPMENT),
            pattern_names=("project_equipment",),
        ),
    },
    "fuk": {
        "projekt_ereignis": DatasetProfile(
            name="Projekt_Ereignis",
            canonical_predicates=(PROJECT, EVENT),
            pattern_names=("project_event",),
        ),
        "ereignis_digitales_objekt": DatasetProfile(
            name="Ereignis_Digitales_Objekt",
            canonical_predicates=(EVENT, DIGITAL_OBJECT),
            pattern_names=("event_digital_object", "project_event_digital_bridge"),
            notes=("Bridges events to their digital surrogates",),
        ),
        "ereignis_informationstraeger": DatasetProfile(
            name="Ereignis_Informationsträger",
            canonical_predicates=(EVENT, INFORMATION_CARRIER),
            pattern_names=("event_information_carrier",),
        ),
        "ereignis_equipment_software": DatasetProfile(
            name="Ereignis_Equipment_Software",
            canonical_predicates=(EVENT, EQUIPMENT),
            pattern_names=("event_equipment",),
            notes=("Equipment assigned at event level",),
        ),
        "projekt_schlagworte": DatasetProfile(
            name="Projekt_Schlagworte",
            canonical_predicates=(PROJECT, KEYWORD),
            pattern_names=("project_keyword",),
        ),
        "akteurin_ereignis_kreuztabelle": DatasetProfile(
            name="AkteurIn_Ereignis_Kreuztabelle",
            canonical_predicates=(EVENT, ACTOR_IN_EVENT, ROLE_IN_EVENT),
            pattern_names=("event_actor", "project_event_actor_bridge"),
            notes=("Role-based actor assignments for events",),
        ),
    },
}

# Share Folkwang configuration with HMT until a dedicated profile exists.
KREUZ_DATASET_PROFILES["hmt"] = KREUZ_DATASET_PROFILES["fuk"]


def normalize_dataset_key(dataset_name: str | None) -> str | None:
    """Normalize dataset names for dictionary lookups."""
    if not dataset_name:
        return None
    normalized = dataset_name.strip().lower()
    if normalized.endswith(".csv"):
        normalized = normalized[:-4]
    return normalized


def get_profiles_for_org(org_code: str) -> Mapping[str, DatasetProfile]:
    """Return dataset profiles for the given organization (normalized keys)."""
    return KREUZ_DATASET_PROFILES.get(org_code.lower(), {})


def iter_applicable_patterns(
    org_code: str,
    dataset_name: str | None,
    present_properties: Iterable[str],
) -> Sequence[DerivationPattern]:
    """Determine derivation patterns that should apply to a junction node."""

    present = tuple({prop for prop in present_properties if prop})
    profiles = get_profiles_for_org(org_code)
    pattern_ids: Sequence[str] | None = None

    if dataset_name:
        dataset_profile = profiles.get(normalize_dataset_key(dataset_name))
        if dataset_profile and dataset_profile.pattern_names:
            pattern_ids = dataset_profile.pattern_names

    patterns: list[DerivationPattern] = []
    candidate_patterns = (
        [DERIVATION_PATTERNS[name] for name in pattern_ids]
        if pattern_ids
        else DERIVATION_PATTERNS.values()
    )

    property_set = set(present)
    for pattern in candidate_patterns:
        if set(pattern.required_properties).issubset(property_set):
            patterns.append(pattern)

    return patterns


def all_configured_canonical_properties() -> Tuple[str, ...]:
    """Return the union of canonical predicate URIs referenced by patterns."""

    uris: set[str] = set()
    for pattern in DERIVATION_PATTERNS.values():
        uris.update(pattern.required_properties)
        for recipe in pattern.recipes:
            uris.add(recipe.subject_property)
            uris.add(recipe.object_property)
            uris.add(recipe.predicate_uri)
    return tuple(sorted(uris))
