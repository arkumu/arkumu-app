from __future__ import annotations

import base64
import binascii
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from typing import Optional

from django.conf import settings
from django.contrib.auth import authenticate
from django.http import HttpRequest, HttpResponse

from arkumu.oaipmh.constants import (
    DNX_NS,
    METS_NS as DEFAULT_METS_NS,
    METS_SCHEMA_URL as DEFAULT_METS_SCHEMA_URL,
    ROSETTA_METS_NS,
    XLINK_NS,
    XSI_NS,
)
from arkumu.oaipmh.formats.dublin_core import DC_NS, DCTERMS_NS
from arkumu.oaipmh.oai_project import HARVESTABLE_STORAGE_STATUSES

REPO_NAME = "Arkumu Repository"
REPO_BASEURL = "/oai/"
REPO_ADMIN_EMAIL = "mondaca@uni-koeln.de"
REPO_PROTOCOL_VERSION = "2.0"
REPO_EARLIEST_DATASTAMP = "1970-01-01T00:00:00Z"
REPO_DELETED_RECORD = "no"
REPO_GRANULARITY = "YYYY-MM-DDThh:mm:ssZ"
SCHEMA_DESCRIPTION_NS = "http://arkumu.org/oai/schema-info/1.0"
REPO_REPOSITORY_IDENTIFIER = "arkumu"

# Toggle between LOC METS and Rosetta METS namespace for testing
USE_ROSETTA_METS = False  # Set to False for standard LOC METS

METS_NS = ROSETTA_METS_NS if USE_ROSETTA_METS else DEFAULT_METS_NS
OAI_NS = "http://www.openarchives.org/OAI/2.0/"
# Rosetta doesn't have a public schema URL, use local reference
METS_SCHEMA_URL = "rosettaMets.xsd" if USE_ROSETTA_METS else DEFAULT_METS_SCHEMA_URL
XML_NS = "http://www.w3.org/XML/1998/namespace"
SUPPORTED_METADATA_FORMATS = ["oai_dc", "mets"]
METS_PROFILE_VERSION = "ROSETTA-METS" if USE_ROSETTA_METS else "LOC-METS"
METS_SCHEMA_FILE = Path(settings.BASE_DIR) / "arkumu/oaipmh/schema/mets.xsd"
METS_LEGACY_SCHEMA_FILE = METS_SCHEMA_FILE
HARVESTABLE_FILE_STATUSES = HARVESTABLE_STORAGE_STATUSES

EVENT_COPYRIGHT_TYPE_LABEL = "ist/is Urheber:in"
EVENT_NEIGHBOURING_TYPE_LABEL = "ist/is Leistungsschutzinhaber:in"
EVENT_COPYRIGHT_RIGHTS_URIS: tuple[str, ...] = (
    "https://www.gesetze-im-internet.de/urhg/",
    "https://www.gesetze-im-internet.de/englisch_urhg/",
)
EVENT_NEIGHBOURING_RIGHTS_URIS: tuple[str, ...] = (
    "https://www.gesetze-im-internet.de/urhg/BJNR012730965.html#BJNR012730965BJNG001501377",
    "https://www.gesetze-im-internet.de/englisch_urhg/englisch_urhg.html#p0646",
)

METS_NSMAP = {
    'mets': METS_NS,
    'dc': DC_NS,
    'dcterms': DCTERMS_NS,
    'xlink': XLINK_NS,
    'xsi': XSI_NS,
    None: DNX_NS,
}

_DIGITAL_OBJECT_ORG_DEFAULT = ("fuk", "det", "rsh", "khm", "hmt")
_DIGITAL_OBJECT_URI_REGEX = r'/entities/digitales-objekt/[0-9]+$'
_PROJECT_TYPE_URIS: tuple[str, ...] = tuple(
    uri.strip()
    for uri in getattr(settings, "OAI_PROJECT_TYPE_URIS", ())
    if uri and str(uri).strip()
)
_RDF_TYPE_URI = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

SIMPLIFIED_LICENSE_LABEL = "Lizenz arkumu-A 1.0"
SIMPLIFIED_LICENSE_NOTE = (
    "Die Hochschule erwirbt das einfache (nicht-exklusive) zeitlich, räumlich und inhaltlich "
    "unbeschränkte Recht, das Werk oder werkähnliche \"Projekt\" zum Zweck der Langzeitverfügbarkeit "
    "zu vervielfältigen (§16 UrhG), zu speichern und gegebenenfalls in langzeitstabile Dateiformate "
    "zu überführen. Dies umfasst auch das Recht, ein Werk erstmalig zu digitalisieren oder eine digitale "
    "Dokumentation des Werkes zu erstellen. Sofern für Zwecke der Langzeitverfügbarkeit eine Umwandlung "
    "bestehender Dateiformate in andere Dateiformate erforderlich ist und diese Umwandlung eine Bearbeitung "
    "darstellen sollte, werden ebenfalls die für diese Zwecke erforderlichen Bearbeitungsrechte eingeräumt. "
    "Der/die Lizenzgeber:in versichert außerdem, dass alle Personen genannt worden sind, die mit dem/der "
    "Lizenzgeber:in gemeinsam Rechte an dem Werk haben (Miturheber § 8 UrhG oder Urheber verbundener Werke "
    "§ 9 UrhG). Ebenso bestätigt der/die Lizenzgeber:in, dass, wenn Fremdmaterial Dritter in dem Werk oder "
    "\"Projekt\" verwendet wurde, er/sie die Rechte an diesem Material rechtskräftig für die oben genannten "
    "Nutzungen erworben hat."
)

_TAILORED_MIN_DATETIME = datetime(1970, 1, 1, tzinfo=dt_timezone.utc)

_db_assembler_override: ContextVar[Optional[bool]] = ContextVar("oai_db_mode_override", default=None)
_curated_link_override: ContextVar[bool] = ContextVar("oai_curated_link_override", default=False)
_tailored_mode_override: ContextVar[bool] = ContextVar("oai_tailored_mode_override", default=False)


def _db_mode_enabled() -> bool:
    override = _db_assembler_override.get()
    if override is not None:
        return override
    return bool(getattr(settings, "OAI_DB_MODE_ENABLED", False))


@contextmanager
def _force_db_mode(state: bool):
    token = _db_assembler_override.set(state)
    try:
        yield
    finally:
        _db_assembler_override.reset(token)


def _curated_links_enabled() -> bool:
    return bool(_curated_link_override.get() or _db_mode_enabled())


def _curated_media_links_active() -> bool:
    """Return True when curated link ordering should be applied."""
    return bool(_curated_link_override.get() or _tailored_mode_enabled())


@contextmanager
def _force_curated_links(state: bool):
    token = _curated_link_override.set(state)
    try:
        yield
    finally:
        _curated_link_override.reset(token)


def _tailored_mode_enabled() -> bool:
    return bool(_tailored_mode_override.get())


@contextmanager
def _force_tailored_mode(state: bool):
    token = _tailored_mode_override.set(state)
    try:
        yield
    finally:
        _tailored_mode_override.reset(token)


def _decode_basic_credentials(auth_header: str) -> Optional[tuple[str, str]]:
    if not auth_header.startswith("Basic "):
        return None
    encoded = auth_header.split(" ", 1)[1].strip()
    try:
        decoded = base64.b64decode(encoded).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    username, _, password = decoded.partition(":")
    if username and password:
        return username, password
    return None


def _enforce_basic_auth(request: HttpRequest) -> Optional[HttpResponse]:
    """Enforce optional HTTP Basic Auth for the OAI endpoint."""

    if request.META.get("HTTP_X_INTERNAL_OAI_BYPASS") == "1":
        return None

    if not getattr(settings, "OAI_BASIC_AUTH_ENABLED", False):
        return None

    allowed_users = getattr(settings, "OAI_BASIC_AUTH_ALLOWED_USERS", [])
    if not allowed_users:
        return None

    credentials = _decode_basic_credentials(request.META.get("HTTP_AUTHORIZATION", ""))
    if credentials:
        username, password = credentials
        user = authenticate(request=request, username=username, password=password)
        if user is not None and user.is_active and user.username in allowed_users:
            return None

    response = HttpResponse(status=401)
    response["WWW-Authenticate"] = 'Basic realm="Arkumu OAI"'
    return response


__all__ = [
    "REPO_NAME",
    "REPO_BASEURL",
    "REPO_ADMIN_EMAIL",
    "REPO_PROTOCOL_VERSION",
    "REPO_EARLIEST_DATASTAMP",
    "REPO_DELETED_RECORD",
    "REPO_GRANULARITY",
    "SCHEMA_DESCRIPTION_NS",
    "REPO_REPOSITORY_IDENTIFIER",
    "METS_NS",
    "OAI_NS",
    "METS_SCHEMA_URL",
    "XML_NS",
    "SUPPORTED_METADATA_FORMATS",
    "METS_PROFILE_VERSION",
    "METS_SCHEMA_FILE",
    "METS_LEGACY_SCHEMA_FILE",
    "HARVESTABLE_FILE_STATUSES",
    "EVENT_COPYRIGHT_TYPE_LABEL",
    "EVENT_NEIGHBOURING_TYPE_LABEL",
    "EVENT_COPYRIGHT_RIGHTS_URIS",
    "EVENT_NEIGHBOURING_RIGHTS_URIS",
    "METS_NSMAP",
    "_DIGITAL_OBJECT_ORG_DEFAULT",
    "_DIGITAL_OBJECT_URI_REGEX",
    "_PROJECT_TYPE_URIS",
    "_RDF_TYPE_URI",
    "SIMPLIFIED_LICENSE_LABEL",
    "SIMPLIFIED_LICENSE_NOTE",
    "_TAILORED_MIN_DATETIME",
    "_db_mode_enabled",
    "_force_db_mode",
    "_curated_links_enabled",
    "_curated_media_links_active",
    "_force_curated_links",
    "_tailored_mode_enabled",
    "_force_tailored_mode",
    "_decode_basic_credentials",
    "_enforce_basic_auth",
]
