from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple
from collections import defaultdict

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.db.models import Q, Prefetch, Count

from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.users.mixins import general_login_required
from arkumu.users.models import Organization

logger = logging.getLogger(__name__)


def _get_canonical_entity_types_with_relationships(manifest: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Extract canonical entity types and their relationships from schema manifest.
    Returns: {canonical_uri: {label, local_datasets, properties, fk_relationships, relationship_contexts}}
    """
    entity_types = {}

    for dataset_key, dataset in manifest.items():
        if not isinstance(dataset, dict):
            continue

        entity_type = dataset.get("entity_type") or {}
        canonical_uri = entity_type.get("canonical_uri")

        if canonical_uri:
            if canonical_uri not in entity_types:
                entity_types[canonical_uri] = {
                    "canonical_uri": canonical_uri,
                    "label": entity_type.get("name") or entity_type.get("label") or canonical_uri.rsplit("/", 1)[-1],
                    "local_datasets": [],
                    "properties": {},
                    "fk_relationships": [],
                    "relationship_contexts": [],
                }
            entity_types[canonical_uri]["local_datasets"].append(dataset_key)

            # Collect canonical property mappings
            properties = dataset.get("properties") or {}
            for prop_slug, prop in properties.items():
                if not isinstance(prop, dict):
                    continue
                canonical_prop_uri = prop.get("canonical_uri")
                if canonical_prop_uri:
                    entity_types[canonical_uri]["properties"][canonical_prop_uri] = {
                        "label": prop.get("name") or prop_slug,
                        "local_uri": prop.get("uri"),
                    }

            # Collect FK relationships
            fk_relationships = dataset.get("fk_relationships") or []
            for fk in fk_relationships:
                if not isinstance(fk, dict):
                    continue
                entity_types[canonical_uri]["fk_relationships"].append({
                    "source_canonical_uri": fk.get("source_property_canonical_uri"),
                    "target_canonical_uri": fk.get("target_property_canonical_uri"),
                    "target_dataset": fk.get("target_dataset"),
                    "notes": fk.get("notes"),
                })

            # Collect relationship contexts
            relationship_contexts = dataset.get("relationship_contexts") or []
            for ctx in relationship_contexts:
                if not isinstance(ctx, dict):
                    continue
                entity_types[canonical_uri]["relationship_contexts"].append({
                    "context_canonical_uri": ctx.get("context_property_canonical_uri"),
                    "primary_canonical_uri": ctx.get("primary_property_canonical_uri"),
                    "secondary_canonical_uri": ctx.get("secondary_property_canonical_uri"),
                })

    return entity_types


def _get_entities_basic(
    org: Organization,
    canonical_type_uri: str,
    type_info: Dict[str, Any],
    limit: Optional[int] = None,
    offset: int = 0,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Query basic entity information WITHOUT relationships (fast initial load).
    Returns: (entities_list, total_count)
    """
    entities = []

    # Find resources that are typed with this canonical URI
    type_predicate_uri = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

    # First, get total count
    base_query = Triple.objects.filter(
        subject__organization=org,
        predicate__uri=type_predicate_uri,
        object__canonical_uri=canonical_type_uri
    )
    total_count = base_query.count()

    # Optimize: Use select_related and only get what we need, with pagination
    typed_triples_query = base_query.select_related('subject').only(
        'subject__id', 'subject__name', 'subject__value', 'subject__uri'
    )

    # Apply pagination
    if limit:
        typed_triples_query = typed_triples_query[offset:offset + limit]

    typed_triples = list(typed_triples_query)
    entity_resources = {triple.subject for triple in typed_triples}

    # Batch fetch all property triples for these entities
    entity_ids = [r.id for r in entity_resources]

    # Optimize: Prefetch all triples at once
    all_property_triples = Triple.objects.filter(
        subject_id__in=entity_ids
    ).exclude(
        predicate__uri=type_predicate_uri
    ).select_related('predicate', 'object').only(
        'subject_id',
        'predicate__uri', 'predicate__canonical_uri', 'predicate__name',
        'object__id', 'object__name', 'object__value', 'object__uri', 'object__resource_type'
    )

    # Group triples by subject
    triples_by_subject = defaultdict(list)
    for triple in all_property_triples:
        triples_by_subject[triple.subject_id].append(triple)

    for resource in entity_resources:
        properties = {}

        for triple in triples_by_subject.get(resource.id, []):
            # Match to canonical properties
            canonical_prop_uri = None
            prop_label = None

            if triple.predicate.canonical_uri and triple.predicate.canonical_uri in type_info["properties"]:
                canonical_prop_uri = triple.predicate.canonical_uri
                prop_label = type_info["properties"][canonical_prop_uri]["label"]
            elif triple.predicate.uri:
                for can_uri, pm in type_info["properties"].items():
                    if pm.get("local_uri") == triple.predicate.uri:
                        canonical_prop_uri = can_uri
                        prop_label = pm["label"]
                        break

            if not prop_label:
                prop_label = triple.predicate.name or triple.predicate.uri.rsplit("/", 1)[-1] if triple.predicate.uri else "Unknown"

            # Get value - object is always a Resource, check if it's a literal type
            if triple.object.resource_type == ResourceType.LITERAL:
                value = triple.object.value or str(triple.object.id)
                value_type = "literal"
                value_id = None
            else:
                value = triple.object.name or triple.object.value or triple.object.uri or str(triple.object.id)
                value_type = "resource"
                value_id = triple.object.id

            if prop_label not in properties:
                properties[prop_label] = {
                    "canonical_uri": canonical_prop_uri,
                    "values": []
                }

            properties[prop_label]["values"].append({
                "value": value,
                "type": value_type,
                "id": value_id,
            })

        # Get entity label
        entity_label = resource.name or resource.value or resource.uri or str(resource.id)

        # Check if this type has any FK relationships defined (don't count, just check)
        has_relationships = len(type_info.get("fk_relationships", [])) > 0

        entities.append({
            "id": resource.id,
            "label": entity_label,
            "uri": resource.uri,
            "properties": properties,
            "has_relationships": has_relationships,
            "canonical_type_uri": canonical_type_uri,
        })

    # Sort by label
    entities.sort(key=lambda e: e["label"].lower() if e["label"] else "")

    return entities, total_count


def _get_connected_entities(
    resource: Resource,
    property_canonical_uri: str,
    target_type_info: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    Get entities connected to this resource via a specific canonical property.
    Used for lazy loading.
    """
    connected = []

    # Find triples where this resource is the subject and predicate matches the canonical URI
    triples = Triple.objects.filter(
        subject=resource
    ).filter(
        Q(predicate__canonical_uri=property_canonical_uri) |
        Q(predicate__uri=property_canonical_uri)
    ).select_related('object', 'predicate').only(
        'object__id', 'object__name', 'object__value', 'object__uri', 'object__resource_type'
    )

    for triple in triples:
        # Skip literals - we only want connected entities
        if triple.object.resource_type != ResourceType.LITERAL:
            # Get basic info about connected resource
            connected_label = triple.object.name or triple.object.value or triple.object.uri or str(triple.object.id)

            # Get properties if target type info is provided
            properties = {}
            if target_type_info and target_type_info.get("properties"):
                # Get property triples for connected resource
                prop_triples = Triple.objects.filter(
                    subject=triple.object
                ).select_related('predicate', 'object').only(
                    'predicate__uri', 'predicate__canonical_uri', 'predicate__name',
                    'object__id', 'object__name', 'object__value', 'object__uri', 'object__resource_type'
                )

                for prop_triple in prop_triples:
                    # Match to canonical properties
                    prop_label = None
                    canonical_uri = None

                    for can_uri, prop_info in target_type_info["properties"].items():
                        if (prop_triple.predicate.canonical_uri == can_uri or
                            prop_triple.predicate.uri == prop_info.get("local_uri")):
                            prop_label = prop_info["label"]
                            canonical_uri = can_uri
                            break

                    if not prop_label:
                        prop_label = prop_triple.predicate.name or prop_triple.predicate.uri.rsplit("/", 1)[-1] if prop_triple.predicate.uri else "Unknown"

                    # Get value - check if it's a literal type
                    if prop_triple.object.resource_type == ResourceType.LITERAL:
                        value = prop_triple.object.value or str(prop_triple.object.id)
                        value_type = "literal"
                        value_id = None
                    else:
                        value = prop_triple.object.name or prop_triple.object.value or prop_triple.object.uri or str(prop_triple.object.id)
                        value_type = "resource"
                        value_id = prop_triple.object.id

                    if prop_label not in properties:
                        properties[prop_label] = {
                            "canonical_uri": canonical_uri,
                            "values": []
                        }

                    properties[prop_label]["values"].append({
                        "value": value,
                        "type": value_type,
                        "id": value_id,
                    })

            connected.append({
                "id": triple.object.id,
                "label": connected_label,
                "uri": triple.object.uri,
                "properties": properties,
            })

    return connected


@general_login_required
def canonical_data_catalog_view(request: HttpRequest) -> HttpResponse:
    """
    Display actual data instances organized by canonical entity types.
    Fast initial load, relationships loaded on-demand via HTMX.
    """
    org_code = request.GET.get("org")

    organizations = Organization.objects.filter(is_active=True).order_by("name")

    selected_org = None
    mapping = None
    manifest = None
    entity_type_data = []

    if org_code:
        selected_org = Organization.objects.filter(code=org_code).first()

        if selected_org:
            mapping = Mapping.get_active_for_organization(selected_org)

            if mapping:
                manifest = (mapping.mapping_config or {}).get("schema_manifest")

                if isinstance(manifest, dict) and manifest:
                    # Extract canonical entity types with relationships
                    all_entity_types = _get_canonical_entity_types_with_relationships(manifest)

                    # For each canonical entity type, query basic instances (fast)
                    page_size = 10
                    for canonical_uri, type_info in sorted(all_entity_types.items(), key=lambda x: x[1]["label"]):
                        entities, total_count = _get_entities_basic(
                            selected_org,
                            canonical_uri,
                            type_info,
                            limit=page_size,
                            offset=0,
                        )

                        entity_type_data.append({
                            "canonical_uri": canonical_uri,
                            "label": type_info["label"],
                            "local_datasets": type_info["local_datasets"],
                            "instance_count": len(entities),
                            "entities": entities,
                            "has_more": total_count > page_size,
                            "total_count": total_count,
                            "fk_relationships": type_info.get("fk_relationships", []),
                            "loaded_count": len(entities),
                        })

    context = {
        "organizations": organizations,
        "selected_org": selected_org,
        "mapping": mapping,
        "entity_type_data": entity_type_data,
        "has_data": bool(entity_type_data),
    }

    return render(request, "metadata/canonical_data_catalog.html", context)


@general_login_required
def canonical_data_relationships_htmx(request: HttpRequest) -> HttpResponse:
    """
    HTMX endpoint to load relationships for a specific entity on-demand.
    """
    org_code = request.GET.get("org")
    entity_id = request.GET.get("entity_id")
    canonical_type_uri = request.GET.get("canonical_type_uri")

    if not all([org_code, entity_id, canonical_type_uri]):
        return HttpResponse("Missing parameters", status=400)

    org = Organization.objects.filter(code=org_code).first()
    if not org:
        return HttpResponse("Organization not found", status=404)

    resource = Resource.objects.filter(id=entity_id, organization=org).first()
    if not resource:
        return HttpResponse("Entity not found", status=404)

    # Get mapping and manifest
    mapping = Mapping.get_active_for_organization(org)
    if not mapping:
        return HttpResponse("No mapping found", status=404)

    manifest = (mapping.mapping_config or {}).get("schema_manifest")
    if not isinstance(manifest, dict):
        return HttpResponse("Invalid manifest", status=404)

    # Get entity type info
    all_entity_types = _get_canonical_entity_types_with_relationships(manifest)
    type_info = all_entity_types.get(canonical_type_uri)
    if not type_info:
        return HttpResponse("Entity type not found", status=404)

    # Load relationships
    relationships = {}
    for fk in type_info.get("fk_relationships", []):
        source_uri = fk.get("source_canonical_uri")
        target_uri = fk.get("target_canonical_uri")

        if not source_uri:
            continue

        # Find target entity type info
        target_type_info = None
        for et_uri, et_info in all_entity_types.items():
            if target_uri in et_info.get("properties", {}):
                target_type_info = et_info
                break

        # Get connected entities
        connected = _get_connected_entities(resource, source_uri, target_type_info)

        if connected:
            rel_label = fk.get("notes") or type_info["properties"].get(source_uri, {}).get("label", "Connected")
            relationships[rel_label] = {
                "source_uri": source_uri,
                "target_uri": target_uri,
                "entities": connected,
            }

    context = {
        "relationships": relationships,
    }

    return render(request, "metadata/partials/canonical_data_relationships.html", context)


@general_login_required
def canonical_data_load_more_htmx(request: HttpRequest) -> HttpResponse:
    """
    HTMX endpoint to load more entities for a specific entity type.
    """
    org_code = request.GET.get("org")
    canonical_type_uri = request.GET.get("canonical_type_uri")
    offset = int(request.GET.get("offset", 0))
    page_size = 10

    if not all([org_code, canonical_type_uri]):
        return HttpResponse("Missing parameters", status=400)

    org = Organization.objects.filter(code=org_code).first()
    if not org:
        return HttpResponse("Organization not found", status=404)

    # Get mapping and manifest
    mapping = Mapping.get_active_for_organization(org)
    if not mapping:
        return HttpResponse("No mapping found", status=404)

    manifest = (mapping.mapping_config or {}).get("schema_manifest")
    if not isinstance(manifest, dict):
        return HttpResponse("Invalid manifest", status=404)

    # Get entity type info
    all_entity_types = _get_canonical_entity_types_with_relationships(manifest)
    type_info = all_entity_types.get(canonical_type_uri)
    if not type_info:
        return HttpResponse("Entity type not found", status=404)

    # Load next page of entities
    entities, total_count = _get_entities_basic(
        org,
        canonical_type_uri,
        type_info,
        limit=page_size,
        offset=offset,
    )

    new_offset = offset + len(entities)
    has_more = new_offset < total_count

    context = {
        "entities": entities,
        "canonical_type_uri": canonical_type_uri,
        "selected_org": org,
        "has_more": has_more,
        "new_offset": new_offset,
        "total_count": total_count,
    }

    return render(request, "metadata/partials/canonical_data_entity_list.html", context)


@general_login_required
def canonical_data_tree_view(request: HttpRequest) -> HttpResponse:
    """
    Display data as an expandable tree view using DaisyUI components.
    Entity types are lazy-loaded when organization node is expanded.
    """
    org_code = request.GET.get("org")

    organizations = Organization.objects.filter(is_active=True).order_by("name")

    selected_org = None
    has_mapping = False

    if org_code:
        selected_org = Organization.objects.filter(code=org_code).first()

        if selected_org:
            mapping = Mapping.get_active_for_organization(selected_org)
            has_mapping = bool(mapping)

    context = {
        "organizations": organizations,
        "selected_org": selected_org,
        "has_mapping": has_mapping,
    }

    return render(request, "metadata/canonical_data_tree.html", context)


@general_login_required
def canonical_data_tree_types_htmx(request: HttpRequest) -> HttpResponse:
    """
    HTMX endpoint to load entity types for tree view when expanding an organization node.
    """
    org_code = request.GET.get("org")

    if not org_code:
        return HttpResponse("Missing org parameter", status=400)

    org = Organization.objects.filter(code=org_code).first()
    if not org:
        return HttpResponse("Organization not found", status=404)

    # Get mapping and manifest
    mapping = Mapping.get_active_for_organization(org)
    if not mapping:
        return HttpResponse("No mapping found", status=404)

    manifest = (mapping.mapping_config or {}).get("schema_manifest")
    if not isinstance(manifest, dict):
        return HttpResponse("Invalid manifest", status=404)

    # Extract canonical entity types
    all_entity_types = _get_canonical_entity_types_with_relationships(manifest)

    # Get counts for each type
    type_predicate_uri = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
    entity_type_data = []

    for canonical_uri, type_info in sorted(all_entity_types.items(), key=lambda x: x[1]["label"]):
        # Just get count, entities loaded lazily
        count = Triple.objects.filter(
            subject__organization=org,
            predicate__uri=type_predicate_uri,
            object__canonical_uri=canonical_uri
        ).count()

        if count > 0:
            entity_type_data.append({
                "canonical_uri": canonical_uri,
                "label": type_info["label"],
                "total_count": count,
            })

    context = {
        "entity_type_data": entity_type_data,
        "org_code": org_code,
    }

    return render(request, "metadata/partials/canonical_data_tree_types.html", context)


@general_login_required
def canonical_data_tree_entities_htmx(request: HttpRequest) -> HttpResponse:
    """
    HTMX endpoint to load entities for tree view when expanding a type node.
    """
    org_code = request.GET.get("org")
    canonical_type_uri = request.GET.get("canonical_type_uri")
    limit = int(request.GET.get("limit", 10))
    offset = int(request.GET.get("offset", 0))

    if not all([org_code, canonical_type_uri]):
        return HttpResponse("Missing parameters", status=400)

    org = Organization.objects.filter(code=org_code).first()
    if not org:
        return HttpResponse("Organization not found", status=404)

    # Get mapping and manifest
    mapping = Mapping.get_active_for_organization(org)
    if not mapping:
        return HttpResponse("No mapping found", status=404)

    manifest = (mapping.mapping_config or {}).get("schema_manifest")
    if not isinstance(manifest, dict):
        return HttpResponse("Invalid manifest", status=404)

    # Get entity type info
    all_entity_types = _get_canonical_entity_types_with_relationships(manifest)
    type_info = all_entity_types.get(canonical_type_uri)
    if not type_info:
        return HttpResponse("Entity type not found", status=404)

    # Load entities
    entities, total_count = _get_entities_basic(
        org,
        canonical_type_uri,
        type_info,
        limit=limit,
        offset=offset,
    )

    new_offset = offset + len(entities)
    has_more = new_offset < total_count

    context = {
        "entities": entities,
        "canonical_type_uri": canonical_type_uri,
        "org_code": org_code,
        "has_more": has_more,
        "new_offset": new_offset,
        "total_count": total_count,
    }

    return render(request, "metadata/partials/canonical_data_tree_entities.html", context)


@general_login_required
def canonical_data_tree_relationships_htmx(request: HttpRequest) -> HttpResponse:
    """
    HTMX endpoint to load relationships for tree view when expanding an entity node.
    """
    org_code = request.GET.get("org")
    entity_id = request.GET.get("entity_id")
    canonical_type_uri = request.GET.get("canonical_type_uri")

    if not all([org_code, entity_id, canonical_type_uri]):
        return HttpResponse("Missing parameters", status=400)

    org = Organization.objects.filter(code=org_code).first()
    if not org:
        return HttpResponse("Organization not found", status=404)

    resource = Resource.objects.filter(id=entity_id, organization=org).first()
    if not resource:
        return HttpResponse("Entity not found", status=404)

    # Get mapping and manifest
    mapping = Mapping.get_active_for_organization(org)
    if not mapping:
        return HttpResponse("No mapping found", status=404)

    manifest = (mapping.mapping_config or {}).get("schema_manifest")
    if not isinstance(manifest, dict):
        return HttpResponse("Invalid manifest", status=404)

    # Get entity type info
    all_entity_types = _get_canonical_entity_types_with_relationships(manifest)
    type_info = all_entity_types.get(canonical_type_uri)
    if not type_info:
        return HttpResponse("Entity type not found", status=404)

    # Load relationships
    relationships = {}
    for fk in type_info.get("fk_relationships", []):
        source_uri = fk.get("source_canonical_uri")
        target_uri = fk.get("target_canonical_uri")

        if not source_uri:
            continue

        # Find target entity type info
        target_type_info = None
        for et_uri, et_info in all_entity_types.items():
            if target_uri in et_info.get("properties", {}):
                target_type_info = et_info
                break

        # Get connected entities
        connected = _get_connected_entities(resource, source_uri, target_type_info)

        if connected:
            rel_label = fk.get("notes") or type_info["properties"].get(source_uri, {}).get("label", "Connected")
            relationships[rel_label] = {
                "source_uri": source_uri,
                "target_uri": target_uri,
                "entities": connected,
            }

    context = {
        "relationships": relationships,
    }

    return render(request, "metadata/partials/canonical_data_tree_relationships.html", context)
