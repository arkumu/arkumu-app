from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from django import forms
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views import View
from urllib.parse import urlparse, urlencode
from django.utils.text import slugify

from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.schema_workspace import (
    DatasetEntityForm,
    SchemaWorkspaceService,
    GUIDED_STEPS,
    FlowState,
    FlowEntity,
    FlowEvent,
    SchemaWorkspaceCoordinator,
)
from arkumu.metadata.schema_workspace.services import JoinRelationship
from arkumu.users.models import Organization

STEP_LABELS: Dict[str, str] = {
    "project": "Projekt",
    "events": "Ereignisse",
    "actors": "Akteure",
    "digital_objects": "Digitale Objekte",
    "summary": "Übersicht",
}

STEP_TEMPLATES: Dict[str, str] = {
    "project": "metadata/entity_creation/flow/_project_step.html",
    "events": "metadata/entity_creation/flow/_events_step.html",
    "actors": "metadata/entity_creation/flow/_actors_step.html",
    "digital_objects": "metadata/entity_creation/flow/_digital_objects_step.html",
    "summary": "metadata/entity_creation/flow/_summary_step.html",
}

PROJECT_DATASET = "Projekt"
EVENT_DATASET = "Ereignis"
ACTOR_DATASET = "Akteurin"
DIGITAL_OBJECT_DATASET = "Digitales Objekt"
DEFAULT_ORGANIZATION_CODE = "fuk"

workspace_coordinator = SchemaWorkspaceCoordinator()


def _resolve_active_organization(request: HttpRequest) -> Optional[Organization]:
    org_data = workspace_coordinator.get_current_organization(request)
    organization: Optional[Organization] = None
    if org_data:
        org_id = org_data.get("id")
        if org_id:
            organization = Organization.objects.filter(id=org_id).first()
        if organization is None:
            org_code = org_data.get("code")
            if org_code:
                organization = Organization.objects.filter(code=org_code).first()
    if organization is None:
        organization = getattr(request.user, "organization", None)
    if organization is None:
        organization = Organization.objects.filter(code=DEFAULT_ORGANIZATION_CODE).first()
    return organization


def _resolve_active_mapping(
    request: HttpRequest,
    organization: Organization,
    mapping_id: Optional[str] = None,
) -> Optional[Mapping]:
    queryset = Mapping.objects.filter(organization_id=organization.code).order_by("-created_at")
    if mapping_id:
        return queryset.filter(id=mapping_id).first()
    mapping_data = workspace_coordinator.get_current_mapping(request)
    if mapping_data:
        mapping = queryset.filter(id=mapping_data.get("id")).first()
        if mapping:
            return mapping
    return queryset.first()


def _augment_field_metadata_with_joins(
    service: SchemaWorkspaceService,
    dataset_name: str,
    field_metadata: Dict[str, Dict[str, Any]],
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, JoinRelationship]]:
    metadata = dict(field_metadata)
    join_map: Dict[str, JoinRelationship] = {}
    for relationship in service.list_join_relationships(dataset_name):
        # Hide the original foreign-key column and any direct property mapped to the same predicate
        metadata.pop(relationship.self_column, None)
        for field_name, field_meta in list(metadata.items()):
            if field_meta.get("property_uri") == relationship.self_property_uri:
                metadata.pop(field_name, None)
            elif (
                (field_meta.get("property_label") or "").strip().lower()
                == (relationship.other_display_label or "").strip().lower()
            ):
                metadata.pop(field_name, None)

        field_name = f"__join__{relationship.join_dataset}__{relationship.other_dataset}"
        join_map[field_name] = relationship
        if field_name in metadata:
            metadata[field_name]["is_join"] = True
            metadata[field_name]["join_relationship"] = relationship
            metadata[field_name]["join_other_dataset"] = relationship.other_dataset
            metadata[field_name]["property_label"] = (
                metadata[field_name].get("property_label")
                or relationship.other_display_label
            )
            continue

        metadata[field_name] = {
            "column_name": field_name,
            "column_type": "join",
            "property_label": relationship.other_display_label,
            "is_required": False,
            "is_multi_value": True,
            "is_join": True,
            "join_relationship": relationship,
            "join_other_dataset": relationship.other_dataset,
            "join_key": f"{relationship.join_dataset}::{relationship.other_dataset}",
            "help_text": f"Verknüpfte {relationship.other_display_label}",
        }

    return metadata, join_map


def _parse_join_payload(raw_value) -> List[str]:
    if raw_value in (None, "", []):
        return []

    if isinstance(raw_value, str):
        try:
            parsed = json.loads(raw_value)
        except (json.JSONDecodeError, TypeError, ValueError):
            parsed = [raw_value]
    else:
        parsed = raw_value

    uris: List[str] = []
    if isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, dict):
                uri = item.get("uri") or item.get("value")
                if uri:
                    uris.append(str(uri))
            elif isinstance(item, str):
                if item.strip():
                    uris.append(item.strip())
    elif isinstance(parsed, str):
        if parsed.strip():
            uris.append(parsed.strip())

    return uris


def _remove_join_source_fields(form: DatasetEntityForm, join_field_map: Dict[str, JoinRelationship]) -> None:
    for relationship in join_field_map.values():
        source_field = relationship.self_column
        if source_field in form.fields:
            form.fields.pop(source_field)
        if hasattr(form, "initial") and isinstance(form.initial, dict):
            form.initial.pop(source_field, None)


def _get_schema_service(request: HttpRequest, mapping_id: Optional[str] = None) -> SchemaWorkspaceService:
    organization = _resolve_active_organization(request)
    mapping: Optional[Mapping] = None

    if mapping_id:
        mapping = get_object_or_404(Mapping, id=mapping_id)
        if organization is None or mapping.organization_id != organization.code:
            organization = Organization.objects.filter(code=mapping.organization_id).first()
    else:
        if organization is None:
            raise ValueError("Keine Organisation verfügbar")
        mapping = _resolve_active_mapping(request, organization)

    if organization is None:
        raise ValueError("Keine Organisation verfügbar")
    if mapping is None:
        raise ValueError("Kein Mapping für die Organisation gefunden")

    org_id = getattr(organization, "id", None)
    if org_id is not None:
        workspace_coordinator.set_current_organization(request, org_id)
    workspace_coordinator.set_current_mapping(
        request,
        str(mapping.id),
        mapping_name=mapping.name,
        organization_id=org_id,
    )

    return SchemaWorkspaceService(mapping=mapping, organization=organization)


def _infer_entity_label(service: SchemaWorkspaceService, entity_uri: str) -> str:
    try:
        entity = Resource.objects.get(uri=entity_uri)
    except Resource.DoesNotExist:
        return entity_uri

    label_predicates = [
        "bevorzugter-titel",
        "titel",
        "title",
        "name",
        "label",
        "beschreibung",
        "description",
        "kommentar",
        "comment",
    ]

    for suffix in label_predicates:
        triple = (
            Triple.objects.filter(
                subject=entity,
                predicate__uri__iendswith=suffix,
                object__resource_type=ResourceType.LITERAL,
            )
            .select_related("object")
            .first()
        )
        if triple:
            value = triple.object.value or triple.object.literal_value or triple.object.name
            if value:
                return str(value)

    anchor = (
        Triple.objects.filter(
            subject=entity,
            object__resource_type=ResourceType.LITERAL,
        )
        .select_related("object")
        .first()
    )
    if anchor:
        value = anchor.object.value or anchor.object.literal_value or anchor.object.name
        if value:
            return f"{value} ({entity_uri.split('/')[-1]})"

    return entity_uri.split('/')[-1]


def _render_dataset_panel(
    request: HttpRequest,
    *,
    service: SchemaWorkspaceService,
    dataset_name: str,
    form: DatasetEntityForm,
    field_metadata: Dict[str, Dict[str, object]],
    entity_uri: Optional[str] = None,
    entity_label: Optional[str] = None,
    success_message: Optional[str] = None,
    error_message: Optional[str] = None,
    load_error: bool = False,
) -> str:
    dataset_summary = service.get_dataset_summary(dataset_name)

    # Pair form fields with their metadata for template access
    normal_fields: List[Dict[str, Any]] = []
    join_fields: List[Dict[str, Any]] = []
    seen_join_keys: Set[str] = set()
    base_suggestion_url = reverse(
        "metadata:entity_workspace_field_values",
        args=[service.mapping.id],
    )

    for index, field in enumerate(form):
        meta = dict(field_metadata.get(field.name, {}))
        widget = field.field.widget
        search_url = None
        target_id = None
        is_join = bool(meta.get("is_join"))

        if is_join:
            search_url = f"{base_suggestion_url}?{urlencode({'dataset': dataset_name, 'column': field.name})}"
            field.field.widget.attrs.setdefault("data-suggestion-url", search_url)

        if not isinstance(widget, forms.HiddenInput):
            has_property = bool(meta.get("property_uri"))
            has_fk = bool(meta.get("fk_relationship"))
            if has_property or has_fk or is_join:
                from django.utils.text import slugify

                target_id = f"field-suggestions-{index}-{slugify(field.name) or index}"
                params = urlencode(
                    {
                        "dataset": dataset_name,
                        "column": field.name,
                        "input_id": field.auto_id or f"id_{slugify(field.name) or index}",
                        "target_id": target_id,
                    }
                )
                search_url = f"{base_suggestion_url}?{params}"
                widget.attrs.setdefault("autocomplete", "off")
                widget.attrs["hx-get"] = search_url
                widget.attrs["hx-trigger"] = "focus, keyup changed delay:200ms"
                widget.attrs["hx-target"] = f"#{target_id}"
                widget.attrs["hx-include"] = "this"
                widget.attrs["data-suggestion-enabled"] = "true"
                widget.attrs["data-suggestion-url"] = search_url

        initial_labels: List[Dict[str, str]] = []
        if is_join:
            raw_initial = field.value()
            try:
                parsed = json.loads(raw_initial) if raw_initial else []
            except (TypeError, ValueError, json.JSONDecodeError):
                parsed = [raw_initial] if raw_initial else []
            if isinstance(parsed, list):
                for entry in parsed:
                    if isinstance(entry, dict):
                        label = entry.get("label") or entry.get("uri") or ""
                        uri = entry.get("uri") or ""
                    else:
                        label = str(entry)
                        uri = str(entry)
                    if label:
                        initial_labels.append({"label": label, "uri": uri})

        destination = join_fields if is_join else normal_fields
        if is_join:
            join_key = meta.get("join_key") or meta.get("join_relationship")
            if join_key in seen_join_keys:
                continue
            seen_join_keys.add(join_key)
        destination.append(
            {
                "field": field,
                "meta": meta,
                "search_url": search_url,
                "target_id": target_id,
                "is_join": is_join,
                "initial_labels": initial_labels,
            }
        )

    join_fields_sorted = sorted(
        join_fields,
        key=lambda item: (item["meta"].get("join_other_dataset", ""), item["field"].label.lower()),
    )

    return render_to_string(
        "metadata/entity_creation/partials/_dataset_panel.html",
        {
            "dataset_summary": dataset_summary,
            "fields_with_metadata": normal_fields,
            "join_fields": join_fields_sorted,
            "form": form,
            "entity_uri": entity_uri,
            "entity_label": entity_label,
            "success_message": success_message,
            "error_message": error_message,
            "load_error": load_error,
            "mapping": service.mapping,
        },
        request=request,
    )


def _step_is_complete(flow_state: FlowState, step: str) -> bool:
    if step == "project":
        return flow_state.project is not None
    if step == "events":
        return bool(flow_state.events)
    if step == "actors":
        return any(event.actors for event in flow_state.events.values())
    if step == "digital_objects":
        return any(event.digital_objects for event in flow_state.events.values())
    if step == "summary":
        return bool(flow_state.project) and bool(flow_state.events)
    return False


def _step_is_enabled(flow_state: FlowState, step: str) -> bool:
    if step == "project":
        return True
    if step == "events":
        return flow_state.project is not None
    if step == "actors":
        return bool(flow_state.events)
    if step == "digital_objects":
        return bool(flow_state.events)
    if step == "summary":
        return flow_state.project is not None
    return False


def _build_step_items(
    flow_state: FlowState,
    active_step: str,
    flow_url: str,
) -> List[Dict[str, object]]:
    items: List[Dict[str, object]] = []
    for step in GUIDED_STEPS:
        label = STEP_LABELS.get(step, step.title())
        enabled = _step_is_enabled(flow_state, step)
        complete = _step_is_complete(flow_state, step)
        if step == active_step:
            status = "current"
        elif complete:
            status = "complete"
        else:
            status = "upcoming"
        items.append(
            {
                "name": step,
                "label": label,
                "status": status,
                "enabled": enabled,
                "url": f"{flow_url}?flow_id={flow_state.flow_id}&step={step}",
            }
        )
    return items


def _fk_target_lookup(schema: Dict[str, object]) -> Dict[str, str]:
    lookup: Dict[str, str] = {}
    for rel in schema.get("fk_relationships", []) or []:
        source = rel.get("source_column")
        target = rel.get("target_dataset")
        if source and target:
            lookup[source] = target
    return lookup


def _configure_fk_defaults(
    form: DatasetEntityForm,
    *,
    schema: Dict[str, object],
    target_dataset: str,
    target_uri: str,
) -> None:
    for rel in schema.get("fk_relationships", []) or []:
        if rel.get("target_dataset") != target_dataset:
            continue
        field_name = rel.get("source_column")
        if not field_name or field_name not in form.fields:
            continue
        field = form.fields[field_name]
        field.initial = target_uri
        field.widget = forms.HiddenInput()


def _find_junction_dataset(
    service: SchemaWorkspaceService,
    dataset_a: str,
    dataset_b: str,
) -> Tuple[Optional[str], Optional[Dict[str, object]]]:
    candidates = service.list_datasets()
    dataset_names = [summary.dataset_name for summary in candidates]
    for dataset_name in dataset_names:
        schema = service.get_dataset_schema(dataset_name)
        junction = schema.get("junction_schema")
        if not junction:
            continue
        primary = junction.get("primary_dataset")
        secondary = junction.get("secondary_dataset")
        if {primary, secondary} == {dataset_a, dataset_b}:
            return dataset_name, schema
    return None, None


def _prepare_project_step(
    request: HttpRequest,
    *,
    service: SchemaWorkspaceService,
    flow_state: FlowState,
    mapping: Mapping,
    form: Optional[DatasetEntityForm] = None,
) -> Dict[str, object]:
    dataset_name = PROJECT_DATASET
    try:
        field_metadata = service.get_field_metadata(dataset_name)
        dataset_summary = service.get_dataset_summary(dataset_name)
    except ValueError:
        return {
            "form": None,
            "fields_with_metadata": [],
            "dataset_summary": None,
            "flow_id": flow_state.flow_id,
            "submit_url": None,
            "project_summary": flow_state.project,
            "dataset_unavailable": True,
            "missing_dataset": dataset_name,
        }
    if form is None:
        form = DatasetEntityForm(field_metadata=field_metadata)
    fields_with_metadata = []
    for field in form.visible_fields_in_order():
        fields_with_metadata.append(
            {
                "field": field,
                "meta": field_metadata.get(field.name, {}),
            }
        )
    base_url = reverse("metadata:entity_workspace_flow", args=[mapping.id])
    submit_url = f"{base_url}?step=project&flow_id={flow_state.flow_id}"
    return {
        "form": form,
        "fields_with_metadata": fields_with_metadata,
        "dataset_summary": dataset_summary,
        "flow_id": flow_state.flow_id,
        "submit_url": submit_url,
        "project_summary": flow_state.project,
    }


def _prepare_events_step(
    request: HttpRequest,
    *,
    service: SchemaWorkspaceService,
    flow_state: FlowState,
    mapping: Mapping,
    form: Optional[DatasetEntityForm] = None,
) -> Dict[str, object]:
    base_url = reverse("metadata:entity_workspace_flow", args=[mapping.id])
    dataset_name = EVENT_DATASET
    try:
        field_metadata = service.get_field_metadata(dataset_name)
        schema = service.get_dataset_schema(dataset_name)
    except ValueError:
        return {
            "flow_id": flow_state.flow_id,
            "project_summary": flow_state.project,
            "events": list(flow_state.events.values()),
            "form": None,
            "fields_with_metadata": [],
            "submit_url": f"{base_url}?step=events&flow_id={flow_state.flow_id}",
            "dataset_unavailable": True,
            "missing_dataset": dataset_name,
        }
    fk_lookup = _fk_target_lookup(schema)
    if form is None:
        form = DatasetEntityForm(field_metadata=field_metadata)
    project = flow_state.project
    if project:
        _configure_fk_defaults(
            form,
            schema=schema,
            target_dataset=project.dataset,
            target_uri=project.uri,
        )
    fields_with_metadata = []
    for field in form.visible_fields_in_order():
        fields_with_metadata.append(
            {
                "field": field,
                "meta": {
                    **field_metadata.get(field.name, {}),
                    "fk_target_dataset": fk_lookup.get(field.name),
                },
            }
        )
    return {
        "flow_id": flow_state.flow_id,
        "project_summary": flow_state.project,
        "events": list(flow_state.events.values()),
        "form": form,
        "fields_with_metadata": fields_with_metadata,
        "submit_url": f"{base_url}?step=events&flow_id={flow_state.flow_id}",
    }


def _prepare_actors_step(
    request: HttpRequest,
    *,
    service: SchemaWorkspaceService,
    flow_state: FlowState,
    mapping: Mapping,
    form: Optional[DatasetEntityForm] = None,
    selected_event_uri: Optional[str] = None,
) -> Dict[str, object]:
    base_url = reverse("metadata:entity_workspace_flow", args=[mapping.id])
    events = list(flow_state.events.values())
    if selected_event_uri is None:
        selected_event_uri = request.GET.get("event_uri") or request.POST.get("event_uri")
    selected_event = next((event for event in events if event.uri == selected_event_uri), None)
    if selected_event is None and events:
        selected_event = events[0]
        selected_event_uri = selected_event.uri

    join_dataset_name, join_schema = _find_junction_dataset(
        service, EVENT_DATASET, ACTOR_DATASET
    )

    bound_form = form
    fields_with_metadata: List[Dict[str, object]] = []
    if join_dataset_name and selected_event:
        field_metadata = service.get_field_metadata(join_dataset_name)
        if bound_form is None:
            bound_form = DatasetEntityForm(field_metadata=field_metadata)
        _configure_fk_defaults(
            bound_form,
            schema=join_schema,
            target_dataset=EVENT_DATASET,
            target_uri=selected_event.uri,
        )
        fk_lookup = _fk_target_lookup(join_schema)
        fields_with_metadata = [
            {
                "field": field,
                "meta": {
                    **field_metadata.get(field.name, {}),
                    "fk_target_dataset": fk_lookup.get(field.name),
                },
            }
            for field in bound_form.visible_fields_in_order()
        ]

    submit_url = f"{base_url}?step=actors&flow_id={flow_state.flow_id}"
    if selected_event_uri:
        submit_url = f"{submit_url}&event_uri={selected_event_uri}"

    return {
        "flow_id": flow_state.flow_id,
        "project_summary": flow_state.project,
        "events": events,
        "selected_event": selected_event,
        "join_dataset_name": join_dataset_name,
        "form": bound_form,
        "fields_with_metadata": fields_with_metadata,
        "submit_url": submit_url,
        "switch_event_url": f"{base_url}?step=actors&flow_id={flow_state.flow_id}",
    }


def _prepare_digital_objects_step(
    request: HttpRequest,
    *,
    service: SchemaWorkspaceService,
    flow_state: FlowState,
    mapping: Mapping,
    form: Optional[DatasetEntityForm] = None,
    selected_event_uri: Optional[str] = None,
) -> Dict[str, object]:
    base_url = reverse("metadata:entity_workspace_flow", args=[mapping.id])
    events = list(flow_state.events.values())
    if selected_event_uri is None:
        selected_event_uri = request.GET.get("event_uri") or request.POST.get("event_uri")
    selected_event = next((event for event in events if event.uri == selected_event_uri), None)
    if selected_event is None and events:
        selected_event = events[0]
        selected_event_uri = selected_event.uri

    join_dataset_name, join_schema = _find_junction_dataset(
        service, EVENT_DATASET, DIGITAL_OBJECT_DATASET
    )

    bound_form = form
    fields_with_metadata: List[Dict[str, object]] = []
    if join_dataset_name and selected_event:
        field_metadata = service.get_field_metadata(join_dataset_name)
        if bound_form is None:
            bound_form = DatasetEntityForm(field_metadata=field_metadata)
        _configure_fk_defaults(
            bound_form,
            schema=join_schema,
            target_dataset=EVENT_DATASET,
            target_uri=selected_event.uri,
        )
        fk_lookup = _fk_target_lookup(join_schema)
        fields_with_metadata = [
            {
                "field": field,
                "meta": {
                    **field_metadata.get(field.name, {}),
                    "fk_target_dataset": fk_lookup.get(field.name),
                },
            }
            for field in bound_form.visible_fields_in_order()
        ]

    submit_url = f"{base_url}?step=digital_objects&flow_id={flow_state.flow_id}"
    if selected_event_uri:
        submit_url = f"{submit_url}&event_uri={selected_event_uri}"

    return {
        "flow_id": flow_state.flow_id,
        "project_summary": flow_state.project,
        "events": events,
        "selected_event": selected_event,
        "join_dataset_name": join_dataset_name,
        "form": bound_form,
        "fields_with_metadata": fields_with_metadata,
        "submit_url": submit_url,
        "switch_event_url": f"{base_url}?step=digital_objects&flow_id={flow_state.flow_id}",
    }


def _prepare_summary_step(
    request: HttpRequest,
    *,
    service: SchemaWorkspaceService,
    flow_state: FlowState,
    mapping: Mapping,
) -> Dict[str, object]:
    total_actor_count = sum(len(event.actors) for event in flow_state.events.values())
    total_object_count = sum(len(event.digital_objects) for event in flow_state.events.values())
    return {
        "flow_id": flow_state.flow_id,
        "project_summary": flow_state.project,
        "events": list(flow_state.events.values()),
        "total_actor_count": total_actor_count,
        "total_object_count": total_object_count,
    }


def _derive_entity_label(form: DatasetEntityForm, fallback: str) -> str:
    for field_name in getattr(form, "anchor_fields", []):
        value = form.cleaned_data.get(field_name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for field in form.visible_fields_in_order():
        value = form.cleaned_data.get(field.name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def _render_guided_flow_panel(
    request: HttpRequest,
    *,
    service: SchemaWorkspaceService,
    mapping: Mapping,
    flow_state: FlowState,
    active_step: str,
    step_context: Optional[Dict[str, object]] = None,
    message: Optional[Dict[str, str]] = None,
) -> str:
    flow_url = reverse("metadata:entity_workspace_flow", args=[mapping.id])
    step_items = _build_step_items(flow_state, active_step, flow_url)
    step_template = STEP_TEMPLATES.get(active_step)
    return render_to_string(
        "metadata/entity_creation/partials/_guided_flow_panel.html",
        {
            "flow_state": flow_state,
            "step_items": step_items,
            "active_step": active_step,
            "step_template": step_template,
            "step_context": step_context or {},
            "message": message,
        },
        request=request,
    )


class SchemaDrivenWorkspaceView(LoginRequiredMixin, View):
    template_name = "metadata/entity_creation/workspace.html"
    coordinator = workspace_coordinator

    def get(self, request: HttpRequest) -> HttpResponse:
        organization = _resolve_active_organization(request)
        if organization is None:
            return render(
                request,
                self.template_name,
                {
                    "organization_required": True,
                },
            )

        # Auto-select latest mapping (most recent created)
        selected_mapping = Mapping.objects.filter(
            organization_id=organization.code
        ).order_by("-created_at").first()

        if not selected_mapping:
            return render(
                request,
                self.template_name,
                {
                    "organization": organization,
                    "selected_mapping": None,
                    "dataset_summaries": [],
                    "dataset_panel_html": "",
                    "active_dataset_name": None,
                    "guided_panel_html": "",
                    "mapping_required": True,
                },
            )

        org_id = getattr(organization, "id", None)
        if org_id is not None:
            self.coordinator.set_current_organization(request, org_id)

        self.coordinator.set_current_mapping(
            request,
            str(selected_mapping.id),
            mapping_name=selected_mapping.name,
            organization_id=org_id,
        )

        service = SchemaWorkspaceService(
            mapping=selected_mapping,
            organization=organization,
        )
        all_dataset_summaries = service.list_datasets()

        # Filter controlled vocabularies for non-admin users
        user_can_edit_vocabs = request.user.is_staff or (
            hasattr(request.user, 'has_role') and request.user.has_role('curator')
        )
        if not user_can_edit_vocabs:
            dataset_summaries = [
                ds for ds in all_dataset_summaries
                if not ds.is_controlled_vocab
            ]
        else:
            dataset_summaries = all_dataset_summaries

        # Separate main entities and controlled vocabularies for template
        main_entities = [ds for ds in dataset_summaries if not ds.is_controlled_vocab]
        controlled_vocabs = [ds for ds in dataset_summaries if ds.is_controlled_vocab]

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
                "selected_mapping": selected_mapping,
                "dataset_summaries": dataset_summaries,
                "main_entities": main_entities,
                "controlled_vocabs": controlled_vocabs,
                "user_can_edit_vocabs": user_can_edit_vocabs,
                "dataset_panel_html": dataset_panel_html,
                "active_dataset_name": active_dataset_name,
            },
        )


def _normalize_step(step: str) -> str:
    if step in GUIDED_STEPS:
        return step
    return "project"


class SchemaWorkspaceFlowView(LoginRequiredMixin, View):
    """
    HTMX view that powers the guided entity creation flow.
    """

    coordinator = workspace_coordinator

    def get(self, request: HttpRequest, mapping_id: str) -> HttpResponse:
        try:
            service = _get_schema_service(request, mapping_id)
        except ValueError as exc:
            return HttpResponseBadRequest(str(exc))

        mapping = service.mapping
        organization = service.organization
        org_id = getattr(organization, "id", None)
        if org_id is not None:
            self.coordinator.set_current_organization(request, org_id)
        self.coordinator.set_current_mapping(
            request,
            str(mapping.id),
            mapping_name=mapping.name,
            organization_id=org_id,
        )
        requested_step = _normalize_step(request.GET.get("step", "project"))
        flow_state = self.coordinator.get_or_create_flow_state(
            request,
            mapping=mapping,
            organization=organization,
            flow_id=request.GET.get("flow_id"),
        )

        step_context, message = self._build_step_context(
            request=request,
            service=service,
            mapping=mapping,
            flow_state=flow_state,
            step=requested_step,
        )

        html = _render_guided_flow_panel(
            request,
            service=service,
            mapping=mapping,
            flow_state=flow_state,
            active_step=requested_step,
            step_context=step_context,
            message=message,
        )
        return HttpResponse(html)

    def post(self, request: HttpRequest, mapping_id: str) -> HttpResponse:
        step = _normalize_step(request.GET.get("step") or request.POST.get("step", "project"))
        try:
            service = _get_schema_service(request, mapping_id)
        except ValueError as exc:
            return HttpResponseBadRequest(str(exc))

        mapping = service.mapping
        organization = service.organization
        org_id = getattr(organization, "id", None)
        if org_id is not None:
            self.coordinator.set_current_organization(request, org_id)
        self.coordinator.set_current_mapping(
            request,
            str(mapping.id),
            mapping_name=mapping.name,
            organization_id=org_id,
        )
        flow_state = self.coordinator.get_or_create_flow_state(
            request,
            mapping=mapping,
            organization=organization,
            flow_id=request.GET.get("flow_id") or request.POST.get("flow_id"),
        )

        if step == "project":
            return self._handle_project_post(
                request=request,
                service=service,
                mapping=mapping,
                flow_state=flow_state,
            )
        if step == "events":
            return self._handle_event_post(
                request=request,
                service=service,
                mapping=mapping,
                flow_state=flow_state,
            )
        if step == "actors":
            return self._handle_actor_post(
                request=request,
                service=service,
                mapping=mapping,
                flow_state=flow_state,
            )
        if step == "digital_objects":
            return self._handle_digital_object_post(
                request=request,
                service=service,
                mapping=mapping,
                flow_state=flow_state,
            )

        return HttpResponseBadRequest("Unsupported flow step.")

    def _build_step_context(
        self,
        *,
        request: HttpRequest,
        service: SchemaWorkspaceService,
        mapping: Mapping,
        flow_state: FlowState,
        step: str,
    ) -> Tuple[Dict[str, object], Optional[Dict[str, str]]]:
        if step == "project":
            context = _prepare_project_step(
                request,
                service=service,
                flow_state=flow_state,
                mapping=mapping,
            )
            message = None
            return context, message

        if not _step_is_enabled(flow_state, step):
            if step == "events":
                context = _prepare_events_step(
                    request,
                    service=service,
                    flow_state=flow_state,
                    mapping=mapping,
                )
                message = {
                    "level": "info",
                    "text": "Bitte lege zunächst ein Projekt an, um Ereignisse zu verknüpfen.",
                }
                return context, message
            if step == "actors":
                context = _prepare_actors_step(
                    request,
                    service=service,
                    flow_state=flow_state,
                    mapping=mapping,
                )
                message = {
                    "level": "info",
                    "text": "Füge zuerst mindestens ein Ereignis hinzu, bevor Akteur*innen zugeordnet werden.",
                }
                return context, message
            if step == "digital_objects":
                context = _prepare_digital_objects_step(
                    request,
                    service=service,
                    flow_state=flow_state,
                    mapping=mapping,
                )
                message = {
                    "level": "info",
                    "text": "Erfasse zunächst Ereignisse, um digitale Objekte zu verlinken.",
                }
                return context, message
            if step == "summary":
                context = _prepare_summary_step(
                    request,
                    service=service,
                    flow_state=flow_state,
                    mapping=mapping,
                )
                message = {
                    "level": "info",
                    "text": "Lege ein Projekt sowie mindestens ein Ereignis an, um die Übersicht zu aktivieren.",
                }
                return context, message

        if step == "events":
            return _prepare_events_step(
                request,
                service=service,
                flow_state=flow_state,
                mapping=mapping,
            ), None
        if step == "actors":
            return _prepare_actors_step(
                request,
                service=service,
                flow_state=flow_state,
                mapping=mapping,
            ), None
        if step == "digital_objects":
            return _prepare_digital_objects_step(
                request,
                service=service,
                flow_state=flow_state,
                mapping=mapping,
            ), None
        if step == "summary":
            return _prepare_summary_step(
                request,
                service=service,
                flow_state=flow_state,
                mapping=mapping,
            ), None

        return {}, None

    def _handle_event_post(
        self,
        *,
        request: HttpRequest,
        service: SchemaWorkspaceService,
        mapping: Mapping,
        flow_state: FlowState,
    ) -> HttpResponse:
        if flow_state.project is None:
            return HttpResponseBadRequest(
                "Ein Projekt muss vor dem Hinzufügen von Ereignissen erstellt werden."
            )

        organization = service.organization

        dataset_name = EVENT_DATASET
        field_metadata = service.get_field_metadata(dataset_name)
        schema = service.get_dataset_schema(dataset_name)
        form = DatasetEntityForm(
            request.POST,
            field_metadata=field_metadata,
        )
        _configure_fk_defaults(
            form,
            schema=schema,
            target_dataset=flow_state.project.dataset,
            target_uri=flow_state.project.uri,
        )

        if form.is_valid():
            try:
                entity_data = form.cleaned_entity_data()
                saved_uri, created = service.save_entity(dataset_name, entity_data)
                anchor_values = {
                    key: str(value)
                    for key, value in form.anchor_values().items()
                    if value not in (None, "")
                }
                label = _derive_entity_label(form, saved_uri)
                flow_state.events[saved_uri] = FlowEvent(
                    uri=saved_uri,
                    dataset=dataset_name,
                    label=label,
                    anchor_values=anchor_values,
                )
                self.coordinator.save_flow_state(
                    request,
                    mapping=mapping,
                    organization=organization,
                    state=flow_state,
                )

                message = {
                    "level": "success",
                    "text": "Ereignis gespeichert. Du kannst weitere Ereignisse hinzufügen oder Akteur*innen verknüpfen.",
                }
                fresh_form = DatasetEntityForm(field_metadata=field_metadata)
                _configure_fk_defaults(
                    fresh_form,
                    schema=schema,
                    target_dataset=flow_state.project.dataset,
                    target_uri=flow_state.project.uri,
                )
                step_context = _prepare_events_step(
                    request,
                    service=service,
                    flow_state=flow_state,
                    mapping=mapping,
                    form=fresh_form,
                )
                html = _render_guided_flow_panel(
                    request,
                    service=service,
                    mapping=mapping,
                    flow_state=flow_state,
                    active_step="events",
                    step_context=step_context,
                    message=message,
                )
                return HttpResponse(html)
            except ValueError as exc:
                error_message = str(exc)
        else:
            error_message = "Bitte überprüfe die Eingabefelder des Ereignisses."

        step_context = _prepare_events_step(
            request,
            service=service,
            flow_state=flow_state,
            mapping=mapping,
            form=form,
        )
        message = {
            "level": "error",
            "text": error_message,
        }
        html = _render_guided_flow_panel(
            request,
            service=service,
            mapping=mapping,
            flow_state=flow_state,
            active_step="events",
            step_context=step_context,
            message=message,
        )
        return HttpResponse(html)

    def _handle_actor_post(
        self,
        *,
        request: HttpRequest,
        service: SchemaWorkspaceService,
        mapping: Mapping,
        flow_state: FlowState,
    ) -> HttpResponse:
        organization = service.organization
        if not flow_state.events:
            return HttpResponseBadRequest("Es muss mindestens ein Ereignis vorhanden sein, um Akteur*innen zuzuordnen.")

        join_dataset_name, join_schema = _find_junction_dataset(
            service, EVENT_DATASET, ACTOR_DATASET
        )
        if not join_dataset_name:
            return HttpResponseBadRequest(
                "Das aktuelle Mapping stellt keine Verknüpfung zwischen Ereignis und Akteur bereit."
            )

        selected_event_uri = request.POST.get("event_uri")
        selected_event = None
        if selected_event_uri:
            selected_event = flow_state.events.get(selected_event_uri)
        if selected_event is None:
            # Fallback to first event
            selected_event = next(iter(flow_state.events.values()))
            selected_event_uri = selected_event.uri

        field_metadata = service.get_field_metadata(join_dataset_name)
        form = DatasetEntityForm(
            request.POST,
            field_metadata=field_metadata,
        )
        _configure_fk_defaults(
            form,
            schema=join_schema,
            target_dataset=EVENT_DATASET,
            target_uri=selected_event.uri,
        )

        actor_fk_lookup = _fk_target_lookup(join_schema)
        actor_field_name = next(
            (name for name, target in actor_fk_lookup.items() if target == ACTOR_DATASET),
            None,
        )

        if form.is_valid():
            try:
                entity_data = form.cleaned_entity_data()
                saved_uri, created = service.save_entity(join_dataset_name, entity_data)

                actor_value = None
                if actor_field_name:
                    actor_value = form.cleaned_data.get(actor_field_name)
                    if isinstance(actor_value, (list, tuple)):
                        actor_value = actor_value[0] if actor_value else None

                actor_uri = None
                if actor_value:
                    parsed = urlparse(str(actor_value))
                    if parsed.scheme and parsed.netloc:
                        actor_uri = str(actor_value)
                    else:
                        actor_uri = service._processor.resource_manager.generate_entity_uri(
                            ACTOR_DATASET, actor_value
                        )

                if actor_uri:
                    actor_entity = FlowEntity(
                        uri=actor_uri,
                        dataset=ACTOR_DATASET,
                        label=str(actor_value or actor_uri),
                        anchor_values={},
                    )
                    target_event = flow_state.events.get(selected_event.uri)
                    if target_event:
                        target_event.actors.append(actor_entity)
                        self.coordinator.save_flow_state(
                            request,
                            mapping=mapping,
                            organization=organization,
                            state=flow_state,
                        )

                message = {
                    "level": "success",
                    "text": "Akteur*in wurde mit dem Ereignis verknüpft.",
                }
                fresh_form = DatasetEntityForm(field_metadata=field_metadata)
                _configure_fk_defaults(
                    fresh_form,
                    schema=join_schema,
                    target_dataset=EVENT_DATASET,
                    target_uri=selected_event.uri,
                )
                step_context = _prepare_actors_step(
                    request,
                    service=service,
                    flow_state=flow_state,
                    mapping=mapping,
                    form=fresh_form,
                    selected_event_uri=selected_event.uri,
                )
                html = _render_guided_flow_panel(
                    request,
                    service=service,
                    mapping=mapping,
                    flow_state=flow_state,
                    active_step="actors",
                    step_context=step_context,
                    message=message,
                )
                return HttpResponse(html)
            except ValueError as exc:
                error_message = str(exc)
        else:
            error_message = "Bitte überprüfe die Angaben für die Akteur-Verknüpfung."

        step_context = _prepare_actors_step(
            request,
            service=service,
            flow_state=flow_state,
            mapping=mapping,
            form=form,
            selected_event_uri=selected_event_uri,
        )
        message = {
            "level": "error",
            "text": error_message,
        }
        html = _render_guided_flow_panel(
            request,
            service=service,
            mapping=mapping,
            flow_state=flow_state,
            active_step="actors",
            step_context=step_context,
            message=message,
        )
        return HttpResponse(html)

    def _handle_digital_object_post(
        self,
        *,
        request: HttpRequest,
        service: SchemaWorkspaceService,
        mapping: Mapping,
        flow_state: FlowState,
    ) -> HttpResponse:
        organization = service.organization
        if not flow_state.events:
            return HttpResponseBadRequest("Es muss mindestens ein Ereignis vorhanden sein, um digitale Objekte zu verknüpfen.")

        join_dataset_name, join_schema = _find_junction_dataset(
            service, EVENT_DATASET, DIGITAL_OBJECT_DATASET
        )
        if not join_dataset_name:
            return HttpResponseBadRequest(
                "Das Mapping stellt keine Verknüpfung zwischen Ereignis und digitalem Objekt bereit."
            )

        selected_event_uri = request.POST.get("event_uri")
        selected_event = None
        if selected_event_uri:
            selected_event = flow_state.events.get(selected_event_uri)
        if selected_event is None:
            selected_event = next(iter(flow_state.events.values()))
            selected_event_uri = selected_event.uri

        field_metadata = service.get_field_metadata(join_dataset_name)
        form = DatasetEntityForm(
            request.POST,
            field_metadata=field_metadata,
        )
        _configure_fk_defaults(
            form,
            schema=join_schema,
            target_dataset=EVENT_DATASET,
            target_uri=selected_event.uri,
        )

        object_fk_lookup = _fk_target_lookup(join_schema)
        object_field_name = next(
            (name for name, target in object_fk_lookup.items() if target == DIGITAL_OBJECT_DATASET),
            None,
        )

        if form.is_valid():
            try:
                entity_data = form.cleaned_entity_data()
                saved_uri, created = service.save_entity(join_dataset_name, entity_data)

                object_value = None
                if object_field_name:
                    object_value = form.cleaned_data.get(object_field_name)
                    if isinstance(object_value, (list, tuple)):
                        object_value = object_value[0] if object_value else None

                object_uri = None
                if object_value:
                    parsed = urlparse(str(object_value))
                    if parsed.scheme and parsed.netloc:
                        object_uri = str(object_value)
                    else:
                        object_uri = service._processor.resource_manager.generate_entity_uri(
                            DIGITAL_OBJECT_DATASET, object_value
                        )

                if object_uri:
                    digital_entity = FlowEntity(
                        uri=object_uri,
                        dataset=DIGITAL_OBJECT_DATASET,
                        label=str(object_value or object_uri),
                        anchor_values={},
                    )
                    target_event = flow_state.events.get(selected_event.uri)
                    if target_event:
                        target_event.digital_objects.append(digital_entity)
                        self.coordinator.save_flow_state(
                            request,
                            mapping=mapping,
                            organization=organization,
                            state=flow_state,
                        )

                message = {
                    "level": "success",
                    "text": "Digitales Objekt wurde mit dem Ereignis verknüpft.",
                }
                fresh_form = DatasetEntityForm(field_metadata=field_metadata)
                _configure_fk_defaults(
                    fresh_form,
                    schema=join_schema,
                    target_dataset=EVENT_DATASET,
                    target_uri=selected_event.uri,
                )
                step_context = _prepare_digital_objects_step(
                    request,
                    service=service,
                    flow_state=flow_state,
                    mapping=mapping,
                    form=fresh_form,
                    selected_event_uri=selected_event.uri,
                )
                html = _render_guided_flow_panel(
                    request,
                    service=service,
                    mapping=mapping,
                    flow_state=flow_state,
                    active_step="digital_objects",
                    step_context=step_context,
                    message=message,
                )
                return HttpResponse(html)
            except ValueError as exc:
                error_message = str(exc)
        else:
            error_message = "Bitte überprüfe die Angaben für die Objekt-Verknüpfung."

        step_context = _prepare_digital_objects_step(
            request,
            service=service,
            flow_state=flow_state,
            mapping=mapping,
            form=form,
            selected_event_uri=selected_event_uri,
        )
        message = {
            "level": "error",
            "text": error_message,
        }
        html = _render_guided_flow_panel(
            request,
            service=service,
            mapping=mapping,
            flow_state=flow_state,
            active_step="digital_objects",
            step_context=step_context,
            message=message,
        )
        return HttpResponse(html)

    def _handle_project_post(
        self,
        *,
        request: HttpRequest,
        service: SchemaWorkspaceService,
        mapping: Mapping,
        flow_state: FlowState,
    ) -> HttpResponse:
        organization = service.organization
        dataset_name = PROJECT_DATASET
        field_metadata = service.get_field_metadata(dataset_name)
        form = DatasetEntityForm(
            request.POST,
            field_metadata=field_metadata,
        )

        if form.is_valid():
            try:
                entity_data = form.cleaned_entity_data()
                saved_uri, created = service.save_entity(dataset_name, entity_data)
                anchor_values = {
                    key: str(value)
                    for key, value in form.anchor_values().items()
                    if value not in (None, "")
                }
                label = _derive_entity_label(form, saved_uri)
                flow_state.project = FlowEntity(
                    uri=saved_uri,
                    dataset=dataset_name,
                    label=label,
                    anchor_values=anchor_values,
                )
                flow_state.reset_after_project_change()
                self.coordinator.save_flow_state(
                    request,
                    mapping=mapping,
                    organization=organization,
                    state=flow_state,
                )

                message = {
                    "level": "success",
                    "text": "Projekt erfolgreich erstellt. Du kannst jetzt Ereignisse hinzufügen.",
                }
                step_context = _prepare_events_step(
                    request,
                    service=service,
                    flow_state=flow_state,
                    mapping=mapping,
                )
                html = _render_guided_flow_panel(
                    request,
                    service=service,
                    mapping=mapping,
                    flow_state=flow_state,
                    active_step="events",
                    step_context=step_context,
                    message=message,
                )
                return HttpResponse(html)
            except ValueError as exc:
                error_message = str(exc)
        else:
            error_message = "Bitte korrigiere die markierten Eingabefelder."

        step_context = _prepare_project_step(
            request,
            service=service,
            flow_state=flow_state,
            mapping=mapping,
            form=form,
        )
        message = {
            "level": "error",
            "text": error_message,
        }
        html = _render_guided_flow_panel(
            request,
            service=service,
            mapping=mapping,
            flow_state=flow_state,
            active_step="project",
            step_context=step_context,
            message=message,
        )
        return HttpResponse(html)


class EntitySearchView(LoginRequiredMixin, View):
    """
    HTMX endpoint that searches entities in a dataset by human-readable content.
    Returns JSON results for autocomplete dropdown.
    """

    def get(self, request: HttpRequest, mapping_id: str) -> HttpResponse:
        dataset_name = request.GET.get("dataset")
        query = request.GET.get("q", "").strip()

        if not dataset_name:
            return HttpResponseBadRequest("Missing dataset parameter")

        try:
            service = _get_schema_service(request, mapping_id)
        except ValueError as exc:
            return HttpResponseBadRequest(str(exc))

        schema = service.get_dataset_schema(dataset_name)
        dataset_resource = schema.get("dataset_resource")
        if not dataset_resource:
            dataset_resource = service._resolve_dataset_resource(dataset_name, schema)  # type: ignore[attr-defined]
        if not dataset_resource:
            return HttpResponse("[]", content_type="application/json")

        is_part_of_uri = "http://purl.org/dc/terms/isPartOf"
        dataset_entities_qs = Triple.objects.filter(
            predicate__uri=is_part_of_uri,
            object=dataset_resource,
        ).values_list("subject__uri", flat=True)

        max_results = 20

        if query:
            from django.db.models import Q

            literal_matches = Triple.objects.filter(
                subject__uri__in=dataset_entities_qs,
                object__resource_type=ResourceType.LITERAL,
            ).filter(
                Q(object__value__icontains=query)
                | Q(object__name__icontains=query)
            ).values_list("subject__uri", flat=True)

            uri_matches = dataset_entities_qs.filter(subject__uri__icontains=query)

            combined = list(uri_matches[:max_results])
            for uri in literal_matches[:max_results]:
                if uri not in combined:
                    combined.append(uri)
                    if len(combined) >= max_results:
                        break
            entity_uris = combined
        else:
            entity_uris = list(dataset_entities_qs[:max_results])

        results = []
        for uri in entity_uris:
            label = _infer_entity_label(service, uri)
            results.append(
                {
                    "uri": uri,
                    "label": label,
                    "id": uri.split("/")[-1],
                }
            )

        return HttpResponse(
            render_to_string(
                "metadata/entity_creation/partials/_entity_search_results.html",
                {
                    "results": results,
                    "dataset_name": dataset_name,
                },
                request=request
            )
        )

class DatasetFieldValueOptionsView(LoginRequiredMixin, View):
    """Return existing literal suggestions for dataset fields."""

    max_suggestions = 20

    def get(self, request: HttpRequest, mapping_id: str) -> HttpResponse:
        dataset_name = request.GET.get("dataset")
        column_name = request.GET.get("column")
        input_id = request.GET.get("input_id")
        target_id = request.GET.get("target_id")

        if not dataset_name or not column_name or not input_id or not target_id:
            return HttpResponseBadRequest("Missing required parameters")

        try:
            service = _get_schema_service(request, mapping_id)
        except ValueError as exc:
            return HttpResponseBadRequest(str(exc))

        field_metadata = service.get_field_metadata(dataset_name)
        field_metadata, join_field_map = _augment_field_metadata_with_joins(
            service,
            dataset_name,
            field_metadata,
        )
        field_meta = field_metadata.get(column_name)
        if not field_meta:
            return HttpResponseBadRequest("Unknown field")

        column_alias = f"{column_name}[]"
        query = (
            request.GET.get("q")
            or request.GET.get(column_name)
            or request.GET.get(column_alias)
            or ""
        ).strip()

        fk_info = field_meta.get("fk_relationship")
        if field_meta.get("is_join"):
            relationship = join_field_map.get(column_name)
            suggestions = self._collect_join_entity_suggestions(service, relationship, query)
        elif fk_info:
            suggestions = self._collect_fk_suggestions(service, fk_info, query)
        else:
            suggestions = self._collect_property_suggestions(
                service,
                field_meta.get("property_uri"),
                query,
            )

        context = {
            "suggestions": suggestions[: self.max_suggestions],
            "input_id": input_id,
            "target_id": target_id,
        }
        return render(
            request,
            "metadata/entity_creation/partials/_dataset_field_suggestions.html",
            context,
        )

    def _collect_fk_suggestions(
        self,
        service: SchemaWorkspaceService,
        fk_info: Dict[str, Any],
        query: str,
    ) -> List[Dict[str, str]]:
        target_dataset = fk_info.get("target_dataset")
        target_column = fk_info.get("target_column")
        if not target_dataset or not target_column:
            return []

        target_schema = service.get_dataset_schema(target_dataset)
        property_resource = target_schema.get("properties", {}).get(target_column)
        property_uri = getattr(property_resource, "uri", None)
        return self._collect_property_suggestions(service, property_uri, query)

    def _collect_property_suggestions(
        self,
        service: SchemaWorkspaceService,
        property_uri: Optional[str],
        query: str,
        ) -> List[Dict[str, str]]:
        if not property_uri:
            return []

        predicate = Resource.objects.filter(uri=property_uri).first()
        if predicate is None:
            return []

        organization = getattr(service, "organization", None)
        qs = Triple.objects.filter(
            predicate=predicate,
            object__resource_type=ResourceType.LITERAL,
        ).select_related("object")

        if organization is not None:
            qs = qs.filter(source=organization)

        if query:
            from django.db.models import Q

            qs = qs.filter(
                Q(object__value__icontains=query)
                | Q(object__name__icontains=query)
            )

        qs = qs.order_by("object__value", "object__name")

        seen: set[str] = set()
        suggestions: List[Dict[str, str]] = []
        for triple in qs[: 5 * self.max_suggestions]:
            literal = triple.object.value or triple.object.name
            if not literal:
                continue
            key = literal.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            suggestions.append({
                "value": literal,
                "label": literal,
            })
            if len(suggestions) >= self.max_suggestions:
                break

        return suggestions

    def _collect_join_entity_suggestions(
        self,
        service: SchemaWorkspaceService,
        relationship: Optional[JoinRelationship],
        query: str,
    ) -> List[Dict[str, str]]:
        if relationship is None:
            return []

        schema = service.get_dataset_schema(relationship.other_dataset)
        dataset_resource = service._resolve_dataset_resource(relationship.other_dataset, schema)  # type: ignore[attr-defined]
        if not dataset_resource:
            return []

        is_part_of_uri = "http://purl.org/dc/terms/isPartOf"
        entities_qs = Triple.objects.filter(
            predicate__uri=is_part_of_uri,
            object=dataset_resource,
        ).values_list("subject__uri", flat=True)

        if query:
            from django.db.models import Q

            literal_matches = Triple.objects.filter(
                subject__uri__in=entities_qs,
                object__resource_type=ResourceType.LITERAL,
            ).filter(
                Q(object__value__icontains=query)
                | Q(object__name__icontains=query)
            ).values_list("subject__uri", flat=True)

            uri_matches = entities_qs.filter(subject__uri__icontains=query)

            uris = list(uri_matches[:20])
            for uri in literal_matches[:20]:
                if uri not in uris:
                    uris.append(uri)
                    if len(uris) >= 20:
                        break
        else:
            uris = list(entities_qs[:20])

        results: List[Dict[str, str]] = []
        for uri in uris:
            label = _infer_entity_label(service, uri)
            results.append({"value": uri, "label": label})
        return results


class SchemaDatasetFragmentView(LoginRequiredMixin, View):
    """
    HTMX fragment that renders or processes a dataset entity form.
    """

    def get_service(
        self, request: HttpRequest, mapping_id: str
    ) -> SchemaWorkspaceService:
        return _get_schema_service(request, mapping_id)

    def get(self, request: HttpRequest, mapping_id: str) -> HttpResponse:
        dataset_name = request.GET.get("dataset")
        if not dataset_name:
            return HttpResponseBadRequest("Missing dataset parameter")

        service = self.get_service(request, mapping_id)
        field_metadata = service.get_field_metadata(dataset_name)
        field_metadata, join_field_map = _augment_field_metadata_with_joins(
            service,
            dataset_name,
            field_metadata,
        )
        mode = request.GET.get("mode")
        entity_uri: Optional[str] = request.GET.get("entity_uri")
        entity_label: Optional[str] = request.GET.get("entity_label")
        initial_data: Optional[Dict[str, object]] = None
        load_error = False
        disable_anchors = False

        if mode == "load":
            # Load by entity_uri if provided directly
            if entity_uri:
                try:
                    loaded = service.load_entity_by_uri(dataset_name, entity_uri)
                    if loaded:
                        initial_data = loaded
                        disable_anchors = True
                        if not entity_label:
                            entity_label = _infer_entity_label(service, entity_uri)
                    else:
                        load_error = True
                except ValueError:
                    load_error = True
            else:
                # Fall back to anchor-based loading (legacy)
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
                    if entity_uri and not entity_label:
                        entity_label = _infer_entity_label(service, entity_uri)
                else:
                    load_error = True

        form = DatasetEntityForm(
            field_metadata=field_metadata,
            initial=initial_data,
            disable_anchors=disable_anchors,
        )
        _remove_join_source_fields(form, join_field_map)

        if entity_uri:
            for field_name, relationship in join_field_map.items():
                join_values = service.get_join_values(relationship, entity_uri)
                if not join_values:
                    form.initial[field_name] = json.dumps([])
                    continue
                labelled = [
                    {
                        "uri": uri,
                        "label": _infer_entity_label(service, uri),
                    }
                    for uri in join_values
                ]
                form.initial[field_name] = json.dumps(labelled)
                # Ensure entity label for info banner if missing
                if not entity_label:
                    entity_label = _infer_entity_label(service, entity_uri)

        html = _render_dataset_panel(
            request,
            service=service,
            dataset_name=dataset_name,
            form=form,
            field_metadata=field_metadata,
            entity_uri=entity_uri,
            entity_label=entity_label,
            load_error=load_error,
        )
        return HttpResponse(html)

    def post(self, request: HttpRequest, mapping_id: str) -> HttpResponse:
        dataset_name = request.POST.get("dataset")
        if not dataset_name:
            return HttpResponseBadRequest("Missing dataset parameter")

        service = self.get_service(request, mapping_id)
        field_metadata = service.get_field_metadata(dataset_name)
        field_metadata, join_field_map = _augment_field_metadata_with_joins(
            service,
            dataset_name,
            field_metadata,
        )
        entity_uri = request.POST.get("entity_uri") or None

        form = DatasetEntityForm(
            request.POST,
            field_metadata=field_metadata,
            disable_anchors=bool(entity_uri),
        )
        _remove_join_source_fields(form, join_field_map)

        if form.is_valid():
            try:
                entity_data = form.cleaned_entity_data()
                join_payloads: Dict[str, List[str]] = {}
                for field_name, relationship in join_field_map.items():
                    raw = entity_data.pop(field_name, None)
                    join_payloads[field_name] = _parse_join_payload(raw)
                saved_uri, created = service.save_entity(
                    dataset_name, entity_data, entity_uri=entity_uri
                )
                entity_label = _infer_entity_label(service, saved_uri)

                for field_name, values in join_payloads.items():
                    relationship = join_field_map[field_name]
                    service.sync_join_relationship(
                        entity_uri=saved_uri,
                        relationship=relationship,
                        related_uris=values,
                    )

                if created:
                    success_message = f"Entity erfolgreich erstellt (<code class=\"font-mono\">{saved_uri}</code>)."
                    # Reset form for a new entry while keeping anchors blank
                    form = DatasetEntityForm(field_metadata=field_metadata)
                    entity_uri = None
                    entity_label = None
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

                if entity_uri:
                    for field_name, relationship in join_field_map.items():
                        join_values = service.get_join_values(relationship, entity_uri)
                        labelled = [
                            {
                                "uri": uri,
                                "label": _infer_entity_label(service, uri),
                            }
                            for uri in join_values
                        ]
                        form.initial[field_name] = json.dumps(labelled)

                html = _render_dataset_panel(
                    request,
                    service=service,
                    dataset_name=dataset_name,
                    form=form,
                    field_metadata=field_metadata,
                    entity_uri=entity_uri,
                    entity_label=entity_label,
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
            entity_label=_infer_entity_label(service, entity_uri) if entity_uri else None,
            error_message=error_message,
        )
        return HttpResponse(html, status=400)
