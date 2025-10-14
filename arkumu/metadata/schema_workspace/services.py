from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from django.db import transaction
from arkumu.importer.services.schema_service import SchemaService
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.models.resources import EntityResource, PropertyResource
from arkumu.metadata.models.mappings import Mapping
from arkumu.users.models import Organization


@dataclass(frozen=True)
class DatasetSummary:
    dataset_name: str
    display_label: str
    anchor_columns: List[str]
    property_count: int
    relationship_count: int


class SchemaWorkspaceService:
    """Expose SchemaService blueprints in a UI-friendly format."""

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
        self._schema_service = SchemaService(
            mapping_id=str(mapping.id),
            institution=organization.code,
            base_uri=base_uri,
        )
        # Ensure processor and dataset blueprints are available once up front
        self._schema_service._ensure_schema_loaded()
        self._processor = self._schema_service._processor

    # ------------------------------------------------------------------ #
    # Blueprint inspection helpers
    # ------------------------------------------------------------------ #
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
            summaries.append(
                DatasetSummary(
                    dataset_name=dataset_name,
                    display_label=display_label,
                    anchor_columns=anchor_columns,
                    property_count=len(schema.get("properties", {})),
                    relationship_count=len(schema.get("fk_relationships", [])),
                )
            )

        # Order alphabetically by display label for predictable UI
        return sorted(summaries, key=lambda item: item.display_label.lower())

    def get_dataset_schema(self, dataset_name: str) -> Dict[str, Any]:
        schema = self._schema_service.get_dataset_schema(dataset_name)
        if not schema:
            raise ValueError(f"No schema blueprint found for dataset '{dataset_name}'")
        return schema

    def get_dataset_summary(self, dataset_name: str) -> DatasetSummary:
        schema = self.get_dataset_schema(dataset_name)
        entity_type = schema.get("entity_type")
        display_label = getattr(entity_type, "name", "") or dataset_name
        anchor_columns = [
            anchor["column_name"] for anchor in schema.get("anchor_columns", [])
        ]
        return DatasetSummary(
            dataset_name=dataset_name,
            display_label=display_label,
            anchor_columns=anchor_columns,
            property_count=len(schema.get("properties", {})),
            relationship_count=len(schema.get("fk_relationships", [])),
        )

    def get_field_metadata(self, dataset_name: str) -> Dict[str, Dict[str, Any]]:
        schema = self.get_dataset_schema(dataset_name)
        field_meta: Dict[str, Dict[str, Any]] = {}
        for column_name, column_meta in schema.get("column_metadata", {}).items():
            property_resource = schema["properties"].get(column_name)
            field_meta[column_name] = {
                **column_meta,
                "property_uri": getattr(property_resource, "uri", None),
                "property_label": getattr(property_resource, "name", column_name),
            }
        return field_meta

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

            column_meta = schema["column_metadata"].get(column_name, {})
            if column_name in schema.get("multi_value_schemas", {}):
                separator = schema["multi_value_schemas"][column_name]["separator"]
                initial[column_name] = separator.join(
                    str(value) for value in values if value is not None
                )
            else:
                first_value = values[0]
                if isinstance(first_value, EntityResource):
                    initial[column_name] = first_value._resource.uri
                else:
                    initial[column_name] = first_value

        # Preserve anchor values explicitly (in case form hides them)
        for anchor_col, value in zip(
            [a["column_name"] for a in schema.get("anchor_columns", [])],
            ordered_anchor_values,
        ):
            initial.setdefault(anchor_col, value)

        return initial, entity_uri

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

                # Link entity to dataset container
                dataset_resource = self._processor.dataset_blueprints[dataset_name][
                    "dataset_resource"
                ]
                is_part_of_uri = self._processor._generate_property_uri("isPartOf")
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
            property_ids = [res.id for res in properties.values()]
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
                    separator = multi_value_schemas[column_name]["separator"]
                    values = (
                        [v.strip() for v in value.split(separator)]
                        if isinstance(value, str)
                        else value
                    )
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
                    external_uri = external_schemas[column_name]["uri_template"].format(
                        value=value
                    )
                    external_resource, _ = Resource.objects.get_or_create(
                        uri=external_uri,
                        defaults={
                            "resource_type": ResourceType.ENTITY,
                            "name": str(value)[:100],
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
        if isinstance(value, (list, tuple, set)):
            raw_values = list(value)
        elif multi_value_schema:
            separator = multi_value_schema.get("separator", ",")
            raw_values = [v.strip() for v in str(value).split(separator)]
        else:
            raw_values = [value]

        normalized: List[str] = []
        seen = set()
        for item in raw_values:
            item_str = str(item).strip()
            if item_str and item_str not in seen:
                normalized.append(item_str)
                seen.add(item_str)
        return normalized

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
                    is_part_of_uri = self._processor._generate_property_uri("isPartOf")
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
