from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import TemplateView

from arkumu.common.mixins.base_coordinator import BaseCoordinatorMixin
from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.models.resource import Resource
from arkumu.metadata.schema_workspace.services import SchemaWorkspaceService
from arkumu.metadata.services.project_workspace_listing_service import (
    ProjectWorkspaceFilters,
    ProjectWorkspaceListingService,
    STATUS_BADGE_STYLES,
    STATUS_LABELS,
)
from arkumu.users.mixins import ManagerRequiredMixin
from arkumu.users.models import Organization


@dataclass(frozen=True)
class DatasetOption:
    dataset_name: str
    label: str
    is_vocabulary: bool


def _resolve_dataset_options(user) -> Tuple[List[DatasetOption], List[DatasetOption]]:
    entity_options: List[DatasetOption] = []
    vocab_options: List[DatasetOption] = []

    organization = getattr(user, "organization", None)
    if organization:
        try:
            mapping = (
                Mapping.objects.filter(organization_id=organization.code)
                .order_by("-created_at")
                .first()
            )
            if mapping:
                workspace_service = SchemaWorkspaceService(mapping=mapping, organization=organization)
                for summary in workspace_service.list_datasets():
                    option = DatasetOption(
                        dataset_name=summary.dataset_name,
                        label=summary.display_label,
                        is_vocabulary=summary.is_controlled_vocab,
                    )
                    if summary.is_controlled_vocab:
                        vocab_options.append(option)
                    else:
                        entity_options.append(option)
        except Exception:
            # Fall back to static options below if schema service fails
            pass

    if not entity_options:
        entity_options = []
    fallback_entities = [
        DatasetOption("Projekt", "Projekte", False),
        DatasetOption("Ereignis", "Ereignisse", False),
        DatasetOption("Akteurin", "Akteure", False),
        DatasetOption("Digitales Objekt", "Digitale Objekte", False),
    ]
    for option in fallback_entities:
        if option.dataset_name not in {opt.dataset_name for opt in entity_options}:
            entity_options.append(option)

    if not vocab_options:
        vocab_options = []
    fallback_vocab = [
        DatasetOption("Projektart", "Projektarten", True),
        DatasetOption("Schlagwort", "Schlagworte", True),
    ]
    for option in fallback_vocab:
        if option.dataset_name not in {opt.dataset_name for opt in vocab_options}:
            vocab_options.append(option)
    return entity_options, vocab_options


def _select_dataset(user, dataset_name: Optional[str]) -> Tuple[DatasetOption, List[DatasetOption], List[DatasetOption]]:
    entity_options, vocab_options = _resolve_dataset_options(user)
    options_map = {opt.dataset_name: opt for opt in entity_options + vocab_options}
    selected = options_map.get(dataset_name)
    if not selected:
        selected = entity_options[0] if entity_options else (vocab_options[0] if vocab_options else DatasetOption(ProjectWorkspaceListingService.DEFAULT_DATASET, ProjectWorkspaceListingService.DEFAULT_DATASET, False))
    return selected, entity_options, vocab_options


class ProjectOverviewCoordinatorMixin(BaseCoordinatorMixin):
    """Shared helpers for project overview views integrating BaseCoordinator."""

    def _normalize_org_selection(
        self,
        request: HttpRequest,
        *,
        requested_code: Optional[str],
        allow_all: bool,
    ) -> Tuple[Optional[str], Optional[Organization]]:
        """
        Determine the effective organization selection given the request, honoring
        the BaseCoordinator session and user defaults.
        """

        normalized = (requested_code or "").strip() or None

        if normalized == "all":
            if allow_all:
                self.clear_current_organization(request)
                return "all", None
            normalized = None

        if normalized:
            org_data = self.set_current_organization(request, normalized)
            if org_data:
                organization = Organization.objects.filter(id=org_data["id"]).first()
                return org_data["code"], organization
            self.clear_current_organization(request)
            normalized = None

        org_data = self.get_current_organization(request)
        if org_data:
            organization = Organization.objects.filter(id=org_data["id"]).first()
            if organization:
                return org_data["code"], organization

        user_org = getattr(request.user, "organization", None)
        if user_org:
            self.set_current_organization(request, user_org.id)
            return user_org.code, user_org

        if allow_all:
            self.clear_current_organization(request)
            return "all", None

        return None, None


class ProjectOverviewManageView(
    ManagerRequiredMixin,
    ProjectOverviewCoordinatorMixin,
    TemplateView,
):
    """Render the HTMX-powered workspace overview shell."""

    template_name = "metadata/projects/manage.html"

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        context = super().get_context_data(**kwargs)
        filters = ProjectWorkspaceFilters.from_query_params(self.request.GET.dict())
        user = self.request.user

        selected_dataset, entity_datasets, vocabulary_datasets = _select_dataset(
            user, filters.dataset
        )
        filters = replace(filters, dataset=selected_dataset.dataset_name)

        organizations_qs = Organization.objects.order_by("name")
        if user.has_role_permission("can_view_cross_university_public"):
            organizations = list(organizations_qs)
            show_all_option = True
        else:
            organizations = [user.organization] if user.organization else []
            show_all_option = False

        active_org_code, active_org = self._normalize_org_selection(
            self.request,
            requested_code=filters.organization_code,
            allow_all=show_all_option,
        )
        filters = replace(filters, organization_code=active_org_code)

        service = ProjectWorkspaceListingService(user, dataset_name=selected_dataset.dataset_name)
        queryset = service.get_queryset(filters)
        paginator = Paginator(queryset, filters.page_size)
        page_obj = paginator.get_page(filters.page)
        service.populate_actor_counts(page_obj.object_list)

        table_config = {
            "dataset_name": selected_dataset.dataset_name,
            "dataset_label": selected_dataset.label,
            "show_event_counts": service._is_project_dataset,
            "show_actor_counts": service._is_project_dataset,
            "show_digital_counts": service._is_project_dataset,
            "supports_detail": service._is_project_dataset,
        }
        table_config["total_columns"] = 5 + sum(
            1 for key in ("show_event_counts", "show_actor_counts", "show_digital_counts") if table_config[key]
        )
        table_config["total_columns"] = 5 + sum(
            1 for key in ("show_event_counts", "show_actor_counts", "show_digital_counts") if table_config[key]
        )

        table_context = {
            "projects": page_obj.object_list,
            "page_obj": page_obj,
            "paginator": paginator,
            "filters": filters,
            "status_labels": STATUS_LABELS,
            "status_badges": STATUS_BADGE_STYLES,
            "total_count": paginator.count,
            "table_config": table_config,
        }

        context.update(
            {
                "filters": filters,
                "organizations": organizations,
                "show_all_option": show_all_option,
                "active_organization": active_org,
                "active_organization_code": active_org_code,
                "status_labels": STATUS_LABELS,
                "page_sizes": (25, 50, 100),
                "table_context": table_context,
                "entity_datasets": entity_datasets,
                "vocabulary_datasets": vocabulary_datasets,
                "selected_dataset": selected_dataset,
                "table_config": table_config,
            }
        )
        return context


class ProjectOverviewTableView(
    ManagerRequiredMixin,
    ProjectOverviewCoordinatorMixin,
    View,
):
    """Return the paginated table body for the overview list."""

    template_name = "metadata/projects/partials/table_body.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        filters = ProjectWorkspaceFilters.from_query_params(request.GET.dict())
        selected_dataset, _, _ = _select_dataset(request.user, filters.dataset)
        filters = replace(filters, dataset=selected_dataset.dataset_name)

        show_all_option = request.user.has_role_permission("can_view_cross_university_public")
        active_org_code, _ = self._normalize_org_selection(
            request,
            requested_code=filters.organization_code,
            allow_all=show_all_option,
        )
        filters = replace(filters, organization_code=active_org_code)

        service = ProjectWorkspaceListingService(request.user, dataset_name=selected_dataset.dataset_name)
        queryset = service.get_queryset(filters)

        paginator = Paginator(queryset, filters.page_size)
        page_obj = paginator.get_page(filters.page)
        service.populate_actor_counts(page_obj.object_list)

        table_config = {
            "dataset_name": selected_dataset.dataset_name,
            "dataset_label": selected_dataset.label,
            "show_event_counts": service._is_project_dataset,
            "show_actor_counts": service._is_project_dataset,
            "show_digital_counts": service._is_project_dataset,
            "supports_detail": service._is_project_dataset,
        }

        html = render_to_string(
            self.template_name,
            {
                "projects": page_obj.object_list,
                "page_obj": page_obj,
                "paginator": paginator,
                "filters": filters,
                "status_labels": STATUS_LABELS,
                "status_badges": STATUS_BADGE_STYLES,
                "total_count": paginator.count,
                "table_config": table_config,
                "oob": True,
            },
            request=request,
        )
        return HttpResponse(html)


class ProjectOverviewDetailView(ManagerRequiredMixin, View):
    """Render the expandable detail drawer."""

    template_name = "metadata/projects/partials/detail_panel.html"

    def get(self, request: HttpRequest, resource_id: UUID) -> HttpResponse:
        filters = ProjectWorkspaceFilters.from_query_params(request.GET.dict())
        selected_dataset, _, _ = _select_dataset(request.user, filters.dataset)
        service = ProjectWorkspaceListingService(request.user, dataset_name=selected_dataset.dataset_name)
        try:
            project = service.project_from_id(resource_id)
            events = service.list_events(project)
            digital_objects = service.list_digital_objects(project)
        except PermissionDenied as exc:
            html = render_to_string(
                "metadata/projects/partials/feedback.html",
                {"level": "error", "message": str(exc)},
                request=request,
            )
            return HttpResponse(html, status=403)

        html = render_to_string(
            self.template_name,
            {
                "project": project,
                "events": events,
                "digital_objects": digital_objects,
                "dataset_is_project": service._is_project_dataset,
                "dataset_label": selected_dataset.label,
            },
            request=request,
        )
        return HttpResponse(html)


class _ProjectStatusMutationView(ManagerRequiredMixin, View):
    """Base class for publish/unpublish operations."""

    success_message = ""

    def _mutate(self, service: ProjectWorkspaceListingService, project: Resource) -> Resource:
        raise NotImplementedError

    def post(self, request: HttpRequest, resource_id: UUID) -> HttpResponse:
        combined_params = {**request.GET.dict(), **request.POST.dict()}
        filters = ProjectWorkspaceFilters.from_query_params(combined_params)
        selected_dataset, _, _ = _select_dataset(request.user, filters.dataset)
        filters = replace(filters, dataset=selected_dataset.dataset_name)
        service = ProjectWorkspaceListingService(request.user, dataset_name=selected_dataset.dataset_name)
        try:
            project = service.project_from_id(resource_id)
            project = self._mutate(service, project)
            refreshed = (
                service.get_queryset(filters).filter(id=project.id).first()
                or service.get_queryset(ProjectWorkspaceFilters.from_query_params({}))
                .filter(id=project.id)
                .first()
            )
        except PermissionDenied as exc:
            html = render_to_string(
                "metadata/projects/partials/feedback.html",
                {"level": "error", "message": str(exc)},
                request=request,
            )
            return HttpResponse(html, status=403)

        if not refreshed:
            status_code = getattr(project, "status_code", "draft")
            project.status_code = status_code
            project.status_label = STATUS_LABELS.get(status_code, STATUS_LABELS["draft"])
            project.status_css = STATUS_BADGE_STYLES.get(status_code, STATUS_BADGE_STYLES["draft"])
            project.events_count = getattr(project, "events_count", 0)
            project.actors_count = getattr(project, "actors_count", 0)
            project.digital_objects_count = getattr(project, "digital_objects_count", 0)
            project.is_publishable = getattr(project, "is_publishable", False)
            project.display_title = getattr(project, "display_title", project.name or project.uri)
            project.has_actor_edges = getattr(project, "has_actor_edges", False)
            refreshed = project  # Fall back to bare instance without annotations
        service.populate_actor_counts([refreshed])

        table_config = {
            "dataset_name": selected_dataset.dataset_name,
            "dataset_label": selected_dataset.label,
            "show_event_counts": service._is_project_dataset,
            "show_actor_counts": service._is_project_dataset,
            "show_digital_counts": service._is_project_dataset,
            "supports_detail": service._is_project_dataset,
        }
        table_config["total_columns"] = 5 + sum(
            1 for key in ("show_event_counts", "show_actor_counts", "show_digital_counts") if table_config[key]
        )

        row_html = render_to_string(
            "metadata/projects/partials/row.html",
            {
                "project": refreshed,
                "status_labels": STATUS_LABELS,
                "status_badges": STATUS_BADGE_STYLES,
                "table_config": table_config,
            },
            request=request,
        )
        feedback_html = render_to_string(
            "metadata/projects/partials/feedback.html",
            {"level": "success", "message": self.success_message},
            request=request,
        )

        payload = f'{row_html}<div id="project-feedback" hx-swap-oob="true">{feedback_html}</div>'
        response = HttpResponse(payload)
        response["HX-Trigger"] = "project-status-updated"
        return response


class ProjectPublishView(_ProjectStatusMutationView):
    success_message = _("Projekt wurde veröffentlicht.")

    def _mutate(
        self,
        service: ProjectWorkspaceListingService,
        project: Resource,
    ) -> Resource:
        return service.publish(project)


class ProjectUnpublishView(_ProjectStatusMutationView):
    success_message = _("Projekt wurde entveröffentlicht.")

    def _mutate(
        self,
        service: ProjectWorkspaceListingService,
        project: Resource,
    ) -> Resource:
        return service.unpublish(project)


__all__ = [
    "ProjectOverviewManageView",
    "ProjectOverviewTableView",
    "ProjectOverviewDetailView",
    "ProjectPublishView",
    "ProjectUnpublishView",
]
