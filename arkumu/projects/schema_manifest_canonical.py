"""Canonical schema dataclasses synthesized across partner-specific manifests.

This module inspects the organization-specific schema manifest dataclasses and
constructs a unified set of canonical dataclasses that expose every canonical
property observed across the participating institutions.  The generated
classes provide:

- a common field layout with consistent canonical URIs per attribute
- metadata describing which organization datasets/columns implement each field
- an `extra_properties` bucket for future extensions or rarely used values
- flags indicating which properties should surface in editor-facing forms

The goal is to let new metadata entry flows operate on a single canonical
schema while adapter layers translate to/from the organization-specific
structures.
"""

from __future__ import annotations

import importlib
import keyword
import re
from dataclasses import dataclass, field, fields, make_dataclass
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional

# ---------------------------------------------------------------------------
# Source manifest modules (per organization)
# ---------------------------------------------------------------------------
ORG_MANIFEST_MODULES: Mapping[str, str] = {
    "fuk": "arkumu.projects.schema_manifest_model_fuk",
    "det": "arkumu.projects.schema_manifest_model_det",
    "rsh": "arkumu.projects.schema_manifest_model_rsh",
    # hmt and khm currently provide only organization-specific canonical URIs;
    # they are still considered when building source binding metadata where
    # possible, but they do not contribute to the generic "http://arkumu.org/data/types/" namespace.
}

# Regex used to extract dataset name and canonical class URI from dataclass
# docstrings produced by the manifest generator.
DATASET_DOC_RE = re.compile(
    r"Dataset\s+(?P<dataset>.+?)\s+\(canonical\s+(?P<canonical>[^)]+)\)"
)

GENERAL_CANONICAL_PREFIX = "http://arkumu.org/data/types/"

# ---------------------------------------------------------------------------
# Source binding representation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceBinding:
    """Describes how a canonical property is realised in an org-specific dataset."""

    organization: str
    dataset: str
    dataset_property: Optional[str]
    field_name: str
    local_uri: Optional[str]

    def as_dict(self) -> Dict[str, Optional[str]]:
        return {
            "organization": self.organization,
            "dataset": self.dataset,
            "dataset_property": self.dataset_property,
            "field_name": self.field_name,
            "local_uri": self.local_uri,
        }


# ---------------------------------------------------------------------------
# Canonical entity base class with helpful utilities
# ---------------------------------------------------------------------------


class CanonicalEntityBase:
    """Common helpers shared by generated canonical dataclasses."""

    # Populated dynamically on subclasses after `make_dataclass` creation.
    canonical_uri: str = ""
    property_bindings: Mapping[str, List[SourceBinding]] = {}
    datasets_by_org: Mapping[str, List[str]] = {}

    def as_dict(self) -> Dict[str, Any]:
        """Return a serialisable view of populated fields (excluding empties)."""
        output: Dict[str, Any] = {}
        for f in fields(self):  # type: ignore[arg-type]
            value = getattr(self, f.name)
            if not value:
                continue
            output[f.name] = value
        return output


# ---------------------------------------------------------------------------
# Helpers to build canonical field definitions
# ---------------------------------------------------------------------------


def _normalise_field_name(uri: str, existing: Iterable[str]) -> str:
    """Convert a canonical property URI to a safe Python attribute name."""

    token = uri.rstrip("/").split("/")[-1]
    token = token.replace("-", "_")
    token = re.sub(r"[^0-9a-zA-Z_]", "_", token)
    token = re.sub(r"__+", "_", token)
    token = token.lower()
    if token and token[0].isdigit():
        token = f"p_{token}"
    if keyword.iskeyword(token):
        token += "_"

    candidate = token or "unnamed"
    suffix = 1
    existing_set = set(existing)
    while candidate in existing_set:
        suffix += 1
        candidate = f"{token}_{suffix}"
    return candidate


def _collect_canonical_class_map() -> Dict[str, Dict[str, Any]]:
    """Aggregate property bindings across all organization manifests."""

    class_map: Dict[str, Dict[str, Any]] = {}

    for org_code, module_path in ORG_MANIFEST_MODULES.items():
        module = importlib.import_module(module_path)

        for attr_name in dir(module):
            cls = getattr(module, attr_name)
            dataclass_fields = getattr(cls, "__dataclass_fields__", None)
            if not dataclass_fields:
                continue

            doc = getattr(cls, "__doc__", "") or ""
            match = DATASET_DOC_RE.search(doc)
            if not match:
                continue

            dataset_name = match.group("dataset")
            canonical_class_uri = match.group("canonical")

            if not canonical_class_uri.startswith(GENERAL_CANONICAL_PREFIX):
                # Skip organization-specific canonical URIs; those will be
                # handled by org adapters but are not part of the shared schema.
                continue

            info = class_map.setdefault(
                canonical_class_uri,
                {
                    "per_org_datasets": {},
                    "properties": {},
                },
            )

            per_org = info["per_org_datasets"].setdefault(org_code, set())
            per_org.add(dataset_name)

            for field_obj in dataclass_fields.values():
                metadata = field_obj.metadata or {}
                canonical_prop_uri = metadata.get("canonical_uri")
                if not canonical_prop_uri:
                    continue
                bindings = info["properties"].setdefault(canonical_prop_uri, [])
                bindings.append(
                    SourceBinding(
                        organization=org_code,
                        dataset=dataset_name,
                        dataset_property=metadata.get("dataset_property"),
                        field_name=field_obj.name,
                        local_uri=metadata.get("local_uri"),
                    )
                )

    return class_map


# Canonical classes whose dataclasses we expose directly.
CORE_CANONICAL_CLASSES: Mapping[str, str] = {
    "project": "http://arkumu.org/data/types/projekt",
    "event": "http://arkumu.org/data/types/ereignis",
    "actor": "http://arkumu.org/data/types/akteurin",
    "actor_event": "http://arkumu.org/data/types/akteurin-ereignis-kreuztabelle",
    "digital_object": "http://arkumu.org/data/types/digitales-objekt",
    "institution": "http://arkumu.org/data/types/einliefernde-hochschule",
    "project_category": "http://arkumu.org/data/types/projektkategorie",
    "role": "http://arkumu.org/data/types/rolle",
}

# Properties that should be highlighted in editor-facing forms.  These are
# derived from the card schema template used in the catalog UI.
FORM_VISIBLE_URIS: set[str] = set()
try:
    from arkumu.catalog.services.schema_manifest_service import CARD_SCHEMA_TEMPLATE

    for section in CARD_SCHEMA_TEMPLATE.sections.values():
        for prop in section.properties.values():
            FORM_VISIBLE_URIS.add(prop.canonical_uri)
except Exception:  # pragma: no cover - defensive import guarding
    # If the catalog service cannot be imported (e.g., during isolated tests),
    # fall back to an empty set. Form generation can still opt-in manually.
    FORM_VISIBLE_URIS = {
        "http://arkumu.org/data/properties/bevorzugter-titel",
        "http://arkumu.org/data/properties/bevorzugter-untertitel",
        "http://arkumu.org/data/properties/ereignisbeginn",
        "http://arkumu.org/data/properties/ereignisende",
        "http://arkumu.org/data/properties/ereignisort",
        "http://arkumu.org/data/properties/deutscher-name",
        "http://arkumu.org/data/properties/deutscher-name-der-rolle-breadcrumb",
        "http://arkumu.org/data/properties/projektkategorie",
        "http://arkumu.org/data/properties/einliefernde-hochschule",
        "http://arkumu.org/data/properties/dateipfad",
    }

# ---------------------------------------------------------------------------
# Build canonical dataclasses at import time
# ---------------------------------------------------------------------------

_CANONICAL_CLASS_MAP = _collect_canonical_class_map()
CANONICAL_PROPERTY_REGISTRY: Dict[str, Dict[str, List[SourceBinding]]] = {
    class_uri: class_info["properties"]
    for class_uri, class_info in _CANONICAL_CLASS_MAP.items()
}
CANONICAL_DATASETS_BY_ORG: Dict[str, Dict[str, List[str]]] = {
    class_uri: {
        org: sorted(list(datasets))
        for org, datasets in class_info["per_org_datasets"].items()
    }
    for class_uri, class_info in _CANONICAL_CLASS_MAP.items()
}

CANONICAL_CLASS_REGISTRY: Dict[str, type] = {}

__all__: List[str] = ["CanonicalEntityBase", "SourceBinding", "CANONICAL_CLASS_REGISTRY", "CANONICAL_PROPERTY_REGISTRY", "CANONICAL_DATASETS_BY_ORG", "get_canonical_class"]


def _build_dataclass_for_canonical_uri(alias: str, canonical_uri: str) -> Optional[type]:
    class_info = _CANONICAL_CLASS_MAP.get(canonical_uri)
    if not class_info:
        return None

    properties = class_info["properties"]
    field_names: List[str] = []
    dataclass_fields: List[tuple[str, Any, Any]] = []

    for prop_uri, bindings in sorted(properties.items()):
        field_name = _normalise_field_name(prop_uri, field_names)
        field_names.append(field_name)

        metadata = {
            "canonical_uri": prop_uri,
            "source_bindings": tuple(bindings),
            "expose_in_forms": prop_uri in FORM_VISIBLE_URIS,
        }

        dataclass_fields.append(
            (
                field_name,
                list[str],
                field(default_factory=list, metadata=metadata),
            )
        )

    # Always provide an "extra" container for forward compatibility.
    dataclass_fields.append(
        (
            "extra_properties",
            dict[str, list[str]],
            field(
                default_factory=dict,
                metadata={
                    "canonical_uri": None,
                    "source_bindings": tuple(),
                    "expose_in_forms": False,
                },
            ),
        )
    )

    class_name = f"Canonical{alias.title()}"
    canonical_cls = make_dataclass(
        class_name,
        dataclass_fields,
        bases=(CanonicalEntityBase,),
        frozen=False,
        slots=False,
        repr=True,
    )

    canonical_cls.canonical_uri = canonical_uri  # type: ignore[attr-defined]
    canonical_cls.property_bindings = properties  # type: ignore[attr-defined]
    canonical_cls.datasets_by_org = CANONICAL_DATASETS_BY_ORG.get(canonical_uri, {})  # type: ignore[attr-defined]

    CANONICAL_CLASS_REGISTRY[canonical_uri] = canonical_cls
    CANONICAL_CLASS_REGISTRY[class_name] = canonical_cls

    globals()[class_name] = canonical_cls
    __all__.append(class_name)

    return canonical_cls


for alias, canonical_uri in CORE_CANONICAL_CLASSES.items():
    _build_dataclass_for_canonical_uri(alias, canonical_uri)


def get_canonical_class(identifier: str) -> type:
    """Retrieve a canonical dataclass by alias or canonical URI."""

    if identifier in CANONICAL_CLASS_REGISTRY:
        return CANONICAL_CLASS_REGISTRY[identifier]

    # Allow lookup by alias even if not title-cased.
    lowered = identifier.lower()
    for alias, uri in CORE_CANONICAL_CLASSES.items():
        if lowered in {alias, uri}:
            return CANONICAL_CLASS_REGISTRY[uri]

    raise KeyError(f"Unknown canonical class identifier: {identifier}")


__all__.append("CORE_CANONICAL_CLASSES")
__all__.append("FORM_VISIBLE_URIS")
