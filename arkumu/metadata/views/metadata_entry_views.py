"""Views powering the canonical metadata entry UI."""

from __future__ import annotations

import json
from typing import Dict, Iterable, List
from urllib.parse import urlencode

from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.views import View
from django.views.generic import TemplateView
from django.urls import reverse

from arkumu.metadata.services.metadata_entry_service import (
    EntryResult,
    MetadataEntryService,
    SectionManifest,
)
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
        organizations = list(self._allowed_organizations())
        org_code = self._resolve_organization_code(request)
        context: Dict[str, object] = {
            "organizations": organizations,
            "selected_organization": org_code,
        }
        context["navbar_metadata_entry_link"] = self.render_metadata_entry_nav_items(
            request,
            active=True,
        )
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

        structure_service = ProjectStructureService()
        context["project_structure"] = structure_service.get_project_structure()

        recent_entries_service = RecentMetadataEntryService()
        allowed_codes = [org.code for org in organizations]
        context["recent_entries"] = recent_entries_service.list_recent_entries(
            organization_code=org_code,
            fallback_codes=allowed_codes,
        )
        context["organization_code"] = org_code

        selected_entity = self._resolve_entity_key(request)
        tabs = self._build_tab_definitions(org_code, selected_entity)
        context["selected_entity"] = selected_entity
        context["entity_tabs"] = tabs
        context["active_tab_url"] = next(
            (tab["url"] for tab in tabs if tab["key"] == selected_entity),
            tabs[0]["url"] if tabs else "",
        )
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


class MetadataEntryDashboardView(MetadataEntryMixin, TemplateView):
    """Renders the base metadata entry workspace."""

    template_name = "metadata/entry/dashboard.html"

    def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        context = self._shared_context(request)
        if request.headers.get("HX-Request"):
            return render(request, "metadata/entry/partials/dashboard_inner.html", context)
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

    def _build_payload(self, post_data, manifest: SectionManifest) -> Dict[str, object]:
        payload: Dict[str, object] = {}
        for field in manifest.fields:
            values = post_data.getlist(field.name)
            if not values:
                payload[field.name] = ""
            else:
                payload[field.name] = values[-1]
        return payload
