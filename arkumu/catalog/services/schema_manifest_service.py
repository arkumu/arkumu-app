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
            },
        ),
    },
)


class SchemaManifestService:
    """Loads schema manifests and exposes canonical mappings for consumers."""

    CACHE_TIMEOUT = 600  # seconds

    def get_card_schema(self, organization_code: str) -> CardSchema:
        """Return a card-specific view of the schema manifest for an organization."""
        logger.info(
            "SchemaManifestService.get_card_schema: Starting for org '%s'",
            organization_code,
        )

        canonical_schema = self._get_canonical_schema(organization_code)

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
                            bindings=[]  # Fresh empty bindings list
                        )
                        for prop_name, prop in section.properties.items()
                    },
                    fk_relationships=[]  # Will be set from canonical_schema
                )
                for name, section in CARD_SCHEMA_TEMPLATE.sections.items()
            }
        )

        if canonical_schema is None:
            logger.warning(
                "SchemaManifestService.get_card_schema: No canonical schema found for org '%s'",
                organization_code,
            )
            return schema

        logger.info(
            "SchemaManifestService.get_card_schema: Found canonical schema with %d classes for org '%s'",
            len(canonical_schema),
            organization_code,
        )

        # Log available canonical classes
        logger.debug(
            "SchemaManifestService.get_card_schema: Found %d canonical classes",
            len(canonical_schema.keys()),
        )

        for section in schema.sections.values():
            class_binding = canonical_schema.get(section.canonical_class_uri)

            if class_binding:
                logger.info(
                    "SchemaManifestService.get_card_schema: Found binding for section '%s' (class: %s) with %d properties, %d FK relationships",
                    section.label,
                    section.canonical_class_uri,
                    len(class_binding.properties),
                    len(class_binding.fk_relationships),
                )

                # Log FK relationships for debugging
                if class_binding.fk_relationships:
                    logger.info(f"  FK relationships for {section.label}:")
                    for fk in class_binding.fk_relationships[:3]:  # Show first 3
                        logger.info(f"    - {fk.get('source_property')} -> {fk.get('target_dataset')}.{fk.get('target_property')}")

                # Share FK relationships reference (read-only metadata)
                section.fk_relationships = class_binding.fk_relationships
            else:
                logger.warning(
                    "SchemaManifestService.get_card_schema: No binding found for section '%s' (class: %s)",
                    section.label,
                    section.canonical_class_uri,
                )

            for prop in section.properties.values():
                if class_binding:
                    bindings = class_binding.properties.get(prop.canonical_uri, [])
                    if bindings:
                        logger.debug(
                            "SchemaManifestService.get_card_schema: Property '%s' (%s) has %d bindings",
                            prop.name,
                            prop.canonical_uri,
                            len(bindings),
                        )
                        for binding in bindings:
                            logger.debug(
                                "  - Dataset: %s, Column: %s",
                                binding.dataset,
                                binding.column,
                            )
                    else:
                        logger.debug(
                            "SchemaManifestService.get_card_schema: Property '%s' (%s) has NO bindings",
                            prop.name,
                            prop.canonical_uri,
                        )
                else:
                    bindings = []

                # Set bindings directly (they're immutable dataclass instances)
                prop.bindings = bindings

        # Log summary of available sections
        available_sections = [s.label for s in schema.sections.values() if s.available]
        logger.info(
            "SchemaManifestService.get_card_schema: Returning schema with %d available sections: %s",
            len(available_sections),
            available_sections,
        )

        return schema

    def get_relationship_hints(self, organization_code: str) -> Dict[str, List[Dict[str, Any]]]:
        """Return FK relationship metadata keyed by card section."""

        schema = self.get_card_schema(organization_code)
        hints: Dict[str, List[Dict[str, Any]]] = {}

        for section_name, section in schema.sections.items():
            if not section.fk_relationships:
                continue
            hints[section_name] = [
                {
                    'source_property': fk.get('source_property'),
                    'target_property': fk.get('target_property'),
                    'target_dataset': fk.get('target_dataset'),
                    'target_column': fk.get('target_column'),
                    'is_multi_value': fk.get('is_multi_value', False),
                }
                for fk in section.fk_relationships
                if fk.get('source_property') or fk.get('target_property')
            ]

        return hints

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_canonical_schema(self, organization_code: str) -> Optional[Dict[str, CanonicalClassBinding]]:
        """Load and canonicalise the schema manifest for an organization."""
        if not organization_code:
            logger.warning("SchemaManifestService._get_canonical_schema: No organization code provided")
            return None

        cache_key = f"canonical_schema_manifest:{organization_code}"
        cached = cache.get(cache_key)
        if cached is not None:
            logger.info(
                "SchemaManifestService._get_canonical_schema: Cache HIT for org '%s' - returning %d classes",
                organization_code,
                len(cached) if cached else 0,
            )
            return cached

        logger.info(
            "SchemaManifestService._get_canonical_schema: Cache MISS for org '%s' - loading from database",
            organization_code,
        )

        mapping = (
            Mapping.objects.filter(
                organization_id=organization_code,
                mapping_config__schema_manifest__isnull=False,
            )
            .order_by('-updated_at')
            .first()
        )

        if not mapping:
            logger.info(
                "SchemaManifestService: No mapping with schema_manifest found for org '%s'",
                organization_code,
            )
            cache.set(cache_key, None, self.CACHE_TIMEOUT)
            return None

        manifest = mapping.mapping_config.get('schema_manifest')
        if not manifest:
            logger.info(
                "SchemaManifestService: Mapping %s for org '%s' has empty schema_manifest",
                mapping.id,
                organization_code,
            )
            cache.set(cache_key, None, self.CACHE_TIMEOUT)
            return None

        logger.info(
            "SchemaManifestService._get_canonical_schema: Found manifest for org '%s' in mapping %s with %d datasets",
            organization_code,
            mapping.id,
            len(manifest),
        )

        canonical_schema = self._build_canonical_schema(manifest)

        logger.info(
            "SchemaManifestService._get_canonical_schema: Caching canonical schema for org '%s' (timeout: %ds)",
            organization_code,
            self.CACHE_TIMEOUT,
        )

        cache.set(cache_key, canonical_schema, self.CACHE_TIMEOUT)
        return canonical_schema

    def _build_canonical_schema(self, manifest: Dict[str, Any]) -> Dict[str, CanonicalClassBinding]:
        """Canonicalise manifest by grouping by canonical URIs."""
        logger.info(
            "SchemaManifestService._build_canonical_schema: Processing manifest with %d datasets",
            len(manifest),
        )

        class_accumulator: Dict[str, Dict[str, Any]] = {}
        dataset_property_bindings: Dict[str, Dict[str, CanonicalPropertyBinding]] = {}

        for dataset_name, dataset_manifest in manifest.items():
            entity_type = dataset_manifest.get('entity_type') or {}
            canonical_class_uri = entity_type.get('canonical_uri') or entity_type.get('uri')
            if not canonical_class_uri:
                logger.debug(
                    "SchemaManifestService: Dataset '%s' missing canonical entity type URI",
                    dataset_name,
                )
                continue

            logger.debug(
                "SchemaManifestService._build_canonical_schema: Dataset '%s' maps to class '%s'",
                dataset_name,
                canonical_class_uri,
            )

            class_entry = class_accumulator.setdefault(
                canonical_class_uri,
                {
                    'datasets': set(),
                    'properties': {},
                    'fk_relationships': [],
                },
            )
            class_entry['datasets'].add(dataset_name)

            properties = dataset_manifest.get('properties') or {}
            dataset_property_bindings[dataset_name] = {}

            logger.debug(
                "SchemaManifestService._build_canonical_schema: Dataset '%s' has %d properties",
                dataset_name,
                len(properties),
            )

            for column_name, property_snapshot in properties.items():
                canonical_prop_uri = property_snapshot.get('canonical_uri') or property_snapshot.get('uri')
                if not canonical_prop_uri:
                    logger.debug(
                        "SchemaManifestService._build_canonical_schema: Column '%s' in dataset '%s' has no canonical URI",
                        column_name,
                        dataset_name,
                    )
                    continue

                binding = CanonicalPropertyBinding(
                    canonical_uri=canonical_prop_uri,
                    dataset=dataset_name,
                    column=column_name,
                    local_uri=property_snapshot.get('uri'),
                    name=property_snapshot.get('name'),
                )
                class_entry['properties'].setdefault(canonical_prop_uri, []).append(binding)
                dataset_property_bindings[dataset_name][column_name] = binding

                logger.debug(
                    "SchemaManifestService._build_canonical_schema: Added binding - Dataset: %s, Column: %s -> Property: %s",
                    dataset_name,
                    column_name,
                    canonical_prop_uri,
                )

        # Second pass for FK relationships now that dataset properties are known
        for dataset_name, dataset_manifest in manifest.items():
            entity_type = dataset_manifest.get('entity_type') or {}
            canonical_class_uri = entity_type.get('canonical_uri') or entity_type.get('uri')
            class_entry = class_accumulator.get(canonical_class_uri)
            if not class_entry:
                continue

            for fk_rel in dataset_manifest.get('fk_relationships', []):
                source_column = fk_rel.get('source_column')
                source_binding = dataset_property_bindings.get(dataset_name, {}).get(source_column)
                target_dataset = fk_rel.get('target_dataset')
                target_column = fk_rel.get('target_column')
                target_binding = dataset_property_bindings.get(target_dataset, {}).get(target_column)

                canonical_source_property = (
                    (source_binding.canonical_uri if source_binding else None)
                    or fk_rel.get('source_property')
                    or fk_rel.get('relationship_type')
                )

                canonical_target_property = target_binding.canonical_uri if target_binding else None

                class_entry['fk_relationships'].append(
                    {
                        'source_dataset': dataset_name,
                        'source_column': source_column,
                        'source_property': canonical_source_property,
                        'target_dataset': target_dataset,
                        'target_column': target_column,
                        'target_property': canonical_target_property,
                        'is_multi_value': fk_rel.get('is_multi_value', False),
                    }
                )

        canonical_bindings: Dict[str, CanonicalClassBinding] = {}
        for class_uri, entry in class_accumulator.items():
            canonical_bindings[class_uri] = CanonicalClassBinding(
                canonical_uri=class_uri,
                datasets=sorted(entry['datasets']),
                properties=entry['properties'],
                fk_relationships=entry['fk_relationships'],
            )

        logger.info(
            "SchemaManifestService._build_canonical_schema: Built canonical schema with %d classes",
            len(canonical_bindings),
        )

        for class_uri, binding in canonical_bindings.items():
            logger.debug(
                "SchemaManifestService._build_canonical_schema: Class '%s' has %d datasets, %d properties, %d FK relationships",
                class_uri,
                len(binding.datasets),
                len(binding.properties),
                len(binding.fk_relationships),
            )

        return canonical_bindings
