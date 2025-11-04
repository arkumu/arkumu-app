"""Translation utilities between organization-specific and canonical schema dataclasses."""
from __future__ import annotations

import importlib
import re
from dataclasses import dataclass, fields, is_dataclass
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Tuple, Type

from arkumu.projects import schema_manifest_canonical as canonical

# ---------------------------------------------------------------------------
# Shared regex helpers (mirrors the generator that created the manifests)
# ---------------------------------------------------------------------------

DATASET_DOC_RE = re.compile(
    r"Dataset\s+(?P<dataset>.+?)\s+\(canonical\s+(?P<canonical>[^)]+)\)"
)


# ---------------------------------------------------------------------------
# Dataset registry construction
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DatasetDescriptor:
    """Metadata describing an organization-specific dataset dataclass."""

    organization: str
    dataset_name: str
    canonical_class_uri: str
    dataclass_type: Type[Any]

    @property
    def key(self) -> Tuple[str, str]:
        return self.organization, self.dataset_name


def _load_dataset_registry() -> Dict[Tuple[str, str], DatasetDescriptor]:
    registry: Dict[Tuple[str, str], DatasetDescriptor] = {}

    manifest_modules: Mapping[str, str] = getattr(canonical, "ORG_MANIFEST_MODULES", {})
    if not manifest_modules:
        raise RuntimeError("schema_manifest_canonical must expose ORG_MANIFEST_MODULES")

    for org_code, module_path in manifest_modules.items():
        module = importlib.import_module(module_path)

        for attr_name in dir(module):
            cls = getattr(module, attr_name)
            if not is_dataclass(cls):
                continue

            doc = getattr(cls, "__doc__", "") or ""
            match = DATASET_DOC_RE.search(doc)
            if not match:
                continue

            dataset_name = match.group("dataset")
            canonical_uri = match.group("canonical")

            descriptor = DatasetDescriptor(
                organization=org_code,
                dataset_name=dataset_name,
                canonical_class_uri=canonical_uri,
                dataclass_type=cls,
            )
            registry[descriptor.key] = descriptor

    return registry


_DATASET_REGISTRY = _load_dataset_registry()


def get_dataset_descriptor(org_code: str, dataset_name: str) -> DatasetDescriptor:
    try:
        return _DATASET_REGISTRY[(org_code, dataset_name)]
    except KeyError as exc:
        raise KeyError(f"No dataset descriptor for org='{org_code}', dataset='{dataset_name}'") from exc


# ---------------------------------------------------------------------------
# Translation helpers
# ---------------------------------------------------------------------------


def _resolve_dataset_name(org_code: str, canonical_obj: canonical.CanonicalEntityBase, dataset_name: Optional[str]) -> str:
    available = canonical_obj.datasets_by_org.get(org_code)
    if not available:
        raise ValueError(
            f"Canonical entity '{canonical_obj.canonical_uri}' has no datasets for organization '{org_code}'"
        )
    if dataset_name:
        if dataset_name not in available:
            raise ValueError(
                f"Dataset '{dataset_name}' not registered for org '{org_code}' and canonical class '{canonical_obj.canonical_uri}'"
            )
        return dataset_name
    return available[0]


def _extract_dataset_name(instance: Any) -> Tuple[str, str]:
    """Return `(canonical_uri, dataset_name)` for an org-specific dataclass instance."""

    doc = getattr(instance.__class__, "__doc__", "") or ""
    match = DATASET_DOC_RE.search(doc)
    if not match:
        raise ValueError(
            f"Cannot determine dataset metadata from dataclass '{instance.__class__.__name__}'"
        )
    canonical_uri = match.group("canonical")
    dataset_name = match.group("dataset")
    return canonical_uri, dataset_name


def org_to_canonical(org_code: str, dataset_obj: Any) -> canonical.CanonicalEntityBase:
    """Convert an organization-specific dataset dataclass into a canonical entity."""

    if not is_dataclass(dataset_obj):
        raise TypeError("dataset_obj must be a dataclass instance")

    canonical_uri, dataset_name = _extract_dataset_name(dataset_obj)
    canonical_cls = canonical.get_canonical_class(canonical_uri)
    canonical_instance = canonical_cls()

    mapped_fields: set[str] = set()

    for canonical_field in fields(canonical_instance):
        if canonical_field.name == "extra_properties":
            continue
        bindings: Iterable[canonical.SourceBinding] = canonical_field.metadata.get("source_bindings", [])
        target_list: List[str] = getattr(canonical_instance, canonical_field.name)

        for binding in bindings:
            if binding.organization != org_code or binding.dataset != dataset_name:
                continue
            value = getattr(dataset_obj, binding.field_name, [])
            if not value:
                continue
            if isinstance(value, list):
                target_list.extend(value)
            else:
                target_list.append(value)
            mapped_fields.add(binding.field_name)

    # Capture unmapped non-empty values in the `extra_properties` bucket.
    extras: MutableMapping[str, List[str]] = canonical_instance.extra_properties
    for dataset_field in fields(dataset_obj):
        if dataset_field.name in mapped_fields:
            continue
        value = getattr(dataset_obj, dataset_field.name)
        if not value:
            continue
        if isinstance(value, list):
            extras[dataset_field.name] = list(value)
        else:
            extras[dataset_field.name] = [value]

    return canonical_instance


def canonical_to_org(
    org_code: str,
    canonical_obj: canonical.CanonicalEntityBase,
    dataset_name: Optional[str] = None,
) -> Any:
    """Convert a canonical entity into an organization-specific dataset dataclass."""

    resolved_dataset_name = _resolve_dataset_name(org_code, canonical_obj, dataset_name)
    descriptor = get_dataset_descriptor(org_code, resolved_dataset_name)

    dataset_instance = descriptor.dataclass_type()

    # Populate fields from canonical values.
    canonical_fields = {f.name: f for f in fields(canonical_obj)}

    for dataset_field in fields(dataset_instance):
        populated: List[str] = []

        for canonical_field in canonical_fields.values():
            bindings: Iterable[canonical.SourceBinding] = canonical_field.metadata.get("source_bindings", [])
            source_values: List[str] = getattr(canonical_obj, canonical_field.name, [])
            if not source_values:
                continue
            for binding in bindings:
                if (
                    binding.organization == org_code
                    and binding.dataset == resolved_dataset_name
                    and binding.field_name == dataset_field.name
                ):
                    populated.extend(source_values)
                    break

        if populated:
            setattr(dataset_instance, dataset_field.name, list(populated))
        else:
            # Fall back to extras (if present) or leave default.
            extra_values = canonical_obj.extra_properties.get(dataset_field.name)
            if extra_values:
                setattr(dataset_instance, dataset_field.name, list(extra_values))

    return dataset_instance


__all__ = [
    "DatasetDescriptor",
    "get_dataset_descriptor",
    "org_to_canonical",
    "canonical_to_org",
]
