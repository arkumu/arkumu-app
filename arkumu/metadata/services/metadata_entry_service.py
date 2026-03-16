"""Metadata entry services backed by project dataclasses."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from arkumu.common.uri_utils import DEFAULT_INSTITUTION_BASE_URI, mint_uri, slugify_uri_part
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.services.canonical_graph_service import RDF_TYPE_URI
from arkumu.metadata.services.mask_schema import MaskSchema, build_project_mask_schema
from arkumu.projects import (
    ProjectCatchphrase,
    ProjectCategory,
    ProjectInstitution,
    ProjectRecord,
    ProjectType,
)
from arkumu.catalog.services.project_views import CardURIs, ProjectURIs
from arkumu.users.models import Organization


# ---------------------------------------------------------------------------
# Form descriptors
# ---------------------------------------------------------------------------


@dataclass
class FormField:
    name: str
    path: str
    label: str
    widget: str = "text"  # text, textarea, tags
    placeholder: str = ""
    help_text: Optional[str] = None
    required: bool = False
    multi: bool = False


@dataclass
class FormSection:
    name: str
    label: str
    description: Optional[str]
    fields: List[FormField]


@dataclass
class SectionManifest:
    name: str
    label: str
    description: Optional[str]
    fields: List[FormField]


@dataclass
class EntryDisplayRow:
    label: str
    value: str


@dataclass
class EntryResult:
    success: bool
    resource: Optional[Resource]
    field_errors: Dict[str, str]
    display_rows: List[EntryDisplayRow]
    record: Optional[ProjectRecord] = None


# ---------------------------------------------------------------------------
# Dataclass-backed form service
# ---------------------------------------------------------------------------


class DataclassFormService:
    """Constructs form sections based on project dataclasses."""

    MASK_SCHEMA: MaskSchema = build_project_mask_schema()
    FIELD_PATHS: Dict[str, str] = {
        "title": "title",
        "subtitle": "subtitle",
        "description": "description",
        "year_range": "year_range",
        "institution__label": "institution.label",
        "institution__code": "institution.code",
        "project_type": "project_type.label",
        "categories": "categories",
        "catchphrases": "catchphrases",
    }

    @classmethod
    def _build_form_sections(cls) -> List[FormSection]:
        sections: List[FormSection] = []
        for mask_section in cls.MASK_SCHEMA.sections:
            fields: List[FormField] = []
            for mask_field in mask_section.fields:
                path = cls.FIELD_PATHS.get(mask_field.name, mask_field.name)
                fields.append(
                    FormField(
                        name=mask_field.name,
                        path=path,
                        label=mask_field.label,
                        widget=mask_field.widget,
                        placeholder=mask_field.placeholder,
                        help_text=mask_field.help_text,
                        required=mask_field.required_rule.is_required,
                        multi=mask_field.multi,
                    )
                )
            sections.append(
                FormSection(
                    name=mask_section.name,
                    label=mask_section.label,
                    description=mask_section.description,
                    fields=fields,
                )
            )
        return sections

    def get_mask_schema(self) -> MaskSchema:
        return self.MASK_SCHEMA

    def get_form_sections(self) -> List[FormSection]:
        return self._build_form_sections()

    def list_sections(self) -> List[Dict[str, str]]:
        return [
            {
                "name": section.name,
                "label": section.label,
                "description": section.description,
                "property_count": len(section.fields),
            }
            for section in self.get_form_sections()
        ]

    def get_section(self, section_name: str) -> SectionManifest:
        section = next((s for s in self.get_form_sections() if s.name == section_name), None)
        if not section:
            raise ValueError(f"Unknown section '{section_name}'")
        return SectionManifest(
            name=section.name,
            label=section.label,
            description=section.description,
            fields=section.fields,
        )

    def to_initial_data(self, record: ProjectRecord) -> Dict[str, str]:
        data: Dict[str, str] = {}
        for section in self.get_form_sections():
            for field in section.fields:
                value = self._extract_path(record, field.path)
                if not value:
                    continue
                if field.multi and isinstance(value, list):
                    data[field.name] = "\n".join(
                        [item for item in value if isinstance(item, str)]
                    )
                elif isinstance(value, list):
                    data[field.name] = "\n".join(str(item) for item in value)
                else:
                    data[field.name] = str(value)
        return data

    def build_record(self, payload: Dict[str, str]) -> ProjectRecord:
        title = self._clean(payload.get("title"))
        subtitle = self._clean(payload.get("subtitle"))
        description = self._clean(payload.get("description"))
        year_range = self._clean(payload.get("year_range"))
        project_type_label = self._clean(payload.get("project_type"))

        institution_label = self._clean(payload.get("institution__label"))
        institution_code = self._clean(payload.get("institution__code"))

        categories = self._split_multi(payload.get("categories"))
        catchphrases = self._split_multi(payload.get("catchphrases"))

        institution = (
            ProjectInstitution(label=institution_label, code=institution_code)
            if institution_label or institution_code
            else None
        )

        project_type = (
            ProjectType(label=project_type_label)
            if project_type_label
            else None
        )

        category_objs = [ProjectCategory(label=label) for label in categories]
        catchphrase_objs = [ProjectCatchphrase(label=label) for label in catchphrases]

        return ProjectRecord(
            subject_id=str(uuid.uuid4()),
            uri="",
            title=title,
            subtitle=subtitle,
            description=description,
            institution=institution,
            categories=category_objs,
            catchphrases=catchphrase_objs,
            project_type=project_type,
            year_range=year_range,
        )

    def _extract_path(self, record: ProjectRecord, path: str):
        value = record
        for segment in path.split('.'):
            if value is None:
                return None
            if isinstance(value, list):
                return value
            value = getattr(value, segment, None)
        return value

    def _clean(self, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None

    def _split_multi(self, value: Optional[str]) -> List[str]:
        if not value:
            return []
        candidates = [item.strip() for item in value.replace('\r', '').split('\n')]
        result: List[str] = []
        for candidate in candidates:
            if not candidate:
                continue
            if ',' in candidate:
                result.extend(
                    [piece.strip() for piece in candidate.split(',') if piece.strip()]
                )
            else:
                result.append(candidate)
        # Deduplicate while preserving order
        seen = set()
        unique: List[str] = []
        for item in result:
            if item.lower() in seen:
                continue
            seen.add(item.lower())
            unique.append(item)
        return unique


# ---------------------------------------------------------------------------
# Dataclass to triple persistence
# ---------------------------------------------------------------------------


class DataclassToTripleMapper:
    """Persists ProjectRecord dataclasses as RDF resources/triples."""

    LITERAL_PREDICATES = {
        "title": CardURIs.TITLE,
        "subtitle": CardURIs.SUBTITLE,
        "description": ProjectURIs.DESCRIPTION,
    }

    CATCHPHRASE_PREDICATE = ProjectURIs.CATCHPHRASE
    CATEGORY_PREDICATE = CardURIs.CATEGORY
    INSTITUTION_PREDICATE = CardURIs.INSTITUTION
    PROJECT_TYPE_PREDICATE = ProjectURIs.PROJECT_TYPE_FIELD

    def __init__(self, base_uri: str) -> None:
        self.base_uri = base_uri.rstrip('/') + '/'

    def persist(self, *, record: ProjectRecord, organization: Organization) -> Resource:
        timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
        slug_base = record.title or f"projekt-{timestamp}"
        project_slug = slugify_uri_part(slug_base) or f"projekt-{timestamp}"
        project_uri = mint_uri(self.base_uri, organization.code, "projects", project_slug)

        project_resource = self._ensure_resource(
            uri=project_uri,
            resource_type=ResourceType.ENTITY,
            name=record.title,
            organization=organization,
            # canonical_uri=CardURIs.PROJECT_TYPE,
        )

        self._ensure_type_triple(project_resource, CardURIs.PROJECT_TYPE, organization)

        self._persist_literals(project_resource, record, organization)
        self._persist_institution(project_resource, record, organization)
        self._persist_categories(project_resource, record, organization)
        self._persist_catchphrases(project_resource, record, organization)
        self._persist_project_type(project_resource, record, organization)

        return project_resource

    def _ensure_resource(
        self,
        *,
        uri: str,
        resource_type: str,
        name: Optional[str],
        organization: Organization,
        canonical_uri: Optional[str] = None,
    ) -> Resource:
        defaults = {
            "resource_type": resource_type,
            "organization": organization,
            "name": name,
            "canonical_uri": canonical_uri,
        }
        resource, _ = Resource.objects.get_or_create(uri=uri, defaults=defaults)
        updated_fields = []
        if resource.organization_id is None and organization:
            resource.organization = organization
            updated_fields.append("organization")
        if name and resource.name != name:
            resource.name = name
            updated_fields.append("name")
        if canonical_uri and resource.canonical_uri != canonical_uri:
            resource.canonical_uri = canonical_uri
            updated_fields.append("canonical_uri")
        if updated_fields:
            resource.save(update_fields=updated_fields)
        return resource

    def _ensure_type_triple(self, subject: Resource, class_uri: str, organization: Organization) -> None:
        predicate = self._ensure_property(RDF_TYPE_URI, organization)
        class_resource = self._ensure_resource(
            uri=class_uri,
            resource_type=ResourceType.CLASS,
            name=class_uri.split('/')[-1],
            organization=organization,
            canonical_uri=class_uri,
        )
        Triple.objects.get_or_create(
            subject=subject,
            predicate=predicate,
            object=class_resource,
            defaults={"source": organization, "is_derived": False},
        )

    def _persist_literals(self, project: Resource, record: ProjectRecord, organization: Organization) -> None:
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
                subject=project,
                predicate=predicate,
                object=literal,
                defaults={"source": organization, "is_derived": False},
            )

    def _persist_institution(self, project: Resource, record: ProjectRecord, organization: Organization) -> None:
        if not record.institution or not record.institution.label:
            return
        if record.institution.uri:
            institution_resource = self._ensure_resource(
                uri=record.institution.uri,
                resource_type=ResourceType.ENTITY,
                name=record.institution.label,
                organization=organization,
            )
        else:
            inst_slug = slugify_uri_part(record.institution.label)
            inst_uri = mint_uri(self.base_uri, organization.code, "institutions", inst_slug)
            institution_resource = self._ensure_resource(
                uri=inst_uri,
                resource_type=ResourceType.ENTITY,
                name=record.institution.label,
                organization=organization,
                canonical_uri=CardURIs.INSTITUTION_TYPE,
            )
        predicate = self._ensure_property(self.INSTITUTION_PREDICATE, organization)
        Triple.objects.get_or_create(
            subject=project,
            predicate=predicate,
            object=institution_resource,
            defaults={"source": organization, "is_derived": False},
        )

    def _persist_categories(self, project: Resource, record: ProjectRecord, organization: Organization) -> None:
        if not record.categories:
            return
        predicate = self._ensure_property(self.CATEGORY_PREDICATE, organization)
        for category in record.categories:
            if not category.label:
                continue
            cat_slug = slugify_uri_part(category.label)
            cat_uri = mint_uri(self.base_uri, organization.code, "categories", cat_slug)
            category_resource = self._ensure_resource(
                uri=cat_uri,
                resource_type=ResourceType.ENTITY,
                name=category.label,
                organization=organization,
                canonical_uri=CardURIs.CATEGORY_TYPE,
            )
            Triple.objects.get_or_create(
                subject=project,
                predicate=predicate,
                object=category_resource,
                defaults={"source": organization, "is_derived": False},
            )

    def _persist_catchphrases(self, project: Resource, record: ProjectRecord, organization: Organization) -> None:
        if not record.catchphrases:
            return
        predicate = self._ensure_property(self.CATCHPHRASE_PREDICATE, organization)
        for catchphrase in record.catchphrases:
            if not catchphrase.label:
                continue
            literal = Resource.objects.create(
                resource_type=ResourceType.LITERAL,
                value=catchphrase.label,
                organization=organization,
            )
            Triple.objects.get_or_create(
                subject=project,
                predicate=predicate,
                object=literal,
                defaults={"source": organization, "is_derived": False},
            )

    def _persist_project_type(self, project: Resource, record: ProjectRecord, organization: Organization) -> None:
        if not record.project_type or not record.project_type.label:
            return
        predicate = self._ensure_property(self.PROJECT_TYPE_PREDICATE, organization)
        if record.project_type.uri:
            target = self._ensure_resource(
                uri=record.project_type.uri,
                resource_type=ResourceType.ENTITY,
                name=record.project_type.label,
                organization=organization,
            )
        else:
            target = Resource.objects.create(
                resource_type=ResourceType.LITERAL,
                value=record.project_type.label,
                organization=organization,
            )
        Triple.objects.get_or_create(
            subject=project,
            predicate=predicate,
            object=target,
            defaults={"source": organization, "is_derived": False},
        )

    def _ensure_property(self, uri: str, organization: Organization) -> Resource:
        predicate, _ = Resource.objects.get_or_create(
            uri=uri,
            defaults={
                "resource_type": ResourceType.PROPERTY,
                "organization": organization,
                "canonical_uri": uri,
            },
        )
        if predicate.organization_id is None:
            predicate.organization = organization
            predicate.save(update_fields=["organization"])
        if predicate.canonical_uri != uri:
            predicate.canonical_uri = uri
            predicate.save(update_fields=["canonical_uri"])
        return predicate


# ---------------------------------------------------------------------------
# Public service entrypoint
# ---------------------------------------------------------------------------


class MetadataEntryService:
    """High-level API for metadata entry views."""

    BASE_URI_SETTING = "ARKUMU_DATA_BASE_URI"

    def __init__(self, organization_code: str) -> None:
        try:
            self.organization = Organization.objects.get(code=organization_code)
        except Organization.DoesNotExist as exc:
            raise ValueError(f"Unknown organization '{organization_code}'") from exc

        base_uri = getattr(settings, self.BASE_URI_SETTING, DEFAULT_INSTITUTION_BASE_URI)
        self.form_service = DataclassFormService()
        self.mapper = DataclassToTripleMapper(base_uri)

    def get_mask_schema(self) -> MaskSchema:
        return self.form_service.get_mask_schema()

    def list_sections(self) -> List[Dict[str, str]]:
        return self.form_service.list_sections()

    def get_section_manifest(self, section_name: str) -> SectionManifest:
        return self.form_service.get_section(section_name)

    def build_initial_data(self, section_name: str) -> Dict[str, str]:
        record = ProjectRecord(subject_id=str(uuid.uuid4()), uri="")
        section = self.get_section_manifest(section_name)
        data = self.form_service.to_initial_data(record)
        # Filter to section-specific fields
        return {field.name: data.get(field.name, "") for field in section.fields}

    def persist_entry(self, section_name: str, payload: Dict[str, str]) -> EntryResult:
        manifest = self.get_section_manifest(section_name)

        field_errors: Dict[str, str] = {}
        cleaned_payload: Dict[str, str] = {}
        for field in manifest.fields:
            raw_value = payload.get(field.name, "")
            if isinstance(raw_value, list):
                raw_value = raw_value[-1]
            raw_value = raw_value.strip() if isinstance(raw_value, str) else ""
            if field.required and not raw_value:
                field_errors[field.name] = "Pflichtfeld"
            cleaned_payload[field.name] = raw_value

        if field_errors:
            return EntryResult(False, None, field_errors, [])

        record = self.form_service.build_record(cleaned_payload)

        with transaction.atomic():
            resource = self.mapper.persist(record=record, organization=self.organization)

        display_rows = self._build_summary_rows(record)
        return EntryResult(True, resource, {}, display_rows, record)

    def _build_summary_rows(self, record: ProjectRecord) -> List[EntryDisplayRow]:
        rows: List[EntryDisplayRow] = []
        if record.title:
            rows.append(EntryDisplayRow("Titel", record.title))
        if record.institution and record.institution.label:
            rows.append(EntryDisplayRow("Institution", record.institution.label))
        if record.categories:
            rows.append(
                EntryDisplayRow(
                    "Kategorien",
                    ", ".join(cat.label for cat in record.categories if cat.label),
                )
            )
        if record.catchphrases:
            rows.append(
                EntryDisplayRow(
                    "Schlagworte",
                    ", ".join(cp.label for cp in record.catchphrases if cp.label),
                )
            )
        return rows
