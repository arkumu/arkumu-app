"""Map internal digital object paths to Rosetta-accessible locations."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from django.conf import settings
import logging

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PathIndex:
    full_paths: frozenset[str]
    by_basename: Dict[str, tuple[str, ...]]


def _clean_path(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized


@lru_cache(maxsize=None)
def _load_index_cached(org_code: str, configured: Optional[str]) -> PathIndex:
    if not configured:
        return PathIndex(full_paths=frozenset(), by_basename={})

    path = Path(configured)
    if not path.exists():
        logger.warning("OAI external path index for %s not found at %s", org_code, path)
        return PathIndex(full_paths=frozenset(), by_basename={})

    full_paths: set[str] = set()
    by_basename: Dict[str, List[str]] = {}

    try:
        with path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                # Skip macOS resource fork entries
                if Path(line).name.startswith("._"):
                    continue
                full_paths.add(line)
                basename = Path(line).name
                if not basename:
                    continue
                by_basename.setdefault(basename, []).append(line)
    except OSError as exc:  # pragma: no cover - defensive
        logger.warning("Failed to load OAI external path index for %s: %s", org_code, exc)
        return PathIndex(full_paths=frozenset(), by_basename={})

    frozen_map = {key: tuple(values) for key, values in by_basename.items()}
    logger.info("OAI path index loaded for %s: %d paths, %d unique basenames", org_code, len(full_paths), len(frozen_map))
    return PathIndex(full_paths=frozenset(full_paths), by_basename=frozen_map)


def _load_index(org_code: str) -> PathIndex:
    configured = getattr(settings, "OAI_EXTERNAL_PATH_FILES", {}).get(org_code)
    return _load_index_cached(org_code, configured)


# Expose cache management helpers for test stability
_load_index.cache_clear = _load_index_cached.cache_clear  # type: ignore[attr-defined]
_load_index.cache_info = _load_index_cached.cache_info  # type: ignore[attr-defined]


def _rosetta_root(org_code: str) -> Optional[str]:
    return getattr(settings, "OAI_EXTERNAL_ROSETTA_ROOTS", {}).get(org_code)


def _hmt_prefixes() -> Iterable[str]:
    prefixes = getattr(settings, "OAI_EXTERNAL_PATH_PREFIXES", {}).get("hmt", [])
    if prefixes:
        return prefixes
    return ("/Volumes/18TB1",)


def resolve_external_paths(
    org_code: str,
    *,
    path: Optional[str] = None,
    file_name: Optional[str] = None,
) -> List[str]:
    """Resolve possible Rosetta paths for a digital object.

    Returns a list of candidate absolute paths on the Rosetta-accessible NFS that
    correspond to the supplied metadata path or filename.
    """

    org = (org_code or "").lower().strip()
    if not org:
        return []

    path = _clean_path(path)
    file_name = _clean_path(file_name)

    if org == "hmt":
        return _resolve_hmt(path, file_name)
    if org == "khm":
        return _resolve_khm(path, file_name)
    return []


def _resolve_hmt(path: Optional[str], file_name: Optional[str]) -> List[str]:
    index = _load_index("hmt")
    roots = list(_hmt_prefixes())
    rosetta_root = _rosetta_root("hmt") or "/rosetta/hfmt/sandbox/input/arkumu"
    candidates: List[str] = []

    if path:
        if path.startswith("/rosetta/"):
            if not index.full_paths or path in index.full_paths:
                return [path]
        for prefix in roots:
            if path.startswith(prefix):
                candidate = path.replace(prefix, rosetta_root, 1)
                if not index.full_paths or candidate in index.full_paths:
                    candidates.append(candidate)
                break

    if not candidates and file_name:
        matches = index.by_basename.get(file_name)
        if matches:
            candidates.extend(matches)

    if not candidates and (path or file_name):
        logger.info(
            "Rosetta resolver (HMT) could not resolve path=%s file=%s (index paths=%d, basenames=%d)",
            path,
            file_name,
            len(index.full_paths),
            len(index.by_basename),
        )

    return candidates


def _resolve_khm(path: Optional[str], file_name: Optional[str]) -> List[str]:
    index = _load_index("khm")
    rosetta_root = _rosetta_root("khm") or "/rosetta/khm/sandbox/input/arkumu/daten"
    candidates: List[str] = []

    if path and path.startswith("/rosetta/"):
        if not index.full_paths or path in index.full_paths:
            candidates.append(path)

    if not candidates and file_name:
        matches = list(index.by_basename.get(file_name, ()))
        if matches:
            candidates.extend(matches)

    if not candidates and file_name:
        derived = str(Path(rosetta_root) / file_name)
        if not index.full_paths or derived in index.full_paths:
            candidates.append(derived)

    if not candidates and (path or file_name):
        logger.info(
            "Rosetta resolver (KHM) could not resolve path=%s file=%s (index paths=%d, basenames=%d)",
            path,
            file_name,
            len(index.full_paths),
            len(index.by_basename),
        )

    # Final dedupe while preserving order
    seen: set[str] = set()
    unique: List[str] = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        unique.append(candidate)
    return unique
