"""Helpers for detecting and decoding legacy HTMX placeholder URIs."""

from __future__ import annotations

from typing import Optional, Tuple

PLACEHOLDER_PREFIX = "uri-http-"
_LEGACY_PREFIX = "uri-"
_LABEL_MARKERS = ("-label-", "-LABEL-")
_RESOURCE_MARKERS = ("-resource-id-", "-RESOURCE-ID-")


def is_placeholder_uri(raw: Optional[str]) -> bool:
    """Return True when the value matches the legacy placeholder slug pattern."""
    return bool(raw and raw.startswith(PLACEHOLDER_PREFIX))


def decode_placeholder_uri(raw: str) -> Tuple[str, Optional[str]]:
    """
    Translate a legacy placeholder slug back into the canonical URI.

    Returns:
        A tuple of (canonical_uri, label_hint). The label hint is derived from the
        placeholder slug when available and can help restore display labels.
    """
    if not is_placeholder_uri(raw):
        return raw, None

    remainder = raw[len(_LEGACY_PREFIX) :]
    label_hint: Optional[str] = None

    for marker in _LABEL_MARKERS:
        if marker in remainder:
            remainder, label_hint = remainder.split(marker, 1)
            break

    for marker in _RESOURCE_MARKERS:
        if marker in remainder:
            remainder = remainder.split(marker, 1)[0]
            break

    if label_hint:
        for marker in _RESOURCE_MARKERS:
            if marker in label_hint:
                label_hint = label_hint.split(marker, 1)[0]
                break
        label_hint = label_hint.replace("-", " ").strip() or None

    tokens = remainder.split("-")
    if len(tokens) < 3:
        return raw, label_hint

    scheme = tokens[0]
    domain = ".".join(tokens[1:3])
    path_tokens = tokens[3:]
    canonical = scheme + "://" + domain
    if path_tokens:
        canonical += "/" + "/".join(path_tokens)

    return canonical, label_hint

