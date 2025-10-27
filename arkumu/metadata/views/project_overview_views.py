from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID
from urllib.parse import urlencode

from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views import View

from arkumu.common.mixins.base_coordinator import BaseCoordinatorMixin
from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.schema_workspace.services import SchemaWorkspaceService
from arkumu.metadata.services.project_workspace_listing_service import (
    ProjectWorkspaceFilters,
    ProjectWorkspaceListingService,
    STATUS_BADGE_STYLES,
    STATUS_LABELS,
)
from arkumu.users.mixins import ManagerRequiredMixin
from arkumu.users.models import Organization


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DatasetOption:
    dataset_name: str
    label: str
    is_vocabulary: bool


def _resolve_dataset_options(active_org_code: Optional[str]) -> Tuple[List[DatasetOption], List[DatasetOption]]:
    entity_options: List[DatasetOption] = []
    vocab_options: List[DatasetOption] = []

    if active_org_code:
        try:
            org = Organization.objects.filter(code=active_org_code).first()
            mapping = (
                Mapping.objects.filter(organization_id=active_org_code)
                .order_by("-created_at")
                .first()
            )
            if mapping and org:
                workspace_service = SchemaWorkspaceService(mapping=mapping, organization=org)
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
            logger.exception("PROJECT_OVERVIEW: Failed to resolve datasets for org %s", active_org_code)

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


def _select_dataset(
    user,
    dataset_name: Optional[str],
    *,
    organization_code: Optional[str] = None,
) -> Tuple[DatasetOption, List[DatasetOption], List[DatasetOption]]:
    active_org_code = organization_code

    if not active_org_code or active_org_code == "all":
        organization = getattr(user, "organization", None)
        if organization:
            active_org_code = organization.code

    entity_options, vocab_options = _resolve_dataset_options(active_org_code)
    if not entity_options and not vocab_options and active_org_code is None:
        entity_options, vocab_options = _resolve_dataset_options(
            getattr(getattr(user, "organization", None), "code", None)
        )
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

    def _build_dataset_detail_context(
        self,
        *,
        organization: Optional[Organization],
        dataset_option: Optional[DatasetOption],
    ) -> Dict[str, Any]:
        """
        Prepare dataset detail information for the project overview drawer.
        """
        detail: Dict[str, Any] = {
            "available": False,
            "summary": None,
            "properties": [],
            "relationships": [],
            "join_relationships": [],
            "has_more_properties": False,
            "total_properties": 0,
            "total_relationships": 0,
            "anchor_columns": [],
            "workspace_url": None,
            "dataset_label": dataset_option.label if dataset_option else None,
            "message": None,
            "is_vocabulary": bool(dataset_option.is_vocabulary) if dataset_option else False,
            "organization_name": organization.name if organization else None,
            "preview_columns": [],
            "preview_entries": [],
        }

        if not dataset_option:
            detail["message"] = _("Wähle ein Dataset aus, um seine Felder zu sehen.")
            return detail

        if not organization:
            detail["message"] = _(
                "Wähle zuerst eine Organisation, damit wir die verfügbaren Felder anzeigen können."
            )
            return detail

        mapping = (
            Mapping.objects.filter(organization_id=organization.code)
            .order_by("-created_at")
            .first()
        )
        if not mapping:
            detail["message"] = _(
                "Für diese Organisation steht noch kein Workspace-Mapping bereit."
            )
            return detail

        try:
            service = SchemaWorkspaceService(mapping=mapping, organization=organization)
            summaries = {item.dataset_name: item for item in service.list_datasets()}
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception(
                "PROJECT_OVERVIEW: Failed to initialise workspace service for %s: %s",
                organization.code,
                exc,
            )
            detail["message"] = _(
                "Dataset-Informationen konnten nicht geladen werden. Versuche es später erneut."
            )
            return detail

        summary = summaries.get(dataset_option.dataset_name)
        if not summary:
            detail["message"] = _(
                "Dieses Dataset ist im aktuellen Workspace noch nicht konfiguriert."
            )
            return detail

        try:
            schema = service.get_dataset_schema(summary.dataset_name)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception(
                "PROJECT_OVERVIEW: Missing schema for dataset %s/%s: %s",
                organization.code,
                summary.dataset_name,
                exc,
            )
            detail["message"] = _(
                "Dieses Dataset ist im aktuellen Workspace noch nicht konfiguriert."
            )
            return detail

        anchor_columns = summary.anchor_columns or []
        column_meta = schema.get("column_metadata", {})
        properties: List[Dict[str, Any]] = []
        for column_name, property_resource in (schema.get("properties") or {}).items():
            meta = column_meta.get(column_name, {})
            properties.append(
                {
                    "column": column_name,
                    "label": getattr(property_resource, "name", column_name),
                    "required": bool(meta.get("required")),
                    "data_type": meta.get("data_type")
                    or meta.get("type")
                    or meta.get("python_type")
                    or meta.get("field_type")
                    or "",
                    "description": meta.get("description") or "",
                    "is_anchor": column_name in anchor_columns,
                }
            )

        properties.sort(key=lambda item: item["label"].lower())
        max_visible_properties = 15
        detail["total_properties"] = len(properties)
        detail["has_more_properties"] = len(properties) > max_visible_properties
        detail["properties"] = properties[:max_visible_properties]

        relationships = []
        for rel in schema.get("fk_relationships", []) or []:
            relationships.append(
                {
                    "label": rel.get("label") or rel.get("source_column"),
                    "source_column": rel.get("source_column"),
                    "target_dataset": rel.get("target_dataset"),
                    "cardinality": rel.get("cardinality") or rel.get("relationship_type"),
                }
            )

        join_relationships = []
        for join in service.list_join_relationships(dataset_option.dataset_name):
            join_relationships.append(
                {
                    "join_dataset": join.join_dataset,
                    "other_dataset": join.other_dataset,
                    "other_display_label": join.other_display_label,
                }
            )

        workspace_query = urlencode({"dataset": summary.dataset_name})
        workspace_url = reverse("metadata:entity_creation_workspace")

        preview_columns: List[str] = []
        property_map = schema.get("properties") or {}
        max_preview_columns = 4
        for column in anchor_columns:
            if column in property_map and column not in preview_columns:
                preview_columns.append(column)
        for column in property_map.keys():
            if column not in preview_columns:
                preview_columns.append(column)
            if len(preview_columns) >= max_preview_columns:
                break

        preview_column_info = []
        for column in preview_columns:
            prop = property_map.get(column)
            preview_column_info.append(
                {
                    "column": column,
                    "label": getattr(prop, "name", column) if prop else column,
                }
            )

        preview_entries: List[Dict[str, Any]] = []
        dataset_resource = schema.get("dataset_resource")
        if dataset_resource is None:
            dataset_resource = service._resolve_dataset_resource(summary.dataset_name, schema)  # type: ignore[attr-defined]

        if dataset_resource and preview_columns:
            is_part_of_uri = "http://purl.org/dc/terms/isPartOf"
            preview_limit = 5
            entity_links = list(
                Triple.objects.filter(
                    predicate__uri=is_part_of_uri,
                    object=dataset_resource,
                )
                .select_related("subject")
                .order_by("-subject__updated_at", "subject__uri")[:preview_limit]
            )
            subjects = [link.subject for link in entity_links if link.subject]

            if subjects:
                subject_ids = [subject.id for subject in subjects if subject]
                predicate_map: Dict[str, str] = {}
                predicate_uris: Set[str] = set()
                for column in preview_columns:
                    prop = property_map.get(column)
                    if not prop:
                        continue
                    uri = getattr(prop, "uri", None)
                    if uri:
                        predicate_map[uri] = column
                        predicate_uris.add(uri)
                    canonical_uri = getattr(prop, "canonical_uri", None)
                    if canonical_uri:
                        predicate_map[canonical_uri] = column
                        predicate_uris.add(canonical_uri)

                triples = Triple.objects.filter(subject_id__in=subject_ids).filter(
                    Q(predicate__uri__in=predicate_uris)
                    | Q(predicate__canonical_uri__in=predicate_uris)
                ).select_related("object", "predicate")

                values_by_subject: Dict[Any, Dict[str, List[str]]] = {
                    subject.id: {column: [] for column in preview_columns} for subject in subjects
                }

                def _format_resource_value(resource_obj: Optional[Resource]) -> str:
                    if not resource_obj:
                        return ""
                    if resource_obj.resource_type == ResourceType.LITERAL:
                        return resource_obj.value or resource_obj.name or ""
                    return resource_obj.name or resource_obj.value or resource_obj.uri or ""

                for triple in triples:
                    column = predicate_map.get(triple.predicate.uri)
                    if not column:
                        continue
                    formatted = _format_resource_value(triple.object)
                    if formatted:
                        values_by_subject.setdefault(triple.subject_id, {}).setdefault(column, []).append(formatted)

                for subject in subjects:
                    if not subject:
                        continue
                    column_values = values_by_subject.get(subject.id) or {}
                    title = None
                    for column in anchor_columns:
                        values = column_values.get(column)
                        if values:
                            title = values[0]
                            break
                    if not title:
                        for column in preview_columns:
                            values = column_values.get(column)
                            if values:
                                title = values[0]
                                break
                    if not title:
                        title = subject.name or subject.value or subject.uri or _("Unbenannt")

                    preview_entries.append(
                        {
                            "title": title,
                            "uri": subject.uri,
                            "values": [
                                {
                                    "column": info["column"],
                                    "label": info["label"],
                                    "values": column_values.get(info["column"], []),
                                }
                                for info in preview_column_info
                            ],
                        }
                    )

        detail.update(
            {
                "available": True,
                "summary": summary,
                "anchor_columns": anchor_columns,
                "relationships": relationships,
                "join_relationships": join_relationships,
                "total_relationships": len(relationships) + len(join_relationships),
                "workspace_url": f"{workspace_url}?{workspace_query}",
                "message": None,
                "preview_columns": preview_column_info,
                "preview_entries": preview_entries,
            }
        )

        return detail


class ProjectOverviewTableView(
    ManagerRequiredMixin,
    ProjectOverviewCoordinatorMixin,
    View,
):
    """Return the paginated table body for the overview list with OOB updates."""

    template_name = "metadata/projects/partials/table_body.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        filters = ProjectWorkspaceFilters.from_query_params(request.GET.dict())
        user = request.user

        logger.info(
            "📊 TABLE VIEW: incoming filters dataset=%s org=%s",
            filters.dataset,
            filters.organization_code,
        )

        show_all_option = user.has_role_permission("can_view_cross_university_public")
        active_org_code, active_org = self._normalize_org_selection(
            request,
            requested_code=filters.organization_code,
            allow_all=show_all_option,
        )
        filters = replace(filters, organization_code=active_org_code)

        selected_dataset, entity_datasets, vocabulary_datasets = _select_dataset(
            user,
            filters.dataset,
            organization_code=active_org.code if active_org else None,
        )
        filters = replace(filters, dataset=selected_dataset.dataset_name)

        logger.info(
            "📊 TABLE VIEW: Resolved dataset=%s (entities=%s, vocabs=%s) for organization=%s",
            selected_dataset.dataset_name,
            len(entity_datasets),
            len(vocabulary_datasets),
            active_org_code,
        )

        service = ProjectWorkspaceListingService(user, dataset_name=selected_dataset.dataset_name)
        queryset = service.get_queryset(filters)

        paginator = Paginator(queryset, filters.page_size)
        page_obj = paginator.get_page(filters.page)
        service.populate_actor_counts(page_obj.object_list)
        service.enrich_project_metadata(page_obj.object_list)

        table_config = {
            "dataset_name": selected_dataset.dataset_name,
            "dataset_label": selected_dataset.label,
            "show_event_counts": service._is_project_dataset,
            "show_actor_counts": service._is_project_dataset,
            "show_digital_counts": service._is_project_dataset,
            "supports_detail": service._is_project_dataset,
        }

        dataset_detail_context = self._build_dataset_detail_context(
            organization=active_org,
            dataset_option=selected_dataset,
        )

        # Main table body HTML
        table_html = render_to_string(
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

        # OOB Update: Dataset dropdown (dataset availability tied to organization scope)
        dataset_dropdown_html = render_to_string(
            "metadata/projects/partials/dataset_dropdown.html",
            {
                "entity_datasets": entity_datasets,
                "vocabulary_datasets": vocabulary_datasets,
                "filters": filters,
            },
            request=request,
        )

        # OOB Update: Result count
        result_meta_html = render_to_string(
            "metadata/projects/partials/result_meta.html",
            {
                "total_count": paginator.count,
                "dataset_label": table_config["dataset_label"],
            },
            request=request,
        )

        dataset_detail_html = render_to_string(
            "metadata/projects/partials/dataset_detail.html",
            {
                "detail": dataset_detail_context,
            },
            request=request,
        )

        # Build response with OOB updates (table + dataset dropdown + result summary)
        oob_select = dataset_dropdown_html.replace('<select', '<select hx-swap-oob="outerHTML"', 1)
        response_html = (
            f'{table_html}'
            f'{oob_select}'
            f'<div id="project-result-meta" hx-swap-oob="innerHTML">{result_meta_html}</div>'
            f'<div id="dataset-detail-panel" hx-swap-oob="outerHTML">{dataset_detail_html}</div>'
        )

        logger.info(
            "📊 OOB RESPONSE: table_html length=%s, dropdown length=%s, meta length=%s, dataset_detail length=%s, dataset=%s",
            len(table_html),
            len(dataset_dropdown_html),
            len(result_meta_html),
            len(dataset_detail_html),
            selected_dataset.dataset_name,
        )
        logger.info(
            "📊 DATASETS: entity_options=%s, vocab_options=%s, selected=%s",
            len(entity_datasets),
            len(vocabulary_datasets),
            filters.dataset,
        )

        return HttpResponse(response_html)


class ProjectOverviewDetailView(ManagerRequiredMixin, View):
    """Render the expandable detail drawer."""

    template_name = "metadata/projects/partials/detail_panel.html"

    def get(self, request: HttpRequest, resource_id: UUID) -> HttpResponse:
        filters = ProjectWorkspaceFilters.from_query_params(request.GET.dict())
        selected_dataset, _, _ = _select_dataset(
            request.user,
            filters.dataset,
            organization_code=(filters.organization_code if filters.organization_code and filters.organization_code != "all" else getattr(getattr(request.user, "organization", None), "code", None)),
        )
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
        selected_dataset, _, _ = _select_dataset(
            request.user,
            filters.dataset,
            organization_code=(
                filters.organization_code
                if filters.organization_code and filters.organization_code != "all"
                else getattr(getattr(request.user, "organization", None), "code", None)
            ),
        )
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
        service.enrich_project_metadata([refreshed])

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
    "ProjectOverviewTableView",
    "ProjectOverviewDetailView",
    "ProjectPublishView",
    "ProjectUnpublishView",
]
