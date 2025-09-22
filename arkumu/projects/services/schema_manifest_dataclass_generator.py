"""Generate dataclasses straight from schema manifests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from django.utils.text import slugify

from arkumu.metadata.models.mappings import Mapping
from arkumu.projects import domain_model


def _camel_case(value: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9]+", value)
    if not tokens:
        return "Dataset"
    cand = "".join(token.capitalize() for token in tokens)
    if cand[0].isdigit():
        cand = f"C{cand}"
    return cand


def _snake_case(value: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9]+", value)
    if not tokens:
        return "field"
    cand = "_".join(token.lower() for token in tokens)
    if cand[0].isdigit():
        cand = f"value_{cand}"
    return cand


def _load_vocabulary_map() -> Dict[str, str]:
    vocab: Dict[str, str] = {}
    for name in dir(domain_model):
        obj = getattr(domain_model, name)
        if getattr(obj, "__dataclass_fields__", None):
            for field in obj.__dataclass_fields__.values():  # type: ignore[attr-defined]
                meta = field.metadata or {}
                canonical = meta.get("predicate_uri")
                vocabulary = meta.get("vocabulary")
                if canonical and vocabulary:
                    vocab[canonical] = vocabulary
    return vocab


@dataclass
class ManifestField:
    name: str
    canonical_uri: str
    dataset_property: str
    metadata: Dict[str, str]


@dataclass
class ManifestClass:
    class_name: str
    dataset_key: str
    canonical_uri: str
    fields: List[ManifestField]


class SchemaManifestDataclassGenerator:
    """Produce python dataclasses from mapping_config.schema_manifest."""

    type_map = {
        "list": "list[str]",
    }

    def __init__(self) -> None:
        self._vocabulary_map = _load_vocabulary_map()

    def load_manifest(self, organization_code: str) -> Dict[str, ManifestClass]:
        mapping = (
            Mapping.objects
            .filter(organization_id=organization_code)
            .order_by('-created_at')
            .first()
        )
        if not mapping:
            return {}
        manifest = mapping.mapping_config.get('schema_manifest', {})
        results: Dict[str, ManifestClass] = {}
        for dataset_key, payload in manifest.items():
            entity = payload.get('entity_type', {})
            canonical_uri = entity.get('canonical_uri') or entity.get('uri') or ''
            class_name = _camel_case(entity.get('name') or dataset_key)
            fields: List[ManifestField] = []
            properties = payload.get('properties', {}) or {}
            for display_name, prop in properties.items():
                canonical_prop = prop.get('canonical_uri') or prop.get('uri') or ''
                field_name = _snake_case(display_name)
                metadata = {
                    'display_name': display_name,
                    'dataset_key': dataset_key,
                    'canonical_uri': canonical_prop,
                }
                local_uri = prop.get('uri')
                if local_uri:
                    metadata['local_uri'] = local_uri
                vocabulary = self._vocabulary_map.get(canonical_prop)
                if vocabulary:
                    metadata['vocabulary'] = vocabulary
                fields.append(
                    ManifestField(
                        name=field_name,
                        canonical_uri=canonical_prop,
                        dataset_property=display_name,
                        metadata=metadata,
                    )
                )
            results[class_name] = ManifestClass(
                class_name=class_name,
                dataset_key=dataset_key,
                canonical_uri=canonical_uri,
                fields=fields,
            )
        return results

    def build_module(self, manifest: Dict[str, ManifestClass]) -> str:
        header = "\n".join(
            [
                '"""Auto-generated from schema manifest."""',
                "from __future__ import annotations",
                "",
                "from dataclasses import dataclass, field",
                "",
            ]
        )
        body = "\n\n".join(self._render_class(cls) for cls in manifest.values())
        return f"{header}\n\n{body}\n"

    def _render_class(self, manifest_class: ManifestClass) -> str:
        lines = [
            "@dataclass",
            f"class {manifest_class.class_name}:",
            f"    \"\"\"Dataset {manifest_class.dataset_key} (canonical {manifest_class.canonical_uri})\"\"\"",
        ]
        if not manifest_class.fields:
            lines.append("    pass")
            return "\n".join(lines)
        for field_def in manifest_class.fields:
            metadata_items = [f"'dataset_property': '{field_def.dataset_property}'", f"'canonical_uri': '{field_def.canonical_uri}'"]
            metadata_items.extend(f"'{k}': '{v}'" for k, v in field_def.metadata.items() if k not in {'display_name', 'dataset_key', 'canonical_uri'})
            metadata_string = ', '.join(metadata_items)
            lines.append(
                f"    {field_def.name}: list[str] = field(default_factory=list, metadata={{ {metadata_string} }})"
            )
        return "\n".join(lines)

