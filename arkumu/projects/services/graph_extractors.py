"""Extractors for converting graph triples to structured data.

Small, focused functions for extracting specific data types from ProjectGraphs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from arkumu.projects.services.graph_service import TripleResult


# Canonical predicate URIs
class Predicates:
    """Canonical predicate URIs for extraction."""
    # Project properties
    TITLE = "http://arkumu.org/data/properties/bevorzugter-titel"
    SUBTITLE = "http://arkumu.org/data/properties/bevorzugter-untertitel"
    DESCRIPTION = "http://arkumu.org/data/properties/beschreibung"
    DESCRIPTION_DE = "http://arkumu.org/data/properties/deutsche-beschreibung"
    IMAGE = "http://arkumu.org/data/properties/vorschaubild"
    INSTITUTION = "http://arkumu.org/data/properties/einliefernde-hochschule"
    CATEGORY = "http://arkumu.org/data/properties/projektkategorie"
    PROJECT_TYPE = "http://arkumu.org/data/properties/projektart"
    ALT_TITLE = "http://arkumu.org/data/properties/alternativer-titel"
    SCHLAGWORT = "http://arkumu.org/data/properties/schlagwort"

    # Event predicates
    EVENT = "http://arkumu.org/data/properties/ereignis"
    EVENT_NAME = "http://arkumu.org/data/properties/ereignisname"
    EVENT_START = "http://arkumu.org/data/properties/ereignisbeginn"
    EVENT_END = "http://arkumu.org/data/properties/ereignisende"
    EVENT_LOCATION = "http://arkumu.org/data/properties/ereignisort"
    EVENT_DESCRIPTION = "http://arkumu.org/data/properties/ereignisbeschreibung"
    EVENT_TYPE = "http://arkumu.org/data/properties/ereignistyp"
    EVENT_TYPE_NAME = "http://arkumu.org/data/properties/deutscher-name-des-ereignistyps"

    # Actor/Junction predicates
    ACTOR_LINK = "http://arkumu.org/data/properties/akteurin-im-ereignis"
    ROLE_LINK = "http://arkumu.org/data/properties/rollen-der-akteurin-im-ereignis"
    ACTOR_NAME = "http://arkumu.org/data/properties/deutscher-name"
    ROLE_NAME = "http://arkumu.org/data/properties/deutscher-name-der-rolle-breadcrumb"
    IST_URHEBERIN = "http://arkumu.org/data/properties/ist-urheberin"
    LEISTUNGSSCHUTZRECHTE = "http://arkumu.org/data/properties/besitzt-leistungsschutzrechte"
    IM_EREIGNIS = "http://arkumu.org/data/properties/im-ereignis"
    PROJEKT = "http://arkumu.org/data/properties/projekt"  # KHM junctions link to Grundereignis via this

    # Digital object predicates
    DIGITAL_OBJECT = "http://arkumu.org/data/properties/digitales-objekt"
    FILE_PATH = "http://arkumu.org/data/properties/dateipfad"
    FILE_NAME = "http://arkumu.org/data/properties/dateiname"
    LICENSE = "http://arkumu.org/data/properties/deutscher-name-der-lizenz"

    # Name lookups
    INSTITUTION_NAME = "http://arkumu.org/data/properties/deutscher-name-der-einliefernden-hochschule"
    CATEGORY_NAME = "http://arkumu.org/data/properties/deutscher-name-der-projektkategorie-breadcrumb"
    SCHLAGWORT_LABEL = "http://arkumu.org/data/properties/deutsches-wikidata-label"
    # Schlagwort label (canonical, used by KHM keywords)
    SCHLAGWORT_NAME = "http://arkumu.org/data/properties/deutscher-name-des-schlagworts"


@dataclass
class TripleIndex:
    """Indexed triples for fast lookup."""
    by_subject: Dict[str, List[TripleResult]] = field(default_factory=dict)
    by_predicate: Dict[str, List[TripleResult]] = field(default_factory=dict)
    by_object: Dict[str, List[TripleResult]] = field(default_factory=dict)
    all_subjects: Set[str] = field(default_factory=set)

    @classmethod
    def from_triples(cls, triples: List[TripleResult]) -> "TripleIndex":
        """Build index from list of triples."""
        index = cls()
        for t in triples:
            # Index by subject
            if t.subject_uri:
                index.all_subjects.add(t.subject_uri)
                if t.subject_uri not in index.by_subject:
                    index.by_subject[t.subject_uri] = []
                index.by_subject[t.subject_uri].append(t)

            # Index by predicate (use canonical if available)
            pred = t.predicate_canonical_uri or t.predicate_uri
            if pred:
                if pred not in index.by_predicate:
                    index.by_predicate[pred] = []
                index.by_predicate[pred].append(t)

            # Index by object URI
            if t.object_uri:
                if t.object_uri not in index.by_object:
                    index.by_object[t.object_uri] = []
                index.by_object[t.object_uri].append(t)

        return index


def get_literal(index: TripleIndex, subject: str, predicate: str) -> Optional[str]:
    """Get first literal value for subject+predicate."""
    triples = index.by_subject.get(subject, [])
    for t in triples:
        pred = t.predicate_canonical_uri or t.predicate_uri
        if pred == predicate and t.object_value:
            return t.object_value
    return None


def get_all_literals(index: TripleIndex, subject: str, predicate: str) -> List[str]:
    """Get all literal values for subject+predicate."""
    result = []
    triples = index.by_subject.get(subject, [])
    for t in triples:
        pred = t.predicate_canonical_uri or t.predicate_uri
        if pred == predicate and t.object_value:
            result.append(t.object_value)
    return result


def get_object_uri(index: TripleIndex, subject: str, predicate: str) -> Optional[str]:
    """Get first object URI for subject+predicate."""
    triples = index.by_subject.get(subject, [])
    for t in triples:
        pred = t.predicate_canonical_uri or t.predicate_uri
        if pred == predicate and t.object_uri:
            return t.object_uri
    return None


def get_all_object_uris(index: TripleIndex, subject: str, predicate: str) -> List[str]:
    """Get all object URIs for subject+predicate."""
    result = []
    triples = index.by_subject.get(subject, [])
    for t in triples:
        pred = t.predicate_canonical_uri or t.predicate_uri
        if pred == predicate and t.object_uri:
            result.append(t.object_uri)
    return result


def extract_code_from_uri(uri: str) -> Optional[str]:
    """Extract org code from URI like .../data/hmt/... -> 'hmt'."""
    if not uri:
        return None
    if "/data/" in uri:
        parts = uri.split("/data/")
        if len(parts) > 1:
            code_part = parts[1].split("/")[0]
            if code_part and code_part not in ("properties", "types", "datasets"):
                return code_part.lower()
    return None


def is_truthy(value: Optional[str]) -> bool:
    """Check if value represents true (1, true, yes, ja)."""
    if not value:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "ja"}


def is_junction_uri(uri: str) -> bool:
    """Check if URI represents a junction entity."""
    if not uri:
        return False
    uri_lower = uri.lower()
    return "kreuz" in uri_lower or "junction" in uri_lower


def find_subjects_by_type_pattern(index: TripleIndex, pattern: str) -> List[str]:
    """Find subjects whose URI contains a pattern (e.g., 'ereignis')."""
    result = []
    for subject in index.all_subjects:
        if pattern.lower() in subject.lower():
            result.append(subject)
    return result
