"""Productive mask-driven create service."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from arkumu.catalog.services.project_views import CardURIs, ProjectURIs
from arkumu.common.uri_utils import DEFAULT_INSTITUTION_BASE_URI, mint_uri, slugify_uri_part
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.services.canonical_graph_service import RDF_TYPE_URI
from arkumu.metadata.services.mask_schema import (
    ACTOR_ENGLISH_NAME_URI,
    MASK_PHASE_CREATE,
    MaskField,
    MaskSchema,
    field_is_visible_in_phase,
    get_mask_schema,
)
from arkumu.metadata.services.metadata_entry_service import DataclassToTripleMapper
from arkumu.metadata.services.vocabulary_options_service import build_metadata_option_map
from arkumu.projects import ProjectInstitution, ProjectRecord, ProjectType
from arkumu.users.models import Organization


@dataclass(frozen=True)
class CreateFieldManifest:
    name: str
    label: str
    widget: str
    required: bool
    placeholder: str = ""
    help_text: Optional[str] = None
    options: Sequence[Tuple[str, str]] = ()


@dataclass(frozen=True)
class CreateSectionManifest:
    name: str
    label: str
    description: Optional[str]
    fields: Sequence[CreateFieldManifest]


@dataclass(frozen=True)
class CreateFormManifest:
    entity_type: str
    label: str
    phase: str
    sections: Sequence[CreateSectionManifest]

    @property
    def fields(self) -> List[CreateFieldManifest]:
        return [field for section in self.sections for field in section.fields]


@dataclass(frozen=True)
class CreateResult:
    success: bool
    resource: Optional[Resource]
    field_errors: Dict[str, str]


@dataclass(frozen=True)
class EventTypeValue:
    label: Optional[str]
    uri: Optional[str] = None


@dataclass(frozen=True)
class EventCreateRecord:
    name: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    event_type: Optional[EventTypeValue] = None


@dataclass(frozen=True)
class ActorCreateRecord:
    name_de: Optional[str] = None
    name_en: Optional[str] = None


class EventToTripleMapper(DataclassToTripleMapper):
    """Persist standalone event resources."""

    EVENT_TYPE_PREDICATE = ProjectURIs.EVENT_TYPE
    EVENT_NAME_PREDICATE = ProjectURIs.EVENT_NAME
    EVENT_START_PREDICATE = CardURIs.EVENT_START
    EVENT_END_PREDICATE = CardURIs.EVENT_END

    def persist_event(self, *, record: EventCreateRecord, organization: Organization) -> Resource:
        timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
        slug_base = record.name or (record.event_type.label if record.event_type else None) or f"ereignis-{timestamp}"
        event_slug = slugify_uri_part(slug_base) or f"ereignis-{timestamp}"
        event_uri = mint_uri(self.base_uri, organization.code, "events", event_slug)

        resource_name = record.name or (record.event_type.label if record.event_type else None) or f"Ereignis {timestamp}"
        event_resource = self._ensure_resource(
            uri=event_uri,
            resource_type=ResourceType.ENTITY,
            name=resource_name,
            organization=organization,
        )
        self._ensure_type_triple(event_resource, CardURIs.EVENT_TYPE, organization)

        if record.name:
            self._persist_literal(event_resource, self.EVENT_NAME_PREDICATE, record.name, organization)
        if record.start:
            self._persist_literal(event_resource, self.EVENT_START_PREDICATE, record.start, organization)
        if record.end:
            self._persist_literal(event_resource, self.EVENT_END_PREDICATE, record.end, organization)
        if record.event_type:
            self._persist_relation_or_literal(
                subject=event_resource,
                predicate_uri=self.EVENT_TYPE_PREDICATE,
                organization=organization,
                resource_uri=record.event_type.uri,
                label=record.event_type.label,
            )

        return event_resource

    def _persist_literal(self, subject: Resource, predicate_uri: str, value: str, organization: Organization) -> None:
        predicate = self._ensure_property(predicate_uri, organization)
        literal = Resource.objects.create(
            resource_type=ResourceType.LITERAL,
            value=value,
            organization=organization,
        )
        Triple.objects.get_or_create(
            subject=subject,
            predicate=predicate,
            object=literal,
            defaults={"source": organization, "is_derived": False},
        )

    def _persist_relation_or_literal(
        self,
        *,
        subject: Resource,
        predicate_uri: str,
        organization: Organization,
        resource_uri: Optional[str],
        label: Optional[str],
    ) -> None:
        predicate = self._ensure_property(predicate_uri, organization)
        if resource_uri:
            target, _ = Resource.objects.get_or_create(
                uri=resource_uri,
                defaults={
                    "resource_type": ResourceType.ENTITY,
                    "organization": organization,
                    "name": label,
                },
            )
        else:
            target = Resource.objects.create(
                resource_type=ResourceType.LITERAL,
                value=label or "",
                organization=organization,
            )
        Triple.objects.get_or_create(
            subject=subject,
            predicate=predicate,
            object=target,
            defaults={"source": organization, "is_derived": False},
        )


class ActorToTripleMapper(DataclassToTripleMapper):
    """Persist minimal actor resources."""

    LITERAL_PREDICATES = {
        "name_de": CardURIs.ACTOR_GERMAN_NAME,
        "name_en": ACTOR_ENGLISH_NAME_URI,
    }

    def persist_actor(self, *, record: ActorCreateRecord, organization: Organization) -> Resource:
        timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
        slug_base = record.name_de or record.name_en or f"akteur-{timestamp}"
        actor_slug = slugify_uri_part(slug_base) or f"akteur-{timestamp}"
        actor_uri = mint_uri(self.base_uri, organization.code, "actors", actor_slug)

        actor_resource = self._ensure_resource(
            uri=actor_uri,
            resource_type=ResourceType.ENTITY,
            name=record.name_de or record.name_en,
            organization=organization,
        )
        self._ensure_type_triple(actor_resource, CardURIs.ACTOR_TYPE, organization)

        for attr, predicate_uri in self.LITERAL_PREDICATES.items():
            value = getattr(record, attr)
            if not value:
                continue
            predicate = self._ensure_property(predicate_uri, organization)
            literal = Resource.objects.create(
                resource_type=ResourceType.LITERAL,
                value=value,
                organization=organization,
            )
            Triple.objects.get_or_create(
                subject=actor_resource,
                predicate=predicate,
                object=literal,
                defaults={"source": organization, "is_derived": False},
            )

        return actor_resource


class MaskCreateService:
    """Create objects from the create-phase mask."""

    BASE_URI_SETTING = "ARKUMU_DATA_BASE_URI"

    TYPE_URIS_BY_FIELD_NAME = {
        "institution__label": "http://arkumu.org/data/types/einliefernde-hochschule",
        "project_type": "http://arkumu.org/data/types/projektart",
        "event_type": "http://arkumu.org/data/types/ereignistyp",
    }

    def __init__(self, organization_code: str, entity_type: str) -> None:
        try:
            self.organization = Organization.objects.get(code=organization_code)
        except Organization.DoesNotExist as exc:
            raise ValueError(f"Unknown organization '{organization_code}'") from exc

        self.entity_type = entity_type.strip().lower()
        self.mask_schema = get_mask_schema(self.entity_type)
        base_uri = getattr(settings, self.BASE_URI_SETTING, DEFAULT_INSTITUTION_BASE_URI)
        self.project_mapper = DataclassToTripleMapper(base_uri)
        self.event_mapper = EventToTripleMapper(base_uri)
        self.actor_mapper = ActorToTripleMapper(base_uri)

    def get_form_manifest(self) -> CreateFormManifest:
        sections: List[CreateSectionManifest] = []
        for section in self.mask_schema.sections:
            fields: List[CreateFieldManifest] = []
            for field in section.fields:
                if not field_is_visible_in_phase(field, MASK_PHASE_CREATE):
                    continue
                options = self._resolve_options(field)
                widget = "select" if options else field.widget
                fields.append(
                    CreateFieldManifest(
                        name=field.name,
                        label=field.label,
                        widget=widget,
                        required=field.required_rule.is_required,
                        placeholder=field.placeholder,
                        help_text=field.help_text,
                        options=options,
                    )
                )
            if fields:
                sections.append(
                    CreateSectionManifest(
                        name=section.name,
                        label=section.label,
                        description=section.description,
                        fields=fields,
                    )
                )
        return CreateFormManifest(
            entity_type=self.entity_type,
            label=self.mask_schema.label,
            phase=MASK_PHASE_CREATE,
            sections=sections,
        )

    def build_initial_data(self) -> Dict[str, str]:
        return {field.name: "" for field in self.get_form_manifest().fields}

    def persist(self, payload: Dict[str, str]) -> CreateResult:
        manifest = self.get_form_manifest()
        field_errors: Dict[str, str] = {}
        cleaned_payload: Dict[str, str] = {}
        for field in manifest.fields:
            raw_value = str(payload.get(field.name, "") or "").strip()
            if field.required and not raw_value:
                field_errors[field.name] = "Pflichtfeld"
            cleaned_payload[field.name] = raw_value

        if self.entity_type == "actor":
            if not cleaned_payload.get("name_de") and not cleaned_payload.get("name_en"):
                field_errors["name_de"] = "Mindestens einer der beiden Namen ist erforderlich."
                field_errors["name_en"] = "Mindestens einer der beiden Namen ist erforderlich."

        if field_errors:
            return CreateResult(False, None, field_errors)

        with transaction.atomic():
            if self.entity_type == "project":
                resource = self._persist_project(cleaned_payload)
            elif self.entity_type == "event":
                resource = self._persist_event(cleaned_payload)
            elif self.entity_type == "actor":
                resource = self._persist_actor(cleaned_payload)
            else:
                raise ValueError(f"Unsupported create entity '{self.entity_type}'")

        return CreateResult(True, resource, {})

    def _persist_project(self, payload: Dict[str, str]) -> Resource:
        institution_value = self._resolve_option_value(payload.get("institution__label"))
        project_type_value = self._resolve_option_value(payload.get("project_type"))
        record = ProjectRecord(
            subject_id=str(uuid.uuid4()),
            uri="",
            title=self._clean(payload.get("title")),
            institution=(
                ProjectInstitution(label=institution_value["label"], uri=institution_value["uri"])
                if institution_value["label"] or institution_value["uri"]
                else None
            ),
            project_type=(
                ProjectType(label=project_type_value["label"], uri=project_type_value["uri"])
                if project_type_value["label"] or project_type_value["uri"]
                else None
            ),
        )
        return self.project_mapper.persist(record=record, organization=self.organization)

    def _persist_event(self, payload: Dict[str, str]) -> Resource:
        event_type_value = self._resolve_option_value(payload.get("event_type"))
        record = EventCreateRecord(
            name=self._clean(payload.get("name")),
            start=self._clean(payload.get("start")),
            end=self._clean(payload.get("end")),
            event_type=EventTypeValue(
                label=event_type_value["label"],
                uri=event_type_value["uri"],
            )
            if event_type_value["label"] or event_type_value["uri"]
            else None,
        )
        return self.event_mapper.persist_event(record=record, organization=self.organization)

    def _persist_actor(self, payload: Dict[str, str]) -> Resource:
        record = ActorCreateRecord(
            name_de=self._clean(payload.get("name_de")),
            name_en=self._clean(payload.get("name_en")),
        )
        return self.actor_mapper.persist_actor(record=record, organization=self.organization)

    def _resolve_options(self, field: MaskField) -> Sequence[Tuple[str, str]]:
        type_uri = self.TYPE_URIS_BY_FIELD_NAME.get(field.name)
        if not type_uri:
            return ()
        option_map = build_metadata_option_map({field.name: type_uri}, organization=self.organization)
        return option_map.get(field.name, [])

    def _resolve_option_value(self, raw_value: Optional[str]) -> Dict[str, Optional[str]]:
        cleaned = self._clean(raw_value)
        if not cleaned:
            return {"uri": None, "label": None}
        if cleaned.startswith("http://") or cleaned.startswith("https://"):
            resource = Resource.objects.filter(uri=cleaned).first()
            label = None
            if resource is not None:
                label = resource.name or resource.value
            if not label:
                label = cleaned.rsplit("/", 1)[-1]
            return {
                "uri": cleaned,
                "label": label,
            }
        return {"uri": None, "label": cleaned}

    @staticmethod
    def _clean(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None
