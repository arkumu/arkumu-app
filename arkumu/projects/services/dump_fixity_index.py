"""Lookup helpers for dump-based storage metadata."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, Optional

from django.conf import settings

from arkumu.storage.services.upload.upload_utils import normalize_s3_key


@dataclass(frozen=True)
class FixityRecord:
    dump_key: str
    storage_key: str
    checksum_or_etag: str
    status: str

    @property
    def normalized_key(self) -> str:
        key = normalize_s3_key(self.storage_key or self.dump_key)
        if key.startswith("data/"):
            key = key[5:]
        return key


def _fixity_base_dir() -> Path:
    configured = getattr(settings, "OAI_DUMP_FIXITY_DIR", None)
    if configured:
        return Path(configured)
    return Path("data")


@lru_cache(maxsize=None)
def _load_index(org_code: str) -> Dict[str, FixityRecord]:
    """Load TSV file for org and map normalized keys to fixity records."""

    base_dir = _fixity_base_dir()
    org = (org_code or "").strip().lower()
    if not org:
        return {}

    tsv_path = base_dir / f"{org}_s3_fixity.tsv"
    if not tsv_path.exists():
        return {}

    mapping: Dict[str, FixityRecord] = {}

    try:
        with tsv_path.open("r", encoding="utf-8") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            for row in reader:
                dump_key = (row.get("dump_key") or "").strip()
                storage_key = (row.get("matched_s3_key") or "").strip() or dump_key
                checksum_or_etag = (row.get("checksum_or_etag") or "").strip()
                status = (row.get("source_status") or "").strip()
                record = FixityRecord(
                    dump_key=dump_key,
                    storage_key=storage_key,
                    checksum_or_etag=checksum_or_etag,
                    status=status,
                )
                normalized = record.normalized_key
                mapping.setdefault(normalized, record)
    except Exception:
        return {}

    return mapping


def clear_cache() -> None:
    _load_index.cache_clear()


def find_fixity(org_code: str, candidates: Iterable[str]) -> Optional[FixityRecord]:
    """Return the first fixity record matching any candidate key."""

    index = _load_index(org_code)
    if not index or not candidates:
        return None

    for candidate in candidates:
        if not candidate:
            continue
        normalized = normalize_s3_key(candidate)
        if normalized.startswith("data/"):
            normalized = normalized[5:]
        record = index.get(normalized)
        if record:
            return record
    return None
