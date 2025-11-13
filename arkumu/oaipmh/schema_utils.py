"""
Utilities for resolving generated schema snapshots for OAI endpoints.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional

from django.conf import settings
from django.http import HttpRequest
from django.urls import reverse

SCHEMA_VARIANTS: Dict[str, str] = {
    "canonical": "canonical-schema.ttl",
    "institutional": "institutional-schema.ttl",
}

SCHEMA_DOCS_ROOT = Path(settings.BASE_DIR) / "docs" / "schemas"
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class SchemaSnapshot:
    """Represents a dated schema export snapshot."""

    tag: str
    path: Path

    def file_path(self, variant: str) -> Path:
        filename = SCHEMA_VARIANTS.get(variant)
        if not filename:
            raise KeyError(f"Unknown schema variant: {variant}")
        file_path = self.path / filename
        if not file_path.exists():
            raise FileNotFoundError(file_path)
        return file_path


def _iter_snapshot_dirs() -> Iterable[Path]:
    if not SCHEMA_DOCS_ROOT.exists():
        return []
    # Sorted descending (latest first)
    return sorted(
        (
            entry
            for entry in SCHEMA_DOCS_ROOT.iterdir()
            if entry.is_dir() and ISO_DATE_RE.match(entry.name)
        ),
        reverse=True,
    )


def get_latest_snapshot() -> Optional[SchemaSnapshot]:
    for directory in _iter_snapshot_dirs():
        return SchemaSnapshot(tag=directory.name, path=directory)
    return None


def get_snapshot(tag: str) -> Optional[SchemaSnapshot]:
    if tag == "latest":
        return get_latest_snapshot()
    candidate = SCHEMA_DOCS_ROOT / tag
    if candidate.is_dir():
        return SchemaSnapshot(tag=tag, path=candidate)
    return None


def list_schema_variants() -> Iterable[str]:
    return SCHEMA_VARIANTS.keys()


@dataclass(frozen=True)
class SchemaUrlBundle:
    snapshot_tag: str
    urls: Dict[str, Dict[str, str]]


def build_schema_url_bundle(request: HttpRequest) -> Optional[SchemaUrlBundle]:
    snapshot = get_latest_snapshot()
    if not snapshot:
        return None

    url_map: Dict[str, Dict[str, str]] = {}
    for variant in SCHEMA_VARIANTS:
        latest_url = request.build_absolute_uri(
            reverse("oai:schema_download", args=("latest", variant))
        )
        snapshot_url = request.build_absolute_uri(
            reverse("oai:schema_download", args=(snapshot.tag, variant))
        )
        url_map[variant] = {
            "latest": latest_url,
            "snapshot": snapshot_url,
        }

    return SchemaUrlBundle(snapshot_tag=snapshot.tag, urls=url_map)
