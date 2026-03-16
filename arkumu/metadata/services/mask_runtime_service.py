"""Runtime resolution for unified metadata masks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional

from arkumu.metadata.services.mask_schema import (
    MASK_PHASE_ALL,
    MappingBindingSource,
    MappingConfigBindingResolver,
    MaskBinding,
    MaskField,
    MaskSchema,
    MaskSection,
    field_is_visible_in_phase,
    get_mask_schema,
    load_mapping_sources_for_organization,
    normalize_mask_phase,
)


FIELD_STATE_MAPPED = "mapped"
FIELD_STATE_CANONICAL = "canonical"
FIELD_STATE_MAPPED_AND_CANONICAL = "mapped_and_canonical"
FIELD_STATE_UNAVAILABLE = "unavailable"
FIELD_STATE_READ_ONLY = "read_only"


@dataclass(frozen=True)
class FieldState:
    code: str
    label: str
    detail: str
    badge_class: str


@dataclass(frozen=True)
class ResolvedMaskField:
    field: MaskField
    bindings: List[MaskBinding]
    state: FieldState


@dataclass(frozen=True)
class ResolvedMaskSection:
    section: MaskSection
    fields: List[ResolvedMaskField]


@dataclass(frozen=True)
class ResolvedMaskSchema:
    schema: MaskSchema
    organization_code: Optional[str]
    phase: str
    sections: List[ResolvedMaskSection]
    mapping_sources: List[MappingBindingSource]

    @property
    def mapping_count(self) -> int:
        return len(self.mapping_sources)


class MaskRuntimeService:
    """Resolve one unified mask against institution-specific bindings."""

    def __init__(
        self,
        *,
        resolver: Optional[MappingConfigBindingResolver] = None,
    ) -> None:
        self.resolver = resolver or MappingConfigBindingResolver()

    def resolve(
        self,
        *,
        entity_type: str,
        organization_code: Optional[str],
        phase: Optional[str] = None,
        mapping_sources: Optional[Iterable[MappingBindingSource]] = None,
    ) -> ResolvedMaskSchema:
        normalized_phase = normalize_mask_phase(phase)
        schema = get_mask_schema(entity_type)
        sources = (
            list(mapping_sources)
            if mapping_sources is not None
            else load_mapping_sources_for_organization(organization_code or "")
        )

        sections: List[ResolvedMaskSection] = []
        for section in schema.sections:
            resolved_fields: List[ResolvedMaskField] = []
            for field in section.fields:
                if not field_is_visible_in_phase(field, normalized_phase):
                    continue
                bindings = self.resolver.resolve_field_bindings(
                    field=field,
                    organization_code=organization_code or "",
                    mapping_sources=sources,
                )
                resolved_fields.append(
                    ResolvedMaskField(
                        field=field,
                        bindings=bindings,
                        state=self._resolve_field_state(field=field, bindings=bindings),
                    )
                )
            if resolved_fields or normalized_phase == MASK_PHASE_ALL:
                sections.append(
                    ResolvedMaskSection(
                        section=section,
                        fields=resolved_fields,
                    )
                )

        return ResolvedMaskSchema(
            schema=schema,
            organization_code=organization_code,
            phase=normalized_phase,
            sections=[section for section in sections if section.fields],
            mapping_sources=sources,
        )

    def _resolve_field_state(
        self,
        *,
        field: MaskField,
        bindings: List[MaskBinding],
    ) -> FieldState:
        canonical_uri = field.semantic_slot.canonical_property_uri

        if bindings and canonical_uri:
            return FieldState(
                code=FIELD_STATE_MAPPED_AND_CANONICAL,
                label="Gemappt + canonical",
                detail="Dieses Feld hat institutionelle Bindings und einen canonical Slot.",
                badge_class="badge-success",
            )
        if bindings:
            return FieldState(
                code=FIELD_STATE_MAPPED,
                label="Gemappt",
                detail="Dieses Feld ist ueber institutionelle Mappings verfuegbar.",
                badge_class="badge-info",
            )
        if canonical_uri:
            return FieldState(
                code=FIELD_STATE_CANONICAL,
                label="Canonical",
                detail="Dieses Feld hat keinen Mapping-Treffer und faellt auf den canonical Slot zurueck.",
                badge_class="badge-primary",
            )
        return FieldState(
            code=FIELD_STATE_UNAVAILABLE,
            label="Noch nicht verfuegbar",
            detail="Dieses Feld hat derzeit weder einen canonical Slot noch einen Mapping-Treffer.",
            badge_class="badge-ghost",
        )
