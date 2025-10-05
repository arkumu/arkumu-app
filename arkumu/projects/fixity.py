"""Utilities for working with digital object fixity metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple
import re


_HEX_RE = re.compile(r"^[0-9a-fA-F]+$")
_SUPPORTED_ALGORITHMS = {
    "md5",
    "sha1",
    "sha256",
    "sha512",
}


def _normalize_algorithm(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    normalized = value.lower().strip()
    if not normalized:
        return None
    normalized = normalized.replace('-', '')
    if normalized in _SUPPORTED_ALGORITHMS:
        return normalized
    return normalized if normalized.startswith("sha") else None


def _normalize_digest(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    normalized = value.strip()
    return normalized or None


@dataclass(frozen=True)
class FixityInfo:
    """Structured representation of a checksum with algorithm and provenance."""

    algorithm: Optional[str]
    digest: Optional[str]
    provenance: Optional[str] = None

    def with_provenance(self, provenance: Optional[str]) -> "FixityInfo":
        if provenance == self.provenance:
            return self
        return FixityInfo(self.algorithm, self.digest, provenance)

    def or_default(self, default_algorithm: Optional[str]) -> "FixityInfo":
        if self.algorithm or not default_algorithm:
            return self
        return FixityInfo(default_algorithm, self.digest, self.provenance)

    def as_tuple(self) -> Tuple[Optional[str], Optional[str]]:
        return self.algorithm, self.digest


def parse_fixity(raw_value: Optional[str]) -> FixityInfo:
    """Return a parsed FixityInfo from a raw checksum string."""

    if not raw_value:
        return FixityInfo(None, None)

    text = str(raw_value).strip()
    if not text:
        return FixityInfo(None, None)

    algorithm: Optional[str] = None
    digest: Optional[str] = text

    for delimiter in (":", "=", " "):
        if delimiter in text:
            prefix, candidate = text.split(delimiter, 1)
            candidate = candidate.strip()
            parsed_algorithm = _normalize_algorithm(prefix)
            if parsed_algorithm and candidate:
                algorithm = parsed_algorithm
                digest = candidate
                break

    if algorithm is None and _HEX_RE.match(text):
        if len(text) == 32:
            algorithm = "md5"
        elif len(text) == 40:
            algorithm = "sha1"
        elif len(text) == 64:
            algorithm = "sha256"
        elif len(text) == 128:
            algorithm = "sha512"

    digest = _normalize_digest(digest)
    if digest is None:
        algorithm = None

    return FixityInfo(algorithm, digest)
