"""Schema driven metadata mask primitives.

This module introduces a lightweight mask schema layer that sits above the
current metadata entry service. The immediate goal is to express editorial form
intent separately from persistence concerns and separately from institution
specific mapping bindings.

The first pilot schema intentionally models only the current project entry flow.
It can later be expanded to mirror Digikunst form intent more closely.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from arkumu.catalog.services.project_views import CardURIs, ProjectURIs
from arkumu.metadata.models.mappings import Mapping


MASK_PHASE_CREATE = "create"
MASK_PHASE_ENRICHMENT = "enrichment"
MASK_PHASE_ALL = "all"

ACTOR_ENGLISH_NAME_URI = "http://arkumu.org/data/properties/englischer-name"
PLACE_TYPE_URI = "http://arkumu.org/data/types/ort"
PLACE_NAME_URI = "http://arkumu.org/data/properties/deutscher-name-des-ortes"
WIKIDATA_ID_URI = "http://arkumu.org/data/properties/wikidata-id"
GND_ID_URI = "http://arkumu.org/data/properties/gnd-nummer"
VIAF_ID_URI = "http://arkumu.org/data/properties/viaf-id"
COLLECTION_TYPE_URI = "http://arkumu.org/data/types/sammlung"
COLLECTION_NAME_DE_URI = "http://arkumu.org/data/properties/deutscher-name-der-sammlung"
COLLECTION_NAME_EN_URI = "http://arkumu.org/data/properties/englischer-name-der-sammlung"
COLLECTION_KIND_URI = "http://arkumu.org/data/properties/sammlungsart"
COLLECTION_DESCRIPTION_DE_URI = "http://arkumu.org/data/properties/deutsche-beschreibung"
COLLECTION_DESCRIPTION_EN_URI = "http://arkumu.org/data/properties/englische-beschreibung"
INFORMATION_CARRIER_TYPE_URI = "http://arkumu.org/data/types/informationstraeger"
INFORMATION_CARRIER_KIND_URI = "http://arkumu.org/data/properties/informationstraegertyp"
INFORMATION_CARRIER_NAME_DE_URI = "http://arkumu.org/data/properties/deutsche-produkt-bezeichnung"
INFORMATION_CARRIER_NAME_EN_URI = "http://arkumu.org/data/properties/englische-produkt-bezeichnung"
INFORMATION_CARRIER_LABEL_URI = "http://arkumu.org/data/properties/label-handelsmarke"
INFORMATION_CARRIER_DESCRIPTION_DE_URI = "http://arkumu.org/data/properties/deutsche-beschreibung"
INFORMATION_CARRIER_DESCRIPTION_EN_URI = "http://arkumu.org/data/properties/englische-beschreibung"
INFORMATION_CARRIER_MATERIAL_URI = "http://arkumu.org/data/properties/materialschlagwort"
KEYWORD_TYPE_URI = "http://arkumu.org/data/types/schlagwort"
KEYWORD_LABEL_DE_URI = "http://arkumu.org/data/properties/deutsches-wikidata-label"
DIGITAL_OBJECT_LICENSE_URI = "http://arkumu.org/data/properties/lizenzstatus"
DIGITAL_OBJECT_MEDIA_TYPE_URI = "http://arkumu.org/data/properties/medientyp"
DIGITAL_OBJECT_RETENTION_TYPE_URI = "http://arkumu.org/data/properties/erhaltungstyp"
DIGITAL_OBJECT_ORIGIN_TYPE_URI = "http://arkumu.org/data/properties/entstehung"


@dataclass(frozen=True)
class RequiredRule:
    """Describes whether a field is required at the mask level."""

    kind: str = "never"  # never, always, conditional
    message: str = "Pflichtfeld"
    expression: Optional[str] = None
    frontend_grails_required: Optional[bool] = None
    backend_grails_required: Optional[bool] = None
    source_detail: Optional[str] = None
    evidence_source: str = "Digikunst-Notiz aus Grails-Analyse"

    @property
    def is_required(self) -> bool:
        return self.kind == "always"

    @property
    def frontend_grails_label(self) -> str:
        return self._bool_label(self.frontend_grails_required)

    @property
    def backend_grails_label(self) -> str:
        return self._bool_label(self.backend_grails_required)

    @staticmethod
    def _bool_label(value: Optional[bool]) -> str:
        if value is True:
            return "ja"
        if value is False:
            return "nein"
        return "unbekannt"


@dataclass(frozen=True)
class ControlledVocabularyRef:
    """Metadata for fields backed by a controlled vocabulary source."""

    source_type: str
    key: str
    allow_free_text: bool = False
    organization_scoped: bool = False
    source_label: str = "Arkumu Vokabular"


@dataclass(frozen=True)
class SemanticSlot:
    """Stable semantic target behind a mask field."""

    slot_id: str
    canonical_property_uri: Optional[str]
    value_type: str = "literal"  # literal, relation, structured
    relation_target: Optional[str] = None
    multi: bool = False
    source_label: str = "Arkumu Canonical Model"


@dataclass(frozen=True)
class MaskField:
    """Editorial definition of one field in a mask."""

    name: str
    label: str
    semantic_slot: SemanticSlot
    widget: str = "text"
    placeholder: str = ""
    help_text: Optional[str] = None
    required_rule: RequiredRule = field(default_factory=RequiredRule)
    multi: bool = False
    visibility: str = "always"  # always, create, enrichment
    vocabulary: Optional[ControlledVocabularyRef] = None
    presentation_source: str = "Arkumu-Maskenschema"


@dataclass(frozen=True)
class MaskSection:
    """Logical grouping of mask fields."""

    name: str
    label: str
    description: Optional[str]
    fields: List[MaskField]
    presentation_source: str = "Arkumu-Maskenschema"


@dataclass(frozen=True)
class MaskSchema:
    """High level editorial mask definition for one entity type."""

    schema_id: str
    entity_type: str
    label: str
    source: str
    sections: List[MaskSection]
    create_supported: bool = False
    create_redirect_url_name: Optional[str] = None

    def get_section(self, section_name: str) -> MaskSection:
        for section in self.sections:
            if section.name == section_name:
                return section
        raise ValueError(f"Unknown section '{section_name}'")

    def get_field(self, field_name: str) -> MaskField:
        for section in self.sections:
            for field in section.fields:
                if field.name == field_name:
                    return field
        raise ValueError(f"Unknown field '{field_name}'")


def field_is_visible_in_phase(field: MaskField, phase: str) -> bool:
    """Return whether a field should be shown in the requested phase."""

    normalized = (phase or MASK_PHASE_ALL).strip().lower()
    if normalized == MASK_PHASE_ALL:
        return True
    if field.visibility == "always":
        return True
    return field.visibility == normalized


def normalize_mask_phase(phase: str | None) -> str:
    """Normalize preview phase selection."""

    normalized = (phase or MASK_PHASE_CREATE).strip().lower()
    if normalized in {MASK_PHASE_CREATE, MASK_PHASE_ENRICHMENT, MASK_PHASE_ALL}:
        return normalized
    return MASK_PHASE_CREATE


@dataclass(frozen=True)
class MappingBindingSource:
    """Minimal mapping source wrapper for resolving bindings."""

    organization_code: str
    mapping_name: str
    mapping_config: Dict[str, Any]
    mapping_id: Optional[str] = None


@dataclass(frozen=True)
class MaskBinding:
    """One candidate backing binding for a semantic slot."""

    organization_code: str
    mapping_name: str
    mapping_id: Optional[str]
    dataset_name: str
    column_name: str
    canonical_property_uri: Optional[str]
    canonical_property_label: Optional[str]
    is_multi_value: bool


class MappingConfigBindingResolver:
    """Resolve field bindings from one or more mapping configs.

    The resolver intentionally works across many mappings for an organization.
    It does not depend on a single active mapping.
    """

    def resolve_field_bindings(
        self,
        *,
        field: MaskField,
        organization_code: str,
        mapping_sources: Iterable[MappingBindingSource],
    ) -> List[MaskBinding]:
        canonical_uri = field.semantic_slot.canonical_property_uri
        if not canonical_uri:
            return []
        return self.resolve_canonical_property(
            canonical_property_uri=canonical_uri,
            organization_code=organization_code,
            mapping_sources=mapping_sources,
        )

    def resolve_canonical_property(
        self,
        *,
        canonical_property_uri: str,
        organization_code: str,
        mapping_sources: Iterable[MappingBindingSource],
    ) -> List[MaskBinding]:
        matches: List[MaskBinding] = []
        for source in mapping_sources:
            if source.organization_code.lower() != organization_code.lower():
                continue
            workspace_columns = source.mapping_config.get("workspace_columns", {})
            for column in workspace_columns.values():
                canonical_mapping = column.get("canonical_mapping") or {}
                if canonical_mapping.get("canonical_property_uri") != canonical_property_uri:
                    continue
                matches.append(
                    MaskBinding(
                        organization_code=source.organization_code,
                        mapping_name=source.mapping_name,
                        mapping_id=source.mapping_id,
                        dataset_name=column.get("dataset") or column.get("source") or "",
                        column_name=column.get("name") or "",
                        canonical_property_uri=canonical_mapping.get("canonical_property_uri"),
                        canonical_property_label=canonical_mapping.get("canonical_property_label"),
                        is_multi_value=bool(column.get("is_multi_value")),
                    )
                )
        return matches


def list_available_mask_schemas() -> List[MaskSchema]:
    """Return the currently available editorial masks."""

    return [
        build_project_mask_schema(),
        build_event_mask_schema(),
        build_actor_mask_schema(),
        build_place_mask_schema(),
        build_collection_mask_schema(),
        build_information_carrier_mask_schema(),
        build_keyword_mask_schema(),
        build_digital_object_mask_schema(),
    ]


def list_creatable_mask_schemas() -> List[MaskSchema]:
    """Return masks that can currently drive the productive create flow."""

    return [schema for schema in list_available_mask_schemas() if schema.create_supported]


def get_mask_schema(entity_type: str) -> MaskSchema:
    """Resolve a mask schema by entity type."""

    normalized = (entity_type or "").strip().lower()
    for schema in list_available_mask_schemas():
        if schema.entity_type == normalized:
            return schema
    raise ValueError(f"Unknown mask schema '{entity_type}'")


def load_mapping_sources_for_organization(organization_code: str) -> List[MappingBindingSource]:
    """Load all mappings for one organization.

    The preview intentionally resolves against every mapping for an organization.
    This makes multi mapping situations visible instead of hiding them behind one
    active record.
    """

    if not organization_code:
        return []

    query = Mapping.objects.filter(organization_id=organization_code.lower()).order_by("-created_at")
    return [
        MappingBindingSource(
            organization_code=mapping.organization_id,
            mapping_name=mapping.name,
            mapping_id=str(mapping.id),
            mapping_config=mapping.mapping_config,
        )
        for mapping in query
    ]


def build_project_mask_schema() -> MaskSchema:
    """Build the initial project pilot mask.

    This mirrors the current metadata entry project flow while introducing the
    abstraction needed for future Digikunst driven masks.
    """

    overview = MaskSection(
        name="overview",
        label="Projektübersicht",
        description="Grundlegende Angaben zum Projekt.",
        fields=[
            MaskField(
                name="title",
                label="Titel",
                semantic_slot=SemanticSlot(
                    slot_id="project.preferred_title",
                    canonical_property_uri=CardURIs.TITLE,
                ),
                placeholder="Bevorzugter Titel",
                visibility=MASK_PHASE_CREATE,
                required_rule=RequiredRule(
                    kind="always",
                    frontend_grails_required=True,
                    backend_grails_required=True,
                ),
            ),
            MaskField(
                name="subtitle",
                label="Untertitel",
                semantic_slot=SemanticSlot(
                    slot_id="project.preferred_subtitle",
                    canonical_property_uri=CardURIs.SUBTITLE,
                ),
                placeholder="Verwendung nur wenn nötig",
                visibility=MASK_PHASE_ENRICHMENT,
                required_rule=RequiredRule(
                    kind="never",
                    frontend_grails_required=False,
                    backend_grails_required=False,
                    source_detail="Digikunst Projekt, bevorzugterTitel.untertitel. Im Create Formular kein Pflichtfeld. Im Edit Formular gibt es eine UI Inkonsistenz, Backend behandelt das Feld als optional.",
                ),
            ),
            MaskField(
                name="description",
                label="Beschreibung",
                semantic_slot=SemanticSlot(
                    slot_id="project.description",
                    canonical_property_uri=ProjectURIs.DESCRIPTION,
                ),
                widget="textarea",
                placeholder="Kurzbeschreibung des Projekts",
                visibility=MASK_PHASE_ENRICHMENT,
                required_rule=RequiredRule(
                    kind="never",
                    source_detail="Dieses Feld ist im aktuellen Arkumu Projektpilot nicht direkt identisch mit einem einzelnen Digikunst Hauptformularfeld. Die Digikunst Projektbeschreibung existiert dort als eigener Unterdatensatz oder Modal.",
                ),
            ),
            MaskField(
                name="year_range",
                label="Zeitraum",
                semantic_slot=SemanticSlot(
                    slot_id="project.year_range",
                    canonical_property_uri=None,
                    value_type="structured",
                ),
                placeholder="z. B. 1984-1986",
                visibility=MASK_PHASE_ENRICHMENT,
                required_rule=RequiredRule(
                    kind="never",
                    source_detail="Kein direktes Digikunst Pflichtfeld im dokumentierten Projekt Create Formular.",
                ),
            ),
        ],
    )

    institution = MaskSection(
        name="institution",
        label="Institution",
        description="Verortung des Projekts.",
        fields=[
            MaskField(
                name="institution__label",
                label="Institution",
                semantic_slot=SemanticSlot(
                    slot_id="project.institution",
                    canonical_property_uri=CardURIs.INSTITUTION,
                    value_type="relation",
                    relation_target="institution",
                ),
                placeholder="Name der Einliefernden Hochschule",
                visibility=MASK_PHASE_CREATE,
                required_rule=RequiredRule(
                    kind="always",
                    frontend_grails_required=True,
                    backend_grails_required=True,
                ),
            ),
            MaskField(
                name="institution__code",
                label="Institutions-Code",
                semantic_slot=SemanticSlot(
                    slot_id="project.institution_code",
                    canonical_property_uri=None,
                    value_type="structured",
                ),
                placeholder="Optionaler interner Code",
                visibility=MASK_PHASE_ENRICHMENT,
                required_rule=RequiredRule(
                    kind="never",
                    source_detail="Kein direktes Digikunst Pflichtfeld im dokumentierten Projekt Create Formular.",
                ),
            ),
            MaskField(
                name="project_type",
                label="Projektart",
                semantic_slot=SemanticSlot(
                    slot_id="project.type",
                    canonical_property_uri=ProjectURIs.PROJECT_TYPE_FIELD,
                    value_type="relation",
                    relation_target="project_type",
                ),
                placeholder="z. B. Konzert, Ausstellung",
                visibility=MASK_PHASE_CREATE,
                required_rule=RequiredRule(
                    kind="always",
                    frontend_grails_required=True,
                    backend_grails_required=True,
                ),
                vocabulary=ControlledVocabularyRef(
                    source_type="canonical",
                    key="project_type",
                    allow_free_text=True,
                ),
            ),
        ],
    )

    classification = MaskSection(
        name="classification",
        label="Klassifizierung",
        description="Schlagworte und Kategorien für die spätere Suche.",
        fields=[
            MaskField(
                name="categories",
                label="Kategorien",
                semantic_slot=SemanticSlot(
                    slot_id="project.categories",
                    canonical_property_uri=CardURIs.CATEGORY,
                    value_type="relation",
                    relation_target="project_category",
                    multi=True,
                ),
                widget="tags",
                placeholder="Mehrere Werte mit Enter bestätigen",
                multi=True,
                visibility=MASK_PHASE_ENRICHMENT,
                required_rule=RequiredRule(
                    kind="never",
                    frontend_grails_required=False,
                    backend_grails_required=False,
                    source_detail="Digikunst Projekt, kategorie. In der Notiz im Backend als optional dokumentiert, im dokumentierten Create Formular kein Pflichtfeld.",
                ),
                vocabulary=ControlledVocabularyRef(
                    source_type="canonical",
                    key="project_category",
                    allow_free_text=True,
                ),
            ),
            MaskField(
                name="catchphrases",
                label="Schlagworte",
                semantic_slot=SemanticSlot(
                    slot_id="project.catchphrases",
                    canonical_property_uri=ProjectURIs.CATCHPHRASE,
                    multi=True,
                ),
                widget="tags",
                placeholder="Mehrere Werte mit Enter bestätigen",
                multi=True,
                visibility=MASK_PHASE_ENRICHMENT,
                required_rule=RequiredRule(
                    kind="never",
                    frontend_grails_required=False,
                    backend_grails_required=False,
                    source_detail="Digikunst Projekt, schlagworte. In der Notiz im Backend als optional dokumentiert, im dokumentierten Create Formular kein Pflichtfeld.",
                ),
            ),
        ],
    )

    return MaskSchema(
        schema_id="project.pilot",
        entity_type="project",
        label="Projekt",
        source="arkumu_project_pilot",
        sections=[overview, institution, classification],
        create_supported=True,
        create_redirect_url_name="metadata:edit_project",
    )


def build_event_mask_schema() -> MaskSchema:
    """Build the event mask from current Arkumu slots and Digikunst evidence."""

    overview = MaskSection(
        name="overview",
        label="Ereignisübersicht",
        description="Grundlegende Angaben zum Ereignis.",
        fields=[
            MaskField(
                name="event_type",
                label="Ereignistyp",
                semantic_slot=SemanticSlot(
                    slot_id="event.type",
                    canonical_property_uri=ProjectURIs.EVENT_TYPE,
                    value_type="relation",
                    relation_target="event_type",
                ),
                widget="select",
                placeholder="Ereignistyp auswählen",
                visibility=MASK_PHASE_CREATE,
                required_rule=RequiredRule(
                    kind="always",
                    frontend_grails_required=True,
                    backend_grails_required=True,
                ),
                vocabulary=ControlledVocabularyRef(
                    source_type="canonical",
                    key="event_types",
                    allow_free_text=True,
                ),
            ),
            MaskField(
                name="name",
                label="Ereignisname",
                semantic_slot=SemanticSlot(
                    slot_id="event.name",
                    canonical_property_uri=ProjectURIs.EVENT_NAME,
                ),
                placeholder="Bezeichnung des Ereignisses",
                visibility=MASK_PHASE_CREATE,
                required_rule=RequiredRule(
                    kind="never",
                    frontend_grails_required=False,
                    backend_grails_required=False,
                    source_detail="Digikunst Ereignis, name. Im Create Formular sichtbar, aber nicht als Pflichtfeld markiert. Im Backend ist das Feld nullable.",
                ),
            ),
        ],
    )

    dates = MaskSection(
        name="dates",
        label="Zeitangaben",
        description="Datierung des Ereignisses.",
        fields=[
            MaskField(
                name="start",
                label="Beginn",
                semantic_slot=SemanticSlot(
                    slot_id="event.start",
                    canonical_property_uri=CardURIs.EVENT_START,
                ),
                widget="date",
                placeholder="TT.MM.JJJJ oder JJJJ-MM-TT",
                visibility=MASK_PHASE_ENRICHMENT,
                required_rule=RequiredRule(
                    kind="never",
                    frontend_grails_required=False,
                    backend_grails_required=False,
                    source_detail="Digikunst Ereignis, beginn. Im Formular nicht als Pflichtfeld dokumentiert. Im Backend nur validiert, wenn ein Wert vorhanden ist; dann muss das Datumsformat stimmen.",
                ),
            ),
            MaskField(
                name="end",
                label="Ende",
                semantic_slot=SemanticSlot(
                    slot_id="event.end",
                    canonical_property_uri=CardURIs.EVENT_END,
                ),
                widget="date",
                placeholder="TT.MM.JJJJ oder JJJJ-MM-TT",
                visibility=MASK_PHASE_ENRICHMENT,
                required_rule=RequiredRule(
                    kind="never",
                    frontend_grails_required=False,
                    backend_grails_required=False,
                    source_detail="Digikunst Ereignis, ende. Im Formular nicht als Pflichtfeld dokumentiert. Im Backend nur validiert, wenn ein Wert vorhanden ist; dann muss das Datumsformat stimmen.",
                ),
            ),
        ],
    )

    return MaskSchema(
        schema_id="event.digikunst",
        entity_type="event",
        label="Ereignis",
        source="digikunst_grails_mask",
        sections=[overview, dates],
        create_supported=True,
        create_redirect_url_name="metadata:edit_ereignis",
    )


def build_actor_mask_schema() -> MaskSchema:
    """Build the actor mask from Digikunst create intent and Arkumu slots."""

    overview = MaskSection(
        name="overview",
        label="AkteurIn",
        description="Minimaler Erfassungseinstieg mit den Namensfeldern.",
        fields=[
            MaskField(
                name="name_de",
                label="Name (DE)",
                semantic_slot=SemanticSlot(
                    slot_id="actor.name_de",
                    canonical_property_uri=CardURIs.ACTOR_GERMAN_NAME,
                ),
                placeholder="Deutscher Name",
                visibility=MASK_PHASE_CREATE,
                required_rule=RequiredRule(
                    kind="conditional",
                    expression="name_de || name_en",
                    source_detail="Digikunst Akteur, create. Mindestens eines von name_de oder name_en muss vorhanden sein. Die Regel wird ueber Validatoren ausgedrueckt, nicht ueber zwei separat markierte Pflichtfelder.",
                ),
            ),
            MaskField(
                name="name_en",
                label="Name (EN)",
                semantic_slot=SemanticSlot(
                    slot_id="actor.name_en",
                    canonical_property_uri=ACTOR_ENGLISH_NAME_URI,
                ),
                placeholder="Englischer Name",
                visibility=MASK_PHASE_CREATE,
                required_rule=RequiredRule(
                    kind="conditional",
                    expression="name_de || name_en",
                    source_detail="Digikunst Akteur, create. Mindestens eines von name_de oder name_en muss vorhanden sein. Die Regel wird ueber Validatoren ausgedrueckt, nicht ueber zwei separat markierte Pflichtfelder.",
                ),
            ),
        ],
    )

    identifiers = MaskSection(
        name="identifiers",
        label="Normdaten",
        description="Externe Identifikatoren und kontrollierte Angaben fuer die spaetere Erweiterung.",
        fields=[
            MaskField(
                name="gender",
                label="Geschlecht",
                semantic_slot=SemanticSlot(
                    slot_id="actor.gender",
                    canonical_property_uri="http://arkumu.org/data/properties/geschlecht",
                ),
                visibility=MASK_PHASE_ENRICHMENT,
                required_rule=RequiredRule(
                    kind="never",
                    frontend_grails_required=False,
                    backend_grails_required=False,
                ),
            ),
            MaskField(
                name="wikidata_id",
                label="Wikidata-ID",
                semantic_slot=SemanticSlot(
                    slot_id="actor.wikidata_id",
                    canonical_property_uri=WIKIDATA_ID_URI,
                ),
                placeholder="Q12345",
                visibility=MASK_PHASE_ENRICHMENT,
            ),
            MaskField(
                name="gnd_id",
                label="GND-Nummer",
                semantic_slot=SemanticSlot(
                    slot_id="actor.gnd_id",
                    canonical_property_uri=GND_ID_URI,
                ),
                visibility=MASK_PHASE_ENRICHMENT,
            ),
            MaskField(
                name="viaf_id",
                label="VIAF-ID",
                semantic_slot=SemanticSlot(
                    slot_id="actor.viaf_id",
                    canonical_property_uri=VIAF_ID_URI,
                ),
                visibility=MASK_PHASE_ENRICHMENT,
            ),
        ],
    )

    return MaskSchema(
        schema_id="actor.digikunst",
        entity_type="actor",
        label="AkteurIn",
        source="digikunst_grails_mask",
        sections=[overview, identifiers],
        create_supported=True,
        create_redirect_url_name="metadata:edit_akteur",
    )


def build_place_mask_schema() -> MaskSchema:
    """Build the place mask from Digikunst create intent and current Arkumu gaps."""

    overview = MaskSection(
        name="overview",
        label="Ort",
        description="Digikunst zeigt bereits beim Anlegen Namen, Kategorie und Koordinaten.",
        fields=[
            MaskField(
                name="name_de",
                label="Name (DE)",
                semantic_slot=SemanticSlot(
                    slot_id="place.name_de",
                    canonical_property_uri=PLACE_NAME_URI,
                ),
                placeholder="Deutscher Ortsname",
                visibility=MASK_PHASE_CREATE,
                required_rule=RequiredRule(
                    kind="conditional",
                    expression="name_de unless wikidata_import",
                    source_detail="Digikunst Ort, create. name_de ist erforderlich, ausser der Datensatz kommt aus dem Wikidata-Import.",
                ),
            ),
            MaskField(
                name="name_en",
                label="Name (EN)",
                semantic_slot=SemanticSlot(
                    slot_id="place.name_en",
                    canonical_property_uri=None,
                    value_type="structured",
                ),
                placeholder="Englischer Ortsname",
                visibility=MASK_PHASE_ENRICHMENT,
                required_rule=RequiredRule(
                    kind="conditional",
                    expression="name_en unless wikidata_import",
                    source_detail="Digikunst Ort, create. name_en ist erforderlich, ausser der Datensatz kommt aus dem Wikidata-Import. Im aktuellen Arkumu Canonical Model ist dafuer noch kein stabiler eigener Slot verdrahtet.",
                ),
            ),
        ],
    )

    coordinates = MaskSection(
        name="coordinates",
        label="Koordinaten",
        description="Pflichtfelder im Digikunst Ort-Formular.",
        fields=[
            MaskField(
                name="latitude",
                label="Latitude",
                semantic_slot=SemanticSlot(
                    slot_id="place.latitude",
                    canonical_property_uri=None,
                    value_type="structured",
                ),
                visibility=MASK_PHASE_CREATE,
                required_rule=RequiredRule(
                    kind="always",
                    frontend_grails_required=True,
                    backend_grails_required=True,
                    source_detail="Digikunst Ort, create. latitude ist Pflichtfeld. Im aktuellen Arkumu Canonical Model ist noch kein stabiler kanonischer Koordinaten-Praedikat-Slot verdrahtet.",
                ),
            ),
            MaskField(
                name="longitude",
                label="Longitude",
                semantic_slot=SemanticSlot(
                    slot_id="place.longitude",
                    canonical_property_uri=None,
                    value_type="structured",
                ),
                visibility=MASK_PHASE_CREATE,
                required_rule=RequiredRule(
                    kind="always",
                    frontend_grails_required=True,
                    backend_grails_required=True,
                    source_detail="Digikunst Ort, create. longitude ist Pflichtfeld. Im aktuellen Arkumu Canonical Model ist noch kein stabiler kanonischer Koordinaten-Praedikat-Slot verdrahtet.",
                ),
            ),
        ],
    )

    identifiers = MaskSection(
        name="identifiers",
        label="Normdaten",
        description="Import- und Normdatenfelder fuer spaetere Erweiterung.",
        fields=[
            MaskField(
                name="wikidata_id",
                label="Wikidata-ID",
                semantic_slot=SemanticSlot(
                    slot_id="place.wikidata_id",
                    canonical_property_uri=WIKIDATA_ID_URI,
                ),
                visibility=MASK_PHASE_ENRICHMENT,
            ),
            MaskField(
                name="gnd_id",
                label="GND-Nummer",
                semantic_slot=SemanticSlot(
                    slot_id="place.gnd_id",
                    canonical_property_uri=GND_ID_URI,
                ),
                visibility=MASK_PHASE_ENRICHMENT,
            ),
            MaskField(
                name="viaf_id",
                label="VIAF-ID",
                semantic_slot=SemanticSlot(
                    slot_id="place.viaf_id",
                    canonical_property_uri=VIAF_ID_URI,
                ),
                visibility=MASK_PHASE_ENRICHMENT,
            ),
        ],
    )

    return MaskSchema(
        schema_id="place.digikunst",
        entity_type="place",
        label="Ort",
        source="digikunst_grails_mask",
        sections=[overview, coordinates, identifiers],
    )


def build_collection_mask_schema() -> MaskSchema:
    """Build the collection mask from Digikunst create requirements."""

    overview = MaskSection(
        name="overview",
        label="Sammlung",
        description="Der Digikunst Einstieg ist bereits relativ vollstaendig.",
        fields=[
            MaskField(
                name="name_de",
                label="Bezeichnung (DE)",
                semantic_slot=SemanticSlot(
                    slot_id="collection.name_de",
                    canonical_property_uri=COLLECTION_NAME_DE_URI,
                ),
                visibility=MASK_PHASE_CREATE,
                required_rule=RequiredRule(
                    kind="always",
                    frontend_grails_required=True,
                    backend_grails_required=True,
                ),
            ),
            MaskField(
                name="name_en",
                label="Bezeichnung (EN)",
                semantic_slot=SemanticSlot(
                    slot_id="collection.name_en",
                    canonical_property_uri=COLLECTION_NAME_EN_URI,
                ),
                visibility=MASK_PHASE_CREATE,
                required_rule=RequiredRule(
                    kind="always",
                    frontend_grails_required=True,
                    backend_grails_required=True,
                ),
            ),
            MaskField(
                name="collection_type",
                label="Sammlungsart",
                semantic_slot=SemanticSlot(
                    slot_id="collection.type",
                    canonical_property_uri=COLLECTION_KIND_URI,
                ),
                visibility=MASK_PHASE_CREATE,
                required_rule=RequiredRule(
                    kind="always",
                    frontend_grails_required=True,
                    backend_grails_required=True,
                ),
            ),
            MaskField(
                name="description_de",
                label="Beschreibung (DE)",
                semantic_slot=SemanticSlot(
                    slot_id="collection.description_de",
                    canonical_property_uri=COLLECTION_DESCRIPTION_DE_URI,
                ),
                widget="textarea",
                visibility=MASK_PHASE_CREATE,
                required_rule=RequiredRule(
                    kind="always",
                    frontend_grails_required=True,
                    backend_grails_required=True,
                ),
            ),
            MaskField(
                name="description_en",
                label="Beschreibung (EN)",
                semantic_slot=SemanticSlot(
                    slot_id="collection.description_en",
                    canonical_property_uri=COLLECTION_DESCRIPTION_EN_URI,
                ),
                widget="textarea",
                visibility=MASK_PHASE_CREATE,
                required_rule=RequiredRule(
                    kind="always",
                    frontend_grails_required=True,
                    backend_grails_required=True,
                ),
            ),
        ],
    )

    return MaskSchema(
        schema_id="collection.digikunst",
        entity_type="collection",
        label="Sammlung",
        source="digikunst_grails_mask",
        sections=[overview],
    )


def build_information_carrier_mask_schema() -> MaskSchema:
    """Build the information carrier mask."""

    overview = MaskSection(
        name="overview",
        label="Informationsträger",
        description="Im ersten Digikunst Schritt wird nur der Typ gesetzt, danach geht es direkt in die Erweiterung.",
        fields=[
            MaskField(
                name="carrier_type",
                label="Informationsträgertyp",
                semantic_slot=SemanticSlot(
                    slot_id="information_carrier.type",
                    canonical_property_uri=INFORMATION_CARRIER_KIND_URI,
                    value_type="relation",
                    relation_target="information_carrier_type",
                ),
                widget="select",
                visibility=MASK_PHASE_CREATE,
                required_rule=RequiredRule(
                    kind="always",
                    frontend_grails_required=True,
                    backend_grails_required=True,
                ),
                vocabulary=ControlledVocabularyRef(
                    source_type="canonical",
                    key="information_carrier_type",
                    allow_free_text=False,
                ),
            ),
        ],
    )

    enrichment = MaskSection(
        name="enrichment",
        label="Erweiterung",
        description="Die restlichen Informationsträger-Felder erscheinen erst nach dem ersten Speichern.",
        fields=[
            MaskField(
                name="name_de",
                label="Produktbezeichnung (DE)",
                semantic_slot=SemanticSlot(
                    slot_id="information_carrier.name_de",
                    canonical_property_uri=INFORMATION_CARRIER_NAME_DE_URI,
                ),
                visibility=MASK_PHASE_ENRICHMENT,
            ),
            MaskField(
                name="name_en",
                label="Produktbezeichnung (EN)",
                semantic_slot=SemanticSlot(
                    slot_id="information_carrier.name_en",
                    canonical_property_uri=INFORMATION_CARRIER_NAME_EN_URI,
                ),
                visibility=MASK_PHASE_ENRICHMENT,
            ),
            MaskField(
                name="label",
                label="Label / Handelsmarke",
                semantic_slot=SemanticSlot(
                    slot_id="information_carrier.label",
                    canonical_property_uri=INFORMATION_CARRIER_LABEL_URI,
                ),
                visibility=MASK_PHASE_ENRICHMENT,
            ),
            MaskField(
                name="description_de",
                label="Beschreibung (DE)",
                semantic_slot=SemanticSlot(
                    slot_id="information_carrier.description_de",
                    canonical_property_uri=INFORMATION_CARRIER_DESCRIPTION_DE_URI,
                ),
                widget="textarea",
                visibility=MASK_PHASE_ENRICHMENT,
            ),
            MaskField(
                name="description_en",
                label="Beschreibung (EN)",
                semantic_slot=SemanticSlot(
                    slot_id="information_carrier.description_en",
                    canonical_property_uri=INFORMATION_CARRIER_DESCRIPTION_EN_URI,
                ),
                widget="textarea",
                visibility=MASK_PHASE_ENRICHMENT,
            ),
            MaskField(
                name="material_keywords",
                label="Materialschlagwort",
                semantic_slot=SemanticSlot(
                    slot_id="information_carrier.material_keyword",
                    canonical_property_uri=INFORMATION_CARRIER_MATERIAL_URI,
                    multi=True,
                ),
                widget="tags",
                multi=True,
                visibility=MASK_PHASE_ENRICHMENT,
                required_rule=RequiredRule(
                    kind="never",
                    frontend_grails_required=False,
                    backend_grails_required=True,
                    source_detail="Digikunst Informationstraeger. materialschlagwort ist im Backend als erforderlich dokumentiert, aber nicht im ersten Create-Schritt sichtbar.",
                ),
            ),
        ],
    )

    return MaskSchema(
        schema_id="information_carrier.digikunst",
        entity_type="information_carrier",
        label="Informationsträger",
        source="digikunst_grails_mask",
        sections=[overview, enrichment],
    )


def build_keyword_mask_schema() -> MaskSchema:
    """Build the keyword mask, including Arkumu gaps for non-canonical fields."""

    overview = MaskSection(
        name="overview",
        label="Schlagwort",
        description="Das Digikunst Create-Formular zeigt Label, Beschreibungen, Synonyme und Normdaten.",
        fields=[
            MaskField(
                name="label_de",
                label="Label (DE)",
                semantic_slot=SemanticSlot(
                    slot_id="keyword.label_de",
                    canonical_property_uri=KEYWORD_LABEL_DE_URI,
                ),
                visibility=MASK_PHASE_CREATE,
                required_rule=RequiredRule(
                    kind="conditional",
                    expression="label_de || label_en",
                    source_detail="Digikunst Schlagwort. Mindestens eines von label_de oder label_en muss gesetzt sein.",
                ),
            ),
            MaskField(
                name="label_en",
                label="Label (EN)",
                semantic_slot=SemanticSlot(
                    slot_id="keyword.label_en",
                    canonical_property_uri=None,
                    value_type="structured",
                ),
                visibility=MASK_PHASE_CREATE,
                required_rule=RequiredRule(
                    kind="conditional",
                    expression="label_de || label_en",
                    source_detail="Digikunst Schlagwort. Mindestens eines von label_de oder label_en muss gesetzt sein. Im aktuellen Arkumu Canonical Model ist dafuer noch kein eigener stabiler Slot verdrahtet.",
                ),
            ),
            MaskField(
                name="description_de",
                label="Beschreibung (DE)",
                semantic_slot=SemanticSlot(
                    slot_id="keyword.description_de",
                    canonical_property_uri=None,
                    value_type="structured",
                ),
                widget="textarea",
                visibility=MASK_PHASE_CREATE,
                required_rule=RequiredRule(
                    kind="always",
                    frontend_grails_required=True,
                    backend_grails_required=True,
                    source_detail="Digikunst Schlagwort. description_de ist Pflichtfeld, aber im aktuellen Arkumu Canonical Model noch nicht als stabiler eigener Slot verdrahtet.",
                ),
            ),
            MaskField(
                name="description_en",
                label="Beschreibung (EN)",
                semantic_slot=SemanticSlot(
                    slot_id="keyword.description_en",
                    canonical_property_uri=None,
                    value_type="structured",
                ),
                widget="textarea",
                visibility=MASK_PHASE_CREATE,
                required_rule=RequiredRule(
                    kind="always",
                    frontend_grails_required=True,
                    backend_grails_required=True,
                    source_detail="Digikunst Schlagwort. description_en ist Pflichtfeld, aber im aktuellen Arkumu Canonical Model noch nicht als stabiler eigener Slot verdrahtet.",
                ),
            ),
            MaskField(
                name="wikidata_id",
                label="Wikidata-ID",
                semantic_slot=SemanticSlot(
                    slot_id="keyword.wikidata_id",
                    canonical_property_uri=WIKIDATA_ID_URI,
                ),
                visibility=MASK_PHASE_ENRICHMENT,
            ),
        ],
    )

    return MaskSchema(
        schema_id="keyword.digikunst",
        entity_type="keyword",
        label="Schlagwort",
        source="digikunst_grails_mask",
        sections=[overview],
    )


def build_digital_object_mask_schema() -> MaskSchema:
    """Build the digital object mask from the upload-centric Digikunst create flow."""

    upload = MaskSection(
        name="upload",
        label="Upload",
        description="Der erste Schritt ist im Digikunst-Formular uploadzentriert.",
        fields=[
            MaskField(
                name="file",
                label="Datei",
                semantic_slot=SemanticSlot(
                    slot_id="digital_object.file",
                    canonical_property_uri=CardURIs.DIGITAL_OBJECT_PATH,
                ),
                widget="file",
                visibility=MASK_PHASE_CREATE,
                required_rule=RequiredRule(
                    kind="always",
                    frontend_grails_required=True,
                    backend_grails_required=True,
                    source_detail="Digikunst DigitalesObjekt. Die erste Erfassung verlangt einen Upload und nicht nur einen Dateipfad-Textwert.",
                ),
            ),
            MaskField(
                name="media_type",
                label="Medientyp",
                semantic_slot=SemanticSlot(
                    slot_id="digital_object.media_type",
                    canonical_property_uri=DIGITAL_OBJECT_MEDIA_TYPE_URI,
                ),
                visibility=MASK_PHASE_CREATE,
                required_rule=RequiredRule(
                    kind="always",
                    frontend_grails_required=True,
                    backend_grails_required=True,
                ),
            ),
            MaskField(
                name="retention_type",
                label="Erhaltungstyp",
                semantic_slot=SemanticSlot(
                    slot_id="digital_object.retention_type",
                    canonical_property_uri=DIGITAL_OBJECT_RETENTION_TYPE_URI,
                ),
                visibility=MASK_PHASE_CREATE,
                required_rule=RequiredRule(
                    kind="always",
                    frontend_grails_required=True,
                    backend_grails_required=True,
                ),
            ),
            MaskField(
                name="origin_type",
                label="Entstehungstyp",
                semantic_slot=SemanticSlot(
                    slot_id="digital_object.origin_type",
                    canonical_property_uri=DIGITAL_OBJECT_ORIGIN_TYPE_URI,
                ),
                visibility=MASK_PHASE_CREATE,
                required_rule=RequiredRule(
                    kind="never",
                    frontend_grails_required=False,
                    backend_grails_required=False,
                ),
            ),
            MaskField(
                name="license_status",
                label="Lizenzstatus",
                semantic_slot=SemanticSlot(
                    slot_id="digital_object.license_status",
                    canonical_property_uri=DIGITAL_OBJECT_LICENSE_URI,
                ),
                visibility=MASK_PHASE_CREATE,
                required_rule=RequiredRule(
                    kind="always",
                    frontend_grails_required=True,
                    backend_grails_required=True,
                ),
            ),
        ],
    )

    return MaskSchema(
        schema_id="digital_object.digikunst",
        entity_type="digital_object",
        label="Digitales Objekt",
        source="digikunst_grails_mask",
        sections=[upload],
    )
