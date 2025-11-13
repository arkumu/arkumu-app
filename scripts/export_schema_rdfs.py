#!/usr/bin/env python3
"""
Export canonical and institutional Arkumu schemas as RDF Schema (RDFS).

The script inspects the generated schema manifest dataclasses and emits two
vocabulary files:

* canonical-schema.ttl – shared `http://arkumu.org/data/types/…` +
  `…/properties/…` vocabulary with dataset provenance notes.
* institutional-schema.ttl – institution specific class/property URIs for
  FUK/DET/RSH/HMT/KHM, each linked back to the canonical vocabulary via
  `owl:equivalentClass` / `owl:equivalentProperty`.

Usage (run from the repository root):

    uv run python scripts/export_schema_rdfs.py

Use `--output-dir` to change the destination (defaults to `schemas`) and
`--format` to pick a serialization supported by rdflib (default: turtle/ttl).
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import os
import re
import shutil
from dataclasses import is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS, SKOS, XSD

from arkumu.oaipmh.schema_config import (
    SCHEMA_VARIANTS,
    SCHEMA_FORMATS,
    DEFAULT_SCHEMA_FORMATS,
    SCHEMA_RELATIVE_DIR,
)

from arkumu.common.uri_utils import slugify_uri_part
from arkumu.projects.schema_manifest_canonical import (
    CANONICAL_CLASS_REGISTRY,
    CANONICAL_DATASETS_BY_ORG,
    CANONICAL_PROPERTY_REGISTRY,
    SourceBinding,
)

DATASET_DOC_RE = re.compile(
    r"Dataset\s+(?P<dataset>.+?)\s+\(canonical\s+(?P<canonical>[^)]+)\)"
)

# Base directory for published schema snapshots.
BASE_SCHEMA_DIR = Path(SCHEMA_RELATIVE_DIR)

# Ordered list of manifest modules to inspect for institutional schemas.
INSTITUTIONAL_MANIFEST_MODULES: Sequence[str] = [
    "arkumu.projects.schema_manifest_model",
    "arkumu.projects.schema_manifest_model_fuk",
    "arkumu.projects.schema_manifest_model_det",
    "arkumu.projects.schema_manifest_model_hmt",
    "arkumu.projects.schema_manifest_model_rsh",
    "arkumu.projects.schema_manifest_model_khm",
]


def _human_label_from_uri(uri: str) -> str:
    """Turn the URI tail into a readable label."""

    tail = uri.rstrip("/").split("/")[-1]
    if not tail:
        return uri
    tokens = tail.replace("_", "-").split("-")
    cleaned = " ".join(token for token in tokens if token)
    return cleaned.strip().title() or tail


def _add_literal(graph: Graph, subject: URIRef, predicate: URIRef, text: str, *, lang: str | None = "en") -> None:
    if not text:
        return
    graph.add((subject, predicate, Literal(text, lang=lang)))


def build_canonical_graph() -> Graph:
    graph = Graph()
    graph.bind("rdfs", RDFS)
    graph.bind("rdf", RDF)
    graph.bind("owl", OWL)
    graph.bind("skos", SKOS)
    graph.bind("dcterms", DCTERMS)
    graph.bind("arktype", Namespace("http://arkumu.org/data/types/"))
    graph.bind("arkprop", Namespace("http://arkumu.org/data/properties/"))

    canonical_classes = {
        getattr(cls, "canonical_uri"): cls
        for cls in set(CANONICAL_CLASS_REGISTRY.values())
        if getattr(cls, "canonical_uri", None)
    }

    for class_uri, cls in sorted(canonical_classes.items()):
        class_ref = URIRef(class_uri)
        graph.add((class_ref, RDF.type, RDFS.Class))
        _add_literal(graph, class_ref, RDFS.label, _human_label_from_uri(class_uri))

        dataset_map = CANONICAL_DATASETS_BY_ORG.get(class_uri, {})
        if dataset_map:
            segments = [
                f"{org.upper()}: {', '.join(datasets)}"
                for org, datasets in sorted(dataset_map.items())
            ]
            _add_literal(
                graph,
                class_ref,
                RDFS.comment,
                f"Available in datasets -> { '; '.join(segments) }",
            )

        property_bindings = CANONICAL_PROPERTY_REGISTRY.get(class_uri, {})
        for prop_uri, bindings in sorted(property_bindings.items()):
            prop_ref = URIRef(prop_uri)
            graph.add((prop_ref, RDF.type, RDF.Property))
            graph.add((prop_ref, RDFS.domain, class_ref))
            graph.add((prop_ref, RDFS.range, RDFS.Literal))
            _add_literal(graph, prop_ref, RDFS.label, _human_label_from_uri(prop_uri))

            # Include a provenance note describing which institutional fields back this property.
            provenance_segments = []
            for binding in sorted(
                bindings, key=lambda b: (b.organization, b.dataset, b.dataset_property or "")
            ):
                provenance_segments.append(
                    f"{binding.organization.upper()}::{binding.dataset}::{binding.dataset_property or binding.field_name}"
                )
                if binding.local_uri:
                    graph.add(
                        (
                            prop_ref,
                            OWL.equivalentProperty,
                            URIRef(binding.local_uri),
                        )
                    )
            if provenance_segments:
                _add_literal(
                    graph,
                    prop_ref,
                    DCTERMS.source,
                    "; ".join(provenance_segments),
                )

    return graph


def _iter_institutional_classes() -> Iterable[Tuple[str, str, str, List[Tuple[str, Dict[str, str]]]]]:
    """
    Yield (org_code, dataset_name, canonical_class_uri, field_entries).

    field_entries is a list of (field_name, metadata) pairs for dataclass fields.
    """

    emitted_keys: set[Tuple[str, str]] = set()

    for module_path in INSTITUTIONAL_MANIFEST_MODULES:
        module = importlib.import_module(module_path)

        for _, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ != module_path or not is_dataclass(cls):
                continue

            doc = getattr(cls, "__doc__", "") or ""
            match = DATASET_DOC_RE.search(doc)
            if not match:
                continue

            dataset_name = match.group("dataset").strip()
            canonical_uri = match.group("canonical").strip()
            field_entries: List[Tuple[str, Dict[str, str]]] = []
            org_code: Optional[str] = None

            dataclass_fields = getattr(cls, "__dataclass_fields__", {})
            for field_obj in dataclass_fields.values():
                metadata = dict(field_obj.metadata or {})
                field_entries.append((field_obj.name, metadata))
                if not org_code and metadata.get("local_uri"):
                    org_code = _extract_org_from_uri(metadata["local_uri"])

            if not org_code:
                continue

            dedupe_key = (org_code, dataset_name.lower())
            if dedupe_key in emitted_keys:
                continue
            emitted_keys.add(dedupe_key)

            yield org_code, dataset_name, canonical_uri, field_entries


def _extract_org_from_uri(uri: str) -> Optional[str]:
    if "/data/" not in uri:
        return None
    tail = uri.split("/data/", 1)[1]
    parts = tail.split("/", 1)
    return parts[0] if parts else None


def _infer_local_class_uri(org_code: str, dataset_name: str, canonical_uri: str) -> str:
    org_prefix = f"http://arkumu.org/data/{org_code}/types/"
    if canonical_uri.startswith(org_prefix):
        return canonical_uri
    slug = slugify_uri_part(dataset_name)
    return f"{org_prefix}{slug}"


def build_institutional_graph() -> Graph:
    graph = Graph()
    graph.bind("rdfs", RDFS)
    graph.bind("rdf", RDF)
    graph.bind("owl", OWL)
    graph.bind("skos", SKOS)
    graph.bind("dcterms", DCTERMS)

    for org_code, dataset_name, canonical_uri, field_entries in sorted(
        _iter_institutional_classes(),
        key=lambda item: (item[0], item[1].lower()),
    ):
        local_class_uri = _infer_local_class_uri(org_code, dataset_name, canonical_uri)
        class_ref = URIRef(local_class_uri)
        graph.add((class_ref, RDF.type, RDFS.Class))
        _add_literal(graph, class_ref, RDFS.label, dataset_name, lang="de")

        if canonical_uri != local_class_uri:
            graph.add((class_ref, OWL.equivalentClass, URIRef(canonical_uri)))

        for field_name, metadata in field_entries:
            local_prop = metadata.get("local_uri")
            canonical_prop = metadata.get("canonical_uri")
            dataset_property = metadata.get("dataset_property") or field_name

            if not local_prop:
                continue

            prop_ref = URIRef(local_prop)
            graph.add((prop_ref, RDF.type, RDF.Property))
            graph.add((prop_ref, RDFS.domain, class_ref))
            graph.add((prop_ref, RDFS.range, RDFS.Literal))
            _add_literal(graph, prop_ref, RDFS.label, dataset_property, lang="de")

            if canonical_prop and canonical_prop != local_prop:
                graph.add((prop_ref, OWL.equivalentProperty, URIRef(canonical_prop)))

            if dataset_property:
                graph.add(
                    (
                        prop_ref,
                        SKOS.altLabel,
                        Literal(dataset_property, lang="de"),
                    )
                )

            graph.add(
                (
                    prop_ref,
                    DCTERMS.isPartOf,
                    class_ref,
                )
            )

    return graph


def _default_output_dir() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    return BASE_SCHEMA_DIR / timestamp


def _update_latest_pointer(target_dir: Path, link_path: Path) -> str:
    link_path.parent.mkdir(parents=True, exist_ok=True)
    if link_path.exists() or link_path.is_symlink():
        if link_path.is_symlink() or link_path.is_file():
            link_path.unlink()
        else:
            shutil.rmtree(link_path)
    try:
        relative_target = os.path.relpath(target_dir, link_path.parent)
        link_path.symlink_to(relative_target)
        return "symlink"
    except OSError:
        shutil.copytree(target_dir, link_path)
        return "copy"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Arkumu schemas as RDFS.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for the generated schema files (default: schemas/<ISO date-time>)",
    )
    parser.add_argument(
        "--format",
        dest="formats",
        choices=list(SCHEMA_FORMATS.keys()),
        action="append",
        help=(
            "RDF serialization(s) to emit. Can be passed multiple times. "
            "Defaults to ttl and xml."
        ),
    )
    parser.add_argument(
        "--mark-latest",
        action="store_true",
        help="Update schemas/latest to point at the generated snapshot",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir: Path = args.output_dir or _default_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    selected_formats = args.formats or list(DEFAULT_SCHEMA_FORMATS)
    # Preserve order while removing duplicates
    seen = set()
    ordered_formats: List[str] = []
    for fmt in selected_formats:
        if fmt not in seen:
            seen.add(fmt)
            ordered_formats.append(fmt)

    canonical_graph = build_canonical_graph()
    institutional_graph = build_institutional_graph()

    for fmt in ordered_formats:
        fmt_meta = SCHEMA_FORMATS[fmt]
        serializer = fmt_meta["serializer"]
        ext = fmt_meta["ext"]

        canonical_path = output_dir / f"{SCHEMA_VARIANTS['canonical']}.{ext}"
        canonical_graph.serialize(destination=str(canonical_path), format=serializer)
        print(f"Wrote canonical schema ({fmt}) to {canonical_path}")

        institutional_path = output_dir / f"{SCHEMA_VARIANTS['institutional']}.{ext}"
        institutional_graph.serialize(destination=str(institutional_path), format=serializer)
        print(f"Wrote institutional schema ({fmt}) to {institutional_path}")

    if args.mark_latest:
        marker = BASE_SCHEMA_DIR / "latest"
        strategy = _update_latest_pointer(output_dir, marker)
        print(f"Updated {marker} via {strategy}")


if __name__ == "__main__":
    main()
