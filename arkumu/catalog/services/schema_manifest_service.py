"""Utilities to consume schema manifests and expose canonical mappings."""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from django.core.cache import cache

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
                )
                for name, section in CARD_SCHEMA_TEMPLATE.sections.items()
            },
        )

        self._populate_card_schema(schema, canonical_schema)

        cache.set(cache_key, schema, self.CACHE_TIMEOUT)

        return copy.deepcopy(schema)

    def _get_canonical_schema(self, organization_code: str) -> Dict[str, Any]:
        canonical_schema = Mapping.objects.filter(organization_id=organization_code).first()
        if not canonical_schema:
            logger.warning(
                "SchemaManifestService.get_canonical_schema: No canonical schema found for org '%s'",
                organization_code,
            )
            return {}

        try:
            return canonical_schema.load_mapping()
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

        class_lookup = {item.get("uri"): item for item in canonical_classes}
        property_lookup = {prop.get("uri"): prop for prop in canonical_properties}

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

                prop_obj = section.properties.get(canonical_prop_uri)
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
