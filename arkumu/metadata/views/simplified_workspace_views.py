"""
Simplified workspace views for metadata entry.

These views use the same infrastructure as the legacy workspace
(SchemaWorkspaceService, DatasetEntityForm, relationship handling)
but only show a subset of fields for a simplified user experience.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import render
from django.views import View

from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.schema_workspace import (
    DatasetEntityForm,
    SchemaWorkspaceService,
)
from arkumu.metadata.services.entity_label_service import infer_entity_label as _infer_entity_label
from arkumu.users.models import Organization

logger = logging.getLogger(__name__)


# Define which fields to show for each entity type
SIMPLIFIED_FIELD_CONFIG = {
    "Projekt": [
        "Bevorzugter Titel",
        "Bevorzugter Untertitel",
        "Deutscher Kommentar",  # Maps to "beschreibung"
        # "Einliefernde Hochschule" - automatic based on organization
        "Organisationseinheit",
        "Projektkategorie",
        "Projektart",
        "Schlagwort",
        "Vorschaubild",
        "Ereignis",
        "Rechtsstatus",
        "Projekterstellung beim Einlieferer",
        "Letzte Projektmodifikation beim Einlieferer",
        "Signatur beim Einlieferer",
        "Werkverzeichnis-Nummer",
    ],
}


def _get_organization(request: HttpRequest) -> Optional[Organization]:
    """Get organization from user or from URI parameter."""
    # First try user's organization
    organization = getattr(request.user, "organization", None)

    # If editing, extract org from URI
    entity_uri = request.GET.get("uri", "")
    if entity_uri and "/data/" in entity_uri:
        uri_parts = entity_uri.split("/")
        if len(uri_parts) >= 6 and uri_parts[3] == "data":
            uri_org_code = uri_parts[4]
            uri_organization = Organization.objects.filter(code=uri_org_code).first()
            if uri_organization:
                organization = uri_organization
                logger.info(f"Using organization from URI: {organization.code}")

    return organization


def _get_schema_service(request: HttpRequest) -> Optional[SchemaWorkspaceService]:
    """Get SchemaWorkspaceService for the current organization."""
    organization = _get_organization(request)
    if not organization:
        return None

    mapping = Mapping.objects.filter(organization_id=organization.code).order_by("-created_at").first()
    if not mapping:
        logger.error(f"No mapping found for organization {organization.code}")
        return None

    logger.info(f"Using mapping {mapping.id} for organization {organization.code}")
    return SchemaWorkspaceService(mapping=mapping, organization=organization)


def _filter_field_metadata(
    field_metadata: Dict[str, Any],
    visible_fields: List[str]
) -> Dict[str, Any]:
    """Filter field metadata to only include visible fields."""
    filtered = {}
    for field_name, metadata in field_metadata.items():
        if field_name in visible_fields:
            filtered[field_name] = metadata
        else:
            logger.debug(f"Hiding field: {field_name}")

    logger.info(f"Filtered {len(field_metadata)} fields to {len(filtered)} visible fields")
    return filtered


def _enrich_fk_metadata(
    form: DatasetEntityForm,
    field_metadata: Dict[str, Any],
    schema_service: SchemaWorkspaceService,
    dataset_name: str,
) -> List[Dict[str, Any]]:
    """
    Enrich FK field metadata with resolved labels and search URLs.

    This mirrors the logic from schema_workspace_views.py lines 419-620.
    For single FK fields, resolves the URI to a human-readable label
    and provides search/autocomplete functionality.
    """
    from django.urls import reverse
    from django.utils.http import urlencode
    from django.utils.text import slugify

    fields_with_metadata: List[Dict[str, Any]] = []

    # Build base suggestion URL for autocomplete
    base_suggestion_url = reverse(
        "metadata:entity_workspace_field_values",
        args=[schema_service.mapping.id],
    )

    for index, field in enumerate(form):
        meta = dict(field_metadata.get(field.name, {}))
        fk_info = meta.get("fk_relationship") or {}
        target_dataset = fk_info.get("target_dataset") if fk_info else None

        # Build search properties for target dataset
        if target_dataset:
            try:
                target_schema = schema_service.get_dataset_schema(target_dataset)
                properties: List[Dict[str, str]] = []
                for column, prop in (target_schema.get("properties", {}) or {}).items():
                    uri = getattr(prop, "uri", None)
                    if not uri:
                        continue
                    label = getattr(prop, "name", column) or column
                    properties.append({"uri": uri, "label": label, "column": column})
                properties.sort(key=lambda item: item["label"].lower())
                meta["search_properties"] = properties
            except ValueError:
                logger.warning(f"Could not load schema for target dataset: {target_dataset}")
                meta["search_properties"] = []

        # Build search URL and target ID for autocomplete
        search_url: Optional[str] = None
        target_id: Optional[str] = None

        if fk_info:
            target_id = f"field-suggestions-{index}-{slugify(field.name) or index}"
            input_id = field.auto_id or f"id_{slugify(field.name) or index}"
            meta["input_id"] = input_id
            meta["target_id"] = target_id

            base_params = {"dataset": dataset_name, "column": field.name}
            base_url = f"{base_suggestion_url}?{urlencode(base_params)}"
            query_params = {"input_id": input_id, "target_id": target_id}
            search_url = base_url + "&" + urlencode(query_params)
            meta["search_url"] = search_url
            meta["base_suggestion_url"] = base_url
            logger.info(f"🔍 FK field '{field.name}': search_url={search_url}, target_id={target_id}")

        # Handle single FK fields (not multi-value)
        if fk_info and not meta.get("is_multi_value"):
            raw_value = form.initial.get(field.name, field.value())
            if raw_value:
                display_prop_uri = meta.get("display_property")

                # Auto-select best display property if not set
                if not display_prop_uri and target_dataset:
                    preferred_names = ["name", "titel", "title", "label", "bezeichnung", "beschreibung"]
                    for prop in meta.get("search_properties", []):
                        prop_name_lower = prop.get("column", "").lower()
                        if any(pref in prop_name_lower for pref in preferred_names):
                            display_prop_uri = prop.get("uri")
                            meta["display_property"] = display_prop_uri
                            meta["display_property_label"] = prop.get("label")
                            logger.info(f"Auto-selected display property for {field.name}: {meta['display_property_label']}")
                            break

                # Resolve URI to human-readable label
                resolved_label = _infer_entity_label(
                    schema_service,
                    str(raw_value),
                    target_dataset,
                    display_property_uri=display_prop_uri,
                )

                if resolved_label and resolved_label != raw_value:
                    meta["resolved_label"] = resolved_label
                    meta["resolved_uri"] = str(raw_value)
                    form.initial[field.name] = resolved_label
                    if field.name in form.fields:
                        form.fields[field.name].initial = resolved_label

                    logger.info(f"✅ Resolved FK field '{field.name}': {raw_value} → {resolved_label}")

        fields_with_metadata.append({
            "field": field,
            "meta": meta,
            "search_url": search_url,
            "target_id": target_id,
        })

    return fields_with_metadata


class SimplifiedProjectEditView(LoginRequiredMixin, View):
    """
    Simplified project edit view using legacy workspace infrastructure.

    Shows only a subset of fields but uses the same relationship handling,
    URI resolution, and search capabilities as the full workspace.
    """

    def get(self, request: HttpRequest) -> HttpResponse:
        """Render the edit form with existing project data."""
        schema_service = _get_schema_service(request)
        if not schema_service:
            return HttpResponseRedirect("/metadata/metadata-entry/")

        entity_uri = request.GET.get("uri", "")
        if not entity_uri:
            return HttpResponseBadRequest("Missing uri parameter")

        dataset_name = "Projekt"
        visible_fields = SIMPLIFIED_FIELD_CONFIG.get(dataset_name, [])

        # Get field metadata from schema
        field_metadata = schema_service.get_field_metadata(dataset_name)
        field_metadata, join_field_map = schema_service.augment_field_metadata_with_joins(
            dataset_name,
            field_metadata,
        )

        # Filter to only show simplified fields
        field_metadata = _filter_field_metadata(field_metadata, visible_fields)

        # Load existing entity data (same as legacy workspace)
        initial_data: Optional[Dict[str, object]] = None
        entity_label: Optional[str] = None
        load_error = False

        try:
            logger.info(f"=" * 80)
            logger.info(f"Loading project: {entity_uri}")
            logger.info(f"=" * 80)

            loaded = schema_service.load_entity_by_uri(dataset_name, entity_uri)
            if loaded:
                initial_data = loaded
                entity_label = _infer_entity_label(schema_service, entity_uri, dataset_name)
                logger.info(f"✅ Loaded {len(loaded)} fields")
                logger.info(f"   Entity label: {entity_label}")
            else:
                load_error = True
                logger.warning(f"❌ No data loaded for {entity_uri}")
        except Exception as e:
            load_error = True
            logger.exception(f"❌ Error loading project: {e}")

        # Create form with loaded data (same as legacy workspace)
        form = DatasetEntityForm(
            field_metadata=field_metadata,
            initial=initial_data,
            disable_anchors=True,  # We're editing, not creating
        )

        # Collect relationship values (same as legacy workspace)
        read_only_relationships: List[Dict[str, Any]] = []
        if entity_uri:
            relationships = schema_service.collect_relationship_values(
                dataset_name=dataset_name,
                entity_uri=entity_uri,
                field_metadata=field_metadata,
                join_field_map=join_field_map,
            )
            # Apply relationship initial values to form
            from arkumu.metadata.views.schema_workspace_views import _apply_relationship_initials
            read_only_relationships = _apply_relationship_initials(
                service=schema_service,
                form=form,
                relationships=relationships,
            )

        # Enrich FK field metadata with resolved labels (same as legacy workspace)
        fields_with_metadata = _enrich_fk_metadata(
            form=form,
            field_metadata=field_metadata,
            schema_service=schema_service,
            dataset_name=dataset_name,
        )

        # Render the form
        context = {
            "form": form,
            "fields_with_metadata": fields_with_metadata,
            "entity_uri": entity_uri,
            "entity_label": entity_label,
            "dataset_name": dataset_name,
            "load_error": load_error,
            "read_only_relationships": read_only_relationships,
            "title": "Projekt bearbeiten",
            "description": "Aktualisiere die wichtigsten Angaben für dieses Projekt.",
        }

        return render(request, "metadata/simplified_workspace/edit_project.html", context)

    def post(self, request: HttpRequest) -> HttpResponse:
        """Save the edited project data."""
        schema_service = _get_schema_service(request)
        if not schema_service:
            return HttpResponseRedirect("/metadata/metadata-entry/")

        dataset_name = "Projekt"
        entity_uri = request.POST.get("entity_uri") or None

        if not entity_uri:
            return HttpResponseBadRequest("Missing entity_uri")

        # Get field metadata
        field_metadata = schema_service.get_field_metadata(dataset_name)
        visible_fields = SIMPLIFIED_FIELD_CONFIG.get(dataset_name, [])
        field_metadata = _filter_field_metadata(field_metadata, visible_fields)

        # Create form with POST data
        form = DatasetEntityForm(
            request.POST,
            field_metadata=field_metadata,
            disable_anchors=True,
        )

        if form.is_valid():
            try:
                entity_data = form.cleaned_entity_data()

                # Save using schema service (same as legacy workspace)
                saved_uri, created = schema_service.save_entity(
                    dataset_name=dataset_name,
                    entity_data=entity_data,
                    entity_uri=entity_uri,
                )

                logger.info(f"✅ Saved project: {saved_uri} (created={created})")

                # Redirect back to metadata entry
                return HttpResponseRedirect("/metadata/metadata-entry/?organization=" + schema_service.organization.code)

            except Exception as e:
                logger.exception(f"❌ Error saving project: {e}")
                # Re-render form with error
                context = {
                    "form": form,
                    "entity_uri": entity_uri,
                    "dataset_name": dataset_name,
                    "error": str(e),
                    "title": "Projekt bearbeiten",
                }
                return render(request, "metadata/simplified_workspace/edit_project.html", context)

        else:
            # Form validation failed
            logger.warning(f"Form validation failed: {form.errors}")
            context = {
                "form": form,
                "entity_uri": entity_uri,
                "dataset_name": dataset_name,
                "title": "Projekt bearbeiten",
            }
            return render(request, "metadata/simplified_workspace/edit_project.html", context)
