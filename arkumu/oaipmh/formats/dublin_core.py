"""
Dublin Core (oai_dc) serializer skeleton and crosswalk helpers.

This module provides a simple, pluggable crosswalk from Arkumu graph
predicates or mapping-config column keys to Dublin Core simple elements
(`oai_dc:dc` with `dc:*` children).

It is intentionally light-weight so it can be wired into a future
OAI‑PMH provider without hard dependencies on Django models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple
import json


# Namespaces
OAI_DC_NS = "http://www.openarchives.org/OAI/2.0/oai_dc/"
DC_NS = "http://purl.org/dc/elements/1.1/"
DCTERMS_NS = "http://purl.org/dc/terms/"


# Predicate → simple DC element name (not qualified with namespace prefix here)
# These follow the guidance captured in arkumu/oaipmh/README.md.
DEFAULT_PREDICATE_MAP: Dict[str, str] = {
    f"{DCTERMS_NS}title": "title",
    f"{DCTERMS_NS}creator": "creator",
    f"{DCTERMS_NS}subject": "subject",
    f"{DCTERMS_NS}description": "description",
    f"{DCTERMS_NS}publisher": "publisher",
    f"{DCTERMS_NS}contributor": "contributor",
    # Date family collapses into dc:date for oai_dc
    f"{DCTERMS_NS}date": "date",
    f"{DCTERMS_NS}issued": "date",
    f"{DCTERMS_NS}created": "date",
    f"{DCTERMS_NS}modified": "date",
    f"{DCTERMS_NS}type": "type",
    f"{DCTERMS_NS}format": "format",
    f"{DCTERMS_NS}identifier": "identifier",
    f"{DCTERMS_NS}source": "source",
    f"{DCTERMS_NS}language": "language",
    f"{DCTERMS_NS}relation": "relation",
    f"{DCTERMS_NS}coverage": "coverage",
    f"{DCTERMS_NS}rights": "rights",
}


@dataclass
class CrosswalkRule:
    """A single mapping rule for a DC term.

    Supports simple selectors:
    - selector == "predicate_uri" with value == full URI
    - selector == "column_key" with value == qualified mapping key (e.g., "fuk::Projekt::Bevorzugter Titel")
    - Optional priority for ordering
    """

    selector: str
    value: str
    priority: int = 100
    notes: Optional[str] = None


@dataclass
class DublinCoreCrosswalk:
    """Holds a mapping from DC terms to lists of CrosswalkRules."""

    mappings: Dict[str, List[CrosswalkRule]] = field(default_factory=dict)

    @classmethod
    def from_json(cls, config: Dict[str, Any]) -> "DublinCoreCrosswalk":
        raw = config.get("mappings", {})
        parsed: Dict[str, List[CrosswalkRule]] = {}
        for dc_term, entries in raw.items():
            rules: List[CrosswalkRule] = []
            for e in entries or []:
                rules.append(
                    CrosswalkRule(
                        selector=e.get("selector", "predicate_uri"),
                        value=e.get("value", ""),
                        priority=int(e.get("priority", 100)),
                        notes=e.get("notes"),
                    )
                )
            # sort by priority ascending
            rules.sort(key=lambda r: r.priority)
            parsed[dc_term] = rules
        return cls(mappings=parsed)

    @classmethod
    def load_file(cls, path: str) -> "DublinCoreCrosswalk":
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_json(json.load(f))


class DublinCoreSerializer:
    """Minimal oai_dc crosswalk that accumulates DC elements.

    Two usage modes:
    1) serialize_from_triples(triples): expects iterable of triples where
       each triple exposes a predicate URI and an object value/label.
    2) serialize_from_row(dataset_name, row, blueprint): maps mapping-config
       column keys via blueprint.property_resources to DC terms using a crosswalk.

    This does not emit XML; it returns a dict {"dc:title": [..], ...} suitable
    for an envelope builder.
    """

    def __init__(
        self,
        predicate_map: Optional[Dict[str, str]] = None,
        crosswalk: Optional[DublinCoreCrosswalk] = None,
    ) -> None:
        self.predicate_map = predicate_map or DEFAULT_PREDICATE_MAP
        self.crosswalk = crosswalk or DublinCoreCrosswalk(mappings={})

    @staticmethod
    def _dc_key(term: str) -> str:
        # Store with dc: prefix so downstream XML builders can apply ns
        return f"dc:{term}"

    def _add(self, out: Dict[str, List[str]], term: str, value: Optional[str]) -> None:
        if value is None:
            return
        v = value.strip()
        if not v:
            return
        key = self._dc_key(term)
        out.setdefault(key, []).append(v)

    # --- Mode 1: graph triples crosswalk ---
    def serialize_from_triples(
        self,
        triples: Iterable[Tuple[str, str, Any]] | Iterable[Any],
        *,
        get_predicate: Optional[Any] = None,
        get_object_value: Optional[Any] = None,
    ) -> Dict[str, List[str]]:
        """Map triples to DC using predicate_map.

        - triples: iterable over either raw (s,p,o) or arbitrary objects
        - get_predicate: function(obj) -> predicate_uri when obj is not a tuple
        - get_object_value: function(obj) -> str literal or label
        """
        out: Dict[str, List[str]] = {}
        for t in triples:
            if isinstance(t, tuple) and len(t) >= 3:
                _, predicate_uri, obj = t[0], t[1], t[2]
                value = str(obj)
            else:
                if not get_predicate or not get_object_value:
                    raise ValueError("Provide get_predicate/get_object_value for object triples")
                predicate_uri = get_predicate(t)
                value = get_object_value(t)

            dc_term = self.predicate_map.get(predicate_uri)
            if dc_term:
                self._add(out, dc_term, value)
        return out

    # --- Mode 2: mapping-config aware crosswalk ---
    def serialize_from_row(
        self,
        dataset_name: str,
        row: Dict[str, Any],
        *,
        blueprint: Optional[Dict[str, Any]] = None,
        organization_code: Optional[str] = None,
    ) -> Dict[str, List[str]]:
        """Map a dataset row to DC using a column‑key based crosswalk.

        - dataset_name: current dataset
        - row: dict of column_name -> value
        - blueprint: optional schema blueprint containing 'property_resources'
        - organization_code: used to build qualified column keys (e.g., 'fuk::Dataset::Column')
        """
        out: Dict[str, List[str]] = {}

        # Build a reverse index of available qualified keys for this row
        # We try both qualified and unqualified keys for resilience.
        qualified_prefix = f"{(organization_code or '').strip()}::{dataset_name}::" if organization_code else None

        available_keys: Dict[str, Any] = {}
        for col, val in row.items():
            available_keys[col] = val
            if qualified_prefix:
                available_keys[f"{qualified_prefix}{col}"] = val

        # Apply crosswalk rules by priority
        for dc_term, rules in self.crosswalk.mappings.items():
            for rule in rules:
                if rule.selector == "column_key":
                    if rule.value in available_keys:
                        self._add(out, dc_term.split(":", 1)[-1], str(available_keys[rule.value]))
                # Predicate rules are applied in triple mode; we ignore here.
                # Other selectors can be added later (e.g., role filters, joins).

        return out


__all__ = [
    "OAI_DC_NS",
    "DC_NS",
    "DCTERMS_NS",
    "DEFAULT_PREDICATE_MAP",
    "CrosswalkRule",
    "DublinCoreCrosswalk",
    "DublinCoreSerializer",
]

