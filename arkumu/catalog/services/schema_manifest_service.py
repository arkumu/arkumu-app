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
        canonical_schema = self._get_canonical_schema(organization_code)
        schema = copy.deepcopy(CARD_SCHEMA_TEMPLATE)

        if canonical_schema is None:
            return schema

        for section in schema.sections.values():
            class_binding = canonical_schema.get(section.canonical_class_uri)
            for prop in section.properties.values():
                if class_binding:
                    bindings = class_binding.properties.get(prop.canonical_uri, [])
                else:
                    bindings = []
                # Replace bindings with copies to avoid accidental mutation of cached objects
                prop.bindings = [
                    CanonicalPropertyBinding(
                        canonical_uri=binding.canonical_uri,
                        dataset=binding.dataset,
                        column=binding.column,
                        local_uri=binding.local_uri,
                        name=binding.name,
                    )
                    for binding in bindings
                ]

        return schema

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_canonical_schema(self, organization_code: str) -> Optional[Dict[str, CanonicalClassBinding]]:
        """Load and canonicalise the schema manifest for an organization."""
        if not organization_code:
            return None

        cache_key = f"canonical_schema_manifest:{organization_code}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

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

        canonical_schema = self._build_canonical_schema(manifest)
        cache.set(cache_key, canonical_schema, self.CACHE_TIMEOUT)
        return canonical_schema

    def _build_canonical_schema(self, manifest: Dict[str, Any]) -> Dict[str, CanonicalClassBinding]:
        """Canonicalise manifest by grouping by canonical URIs."""
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
            for column_name, property_snapshot in properties.items():
                canonical_prop_uri = property_snapshot.get('canonical_uri') or property_snapshot.get('uri')
                if not canonical_prop_uri:
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

        return canonical_bindings
