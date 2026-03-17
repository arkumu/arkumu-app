"""
Service for the simple project entry page.
Creates projects compatible with the existing RDF triple data model
by reusing EntityCreationService infrastructure.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from django.db import transaction

from arkumu.metadata.entity_creation.config import FieldConfig
from arkumu.metadata.entity_creation.services import EntityCreationService
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.resources import EntityResource
from arkumu.metadata.models.triples import Triple

if TYPE_CHECKING:
    from arkumu.users.models import Organization


class SimpleProjectEntryService:
    """Orchestrates project creation for the simple entry form."""

    def __init__(self, organization: "Organization"):
        self.organization = organization
        self._project_service = EntityCreationService.for_key("project", organization)

    @transaction.atomic
    def create_project(
        self,
        *,
        title: str,
        projektart_uri: Optional[str] = None,
        ereignis_uris: Optional[List[str]] = None,
        akteure_uris: Optional[List[str]] = None,
    ) -> EntityResource:
        """Create a project entity with all provided data."""
        entity, _ = EntityResource.create_by_organization_and_dataset_name(
            organization=self.organization,
            dataset_name=self._project_service.dataset_resource_name,
            base_uri=self._project_service.dataset_base_uri,
        )
        entity.set_type(self._project_service.ensure_class_resource())

        # Title
        title_field = self._get_field("bevorzugter_titel")
        if title_field:
            binding = self._project_service.ensure_property_resource(title_field)
            entity.set_property(binding.resource, title)

        # Projektart
        if projektart_uri:
            projektart_field = self._get_field("projektart_uri")
            if projektart_field:
                binding = self._project_service.ensure_property_resource(projektart_field)
                related, _ = EntityResource.get_or_create(projektart_uri)
                entity.set_property(binding.resource, related)

        # Ereignis links
        if ereignis_uris:
            self._link_entities(entity, "ereignis", ereignis_uris)

        # Akteure links
        if akteure_uris:
            self._link_entities(entity, "akteur", akteure_uris)

        return entity

    def _get_field(self, field_name: str) -> Optional[FieldConfig]:
        for field in self._project_service.config.fields:
            if field.field_name == field_name:
                return field
        return None

    def _link_entities(
        self,
        project: EntityResource,
        link_type: str,
        uris: List[str],
    ) -> None:
        """Create relation triples from project to existing entities."""
        predicate_uri = (
            f"{self._project_service.base_uri}/properties/{link_type}"
        )
        predicate_resource, _ = Resource.objects.get_or_create(
            uri=predicate_uri,
            defaults={
                "resource_type": ResourceType.PROPERTY,
                "name": link_type,
            },
        )
        for uri in uris:
            if not uri:
                continue
            target = Resource.objects.filter(uri=uri).first()
            if target:
                Triple.objects.get_or_create(
                    subject=project._resource,
                    predicate=predicate_resource,
                    object=target,
                    source=self.organization,
                    defaults={"is_derived": False},
                )
