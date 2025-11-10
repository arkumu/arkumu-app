"""Helpers for deriving human-readable labels for metadata entities."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from django.utils.text import slugify

from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.schema_workspace.services import SchemaWorkspaceService
from arkumu.metadata.utils.uri_placeholders import decode_placeholder_uri

logger = logging.getLogger(__name__)

IS_PART_OF_URI = "http://purl.org/dc/terms/isPartOf"


def infer_entity_label(
    service: SchemaWorkspaceService,
    entity_uri: str,
    target_dataset: Optional[str] = None,
    include_rich_context: bool = False,
    display_property_uri: Optional[str] = None,
) -> str:
    """
    Derive a human-readable label for the given entity URI.

    This mirrors the heuristics used by the schema workspace single-page editor,
    allowing other views (like tabular browse tables) to resolve FK references
    consistently across organisations.
    """
    logger.debug(
        "[infer_entity_label] entity_uri=%s target_dataset=%s display_property_uri=%s",
        entity_uri,
        target_dataset,
        display_property_uri,
    )

    normalized_uri, placeholder_label = decode_placeholder_uri(entity_uri)
    if normalized_uri != entity_uri:
        logger.debug(
            "[infer_entity_label] Normalized placeholder URI %s -> %s",
            entity_uri,
            normalized_uri,
        )
        entity_uri = normalized_uri

    uri_tail = entity_uri.rstrip("/").split("/")[-1]
    try:
        entity = Resource.objects.get(uri=entity_uri)
    except Resource.DoesNotExist:
        logger.warning("[infer_entity_label] Resource not found for URI %s", entity_uri)
        return placeholder_label or entity_uri

    if target_dataset and ("kreuz" in target_dataset.lower() or "junction" in target_dataset.lower()):
        logger.debug(
            "[infer_entity_label] Resolving join dataset %s via related entities",
            target_dataset,
        )
        related_entities = (
            Triple.objects.filter(
                subject=entity,
                object__resource_type=ResourceType.ENTITY,
            )
            .exclude(predicate__uri__icontains="ispartof")
            .select_related("predicate", "object")[:5]
        )

        candidates: list[Tuple[int, str, str, str]] = []
        for triple in related_entities:
            related_uri = triple.object.uri
            related_name = triple.object.name or ""
            predicate_uri = triple.predicate.uri if triple.predicate else ""

            if "projekt" in predicate_uri.lower() or "werk" in predicate_uri.lower():
                continue

            priority = 3
            uri_lower = related_uri.lower()
            if "ereignis" in uri_lower or "event" in uri_lower:
                priority = 1
            elif any(token in uri_lower for token in ("akteur", "person", "koerperschaft")):
                priority = 2
            elif any(token in uri_lower for token in ("digital", "objekt")):
                priority = 4

            uri_parts = related_uri.split("/entities/")
            if len(uri_parts) == 2:
                dataset_part = uri_parts[1].split("/")[0]
                inferred_dataset = dataset_part.replace("-", "_")
                parts = inferred_dataset.rsplit("_", 1)
                if len(parts) == 2:
                    inferred_dataset = f"{parts[0]}_{parts[1].capitalize()}"
                candidates.append((priority, related_uri, inferred_dataset, related_name))

        candidates.sort(key=lambda item: item[0])
        for priority, related_uri, inferred_dataset, related_name in candidates:
            logger.debug(
                "[infer_entity_label] Join resolution candidate %s (priority %s, dataset %s)",
                related_uri,
                priority,
                inferred_dataset,
            )
            related_label = infer_entity_label(
                service,
                related_uri,
                inferred_dataset,
            )
            if related_label and not related_label.isdigit() and related_label != related_name:
                logger.info(
                    "[infer_entity_label] Join entity %s resolved via %s -> %s",
                    entity_uri,
                    related_uri,
                    related_label,
                )
                return related_label

    if display_property_uri:
        try:
            prop_resource = Resource.objects.get(uri=display_property_uri)
        except Resource.DoesNotExist:
            logger.warning(
                "[infer_entity_label] Display property %s not found",
                display_property_uri,
            )
        else:
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
                    logger.debug(
                        "[infer_entity_label] Using explicit display property %s -> %s",
                        display_property_uri,
                        value,
                    )
                    return str(value)

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
                    value = triple.object.value or triple.object.literal_value or triple.object.name
                    if value:
                        value_str = str(value).strip()
                        if not value_str.isdigit():
                            logger.debug(
                                "[infer_entity_label] Anchor column %s provided label %s",
                                column,
                                value_str,
                            )
                            return value_str
                        logger.debug(
                            "[infer_entity_label] Ignoring numeric anchor column %s=%s",
                            column,
                            value_str,
                        )

    for suffix in ("bevorzugter-titel", "bevorzugtertitel", "titel", "title", "name", "label"):
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
                logger.debug(
                    "[infer_entity_label] Found label via suffix '%s': %s",
                    suffix,
                    value,
                )
                return str(value)

    label_patterns = [
        ("titel", 1),
        ("title", 1),
        ("name", 2),
        ("label", 2),
        ("beschreibung", 3),
        ("description", 3),
        ("kommentar", 4),
        ("comment", 4),
    ]
    candidates: list[Tuple[int, Triple, str]] = []
    for pattern, priority in label_patterns:
        triples = (
            Triple.objects.filter(
                subject=entity,
                predicate__uri__icontains=pattern,
                object__resource_type=ResourceType.LITERAL,
            )
            .select_related("object", "predicate")[:5]
        )
        for triple in triples:
            value = triple.object.value or triple.object.literal_value or triple.object.name
            if value and str(value).strip() and not str(value).strip().isdigit():
                candidates.append((priority, triple, str(value)))

    if candidates:
        candidates.sort(key=lambda item: item[0])
        _, best_triple, best_value = candidates[0]
        predicate_name = best_triple.predicate.name if best_triple.predicate else "unknown"
        logger.debug(
            "[infer_entity_label] Pattern '%s' yielded label %s",
            predicate_name,
            best_value,
        )
        return best_value

    if entity.name and entity.name != entity_uri:
        tail = entity_uri.split("/")[-1]
        if entity.name != tail:
            return entity.name

    anchor_literal = (
        Triple.objects.filter(
            subject=entity,
            object__resource_type=ResourceType.LITERAL,
        )
        .select_related("object")
        .first()
    )
    if anchor_literal:
        value = anchor_literal.object.value or anchor_literal.object.literal_value or anchor_literal.object.name
        if value:
            final_label = f"{value} ({entity_uri.split('/')[-1]})" if include_rich_context else str(value)
            logger.debug("[infer_entity_label] Fallback literal anchor label %s", final_label)
            return final_label

    if placeholder_label:
        logger.debug(
            "[infer_entity_label] Falling back to placeholder label '%s' for %s",
            placeholder_label,
            entity_uri,
        )
        return placeholder_label

    final = entity_uri.split("/")[-1]
    logger.info(
        "[infer_entity_label] Returning URI tail fallback %s for %s",
        final,
        entity_uri,
    )
    return entity_uri


@dataclass
class _DatasetMaps:
    by_resource: Dict[str, str]
    by_slug: Dict[str, str]


class EntityLabelResolver:
    """Cache-friendly label resolver backed by schema manifests."""

    def __init__(self, service: SchemaWorkspaceService) -> None:
        self.service = service
        self._label_cache: Dict[str, str] = {}
        self._maps = self._build_dataset_maps()

    def label_for_resource(
        self,
        resource: Resource,
        display_property_uri: Optional[str] = None,
    ) -> str:
        if not resource or not resource.uri:
            return ""

        cached = self._label_cache.get(resource.uri)
        if cached:
            return cached

        dataset_hint = self._determine_dataset(resource)
        label = infer_entity_label(
            self.service,
            resource.uri,
            target_dataset=dataset_hint,
            display_property_uri=display_property_uri,
        )
        self._label_cache[resource.uri] = label
        return label

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _build_dataset_maps(self) -> _DatasetMaps:
        by_resource: Dict[str, str] = {}
        by_slug: Dict[str, str] = {}

        try:
            summaries = self.service.list_datasets()
        except Exception:
            logger.exception("[EntityLabelResolver] Failed to list datasets")
            return _DatasetMaps(by_resource=by_resource, by_slug=by_slug)

        for summary in summaries:
            dataset_name = summary.dataset_name
            try:
                schema = self.service.get_dataset_schema(dataset_name)
            except ValueError:
                continue

            dataset_resource = schema.get("dataset_resource")
            if dataset_resource:
                by_resource[str(dataset_resource.id)] = dataset_name
                if dataset_resource.uri:
                    by_resource[dataset_resource.uri] = dataset_name
                    slug_from_uri = dataset_resource.uri.rstrip("/").split("/")[-1]
                    if slug_from_uri:
                        by_slug[slug_from_uri.lower()] = dataset_name

            slug = slugify(dataset_name or "")
            if slug:
                by_slug[slug.lower()] = dataset_name
                normalized = slug.replace("-", "_")
                by_slug[normalized.lower()] = dataset_name

        return _DatasetMaps(by_resource=by_resource, by_slug=by_slug)

    def _determine_dataset(self, resource: Resource) -> Optional[str]:
        dataset = self._dataset_from_is_part_of(resource)
        if dataset:
            return dataset

        if resource.uri:
            parts = resource.uri.split("/entities/")
            if len(parts) == 2:
                slug_part = parts[1].split("/")[0].lower()
                dataset = self._maps.by_slug.get(slug_part)
                if dataset:
                    return dataset
                normalized = slug_part.replace("-", "_")
                dataset = self._maps.by_slug.get(normalized)
                if dataset:
                    return dataset

        return None

    def _dataset_from_is_part_of(self, resource: Resource) -> Optional[str]:
        dataset_triples = Triple.objects.filter(
            subject=resource,
            predicate__uri=IS_PART_OF_URI,
        ).values_list("object_id", "object__uri")

        for object_id, object_uri in dataset_triples:
            key = str(object_id)
            dataset = self._maps.by_resource.get(key)
            if dataset:
                return dataset
            if object_uri:
                dataset = self._maps.by_resource.get(object_uri)
                if dataset:
                    return dataset
                uri_tail = object_uri.rstrip("/").split("/")[-1].lower()
                dataset = self._maps.by_slug.get(uri_tail)
                if dataset:
                    return dataset
        return None
