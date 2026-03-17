"""Views powering the canonical metadata entry UI."""

from __future__ import annotations

import json
import logging
import time
from typing import Dict, Iterable, List
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

from django.contrib.auth.mixins import UserPassesTestMixin
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import render
from django.views import View
from django.views.generic import TemplateView
from django.urls import reverse

from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.services.mask_create_service import MaskCreateService
from arkumu.metadata.services.unified_mask_workspace_service import UnifiedMaskWorkspaceService
from arkumu.metadata.services.metadata_entry_service import (
    EntryResult,
    MetadataEntryService,
    SectionManifest,
)
from arkumu.metadata.services.mask_schema import (
    MASK_PHASE_ALL,
    MASK_PHASE_CREATE,
    MASK_PHASE_ENRICHMENT,
    list_available_mask_schemas,
    list_creatable_mask_schemas,
    normalize_mask_phase,
)
from arkumu.metadata.services.mask_runtime_service import MaskRuntimeService
from arkumu.metadata.services.project_structure_service import ProjectStructureService
from arkumu.metadata.services.recent_metadata_entry_service import (
    RecentMetadataEntryService,
)
from arkumu.metadata.views.csv_mapping.mixins.template_helpers import (
    CSVMappingTemplateHelperMixin,
)
from arkumu.common.mixins.base_coordinator import BaseCoordinatorMixin
from arkumu.users.mixins import GeneralLoginRequiredMixin
from arkumu.users.models import Organization


class MetadataEntryMixin(BaseCoordinatorMixin, GeneralLoginRequiredMixin, CSVMappingTemplateHelperMixin):
    """Shared helpers for metadata entry views."""

    allowed_org_codes = {"fuk", "det", "rsh"}

    tab_config = (
        (
            "project",
            "Projekte",
            "metadata:tabular_projects",
        ),
        (
            "ereignis",
            "Ereignisse",
            "metadata:tabular_ereignis",
        ),
        (
            "akteur",
            "Akteure",
            "metadata:tabular_akteur",
        ),
        (
            "ort",
            "Orte",
            "metadata:tabular_ort",
        ),
        (
            "digitales_objekt",
            "Digitale Objekte",
            "metadata:tabular_digitales_objekt",
        ),
        (
            "equipment_software",
            "Equipment Software",
            "metadata:tabular_equipment_software",
        ),
        (
            "alternativer_titel",
            "Alternative Titel",
            "metadata:tabular_alternativer_titel",
        ),
    )
    default_entity = "project"

    def _allowed_organizations(self) -> Iterable[Organization]:
        return Organization.objects.filter(code__in=self.allowed_org_codes, is_active=True).order_by("name")

    def _resolve_organization_code(self, request: HttpRequest) -> str | None:
        raw_code = request.POST.get("organization") or request.GET.get("organization")
        if raw_code and raw_code.lower() in self.allowed_org_codes:
            return raw_code.lower()
        session_org = self.get_current_organization(request)
        if session_org:
            code = (session_org.get("code") or "").lower()
            if code in self.allowed_org_codes:
                return code
        user_org = getattr(request.user, "organization", None)
        if user_org and user_org.code in self.allowed_org_codes:
            return user_org.code
        first_allowed = self._allowed_organizations().first()
        return first_allowed.code if first_allowed else None

    def _build_service(self, organization_code: str | None) -> MetadataEntryService:
        if not organization_code:
            raise ValueError("An organization is required for metadata entry.")
        return MetadataEntryService(organization_code)

    def _shared_context(self, request: HttpRequest) -> Dict[str, object]:
        t0 = time.perf_counter()

        organizations = list(self._allowed_organizations())
        t1 = time.perf_counter()
        logger.info("_shared_context: _allowed_organizations %.3fs", t1 - t0)

        org_code = self._resolve_organization_code(request)
        context: Dict[str, object] = {
            "organizations": organizations,
            "selected_organization": org_code,
        }
        context["navbar_metadata_entry_link"] = self.render_metadata_entry_nav_items(
            request,
            active=True,
        )
        t2 = time.perf_counter()
        logger.info("_shared_context: navbar_render %.3fs", t2 - t1)

        if org_code:
            try:
                service = self._build_service(org_code)
            except ValueError:
                context["sections"] = []
                context["metadata_service_error"] = "Organization manifest unavailable."
            else:
                self.set_current_organization(request, service.organization.id)
                context["sections"] = service.list_sections()
                context["organization"] = service.organization
        else:
            context["sections"] = []
        t3 = time.perf_counter()
        logger.info("_shared_context: service/sections %.3fs", t3 - t2)

        structure_service = ProjectStructureService()
        context["project_structure"] = structure_service.get_project_structure()
        t4 = time.perf_counter()
        logger.info("_shared_context: project_structure %.3fs", t4 - t3)

        recent_entries_service = RecentMetadataEntryService()
        allowed_codes = [org.code for org in organizations]
        context["recent_entries"] = recent_entries_service.list_recent_entries(
            organization_code=org_code,
            fallback_codes=allowed_codes,
        )
        t5 = time.perf_counter()
        logger.info("_shared_context: recent_entries %.3fs", t5 - t4)

        context["organization_code"] = org_code

        selected_entity = self._resolve_entity_key(request)
        tabs = self._build_tab_definitions(org_code, selected_entity)
        context["selected_entity"] = selected_entity
        context["entity_tabs"] = tabs
        context["active_tab_url"] = next(
            (tab["url"] for tab in tabs if tab["key"] == selected_entity),
            tabs[0]["url"] if tabs else "",
        )
        t6 = time.perf_counter()
        logger.info("_shared_context: tabs %.3fs, TOTAL %.3fs", t6 - t5, t6 - t0)

        return context

    def _resolve_entity_key(self, request: HttpRequest) -> str:
        requested = (request.GET.get("entity") or "").strip().lower()
        valid_keys = {key for key, *_ in self.tab_config}
        if requested in valid_keys:
            return requested
        return self.default_entity

    def _build_tab_definitions(
        self,
        organization_code: str | None,
        selected_entity: str,
    ) -> List[Dict[str, str]]:
        base_params = {"embed": "1"}
        if organization_code:
            base_params["organization"] = organization_code
        query = urlencode(base_params)
        tabs: List[Dict[str, str]] = []
        for key, label, url_name in self.tab_config:
            url = reverse(url_name)
            full_url = f"{url}?{query}" if query else url
            tabs.append(
                {
                    "key": key,
                    "label": label,
                    "url": full_url,
                    "checked": key == selected_entity,
                }
            )
        return tabs

    def _build_field_context(
        self,
        manifest: SectionManifest,
        initial_data: Dict[str, object],
        errors: Dict[str, str],
    ) -> List[Dict[str, object]]:
        field_blocks: List[Dict[str, object]] = []
        for field in manifest.fields:
            field_blocks.append(
                {
                    "field": field,
                    "value": initial_data.get(field.name, ""),
                    "error": errors.get(field.name, ""),
                }
            )
        return field_blocks

    def _build_payload(self, post_data, manifest: SectionManifest) -> Dict[str, object]:
        payload: Dict[str, object] = {}
        for field in manifest.fields:
            values = post_data.getlist(field.name)
            if not values:
                payload[field.name] = ""
            else:
                payload[field.name] = values[-1]
        return payload


class MaskPreviewMixin(BaseCoordinatorMixin, GeneralLoginRequiredMixin, CSVMappingTemplateHelperMixin):
    """Helpers for the standalone mask preview page."""

    default_entity = "project"
    runtime_service = MaskRuntimeService()

    def _organizations(self) -> Iterable[Organization]:
        return Organization.objects.filter(is_active=True).order_by("name")

    def _resolve_organization_code(self, request: HttpRequest) -> str | None:
        raw_code = request.GET.get("organization")
        if raw_code:
            return raw_code.lower()
        user_org = getattr(request.user, "organization", None)
        if user_org and user_org.code:
            return user_org.code.lower()
        first_org = self._organizations().first()
        return first_org.code.lower() if first_org else None

    def _resolve_entity_type(self, request: HttpRequest) -> str:
        requested = (request.GET.get("entity") or "").strip().lower()
        available = {schema.entity_type for schema in list_available_mask_schemas()}
        if requested in available:
            return requested
        return self.default_entity

    def _resolve_phase(self, request: HttpRequest) -> str:
        return normalize_mask_phase(request.GET.get("phase"))

    def _resolve_section_name(
        self,
        request: HttpRequest,
        *,
        section_blocks: List[Dict[str, object]],
    ) -> str | None:
        requested = (request.GET.get("section") or "").strip()
        available = [str(block["section"].name) for block in section_blocks]
        if requested in available:
            return requested
        return available[0] if available else None

    def _build_mask_context(self, request: HttpRequest) -> Dict[str, object]:
        organization_code = self._resolve_organization_code(request)
        entity_type = self._resolve_entity_type(request)
        phase = self._resolve_phase(request)
        runtime = self.runtime_service.resolve(
            entity_type=entity_type,
            organization_code=organization_code,
            phase=phase,
        )

        section_blocks = [
            {
                "section": section.section,
                "fields": section.fields,
            }
            for section in runtime.sections
        ]
        selected_section = self._resolve_section_name(request, section_blocks=section_blocks)
        active_section = next(
            (block for block in section_blocks if block["section"].name == selected_section),
            None,
        )

        return {
            "organizations": list(self._organizations()),
            "selected_organization": organization_code,
            "entity_type": entity_type,
            "selected_phase": phase,
            "phase_options": [
                {"value": MASK_PHASE_CREATE, "label": "Anlegen"},
                {"value": MASK_PHASE_ENRICHMENT, "label": "Erweitern"},
                {"value": MASK_PHASE_ALL, "label": "Alle Felder"},
            ],
            "available_entities": list_available_mask_schemas(),
            "mask_schema": runtime.schema,
            "mask_sections": section_blocks,
            "selected_section": selected_section,
            "active_section": active_section,
            "mapping_sources": runtime.mapping_sources,
            "mapping_count": runtime.mapping_count,
            "navbar_metadata_entry_link": self.render_metadata_entry_nav_items(
                request,
                active=True,
            ),
        }


class MaskCreateMixin(BaseCoordinatorMixin, GeneralLoginRequiredMixin, CSVMappingTemplateHelperMixin):
    """Helpers for productive mask-driven create views."""

    default_entity = "project"

    def _organizations(self) -> Iterable[Organization]:
        return Organization.objects.filter(is_active=True).order_by("name")

    def _resolve_organization_code(self, request: HttpRequest) -> str | None:
        raw_code = request.POST.get("organization") or request.GET.get("organization")
        if raw_code:
            return raw_code.lower()
        user_org = getattr(request.user, "organization", None)
        if user_org and user_org.code:
            return user_org.code.lower()
        first_org = self._organizations().first()
        return first_org.code.lower() if first_org else None

    def _resolve_entity_type(self, request: HttpRequest) -> str:
        requested = (request.POST.get("entity") or request.GET.get("entity") or "").strip().lower()
        available = {schema.entity_type for schema in list_creatable_mask_schemas()}
        if requested in available:
            return requested
        return self.default_entity

    def _get_form_service(self, request: HttpRequest) -> MaskCreateService:
        organization_code = self._resolve_organization_code(request)
        entity_type = self._resolve_entity_type(request)
        if not organization_code:
            raise ValueError("Organization is required.")
        return MaskCreateService(organization_code, entity_type)

    def _resolve_section_name(
        self,
        request: HttpRequest,
        *,
        section_blocks: List[Dict[str, object]],
    ) -> str | None:
        requested = (request.POST.get("section") or request.GET.get("section") or "").strip()
        available = [str(block["section"].name) for block in section_blocks]
        if requested in available:
            return requested
        return available[0] if available else None

    def _set_workspace_context(self, request: HttpRequest, organization: Organization) -> None:
        self.set_current_organization(request, organization.id)
        mapping = (
            Mapping.objects.filter(organization_id=organization.code)
            .order_by("-is_active", "-created_at")
            .first()
        )
        if mapping:
            self.set_current_mapping(
                request,
                str(mapping.id),
                mapping_name=mapping.name,
                organization_id=organization.id,
            )

    def _build_context(
        self,
        *,
        request: HttpRequest,
        service: MaskCreateService,
        initial_data: Dict[str, str],
        errors: Dict[str, str],
    ) -> Dict[str, object]:
        manifest = service.get_form_manifest()
        section_blocks: List[Dict[str, object]] = []
        for section in manifest.sections:
            section_blocks.append(
                {
                    "section": section,
                    "fields": [
                        {
                            "field": field,
                            "value": initial_data.get(field.name, ""),
                            "error": errors.get(field.name, ""),
                        }
                        for field in section.fields
                    ],
                }
            )
        selected_section = self._resolve_section_name(request, section_blocks=section_blocks)
        active_section = next(
            (block for block in section_blocks if block["section"].name == selected_section),
            None,
        )
        return {
            "organizations": list(self._organizations()),
            "selected_organization": service.organization.code,
            "available_entities": list_creatable_mask_schemas(),
            "entity_type": service.entity_type,
            "form_manifest": manifest,
            "form_sections": section_blocks,
            "selected_section": selected_section,
            "active_section": active_section,
            "navbar_metadata_entry_link": self.render_metadata_entry_nav_items(
                request,
                active=True,
            ),
        }

    def _build_redirect_url(self, entity_type: str, resource_uri: str) -> str:
        if entity_type == "project":
            base_url = reverse("metadata:edit_project")
        elif entity_type == "event":
            base_url = reverse("metadata:edit_ereignis")
        elif entity_type == "actor":
            base_url = reverse("metadata:edit_akteur")
        else:
            raise ValueError(f"Unsupported entity type '{entity_type}'")
        return f"{base_url}?{urlencode({'uri': resource_uri})}"


class MetadataEntryDashboardView(MetadataEntryMixin, TemplateView):
    """Renders the base metadata entry workspace."""

    template_name = "metadata/entry/dashboard.html"

    def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        context = self._shared_context(request)
        if request.headers.get("HX-Request"):
            return render(request, "metadata/entry/partials/dashboard_inner.html", context)
        return render(request, self.template_name, context)


class SuperuserRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_superuser


class MaskPreviewDashboardView(SuperuserRequiredMixin, MaskPreviewMixin, TemplateView):
    """Read only preview for schema driven masks and their mapping bindings."""

    template_name = "metadata/mask_entry/dashboard.html"

    def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        context = self._build_mask_context(request)
        if request.headers.get("HX-Request"):
            return render(request, "metadata/mask_entry/partials/dashboard_inner.html", context)
        return render(request, self.template_name, context)


class MaskCreateView(SuperuserRequiredMixin, MaskCreateMixin, TemplateView):
    """Productive create form driven by the mask create phase."""

    template_name = "metadata/mask_create/dashboard.html"

    def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        service = self._get_form_service(request)
        context = self._build_context(
            request=request,
            service=service,
            initial_data=service.build_initial_data(),
            errors={},
        )
        return render(request, self.template_name, context)

    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        service = self._get_form_service(request)
        payload = {
            field.name: request.POST.get(field.name, "")
            for field in service.get_form_manifest().fields
        }
        result = service.persist(payload)
        if result.success and result.resource is not None:
            self._set_workspace_context(request, service.organization)
            return HttpResponseRedirect(self._build_redirect_url(service.entity_type, result.resource.uri))

        context = self._build_context(
            request=request,
            service=service,
            initial_data=payload,
            errors=result.field_errors,
        )
        return render(request, self.template_name, context, status=400)


class UnifiedMaskWorkspaceView(SuperuserRequiredMixin, GeneralLoginRequiredMixin, CSVMappingTemplateHelperMixin, TemplateView):
    """Unified cross-institution workspace for mask navigation and create entry."""

    template_name = "metadata/unified_mask_workspace/dashboard.html"
    workspace_service = UnifiedMaskWorkspaceService()

    def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        payload = self.workspace_service.build_payload(
            organization_code=request.GET.get("organization"),
            entity_type=request.GET.get("entity"),
            phase=request.GET.get("phase"),
            section=request.GET.get("section"),
            resource_uri=request.GET.get("resource_uri"),
            page=request.GET.get("page"),
            search_query=request.GET.get("search"),
        )
        active_section = next(
            (
                section
                for section in payload.resolved_mask.sections
                if section.section.name == payload.selected_section
            ),
            None,
        )
        context = {
            "organizations": payload.organizations,
            "selected_organization": payload.selected_organization,
            "entity_options": payload.entity_options,
            "selected_entity": payload.selected_entity,
            "phase_options": payload.phase_options,
            "selected_phase": payload.selected_phase,
            "search_query": payload.search_query,
            "resolved_mask": payload.resolved_mask,
            "selected_section": payload.selected_section,
            "active_section": active_section,
            "existing_entities": payload.existing_entities,
            "existing_entities_page": payload.existing_entities_page,
            "selected_resource_uri": payload.selected_resource_uri,
            "selected_resource_label": payload.selected_resource_label,
            "selected_resource_values": payload.selected_resource_values,
            "navbar_metadata_entry_link": self.render_metadata_entry_nav_items(
                request,
                active=True,
            ),
        }
        if request.headers.get("HX-Request"):
            return render(
                request,
                "metadata/unified_mask_workspace/partials/dashboard_inner.html",
                context,
            )
        return render(request, self.template_name, context)


class MetadataEntrySectionView(MetadataEntryMixin, View):
    """Returns the HTMX form for a specific section."""

    template_name = "metadata/entry/partials/section_form.html"

    def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        org_code = self._resolve_organization_code(request)
        section = request.GET.get("section")
        if not org_code or not section:
            return HttpResponseBadRequest("Missing organization or section parameter.")

        try:
            service = self._build_service(org_code)
            manifest = service.get_section_manifest(section)
            self.set_current_organization(request, service.organization.id)
        except ValueError as exc:
            return HttpResponseBadRequest(str(exc))

        initial_data = service.build_initial_data(section)
        context = {
            "manifest": manifest,
            "organization": service.organization,
            "organization_code": org_code,
            "result": None,
            "initial_data": initial_data,
            "form_error": "",
            "navbar_metadata_entry_link": self.render_metadata_entry_nav_items(
                request,
                active=True,
            ),
            "fields": self._build_field_context(manifest, initial_data, {}),
        }
        return render(request, self.template_name, context)


class MetadataEntrySubmitView(MetadataEntryMixin, View):
    """Handles HTMX submissions for metadata entry."""

    template_name = "metadata/entry/partials/section_form.html"

    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        org_code = self._resolve_organization_code(request)
        section = request.POST.get("section")
        if not org_code or not section:
            return HttpResponseBadRequest("Missing organization or section parameter.")

        try:
            service = self._build_service(org_code)
            manifest = service.get_section_manifest(section)
            self.set_current_organization(request, service.organization.id)
        except ValueError as exc:
            return HttpResponseBadRequest(str(exc))

        payload = self._build_payload(request.POST, manifest)
        result: EntryResult = service.persist_entry(section, payload)
        recent_entries_service = RecentMetadataEntryService()

        if result.success:
            manifest = service.get_section_manifest(section)
            initial_data = service.build_initial_data(section)
            errors: Dict[str, str] = {}
            if result.record:
                resource_uri = result.resource.uri if result.resource else ""
                resource_id = str(result.resource.id) if result.resource else None
                recent_entries_service.record_entry(
                    organization_code=org_code,
                    title=result.record.title,
                    uri=resource_uri,
                    resource_id=resource_id,
                )
        else:
            initial_data = payload
            errors = result.field_errors

        context = {
            "manifest": manifest,
            "organization": service.organization,
            "organization_code": org_code,
            "result": result,
            "initial_data": initial_data,
            "form_error": "",
            "navbar_metadata_entry_link": self.render_metadata_entry_nav_items(
                request,
                active=True,
            ),
            "fields": self._build_field_context(manifest, initial_data, errors),
        }
        response = render(request, self.template_name, context)
        if result.success:
            trigger_payload = {
                "metadata-entry:submission-success": {
                    "organization": org_code,
                }
            }
            response["HX-Trigger"] = json.dumps(trigger_payload)
        return response


class MetadataEntryLatestProjectsView(MetadataEntryMixin, View):
    """HTMX endpoint providing the latest project submissions panel."""

    template_name = "metadata/entry/partials/latest_projects.html"

    def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        org_code = self._resolve_organization_code(request)
        organizations = list(self._allowed_organizations())
        recent_entries_service = RecentMetadataEntryService()
        fallback_codes = [org.code for org in organizations]
        recent_entries = recent_entries_service.list_recent_entries(
            organization_code=org_code,
            fallback_codes=fallback_codes,
        )

        context = {
            "recent_entries": recent_entries,
            "selected_organization": org_code,
        }
        return render(request, self.template_name, context)
