"""Service layer for the unified mask workspace."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib.parse import urlencode

from django.urls import reverse

from arkumu.metadata.services.mask_value_loader_service import (
    LoadedMaskFieldValue,
    MaskValueLoaderService,
)
from arkumu.metadata.services.unified_mask_entity_listing_service import (
    UnifiedMaskEntityListItem,
    UnifiedMaskEntityListPage,
    UnifiedMaskEntityListingService,
)
from arkumu.metadata.services.mask_runtime_service import ResolvedMaskSchema, MaskRuntimeService
from arkumu.metadata.services.mask_schema import (
    MASK_PHASE_ALL,
    MASK_PHASE_CREATE,
    MASK_PHASE_ENRICHMENT,
    list_available_mask_schemas,
)
from arkumu.users.models import Organization


@dataclass(frozen=True)
class WorkspaceEntityOption:
    entity_type: str
    label: str
    create_supported: bool
    preview_url: str
    create_url: Optional[str]


@dataclass(frozen=True)
class UnifiedMaskWorkspacePayload:
    organizations: List[Organization]
    selected_organization: Optional[str]
    entity_options: List[WorkspaceEntityOption]
    selected_entity: str
    selected_phase: str
    search_query: str
    phase_options: List[dict]
    resolved_mask: ResolvedMaskSchema
    selected_section: Optional[str]
    existing_entities: List[UnifiedMaskEntityListItem]
    existing_entities_page: UnifiedMaskEntityListPage
    selected_resource_uri: Optional[str]
    selected_resource_label: Optional[str]
    selected_resource_values: Dict[str, LoadedMaskFieldValue]


class UnifiedMaskWorkspaceService:
    """Build page payloads for the new institution-agnostic mask workspace."""

    def __init__(
        self,
        *,
        runtime_service: Optional[MaskRuntimeService] = None,
        listing_service: Optional[UnifiedMaskEntityListingService] = None,
        value_loader: Optional[MaskValueLoaderService] = None,
    ) -> None:
        self.runtime_service = runtime_service or MaskRuntimeService()
        self.listing_service = listing_service or UnifiedMaskEntityListingService()
        self.value_loader = value_loader or MaskValueLoaderService()

    def list_organizations(self) -> List[Organization]:
        return list(Organization.objects.filter(is_active=True).order_by("name"))

    def resolve_organization_code(self, organization_code: Optional[str]) -> Optional[str]:
        organizations = self.list_organizations()
        available_codes = {organization.code.lower() for organization in organizations}
        normalized = (organization_code or "").strip().lower()
        if normalized in available_codes:
            return normalized
        if organizations:
            return organizations[0].code.lower()
        return None

    def resolve_entity_type(self, entity_type: Optional[str]) -> str:
        normalized = (entity_type or "").strip().lower()
        available = {schema.entity_type for schema in list_available_mask_schemas()}
        if normalized in available:
            return normalized
        return "project"

    def resolve_page(self, page: Optional[int | str]) -> int:
        try:
            parsed = int(page or 1)
        except (TypeError, ValueError):
            parsed = 1
        return max(1, parsed)

    def build_payload(
        self,
        *,
        organization_code: Optional[str],
        entity_type: Optional[str],
        phase: Optional[str],
        section: Optional[str],
        resource_uri: Optional[str],
        page: Optional[int] = None,
        search_query: Optional[str] = None,
    ) -> UnifiedMaskWorkspacePayload:
        organizations = self.list_organizations()
        selected_organization = self.resolve_organization_code(organization_code)
        selected_entity = self.resolve_entity_type(entity_type)
        selected_page = self.resolve_page(page)
        normalized_search = (search_query or "").strip()
        resolved_mask = self.runtime_service.resolve(
            entity_type=selected_entity,
            organization_code=selected_organization,
            phase=phase,
        )
        entity_options = self._build_entity_options(
            organization_code=selected_organization,
            phase=resolved_mask.phase,
        )
        selected_section = self._resolve_section_name(section, resolved_mask)
        existing_entities_page = self._build_existing_entities(
            organization_code=selected_organization,
            entity_type=selected_entity,
            phase=resolved_mask.phase,
            section=selected_section,
            resource_uri=resource_uri,
            page=selected_page,
            search_query=normalized_search,
        )
        existing_entities = existing_entities_page.items
        selected_resource_uri = self._resolve_selected_resource_uri(resource_uri, existing_entities)
        active_section = next(
            (
                resolved_section
                for resolved_section in resolved_mask.sections
                if resolved_section.section.name == selected_section
            ),
            None,
        )
        selected_resource_values = self.value_loader.load_field_values(
            organization_code=selected_organization,
            resource_uri=selected_resource_uri,
            fields=active_section.fields if active_section else [],
        )
        selected_resource_label = next(
            (entity.label for entity in existing_entities if entity.uri == selected_resource_uri),
            None,
        )

        return UnifiedMaskWorkspacePayload(
            organizations=organizations,
            selected_organization=selected_organization,
            entity_options=entity_options,
            selected_entity=selected_entity,
            selected_phase=resolved_mask.phase,
            search_query=normalized_search,
            phase_options=[
                {"value": MASK_PHASE_CREATE, "label": "Anlegen"},
                {"value": MASK_PHASE_ENRICHMENT, "label": "Erweitern"},
                {"value": MASK_PHASE_ALL, "label": "Alle Felder"},
            ],
            resolved_mask=resolved_mask,
            selected_section=selected_section,
            existing_entities=existing_entities,
            existing_entities_page=existing_entities_page,
            selected_resource_uri=selected_resource_uri,
            selected_resource_label=selected_resource_label,
            selected_resource_values=selected_resource_values,
        )

    def _build_entity_options(
        self,
        *,
        organization_code: Optional[str],
        phase: str,
    ) -> List[WorkspaceEntityOption]:
        options: List[WorkspaceEntityOption] = []
        for schema in list_available_mask_schemas():
            preview_query = urlencode(
                {
                    "organization": organization_code or "",
                    "entity": schema.entity_type,
                    "phase": phase,
                }
            )
            preview_url = f"{reverse('metadata:unified_mask_workspace')}?{preview_query}"
            create_url = None
            if schema.create_supported:
                create_query = urlencode(
                    {
                        "organization": organization_code or "",
                        "entity": schema.entity_type,
                    }
                )
                create_url = f"{reverse('metadata:mask_create')}?{create_query}"
            options.append(
                WorkspaceEntityOption(
                    entity_type=schema.entity_type,
                    label=schema.label,
                    create_supported=schema.create_supported,
                    preview_url=preview_url,
                    create_url=create_url,
                )
            )
        return options

    def _resolve_section_name(
        self,
        requested_section: Optional[str],
        resolved_mask: ResolvedMaskSchema,
    ) -> Optional[str]:
        available = [section.section.name for section in resolved_mask.sections]
        normalized = (requested_section or "").strip()
        if normalized in available:
            return normalized
        return available[0] if available else None

    def _build_existing_entities(
        self,
        *,
        organization_code: Optional[str],
        entity_type: str,
        phase: str,
        section: Optional[str],
        resource_uri: Optional[str],
        page: Optional[int],
        search_query: str,
    ) -> UnifiedMaskEntityListPage:
        listing_page = self.listing_service.list_entities(
            organization_code=organization_code,
            entity_type=entity_type,
            page=self.resolve_page(page),
            search_query=search_query,
        )
        items = [
            UnifiedMaskEntityListItem(
                uri=item.uri,
                label=item.label,
                edit_url=item.edit_url,
                visibility=item.visibility,
                updated_at=item.updated_at,
                summary=item.summary,
                source_dataset=item.source_dataset,
                workspace_url=self._build_workspace_url(
                    organization_code=organization_code,
                    entity_type=entity_type,
                    phase=phase,
                    section=section,
                    resource_uri=item.uri,
                    page=listing_page.page,
                    search_query=search_query,
                ),
            )
            for item in listing_page.items
        ]
        return UnifiedMaskEntityListPage(
            items=items,
            page=listing_page.page,
            per_page=listing_page.per_page,
            total_count=listing_page.total_count,
        )

    def _resolve_selected_resource_uri(
        self,
        resource_uri: Optional[str],
        existing_entities: List[UnifiedMaskEntityListItem],
    ) -> Optional[str]:
        requested = (resource_uri or "").strip()
        if requested and any(entity.uri == requested for entity in existing_entities):
            return requested
        return None

    def _build_workspace_url(
        self,
        *,
        organization_code: Optional[str],
        entity_type: str,
        phase: str,
        section: Optional[str],
        resource_uri: Optional[str],
        page: Optional[int],
        search_query: str,
    ) -> str:
        query = urlencode(
            {
                "organization": organization_code or "",
                "entity": entity_type,
                "phase": phase,
                "section": section or "",
                "resource_uri": resource_uri or "",
                "page": page or 1,
                "search": search_query,
            }
        )
        return f"{reverse('metadata:unified_mask_workspace')}?{query}"
