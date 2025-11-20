from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Dict, List, Optional

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from arkumu.metadata.models.mappings import Mapping
from arkumu.projects.schema_manifest_canonical import CANONICAL_PROPERTY_REGISTRY
from arkumu.users.mixins import general_login_required
from arkumu.users.models import Organization


logger = logging.getLogger(__name__)
SUPPORTED_ORGS = ("khm", "hmt")


def _get_supported_organizations() -> List[Organization]:
    return list(Organization.objects.filter(code__in=SUPPORTED_ORGS).order_by("name"))


def _extract_manifest(mapping: Optional[Mapping]) -> Dict[str, Any]:
    if not mapping:
        return {}
    manifest = (mapping.mapping_config or {}).get("schema_manifest")
    return manifest if isinstance(manifest, dict) else {}


def _build_selector_context(
    organization_code: Optional[str],
    *,
    mapping_id: Optional[str] = None,
) -> Dict[str, Any]:
    mappings: List[Mapping] = []
    if organization_code:
        mappings = list(
            Mapping.objects.filter(organization_id=organization_code)
            .order_by("-is_active", "-created_at")
            .all()
        )

    selected_mapping: Optional[Mapping] = None
    if mapping_id:
        selected_mapping = next(
        (m for m in mappings if str(m.id) == str(mapping_id)),
        None,
    )
    if not selected_mapping and mappings:
        selected_mapping = mappings[0]

    return {
        "mappings": mappings,
        "selected_mapping": selected_mapping,
        "selected_mapping_id": str(selected_mapping.id) if selected_mapping else None,
        "has_manifest": bool(_extract_manifest(selected_mapping)),
    }


def _build_manifest_tree_summary(manifest: Dict[str, Any]) -> Dict[str, Any]:
    canonical_classes: Dict[str, Dict[str, Any]] = {}
    datasets: List[Dict[str, Any]] = []
    total_columns = 0
    mapped_columns = 0
    unmapped_columns: List[Dict[str, str]] = []
    for dataset_name, dataset in sorted(manifest.items(), key=lambda item: item[0].lower()):
        entity_type = dataset.get("entity_type") or {}
        canonical_class_uri = entity_type.get("canonical_uri")
        dataset_label = (
            dataset.get("label")
            or entity_type.get("name")
            or dataset.get("name")
            or dataset_name
        )
        dataset_entry = {
            "name": dataset_name,
            "label": dataset_label,
            "canonical_uri": canonical_class_uri,
            "columns": [],
            "unmapped_columns": [],
        }
        datasets.append(dataset_entry)

        if canonical_class_uri:
            cls_entry = canonical_classes.setdefault(
                canonical_class_uri,
                {
                    "uri": canonical_class_uri,
                    "label": entity_type.get("canonical_label") or entity_type.get("name") or canonical_class_uri.rsplit("/", 1)[-1],
                    "datasets": set(),
                    "properties": {},
                },
            )
            cls_entry["datasets"].add(dataset_name)

        properties = dataset.get("properties") or {}
        column_meta = dataset.get("column_metadata") or {}
        for slug, prop in sorted(properties.items(), key=lambda item: item[0].lower()):
            column_info = {
                "slug": slug,
                "label": prop.get("name") or slug,
                "canonical_uri": prop.get("canonical_uri"),
                "uri": prop.get("uri"),
                "metadata": column_meta.get(slug, {}),
            }
            dataset_entry["columns"].append(column_info)
            total_columns += 1
            if column_info["canonical_uri"]:
                mapped_columns += 1
            else:
                missing_entry = {
                    "dataset": dataset_name,
                    "column": slug,
                    "label": column_info["label"],
                }
                dataset_entry["unmapped_columns"].append(missing_entry)
                unmapped_columns.append(missing_entry)

            canonical_prop = prop.get("canonical_uri")
            if canonical_class_uri and canonical_prop:
                cls_entry = canonical_classes.setdefault(
                    canonical_class_uri,
                    {
                        "uri": canonical_class_uri,
                        "label": entity_type.get("canonical_label") or entity_type.get("name") or canonical_class_uri.rsplit("/", 1)[-1],
                        "datasets": set(),
                        "properties": {},
                    },
                )
                prop_entry = cls_entry["properties"].setdefault(
                    canonical_prop,
                    {
                        "uri": canonical_prop,
                        "label": prop.get("canonical_label") or prop.get("name") or canonical_prop.rsplit("/", 1)[-1],
                        "columns": [],
                    },
                )
                prop_entry["columns"].append(
                    {
                        "dataset": dataset_name,
                        "column": slug,
                        "label": prop.get("name") or slug,
                        "metadata": column_meta.get(slug, {}),
                    }
                )

    canonical_class_list: List[Dict[str, Any]] = []
    for cls in canonical_classes.values():
        canonical_class_list.append(
            {
                "uri": cls["uri"],
                "label": cls["label"],
                "dataset_count": len(cls["datasets"]),
                "properties": [
                    {
                        "uri": prop["uri"],
                        "label": prop["label"],
                        "columns": prop["columns"],
                    }
                    for prop in sorted(cls["properties"].values(), key=lambda p: p["label"])
                ],
            }
        )

    dataset_list = [
        {
            "name": dataset["name"],
            "label": dataset["label"],
            "canonical_uri": dataset["canonical_uri"],
            "column_count": len(dataset["columns"]),
            "columns": dataset["columns"],
            "unmapped_count": len(dataset["unmapped_columns"]),
            "unmapped_columns": dataset["unmapped_columns"],
        }
        for dataset in datasets
    ]

    canonical_class_list.sort(key=lambda cls: cls["label"].lower())
    dataset_list.sort(key=lambda ds: ds["label"].lower())

    return {
        "canonical_classes": canonical_class_list,
        "datasets": dataset_list,
        "stats": {
            "dataset_count": len(dataset_list),
            "total_columns": total_columns,
            "mapped_columns": mapped_columns,
            "unmapped_columns": max(total_columns - mapped_columns, 0),
        },
        "unmapped_columns": unmapped_columns,
    }


def _resolve_mapping_and_manifest(
    org_code: Optional[str],
    mapping_id: Optional[str],
) -> tuple[Optional[Mapping], Dict[str, Any]]:
    mapping = None
    if mapping_id:
        qs = Mapping.objects.all()
        if org_code:
            qs = qs.filter(organization_id=org_code)
        mapping = qs.filter(id=mapping_id).first()
        if not mapping:
            mapping = Mapping.objects.filter(id=mapping_id).first()
    manifest = _extract_manifest(mapping)
    return mapping, manifest


@general_login_required
def canonical_manifest_graph_view(request: HttpRequest) -> HttpResponse:
    organizations = _get_supported_organizations()
    selected_org = request.GET.get("organization") or (organizations[0].code if organizations else None)
    selector_context = _build_selector_context(
        selected_org,
        mapping_id=request.GET.get("mapping_id"),
    )

    context = {
        "organizations": organizations,
        "selected_org_code": selected_org,
        **selector_context,
        "view_mode": request.GET.get("view_mode", "dataset"),
    }
    return render(request, "metadata/canonical_manifest_graph.html", context)


@general_login_required
def canonical_graph_selectors(request: HttpRequest) -> HttpResponse:
    organization_code = request.GET.get("organization")
    context = _build_selector_context(
        organization_code,
        mapping_id=request.GET.get("mapping_id"),
    )
    context["selected_org_code"] = organization_code
    return render(request, "metadata/partials/canonical_graph_selectors.html", context)


@general_login_required
@require_http_methods(["GET", "POST"])
def canonical_graph_render(request: HttpRequest) -> HttpResponse:
    org_code = request.POST.get("organization") or request.GET.get("organization")
    mapping_id = request.POST.get("mapping_id") or request.GET.get("mapping_id")

    mapping = None
    if mapping_id:
        qs = Mapping.objects.all()
        if org_code:
            qs = qs.filter(organization_id=org_code)
        mapping = qs.filter(id=mapping_id).first()
        if not mapping:
            mapping = Mapping.objects.filter(id=mapping_id).first()
    manifest = _extract_manifest(mapping)

    error: Optional[str] = None
    tree_summary: Optional[Dict[str, Any]] = None

    if not mapping:
        error = "Select an organization mapping to generate a visualization."
    elif not manifest:
        error = "The selected mapping does not include a schema_manifest entry."
    else:
        tree_summary = _build_manifest_tree_summary(manifest)

    context = {
        "tree_summary": tree_summary if tree_summary and not error else None,
        "error": error,
        "mapping": mapping,
        "organization_code": org_code or (mapping.organization_id if mapping else None),
    }
    return render(request, "metadata/partials/canonical_graph_tree_result.html", context)


@general_login_required
def canonical_graph_tree_canonical(request: HttpRequest) -> HttpResponse:
    org_code = request.GET.get("organization")
    mapping_id = request.GET.get("mapping_id")
    class_uri = request.GET.get("class_uri")
    mapping, manifest = _resolve_mapping_and_manifest(org_code, mapping_id)
    if not mapping or not manifest or not class_uri:
        return render(
            request,
            "metadata/partials/canonical_tree_class_children.html",
            {"class_info": None},
        )
    summary = _build_manifest_tree_summary(manifest)
    class_info = next((cls for cls in summary["canonical_classes"] if cls["uri"] == class_uri), None)
    return render(
        request,
        "metadata/partials/canonical_tree_class_children.html",
        {"class_info": class_info},
    )


@general_login_required
def canonical_graph_tree_dataset(request: HttpRequest) -> HttpResponse:
    org_code = request.GET.get("organization")
    mapping_id = request.GET.get("mapping_id")
    dataset_name = request.GET.get("dataset_name")
    dataset_dom_id = request.GET.get("target_id")
    mapping, manifest = _resolve_mapping_and_manifest(org_code, mapping_id)
    if not mapping or not manifest or not dataset_name:
        return render(
            request,
            "metadata/partials/canonical_tree_dataset_children.html",
            {"dataset": None},
        )
    summary = _build_manifest_tree_summary(manifest)
    dataset = next((ds for ds in summary["datasets"] if ds["name"] == dataset_name), None)
    return render(
        request,
        "metadata/partials/canonical_tree_dataset_children.html",
        {
            "dataset": dataset,
            "dataset_dom_id": dataset_dom_id,
            "organization_code": org_code or mapping.organization_id,
            "mapping": mapping,
        },
    )


@general_login_required
def canonical_graph_tree_edit_column(request: HttpRequest) -> HttpResponse:
    org_code = request.GET.get("organization")
    mapping_id = request.GET.get("mapping_id")
    dataset_name = request.GET.get("dataset_name")
    column_slug = request.GET.get("column_slug")
    dataset_dom_id = request.GET.get("target_id")

    mapping, manifest = _resolve_mapping_and_manifest(org_code, mapping_id)
    if not mapping or not manifest or not dataset_name or not column_slug:
        return render(
            request,
            "metadata/partials/canonical_tree_edit_column.html",
            {"form_error": "Column context missing."},
        )

    dataset = manifest.get(dataset_name)
    if not dataset:
        return render(
            request,
            "metadata/partials/canonical_tree_edit_column.html",
            {"form_error": f"Dataset '{dataset_name}' not found."},
        )
    properties = dataset.get("properties") or {}
    column = properties.get(column_slug)
    if not column:
        return render(
            request,
            "metadata/partials/canonical_tree_edit_column.html",
            {"form_error": f"Column '{column_slug}' not found in dataset '{dataset_name}'."},
        )

    summary = _build_manifest_tree_summary(manifest)
    context = {
        "mapping": mapping,
        "organization_code": org_code or mapping.organization_id,
        "dataset_name": dataset_name,
        "column_slug": column_slug,
        "column": column,
        "dataset_dom_id": dataset_dom_id,
        "canonical_catalog": _get_canonical_property_catalog(dataset.get("entity_type", {}).get("canonical_uri")),
    }
    return render(request, "metadata/partials/canonical_tree_edit_column.html", context)


@general_login_required
@require_http_methods(["POST"])
def canonical_graph_tree_update_column(request: HttpRequest) -> HttpResponse:
    org_code = request.POST.get("organization")
    mapping_id = request.POST.get("mapping_id")
    dataset_name = request.POST.get("dataset_name")
    column_slug = request.POST.get("column_slug")
    dataset_dom_id = request.POST.get("target_id")
    canonical_uri = (request.POST.get("canonical_uri") or "").strip() or None

    mapping, manifest = _resolve_mapping_and_manifest(org_code, mapping_id)
    if not mapping or not manifest or not dataset_name or not column_slug:
        return render(
            request,
            "metadata/partials/canonical_tree_edit_column.html",
            {"form_error": "Update failed: missing dataset or column context."},
        )

    config = mapping.mapping_config or {}
    manifest_config = config.get("schema_manifest") or {}
    dataset_config = manifest_config.get(dataset_name)
    if not dataset_config:
        return render(
            request,
            "metadata/partials/canonical_tree_edit_column.html",
            {"form_error": f"Dataset '{dataset_name}' not found."},
        )
    property_config = (dataset_config.get("properties") or {}).get(column_slug)
    if not property_config:
        return render(
            request,
            "metadata/partials/canonical_tree_edit_column.html",
            {"form_error": f"Column '{column_slug}' not found in dataset '{dataset_name}'."},
        )

    property_config["canonical_uri"] = canonical_uri
    mapping.mapping_config = config
    mapping.save(update_fields=["mapping_config"])

    summary = _build_manifest_tree_summary(manifest_config)
    dataset_summary = next((ds for ds in summary["datasets"] if ds["name"] == dataset_name), None)

    return render(
        request,
        "metadata/partials/canonical_tree_dataset_children.html",
        {
            "dataset": dataset_summary,
            "dataset_dom_id": dataset_dom_id,
            "organization_code": org_code or mapping.organization_id,
            "mapping": mapping,
        },
    )


@lru_cache(maxsize=1)
def _base_canonical_property_catalog() -> List[Dict[str, Any]]:
    catalog: List[Dict[str, Any]] = []
    for class_uri, props in CANONICAL_PROPERTY_REGISTRY.items():
        entries = [
            {
                "uri": prop_uri,
                "label": prop_uri.rstrip("/").split("/")[-1].replace("-", " ").title(),
            }
            for prop_uri in sorted(props.keys())
        ]
        class_label = class_uri.rstrip("/").split("/")[-1].replace("-", " ").title()
        catalog.append(
            {
                "uri": class_uri,
                "label": class_label,
                "properties": entries,
            }
        )
    catalog.sort(key=lambda item: item["label"].lower())
    return catalog


def _get_canonical_property_catalog(preferred_class_uri: Optional[str]) -> List[Dict[str, Any]]:
    base_catalog = _base_canonical_property_catalog()
    catalog = [
        {"uri": entry["uri"], "label": entry["label"], "properties": list(entry["properties"])}
        for entry in base_catalog
    ]
    if preferred_class_uri:
        catalog.sort(key=lambda item: (0 if item["uri"] == preferred_class_uri else 1, item["label"].lower()))
    return catalog
