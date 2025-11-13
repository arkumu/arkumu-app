"""
Utilities for resolving generated schema snapshots for OAI endpoints.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional

from urllib.parse import urljoin

from django.conf import settings
from django.http import HttpRequest
from django.urls import NoReverseMatch, reverse

from .schema_config import (
    SCHEMA_VARIANTS,
    SCHEMA_FORMATS,
    DEFAULT_SCHEMA_FORMATS,
    SCHEMA_RELATIVE_DIR,
)

SCHEMA_DOCS_ROOT = Path(settings.BASE_DIR) / SCHEMA_RELATIVE_DIR
# Accept YYYY-MM-DD or YYYY-MM-DD-HHMMSS
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:-\d{6})?$")


@dataclass(frozen=True)
class SchemaSnapshot:
    """Represents a dated schema export snapshot."""

    tag: str
    path: Path

    def file_path(self, variant: str, fmt: str) -> Path:
        base_name = SCHEMA_VARIANTS.get(variant)
        fmt_meta = SCHEMA_FORMATS.get(fmt)
        if not base_name or not fmt_meta:
            raise KeyError(f"Unknown schema variant ({variant}) or format ({fmt}).")
        filename = f"{base_name}.{fmt_meta['ext']}"
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


def variant_slug(variant: str) -> str:
    """Return URL slug for a canonical variant key."""

    return SCHEMA_VARIANTS.get(variant, variant)


def resolve_variant_key(slug: str) -> Optional[str]:
    """Resolve incoming slug to canonical variant key."""

    if slug in SCHEMA_VARIANTS:
        return slug
    normalized = slug.strip().lower()
    for key, value in SCHEMA_VARIANTS.items():
        if normalized == value.lower():
            return key
    return None


def format_from_extension(extension: str) -> Optional[str]:
    for fmt, meta in SCHEMA_FORMATS.items():
        if meta["ext"] == extension:
            return fmt
    return None


@dataclass(frozen=True)
class SchemaUrlBundle:
    snapshot_tag: str
    urls: Dict[str, Dict[str, Dict[str, str]]]


def _resolve_schema_url(
    snapshot: str,
    variant: str,
    ext: str,
    request: Optional[HttpRequest] = None,
) -> str:
    route_names = ("schema_download_public", "oai:schema_download")
    path = None
    for route in route_names:
        try:
            slug = variant_slug(variant)
            path = reverse(route, args=(snapshot, slug, ext))
            break
        except NoReverseMatch:
            continue
    if path is None:
        raise NoReverseMatch(f"No schema download route defined for variant '{variant}'")
    if request is not None:
        return request.build_absolute_uri(path)
    base_url = getattr(settings, "ABSOLUTE_SITE_BASE_URL", None)
    if base_url:
        return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    return path


def build_schema_url_bundle(request: HttpRequest) -> Optional[SchemaUrlBundle]:
    snapshot = get_latest_snapshot()
    if not snapshot:
        return None

    url_map: Dict[str, Dict[str, Dict[str, str]]] = {}
    for variant in SCHEMA_VARIANTS:
        variant_map: Dict[str, Dict[str, str]] = {}
        for fmt in SCHEMA_FORMATS:
            fmt_meta = SCHEMA_FORMATS[fmt]
            try:
                snapshot.file_path(variant, fmt)
            except FileNotFoundError:
                continue

            ext = fmt_meta["ext"]
            try:
                latest_url = _resolve_schema_url("latest", variant, ext, request)
                snapshot_url = _resolve_schema_url(snapshot.tag, variant, ext, request)
            except NoReverseMatch:
                continue
            variant_map[fmt] = {
                "latest": latest_url,
                "snapshot": snapshot_url,
            }

        if variant_map:
            url_map[variant] = variant_map

    if not url_map:
        return None

    return SchemaUrlBundle(snapshot_tag=snapshot.tag, urls=url_map)


def build_schema_href_map(
    *,
    fmt: str = "xml",
    snapshot_alias: str = "snapshot",
    request: Optional[HttpRequest] = None,
) -> Dict[str, str]:
    """Return variant→href map for schema references."""

    snapshot = get_latest_snapshot()
    if not snapshot:
        return {}

    fmt_meta = SCHEMA_FORMATS.get(fmt)
    if not fmt_meta:
        return {}

    ext = fmt_meta["ext"]
    href_map: Dict[str, str] = {}

    for variant in SCHEMA_VARIANTS:
        try:
            snapshot.file_path(variant, fmt)
        except FileNotFoundError:
            continue
        link_tag = snapshot.tag if snapshot_alias == "snapshot" else snapshot_alias
        try:
            href_map[variant] = _resolve_schema_url(link_tag, variant, ext, request)
        except NoReverseMatch:
            continue

    return href_map
