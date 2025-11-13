"""Shared configuration for OAI schema exports."""

from __future__ import annotations

from pathlib import Path

SCHEMA_VARIANTS = {
    "canonical": "canonical-schema",
    "institutional": "institutional-schema",
}

# Map exporter format keys to file extensions, rdflib serializer names, and content types.
SCHEMA_FORMATS = {
    "ttl": {
        "ext": "ttl",
        "serializer": "turtle",
        "content_type": "text/turtle",
    },
    "xml": {
        "ext": "rdf",
        "serializer": "pretty-xml",
        "content_type": "application/rdf+xml",
    },
    "json-ld": {
        "ext": "jsonld",
        "serializer": "json-ld",
        "content_type": "application/ld+json",
    },
    "nt": {
        "ext": "nt",
        "serializer": "nt",
        "content_type": "application/n-triples",
    },
}

DEFAULT_SCHEMA_FORMATS = ("ttl", "xml")

SCHEMA_RELATIVE_DIR = Path("docs") / "schemas"

__all__ = [
    "SCHEMA_VARIANTS",
    "SCHEMA_FORMATS",
    "DEFAULT_SCHEMA_FORMATS",
    "SCHEMA_RELATIVE_DIR",
]
