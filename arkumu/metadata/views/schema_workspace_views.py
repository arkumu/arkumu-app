from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple, Set

from django import forms
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views import View
from urllib.parse import urlparse, urlencode
from django.utils.text import slugify

logger = logging.getLogger(__name__)

from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.models.resource import Resource, ResourceType, PublicAccessLevel
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
from arkumu.metadata.schema_workspace.services import JoinRelationship, RelationshipValues
from arkumu.metadata.utils.uri_placeholders import decode_placeholder_uri
from arkumu.metadata.views.csv_mapping.mixins.template_helpers import CSVMappingTemplateHelperMixin
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
            workspace_coordinator.clear_current_organization(request)

    if organization is not None:
        return organization

    user_organization = getattr(request.user, "organization", None)
    if user_organization is not None:
        workspace_coordinator.set_current_organization(request, user_organization.id)
        return user_organization

    fallback = Organization.objects.filter(code=DEFAULT_ORGANIZATION_CODE).first()
    if fallback is not None:
        workspace_coordinator.set_current_organization(request, fallback.id)
    return fallback


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
    seen: Set[str] = set()
    if isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, dict):
                uri = item.get("uri") or item.get("value")
                if uri:
                    canonical, _ = decode_placeholder_uri(str(uri))
                    if canonical and canonical not in seen:
                        uris.append(canonical)
                        seen.add(canonical)
            elif isinstance(item, str):
                cleaned = item.strip()
                if not cleaned:
                    continue
                canonical, _ = decode_placeholder_uri(cleaned)
                if canonical and canonical not in seen:
                    uris.append(canonical)
                    seen.add(canonical)
    elif isinstance(parsed, str):
        cleaned = parsed.strip()
        if cleaned:
            canonical, _ = decode_placeholder_uri(cleaned)
            if canonical:
                uris.append(canonical)

    return uris


def _build_selected_items(field_name: str, value_items: Iterable[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    Convert normalized value dictionaries into chip metadata used by the multi-select widget.
    Each value dict should provide at least a URI or label and may include a resource_id.
    """
    import uuid

    selected: List[Dict[str, str]] = []
    seen: Set[str] = set()

    for item in value_items:
        if not isinstance(item, dict):
            continue
        uri = str(item.get("uri") or "").strip()
        label = str(item.get("label") or uri).strip()
        resource_id = item.get("resource_id")

        if not uri and not label:
            continue

        dedupe_key = uri or label
        if dedupe_key and dedupe_key in seen:
            continue
        if dedupe_key:
            seen.add(dedupe_key)

        suffix = uuid.uuid4().hex[:8]
        chip_id = f"relationship-chip-{field_name}-{suffix}"
        selected.append(
            {
                "chip_id": chip_id,
                "hidden_input_id": f"{chip_id}-hidden",
                "uri": uri,
                "label": label or uri,
                "resource_id": str(resource_id) if resource_id else "",
            }
        )

    return selected


def _build_relationship_widget_context(
    *,
    service: SchemaWorkspaceService,
    dataset_name: str,
    field_name: str,
    field_meta: Dict[str, Any],
    selected_value_items: Iterable[Dict[str, Any]],
    selected_property: str,
) -> Dict[str, Any]:
    """
    Assemble template context for the reusable HTMX multi-select widget.
    """
    search_properties = field_meta.get("search_properties") or []
    field_meta["search_properties"] = search_properties

    suggestion_url = "{}?{}".format(
        reverse("metadata:entity_workspace_field_values", args=[service.mapping.id]),
        urlencode({"dataset": dataset_name, "column": field_name}),
    )

    rows_url = "{}?{}".format(
        reverse("metadata:entity_workspace_relationship_rows", args=[service.mapping.id]),
        urlencode({"dataset": dataset_name, "field_name": field_name}),
    )

    wrapper_id = f"multi-select-wrapper-{field_name}"
    search_input_id = f"multi-select-search-{field_name}"
    suggestions_id = f"multi-select-suggestions-{field_name}"
    chip_container_id = f"multi-select-chips-{field_name}"
    property_select_id = f"relationship-property-{field_name}"
    property_input_name = f"relationship_property_{field_name}"

    selected_items = _build_selected_items(field_name, selected_value_items)

    return {
        "field_name": field_name,
        "mapping_id": str(service.mapping.id),
        "dataset_name": dataset_name,
        "search_properties": search_properties,
        "selected_property": selected_property,
        "property_select_id": property_select_id,
        "property_input_name": property_input_name,
        "wrapper_id": wrapper_id,
        "search_input_id": search_input_id,
        "suggestions_id": suggestions_id,
        "chip_container_id": chip_container_id,
        "rows_url": rows_url,
        "suggestion_url": suggestion_url,
        "selected_items": selected_items,
    }


def _remove_join_source_fields(form: DatasetEntityForm, join_field_map: Dict[str, JoinRelationship]) -> None:
    for relationship in join_field_map.values():
        source_field = relationship.self_column
        if source_field in form.fields:
            form.fields.pop(source_field)
        if hasattr(form, "initial") and isinstance(form.initial, dict):
            form.initial.pop(source_field, None)


def _apply_relationship_initials(
    *,
    service: SchemaWorkspaceService,
    form: DatasetEntityForm,
    relationships: List[RelationshipValues],
    mutate_form: bool = True,
) -> List[Dict[str, Any]]:
    read_only: List[Dict[str, Any]] = []

    logger.info(f"[_apply_relationship_initials] Processing {len(relationships)} relationships, mutate_form={mutate_form}")
    for relationship in relationships:
        logger.info(f"[_apply_relationship_initials] Relationship: field={relationship.field_name}, editable={relationship.editable}, uris={len(relationship.uris)}")
        labelled = []
        for uri in relationship.uris:
            item = {
                "uri": uri,
                "label": _infer_entity_label(
                    service,
                    uri,
                    relationship.target_dataset,
                ),
            }
            # Add resource ID for graph view navigation
            resource = Resource.objects.filter(uri=uri).first()
            if resource:
                item["resource_id"] = str(resource.id)
            labelled.append(item)

        if relationship.editable:
            if mutate_form:
                field = form.fields.get(relationship.field_name)
                if field is not None and isinstance(field.widget, forms.HiddenInput):
                    payload = json.dumps(labelled)
                    logger.info(f"[_apply_relationship_initials] Setting initial for '{relationship.field_name}': {len(labelled)} items")
                    form.initial[relationship.field_name] = payload
                    field.initial = payload
                else:
                    logger.warning(f"[_apply_relationship_initials] Field '{relationship.field_name}' not found or not HiddenInput")
        else:
            read_only.append(
                {
                    "label": relationship.display_label,
                    "items": labelled,
                }
            )
            continue

        if mutate_form:
            field = form.fields.get(relationship.field_name)
            if field is not None and isinstance(field.widget, forms.HiddenInput):
                payload = json.dumps(labelled)
                form.initial[relationship.field_name] = payload
                field.initial = payload

    return read_only


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


def _infer_entity_label(
    service: SchemaWorkspaceService,
    entity_uri: str,
    target_dataset: Optional[str] = None,
    include_rich_context: bool = False,
    display_property_uri: Optional[str] = None,
) -> str:
    logger.debug(f"[_infer_entity_label] Called with entity_uri={entity_uri}, target_dataset={target_dataset}, display_property_uri={display_property_uri}")

    # Handle malformed URIs from old data (pattern: uri-{uri}-label-{label})
    uri_tail = entity_uri.split("/")[-1]
    if uri_tail.startswith("uri-") and "-label-" in uri_tail:
        # Extract the actual label from the malformed pattern
        # Pattern: uri-http-arkumu-org-data-fuk-entities-ereignis-1-label-1
        # Extract: 1
        parts = uri_tail.split("-label-")
        if len(parts) == 2:
            actual_label = parts[1]
            logger.info(f"[_infer_entity_label] Extracted label from malformed URI: {actual_label} (from {uri_tail})")
            return actual_label

    try:
        entity = Resource.objects.get(uri=entity_uri)
    except Resource.DoesNotExist:
        logger.warning(f"[_infer_entity_label] Resource not found for URI: {entity_uri}")
        return uri_tail

    # Detect and resolve through join/junction tables
    # Join tables typically have "Kreuz" (cross) in their dataset name or multiple FK relationships
    if target_dataset and ("kreuz" in target_dataset.lower() or "junction" in target_dataset.lower()):
        logger.debug(f"[_infer_entity_label] Detected join table: {target_dataset}, attempting to resolve through it")

        # Find FK relationships from this join entity (excluding the one pointing back to current context)
        related_entities = Triple.objects.filter(
            subject=entity,
            object__resource_type=ResourceType.ENTITY,
        ).exclude(
            predicate__uri__icontains="ispartof"
        ).select_related('predicate', 'object')[:5]

        # Try to find a good label from one of the related entities
        # Prioritize certain entity types: Events > Actors/Persons > Digital Objects
        candidates_by_priority = []

        for rel_triple in related_entities:
            related_uri = rel_triple.object.uri
            related_name = rel_triple.object.name or ""
            pred_uri = rel_triple.predicate.uri if rel_triple.predicate else ""

            # Skip if this looks like it points back to a project/werk (the source we came from)
            if "projekt" in pred_uri.lower() or "werk" in pred_uri.lower():
                continue

            # Determine priority based on entity type in URI
            priority = 3  # Default low priority
            if "ereignis" in related_uri.lower() or "event" in related_uri.lower():
                priority = 1  # High priority for events
            elif "akteur" in related_uri.lower() or "person" in related_uri.lower() or "koerperschaft" in related_uri.lower():
                priority = 2  # Medium priority for actors/persons/organizations
            elif "digital" in related_uri.lower() or "objekt" in related_uri.lower():
                priority = 4  # Low priority for digital objects

            # Try to infer dataset name from the related entity's URI
            # Pattern: http://arkumu.org/data/hmt/entities/02-hfm-ereignis/319
            uri_parts = related_uri.split("/entities/")
            if len(uri_parts) == 2:
                dataset_part = uri_parts[1].split("/")[0]  # e.g., "02-hfm-ereignis"
                # Convert to dataset name format: "02_hfm_Ereignis"
                inferred_dataset = dataset_part.replace("-", "_")
                # Capitalize first letter of last part
                parts = inferred_dataset.rsplit("_", 1)
                if len(parts) == 2:
                    inferred_dataset = f"{parts[0]}_{parts[1].capitalize()}"

                candidates_by_priority.append((priority, related_uri, inferred_dataset, related_name))

        # Sort by priority and try each candidate
        candidates_by_priority.sort(key=lambda x: x[0])
        for priority, related_uri, inferred_dataset, related_name in candidates_by_priority:
            logger.debug(f"[_infer_entity_label] Resolving through join table to {related_uri} (priority {priority}, inferred dataset: {inferred_dataset})")

            # Recursively get label for the related entity
            related_label = _infer_entity_label(service, related_uri, inferred_dataset)

            # If we got a good label (not just a number/ID), use it
            if related_label and not related_label.isdigit() and related_label != related_name:
                logger.info(f"[_infer_entity_label] Resolved join entity {entity_uri} -> {related_label} (priority {priority})")
                return related_label

    # If specific display property requested, fetch that first
    if display_property_uri:
        try:
            prop_resource = Resource.objects.get(uri=display_property_uri)
            triple = (
                Triple.objects.filter(
                    subject=entity,
                    predicate=prop_resource,
                    object__resource_type=ResourceType.LITERAL,
                )
                .select_related("object")
                .first()
            )
            if triple:
                value = triple.object.value or triple.object.literal_value or triple.object.name
                if value:
                    logger.debug(f"[_infer_entity_label] Found value via display_property_uri: {value}")
                    return str(value)
        except Resource.DoesNotExist:
            logger.warning(f"[_infer_entity_label] Display property resource not found: {display_property_uri}")

    if target_dataset:
        try:
            target_schema = service.get_dataset_schema(target_dataset)
        except ValueError:
            target_schema = None
        if target_schema:
            properties = target_schema.get("properties", {}) or {}
            anchor_columns = [
                col.get("column_name")
                for col in target_schema.get("anchor_columns", [])
                if col.get("column_name")
            ]
            candidate_columns = anchor_columns or list(properties.keys())
            for column in candidate_columns:
                prop_resource = properties.get(column)
                if not prop_resource:
                    continue
                triple = (
                    Triple.objects.filter(
                        subject=entity,
                        predicate=prop_resource,
                        object__resource_type=ResourceType.LITERAL,
                    )
                    .select_related("object")
                    .first()
                )
                if triple:
                    value = (
                        triple.object.value
                        or triple.object.literal_value
                        or triple.object.name
                    )
                    if value:
                        # Skip anchor columns that are just numeric IDs - continue to smarter pattern matching
                        value_str = str(value).strip()
                        if not value_str.isdigit():
                            logger.debug(f"[_infer_entity_label] Found label via anchor column '{column}': {value_str}")
                            return value_str
                        else:
                            logger.debug(f"[_infer_entity_label] Skipping numeric anchor column '{column}': {value_str}")

    # Try exact suffix matches first (most specific)
    label_predicates_exact = [
        "bevorzugter-titel",
        "bevorzugtertitel",
        "titel",
        "title",
        "name",
        "label",
    ]

    for suffix in label_predicates_exact:
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
                logger.debug(f"[_infer_entity_label] Found label via exact suffix '{suffix}': {value}")
                return str(value)

    # Try "contains" matches for common patterns (e.g., "Ereignis_DeutscherName" contains "Name")
    label_patterns_contains = [
        ("titel", 1),  # Priority 1 (highest)
        ("title", 1),
        ("name", 2),   # Priority 2
        ("label", 2),
        ("beschreibung", 3),  # Priority 3
        ("description", 3),
        ("kommentar", 4),  # Priority 4 (lowest)
        ("comment", 4),
    ]

    # Collect all matching triples with their priority
    candidates = []
    for pattern, priority in label_patterns_contains:
        triples = Triple.objects.filter(
            subject=entity,
            predicate__uri__icontains=pattern,
            object__resource_type=ResourceType.LITERAL,
        ).select_related("object", "predicate")[:5]

        for triple in triples:
            value = triple.object.value or triple.object.literal_value or triple.object.name
            if value and str(value).strip():
                # Skip if it's just a number or ID
                if not str(value).strip().isdigit():
                    candidates.append((priority, triple, str(value)))

    # Return the highest priority candidate
    if candidates:
        candidates.sort(key=lambda x: x[0])  # Sort by priority (lowest number = highest priority)
        _, best_triple, best_value = candidates[0]
        pred_name = best_triple.predicate.name if best_triple.predicate else "unknown"
        logger.debug(f"[_infer_entity_label] Found label via pattern match (predicate: {pred_name}): {best_value}")
        return best_value

    if entity.name and entity.name != entity_uri:
        tail = entity_uri.split("/")[-1]
        if entity.name != tail:
            return entity.name

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
            if include_rich_context:
                # Include ID for context: "Deutsch (110)"
                final_label = f"{value} ({entity_uri.split('/')[-1]})"
            else:
                final_label = str(value)
            logger.debug(f"[_infer_entity_label] Returning anchor-based label: {final_label}")
            return final_label

    final_label = entity_uri.split('/')[-1]
    logger.info(f"[_infer_entity_label] No good label found, returning URI tail: {final_label} for {entity_uri}")
    return final_label


def _build_project_access_context(
    *,
    service: SchemaWorkspaceService,
    dataset_summary: Any,
    dataset_name: str,
    entity_uri: Optional[str],
    message: Optional[str] = None,
) -> Dict[str, Any]:
    slug = slugify(dataset_name).lower()
    if slug not in {"projekt", "project"}:
        return {
            "project_access_enabled": False,
        }

    choices = [
        {"value": value, "label": label}
        for value, label in PublicAccessLevel.choices
    ]

    resource: Optional[Resource] = None
    if entity_uri:
        resource = Resource.objects.filter(uri=entity_uri).first()

    current_level_enum = PublicAccessLevel.PRIVATE
    if resource and resource.public_access_level:
        current_level_enum = PublicAccessLevel(resource.public_access_level)

    choice_map = dict(PublicAccessLevel.choices)
    current_display = choice_map.get(current_level_enum.value, current_level_enum.label)

    disabled = resource is None or not entity_uri

    context: Dict[str, Any] = {
        "project_access_enabled": True,
        "project_access_choices": choices,
        "current_access_level": current_level_enum.value,
        "current_access_display": current_display,
        "project_access_disabled": disabled,
        "project_access_public_approved": bool(resource and resource.is_public_approved),
        "project_access_message": message or "",
    }
    return context


def _render_dataset_panel(
    request: HttpRequest,
    *,
    service: SchemaWorkspaceService,
    dataset_name: str,
    form: DatasetEntityForm,
    field_metadata: Dict[str, Dict[str, object]],
    join_field_map: Optional[Dict[str, JoinRelationship]] = None,
    entity_uri: Optional[str] = None,
    entity_label: Optional[str] = None,
    success_message: Optional[str] = None,
    error_message: Optional[str] = None,
    load_error: bool = False,
    read_only_relationships: Optional[List[Dict[str, Any]]] = None,
) -> str:
    dataset_summary = service.get_dataset_summary(dataset_name)
    project_access_context = _build_project_access_context(
        service=service,
        dataset_summary=dataset_summary,
        dataset_name=dataset_name,
        entity_uri=entity_uri,
    )
    join_field_map = join_field_map or {}
    target_property_cache: Dict[str, List[Dict[str, str]]] = {}

    selected_property = (
        request.GET.get("property")
        or request.POST.get("property")
        or None
    )

    search_properties: List[Dict[str, str]] = []
    seen_property_uris: Set[str] = set()
    for meta in field_metadata.values():
        if meta.get("is_join"):
            continue
        property_uri = meta.get("property_uri")
        if not property_uri:
            continue
        uri_str = str(property_uri)
        if not uri_str or uri_str in seen_property_uris:
            continue
        label = str(meta.get("property_label") or meta.get("column_name") or uri_str)
        search_properties.append({"uri": uri_str, "label": label})
        seen_property_uris.add(uri_str)

    search_properties.sort(key=lambda item: item["label"].lower())

    # Pair form fields with their metadata for template access
    normal_fields: List[Dict[str, Any]] = []
    relationship_fields: List[Dict[str, Any]] = []
    seen_relationship_keys: Set[str] = set()
    base_suggestion_url = reverse(
        "metadata:entity_workspace_field_values",
        args=[service.mapping.id],
    )

    for index, field in enumerate(form):
        meta = dict(field_metadata.get(field.name, {}))
        widget = field.field.widget
        search_url: Optional[str] = None
        target_id: Optional[str] = None
        is_join = bool(meta.get("is_join"))
        fk_info = meta.get("fk_relationship") or {}
        is_multi_fk = bool(fk_info and meta.get("is_multi_value"))
        is_relationship = is_join or is_multi_fk
        target_dataset: Optional[str] = None
        relationship = None

        if is_join:
            relationship = join_field_map.get(field.name)
            if relationship:
                target_dataset = relationship.other_dataset
        elif fk_info:
            target_dataset = fk_info.get("target_dataset")

        if target_dataset:
            if target_dataset not in target_property_cache:
                try:
                    target_schema = service.get_dataset_schema(target_dataset)
                except ValueError:
                    target_property_cache[target_dataset] = []
                else:
                    properties: List[Dict[str, str]] = []
                    for column, prop in (target_schema.get("properties", {}) or {}).items():
                        uri = getattr(prop, "uri", None)
                        if not uri:
                            continue
                        label = getattr(prop, "name", column) or column
                        properties.append({"uri": uri, "label": label, "column": column})
                    properties.sort(key=lambda item: item["label"].lower())
                    target_property_cache[target_dataset] = properties
            meta["search_properties"] = target_property_cache[target_dataset]
            meta["target_dataset"] = target_dataset

            # Auto-select best display property for single FK fields
            if fk_info and not meta.get("is_multi_value"):
                preferred_names = ["name", "titel", "title", "label", "bezeichnung", "beschreibung"]
                meta["display_property"] = None
                for prop in target_property_cache[target_dataset]:
                    prop_name_lower = prop.get("column", "").lower()
                    if any(pref in prop_name_lower for pref in preferred_names):
                        meta["display_property"] = prop.get("uri")
                        meta["display_property_label"] = prop.get("label")
                        break

        base_params = {"dataset": dataset_name, "column": field.name}
        base_url = f"{base_suggestion_url}?{urlencode(base_params)}"
        meta["base_suggestion_url"] = base_url
        field.field.widget.attrs.setdefault("data-base-suggestion-url", base_url)
        field.field.widget.attrs.setdefault("data-suggestion-url", base_url)
        if is_join or is_multi_fk:
            field.field.widget.attrs.setdefault("data-suggestion-enabled", "true")

        # Add property resource ID for graph view navigation
        property_uri = meta.get("property_uri")
        if property_uri:
            property_resource = Resource.objects.filter(uri=property_uri).first()
            if property_resource:
                meta["property_resource_id"] = str(property_resource.id)

        if not isinstance(widget, forms.HiddenInput):
            has_property = bool(meta.get("property_uri"))
            has_fk = bool(meta.get("fk_relationship"))
            if has_property or has_fk or is_join:
                from django.utils.text import slugify

                target_id = f"field-suggestions-{index}-{slugify(field.name) or index}"
                input_id = field.auto_id or f"id_{slugify(field.name) or index}"
                meta["input_id"] = input_id
                query_params = {"input_id": input_id, "target_id": target_id}
                selected_property = meta.get("selected_property") or ""
                if selected_property:
                    query_params["property"] = selected_property
                search_url = base_url + "&" + urlencode(query_params)
                widget.attrs.setdefault("autocomplete", "off")
                widget.attrs["hx-get"] = search_url
                widget.attrs["hx-trigger"] = "focus, keyup changed delay:200ms"
                widget.attrs["hx-target"] = f"#{target_id}"
                widget.attrs["hx-include"] = "this"
                widget.attrs["data-suggestion-enabled"] = "true"
                widget.attrs["data-suggestion-url"] = base_url
                widget.attrs["data-base-suggestion-url"] = base_url
                widget.attrs["data-target-id"] = target_id
                widget.attrs["data-input-id"] = input_id
                if meta.get("search_properties"):
                    select_id = f"field-property-{index}-{slugify(field.name) or index}"
                    meta["search_select_id"] = select_id
                    widget.attrs.setdefault("data-property-select", select_id)
                meta["target_id"] = target_id
            else:
                meta["target_id"] = None
        else:
            meta["target_id"] = None

        if is_join or is_multi_fk:
            meta["container_id"] = f"multi-value-{field.name}"
        else:
            meta["container_id"] = ""

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
                        label_entry = {"label": label, "uri": uri}
                        # Add resource ID for graph view navigation
                        if uri:
                            target_resource = Resource.objects.filter(uri=uri).first()
                            if target_resource:
                                label_entry["resource_id"] = str(target_resource.id)
                        initial_labels.append(label_entry)
            if initial_labels:
                labelled_json = json.dumps(initial_labels)
                form.initial[field.name] = labelled_json
                field.form.initial[field.name] = labelled_json
        elif meta.get("fk_relationship") and meta.get("is_multi_value"):
            raw_initial = form.initial.get(field.name, field.value())
            parsed_values: List[Any]
            if isinstance(raw_initial, str) and raw_initial:
                try:
                    loaded = json.loads(raw_initial)
                    parsed_values = loaded if isinstance(loaded, list) else [raw_initial]
                except (TypeError, ValueError, json.JSONDecodeError):
                    parsed_values = [raw_initial]
            elif isinstance(raw_initial, list):
                parsed_values = raw_initial
            else:
                parsed_values = []

            normalized: List[Dict[str, str]] = []
            for entry in parsed_values:
                if isinstance(entry, dict):
                    uri = (entry.get("uri") or entry.get("value") or "").strip()
                else:
                    uri = str(entry).strip()
                if not uri:
                    continue
                label = _infer_entity_label(
                    service,
                    uri,
                    fk_info.get("target_dataset") if fk_info else None,
                )

                # Add resource ID for graph view navigation
                resource_entry = {"label": label, "uri": uri}
                target_resource = Resource.objects.filter(uri=uri).first()
                if target_resource:
                    resource_entry["resource_id"] = str(target_resource.id)
                normalized.append(resource_entry)

            if normalized:
                labelled_json = json.dumps(normalized)
                form.initial[field.name] = labelled_json
                field.form.initial[field.name] = labelled_json
                initial_labels.extend(normalized)

        if fk_info and not meta.get("is_multi_value"):
            raw_value = form.initial.get(field.name, field.value())
            if raw_value:
                # Use selected display property if available
                display_prop_uri = meta.get("display_property")
                resolved_label = _infer_entity_label(
                    service,
                    str(raw_value),
                    fk_info.get("target_dataset"),
                    display_property_uri=display_prop_uri,
                )
                if resolved_label and resolved_label != raw_value:
                    meta["resolved_label"] = resolved_label
                    meta["resolved_uri"] = str(raw_value)
                    form.initial[field.name] = resolved_label
                    if field.name in form.fields:
                        form.fields[field.name].initial = resolved_label

                    # Add resource ID for graph view navigation of FK target
                    target_resource = Resource.objects.filter(uri=str(raw_value)).first()
                    if target_resource:
                        meta["resolved_resource_id"] = str(target_resource.id)

        if meta.get("resolved_uri") and hasattr(widget, "attrs"):
            widget.attrs.setdefault("data-initial-uri", meta["resolved_uri"])

        # For non-FK/relationship fields, try to find resource ID for current value
        if not is_relationship and not meta.get("resolved_uri"):
            current_value = form.initial.get(field.name) or field.value()
            if current_value and not isinstance(widget, forms.HiddenInput):
                # Try to find a resource with this value (could be by name, value, or URI)
                resource = None
                # First try as URI
                resource = Resource.objects.filter(uri=str(current_value)).first()
                # Then try by name
                if not resource:
                    resource = Resource.objects.filter(name=str(current_value)).first()
                # Then try by value (for literals)
                if not resource:
                    resource = Resource.objects.filter(value=str(current_value)).first()

                if resource:
                    meta["current_value_resource_id"] = str(resource.id)
                    meta["current_value"] = str(current_value)

        destination = relationship_fields if is_relationship else normal_fields
        if is_relationship:
            join_key = meta.get("join_key") or meta.get("join_relationship") or meta.get("property_uri")
            if join_key in seen_relationship_keys:
                continue
            seen_relationship_keys.add(join_key)
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

    normal_fields_sorted = sorted(
        normal_fields,
        key=lambda item: item["field"].label.lower(),
    )

    # Prepare multi-value rows for regular fields (pure HTMX, no JS)
    import uuid
    for item in normal_fields_sorted:
        if not item["meta"].get("is_multi_value"):
            continue

        field = item["field"]
        meta = item["meta"]
        field_name = field.name
        initial_labels = item.get("initial_labels", [])

        rows = []
        if initial_labels:
            for label_data in initial_labels:
                row_id = f"multi-value-row-{field_name}-{uuid.uuid4().hex[:8]}"
                input_id = f"input-{row_id}"
                suggestions_id = f"suggestions-{row_id}"

                if isinstance(label_data, dict):
                    display_value = label_data.get("label", "")
                    stored_value = label_data.get("uri", "")
                    resource_id = label_data.get("resource_id")
                else:
                    display_value = str(label_data)
                    stored_value = str(label_data)
                    resource_id = None

                row_data = {
                    "row_id": row_id,
                    "input_id": input_id,
                    "suggestions_id": suggestions_id,
                    "display_value": display_value,
                    "stored_value": stored_value,
                    "suggestion_url": meta.get("base_suggestion_url", ""),
                }
                if resource_id:
                    # Ensure resource_id is string (might already be from JSON)
                    row_data["resource_id"] = str(resource_id) if resource_id else None
                rows.append(row_data)

        item["rows"] = rows

    relationship_fields_sorted = sorted(
        relationship_fields,
        key=lambda item: item["field"].label.lower(),
    )

    # Prepare relationship rows data for pure HTMX rendering
    import uuid
    for rel_item in relationship_fields_sorted:
        field = rel_item["field"]
        meta = rel_item["meta"]
        field_name = field.name

        # Ensure search_properties is always a list
        if "search_properties" not in meta or meta["search_properties"] is None:
            meta["search_properties"] = []

        # Get initial labels/values
        initial_labels = rel_item.get("initial_labels", [])

        # Generate rows for existing values
        rows = []
        if initial_labels:
            for label_data in initial_labels:
                row_id = f"relationship-row-{field_name}-{uuid.uuid4().hex[:8]}"
                input_id = f"input-{row_id}"
                suggestions_id = f"suggestions-{row_id}"

                display_value = label_data.get("label", "")
                stored_value = label_data.get("uri", "")
                resource_id = label_data.get("resource_id")

                row_data = {
                    "row_id": row_id,
                    "input_id": input_id,
                    "suggestions_id": suggestions_id,
                    "display_value": display_value,
                    "stored_value": stored_value,
                    "suggestion_url": meta.get("base_suggestion_url", ""),
                }
                if resource_id:
                    # Ensure resource_id is string (might already be from JSON)
                    row_data["resource_id"] = str(resource_id) if resource_id else None
                rows.append(row_data)
        else:
            # Create one empty row if no initial values
            row_id = f"relationship-row-{field_name}-{uuid.uuid4().hex[:8]}"
            input_id = f"input-{row_id}"
            suggestions_id = f"suggestions-{row_id}"
            rows.append({
                "row_id": row_id,
                "input_id": input_id,
                "suggestions_id": suggestions_id,
                "display_value": "",
                "stored_value": "",
                "suggestion_url": meta.get("base_suggestion_url", ""),
            })

        rel_item["rows"] = rows
        rel_item["property_select_id"] = f"relationship-property-{field_name}"
        rel_item["selected_property"] = ""

    template_context = {
        "dataset_summary": dataset_summary,
        "fields_with_metadata": normal_fields_sorted,
        "relationship_fields": relationship_fields_sorted,
        "form": form,
        "entity_uri": entity_uri,
        "entity_label": entity_label,
        "success_message": success_message,
        "error_message": error_message,
        "load_error": load_error,
        "mapping": service.mapping,
        "search_properties": search_properties,
        "selected_property": selected_property,
        "read_only_relationships": sorted(
            read_only_relationships or [],
            key=lambda item: item["label"].lower(),
        ),
    }
    template_context.update(project_access_context)

    return render_to_string(
        "metadata/entity_creation/partials/_dataset_panel.html",
        template_context,
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

        mapping_queryset = Mapping.objects.filter(
            organization_id=organization.code
        ).order_by("-created_at")
        mapping_list = list(mapping_queryset)

        mapping_override = request.GET.get("mapping")
        selected_mapping = _resolve_active_mapping(
            request,
            organization,
            mapping_override,
        )

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
                    "mappings": mapping_list,
                    "active_mapping_id": None,
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
            hasattr(request.user, 'has_role') and request.user.has_role('researcher')  # TODO: tighten to manager/archivist once roles are finalized.
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
            field_metadata, join_field_map = service.augment_field_metadata_with_joins(
                target_dataset,
                field_metadata,
            )
            form = DatasetEntityForm(field_metadata=field_metadata)
            _remove_join_source_fields(form, join_field_map)
            dataset_panel_html = _render_dataset_panel(
                request,
                service=service,
                dataset_name=target_dataset,
                form=form,
                field_metadata=field_metadata,
                join_field_map=join_field_map,
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
                "mappings": mapping_list,
                "active_mapping_id": str(selected_mapping.id),
                "mapping_required": False,
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

        selected_property = request.GET.get("property") or ""
        property_uris: List[str] = []
        property_label: str = ""
        property_values: Dict[str, str] = {}
        entity_uris: List[str] = []

        if selected_property:
            field_metadata = service.get_field_metadata(dataset_name)
            property_label_lookup: Dict[str, str] = {}
            for meta in field_metadata.values():
                property_uri = meta.get("property_uri")
                if not property_uri:
                    continue
                uri_str = str(property_uri)
                if not uri_str:
                    continue
                label_str = str(meta.get("property_label") or meta.get("column_name") or uri_str)
                property_label_lookup.setdefault(uri_str, label_str)
            if selected_property in property_label_lookup:
                property_uris = [selected_property]
                property_label = property_label_lookup[selected_property]

        max_results = 20

        if property_uris:
            triples_qs = (
                Triple.objects.filter(
                    subject__uri__in=dataset_entities_qs,
                    predicate__uri__in=property_uris,
                    object__resource_type=ResourceType.LITERAL,
                )
                .select_related("subject", "object")
                .order_by("object__value", "object__name", "subject__uri")
            )
            if query:
                from django.db.models import Q

                triples_qs = triples_qs.filter(
                    Q(object__value__icontains=query) | Q(object__name__icontains=query)
                )

            for triple in triples_qs:
                subject_uri = getattr(triple.subject, "uri", None)
                if not subject_uri or subject_uri in property_values:
                    continue
                literal_resource = triple.object
                literal_value = (
                    literal_resource.value
                    or getattr(literal_resource, "literal_value", None)
                    or literal_resource.name
                    or ""
                )
                property_values[subject_uri] = str(literal_value)
                entity_uris.append(subject_uri)
                if len(entity_uris) >= max_results:
                    break
        else:
            if query:
                from django.db.models import Q

                literal_matches_qs = (
                    Triple.objects.filter(
                        subject__uri__in=dataset_entities_qs,
                        object__resource_type=ResourceType.LITERAL,
                    )
                    .filter(
                        Q(object__value__icontains=query)
                        | Q(object__name__icontains=query)
                    )
                    .values_list("subject__uri", flat=True)
                    .distinct()
                )

                uri_matches = dataset_entities_qs.filter(subject__uri__icontains=query)

                combined = list(uri_matches[:max_results])
                for uri in literal_matches_qs[:max_results]:
                    if uri not in combined:
                        combined.append(uri)
                        if len(combined) >= max_results:
                            break
                entity_uris = combined
            else:
                entity_uris = list(dataset_entities_qs[:max_results])

        dataset_endpoint = reverse("metadata:entity_workspace_dataset", args=[service.mapping.id])
        results: List[Dict[str, str]] = []
        for uri in entity_uris:
            raw_label = _infer_entity_label(service, uri, dataset_name)
            identifier = uri.split("/")[-1]
            raw_label_str = str(raw_label).strip() if raw_label else ""
            property_value = property_values.get(uri, "").strip()

            display_label = property_value or raw_label_str or identifier
            secondary_label = ""
            if property_value and raw_label_str and property_value.lower() != raw_label_str.lower():
                secondary_label = raw_label_str

            params: Dict[str, str] = {
                "dataset": dataset_name,
                "mode": "load",
                "entity_uri": uri,
            }
            if display_label:
                params["entity_label"] = display_label
            if property_uris:
                params["property"] = property_uris[0]

            results.append(
                {
                    "uri": uri,
                    "label": display_label,
                    "entity_label": display_label,
                    "property_value": property_value,
                    "property_label": property_label if property_uris else "",
                    "id": identifier,
                    "secondary_label": secondary_label,
                    "load_url": f"{dataset_endpoint}?{urlencode(params)}",
                }
            )

        html = render_to_string(
            "metadata/entity_creation/partials/_entity_search_results.html",
            {
                "results": results,
                "dataset_name": dataset_name,
            },
            request=request,
        )
        helper = CSVMappingTemplateHelperMixin()
        response_html = helper.build_oob_response(html)
        return HttpResponse(response_html)


class ProjectAccessLevelUpdateView(LoginRequiredMixin, View):
    """Update public access level for project resources."""

    def post(self, request: HttpRequest, mapping_id: str) -> HttpResponse:
        dataset_name = request.POST.get("dataset") or ""
        entity_uri = request.POST.get("entity_uri")
        desired_level = request.POST.get("public_access_level")

        if not dataset_name or not entity_uri or not desired_level:
            return HttpResponseBadRequest("Missing required parameters")

        try:
            service = _get_schema_service(request, mapping_id)
        except ValueError as exc:
            return HttpResponseBadRequest(str(exc))

        slug = slugify(dataset_name).lower()
        if slug not in {"projekt", "project"}:
            return HttpResponseBadRequest("Unsupported dataset for access updates")

        valid_levels = {value for value, _ in PublicAccessLevel.choices}
        if desired_level not in valid_levels:
            return HttpResponseBadRequest("Ungültiger Zugriffsstatus")

        resource = Resource.objects.filter(uri=entity_uri).first()
        if resource is None:
            return HttpResponseBadRequest("Projekt wurde nicht gefunden")

        desired_level_enum = PublicAccessLevel(desired_level)
        fields_to_update: List[str] = []
        if resource.public_access_level != desired_level_enum.value:
            resource.public_access_level = desired_level_enum.value
            fields_to_update.append("public_access_level")

        if desired_level_enum != PublicAccessLevel.PUBLIC and resource.is_public_approved:
            resource.is_public_approved = False
            fields_to_update.append("is_public_approved")

        if fields_to_update:
            resource.save(update_fields=list(set(fields_to_update)))
            feedback_message = "Zugriff angepasst."
        else:
            feedback_message = "Zugriff unverändert."

        dataset_summary = service.get_dataset_summary(dataset_name)
        context = {
            "mapping": service.mapping,
            "dataset_summary": dataset_summary,
            "entity_uri": entity_uri,
        }
        context.update(
            _build_project_access_context(
                service=service,
                dataset_summary=dataset_summary,
                dataset_name=dataset_name,
                entity_uri=entity_uri,
                message=feedback_message,
            )
        )

        html = render_to_string(
            "metadata/entity_creation/partials/_project_access_control.html",
            context,
            request=request,
        )
        return HttpResponse(html)


class DatasetFieldValueOptionsView(LoginRequiredMixin, View):
    """Return existing literal suggestions for dataset fields."""

    max_suggestions = 20

    def get(self, request: HttpRequest, mapping_id: str) -> HttpResponse:
        # Handle clear parameter - return empty content to hide dropdown
        if request.GET.get("clear"):
            return HttpResponse("")

        dataset_name = request.GET.get("dataset")
        column_name = request.GET.get("column")
        input_id = request.GET.get("input_id")
        target_id = request.GET.get("target_id")
        property_uri = request.GET.get("property")
        property_select_id = request.GET.get("property_select_id", "")

        logger.info(f"[DatasetFieldValueOptionsView.GET] dataset={dataset_name}, column={column_name}, property={property_uri}")

        if not dataset_name or not column_name or not input_id or not target_id:
            logger.error("[DatasetFieldValueOptionsView.GET] Missing required parameters")
            return HttpResponseBadRequest("Missing required parameters")

        try:
            service = _get_schema_service(request, mapping_id)
        except ValueError as exc:
            return HttpResponseBadRequest(str(exc))

        field_metadata = service.get_field_metadata(dataset_name)
        field_metadata, join_field_map = service.augment_field_metadata_with_joins(
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
            suggestions = self._collect_join_entity_suggestions(service, relationship, query, property_uri)
        elif fk_info:
            suggestions = self._collect_fk_suggestions(service, fk_info, query, property_uri)
        else:
            suggestions = self._collect_property_suggestions(
                service,
                field_meta.get("property_uri"),
                query,
            )

        # Build suggestion URL for close button
        from django.urls import reverse
        from urllib.parse import urlencode
        suggestion_base_url = reverse(
            "metadata:entity_workspace_field_values",
            args=[mapping_id],
        )
        suggestion_params = urlencode({"dataset": dataset_name, "column": column_name})
        suggestion_url = f"{suggestion_base_url}?{suggestion_params}"

        context = {
            "suggestions": suggestions[: self.max_suggestions],
            "input_id": input_id,
            "target_id": target_id,
            "mapping_id": mapping_id,
            "dataset_name": dataset_name,
            "column_name": column_name,
            "property_uri": property_uri or "",
            "property_select_id": property_select_id,
            "suggestion_url": suggestion_url,
        }
        logger.info(f"[DatasetFieldValueOptionsView.GET] Returning {len(context['suggestions'])} suggestions for target={target_id}")
        logger.debug(f"[DatasetFieldValueOptionsView.GET] Suggestions: {context['suggestions'][:3]}")  # Log first 3
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
        property_uri: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        target_dataset = fk_info.get("target_dataset")
        if not target_dataset:
            return []
        return self._collect_dataset_entity_suggestions(service, target_dataset, query, property_uri)

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

    def _collect_dataset_entity_suggestions(
        self,
        service: SchemaWorkspaceService,
        dataset_name: str,
        query: str,
        property_uri: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        logger.info(
            f"[_collect_dataset_entity_suggestions] dataset={dataset_name}, "
            f"query='{query}', property_uri={property_uri}"
        )
        try:
            schema = service.get_dataset_schema(dataset_name)
        except ValueError:
            return []

        dataset_resource = service._resolve_dataset_resource(dataset_name, schema)  # type: ignore[attr-defined]
        if not dataset_resource:
            return []

        is_part_of_uri = "http://purl.org/dc/terms/isPartOf"
        entities_qs = Triple.objects.filter(
            predicate__uri=is_part_of_uri,
            object=dataset_resource,
        ).values_list("subject__uri", flat=True)

        max_results = self.max_suggestions
        literal_label_map: Dict[str, str] = {}
        uri_matches: List[str] = []
        if query:
            from django.db.models import Q

            literal_matches_qs = Triple.objects.filter(
                subject__uri__in=entities_qs,
                object__resource_type=ResourceType.LITERAL,
            )

            if property_uri:
                logger.info(f"[_collect_dataset_entity_suggestions] Filtering by property: {property_uri}")
                literal_matches_qs = literal_matches_qs.filter(predicate__uri=property_uri)
            else:
                logger.info("[_collect_dataset_entity_suggestions] No property filter - searching all properties")

            literal_matches_qs = literal_matches_qs.filter(
                Q(object__value__icontains=query)
                | Q(object__name__icontains=query)
            ).values_list(
                "subject__uri",
                "object__value",
                "object__name",
            )

            logger.info(f"[_collect_dataset_entity_suggestions] Found {literal_matches_qs.count()} literal matches")

            for (
                subject_uri,
                value,
                name,
            ) in literal_matches_qs[: max_results * 5]:
                candidate = next(
                    (
                        str(val).strip()
                        for val in (value, name)
                        if val not in (None, "")
                    ),
                    "",
                )
                if not candidate:
                    continue
                literal_label_map.setdefault(subject_uri, candidate)
                if len(literal_label_map) >= max_results:
                    break

            uri_matches = list(
                Triple.objects.filter(
                    predicate__uri=is_part_of_uri,
                    object=dataset_resource,
                    subject__uri__icontains=query,
                ).values_list("subject__uri", flat=True)[: max_results * 2]
            )
        else:
            uri_matches = []

        uris: List[str] = []

        def append_unique(items: Iterable[str]) -> None:
            for item in items:
                if len(uris) >= max_results:
                    break
                if item not in uris:
                    uris.append(item)

        append_unique(literal_label_map.keys())
        append_unique(uri_matches)

        if len(uris) < max_results:
            append_unique(list(entities_qs[:max_results]))

        seen: Set[str] = set()
        results: List[Dict[str, str]] = []
        for uri in uris:
            if uri in seen:
                continue
            seen.add(uri)
            identifier = uri.split("/")[-1]
            matched_label = literal_label_map.get(uri, "").strip()
            # Use selected property for display if specified
            inferred_label = _infer_entity_label(
                service,
                uri,
                dataset_name,
                display_property_uri=property_uri
            ).strip()

            label = matched_label or inferred_label or identifier
            if label.lower() == identifier.lower():
                humanized = identifier.replace("_", " ").replace("-", " ").strip()
                if humanized and humanized.lower() != label.lower():
                    label = humanized

            display_label = matched_label or label

            suggestion = {
                "value": uri,
                "label": label,
                "display": display_label,
                "identifier": identifier,
            }
            results.append(suggestion)

            # Log first few suggestions to debug display issues
            if len(results) <= 3:
                logger.info(f"[Suggestion #{len(results)}] display='{display_label}', label='{label}', identifier='{identifier}'")
        return results

    def _collect_join_entity_suggestions(
        self,
        service: SchemaWorkspaceService,
        relationship: Optional[JoinRelationship],
        query: str,
        property_uri: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        if relationship is None:
            return []
        return self._collect_dataset_entity_suggestions(
            service,
            relationship.other_dataset,
            query,
            property_uri,
        )


class RelationshipRowView(LoginRequiredMixin, View):
    """
    HTMX endpoint for managing individual relationship rows.
    """

    def post(self, request: HttpRequest, mapping_id: str) -> HttpResponse:
        """Add a new relationship row."""
        dataset_name = request.GET.get("dataset")
        field_name = request.GET.get("field_name")

        logger.info(f"[RelationshipRowView.POST] Adding row: dataset={dataset_name}, field={field_name}")

        if not dataset_name or not field_name:
            logger.error("[RelationshipRowView.POST] Missing dataset or field_name parameter")
            return HttpResponseBadRequest("Missing dataset or field_name parameter")

        try:
            service = _get_schema_service(request, mapping_id)
        except ValueError as exc:
            logger.error(f"[RelationshipRowView.POST] Service error: {exc}")
            return HttpResponseBadRequest(str(exc))

        field_metadata = service.get_field_metadata(dataset_name)
        field_metadata, join_field_map = service.augment_field_metadata_with_joins(
            dataset_name,
            field_metadata,
        )
        field_meta = field_metadata.get(field_name)
        if not field_meta:
            logger.error(f"[RelationshipRowView.POST] Unknown field: {field_name}")
            return HttpResponseBadRequest("Unknown field")

        selected_property = request.POST.get(f"relationship_property_{field_name}", "")
        logger.info(f"[RelationshipRowView.POST] Selected property: {selected_property}")

        # Generate unique IDs for this row
        import uuid
        row_id = f"relationship-row-{field_name}-{uuid.uuid4().hex[:8]}"
        input_id = f"input-{row_id}"
        suggestions_id = f"suggestions-{row_id}"

        # Build suggestion URL
        base_suggestion_url = reverse(
            "metadata:entity_workspace_field_values",
            args=[service.mapping.id],
        )
        base_params = {"dataset": dataset_name, "column": field_name}
        suggestion_url = f"{base_suggestion_url}?{urlencode(base_params)}"

        # Determine property select ID
        property_select_id = f"relationship-property-{field_name}"

        context = {
            "row_id": row_id,
            "input_id": input_id,
            "suggestions_id": suggestions_id,
            "field_name": field_name,
            "display_value": "",
            "stored_value": "",
            "suggestion_url": suggestion_url,
            "selected_property": selected_property,
            "property_select_id": property_select_id,
            "mapping_id": mapping_id,
        }

        logger.info(f"[RelationshipRowView.POST] Rendering row: {row_id}")
        return render(
            request,
            "metadata/entity_creation/partials/_relationship_row.html",
            context,
        )

    def delete(self, request: HttpRequest, mapping_id: str) -> HttpResponse:
        """Remove a relationship row."""
        # Return empty response to remove the row via hx-swap="outerHTML"
        return HttpResponse("")


class RelationshipRowsView(LoginRequiredMixin, View):
    """
    HTMX endpoint for re-rendering all relationship rows when property changes.
    """

    def get(self, request: HttpRequest, mapping_id: str) -> HttpResponse:
        """Re-render all rows with new property selection."""
        dataset_name = request.GET.get("dataset")
        field_name = request.GET.get("field_name")

        logger.info(f"[RelationshipRowsView.GET] Re-rendering rows: dataset={dataset_name}, field={field_name}")

        if not dataset_name or not field_name:
            logger.error("[RelationshipRowsView.GET] Missing dataset or field_name parameter")
            return HttpResponseBadRequest("Missing dataset or field_name parameter")

        try:
            service = _get_schema_service(request, mapping_id)
        except ValueError as exc:
            logger.error(f"[RelationshipRowsView.GET] Service error: {exc}")
            return HttpResponseBadRequest(str(exc))

        field_metadata = service.get_field_metadata(dataset_name)
        field_metadata, join_field_map = service.augment_field_metadata_with_joins(
            dataset_name,
            field_metadata,
        )

        selected_property = request.GET.get(f"relationship_property_{field_name}", "")
        logger.info(f"[RelationshipRowsView.GET] Selected property: {selected_property}")

        raw_values = [
            value.strip()
            for value in request.GET.getlist(f"{field_name}[]")
            if value and value.strip()
        ]
        logger.info(f"[RelationshipRowsView.GET] Existing values (raw): {raw_values}")

        relationship = join_field_map.get(field_name)
        fk_info = field_metadata.get(field_name, {}).get("fk_relationship") or {}
        target_dataset = None
        if relationship:
            target_dataset = relationship.other_dataset
        elif fk_info:
            target_dataset = fk_info.get("target_dataset")

        normalized_values: List[Tuple[str, Optional[str]]] = []
        seen: Set[str] = set()
        for raw_value in raw_values:
            canonical_value, label_hint = decode_placeholder_uri(raw_value)
            if not canonical_value or canonical_value in seen:
                continue
            seen.add(canonical_value)
            normalized_values.append((canonical_value, label_hint))
        logger.info(
            "[RelationshipRowsView.GET] Normalized values: %s",
            [value for value, _ in normalized_values],
        )

        # Build suggestion URL
        base_suggestion_url = reverse(
            "metadata:entity_workspace_field_values",
            args=[service.mapping.id],
        )
        base_params = {"dataset": dataset_name, "column": field_name}
        suggestion_url = f"{base_suggestion_url}?{urlencode(base_params)}"

        # Determine property select ID
        property_select_id = f"relationship-property-{field_name}"

        # Generate rows for existing values
        rows = []
        import uuid
        for value, label_hint in normalized_values:
            row_id = f"relationship-row-{field_name}-{uuid.uuid4().hex[:8]}"
            input_id = f"input-{row_id}"
            suggestions_id = f"suggestions-{row_id}"
            inferred_label = _infer_entity_label(
                service,
                value,
                target_dataset,
            ) if target_dataset else ""
            display_value = label_hint or inferred_label or value

            rows.append({
                "row_id": row_id,
                "input_id": input_id,
                "suggestions_id": suggestions_id,
                "display_value": display_value,
                "stored_value": value,
                "suggestion_url": suggestion_url,
            })

        # If no existing values, create one empty row
        if not rows:
            row_id = f"relationship-row-{field_name}-{uuid.uuid4().hex[:8]}"
            input_id = f"input-{row_id}"
            suggestions_id = f"suggestions-{row_id}"
            rows.append({
                "row_id": row_id,
                "input_id": input_id,
                "suggestions_id": suggestions_id,
                "display_value": "",
                "stored_value": "",
                "suggestion_url": suggestion_url,
            })

        logger.info(f"[RelationshipRowsView.GET] Rendering {len(rows)} rows")

        context = {
            "rows": rows,
            "field_name": field_name,
            "selected_property": selected_property,
            "property_select_id": property_select_id,
            "mapping_id": mapping_id,
        }

        # Render all rows
        html = "".join([
            render_to_string(
                "metadata/entity_creation/partials/_relationship_row.html",
                {**row, "field_name": field_name, "selected_property": selected_property,
                 "property_select_id": property_select_id, "mapping_id": mapping_id},
                request=request,
            )
            for row in rows
        ])

        logger.info(f"[RelationshipRowsView.GET] Rendered HTML length: {len(html)}")
        return HttpResponse(html)


class RelationshipSelectSuggestionView(LoginRequiredMixin, CSVMappingTemplateHelperMixin, View):
    """
    HTMX endpoint for selecting a suggestion value.
    Returns OOB updates for both visible and hidden inputs.
    """

    def post(self, request: HttpRequest, mapping_id: str) -> HttpResponse:
        """Handle suggestion selection using targeted OOB swaps for input elements."""
        import re
        from django.utils.html import escape

        input_id = request.POST.get("input_id")
        target_id = request.POST.get("target_id")
        dataset_name = request.POST.get("dataset")
        column_name = request.POST.get("column")
        raw_value = request.POST.get("value", "") or ""
        value_candidate = raw_value.strip()
        label = (request.POST.get("label", raw_value) or "").strip()
        value, label_hint = decode_placeholder_uri(value_candidate)
        if label_hint and (not label or label in {raw_value.strip(), value_candidate, value}):
            label = label_hint
        if not label:
            label = value or value_candidate or raw_value.strip()
        selected_property = request.POST.get("property") or ""
        property_select_id = request.POST.get("property_select_id") or ""

        if not input_id or not target_id or not dataset_name or not column_name:
            logger.warning(
                "[RelationshipSelectSuggestionView.POST] Missing required parameters: "
                f"input_id={input_id}, target_id={target_id}, dataset={dataset_name}, column={column_name}"
            )
            return HttpResponseBadRequest("Missing required parameters")

        hidden_input_id = f"{input_id}-hidden"

        logger.info(
            "[RelationshipSelectSuggestionView.POST] Updating inputs: "
            f"visible={input_id}, hidden={hidden_input_id}, value={value}, label={label}"
        )

        # Build suggestion URL for the visible input
        suggestion_base_url = reverse(
            "metadata:entity_workspace_field_values",
            args=[mapping_id],
        )
        suggestion_params = urlencode({"dataset": dataset_name, "column": column_name})
        suggestion_url = f"{suggestion_base_url}?{suggestion_params}"
        property_param = f"&property={escape(selected_property)}" if selected_property else ""
        property_select_param = f"&property_select_id={escape(property_select_id)}" if property_select_id else ""

        # Create OOB updates for individual inputs
        # 1. Update hidden input with the URI value
        hidden_input_html = f'''<input type="hidden"
           name="{escape(column_name)}[]"
           id="{escape(hidden_input_id)}"
           value="{escape(value)}"
           data-uri="{escape(value)}"
           data-label="{escape(label)}"
           hx-swap-oob="outerHTML">'''

        # 2. Update visible input with the display label
        visible_input_html = f'''<input type="text"
           id="{escape(input_id)}"
           name="q"
           class="input input-bordered flex-1"
           placeholder="Wert eingeben"
           value="{escape(label)}"
           hx-get="{escape(suggestion_url)}&input_id={escape(input_id)}&target_id={escape(target_id)}{property_select_param}{property_param}"
           hx-trigger="focus, keyup changed delay:200ms"
           hx-target="#{escape(target_id)}"
           hx-include="this{', #' + escape(property_select_id) if property_select_id else ''}"
           autocomplete="off"
           hx-swap-oob="outerHTML">'''

        # 3. Clear the dropdown
        dropdown_html = f'<div id="{escape(target_id)}" hx-swap-oob="innerHTML"></div>'

        response_html = f"{hidden_input_html}\n{visible_input_html}\n{dropdown_html}"
        logger.debug(f"[RelationshipSelectSuggestionView.POST] Response HTML: {response_html[:200]}")
        return HttpResponse(response_html)


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
        field_metadata, join_field_map = service.augment_field_metadata_with_joins(
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
                            entity_label = _infer_entity_label(service, entity_uri, dataset_name)
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
                        entity_label = _infer_entity_label(service, entity_uri, dataset_name)
                else:
                    load_error = True

        form = DatasetEntityForm(
            field_metadata=field_metadata,
            initial=initial_data,
            disable_anchors=disable_anchors,
        )
        _remove_join_source_fields(form, join_field_map)

        read_only_relationships: List[Dict[str, Any]] = []
        if entity_uri:
            relationships = service.collect_relationship_values(
                dataset_name=dataset_name,
                entity_uri=entity_uri,
                field_metadata=field_metadata,
                join_field_map=join_field_map,
            )
            read_only_relationships = _apply_relationship_initials(
                service=service,
                form=form,
                relationships=relationships,
            )
            if not entity_label:
                entity_label = _infer_entity_label(service, entity_uri, dataset_name)

        html = _render_dataset_panel(
            request,
            service=service,
            dataset_name=dataset_name,
            form=form,
            field_metadata=field_metadata,
            join_field_map=join_field_map,
            entity_uri=entity_uri,
            entity_label=entity_label,
            load_error=load_error,
            read_only_relationships=read_only_relationships,
        )
        return HttpResponse(html)

    def post(self, request: HttpRequest, mapping_id: str) -> HttpResponse:
        dataset_name = request.POST.get("dataset")
        if not dataset_name:
            return HttpResponseBadRequest("Missing dataset parameter")

        logger.info(f"[SchemaDatasetFragmentView.POST] Saving entity for dataset={dataset_name}")

        service = self.get_service(request, mapping_id)
        field_metadata = service.get_field_metadata(dataset_name)
        field_metadata, join_field_map = service.augment_field_metadata_with_joins(
            dataset_name,
            field_metadata,
        )
        entity_uri = request.POST.get("entity_uri") or None

        logger.info(f"[SchemaDatasetFragmentView.POST] entity_uri={entity_uri}, join_fields={list(join_field_map.keys())}")

        submission_mode = request.POST.get("submission_mode", "create_new")

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

                # Process join fields (those in join_field_map)
                # HTMX sends arrays as fieldname[], so check POST directly
                for field_name, relationship in join_field_map.items():
                    # First try to get array data from POST (pure HTMX submission)
                    array_key = f"{field_name}[]"
                    raw_array = request.POST.getlist(array_key)

                    if raw_array:
                        # Pure HTMX: got array of values directly
                        logger.info(f"[SchemaDatasetFragmentView.POST] Join field '{field_name}': raw_array={raw_array}")
                        normalized = []
                        seen_values: Set[str] = set()
                        for item in raw_array:
                            cleaned = item.strip()
                            if not cleaned:
                                continue
                            canonical, _ = decode_placeholder_uri(cleaned)
                            if canonical and canonical not in seen_values:
                                normalized.append(canonical)
                                seen_values.add(canonical)
                        join_payloads[field_name] = normalized
                    else:
                        # Fallback: check form data (for JSON string or single value)
                        raw = entity_data.pop(field_name, None)
                        logger.info(f"[SchemaDatasetFragmentView.POST] Join field '{field_name}': raw_value={raw}")
                        join_payloads[field_name] = _parse_join_payload(raw)

                    logger.info(f"[SchemaDatasetFragmentView.POST] Join field '{field_name}': parsed={join_payloads[field_name]}")

                # Process multi-value FK fields (not in join_field_map but are relationships)
                for field_name, meta in field_metadata.items():
                    if field_name in join_payloads:
                        continue  # Already processed above
                    fk_info = meta.get("fk_relationship")
                    if fk_info and meta.get("is_multi_value"):
                        # First try to get array data from POST (pure HTMX submission)
                        array_key = f"{field_name}[]"
                        raw_array = request.POST.getlist(array_key)

                        if raw_array:
                            # Pure HTMX: got array of values directly
                            logger.info(f"[SchemaDatasetFragmentView.POST] Multi-FK field '{field_name}': raw_array={raw_array}")
                            normalized = []
                            seen_values: Set[str] = set()
                            for item in raw_array:
                                cleaned = item.strip()
                                if not cleaned:
                                    continue
                                canonical, _ = decode_placeholder_uri(cleaned)
                                if canonical and canonical not in seen_values:
                                    normalized.append(canonical)
                                    seen_values.add(canonical)
                            join_payloads[field_name] = normalized
                            continue

                        # Fallback: check form data (for JSON string or single value)
                        raw = entity_data.pop(field_name, None)
                        logger.info(f"[SchemaDatasetFragmentView.POST] Multi-FK field '{field_name}': raw_value={raw}")
                        parsed = _parse_join_payload(raw)
                        logger.info(f"[SchemaDatasetFragmentView.POST] Multi-FK field '{field_name}': parsed={parsed}")
                        join_payloads[field_name] = parsed

                saved_uri, created = service.save_entity(
                    dataset_name, entity_data, entity_uri=entity_uri
                )
                entity_label = _infer_entity_label(service, saved_uri, dataset_name)
                cleaned_initial = {key: form.cleaned_data.get(key) for key in form.fields}

                for field_name, values in join_payloads.items():
                    # Check if this is a join field or a multi-FK field
                    if field_name in join_field_map:
                        # Join field - use sync_join_relationship
                        relationship = join_field_map[field_name]
                        logger.info(f"[SchemaDatasetFragmentView.POST] Syncing join relationship '{field_name}' with {len(values)} values")
                        service.sync_join_relationship(
                            entity_uri=saved_uri,
                            relationship=relationship,
                            related_uris=values,
                        )
                    else:
                        # Multi-FK field - save as FK relationship
                        meta = field_metadata.get(field_name, {})
                        fk_info = meta.get("fk_relationship")
                        if fk_info:
                            target_dataset = fk_info.get("target_dataset")
                            property_uri = meta.get("property_uri")
                            logger.info(f"[SchemaDatasetFragmentView.POST] Saving multi-FK '{field_name}' -> {target_dataset} with {len(values)} values")
                            # Save as direct FK triples
                            service.save_multi_fk_relationship(
                                entity_uri=saved_uri,
                                property_uri=property_uri,
                                related_uris=values,
                            )

                if created:
                    keep_editing = submission_mode == "stay_on_entity"
                    if keep_editing:
                        success_message = "Entity erfolgreich erstellt. Du kannst weiter bearbeiten."
                        form = DatasetEntityForm(
                            field_metadata=field_metadata,
                            initial=cleaned_initial,
                            disable_anchors=True,
                        )
                        entity_uri = saved_uri
                    else:
                        success_message = (
                            f"Entity erfolgreich erstellt (<code class=\"font-mono\">{saved_uri}</code>)."
                        )
                        # Reset form for a new entry while keeping anchors blank
                        form = DatasetEntityForm(field_metadata=field_metadata)
                        entity_uri = None
                        entity_label = None
                else:
                    success_message = "Änderungen gespeichert."
                    # Rehydrate form with current values to keep user context
                    form = DatasetEntityForm(
                        field_metadata=field_metadata,
                        initial=cleaned_initial,
                        disable_anchors=True,
                    )
                    entity_uri = saved_uri

                read_only_relationships: List[Dict[str, Any]] = []
                if entity_uri:
                    relationships = service.collect_relationship_values(
                        dataset_name=dataset_name,
                        entity_uri=entity_uri,
                        field_metadata=field_metadata,
                        join_field_map=join_field_map,
                    )
                    logger.info(f"[SchemaDatasetFragmentView.POST] Collected {len(relationships)} relationships after save")
                    read_only_relationships = _apply_relationship_initials(
                        service=service,
                        form=form,
                        relationships=relationships,
                    )
                    logger.info(f"[SchemaDatasetFragmentView.POST] Applied relationship initials: {len(read_only_relationships)} fields")

                html = _render_dataset_panel(
                    request,
                    service=service,
                    dataset_name=dataset_name,
                    form=form,
                    field_metadata=field_metadata,
                    join_field_map=join_field_map,
                    entity_uri=entity_uri,
                    entity_label=entity_label,
                    success_message=success_message,
                    read_only_relationships=read_only_relationships,
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

        read_only_relationships: List[Dict[str, Any]] = []
        if entity_uri:
            relationships = service.collect_relationship_values(
                dataset_name=dataset_name,
                entity_uri=entity_uri,
                field_metadata=field_metadata,
                join_field_map=join_field_map,
            )
            read_only_relationships = _apply_relationship_initials(
                service=service,
                form=form,
                relationships=relationships,
                mutate_form=False,
            )

        entity_label_resolved = (
            _infer_entity_label(service, entity_uri, dataset_name)
            if entity_uri
            else None
        )

        html = _render_dataset_panel(
            request,
            service=service,
            dataset_name=dataset_name,
            form=form,
            field_metadata=field_metadata,
            join_field_map=join_field_map,
            entity_uri=entity_uri,
            entity_label=entity_label_resolved,
            error_message=error_message,
            read_only_relationships=read_only_relationships,
        )
        return HttpResponse(html, status=400)
