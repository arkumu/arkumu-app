from __future__ import annotations

from typing import Any, Dict
from uuid import UUID

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import TemplateView
from django.core.paginator import Paginator

from arkumu.metadata.models.resource import Resource
from arkumu.metadata.services.project_workspace_listing_service import (
    ProjectWorkspaceFilters,
    ProjectWorkspaceListingService,
    STATUS_BADGE_STYLES,
    STATUS_LABELS,
)
from arkumu.users.mixins import ManagerRequiredMixin
from arkumu.users.models import Organization


class ProjectOverviewManageView(ManagerRequiredMixin, TemplateView):
    """Render the HTMX-powered workspace overview shell."""

    template_name = "metadata/projects/manage.html"

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        context = super().get_context_data(**kwargs)
        filters = ProjectWorkspaceFilters.from_query_params(self.request.GET.dict())
        user = self.request.user

        organizations_qs = Organization.objects.order_by("name")
        if user.has_role_permission("can_view_cross_university_public"):
            organizations = list(organizations_qs)
            show_all_option = True
        else:
            organizations = [user.organization] if user.organization else []
            show_all_option = False

        context.update(
            {
                "filters": filters,
                "organizations": organizations,
                "show_all_option": show_all_option,
                "status_labels": STATUS_LABELS,
                "page_sizes": (25, 50, 100),
            }
        )
        return context


class ProjectOverviewTableView(ManagerRequiredMixin, View):
    """Return the paginated table body for the overview list."""

    template_name = "metadata/projects/partials/table_body.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        filters = ProjectWorkspaceFilters.from_query_params(request.GET.dict())
        service = ProjectWorkspaceListingService(request.user)
        queryset = service.get_queryset(filters)

        paginator = Paginator(queryset, filters.page_size)
        page_obj = paginator.get_page(filters.page)
        service.populate_actor_counts(page_obj.object_list)

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
            },
            request=request,
        )
        return HttpResponse(html)


class ProjectOverviewDetailView(ManagerRequiredMixin, View):
    """Render the expandable detail drawer."""

    template_name = "metadata/projects/partials/detail_panel.html"

    def get(self, request: HttpRequest, resource_id: UUID) -> HttpResponse:
        service = ProjectWorkspaceListingService(request.user)
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
        service = ProjectWorkspaceListingService(request.user)
        try:
            project = service.project_from_id(resource_id)
            project = self._mutate(service, project)
            raw_params = {**request.GET.dict(), **request.POST.dict()}
            filters = ProjectWorkspaceFilters.from_query_params(raw_params)
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

        row_html = render_to_string(
            "metadata/projects/partials/row.html",
            {
                "project": refreshed,
                "status_labels": STATUS_LABELS,
                "status_badges": STATUS_BADGE_STYLES,
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
