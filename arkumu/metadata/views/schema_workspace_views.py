from __future__ import annotations

from typing import Dict, Optional

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views import View

from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.schema_workspace import DatasetEntityForm, SchemaWorkspaceService


def _render_dataset_panel(
    request: HttpRequest,
    *,
    service: SchemaWorkspaceService,
    dataset_name: str,
    form: DatasetEntityForm,
    field_metadata: Dict[str, Dict[str, object]],
    entity_uri: Optional[str] = None,
    success_message: Optional[str] = None,
    error_message: Optional[str] = None,
    load_error: bool = False,
) -> str:
    dataset_summary = service.get_dataset_summary(dataset_name)
    return render_to_string(
        "metadata/entity_creation/partials/_dataset_panel.html",
        {
            "dataset_summary": dataset_summary,
            "field_metadata": field_metadata,
            "form": form,
            "entity_uri": entity_uri,
            "success_message": success_message,
            "error_message": error_message,
            "load_error": load_error,
            "mapping": service.mapping,
        },
        request=request,
    )


class SchemaDrivenWorkspaceView(LoginRequiredMixin, View):
    template_name = "metadata/entity_creation/workspace.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        organization = getattr(request.user, "organization", None)
        if organization is None:
            return render(
                request,
                self.template_name,
                {
                    "organization_required": True,
                },
            )

        mappings = list(
            Mapping.objects.filter(organization_id=organization.code).order_by("name")
        )
        if not mappings:
            return render(
                request,
                self.template_name,
                {
                    "organization": organization,
                    "mappings": [],
                    "selected_mapping": None,
                    "dataset_summaries": [],
                    "dataset_panel_html": "",
                },
            )

        mapping_id = request.GET.get("mapping_id")
        selected_mapping = None
        if mapping_id:
            selected_mapping = next(
                (m for m in mappings if str(m.id) == mapping_id), None
            )
        if selected_mapping is None:
            selected_mapping = mappings[0]

        service = SchemaWorkspaceService(
            mapping=selected_mapping,
            organization=organization,
        )
        dataset_summaries = service.list_datasets()
        dataset_panel_html = ""
        active_dataset = request.GET.get("dataset")

        active_dataset_name = None
        if dataset_summaries:
            target_dataset = (
                active_dataset
                if active_dataset
                and any(ds.dataset_name == active_dataset for ds in dataset_summaries)
                else dataset_summaries[0].dataset_name
            )
            active_dataset_name = target_dataset
            field_metadata = service.get_field_metadata(target_dataset)
            form = DatasetEntityForm(field_metadata=field_metadata)
            dataset_panel_html = _render_dataset_panel(
                request,
                service=service,
                dataset_name=target_dataset,
                form=form,
                field_metadata=field_metadata,
            )

        return render(
            request,
            self.template_name,
            {
                "organization": organization,
                "mappings": mappings,
                "selected_mapping": selected_mapping,
                "dataset_summaries": dataset_summaries,
                "dataset_panel_html": dataset_panel_html,
                "active_dataset_name": active_dataset_name,
            },
        )


class SchemaDatasetFragmentView(LoginRequiredMixin, View):
    """
    HTMX fragment that renders or processes a dataset entity form.
    """

    def get_service(
        self, request: HttpRequest, mapping_id: str
    ) -> SchemaWorkspaceService:
        organization = getattr(request.user, "organization", None)
        if organization is None:
            raise ValueError("User does not belong to an organization")
        mapping = get_object_or_404(Mapping, id=mapping_id)
        if mapping.organization_id != organization.code:
            raise ValueError("Mapping does not belong to current organization")
        return SchemaWorkspaceService(mapping=mapping, organization=organization)

    def get(self, request: HttpRequest, mapping_id: str) -> HttpResponse:
        dataset_name = request.GET.get("dataset")
        if not dataset_name:
            return HttpResponseBadRequest("Missing dataset parameter")

        service = self.get_service(request, mapping_id)
        field_metadata = service.get_field_metadata(dataset_name)
        mode = request.GET.get("mode")
        entity_uri: Optional[str] = request.GET.get("entity_uri")
        initial_data: Optional[Dict[str, object]] = None
        load_error = False
        disable_anchors = False

        if mode == "load":
            anchor_payload = {
                key.split("anchor__", 1)[1]: value
                for key, value in request.GET.items()
                if key.startswith("anchor__") and value
            }
            try:
                loaded = service.get_initial_entity_data(dataset_name, anchor_payload)
            except ValueError:
                loaded = None
            if loaded:
                initial_data, entity_uri = loaded
                disable_anchors = True
            else:
                load_error = True

        form = DatasetEntityForm(
            field_metadata=field_metadata,
            initial=initial_data,
            disable_anchors=disable_anchors,
        )

        html = _render_dataset_panel(
            request,
            service=service,
            dataset_name=dataset_name,
            form=form,
            field_metadata=field_metadata,
            entity_uri=entity_uri,
            load_error=load_error,
        )
        return HttpResponse(html)

    def post(self, request: HttpRequest, mapping_id: str) -> HttpResponse:
        dataset_name = request.POST.get("dataset")
        if not dataset_name:
            return HttpResponseBadRequest("Missing dataset parameter")

        service = self.get_service(request, mapping_id)
        field_metadata = service.get_field_metadata(dataset_name)
        entity_uri = request.POST.get("entity_uri") or None

        form = DatasetEntityForm(
            request.POST,
            field_metadata=field_metadata,
            disable_anchors=bool(entity_uri),
        )

        if form.is_valid():
            try:
                entity_data = form.cleaned_entity_data()
                saved_uri, created = service.save_entity(
                    dataset_name, entity_data, entity_uri=entity_uri
                )
                if created:
                    success_message = f"Entity erfolgreich erstellt (<code class=\"font-mono\">{saved_uri}</code>)."
                    # Reset form for a new entry while keeping anchors blank
                    form = DatasetEntityForm(field_metadata=field_metadata)
                    entity_uri = None
                else:
                    success_message = "Änderungen gespeichert."
                    # Rehydrate form with current values to keep user context
                    initial = {key: form.cleaned_data.get(key) for key in form.fields}
                    form = DatasetEntityForm(
                        field_metadata=field_metadata,
                        initial=initial,
                        disable_anchors=True,
                    )
                    entity_uri = saved_uri

                html = _render_dataset_panel(
                    request,
                    service=service,
                    dataset_name=dataset_name,
                    form=form,
                    field_metadata=field_metadata,
                    entity_uri=entity_uri,
                    success_message=success_message,
                )
                response = HttpResponse(html)
                response["HX-Trigger"] = '{"entity-saved": {"dataset": "%s", "uri": "%s"}}' % (
                    dataset_name,
                    saved_uri,
                )
                return response
            except ValueError as exc:
                error_message = str(exc)
        else:
            error_message = "Please correct the highlighted fields."

        html = _render_dataset_panel(
            request,
            service=service,
            dataset_name=dataset_name,
            form=form,
            field_metadata=field_metadata,
            entity_uri=entity_uri,
            error_message=error_message,
        )
        return HttpResponse(html, status=400)
