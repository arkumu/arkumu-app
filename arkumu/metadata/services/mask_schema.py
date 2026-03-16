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
    ]


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
                visibility=MASK_PHASE_ENRICHMENT,
                required_rule=RequiredRule(
                    kind="never",
                    frontend_grails_required=False,
                    backend_grails_required=False,
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
    )
