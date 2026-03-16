"""Resolve institution mapping sets for unified mask entities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from arkumu.catalog.services.project_views import CardURIs
from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.services.mask_schema import (
    COLLECTION_TYPE_URI,
    INFORMATION_CARRIER_TYPE_URI,
    KEYWORD_TYPE_URI,
    PLACE_TYPE_URI,
)


ENTITY_TYPE_TO_CANONICAL_CLASS: Dict[str, str] = {
    "project": CardURIs.PROJECT_TYPE,
    "event": CardURIs.EVENT_TYPE,
    "actor": CardURIs.ACTOR_TYPE,
    "place": PLACE_TYPE_URI,
    "collection": COLLECTION_TYPE_URI,
    "information_carrier": INFORMATION_CARRIER_TYPE_URI,
    "keyword": KEYWORD_TYPE_URI,
    "digital_object": CardURIs.DIGITAL_OBJECT_TYPE,
}


@dataclass(frozen=True)
class MappingDatasetBinding:
    mapping_id: str
    mapping_name: str
    dataset_name: str
    canonical_type_uri: str


class MappingSetResolver:
    """Resolve datasets across all mappings for an institution and entity."""

    def list_datasets_for_entity(
        self,
        *,
        organization_code: Optional[str],
        entity_type: str,
    ) -> List[MappingDatasetBinding]:
        org_code = (organization_code or "").strip().lower()
        canonical_type_uri = ENTITY_TYPE_TO_CANONICAL_CLASS.get((entity_type or "").strip().lower())
        if not org_code or not canonical_type_uri:
            return []

        datasets: List[MappingDatasetBinding] = []
        seen = set()
        mappings = Mapping.objects.filter(organization_id=org_code).order_by("-created_at")
        for mapping in mappings:
            manifest = self._extract_manifest(mapping.mapping_config or {})
            if not manifest:
                continue
            for dataset_name, dataset_data in manifest.items():
                entity_info = (dataset_data or {}).get("entity_type") or {}
                if entity_info.get("canonical_uri") != canonical_type_uri:
                    continue
                dedupe_key = (str(mapping.id), dataset_name)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                datasets.append(
                    MappingDatasetBinding(
                        mapping_id=str(mapping.id),
                        mapping_name=mapping.name,
                        dataset_name=dataset_name,
                        canonical_type_uri=canonical_type_uri,
                    )
                )
        return datasets

    def _extract_manifest(self, mapping_config: Dict[str, object]) -> Dict[str, object]:
        promoted = mapping_config.get("promoted_manifest") or {}
        if isinstance(promoted, dict):
            promoted_manifest = promoted.get("schema_manifest")
            if isinstance(promoted_manifest, dict) and promoted_manifest:
                return promoted_manifest
        schema_manifest = mapping_config.get("schema_manifest")
        if isinstance(schema_manifest, dict):
            return schema_manifest
        return {}
