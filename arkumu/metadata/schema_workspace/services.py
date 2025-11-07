from __future__ import annotations

import logging
import re
import secrets
import string
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple, Set, Pattern
from urllib.parse import urlparse, urlencode

from django.db import transaction
from django.db.models import Q
from django.utils.text import slugify
from django.conf import settings

logger = logging.getLogger(__name__)

from arkumu.common.uri_utils import mint_uri, slugify_uri_part
from arkumu.importer.services.schema_service import SchemaService
from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.constants import ACTOR_EVENT_JOIN_DATASET
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.models.resources import ClassResource, EntityResource, PropertyResource
from arkumu.metadata.utils.uri_placeholders import decode_placeholder_uri
from arkumu.users.models import Organization


def generate_auto_id(dataset_name: str) -> str:
    """
    Generate a unique identifier for an entity using timestamp and random suffix.

    Format: {dataset_name_lower}_{YYYYMMDD}_{random_hex}
    Example: projekt_20251015_a3f2, ereignis_20251015_b7c9

    Args:
        dataset_name: Name of the dataset (e.g., "Projekt", "Ereignis")

    Returns:
        Auto-generated unique identifier string
    """
    timestamp = datetime.now().strftime("%Y%m%d")
    random_suffix = secrets.token_hex(2)  # 4 character hex string
    dataset_prefix = dataset_name.lower().replace(" ", "_")
    return f"{dataset_prefix}_{timestamp}_{random_suffix}"


@dataclass(frozen=True)
class DatasetSummary:
    dataset_name: str
    display_label: str
    anchor_columns: List[str]
    property_count: int
    relationship_count: int
    is_controlled_vocab: bool = False
    entity_count: int = 0


@dataclass(frozen=True)
class JoinRelationship:
    """Description of a junction dataset linking two other datasets."""

    join_dataset: str
    join_dataset_schema: Dict[str, Any]
    self_column: str
    self_property_uri: str
    other_dataset: str
    other_column: str
    other_property_uri: str
    other_display_label: str
    context_columns: List[Dict[str, Optional[str]]] = field(default_factory=list)
    search_property_uris: List[str] = field(default_factory=list)
    widget_name: Optional[str] = None


@dataclass(frozen=True)
class RelationshipValues:
    """Collected relationship values for badge display and widget hydration."""

    field_name: str
    display_label: str
    uris: List[str]
    is_join: bool
    target_dataset: Optional[str] = None
    property_uri: Optional[str] = None
    editable: bool = True
    records: List[Dict[str, Any]] = field(default_factory=list)


class SchemaWorkspaceService:
    """Expose SchemaService blueprints in a UI-friendly format."""

    _PROJECT_DATASET_SLUGS: Set[str] = {"projekt", "project"}
    _PROJECT_TITLE_COLUMN_NAMES: Set[str] = {"bevorzugter_titel", "preferred_title"}
    _PROJECT_TITLE_LABELS: Set[str] = {"bevorzugter titel", "preferred title"}

    def __init__(
        self,
        *,
        mapping: Mapping,
        organization: Organization,
        base_uri: str = "http://arkumu.org/data",
    ) -> None:
        self.mapping = mapping
        self.organization = organization
        self.base_uri = base_uri
        schema_variant_key = getattr(settings, "METADATA_SCHEMA_MANIFEST_KEY", "promoted_manifest")

        self._schema_service = SchemaService(
            mapping_id=str(mapping.id),
            institution=organization.code,
            base_uri=base_uri,
            schema_variant_key=schema_variant_key,
        )
        # Ensure processor and dataset blueprints are available once up front
        self._schema_service._ensure_schema_loaded()
        self._processor = self._schema_service._processor
        self._external_template_regex_cache: Dict[str, Pattern[str]] = {}
        self._context_value_cache: Dict[str, List[str]] = {}

    # ------------------------------------------------------------------ #
    # Blueprint inspection helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _is_controlled_vocabulary(dataset_name: str, schema: Dict[str, Any]) -> bool:
        """
        Detect controlled vocabularies by name patterns.

        Controlled vocabularies are reference data used for dropdowns and validation,
        typically containing types, categories, and other classification data.
        """
        vocab_patterns = [
            'typ', 'art', 'kategorie', 'rolle', 'schlagwort',
            'sprache', 'ort', 'einheit', 'lizenz'
        ]
        dataset_lower = dataset_name.lower()
        return any(pattern in dataset_lower for pattern in vocab_patterns)

    def list_datasets(self) -> List[DatasetSummary]:
        summaries: List[DatasetSummary] = []
        for dataset_name in self._schema_service.list_datasets():
            schema = self._schema_service.get_dataset_schema(dataset_name)
            if not schema:
                continue
            # Hide junction tables from end users
            if schema.get("junction_schema"):
                continue

            entity_type = schema.get("entity_type")
            display_label = getattr(entity_type, "name", "") or dataset_name
            anchor_columns = [
                anchor["column_name"] for anchor in schema.get("anchor_columns", [])
            ]

            # Categorize as controlled vocabulary or main entity
            is_controlled_vocab = self._is_controlled_vocabulary(dataset_name, schema)

            # Count entities for this dataset (via dataset_resource isPartOf relationship)
            entity_count = 0
            dataset_resource = self._resolve_dataset_resource(dataset_name, schema)
            if dataset_resource:
                is_part_of_uri = "http://purl.org/dc/terms/isPartOf"
                entity_count = Triple.objects.filter(
                    predicate__uri=is_part_of_uri,
                    object=dataset_resource,
                ).count()

            summaries.append(
                DatasetSummary(
                    dataset_name=dataset_name,
                    display_label=display_label,
                    anchor_columns=anchor_columns,
                    property_count=len(schema.get("properties", {})),
                    relationship_count=len(schema.get("fk_relationships", [])),
                    is_controlled_vocab=is_controlled_vocab,
                    entity_count=entity_count,
                )
            )

        # Sort by category (main entities first) then by display label
        return sorted(summaries, key=lambda item: (item.is_controlled_vocab, item.display_label.lower()))

    def get_dataset_schema(self, dataset_name: str) -> Dict[str, Any]:
        schema = self._schema_service.get_dataset_schema(dataset_name)
        if not schema:
            raise ValueError(f"No schema blueprint found for dataset '{dataset_name}'")
        return schema

    def _resolve_dataset_resource(
        self,
        dataset_name: str,
        schema: Dict[str, Any],
    ) -> Optional[Resource]:
        dataset_resource = schema.get("dataset_resource")
        if dataset_resource:
            return dataset_resource

        organization = self.organization
        if organization is None:
            return None

        dataset_uri = mint_uri(
            self.base_uri,
            slugify_uri_part(str(organization.code)),
            "datasets",
            slugify_uri_part(dataset_name),
        )
        dataset_defaults = {
            "resource_type": ResourceType.IRI,
            "name": getattr(schema.get("entity_type"), "name", "") or dataset_name,
            "organization": organization,
        }
        dataset_resource, _ = Resource.objects.get_or_create(
            uri=dataset_uri,
            defaults=dataset_defaults,
        )
        if dataset_resource.organization is None:
            dataset_resource.organization = organization
            dataset_resource.save(update_fields=["organization"])

        schema["dataset_resource"] = dataset_resource
        return dataset_resource

    def get_dataset_summary(self, dataset_name: str) -> DatasetSummary:
        schema = self.get_dataset_schema(dataset_name)
        entity_type = schema.get("entity_type")
        display_label = getattr(entity_type, "name", "") or dataset_name
        anchor_columns = [
            anchor["column_name"] for anchor in schema.get("anchor_columns", [])
        ]

        # Categorize as controlled vocabulary or main entity
        is_controlled_vocab = self._is_controlled_vocabulary(dataset_name, schema)

        # Count entities for this dataset
        entity_count = 0
        dataset_resource = self._resolve_dataset_resource(dataset_name, schema)
        if dataset_resource:
            is_part_of_uri = "http://purl.org/dc/terms/isPartOf"
            entity_count = Triple.objects.filter(
                predicate__uri=is_part_of_uri,
                object=dataset_resource,
            ).count()

        return DatasetSummary(
            dataset_name=dataset_name,
            display_label=display_label,
            anchor_columns=anchor_columns,
            property_count=len(schema.get("properties", {})),
            relationship_count=len(schema.get("fk_relationships", [])),
            is_controlled_vocab=is_controlled_vocab,
            entity_count=entity_count,
        )

    def _get_configured_join_relationships(self, dataset_name: str) -> List[JoinRelationship]:
        config_root = (self.mapping.mapping_config or {}).get("junction_widgets") or {}
        if not config_root:
            return []

        config_list: List[Dict[str, Any]] = []
        if dataset_name in config_root:
            config_list = config_root.get(dataset_name) or []
        else:
            slug = slugify(dataset_name)
            config_list = config_root.get(slug) or []

        relationships: List[JoinRelationship] = []
        if not config_list:
            return relationships

        for entry in config_list:
            if not isinstance(entry, dict):
                continue
            join_dataset = entry.get("join_dataset") or entry.get("join_table") or entry.get("dataset")
            if not join_dataset:
                continue
            try:
                join_schema = self.get_dataset_schema(join_dataset)
            except ValueError:
                continue

            properties = join_schema.get("properties", {}) or {}
            junction_meta = join_schema.get("junction_schema") or {}

            self_column = entry.get("self_column") or entry.get("fk1") or entry.get("source_column")
            other_column = entry.get("other_column") or entry.get("fk2") or entry.get("target_column")
            if not self_column or not other_column:
                # Fall back to junction schema defaults if available
                if dataset_name == junction_meta.get("primary_dataset"):
                    self_column = junction_meta.get("primary_fk")
                    other_column = junction_meta.get("secondary_fk")
                elif dataset_name == junction_meta.get("secondary_dataset"):
                    self_column = junction_meta.get("secondary_fk")
                    other_column = junction_meta.get("primary_fk")
            if not self_column or not other_column:
                continue

            other_dataset = entry.get("other_dataset")
            if not other_dataset:
                other_dataset = (
                    junction_meta.get("secondary_dataset")
                    if dataset_name == junction_meta.get("primary_dataset")
                    else junction_meta.get("primary_dataset")
                )
            if not other_dataset:
                continue

            self_property = properties.get(self_column)
            other_property = properties.get(other_column)
            if not self_property or not other_property:
                continue

            try:
                other_summary = self.get_dataset_summary(other_dataset)
            except ValueError:
                other_summary = DatasetSummary(
                    dataset_name=other_dataset,
                    display_label=other_dataset,
                    anchor_columns=[],
                    property_count=0,
                    relationship_count=0,
                )

            context_columns_config = entry.get("context_columns") or entry.get("context_fields") or []
            context_specs: List[Dict[str, Optional[str]]] = []
            if not context_columns_config and junction_meta.get("context_columns"):
                context_columns_config = junction_meta.get("context_columns")

            for context_column in context_columns_config:
                column_name = context_column
                property_uri = None
                label = None
                if isinstance(context_column, dict):
                    column_name = context_column.get("column") or context_column.get("name")
                    property_uri = context_column.get("property_uri")
                    label = context_column.get("label")
                if not column_name:
                    continue
                context_prop = properties.get(column_name)
                property_uri = property_uri or getattr(context_prop, "uri", None)
                slug = slugify(column_name or "").replace("-", "_")
                context_specs.append(
                    {
                        "column": column_name,
                        "property_uri": property_uri,
                        "label": label or getattr(context_prop, "name", column_name),
                        "slug": slug,
                    }
                )

            search_columns = entry.get("search_columns") or entry.get("search_properties") or []
            search_property_uris: List[str] = []
            if search_columns:
                try:
                    target_schema = self.get_dataset_schema(other_dataset)
                except ValueError:
                    target_schema = {}
                target_properties = target_schema.get("properties", {}) or {}

                for item in search_columns:
                    uri_candidate = None
                    if isinstance(item, dict):
                        column_name = item.get("column")
                        uri_candidate = item.get("property_uri") or item.get("uri")
                        if column_name and not uri_candidate:
                            prop = target_properties.get(column_name)
                            uri_candidate = getattr(prop, "uri", None)
                    else:
                        column_name = str(item)
                        if column_name.startswith("http://") or column_name.startswith("https://"):
                            uri_candidate = column_name
                        else:
                            prop = target_properties.get(column_name)
                            uri_candidate = getattr(prop, "uri", None)
                    if uri_candidate:
                        search_property_uris.append(uri_candidate)

            widget_name = entry.get("widget") or entry.get("widget_name") or "JunctionRelationshipWidget"

            relationships.append(
                JoinRelationship(
                    join_dataset=join_dataset,
                    join_dataset_schema=join_schema,
                    self_column=self_column,
                    self_property_uri=getattr(self_property, "uri", None),
                    other_dataset=other_dataset,
                    other_column=other_column,
                    other_property_uri=getattr(other_property, "uri", None),
                    other_display_label=entry.get("label") or other_summary.display_label,
                    context_columns=context_specs,
                    search_property_uris=search_property_uris,
                    widget_name=widget_name,
                )
            )

        return relationships

    def list_join_relationships(self, dataset_name: str) -> List[JoinRelationship]:
        """Return junction definitions that relate the given dataset to others."""

        relationships: List[JoinRelationship] = []
        seen: Set[Tuple[str, str, str]] = set()

        configured_relationships = self._get_configured_join_relationships(dataset_name)
        for rel in configured_relationships:
            key = (rel.join_dataset, dataset_name, rel.other_dataset)
            if key not in seen:
                relationships.append(rel)
                seen.add(key)

        dataset_names = self._schema_service.list_datasets()
        for candidate in dataset_names:
            if candidate == dataset_name:
                continue
            if any(rel.join_dataset == candidate for rel in configured_relationships):
                continue
            schema = self.get_dataset_schema(candidate)
            junction = schema.get("junction_schema") or {}

            primary_dataset = junction.get("primary_dataset")
            secondary_dataset = junction.get("secondary_dataset")
            self_column: Optional[str] = None
            other_dataset: Optional[str] = None
            other_column: Optional[str] = None

            if dataset_name in {primary_dataset, secondary_dataset}:
                if dataset_name == primary_dataset:
                    self_column = junction.get("primary_fk")
                    other_dataset = secondary_dataset
                    other_column = junction.get("secondary_fk")
                else:
                    self_column = junction.get("secondary_fk")
                    other_dataset = primary_dataset
                    other_column = junction.get("primary_fk")
            else:
                fk_relationships = schema.get("fk_relationships", []) or []
                self_rel = None
                other_rel = None
                for rel in fk_relationships:
                    rel_target = rel.get("target_dataset")
                    if rel_target == dataset_name:
                        if self_rel is None:
                            self_rel = rel
                        elif other_rel is None:
                            other_rel = rel
                    else:
                        if other_rel is None:
                            other_rel = rel
                if self_rel is None and fk_relationships:
                    self_rel = fk_relationships[0]
                if other_rel is None and fk_relationships:
                    for rel in fk_relationships:
                        if rel is not self_rel:
                            other_rel = rel
                            break
                if self_rel is None:
                    continue
                if other_rel is None:
                    continue
                self_column = self_rel.get("source_column")
                other_column = other_rel.get("source_column")
                other_dataset = other_rel.get("target_dataset") or dataset_name

            if not self_column or not other_column:
                continue

            if not other_dataset or not self_column or not other_column:
                continue

            key = (candidate, dataset_name, other_dataset)
            if key in seen:
                continue
            seen.add(key)

            properties = schema.get("properties", {}) or {}
            self_property = properties.get(self_column)
            other_property = properties.get(other_column)
            other_summary = self.get_dataset_summary(other_dataset)
            context_specs: List[Dict[str, Optional[str]]] = []
            for context_column in junction.get("context_columns", []) or []:
                context_prop = properties.get(context_column)
                context_specs.append(
                    {
                        "column": context_column,
                        "property_uri": getattr(context_prop, "uri", None),
                        "slug": slugify(context_column or "").replace("-", "_"),
                    }
                )

            widget_name = None
            if candidate == ACTOR_EVENT_JOIN_DATASET and dataset_name.lower() == "ereignis".lower():
                widget_name = "ActorParticipationWidget"

            relationships.append(
                JoinRelationship(
                    join_dataset=candidate,
                    join_dataset_schema=schema,
                    self_column=self_column,
                    self_property_uri=getattr(self_property, "uri", None),
                    other_dataset=other_dataset,
                    other_column=other_column,
                    other_property_uri=getattr(other_property, "uri", None),
                    other_display_label=other_summary.display_label,
                    context_columns=context_specs,
                    widget_name=widget_name,
                )
            )

        return relationships

    def _get_external_schema(
        self,
        schema: Dict[str, Any],
        column_name: str,
    ) -> Optional[Dict[str, Any]]:
        external_schemas = schema.get("external_ontology_schemas", {}) or {}
        return external_schemas.get(column_name)

    def _build_external_template_regex(self, template: str) -> Optional[Pattern[str]]:
        if not template:
            return None
        cached = self._external_template_regex_cache.get(template)
        if cached is not None:
            return cached

        formatter = string.Formatter()
        pattern_parts: List[str] = []
        seen: Set[str] = set()
        try:
            for literal_text, field_name, _format_spec, _conversion in formatter.parse(template):
                if literal_text:
                    pattern_parts.append(re.escape(literal_text))
                if field_name is None:
                    continue
                if field_name in seen:
                    pattern_parts.append(f"(?P={field_name})")
                else:
                    pattern_parts.append(f"(?P<{field_name}>.+?)")
                    seen.add(field_name)
            pattern_parts.append("$")
            pattern = re.compile("".join(pattern_parts))
        except ValueError:
            return None

        self._external_template_regex_cache[template] = pattern
        return pattern

    def _extract_external_identifier(
        self,
        *,
        template: str,
        candidate: str,
    ) -> Optional[str]:
        if not template or not candidate:
            return None
        regex = self._build_external_template_regex(template)
        if regex is None:
            return None
        match = regex.match(candidate)
        if not match:
            return None
        groups = match.groupdict()
        for key in ("identifier", "value"):
            value = groups.get(key)
            if value:
                return value
        for value in groups.values():
            if value:
                return value
        return None

    def _normalize_external_identifier(self, template: str, value: Any) -> str:
        if value in (None, ""):
            return ""
        candidate = str(value).strip()
        extracted = self._extract_external_identifier(template=template, candidate=candidate)
        return extracted or candidate

    def get_context_value_options(
        self,
        property_uri: Optional[str],
        limit: int = 200,
    ) -> List[str]:
        if not property_uri:
            return []
        cached = self._context_value_cache.get(property_uri)
        if cached is not None:
            return cached

        triples = Triple.objects.filter(
            predicate__uri=property_uri,
        ).select_related("object")

        seen: Set[str] = set()
        values: List[str] = []
        for triple in triples.iterator():
            obj = triple.object
            if obj is None:
                continue
            text = obj.value or obj.name or obj.uri or ""
            text = text.strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            values.append(text)
            if len(values) >= limit:
                break

        values.sort(key=lambda item: item.lower())
        self._context_value_cache[property_uri] = values
        return values

    def _prepare_form_value(
        self,
        *,
        schema: Dict[str, Any],
        column_name: str,
        value: Any,
    ) -> str:
        if isinstance(value, EntityResource):
            raw_value = value._resource.uri
        else:
            raw_value = value

        if raw_value is None:
            return ""

        external_schema = self._get_external_schema(schema, column_name)
        if external_schema:
            template = external_schema.get("uri_template", "")
            return self._normalize_external_identifier(template, raw_value)

        return str(raw_value)

    def get_field_metadata(self, dataset_name: str) -> Dict[str, Dict[str, Any]]:
        schema = self.get_dataset_schema(dataset_name)
        fk_lookup = self._build_fk_lookup(schema)
        field_meta: Dict[str, Dict[str, Any]] = {}
        dataset_slug = slugify(dataset_name or "").lower()
        enforce_title_required = dataset_slug in self._PROJECT_DATASET_SLUGS
        project_title_slugs = {
            slugify(name).replace("-", "_") for name in self._PROJECT_TITLE_COLUMN_NAMES
        } if enforce_title_required else set()
        for column_name, column_meta in schema.get("column_metadata", {}).items():
            property_resource = schema["properties"].get(column_name)
            meta = {
                **column_meta,
                "property_uri": getattr(property_resource, "uri", None),
                "property_label": getattr(property_resource, "name", column_name),
            }
            if column_name in fk_lookup:
                meta["fk_relationship"] = fk_lookup[column_name]
                if meta.get("fk_relationship", {}).get("is_multi_value"):
                    meta["is_multi_value"] = True
            if not meta.get("is_multi_value"):
                column_type = str(meta.get("column_type") or "").lower()
                if "multi_value" in column_type or column_name in schema.get("multi_value_schemas", {}):
                    meta["is_multi_value"] = True
            if enforce_title_required:
                column_key = column_name.strip().lower()
                label_key = str(meta.get("property_label") or "").strip().lower()
                column_slug = slugify(column_name or "").replace("-", "_")
                if (
                    column_key in self._PROJECT_TITLE_COLUMN_NAMES
                    or column_slug in project_title_slugs
                    or label_key in self._PROJECT_TITLE_LABELS
                ):
                    meta["is_required"] = True
            field_meta[column_name] = meta

        sorted_items = sorted(
            field_meta.items(),
            key=lambda item: (str(item[1].get("property_label") or item[0]).lower(), item[0]),
        )
        return {key: field_meta[key] for key, _ in sorted_items}

    def augment_field_metadata_with_joins(
        self,
        dataset_name: str,
        field_metadata: Dict[str, Dict[str, Any]],
    ) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, JoinRelationship]]:
        metadata = dict(field_metadata)
        join_map: Dict[str, JoinRelationship] = {}

        direct_multi_targets = {
            meta.get("fk_relationship", {}).get("target_dataset")
            for meta in metadata.values()
            if meta.get("fk_relationship") and meta.get("is_multi_value")
        }

        for relationship in self.list_join_relationships(dataset_name):
            if relationship.other_dataset in direct_multi_targets and not relationship.widget_name:
                continue
            metadata.pop(relationship.self_column, None)

            for field_name, field_meta in list(metadata.items()):
                if field_meta.get("property_uri") == relationship.self_property_uri:
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
                if relationship.context_columns:
                    metadata[field_name]["context_columns"] = relationship.context_columns
                if relationship.search_property_uris:
                    metadata[field_name]["search_property_uris"] = relationship.search_property_uris
                    metadata[field_name].setdefault("selected_property", relationship.search_property_uris[0])
                if relationship.widget_name:
                    metadata[field_name]["widget"] = relationship.widget_name
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
            if relationship.context_columns:
                metadata[field_name]["context_columns"] = relationship.context_columns
            if relationship.search_property_uris:
                metadata[field_name]["search_property_uris"] = relationship.search_property_uris
                metadata[field_name]["selected_property"] = relationship.search_property_uris[0]
            if relationship.widget_name:
                metadata[field_name]["widget"] = relationship.widget_name

        return metadata, join_map

    def collect_relationship_values(
        self,
        *,
        dataset_name: str,
        entity_uri: str,
        field_metadata: Dict[str, Dict[str, Any]],
        join_field_map: Dict[str, JoinRelationship],
    ) -> List[RelationshipValues]:
        if not entity_uri:
            return []

        entity_resource = Resource.objects.filter(uri=entity_uri).first()
        if entity_resource is None:
            return []

        collected: List[RelationshipValues] = []

        for field_name, relationship in join_field_map.items():
            backend_records = self._get_join_entity_records(relationship, entity_uri)
            if not backend_records:
                continue
            other_label = relationship.other_display_label or relationship.other_dataset
            uris = [
                record.get("related_uri")
                for record in backend_records
                if record.get("related_uri")
            ]
            if not uris:
                continue
            ui_records: List[Dict[str, Any]] = []
            for record in backend_records:
                related_uri = record.get("related_uri")
                if not related_uri:
                    continue
                context_values = record.get("context") if isinstance(record.get("context"), dict) else {}
                normalized_context: Dict[str, str] = {}
                for key, value in context_values.items():
                    slug = slugify(str(key or "")).replace("-", "_")
                    if not slug:
                        continue
                    normalized_context[slug] = "" if value is None else str(value)
                ui_records.append(
                    {
                        "uri": related_uri,
                        "context": normalized_context,
                        "context_display": context_values,
                        "join_resource_id": record.get("join_resource_id"),
                    }
                )
            collected.append(
                RelationshipValues(
                    field_name=field_name,
                    display_label=other_label,
                    uris=list(uris),
                    is_join=True,
                    target_dataset=relationship.other_dataset,
                    property_uri=relationship.other_property_uri,
                    records=ui_records,
                )
            )

        for field_name, meta in field_metadata.items():
            if field_name in join_field_map:
                continue

            fk_info = meta.get("fk_relationship")
            if not fk_info:
                continue

            property_uri = (
                meta.get("property_uri")
                or fk_info.get("source_property_uri")
                or fk_info.get("source_canonical_property")
            )
            if not property_uri:
                continue

            uris = self._get_fk_values(
                entity_resource=entity_resource,
                property_uri=property_uri,
            )
            if not uris:
                continue

            target_dataset = fk_info.get("target_dataset")
            display_label = target_dataset
            if target_dataset:
                try:
                    display_label = self.get_dataset_summary(target_dataset).display_label
                except ValueError:
                    display_label = target_dataset

            collected.append(
                RelationshipValues(
                    field_name=field_name,
                    display_label=display_label or field_name,
                    uris=uris,
                    is_join=False,
                    target_dataset=target_dataset,
                    property_uri=property_uri,
                    editable=True,
                )
            )

        exclude_datasets = {
            rel.target_dataset
            for rel in collected
            if rel.target_dataset
        }

        collected.extend(
            self._collect_reverse_fk_values(
                dataset_name=dataset_name,
                entity_resource=entity_resource,
                field_metadata=field_metadata,
                join_field_map=join_field_map,
                exclude_datasets=exclude_datasets,
            )
        )

        return collected

    def _collect_reverse_fk_values(
        self,
        *,
        dataset_name: str,
        entity_resource: Resource,
        field_metadata: Dict[str, Dict[str, Any]],
        join_field_map: Dict[str, JoinRelationship],
        exclude_datasets: Set[str],
    ) -> List[RelationshipValues]:
        """
        Gather entities from other datasets that reference the current entity via FK.

        These values are used for read-only badges on the dataset panel.
        """
        is_part_of_uri = "http://purl.org/dc/terms/isPartOf"
        reverse_values: List[RelationshipValues] = []
        for candidate in self._schema_service.list_datasets():
            if candidate == dataset_name or candidate in exclude_datasets:
                continue

            schema = self.get_dataset_schema(candidate)
            if schema.get("junction_schema"):
                # Junction datasets are already handled via join relationships
                continue

            fk_rels: List[Dict[str, Any]] = schema.get("fk_relationships", []) or []
            relevant_rels = [
                rel for rel in fk_rels if rel.get("target_dataset") == dataset_name
            ]
            if not relevant_rels:
                continue

            candidate_dataset_resource = self._resolve_dataset_resource(candidate, schema)
            candidate_summary = self.get_dataset_summary(candidate)
            collected_subject_ids: Set[int] = set()

            for rel in relevant_rels:
                property_uri = (
                    rel.get("source_property_uri")
                    or rel.get("source_canonical_property")
                )
                property_resource = self._get_property_resource(property_uri)
                if property_resource is None:
                    continue

                subject_ids = Triple.objects.filter(
                    predicate=property_resource._resource,
                    object=entity_resource,
                ).values_list("subject_id", flat=True)
                if not subject_ids:
                    continue

                if candidate_dataset_resource:
                    member_ids = set(
                        Triple.objects.filter(
                            subject_id__in=subject_ids,
                            predicate__uri=is_part_of_uri,
                            object=candidate_dataset_resource,
                        ).values_list("subject_id", flat=True)
                    )
                else:
                    member_ids = set(subject_ids)

                if not member_ids:
                    member_ids = set(subject_ids)

                if not member_ids:
                    continue

                collected_subject_ids.update(member_ids)

            if not collected_subject_ids:
                continue

            uris = list(
                Resource.objects.filter(id__in=collected_subject_ids).values_list(
                    "uri", flat=True
                )
            )
            if not uris:
                continue

            reverse_values.append(
                RelationshipValues(
                    field_name=f"__reverse__{candidate}",
                    display_label=candidate_summary.display_label,
                    uris=uris,
                    is_join=False,
                    target_dataset=candidate,
                    editable=False,
                )
            )

        return reverse_values

    # ------------------------------------------------------------------ #
    # Entity helpers
    # ------------------------------------------------------------------ #
    def get_initial_entity_data(
        self, dataset_name: str, anchor_values: Dict[str, str]
    ) -> Optional[Tuple[Dict[str, Any], str]]:
        """
        Load an existing entity by its anchor values.

        Returns:
            Tuple of (initial_form_data, entity_uri) or None if not found.
        """
        schema = self.get_dataset_schema(dataset_name)
        ordered_anchor_values = self._ordered_anchor_values(schema, anchor_values)
        if not ordered_anchor_values:
            return None

        entity_uri = self._build_entity_uri(dataset_name, ordered_anchor_values)
        resource = Resource.objects.filter(uri=entity_uri).first()
        if not resource:
            return None

        entity = EntityResource(resource)
        initial: Dict[str, Any] = {}

        for column_name, property_resource in schema.get("properties", {}).items():
            property_wrapper = PropertyResource(property_resource)
            values = entity.get_property(property_wrapper)
            if not values:
                continue

            if column_name in schema.get("multi_value_schemas", {}):
                import json
                prepared_values = [
                    self._prepare_form_value(
                        schema=schema,
                        column_name=column_name,
                        value=value,
                    )
                    for value in values
                    if value is not None
                ]
                initial[column_name] = json.dumps(prepared_values)
            else:
                first_value = values[0]
                initial[column_name] = self._prepare_form_value(
                    schema=schema,
                    column_name=column_name,
                    value=first_value,
                )

        # Preserve anchor values explicitly (in case form hides them)
        for anchor_col, value in zip(
            [a["column_name"] for a in schema.get("anchor_columns", [])],
            ordered_anchor_values,
        ):
            initial.setdefault(anchor_col, value)

        return initial, entity_uri

    def load_entity_by_uri(
        self, dataset_name: str, entity_uri: str
    ) -> Optional[Dict[str, Any]]:
        """
        Load an existing entity by its URI for editing.

        Returns:
            Dict of initial form data or None if not found.
        """
        schema = self.get_dataset_schema(dataset_name)
        resource = Resource.objects.filter(uri=entity_uri).first()
        if not resource:
            return None

        entity = EntityResource(resource)
        initial: Dict[str, Any] = {}

        for column_name, property_resource in schema.get("properties", {}).items():
            property_wrapper = PropertyResource(property_resource)
            values = entity.get_property(property_wrapper)
            if not values:
                continue

            if column_name in schema.get("multi_value_schemas", {}):
                import json
                prepared_values = [
                    self._prepare_form_value(
                        schema=schema,
                        column_name=column_name,
                        value=value,
                    )
                    for value in values
                    if value is not None
                ]
                initial[column_name] = json.dumps(prepared_values)
            else:
                first_value = values[0]
                initial[column_name] = self._prepare_form_value(
                    schema=schema,
                    column_name=column_name,
                    value=first_value,
                )

        # Extract and preserve anchor values from URI
        uri_parts = entity_uri.split('/')
        if uri_parts:
            identifier = uri_parts[-1]
            anchor_columns = [a["column_name"] for a in schema.get("anchor_columns", [])]
            if anchor_columns and '_' in identifier:
                # If identifier has underscores, try to split it
                id_parts = identifier.split('_')
                for i, anchor_col in enumerate(anchor_columns):
                    if i < len(id_parts):
                        initial.setdefault(anchor_col, id_parts[i])
            elif anchor_columns and len(anchor_columns) == 1:
                # Single anchor column, use entire identifier
                initial.setdefault(anchor_columns[0], identifier)

        return initial

    def save_entity(
        self,
        dataset_name: str,
        entity_data: Dict[str, Any],
        *,
        entity_uri: Optional[str] = None,
    ) -> Tuple[str, bool]:
        """
        Create or update an entity and return its URI and a created flag.
        """
        schema = self.get_dataset_schema(dataset_name)
        properties = schema.get("properties", {})
        column_metadata = schema.get("column_metadata", {})
        multi_value_schemas = schema.get("multi_value_schemas", {})
        external_schemas = schema.get("external_ontology_schemas", {})
        fk_lookup = self._build_fk_lookup(schema)

        with transaction.atomic():
            # Determine target entity resource
            if entity_uri:
                entity_resource = Resource.objects.filter(uri=entity_uri).first()
                created = False
                if not entity_resource:
                    raise ValueError(
                        f"Entity '{entity_uri}' not found for dataset '{dataset_name}'"
                    )
            else:
                anchor_values = self._ordered_anchor_values(schema, entity_data)
                # Auto-generate anchor values if not provided
                if not anchor_values:
                    anchor_columns = schema.get("anchor_columns", [])
                    if anchor_columns:
                        # Generate auto-ID and populate first anchor field
                        auto_id = generate_auto_id(dataset_name)
                        first_anchor_column = anchor_columns[0].get("column_name")
                        if first_anchor_column:
                            entity_data[first_anchor_column] = auto_id
                            anchor_values = [auto_id]

                if not anchor_values:
                    raise ValueError(
                        f"Missing anchor values for dataset '{dataset_name}'"
                    )
                entity_uri = self._build_entity_uri(dataset_name, anchor_values)
                entity_resource = self._processor.resource_manager.create_entity_resource(
                    entity_uri,
                    dataset_name,
                )
                created = True

                # Link entity to dataset container using Dublin Core isPartOf
                dataset_resource = self._processor.dataset_blueprints[dataset_name][
                    "dataset_resource"
                ]
                is_part_of_uri = "http://purl.org/dc/terms/isPartOf"
                self._processor.resource_manager.create_relationship_triple(
                    entity_resource,
                    is_part_of_uri,
                    dataset_resource,
                )

                # Add rdf:type triple for the entity
                entity_type_res = schema.get("entity_type")
                if entity_type_res:
                    rdf_type_uri = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
                    self._processor.resource_manager.create_relationship_triple(
                        entity_resource,
                        rdf_type_uri,
                        entity_type_res,
                    )

            # Clear existing property triples for update scenarios
            # But exclude TripleCreatorWidget fields which are managed via HTMX
            property_ids = []
            for column_name, res in properties.items():
                col_meta = column_metadata.get(column_name, {})
                # Skip TripleCreatorWidget fields - they are managed separately via HTMX endpoints
                if col_meta.get("widget") == "TripleCreatorWidget":
                    continue
                property_ids.append(res.id)

            if property_ids:
                Triple.objects.filter(
                    subject=entity_resource, predicate_id__in=property_ids
                ).delete()

            # Recreate property triples based on cleaned data
            for column_name, property_resource in properties.items():
                if column_name not in entity_data:
                    continue

                value = entity_data[column_name]
                if value in (None, "", []):
                    continue

                fk_info = fk_lookup.get(column_name)

                if fk_info:
                    for target_value in self._normalize_fk_values(
                        value,
                        multi_value_schemas.get(column_name),
                    ):
                        self._create_fk_relationship(
                            entity_resource,
                            property_resource,
                            fk_info,
                            target_value,
                        )
                    continue

                if column_name in multi_value_schemas:
                    # Parse values from + button UI (JSON array) or CSV import (separator)
                    separator = multi_value_schemas[column_name]["separator"]

                    if isinstance(value, str) and value.startswith('['):
                        # From + button UI: JSON array
                        try:
                            import json
                            values = json.loads(value)
                        except (json.JSONDecodeError, ValueError):
                            # Fallback to separator split
                            values = [v.strip() for v in value.split(separator)]
                    elif isinstance(value, str):
                        # Legacy CSV import: separator split
                        values = [v.strip() for v in value.split(separator)]
                    else:
                        values = value

                    for single_value in values:
                        if single_value:
                            self._processor.resource_manager.create_property_triple(
                                entity_resource,
                                property_resource.uri,
                                str(single_value),
                                "http://www.w3.org/2001/XMLSchema#string",
                            )
                    continue

                if column_name in external_schemas:
                    template = external_schemas[column_name].get("uri_template", "")
                    normalized_value = self._normalize_external_identifier(template, value)
                    entity_data[column_name] = normalized_value
                    external_uri = self._format_external_uri(
                        column_name=column_name,
                        template=template,
                        value=normalized_value,
                        entity_data=entity_data,
                    )
                    external_resource, _ = Resource.objects.get_or_create(
                        uri=external_uri,
                        defaults={
                            "resource_type": ResourceType.ENTITY,
                            "name": str(normalized_value or value)[:100],
                            "is_placeholder": False,
                            "organization": None,
                        },
                    )
                    self._processor.resource_manager.create_relationship_triple(
                        entity_resource,
                        property_resource.uri,
                        external_resource,
                    )
                    continue

                # Default literal handling
                datatype = column_metadata.get(column_name, {}).get(
                    "datatype", "http://www.w3.org/2001/XMLSchema#string"
                )
                self._processor.resource_manager.create_property_triple(
                    entity_resource,
                    property_resource.uri,
                    str(value),
                    datatype,
                )
        return entity_uri, created

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _format_external_uri(
        self,
        *,
        column_name: str,
        template: str,
        value: Any,
        entity_data: Dict[str, Any],
    ) -> str:
        """
        Resolve an external ontology URI template, supporting legacy placeholder
        names like {identifier} alongside the current {value} token.
        """
        formatter = string.Formatter()
        format_kwargs: Dict[str, Any] = {
            "value": value,
            "identifier": value,
            column_name: value,
        }

        for _, field_name, _, _ in formatter.parse(template):
            if not field_name or field_name in format_kwargs:
                continue
            if field_name in entity_data:
                format_kwargs[field_name] = entity_data[field_name]

        try:
            return template.format(**format_kwargs)
        except KeyError as exc:
            missing_field = exc.args[0] if exc.args else "value"
            raise ValueError(
                f"URI template for column '{column_name}' requires value for '{missing_field}'"
            ) from exc

    def _build_entity_uri(self, dataset_name: str, anchor_values: List[str]) -> str:
        entity_identifier = "_".join(
            str(value).strip() for value in anchor_values if str(value).strip()
        )
        return self._processor.resource_manager.generate_entity_uri(
            dataset_name, entity_identifier
        )

    @staticmethod
    def _ordered_anchor_values(
        schema: Dict[str, Any], values: Dict[str, Any]
    ) -> List[str]:
        ordered: List[str] = []
        for anchor_info in schema.get("anchor_columns", []):
            column_name = anchor_info.get("column_name")
            if not column_name:
                continue
            raw_value = values.get(column_name)
            if raw_value in (None, ""):
                return []
            ordered.append(str(raw_value))
        return ordered

    @staticmethod
    def _build_fk_lookup(schema: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        lookup: Dict[str, Dict[str, Any]] = {}
        for fk_rel in schema.get("fk_relationships", []):
            source_column = fk_rel.get("source_column")
            if not source_column:
                continue
            lookup[source_column] = fk_rel
        return lookup

    @staticmethod
    def _normalize_fk_values(
        value: Any, multi_value_schema: Optional[Dict[str, Any]]
    ) -> List[str]:
        if value in (None, "", []):
            return []

        raw_values: List[Any]

        # Try to parse as JSON array first (from + button UI)
        if isinstance(value, str) and value.startswith('['):
            try:
                import json
                raw_values = json.loads(value)
            except (json.JSONDecodeError, ValueError):
                # Fallback to separator split for backwards compatibility
                if multi_value_schema:
                    separator = multi_value_schema.get("separator", ",")
                    raw_values = [v.strip() for v in value.split(separator)]
                else:
                    raw_values = [value]
        elif isinstance(value, (list, tuple, set)):
            raw_values = list(value)
        elif multi_value_schema:
            # Legacy CSV import path: split by separator
            separator = multi_value_schema.get("separator", ",")
            raw_values = [v.strip() for v in str(value).split(separator)]
        else:
            raw_values = [value]

        normalized: List[str] = []
        seen = set()
        for item in raw_values:
            if isinstance(item, dict):
                candidate = item.get("uri") or item.get("value") or ""
            else:
                candidate = item
            item_str = str(candidate).strip()
            if not item_str:
                continue
            canonical, _ = decode_placeholder_uri(item_str)
            if canonical and canonical not in seen:
                normalized.append(canonical)
                seen.add(canonical)
        return normalized

    # ------------------------------------------------------------------ #
    # Join dataset helpers
    # ------------------------------------------------------------------ #

    def _get_property_resource(self, property_uri: Optional[str]) -> Optional[PropertyResource]:
        if not property_uri:
            return None
        resource = Resource.objects.filter(uri=property_uri).first()
        if resource is None:
            name = property_uri.rsplit("/", 1)[-1]
            resource, _ = Resource.objects.get_or_create(
                uri=property_uri,
                defaults={
                    "resource_type": ResourceType.PROPERTY,
                    "name": name,
                    "organization": self.organization,
                },
            )
        return PropertyResource(resource)

    def _get_join_entity_records(
        self,
        relationship: JoinRelationship,
        entity_uri: str,
    ) -> List[Dict[str, Any]]:
        entity_resource = Resource.objects.filter(uri=entity_uri).first()
        if entity_resource is None:
            return []

        self_property = self._get_property_resource(relationship.self_property_uri)
        other_property = self._get_property_resource(relationship.other_property_uri)
        if self_property is None or other_property is None:
            return []

        join_subject_ids = Triple.objects.filter(
            predicate=self_property._resource,
            object=entity_resource,
        ).values_list("subject_id", flat=True)

        if not join_subject_ids:
            return []

        context_property_map: Dict[str, PropertyResource] = {}
        for context_spec in relationship.context_columns:
            property_uri = context_spec.get("property_uri")
            if not property_uri:
                continue
            property_resource = self._get_property_resource(property_uri)
            if property_resource:
                context_property_map[context_spec["column"]] = property_resource

        target_triples = Triple.objects.filter(
            subject_id__in=join_subject_ids,
            predicate=other_property._resource,
            object__resource_type=ResourceType.ENTITY,
        ).values_list("subject_id", "object__uri")

        records: List[Dict[str, Any]] = []
        triples_by_subject: Dict[str, str] = {str(subject_id): other_uri for subject_id, other_uri in target_triples}

        for subject_id in join_subject_ids:
            subject_key = str(subject_id)
            related_uri = triples_by_subject.get(subject_key)
            if not related_uri:
                continue

            context_values: Dict[str, str] = {}
            for column_name, property_resource in context_property_map.items():
                value = ""
                context_triples = Triple.objects.filter(
                    subject_id=subject_id,
                    predicate=property_resource._resource,
                ).select_related("object")
                for triple in context_triples:
                    obj = triple.object
                    if obj is None:
                        continue
                    value = obj.value or obj.name or obj.uri or ""
                    if value:
                        break
                context_values[column_name] = value

            records.append(
                {
                    "join_resource_id": subject_key,
                    "related_uri": related_uri,
                    "context": context_values,
                }
            )

        return records

    def _get_join_entity_map(
        self,
        relationship: JoinRelationship,
        entity_uri: str,
    ) -> Dict[str, str]:
        records = self._get_join_entity_records(relationship, entity_uri)
        return {
            record["join_resource_id"]: record["related_uri"]
            for record in records
            if record.get("join_resource_id") and record.get("related_uri")
        }

    def _create_join_entity(
        self,
        relationship: JoinRelationship,
        entity_uri: str,
        related_uri: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        self_resource = Resource.objects.filter(uri=entity_uri).first()
        if self_resource is None:
            return

        self_entity = EntityResource(self_resource)
        other_entity, _ = EntityResource.get_or_create(related_uri)

        join_entity, _ = EntityResource.create_by_organization_and_dataset_name(
            organization=self.organization,
            dataset_name=relationship.join_dataset,
            base_uri=self.base_uri,
        )

        join_class = relationship.join_dataset_schema.get("entity_type")
        if join_class is not None:
            join_entity.set_type(ClassResource(join_class))

        self_property = self._get_property_resource(relationship.self_property_uri)
        other_property = self._get_property_resource(relationship.other_property_uri)
        if self_property is None or other_property is None:
            return

        join_entity.set_property(self_property, self_entity)
        join_entity.set_property(other_property, other_entity)
        self._apply_join_context(join_entity, relationship, context or {})

    def _apply_join_context(
        self,
        join_entity: EntityResource,
        relationship: JoinRelationship,
        context: Dict[str, Any],
    ) -> None:
        if not relationship.context_columns:
            return

        for context_spec in relationship.context_columns:
            column_name = context_spec.get("column")
            property_uri = context_spec.get("property_uri")
            if not column_name or not property_uri:
                continue

            property_resource = self._get_property_resource(property_uri)
            if property_resource is None:
                continue

            value = context.get(column_name)
            Triple.objects.filter(
                subject=join_entity._resource,
                predicate=property_resource._resource,
            ).delete()

            if value in (None, ""):
                continue

            join_entity.set_property(property_resource, str(value))

    def sync_join_relationship(
        self,
        *,
        entity_uri: str,
        relationship: JoinRelationship,
        related_items: List[Any],
    ) -> None:
        normalized_items: List[Dict[str, Any]] = []
        for item in related_items:
            if isinstance(item, str):
                uri = item.strip()
                if uri:
                    normalized_items.append({"uri": uri, "context": {}})
            elif isinstance(item, dict):
                uri = str(item.get("uri") or "").strip()
                if not uri:
                    continue
                context = item.get("context") or {}
                if not isinstance(context, dict):
                    context = {}
                normalized_items.append(
                    {
                        "uri": uri,
                        "context": {str(k): ("" if v is None else str(v)) for k, v in context.items()},
                    }
                )

        existing_records = self._get_join_entity_records(relationship, entity_uri)
        used_indices: Set[int] = set()

        def context_dict(record: Dict[str, Any]) -> Dict[str, str]:
            ctx = record.get("context") or {}
            if isinstance(ctx, dict):
                return {str(k): ("" if v is None else str(v)) for k, v in ctx.items()}
            return {}

        # Delete or update existing records as needed
        for desired in normalized_items:
            uri = desired["uri"]
            context = context_dict(desired)

            exact_match_index = None
            for idx, record in enumerate(existing_records):
                if idx in used_indices:
                    continue
                if record.get("related_uri") == uri and context_dict(record) == context:
                    exact_match_index = idx
                    break

            if exact_match_index is not None:
                used_indices.add(exact_match_index)
                continue

            # Try to find record with same URI and update context
            updated = False
            for idx, record in enumerate(existing_records):
                if idx in used_indices:
                    continue
                if record.get("related_uri") == uri:
                    join_resource = Resource.objects.filter(id=record.get("join_resource_id")).first()
                    if join_resource:
                        join_entity = EntityResource(join_resource)
                        self._apply_join_context(join_entity, relationship, context)
                    used_indices.add(idx)
                    updated = True
                    break

            if not updated:
                self._create_join_entity(
                    relationship,
                    entity_uri,
                    uri,
                    context=context,
                )

        # Delete any remaining existing relationships that were not matched
        for idx, record in enumerate(existing_records):
            if idx in used_indices:
                continue
            join_resource_id = record.get("join_resource_id")
            if join_resource_id:
                Resource.objects.filter(id=join_resource_id).delete()

    def get_join_values(self, relationship: JoinRelationship, entity_uri: str) -> List[str]:
        return list(self._get_join_entity_map(relationship, entity_uri).values())

    def save_multi_fk_relationship(
        self,
        *,
        entity_uri: str,
        property_uri: str,
        related_uris: List[str],
    ) -> None:
        """Save multiple FK relationships, replacing existing ones."""
        from arkumu.metadata.models.resource import Resource
        from arkumu.metadata.models.triples import Triple

        # Get the entity and property resources
        entity = Resource.objects.filter(uri=entity_uri).first()
        predicate = Resource.objects.filter(uri=property_uri).first()

        if not entity or not predicate:
            return

        # Delete existing triples for this property
        Triple.objects.filter(
            subject=entity,
            predicate=predicate,
        ).delete()

        # Create new triples for each related URI
        for related_uri in related_uris:
            if not related_uri:
                continue

            # Get or create the related resource
            related_resource = Resource.objects.filter(uri=related_uri).first()
            if not related_resource:
                # Try to create it if it's a valid URI
                try:
                    related_resource = Resource.objects.create(
                        uri=related_uri,
                        source=self.organization,
                    )
                except Exception:
                    continue  # Skip if we can't create the resource

            # Create the triple
            Triple.objects.create(
                subject=entity,
                predicate=predicate,
                object=related_resource,
                source=self.organization,
            )

    def _create_fk_relationship(
        self,
        entity_resource: Resource,
        property_resource: Resource,
        fk_info: Dict[str, Any],
        target_value: str,
    ) -> None:
        target_dataset = fk_info.get("target_dataset")
        if not target_dataset:
            return

        parsed = urlparse(str(target_value))
        if parsed.scheme and parsed.netloc:
            target_uri = str(target_value)
        else:
            target_uri = self._processor.resource_manager.generate_entity_uri(
                target_dataset, target_value
            )

        target_resource = Resource.objects.filter(uri=target_uri).first()
        if not target_resource:
            target_resource = self._processor.resource_manager.create_entity_resource(
                target_uri,
                target_dataset,
                is_stub=True,
            )
            target_blueprint = self._processor.dataset_blueprints.get(target_dataset)
            if target_blueprint:
                dataset_resource = target_blueprint.get("dataset_resource")
                if dataset_resource:
                    # Use Dublin Core isPartOf for consistency with existing entities
                    is_part_of_uri = "http://purl.org/dc/terms/isPartOf"
                    self._processor.resource_manager.create_relationship_triple(
                        target_resource,
                        is_part_of_uri,
                        dataset_resource,
                    )
                entity_type = target_blueprint.get("entity_type_resource")
                if entity_type:
                    rdf_type_uri = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
                    self._processor.resource_manager.create_relationship_triple(
                        target_resource,
                        rdf_type_uri,
                        entity_type,
                    )

        self._processor.resource_manager.create_relationship_triple(
            entity_resource,
            property_resource.uri,
            target_resource,
        )

    def _get_fk_values(
        self,
        *,
        entity_resource: Resource,
        property_uri: Optional[str],
    ) -> List[str]:
        property_resource = self._get_property_resource(property_uri)
        if property_resource is None:
            return []

        uris = [
            uri
            for uri in Triple.objects.filter(
                subject=entity_resource,
                predicate=property_resource._resource,
                object__resource_type=ResourceType.ENTITY,
            ).values_list("object__uri", flat=True)
            if uri
        ]
        return uris

    def list_triple_relationships(
        self,
        *,
        subject_uri: str,
        predicate_uri: str,
        target_dataset: Optional[str] = None,
        display_property_uri: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Return existing triple relationships for a subject/predicate combination.
        """
        if not subject_uri or not predicate_uri:
            return []

        subject = Resource.objects.filter(uri=subject_uri).first()
        if subject is None:
            return []

        triples_qs = (
            Triple.objects.filter(
                subject=subject,
                predicate__uri=predicate_uri,
            )
            .filter(Q(source=self.organization) | Q(source__isnull=True))
            .select_related("object")
            .order_by("object__name", "object__uri")
        )

        from arkumu.metadata.services.entity_label_service import infer_entity_label

        results: List[Dict[str, Any]] = []
        for triple in triples_qs:
            obj = triple.object
            if obj is None:
                continue
            object_uri = getattr(obj, "uri", "")
            if not object_uri:
                continue
            label = infer_entity_label(
                self,
                object_uri,
                target_dataset=target_dataset,
                display_property_uri=display_property_uri,
            )
            results.append(
                {
                    "id": str(triple.id),
                    "uri": object_uri,
                    "label": label or object_uri,
                    "source_id": getattr(triple.source, "id", None),
                }
            )
        return results

    def create_triple_relationship(
        self,
        *,
        subject_uri: str,
        predicate_uri: str,
        object_uri: str,
    ) -> Tuple[bool, Optional[Triple]]:
        """
        Create or retrieve a triple for the provided subject/predicate/object.
        """
        if not subject_uri or not predicate_uri or not object_uri:
            return False, None

        if subject_uri == object_uri:
            return False, None

        subject = Resource.objects.filter(uri=subject_uri).first()
        predicate = Resource.objects.filter(uri=predicate_uri).first()
        target = Resource.objects.filter(uri=object_uri).first()

        if subject is None or predicate is None or target is None:
            return False, None

        triple, created = Triple.objects.get_or_create(
            subject=subject,
            predicate=predicate,
            object=target,
            source=self.organization,
            defaults={"is_derived": False},
        )
        if not created and triple.source != self.organization:
            triple.source = self.organization
            triple.save(update_fields=["source"])
        return True, triple

    def delete_triple_relationship(
        self,
        *,
        subject_uri: str,
        predicate_uri: str,
        object_uri: str,
    ) -> int:
        """
        Delete a triple belonging to the current organisation.
        Returns the number of rows removed.
        """
        if not subject_uri or not predicate_uri or not object_uri:
            return 0
        return Triple.objects.filter(
            subject__uri=subject_uri,
            predicate__uri=predicate_uri,
            object__uri=object_uri,
            source=self.organization,
        ).delete()[0]

    def suggest_triple_targets(
        self,
        *,
        target_dataset: str,
        query: str = "",
        property_uri: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, str]]:
        """
        Suggest entity targets for a triple based on dataset membership and literals.
        """
        if not target_dataset:
            return []

        try:
            schema = self.get_dataset_schema(target_dataset)
        except ValueError:
            return []

        dataset_resource = self._resolve_dataset_resource(target_dataset, schema)
        if not dataset_resource:
            return []

        is_part_of_uri = "http://purl.org/dc/terms/isPartOf"
        entities_qs = Triple.objects.filter(
            predicate__uri=is_part_of_uri,
            object=dataset_resource,
        ).values_list("subject__uri", flat=True)

        literal_label_map: Dict[str, str] = {}
        uri_matches: List[str] = []
        if query:
            literal_qs = Triple.objects.filter(
                subject__uri__in=entities_qs,
                object__resource_type=ResourceType.LITERAL,
            )
            if property_uri:
                literal_qs = literal_qs.filter(predicate__uri=property_uri)
                logger.info(f"🔍 Filtering triples by property: {property_uri}")
            else:
                logger.info(f"⚠️  No property_uri provided, searching ALL literal properties")

            literal_qs = literal_qs.filter(
                Q(object__value__icontains=query) | Q(object__name__icontains=query)
            ).values_list("subject__uri", "object__value", "object__name")

            logger.info(f"🔍 Found {literal_qs.count()} matches for query '{query}'")

            for subject_uri, value, name in literal_qs[: limit * 5]:
                label_candidate = next(
                    (str(val).strip() for val in (value, name) if val not in (None, "")),
                    "",
                )
                if not label_candidate:
                    continue
                literal_label_map.setdefault(subject_uri, label_candidate)
                if len(literal_label_map) >= limit:
                    break

            uri_matches = list(
                Triple.objects.filter(
                    predicate__uri=is_part_of_uri,
                    object=dataset_resource,
                    subject__uri__icontains=query,
                ).values_list("subject__uri", flat=True)[: limit * 2]
            )

        def append_unique(results: List[str], items: Iterable[str]) -> List[str]:
            collected = list(results)
            seen = set(collected)
            for item in items:
                if len(collected) >= limit:
                    break
                if item not in seen:
                    collected.append(item)
                    seen.add(item)
            return collected

        ordered_uris = append_unique([], literal_label_map.keys())
        if len(ordered_uris) < limit:
            ordered_uris = append_unique(ordered_uris, uri_matches)
        if len(ordered_uris) < limit:
            ordered_uris = append_unique(ordered_uris, list(entities_qs[:limit]))

        from arkumu.metadata.services.entity_label_service import infer_entity_label

        suggestions: List[Dict[str, str]] = []
        for uri in ordered_uris:
            label = literal_label_map.get(uri, "")
            inferred = infer_entity_label(self, uri, target_dataset=target_dataset)
            identifier = uri.rstrip("/").split("/")[-1]
            display_label = label or inferred or identifier
            suggestions.append(
                {
                    "uri": uri,
                    "label": display_label,
                    "identifier": identifier,
                }
            )
        return suggestions
