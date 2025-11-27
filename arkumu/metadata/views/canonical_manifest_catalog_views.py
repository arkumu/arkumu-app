from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.models.resource import Resource
from arkumu.users.mixins import general_login_required
from arkumu.users.models import Organization

logger = logging.getLogger(__name__)


def _extract_uri_tail(uri: Optional[str]) -> str:
    """Extract the last segment of a URI for fallback labeling."""
    if not uri:
        return "(empty)"
    return uri.rstrip("/").split("/")[-1]


def _collect_uris_from_manifest(manifest: Dict[str, Any]) -> Set[str]:
    """Collect all URIs and canonical URIs from a manifest for bulk resolution."""
    uris = set()

    for dataset_key, dataset in manifest.items():
        if not isinstance(dataset, dict):
            continue

        entity_type = dataset.get("entity_type") or {}
        if entity_type.get("uri"):
            uris.add(entity_type["uri"])
        if entity_type.get("canonical_uri"):
            uris.add(entity_type["canonical_uri"])

        properties = dataset.get("properties") or {}
        for prop_slug, prop in properties.items():
            if not isinstance(prop, dict):
                continue
            if prop.get("uri"):
                uris.add(prop["uri"])
            if prop.get("canonical_uri"):
                uris.add(prop["canonical_uri"])

        fk_relationships = dataset.get("fk_relationships") or []
        for fk in fk_relationships:
            if not isinstance(fk, dict):
                continue
            for key in ["source_property_uri", "source_property_canonical_uri",
                       "target_property_uri", "target_property_canonical_uri"]:
                if fk.get(key):
                    uris.add(fk[key])

        relationship_contexts = dataset.get("relationship_contexts") or []
        for ctx in relationship_contexts:
            if not isinstance(ctx, dict):
                continue
            for key in ["context_property_uri", "context_property_canonical_uri",
                       "primary_property_uri", "primary_property_canonical_uri",
                       "secondary_property_uri", "secondary_property_canonical_uri"]:
                if ctx.get(key):
                    uris.add(ctx[key])

    return uris


def _build_label_map(uris: Set[str]) -> Dict[str, Dict[str, Any]]:
    """
    Build a lookup map from URIs to their labels by querying Resource.
    Returns: {uri: {"label": str, "resource": Resource or None}}
    """
    if not uris:
        return {}

    uri_list = list(uris)

    uri_resources = {
        r.uri: r
        for r in Resource.objects.filter(uri__in=uri_list).only("uri", "name", "value", "canonical_uri")
    }

    canonical_resources = {
        r.canonical_uri: r
        for r in Resource.objects.filter(canonical_uri__in=uri_list).only("uri", "name", "value", "canonical_uri")
        if r.canonical_uri
    }

    label_map = {}
    for uri in uris:
        resource = uri_resources.get(uri)
        if resource:
            label = resource.name or resource.value or _extract_uri_tail(uri)
            label_map[uri] = {"label": label, "resource": resource}
        else:
            canonical_resource = canonical_resources.get(uri)
            if canonical_resource:
                label = canonical_resource.name or canonical_resource.value or _extract_uri_tail(uri)
                label_map[uri] = {"label": label, "resource": canonical_resource}
            else:
                label_map[uri] = {"label": _extract_uri_tail(uri), "resource": None}

    return label_map


def _aggregate_org_manifests(org_code: Optional[str] = None) -> Dict[str, Any]:
    """
    Aggregate schema manifests across organizations.

    Args:
        org_code: Optional organization code filter. If None, aggregates all orgs.

    Returns:
        Dictionary with organizations, datasets, and statistics.
    """
    if org_code:
        organizations = Organization.objects.filter(code=org_code, is_active=True)
    else:
        organizations = Organization.objects.filter(is_active=True).order_by("name")

    all_uris: Set[str] = set()
    org_data_list: List[Dict[str, Any]] = []
    total_properties = 0
    total_datasets = 0
    orgs_missing_manifest = []

    for org in organizations:
        mapping = Mapping.get_active_for_organization(org)

        if not mapping:
            orgs_missing_manifest.append(org.name)
            org_data_list.append({
                "org_code": org.code,
                "org_name": org.name,
                "mapping": None,
                "manifest": None,
                "datasets": [],
                "error": "No mapping found"
            })
            continue

        manifest = (mapping.mapping_config or {}).get("schema_manifest")

        if not isinstance(manifest, dict) or not manifest:
            orgs_missing_manifest.append(org.name)
            org_data_list.append({
                "org_code": org.code,
                "org_name": org.name,
                "mapping": mapping,
                "manifest": None,
                "datasets": [],
                "error": "No schema_manifest in mapping"
            })
            continue

        org_uris = _collect_uris_from_manifest(manifest)
        all_uris.update(org_uris)

        datasets = []
        for dataset_key, dataset in sorted(manifest.items(), key=lambda x: x[0]):
            if not isinstance(dataset, dict):
                continue

            entity_type = dataset.get("entity_type") or {}
            dataset_label = (
                dataset.get("label")
                or entity_type.get("name")
                or dataset_key
            )

            properties = []
            for column_slug, prop in sorted((dataset.get("properties") or {}).items(), key=lambda x: x[0]):
                if not isinstance(prop, dict):
                    continue
                properties.append({
                    "column_slug": column_slug,
                    "name": prop.get("name", column_slug),
                    "uri": prop.get("uri"),
                    "canonical_uri": prop.get("canonical_uri"),
                })
                total_properties += 1

            fk_relationships = []
            for fk in (dataset.get("fk_relationships") or []):
                if not isinstance(fk, dict):
                    continue
                fk_relationships.append({
                    "source_property_uri": fk.get("source_property_uri"),
                    "source_property_canonical_uri": fk.get("source_property_canonical_uri"),
                    "target_property_uri": fk.get("target_property_uri"),
                    "target_property_canonical_uri": fk.get("target_property_canonical_uri"),
                    "source_dataset": fk.get("source_dataset", dataset_key),
                    "target_dataset": fk.get("target_dataset"),
                    "notes": fk.get("notes"),
                })

            relationship_contexts = []
            for ctx in (dataset.get("relationship_contexts") or []):
                if not isinstance(ctx, dict):
                    continue
                relationship_contexts.append({
                    "context_property_uri": ctx.get("context_property_uri"),
                    "context_property_canonical_uri": ctx.get("context_property_canonical_uri"),
                    "primary_property_uri": ctx.get("primary_property_uri"),
                    "primary_property_canonical_uri": ctx.get("primary_property_canonical_uri"),
                    "secondary_property_uri": ctx.get("secondary_property_uri"),
                    "secondary_property_canonical_uri": ctx.get("secondary_property_canonical_uri"),
                })

            datasets.append({
                "dataset_key": dataset_key,
                "dataset_label": dataset_label,
                "entity_type": {
                    "uri": entity_type.get("uri"),
                    "canonical_uri": entity_type.get("canonical_uri"),
                    "label": entity_type.get("name") or entity_type.get("label"),
                },
                "properties": properties,
                "fk_relationships": fk_relationships,
                "relationship_contexts": relationship_contexts,
            })
            total_datasets += 1

        org_data_list.append({
            "org_code": org.code,
            "org_name": org.name,
            "mapping": mapping,
            "manifest": manifest,
            "datasets": datasets,
            "error": None,
        })

    label_map = _build_label_map(all_uris)

    return {
        "organizations": org_data_list,
        "label_map": label_map,
        "stats": {
            "org_count": len(organizations),
            "dataset_count": total_datasets,
            "property_count": total_properties,
            "orgs_missing_manifest": orgs_missing_manifest,
        }
    }


@general_login_required
def canonical_manifest_catalog_view(request: HttpRequest) -> HttpResponse:
    """
    Display a read-only HTML page that lists the canonical schema manifest
    across all institutions with human-friendly labels resolved from Resource.
    """
    org_code = request.GET.get("org")

    data = _aggregate_org_manifests(org_code)

    context = {
        "organizations": data["organizations"],
        "label_map": data["label_map"],
        "stats": data["stats"],
        "filtered_org": org_code,
    }

    return render(request, "metadata/canonical_manifest_catalog.html", context)
