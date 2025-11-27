"""
CSV Mapping Canonical Property Views

Provides inline configuration of canonical property mappings for workspace
columns in the CSV mapping editor. This is intentionally kept separate from
the schema_manifest pipeline: selections here are stored alongside the
mapping configuration without mutating the manifest built by imports.
"""

import logging

from django.http import HttpResponse
from django.shortcuts import render
from django.views import View

from arkumu.users.mixins import GeneralLoginRequiredMixin
from arkumu.metadata.views.csv_mapping.mixins.coordinator import CSVMappingCoordinatorMixin
from arkumu.metadata.views.csv_mapping.mixins.template_helpers import CSVMappingTemplateHelperMixin
from arkumu.metadata.views.canonical_graph_views import _get_canonical_property_catalog

logger = logging.getLogger(__name__)


def _build_canonical_property_index(catalog):
    """
    Build a lookup index from canonical property URI to labels and class URI.

    Args:
        catalog (list): Canonical catalog as returned by _get_canonical_property_catalog

    Returns:
        dict: {property_uri: {"property_label": str, "class_uri": str, "class_label": str}}
    """
    index = {}
    for cls in catalog or []:
        class_uri = cls.get("uri")
        class_label = cls.get("label") or (class_uri.rsplit("/", 1)[-1] if class_uri else "")
        for prop in cls.get("properties", []):
            uri = prop.get("uri")
            if not uri:
                continue
            label = prop.get("label") or uri.rsplit("/", 1)[-1]
            index[uri] = {
                "property_label": label,
                "class_uri": class_uri,
                "class_label": class_label,
            }
    return index


class ToggleCanonicalMappingFormView(
    GeneralLoginRequiredMixin,
    CSVMappingCoordinatorMixin,
    CSVMappingTemplateHelperMixin,
    View,
):
    """
    Toggle canonical property configuration form for a workspace column.
    """

    def post(self, request):
        try:
            current_org = self.get_current_organization(request)
            if not current_org:
                return HttpResponse("No organization selected", status=400)
            organization_id = current_org["code"]

            column_id = request.POST.get("column_id") or request.GET.get("column_id")
            if not column_id:
                return HttpResponse('<div class="text-error text-sm">Column ID required</div>')

            logger.info("CSV_TOGGLE_CANONICAL_FORM: column_id='%s', org='%s'", column_id, organization_id)

            column = self.get_unified_column_by_id(request, organization_id, column_id)
            if not column:
                logger.error("CSV_TOGGLE_CANONICAL_FORM: Column '%s' not found", column_id)
                return HttpResponse('<div class="text-error text-sm">Column not found in workspace</div>')

            canonical_mapping = column.get("canonical_mapping") or {}
            catalog = _get_canonical_property_catalog(None)

            context = {
                "column": column,
                "organization_id": organization_id,
                "canonical_mapping": canonical_mapping,
                "canonical_catalog": catalog,
                "csrf_token": request.META.get("CSRF_COOKIE"),
            }

            return render(
                request,
                "csv_mapping/partials/inline_canonical_mapping_form.html",
                context,
            )
        except Exception as exc:  # pragma: no cover - defensive branch
            logger.error("CSV_TOGGLE_CANONICAL_FORM: Error toggling form: %s", exc, exc_info=True)
            return HttpResponse(
                '<div class="text-error text-sm">Error opening canonical mapping configuration</div>'
            )


class SaveCanonicalMappingView(
    GeneralLoginRequiredMixin,
    CSVMappingCoordinatorMixin,
    CSVMappingTemplateHelperMixin,
    View,
):
    """
    Persist canonical property mapping for a workspace column.

    The selected canonical URI must exist in the canonical property catalog;
    arbitrary URIs are rejected.
    """

    def post(self, request):
        try:
            current_org = self.get_current_organization(request)
            if not current_org:
                return HttpResponse("No organization selected", status=400)
            organization_id = current_org["code"]

            column_id = request.POST.get("column_id")
            canonical_property_uri = (request.POST.get("canonical_property_uri") or "").strip()

            logger.info(
                "CSV_SAVE_CANONICAL_MAPPING: column_id='%s', canonical_property_uri='%s', org='%s'",
                column_id,
                canonical_property_uri,
                organization_id,
            )

            if not column_id:
                return HttpResponse('<div class="text-error text-xs p-2">Column ID required</div>')
            if not canonical_property_uri:
                return HttpResponse(
                    '<div class="text-error text-xs p-2">Canonical property selection is required</div>'
                )

            catalog = _get_canonical_property_catalog(None)
            index = _build_canonical_property_index(catalog)
            meta = index.get(canonical_property_uri)
            if not meta:
                logger.error(
                    "CSV_SAVE_CANONICAL_MAPPING: Unknown canonical property URI '%s' for org '%s'",
                    canonical_property_uri,
                    organization_id,
                )
                return HttpResponse(
                    '<div class="text-error text-xs p-2">Invalid canonical property selection</div>'
                )

            existing_columns = self.get_workspace_columns(request, organization_id)
            updated_column = None

            for col in existing_columns:
                if col.get("id") == column_id:
                    col["is_canonical_mapped"] = True
                    col["canonical_mapping"] = {
                        "canonical_property_uri": canonical_property_uri,
                        "canonical_property_label": meta["property_label"],
                        "canonical_class_uri": meta["class_uri"],
                        "canonical_class_label": meta["class_label"],
                        "source": "manual",
                    }
                    updated_column = col
                    logger.info(
                        "CSV_SAVE_CANONICAL_MAPPING: ✅ Set canonical mapping for column '%s' to '%s'",
                        column_id,
                        canonical_property_uri,
                    )
                    break

            if not updated_column:
                logger.error(
                    "CSV_SAVE_CANONICAL_MAPPING: Column '%s' not found in workspace for org '%s'",
                    column_id,
                    organization_id,
                )
                return HttpResponse('<div class="text-error text-xs p-2">Column not found in workspace</div>')

            self.update_workspace_columns(request, organization_id, existing_columns)

            column_html = self.render_column_item_template(request, organization_id, updated_column)
            return HttpResponse(column_html)
        except Exception as exc:  # pragma: no cover - defensive branch
            logger.error("CSV_SAVE_CANONICAL_MAPPING: Error saving configuration: %s", exc, exc_info=True)
            return HttpResponse(
                '<div class="text-error text-xs p-2">Error saving canonical mapping configuration</div>'
            )


class RemoveCanonicalMappingView(
    GeneralLoginRequiredMixin,
    CSVMappingCoordinatorMixin,
    CSVMappingTemplateHelperMixin,
    View,
):
    """
    Remove canonical property mapping from a workspace column.
    """

    def post(self, request):
        try:
            current_org = self.get_current_organization(request)
            if not current_org:
                return HttpResponse("No organization selected", status=400)
            organization_id = current_org["code"]

            column_id = request.POST.get("column_id")
            logger.info("CSV_REMOVE_CANONICAL_MAPPING: column_id='%s', org='%s'", column_id, organization_id)

            if not column_id:
                return HttpResponse('<div class="text-error text-xs p-2">Column ID required</div>')

            existing_columns = self.get_workspace_columns(request, organization_id)
            updated_column = None

            for col in existing_columns:
                if col.get("id") == column_id:
                    col.pop("canonical_mapping", None)
                    col["is_canonical_mapped"] = False
                    updated_column = col
                    logger.info(
                        "CSV_REMOVE_CANONICAL_MAPPING: ✅ Removed canonical mapping from column '%s'", column_id
                    )
                    break

            if not updated_column:
                logger.error(
                    "CSV_REMOVE_CANONICAL_MAPPING: Column '%s' not found in workspace for org '%s'",
                    column_id,
                    organization_id,
                )
                return HttpResponse('<div class="text-error text-xs p-2">Column not found in workspace</div>')

            self.update_workspace_columns(request, organization_id, existing_columns)
            column_html = self.render_column_item_template(request, organization_id, updated_column)
            return HttpResponse(column_html)
        except Exception as exc:  # pragma: no cover - defensive branch
            logger.error("CSV_REMOVE_CANONICAL_MAPPING: Error removing configuration: %s", exc, exc_info=True)
            return HttpResponse(
                '<div class="text-error text-xs p-2">Error removing canonical mapping configuration</div>'
            )


class HideCanonicalMappingFormView(
    GeneralLoginRequiredMixin,
    CSVMappingCoordinatorMixin,
    View,
):
    """
    Hide canonical mapping form for a column.
    """

    def get(self, request):
        try:
            column_id = request.GET.get("column_id")
            logger.info("CSV_HIDE_CANONICAL_FORM: column='%s'", column_id)

            from django.utils.text import slugify

            slugified_id = slugify(column_id) if column_id else "unknown"
            return HttpResponse(f'<div id="canonical-form-{slugified_id}"></div>')
        except Exception as exc:  # pragma: no cover - defensive branch
            logger.error("CSV_HIDE_CANONICAL_FORM: Error hiding form: %s", exc, exc_info=True)
            return HttpResponse(
                '<div class="text-error text-sm">Error hiding canonical mapping form</div>'
            )

