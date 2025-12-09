"""DCP bundle index lookups for KHM using relative Rosetta paths."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import logging

from django.conf import settings

from arkumu.oaipmh.models import OAIDcpPathIndex
from arkumu.oaipmh import path_mapping

logger = logging.getLogger(__name__)

# In-memory cache for ALL DCP file lists (folder_name -> tuple of file paths)
_DCP_FILES_CACHE: Dict[str, Tuple[str, ...]] = {}
_DCP_FILES_CACHE_LOADED = False


def _load_dcp_files_cache() -> None:
    """Load ALL KHM DCP file lists into memory (one-time)."""
    global _DCP_FILES_CACHE, _DCP_FILES_CACHE_LOADED
    if _DCP_FILES_CACHE_LOADED:
        return

    # Query all KHM DCP entries at once
    qs = OAIDcpPathIndex.objects.filter(org_code="khm").order_by("folder_name", "relative_file_path")

    # Group by folder_name
    results: Dict[str, List[str]] = {}
    for entry in qs:
        folder_name = entry.folder_name
        rel_path = entry.relative_file_path.strip().lstrip("/")
        if not rel_path:
            continue

        if folder_name not in results:
            results[folder_name] = []

        # Extract the file path after the folder_name segment
        if "/" not in rel_path:
            if rel_path == folder_name:
                results[folder_name].append(rel_path)
            continue

        segments = rel_path.split("/")
        try:
            idx = segments.index(folder_name)
        except ValueError:
            continue

        remainder = segments[idx + 1:]
        if remainder:
            results[folder_name].append("/".join(remainder))

    # Convert to tuples
    _DCP_FILES_CACHE = {k: tuple(v) for k, v in results.items()}
    _DCP_FILES_CACHE_LOADED = True
    logger.info("DCP files cache loaded: %d folders, %d total files",
                len(_DCP_FILES_CACHE),
                sum(len(v) for v in _DCP_FILES_CACHE.values()))


@dataclass(frozen=True)
class BundleLookupResult:
    """Resolved DCP bundle members for a given folder."""

    org_code: str
    folder_name: str
    # Relative file paths under the Rosetta root, e.g. "2265_..._dcp/asset.mxf"
    relative_file_paths: Tuple[str, ...]


def _normalize_org_code(org_code: Optional[str]) -> str:
    return (org_code or "").strip().lower()


def _derive_bundle_key_from_relative_path(relative_path: str) -> Optional[str]:
    """Derive bundle_key from a relative path by cutting after the first *.dcp segment."""
    if not relative_path:
        return None
    parts = [segment for segment in relative_path.split("/") if segment]
    if not parts:
        return None
    bundle_parts: List[str] = []
    for segment in parts:
        bundle_parts.append(segment)
        if segment.lower().endswith(".dcp"):
            break
    if not bundle_parts:
        return None
    return "/".join(bundle_parts)


def _rosetta_root(org_code: str) -> Optional[str]:
    roots = getattr(settings, "OAI_EXTERNAL_ROSETTA_ROOTS", {}) or {}
    root = roots.get(org_code)
    if root:
        return str(root).rstrip("/")
    return None


def batch_get_bundle_members(
    org_code: str,
    folder_names: Sequence[str],
) -> Dict[str, Tuple[str, ...]]:
    """Batch fetch DCP bundle members for multiple folders at once.

    Returns a dict mapping folder_name -> tuple of relative file paths.
    Uses in-memory cache for KHM (no DB query needed).
    """
    org = _normalize_org_code(org_code)
    if not org or not folder_names:
        return {}

    # Use in-memory cache for KHM
    if org == "khm":
        _load_dcp_files_cache()
        return {fn: _DCP_FILES_CACHE.get(fn, ()) for fn in folder_names if fn in _DCP_FILES_CACHE}

    # Fallback to DB query for other orgs
    qs = OAIDcpPathIndex.objects.filter(
        org_code=org,
        folder_name__in=list(folder_names),
    ).order_by("folder_name", "relative_file_path")

    results: Dict[str, List[str]] = {fn: [] for fn in folder_names}

    for entry in qs:
        folder_name = entry.folder_name
        rel_path = entry.relative_file_path.strip().lstrip("/")
        if not rel_path:
            continue

        if "/" not in rel_path:
            if rel_path == folder_name:
                results[folder_name].append(rel_path)
            continue

        segments = rel_path.split("/")
        try:
            idx = segments.index(folder_name)
        except ValueError:
            continue

        remainder = segments[idx + 1:]
        if len(remainder) != 1:
            continue

        candidate = "/".join(segments[idx:])
        if candidate not in results[folder_name]:
            results[folder_name].append(candidate)

    return {fn: tuple(paths) for fn, paths in results.items() if paths}


def get_bundle_members(
    org_code: str,
    folder_name: str,
    *,
    folder_path: Optional[str] = None,
) -> BundleLookupResult:
    """Return relative file paths for all files in the given DCP bundle.

    - org_code: organization code, e.g. "khm".
    - folder_name: last segment of the DCP folder path as stored in the triple.
    - folder_path: optional original folder path from the triple (absolute). Used only
      as a hint to disambiguate bundles with the same folder_name.

    The function first attempts to use the OAIDcpPathIndex table. If no entries are
    found, it falls back to scanning the in-memory PathIndex (loaded from the
    configured mapping file) using the legacy semantics.
    """
    org = _normalize_org_code(org_code)
    if not org or not folder_name:
        return BundleLookupResult(org, folder_name, relative_file_paths=())

    # Try DB-backed index first
    qs = OAIDcpPathIndex.objects.filter(org_code=org, folder_name=folder_name)
    if folder_path:
        # Try to derive a bundle_key hint from folder_path
        root = _rosetta_root(org)
        rel_hint: Optional[str] = None
        if root and folder_path.startswith(root + "/"):
            rel_hint = folder_path[len(root) + 1 :]
        elif root and folder_path == root:
            rel_hint = ""
        if rel_hint:
            bundle_hint = _derive_bundle_key_from_relative_path(rel_hint)
            if bundle_hint:
                qs = qs.filter(bundle_key=bundle_hint)

    paths: List[str] = []
    if qs.exists():
        for entry in qs.order_by("relative_file_path"):
            # Ensure we only return direct children of the bundle root
            rel_path = entry.relative_file_path.strip().lstrip("/")
            if not rel_path:
                continue
            if "/" not in rel_path:
                # File in root; only accept if folder_name equals file_name (rare)
                if rel_path == folder_name:
                    paths.append(rel_path)
                continue
            # Match on folder_name as a segment
            segments = rel_path.split("/")
            try:
                idx = segments.index(folder_name)
            except ValueError:
                continue
            remainder = segments[idx + 1 :]
            if len(remainder) != 1:
                continue
            candidate = "/".join(segments[idx:])
            paths.append(candidate)

        if paths:
            unique: List[str] = []
            seen: set[str] = set()
            for value in paths:
                if value in seen:
                    continue
                seen.add(value)
                unique.append(value)
            return BundleLookupResult(org, folder_name, relative_file_paths=tuple(unique))

    # Fallback: scan PathIndex once using legacy semantics on the configured file
    index = path_mapping._load_index(org)  # type: ignore[attr-defined]
    full_paths = index.full_paths
    if not full_paths:
        return BundleLookupResult(org, folder_name, relative_file_paths=())

    root = _rosetta_root(org)
    if not root:
        logger.warning("No Rosetta root configured for org=%s; cannot derive relative DCP paths", org)
        return BundleLookupResult(org, folder_name, relative_file_paths=())

    matching: List[str] = []
    for abs_path in full_paths:
        normalized = abs_path.replace("\\", "/")
        if folder_name not in normalized:
            continue
        idx = normalized.find(folder_name)
        if idx == -1:
            continue
        after = normalized[idx + len(folder_name) :]
        if not after.startswith("/"):
            continue
        filename = after[1:]
        if not filename or "/" in filename:
            continue
        if not normalized.startswith(root + "/"):
            # Skip paths outside the configured Rosetta root; they cannot be turned into relative paths
            continue
        rel_path = normalized[len(root) + 1 :]
        matching.append(rel_path)

    if not matching:
        return BundleLookupResult(org, folder_name, relative_file_paths=())

    unique_rel: List[str] = []
    seen_rel: set[str] = set()
    for rel in matching:
        if rel in seen_rel:
            continue
        seen_rel.add(rel)
        unique_rel.append(rel)

    logger.info(
        "DCP index fallback used for org=%s folder=%s (matches=%d)", org, folder_name, len(unique_rel)
    )
    return BundleLookupResult(org, folder_name, relative_file_paths=tuple(unique_rel))

