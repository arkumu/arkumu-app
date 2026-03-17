"""
Service for the simple project entry page.
Fully mapping-aware: reads the active mapping's schema_manifest to resolve
org-specific property URIs, entity type URIs, and dataset names.
Works for both canonical and non-canonical institutions.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Dict, List, Optional

from django.db import transaction

from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.resources import EntityResource
from arkumu.metadata.models.triples import Triple
from arkumu.storage.models.s3_file_objects import S3FileObject

if TYPE_CHECKING:
    from arkumu.users.models import Organization

logger = logging.getLogger(__name__)

# Canonical URIs used to look up org-specific URIs from the mapping
_CANONICAL = {
    "projekt_type": "http://arkumu.org/data/types/projekt",
    "titel": "http://arkumu.org/data/properties/bevorzugter-titel",
    "projektart": "http://arkumu.org/data/properties/projektart",
    "ereignis_type": "http://arkumu.org/data/types/ereignis",
    "ereignis_name": "http://arkumu.org/data/properties/ereignisname",
    "akteurin_type": "http://arkumu.org/data/types/akteurin",
    "akteurin_name": "http://arkumu.org/data/properties/deutscher-name",
    "digitales_objekt_type": "http://arkumu.org/data/types/digitales-objekt",
    "dateipfad": "http://arkumu.org/data/properties/dateipfad",
    "digitales_objekt_link": "http://arkumu.org/data/properties/digitales-objekt",
    "alternativer_titel": "http://arkumu.org/data/properties/alternativer-titel",
}


class MappingResolver:
    """Resolves org-specific URIs from the mapping's schema_manifest."""

    def __init__(self, organization: "Organization"):
        self.organization = organization
        mapping = Mapping.get_active_for_organization(organization)
        if not mapping or not mapping.mapping_config:
            raise ValueError(f"No active mapping for organization '{organization.code}'")
        self.manifest = mapping.mapping_config.get("schema_manifest", {})

    def find_dataset(self, canonical_type_uri: str) -> Optional[Dict]:
        """Find the first dataset whose entity_type.canonical_uri matches."""
        for ds_name, ds_config in self.manifest.items():
            if not isinstance(ds_config, dict):
                continue
            et = ds_config.get("entity_type", {})
            if et.get("canonical_uri") == canonical_type_uri:
                return {"name": ds_name, "config": ds_config, "entity_type": et}
        return None

    def find_property_uri(self, dataset_config: Dict, canonical_property_uri: str) -> Optional[str]:
        """Find the org-specific property URI from a dataset's properties."""
        for prop_name, prop_config in dataset_config.get("properties", {}).items():
            if prop_config.get("canonical_uri") == canonical_property_uri:
                return prop_config.get("uri")
        return None

    def find_property_uri_across_datasets(self, canonical_type_uri: str, canonical_property_uri: str) -> Optional[str]:
        """Find property URI across all datasets of a given entity type."""
        for ds_name, ds_config in self.manifest.items():
            if not isinstance(ds_config, dict):
                continue
            et = ds_config.get("entity_type", {})
            if et.get("canonical_uri") != canonical_type_uri:
                continue
            uri = self.find_property_uri(ds_config, canonical_property_uri)
            if uri:
                return uri
        return None


def _ensure_predicate(uri: str, name: str) -> Resource:
    """Get or create a property Resource."""
    resource, _ = Resource.objects.get_or_create(
        uri=uri,
        defaults={"resource_type": ResourceType.PROPERTY, "name": name},
    )
    return resource


class SimpleProjectEntryService:
    """Orchestrates project creation using mapping-resolved URIs."""

    def __init__(self, organization: "Organization"):
        self.organization = organization
        self.resolver = MappingResolver(organization)
        self._project_ds = self.resolver.find_dataset(_CANONICAL["projekt_type"])
        if not self._project_ds:
            raise ValueError(f"No project dataset found in mapping for '{organization.code}'")

    @transaction.atomic
    def create_project(
        self,
        *,
        title: str,
        alternativer_titel: Optional[str] = None,
        projektart_uri: Optional[str] = None,
        projektkategorie_uris: Optional[List[str]] = None,
        ereignis_uris: Optional[List[str]] = None,
        akteure_uris: Optional[List[str]] = None,
    ) -> EntityResource:
        """Create a project entity with all provided data using mapping URIs."""
        ds = self._project_ds
        base_uri = f"http://arkumu.org/data"

        # Create entity with dataset membership
        entity, _ = EntityResource.create_by_organization_and_dataset_name(
            organization=self.organization,
            dataset_name=ds["name"],
            base_uri=base_uri,
        )

        # Set rdf:type using the mapping's entity type URI
        type_uri = ds["entity_type"].get("uri", "")
        if type_uri:
            type_resource, _ = Resource.objects.get_or_create(
                uri=type_uri,
                defaults={"resource_type": ResourceType.CLASS, "name": ds["name"]},
            )
            rdf_type = Resource.objects.get(uri="http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
            Triple.objects.get_or_create(
                subject=entity._resource,
                predicate=rdf_type,
                object=type_resource,
                defaults={"source": self.organization},
            )

        # Title — use mapping-resolved URI
        title_uri = self.resolver.find_property_uri(ds["config"], _CANONICAL["titel"])
        if not title_uri:
            raise ValueError(f"Title property not found in mapping for '{self.organization.code}'")
        title_pred = _ensure_predicate(title_uri, "Bevorzugter Titel")
        title_literal, _ = Resource.objects.get_or_create(
            resource_type=ResourceType.LITERAL,
            value=title,
            defaults={"name": title[:100]},
        )
        Triple.objects.create(
            subject=entity._resource,
            predicate=title_pred,
            object=title_literal,
            source=self.organization,
        )

        # Projektart
        if projektart_uri:
            projektart_prop_uri = self.resolver.find_property_uri(ds["config"], _CANONICAL["projektart"])
            if projektart_prop_uri:
                pred = _ensure_predicate(projektart_prop_uri, "Projektart")
                target = Resource.objects.filter(uri=projektart_uri).first()
                if target:
                    Triple.objects.get_or_create(
                        subject=entity._resource,
                        predicate=pred,
                        object=target,
                        source=self.organization,
                        defaults={"is_derived": False},
                    )

        # Projektkategorie(n)
        if projektkategorie_uris:
            kat_prop_uri = self.resolver.find_property_uri(
                ds["config"], "http://arkumu.org/data/properties/projektkategorie"
            )
            if kat_prop_uri:
                pred = _ensure_predicate(kat_prop_uri, "Projektkategorie")
                for kat_uri in projektkategorie_uris:
                    if not kat_uri:
                        continue
                    target = Resource.objects.filter(uri=kat_uri).first()
                    if target:
                        Triple.objects.get_or_create(
                            subject=entity._resource,
                            predicate=pred,
                            object=target,
                            source=self.organization,
                            defaults={"is_derived": False},
                        )

        # Alternativer Titel
        if alternativer_titel:
            self._set_alternativer_titel(entity, alternativer_titel)

        # Ereignis links
        if ereignis_uris:
            self._link_entities(entity, _CANONICAL["ereignis_type"], "ereignis", ereignis_uris)

        # Akteure links
        if akteure_uris:
            self._link_entities(entity, _CANONICAL["akteurin_type"], "akteur", akteure_uris)

        return entity

    @transaction.atomic
    def create_digital_object(
        self,
        *,
        project: EntityResource,
        s3_key: str,
        file_name: str,
        content_type: str,
        file_size: int,
    ) -> EntityResource:
        """Create a digital object entity and link it to the project."""
        do_ds = self.resolver.find_dataset(_CANONICAL["digitales_objekt_type"])
        if not do_ds:
            raise ValueError(f"No digital object dataset in mapping for '{self.organization.code}'")

        base_uri = "http://arkumu.org/data"
        do_entity, _ = EntityResource.create_by_organization_and_dataset_name(
            organization=self.organization,
            dataset_name=do_ds["name"],
            base_uri=base_uri,
        )

        # Set rdf:type
        type_uri = do_ds["entity_type"].get("uri", "")
        if type_uri:
            type_resource, _ = Resource.objects.get_or_create(
                uri=type_uri,
                defaults={"resource_type": ResourceType.CLASS, "name": do_ds["name"]},
            )
            rdf_type = Resource.objects.get(uri="http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
            Triple.objects.get_or_create(
                subject=do_entity._resource,
                predicate=rdf_type,
                object=type_resource,
                defaults={"source": self.organization},
            )

        # Set dateipfad
        dateipfad_uri = self.resolver.find_property_uri(do_ds["config"], _CANONICAL["dateipfad"])
        if dateipfad_uri:
            pred = _ensure_predicate(dateipfad_uri, "Dateipfad")
            literal, _ = Resource.objects.get_or_create(
                resource_type=ResourceType.LITERAL,
                value=s3_key,
                defaults={"name": s3_key[:100]},
            )
            Triple.objects.create(
                subject=do_entity._resource,
                predicate=pred,
                object=literal,
                source=self.organization,
            )

        # Link digital object to project
        do_link_uri = self.resolver.find_property_uri_across_datasets(
            _CANONICAL["projekt_type"], _CANONICAL["digitales_objekt_link"]
        )
        if not do_link_uri:
            do_link_uri = f"http://arkumu.org/data/{self.organization.code}/properties/digitales-objekt"
        pred = _ensure_predicate(do_link_uri, "Digitales Objekt")
        Triple.objects.get_or_create(
            subject=project._resource,
            predicate=pred,
            object=do_entity._resource,
            source=self.organization,
            defaults={"is_derived": False},
        )

        # Link S3FileObject to the digital object Resource
        s3_file = S3FileObject.objects.filter(
            s3_key=s3_key,
            organization=self.organization.code,
        ).first()
        if s3_file:
            s3_file.related_resource = do_entity._resource
            s3_file.save(update_fields=["related_resource"])
        else:
            logger.warning("S3FileObject not found for key=%s org=%s", s3_key, self.organization.code)

        return do_entity

    def _set_alternativer_titel(self, project: EntityResource, text: str) -> None:
        """Set alternative title — mapping decides where it goes.

        Non-canonical orgs (khm, hmt): alternativer-titel is a literal on the project.
        Canonical orgs (fuk, det, rsh): alternativer-titel lives on a separate
        Alternativer_Titel entity linked to the project via alternativer-titel-set.
        The mapping's schema_manifest tells us which case applies.
        """
        canonical_uri = _CANONICAL["alternativer_titel"]

        # Case 1: property exists directly on the project dataset → literal
        proj_prop_uri = self.resolver.find_property_uri(self._project_ds["config"], canonical_uri)
        if proj_prop_uri:
            pred = _ensure_predicate(proj_prop_uri, "Alternativer Titel")
            literal, _ = Resource.objects.get_or_create(
                resource_type=ResourceType.LITERAL,
                value=text,
                defaults={"name": text[:100]},
            )
            Triple.objects.create(
                subject=project._resource,
                predicate=pred,
                object=literal,
                source=self.organization,
            )
            return

        # Case 2: property lives on a separate entity type → create sub-entity and link
        alt_titel_ds = self.resolver.find_dataset("http://arkumu.org/data/types/alternativer-titel")
        if not alt_titel_ds:
            logger.warning("No alternativer-titel dataset or property found in mapping for '%s'", self.organization.code)
            return

        base_uri = "http://arkumu.org/data"
        alt_entity, _ = EntityResource.create_by_organization_and_dataset_name(
            organization=self.organization,
            dataset_name=alt_titel_ds["name"],
            base_uri=base_uri,
        )

        # Set rdf:type
        type_uri = alt_titel_ds["entity_type"].get("uri", "")
        if type_uri:
            type_resource, _ = Resource.objects.get_or_create(
                uri=type_uri,
                defaults={"resource_type": ResourceType.CLASS, "name": alt_titel_ds["name"]},
            )
            rdf_type = Resource.objects.get(uri="http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
            Triple.objects.get_or_create(
                subject=alt_entity._resource,
                predicate=rdf_type,
                object=type_resource,
                defaults={"source": self.organization},
            )

        # Set the text value on the sub-entity
        prop_uri = self.resolver.find_property_uri(alt_titel_ds["config"], canonical_uri)
        if prop_uri:
            pred = _ensure_predicate(prop_uri, "Alternativer Titel")
            literal, _ = Resource.objects.get_or_create(
                resource_type=ResourceType.LITERAL,
                value=text,
                defaults={"name": text[:100]},
            )
            Triple.objects.create(
                subject=alt_entity._resource,
                predicate=pred,
                object=literal,
                source=self.organization,
            )

        # Link sub-entity to project via alternativer-titel-set
        link_uri = self.resolver.find_property_uri_across_datasets(
            _CANONICAL["projekt_type"],
            "http://arkumu.org/data/properties/alternativer-titel-set",
        )
        if link_uri:
            pred = _ensure_predicate(link_uri, "Alternativer Titel-Set")
            Triple.objects.get_or_create(
                subject=project._resource,
                predicate=pred,
                object=alt_entity._resource,
                source=self.organization,
                defaults={"is_derived": False},
            )

    def _link_entities(
        self,
        project: EntityResource,
        canonical_type_uri: str,
        link_name: str,
        uris: List[str],
    ) -> None:
        """Create relation triples using mapping-resolved predicate URIs."""
        # Find the property URI from the project dataset that links to this entity type
        link_canonical = f"http://arkumu.org/data/properties/{link_name}"
        pred_uri = self.resolver.find_property_uri_across_datasets(
            _CANONICAL["projekt_type"], link_canonical
        )
        if not pred_uri:
            pred_uri = f"http://arkumu.org/data/{self.organization.code}/properties/{link_name}"
            logger.warning("Link property '%s' not in mapping, using fallback: %s", link_name, pred_uri)

        pred = _ensure_predicate(pred_uri, link_name)
        for uri in uris:
            if not uri:
                continue
            target = Resource.objects.filter(uri=uri).first()
            if not target:
                logger.warning("Target resource not found for URI: %s", uri)
                continue
            Triple.objects.get_or_create(
                subject=project._resource,
                predicate=pred,
                object=target,
                source=self.organization,
                defaults={"is_derived": False},
            )
