"""
Service layer for metadata entity creation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple

from django.db import transaction

from arkumu.metadata.models.resource import Resource
from arkumu.metadata.models.resources import (
    ClassResource,
    EntityResource,
    PropertyResource,
)
from arkumu.metadata.models.triples import Triple

from .config import EntityCreationConfig, FieldConfig, ENTITY_CREATION_CONFIG


@dataclass(slots=True)
class PropertyBinding:
    """Cached property resource with metadata."""

    config: FieldConfig
    resource: PropertyResource


class EntityCreationService:
    """
    Central service that knows how to materialise entity resources based on the
    declarative configuration.
    """

    def __init__(self, config: EntityCreationConfig, organization):
        self.config = config
        self.organization = organization
        self.base_uri = f"http://arkumu.org/data/{organization.code}"
        self.dataset_base_uri = self.base_uri.rsplit("/", 1)[0] if "/" in self.base_uri else self.base_uri
        self.dataset_resource_name = self._resolve_dataset_resource_name()
        self._class_resource: Optional[ClassResource] = None
        self._property_cache: Dict[str, PropertyBinding] = {}

    @classmethod
    def for_key(cls, key: str, organization) -> "EntityCreationService":
        try:
            config = ENTITY_CREATION_CONFIG[key]
        except KeyError as exc:
            raise ValueError(f"Unknown entity creation key '{key}'") from exc
        return cls(config=config, organization=organization)

    def ensure_class_resource(self) -> ClassResource:
        if self._class_resource is None:
            uri = f"{self.base_uri}/{self.config.class_path}"
            class_resource, _ = ClassResource.get_or_create(
                uri=uri,
                name=self.config.class_label,
            )
            self._class_resource = class_resource
        return self._class_resource

    def ensure_property_resource(self, field: FieldConfig) -> PropertyBinding:
        if field.field_name not in self._property_cache:
            uri = f"{self.base_uri}/{field.property_path}"
            property_resource, _ = PropertyResource.get_or_create(
                uri=uri,
                name=field.property_label,
            )
            self._property_cache[field.field_name] = PropertyBinding(
                config=field,
                resource=property_resource,
            )
        return self._property_cache[field.field_name]

    def create_or_update_from_form(self, form) -> Tuple[EntityResource, bool]:
        """
        Create a new entity (or fetch an existing one) based on a validated form.

        Returns a tuple of the entity resource and a flag indicating whether it
        was newly created.
        """
        if not form.is_valid():
            raise ValueError("Form must be valid before calling create_or_update_from_form")

        selected_uri = form.cleaned_data.get("uri")
        if selected_uri:
            entity, created = EntityResource.get_or_create(selected_uri)
            EntityResource.ensure_dataset_membership(
                entity=entity,
                organization=self.organization,
                dataset_name=self.dataset_resource_name,
                base_uri=self.dataset_base_uri,
            )
            return entity, created

        with transaction.atomic():
            entity, _ = EntityResource.create_by_organization_and_dataset_name(
                organization=self.organization,
                dataset_name=self.dataset_resource_name,
                base_uri=self.dataset_base_uri,
            )
            entity.set_type(self.ensure_class_resource())

            for field in self.config.fields:
                value = form.cleaned_data.get(field.field_name)
                if value in (None, "", []):
                    continue
                binding = self.ensure_property_resource(field)
                self._assign_value(entity, binding, value)

        return entity, True

    def update_entity_from_form(self, *, entity: EntityResource, form) -> None:
        """
        Update an existing entity with values provided by a validated form.
        """
        if not form.is_valid():
            raise ValueError("Form must be valid before calling update_entity_from_form")

        cleaned = form.cleaned_data
        with transaction.atomic():
            EntityResource.ensure_dataset_membership(
                entity=entity,
                organization=self.organization,
                dataset_name=self.dataset_resource_name,
                base_uri=self.dataset_base_uri,
            )

            for field in self.config.fields:
                if field.field_name not in cleaned:
                    continue

                binding = self.ensure_property_resource(field)
                Triple.objects.filter(
                    subject=entity._resource,
                    predicate=binding.resource._resource,
                ).delete()

                value = cleaned.get(field.field_name)
                if value in (None, "", []):
                    continue

                self._assign_value(entity, binding, value)

    def _resolve_dataset_resource_name(self) -> str:
        if self.config.dataset_resource_name:
            return self.config.dataset_resource_name

        inferred = self._infer_dataset_resource_name_from_mapping()
        if inferred:
            return inferred
        return self.config.dataset_name

    def _infer_dataset_resource_name_from_mapping(self) -> Optional[str]:
        from arkumu.metadata.models.mappings import Mapping
        from arkumu.metadata.schema_workspace.services import SchemaWorkspaceService
        from arkumu.common.uri_utils import slugify_uri_part

        try:
            mapping = (
                Mapping.objects.filter(organization_id=self.organization.code)
                .order_by("-created_at")
                .first()
            )
        except Exception:
            return None
        if mapping is None:
            return None

        try:
            workspace_service = SchemaWorkspaceService(
                mapping=mapping,
                organization=self.organization,
                base_uri=self.dataset_base_uri,
            )
            dataset_summaries = workspace_service.list_datasets()
        except Exception:
            return None

        target_label = self.config.dataset_name.lower()
        target_slug = slugify_uri_part(self.config.dataset_name).lower()

        for summary in dataset_summaries:
            if summary.display_label and summary.display_label.lower() == target_label:
                return summary.dataset_name

        for summary in dataset_summaries:
            dataset_name_lower = summary.dataset_name.lower()
            if dataset_name_lower == target_label or target_slug in dataset_name_lower:
                return summary.dataset_name

        return None

    def _assign_value(
        self,
        entity: EntityResource,
        binding: PropertyBinding,
        value,
    ) -> None:
        """Persist a single value based on the configuration."""
        if binding.config.value_type == "literal":
            entity.set_property(binding.resource, value)
            return

        if binding.config.value_type == "entity":
            related, _ = EntityResource.get_or_create(value)
            entity.set_property(binding.resource, related)
            return

        if binding.config.value_type == "entity_multi":
            for uri in value:
                if not uri:
                    continue
                related, _ = EntityResource.get_or_create(uri)
                entity.set_property(binding.resource, related)
            return

        raise ValueError(f"Unsupported value type '{binding.config.value_type}'")

    def build_initial_data(self, entity: EntityResource) -> Dict[str, object]:
        """Return initial data for repopulating a form when an existing entity is selected."""
        initial: Dict[str, object] = {}
        for field in self.config.fields:
            binding = self.ensure_property_resource(field)
            values = entity.get_property(binding.resource)
            if not values:
                continue

            if field.value_type == "literal":
                initial[field.field_name] = values[0]
            elif field.value_type == "entity":
                related = values[0]
                initial[field.field_name] = self._extract_uri(related)
            elif field.value_type == "entity_multi":
                initial[field.field_name] = [
                    self._extract_uri(item) for item in values if item is not None
                ]
        return initial

    @staticmethod
    def _extract_uri(value) -> Optional[str]:
        """Coerce a property value into a URI string if possible."""
        if value is None:
            return None
        if isinstance(value, EntityResource):
            return value._resource.uri
        if hasattr(value, "uri"):
            return value.uri
        if isinstance(value, str):
            return value
        return None


class EntityInitialDataBuilder:
    """Helper for HTMX fragments – wraps error handling for initial data."""

    def __init__(self, service: EntityCreationService):
        self.service = service

    def get_initial_for_uri(self, uri: str) -> Optional[Dict[str, object]]:
        if not uri:
            return None
        try:
            resource = Resource.objects.get(uri=uri)
        except Resource.DoesNotExist:
            return None
        entity = EntityResource(resource)
        return self.service.build_initial_data(entity)
