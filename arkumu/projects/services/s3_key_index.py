from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from arkumu.storage.services.upload.upload_utils import normalize_s3_key

@dataclass(frozen=True)
class S3KeyLookup:
    by_full: Dict[str, str]
    by_name: Dict[str, frozenset[str]]
    by_lower: Dict[str, str]

    def find(self, candidates: Iterable[str]) -> Optional[str]:
        for candidate in candidates:
            full = self.by_full.get(candidate)
            if full:
                return full
        for candidate in candidates:
            name = candidate.split('/')[-1]
            matches = self.by_name.get(name)
            if matches and len(matches) == 1:
                return next(iter(matches))
        for candidate in candidates:
            lowered = candidate.lower()
            match = self.by_lower.get(lowered)
            if match:
                return match
        return None


_CACHE: Dict[str, S3KeyLookup] = {}


def _normalise_key(value: str) -> Optional[str]:
    if not value:
        return None
    normalised = normalize_s3_key(value.strip())
    if not normalised:
        return None
    if normalised.startswith('data/'):
        normalised = normalised[5:]
    return normalised


def get_s3_key_map(org_code: str, *, base_dir: Path = Path('data')) -> S3KeyLookup:
    code = (org_code or '').strip().lower()
    if not code:
        return S3KeyLookup({}, {}, {})

    cached = _CACHE.get(code)
    if cached:
        return cached

    path = base_dir / f'{code}_s3_keys.txt'
    by_full: Dict[str, str] = {}
    by_name: Dict[str, set[str]] = defaultdict(set)
    by_lower: Dict[str, str] = {}
    lower_collisions: set[str] = set()
    if path.exists():
        with path.open('r', encoding='utf-8') as handle:
            for raw in handle:
                raw = raw.strip()
                if not raw:
                    continue
                normalised = _normalise_key(raw)
                if not normalised:
                    continue
                by_full.setdefault(normalised, raw)
                name = normalize_s3_key(Path(raw).name)
                if name:
                    by_name[name].add(raw)
                lowered = normalised.lower()
                existing = by_lower.get(lowered)
                if existing and existing != raw:
                    lower_collisions.add(lowered)
                elif not existing:
                    by_lower[lowered] = raw
    for key in lower_collisions:
        by_lower.pop(key, None)
    lookup = S3KeyLookup(
        by_full=by_full,
        by_name={k: frozenset(v) for k, v in by_name.items()},
        by_lower=by_lower,
    )
    _CACHE[code] = lookup
    return lookup


def _normalised_candidates(value: Optional[str]) -> List[str]:
    if not value:
        return []
    raw = str(value).strip()
    if not raw:
        return []
    variants = {raw}
    if '\\' in raw:
        variants.add(raw.replace('\\', '/'))
    normalised_values: List[str] = []
    seen: set[str] = set()
    for variant in variants:
        normalised = _normalise_key(variant)
        if not normalised:
            continue
        if normalised not in seen:
            normalised_values.append(normalised)
            seen.add(normalised)
    return normalised_values


def lookup_dump_storage_key(org_code: str, candidates: Iterable[Optional[str]]) -> Optional[str]:
    lookup = get_s3_key_map(org_code)
    normalised: List[str] = []
    for candidate in candidates:
        normalised.extend(_normalised_candidates(candidate))
    if not normalised:
        return None
    return lookup.find(normalised)
