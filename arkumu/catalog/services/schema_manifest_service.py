"""Utilities to consume schema manifests and expose canonical mappings."""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from django.core.cache import cache
from django.utils.text import slugify

from arkumu.metadata.models.mappings import Mapping

logger = logging.getLogger(__name__)


@dataclass
class CanonicalPropertyBinding:
    """Represents where a canonical property is implemented."""

    canonical_uri: str
    dataset: Optional[str] = None
    column: Optional[str] = None
    local_uri: Optional[str] = None
    name: Optional[str] = None

    @property
    def available(self) -> bool:
        return bool(self.dataset and self.column)


@dataclass
class CanonicalClassBinding:
    """Represents a canonical class and its known properties/relationships."""

    canonical_uri: str
    datasets: List[str] = field(default_factory=list)
    properties: Dict[str, List[CanonicalPropertyBinding]] = field(default_factory=dict)
    fk_relationships: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class CardProperty:
    """Spec for a card field tied to a canonical URI."""

    name: str
    canonical_uri: str
    bindings: List[CanonicalPropertyBinding] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return any(binding.available for binding in self.bindings)


@dataclass
class CardSection:
    """Group of properties belonging to a canonical class."""

    label: str
    canonical_class_uri: str
    properties: Dict[str, CardProperty]
    fk_relationships: List[Dict[str, Any]] = field(default_factory=list)
    relationship_contexts: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return any(prop.available for prop in self.properties.values())


@dataclass
class CardSchema:
    """Typed schema description for catalog cards."""

    sections: Dict[str, CardSection]

    def get_property(self, section: str, name: str) -> Optional[CardProperty]:
        section_obj = self.sections.get(section)
        if not section_obj:
            return None
        return section_obj.properties.get(name)


CARD_SCHEMA_TEMPLATE: CardSchema = CardSchema(
    sections={
        'project': CardSection(
            label='project',
            canonical_class_uri='http://arkumu.org/data/types/projekt',
            properties={
                'title': CardProperty('title', 'http://arkumu.org/data/properties/bevorzugter-titel'),
                'subtitle': CardProperty('subtitle', 'http://arkumu.org/data/properties/bevorzugter-untertitel'),
                'image': CardProperty('image', 'http://arkumu.org/data/properties/vorschaubild'),
                'event': CardProperty('event', 'http://arkumu.org/data/properties/ereignis'),
                'institution': CardProperty('institution', 'http://arkumu.org/data/properties/einliefernde-hochschule'),
                'category': CardProperty('category', 'http://arkumu.org/data/properties/projektkategorie'),
            },
        ),
        'event': CardSection(
            label='event',
            canonical_class_uri='http://arkumu.org/data/types/ereignis',
            properties={
                'start': CardProperty('start', 'http://arkumu.org/data/properties/ereignisbeginn'),
                'end': CardProperty('end', 'http://arkumu.org/data/properties/ereignisende'),
                'location': CardProperty('location', 'http://arkumu.org/data/properties/ereignisort'),
            },
        ),
        'actor_event': CardSection(
            label='actor_event',
            canonical_class_uri='http://arkumu.org/data/types/akteurin-ereignis-kreuztabelle',
            properties={
                'actor_link': CardProperty('actor_link', 'http://arkumu.org/data/properties/akteurin-im-ereignis'),
                'role_link': CardProperty('role_link', 'http://arkumu.org/data/properties/rollen-der-akteurin-im-ereignis'),
            },
        ),
        'actor': CardSection(
            label='actor',
            canonical_class_uri='http://arkumu.org/data/types/akteurin',
            properties={
                'name': CardProperty('name', 'http://arkumu.org/data/properties/deutscher-name'),
            },
        ),
        'role': CardSection(
            label='role',
            canonical_class_uri='http://arkumu.org/data/types/rolle',
            properties={
                'name': CardProperty('name', 'http://arkumu.org/data/properties/deutscher-name-der-rolle-breadcrumb'),
            },
        ),
        'digital_object': CardSection(
            label='digital_object',
            canonical_class_uri='http://arkumu.org/data/types/digitales-objekt',
            properties={
                'path': CardProperty('path', 'http://arkumu.org/data/properties/dateipfad'),
                'license': CardProperty('license', 'http://arkumu.org/data/properties/lizenzstatus'),
            },
            fk_relationships=[
                {
                    'source_property': 'http://arkumu.org/data/properties/lizenzstatus',
                    'target_property': 'http://arkumu.org/data/properties/uri',
                }
            ],
        ),
        'digital_object_license': CardSection(
            label='digital_object_license',
            canonical_class_uri='http://arkumu.org/data/types/digitales-objekt-lizenz',
            properties={
                'uri': CardProperty('uri', 'http://arkumu.org/data/properties/uri'),
                'label_de': CardProperty('label_de', 'http://arkumu.org/data/properties/deutscher-anzeigetext'),
                'label_en': CardProperty('label_en', 'http://arkumu.org/data/properties/englischer-anzeigetext'),
                'rights_statement': CardProperty('rights_statement', 'http://arkumu.org/data/properties/zugehoeriges-rechtestatement'),
                'identifier': CardProperty('identifier', 'http://arkumu.org/data/properties/digitales-objekt-lizenz-id'),
            },
        ),
        'institution': CardSection(
            label='institution',
            canonical_class_uri='http://arkumu.org/data/types/einliefernde-hochschule',
            properties={
                'german_name': CardProperty('german_name', 'http://arkumu.org/data/properties/deutscher-name-der-einliefernden-hochschule'),
            },
        ),
        'project_category': CardSection(
            label='project_category',
            canonical_class_uri='http://arkumu.org/data/types/projektkategorie',
            properties={
                'german_name': CardProperty('german_name', 'http://arkumu.org/data/properties/deutscher-name-der-projektkategorie-breadcrumb'),
                'synonyms': CardProperty('synonyms', 'http://arkumu.org/data/properties/synonyme'),
                'wikidata_id': CardProperty('wikidata_id', 'http://arkumu.org/data/properties/wikidata-id'),
            },
        ),
    },
)


_CARD_SCHEMA_CACHE_SENTINEL = object()


class SchemaManifestService:
    """Loads schema manifests and exposes canonical mappings for consumers."""

    # Card schema usage is read-heavy; rely on importer-driven invalidation rather than short TTLs.
    CACHE_TIMEOUT = 30 * 24 * 3600  # 30 days

    def get_card_schema(self, organization_code: str) -> CardSchema:
        """Return a card-specific view of the schema manifest for an organization."""
        logger.info(
            "SchemaManifestService.get_card_schema: Starting for org '%s'",
            organization_code,
        )

        cache_key = f"card_schema_manifest:{organization_code}"
        cached_schema = cache.get(cache_key, _CARD_SCHEMA_CACHE_SENTINEL)
        if cached_schema is not _CARD_SCHEMA_CACHE_SENTINEL:
            logger.info(
                "SchemaManifestService.get_card_schema: Cache HIT for built card schema (org '%s')",
                organization_code,
            )
            return copy.deepcopy(cached_schema)

        canonical_schema = self._get_canonical_schema(organization_code)

        logger.info(
            "SchemaManifestService.get_card_schema: Cache MISS for built card schema (org '%s')",
            organization_code,
        )

        # Create new schema with fresh binding lists (only copy structure, not data)
        schema = CardSchema(
            sections={
                name: CardSection(
                    label=section.label,
                    canonical_class_uri=section.canonical_class_uri,
                    properties={
                        prop_name: CardProperty(
                            name=prop.name,
                            canonical_uri=prop.canonical_uri,
                            bindings=[],
                        )
                        for prop_name, prop in section.properties.items()
                    },
                    fk_relationships=copy.deepcopy(section.fk_relationships),
                    relationship_contexts=copy.deepcopy(section.relationship_contexts),
                )
                for name, section in CARD_SCHEMA_TEMPLATE.sections.items()
            },
        )

        self._populate_card_schema(schema, canonical_schema)

        cache.set(cache_key, schema, self.CACHE_TIMEOUT)

        return copy.deepcopy(schema)

    def _get_canonical_schema(self, organization_code: str) -> Dict[str, Any]:
        # Get the active mapping for this organization
        canonical_schema = (
            Mapping.objects
            .filter(organization_id=organization_code, is_active=True)
            .first()
        )
        if not canonical_schema:
            logger.warning(
                "SchemaManifestService.get_canonical_schema: No canonical schema found for org '%s'",
                organization_code,
            )
            return {}

        try:
            mapping_payload = canonical_schema.mapping_config or {}
            if not isinstance(mapping_payload, dict):
                logger.error(
                    "SchemaManifestService.get_canonical_schema: mapping_config malformed for org '%s'",
                    organization_code,
                )
                return {}
            return mapping_payload
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error(
                "SchemaManifestService.get_canonical_schema: Failed to load schema for org '%s': %s",
                organization_code,
                exc,
                exc_info=True,
            )
            return {}

    def _populate_card_schema(self, schema: CardSchema, canonical_schema: Dict[str, Any]) -> None:
        """Populate schema template with binding information."""

        if not canonical_schema:
            logger.warning("SchemaManifestService._populate_card_schema: canonical schema missing")
            return

        canonical_classes = canonical_schema.get("classes", [])
        canonical_properties = canonical_schema.get("properties", [])

        manifest_property_lookup: Dict[str, Dict[str, Any]] = {}
        manifest_class_lookup: Dict[str, Dict[str, Any]] = {}

        manifest_datasets = canonical_schema.get("schema_manifest", {}) or {}
        if manifest_datasets:
            for dataset_name, dataset_manifest in manifest_datasets.items():
                entity_info = dataset_manifest.get("entity_type") or {}
                canonical_class_uri = entity_info.get("canonical_uri") or entity_info.get("uri")
                if not canonical_class_uri:
                    continue

                class_entry = manifest_class_lookup.setdefault(
                    canonical_class_uri,
                    {
                        "uri": canonical_class_uri,
                        "datasets": [],
                        "properties": [],
                        "relationships": [],
                        "label": entity_info.get("name") or canonical_class_uri,
                    },
                )

                if dataset_name not in class_entry["datasets"]:
                    class_entry["datasets"].append(dataset_name)

                for column_name, prop_snapshot in (dataset_manifest.get("properties") or {}).items():
                    canonical_property_uri = prop_snapshot.get("canonical_uri") or prop_snapshot.get("uri")
                    if not canonical_property_uri:
                        continue

                    manifest_property_lookup[canonical_property_uri] = {
                        "uri": prop_snapshot.get("uri"),
                        "canonical_uri": canonical_property_uri,
                        "name": prop_snapshot.get("name") or column_name,
                    }

                    property_entry = next(
                        (p for p in class_entry["properties"] if p["canonical_property"] == canonical_property_uri),
                        None,
                    )
                    if not property_entry:
                        property_entry = {
                            "canonical_property": canonical_property_uri,
                            "bindings": [],
                        }
                        class_entry["properties"].append(property_entry)

                    property_entry["bindings"].append(
                        {
                            "dataset": dataset_name,
                            "column": column_name,
                            "local_property_uri": prop_snapshot.get("uri"),
                            "name": prop_snapshot.get("name"),
                        }
                    )

                for rel in dataset_manifest.get("fk_relationships", []) or []:
                    # Ensure canonical fields exist for downstream consumers
                    rel_copy = dict(rel)
                    if rel_copy.get("source_canonical_property"):
                        rel_copy.setdefault("source_property", rel_copy["source_canonical_property"])
                    if rel_copy.get("target_canonical_property"):
                        rel_copy.setdefault("target_property", rel_copy["target_canonical_property"])
                    rel_copy.setdefault("source_dataset", dataset_name)
                    class_entry["relationships"].append(rel_copy)

                for ctx in dataset_manifest.get("relationship_contexts", []) or []:
                    class_entry.setdefault("relationship_contexts", []).append(ctx)

            if not canonical_classes:
                canonical_classes = list(manifest_class_lookup.values())
            canonical_properties = canonical_properties or list(manifest_property_lookup.values())

            # Ensure schema has sections for all canonical classes we discovered in manifest
            existing_class_uris: Set[str] = {
                section.canonical_class_uri for section in schema.sections.values()
            }
            for class_uri, class_entry in manifest_class_lookup.items():
                if class_uri in existing_class_uris:
                    continue

                raw_label = class_entry.get("label") or class_uri.split('/')[-1]
                section_key = slugify(raw_label or class_uri) or f"section_{len(schema.sections)}"
                if section_key in schema.sections:
                    section_key = f"{section_key}_{len(schema.sections)}"

                schema.sections[section_key] = CardSection(
                    label=raw_label,
                    canonical_class_uri=class_uri,
                    properties={},
                    fk_relationships=[],
                    relationship_contexts=[],
                )
                existing_class_uris.add(class_uri)

        class_lookup = {item.get("uri"): item for item in canonical_classes}
        property_lookup = {prop.get("uri"): prop for prop in canonical_properties}

        if manifest_property_lookup:
            property_lookup.update({uri: data for uri, data in manifest_property_lookup.items() if uri})

        for section in schema.sections.values():
            canonical_class = class_lookup.get(section.canonical_class_uri)
            if not canonical_class:
                logger.debug(
                    "SchemaManifestService._populate_card_schema: canonical class missing: %s",
                    section.canonical_class_uri,
                )
                continue

            datasets = canonical_class.get("datasets", [])
            section.datasets = datasets

            bindings = canonical_class.get("properties", [])
            for binding in bindings:
                canonical_prop_uri = binding.get("canonical_property")
                column_bindings = binding.get("bindings", [])

                if not canonical_prop_uri:
                    continue

                prop_obj = None

                # Prefer existing properties with matching canonical URI (template-defined keys)
                for existing_key, existing_prop in section.properties.items():
                    if existing_prop.canonical_uri == canonical_prop_uri:
                        prop_obj = existing_prop
                        break

                if not prop_obj:
                    prop_lookup_obj = property_lookup.get(canonical_prop_uri)
                    prop_name = prop_lookup_obj.get("name") if prop_lookup_obj else canonical_prop_uri
                    prop_obj = CardProperty(prop_name, canonical_prop_uri)
                    section.properties[prop_name] = prop_obj

                for column_binding in column_bindings:
                    prop_obj.bindings.append(
                        CanonicalPropertyBinding(
                            canonical_uri=canonical_prop_uri,
                            dataset=column_binding.get("dataset"),
                            column=column_binding.get("column"),
                            local_uri=column_binding.get("local_property_uri"),
                            name=column_binding.get("name"),
                        )
                    )

            section.fk_relationships.extend(canonical_class.get("relationships", []))
            section.relationship_contexts.extend(copy.deepcopy(canonical_class.get("relationship_contexts", [])))
