"""Shared constants for Arkumu OAI-PMH Rosetta METS integration."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings

# Core namespaces
METS_NS = "http://www.loc.gov/METS/"
METS_SCHEMA_URL = "http://www.loc.gov/standards/mets/mets.xsd"
DNX_NS = "http://www.exlibrisgroup.com/dps/dnx"
XLINK_NS = "http://www.w3.org/1999/xlink"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

# Paths to bundled Rosetta schemas
SCHEMA_BASE_PATH = Path(settings.BASE_DIR) / "arkumu/oaipmh/schema"
METS_SCHEMA_PATH = SCHEMA_BASE_PATH / "mets.xsd"
DNX_SCHEMA_PATH = SCHEMA_BASE_PATH / "dnx_sip.xsd"
XLINK_SCHEMA_PATH = SCHEMA_BASE_PATH / "xlink.xsd"

# Expected namespaces on the METS root element following Rosetta example output
REQUIRED_METS_NAMESPACE_MAP = {
    None: DNX_NS,
    "mets": METS_NS,
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "xlink": XLINK_NS,
    "xsi": XSI_NS,
}

__all__ = [
    "DNX_NS",
    "DNX_SCHEMA_PATH",
    "REQUIRED_METS_NAMESPACE_MAP",
    "METS_NS",
    "METS_SCHEMA_PATH",
    "METS_SCHEMA_URL",
    "SCHEMA_BASE_PATH",
    "XLINK_NS",
    "XLINK_SCHEMA_PATH",
    "XSI_NS",
]
