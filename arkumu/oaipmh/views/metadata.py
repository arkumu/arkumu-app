"""Metadata builders for Arkumu OAI-PMH views."""

from __future__ import annotations

import logging
import mimetypes
from datetime import datetime, timezone as dt_timezone
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

from django.http import HttpRequest
from lxml import etree as ET

from arkumu.oaipmh import schema_utils
from arkumu.common.arkumu_license import (
    ARKUMU_LICENSE_LABELS,
    ARKUMU_LICENSE_TEXTS,
    ARKUMU_LICENSE_URIS,
    license_token_from_license_info,
)
from arkumu.common.uri_utils import slugify_uri_part
from arkumu.metadata.models.resource import PublicAccessLevel, Resource
from arkumu.metadata.services.canonical_graph_service import CanonicalGraphService
from arkumu.projects.services.graph_service import get_project_graphs
from arkumu.storage.models.s3_file_objects import S3FileObject
from arkumu.oaipmh.constants import DNX_NS, XLINK_NS, XSI_NS
from arkumu.oaipmh.formats.dublin_core import DC_NS, DCTERMS_NS, OAI_DC_NS
from arkumu.oaipmh.formats.mets_source_metadata import build_rdf_graph, RDF_NS
from arkumu.oaipmh.oai_project import NormalizedDigitalObject, OAIProject
from arkumu.oaipmh.validation import rosetta_mets_validator
from arkumu.projects import (
    ProjectDigitalObject,
    ProjectDigitalObjectLicense,
    ProjectEvent,
    ProjectRecord,
)

from .config import (
    EVENT_COPYRIGHT_RIGHTS_URIS,
    EVENT_COPYRIGHT_TYPE_LABEL,
    EVENT_NEIGHBOURING_RIGHTS_URIS,
    EVENT_NEIGHBOURING_TYPE_LABEL,
    HARVESTABLE_FILE_STATUSES,
    METS_NS,
    METS_NSMAP,
    METS_SCHEMA_URL,
    SIMPLIFIED_LICENSE_LABEL,
    SIMPLIFIED_LICENSE_NOTE,
    XML_NS,
    _curated_media_links_active,
    _db_mode_enabled,
    _tailored_mode_enabled,
)
from .institutional import (
    _build_institutional_rdf_element,
    _normalized_org_code,
    _should_apply_khm_hmt_license_rights,
    _should_emit_institutional_rdf,
    _KHM_HMT_LICENSE_ORGS,
)
from .projects import _candidate_projects_for_resource, get_project_builder

logger = logging.getLogger(__name__)

_RIGHTS_STATUS_PROTECTED_EN = "Protected by German Urheberrecht and/oder Leistungsschutzrecht."
_RIGHTS_STATUS_FREE_EN = "Free of German Urheberrecht and Leistungsschutzrecht protection."
_RIGHTS_DISCLAIMER_PROTECTED_DE = (
    "Die Schutzfrist wird aktuell geprüft. Bis zur Klärung durch die Rechteinhaber:in werden die Projekte nicht öffentlich zugänglich gemacht."
)
_RIGHTS_DISCLAIMER_PROTECTED_EN = (
    "The copyright term is currently being verified. The projects will remain unavailable until resolved by the rights holder."
)
_RIGHTS_DISCLAIMER_FREE_DE = (
    "Die Schutzfrist ist erloschen. Es können möglicherweise Persönlichkeitsrechte, Rechte aus dem Datenschutz, dem Urheber- oder Leistungsschutzrecht betroffen sein."
)
_RIGHTS_DISCLAIMER_FREE_EN = (
    "The copyright term has expired. There might still be applicable personality, data protection, copyright, or neighbouring rights."
)


def _format_datestamp(dt: datetime) -> str:
    """Format datetime as OAI-PMH datestamp."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_fixity_type(label: Optional[str]) -> Optional[str]:
    """Normalize fixity algorithm labels to Rosetta-compatible tokens."""
    if label and label.upper().replace("-", "") == "SHA256":
        return "SHA256"
    return label


def _original_storage_path(obj: NormalizedDigitalObject) -> Optional[str]:
    """Return the Arkumu-managed storage path when available."""
    rosetta_refs = {
        candidate.strip()
        for candidate in (
            *(obj.rosetta_candidates or ()),
            obj.rosetta_path,
        )
        if candidate
    }
    for candidate in (obj.storage_key, obj.original_path):
        if not candidate:
            continue
        normalized = candidate.strip()
        if not normalized:
            continue
        if normalized in rosetta_refs:
            continue
        if normalized.startswith("/rosetta/"):
            continue
        return normalized
    return None

def _metadata_element_is_valid(
    metadata_elem: ET._Element,
    *,
    resource_uri: Optional[str] = None,
) -> bool:
    """Check that a metadata wrapper contains a schema-valid METS payload."""

    result = rosetta_mets_validator.validate_metadata_element(
        metadata_elem,
        resource_uri=resource_uri,
    )
    return result.is_valid
def _metadata_xml_is_valid(
    metadata_xml: str,
    *,
    resource_uri: Optional[str] = None,
) -> bool:
    """Parse and validate cached METS metadata stored as XML text."""

    result = rosetta_mets_validator.validate_metadata_xml(
        metadata_xml,
        resource_uri=resource_uri,
    )
    return result.is_valid
def _register_rosetta_namespaces() -> None:
    """Register namespace prefixes required for Rosetta METS serialization."""
    ET.register_namespace('mets', METS_NS)
    ET.register_namespace('dc', DC_NS)
    ET.register_namespace('dcterms', DCTERMS_NS)
    ET.register_namespace('xlink', XLINK_NS)
    ET.register_namespace('xsi', XSI_NS)
def _create_dnx_element(
    parent: ET._Element,
    tag: str,
    attrib: Optional[Dict[str, str]] = None,
    text: Optional[str] = None,
) -> ET._Element:
    """Create a DNX element that renders without an explicit namespace prefix."""

    # Use the same library as the parent element
    # Check if parent has the lxml-specific nsmap attribute
    elem = ET.SubElement(parent, ET.QName(DNX_NS, tag), attrib or {})

    if text is not None:
        elem.text = str(text)

    return elem
def _infer_representation_type(obj: NormalizedDigitalObject) -> str:
    """Heuristically map digital objects onto Rosetta representation buckets."""
    hint_parts = [
        getattr(obj, 'storage_key', None) or getattr(obj, 'path', None) or '',
        getattr(obj, 'original_path', None) or getattr(obj, 'path', None) or '',
        getattr(obj, 'file_name', None) or '',
        getattr(obj, 'rosetta_path', None) or '',
    ]
    hint = " ".join(hint_parts).lower()

    if any(token in hint for token in ("preservation", "master")):
        return "PRESERVATION_MASTER"

    if any(token in hint for token in ("derivate", "derivative", "modified", "preview", "service")):
        return "MODIFIED_MASTER"

    if any(token in hint for token in ("access", "web", "thumbnail", "delivery")):
        return "MODIFIED_MASTER_02"

    if obj.content_type and obj.content_type.lower() in {"application/pdf", "application/vnd.ms-powerpoint"}:
        return "MODIFIED_MASTER"

    return "PRESERVATION_MASTER"
def _group_digital_objects_for_rosetta(objects: List[NormalizedDigitalObject]) -> List[tuple[str, List[NormalizedDigitalObject]]]:
    """Return preservation master files grouped for Rosetta representations."""

    preservation_objects = [
        obj for obj in objects
        if _infer_representation_type(obj) == "PRESERVATION_MASTER"
    ]

    if preservation_objects:
        return [("PRESERVATION_MASTER", preservation_objects)]

    if objects:
        # Fallback to all objects to avoid emitting an empty representation when heuristics failed.
        return [("PRESERVATION_MASTER", objects)]

    return []
def _build_identifier(resource_uri: str) -> str:
    """Build OAI identifier from resource URI."""
    from urllib.parse import quote
    return f"oai:arkumu:resource:{quote(resource_uri)}"
def _build_record_header(resource: Resource) -> ET._Element:
    """Build OAI record header."""
    header = ET.Element("header")
    ET.SubElement(header, "identifier").text = _build_identifier(resource.uri)
    datestamp_source = getattr(resource, "effective_datestamp", None) or resource.updated_at
    ET.SubElement(header, "datestamp").text = _format_datestamp(datestamp_source)
    if resource.organization:
        ET.SubElement(header, "setSpec").text = resource.organization.code
    return header
def _add_dc_value(
    payload: Dict[str, List[Any]],
    term: str,
    value: Optional[str],
    namespace: str = 'dc',
    attrs: Optional[Dict[ET.QName, str]] = None,
    *,
    allow_duplicates: bool = False,
) -> None:
    if value is None:
        return
    normalized = str(value).strip()
    if not normalized:
        return
    key = f"{namespace}:{term}"
    entries = payload.setdefault(key, [])
    entry = {'value': normalized, 'attrs': attrs or {}} if attrs else normalized

    if not allow_duplicates:
        for existing in entries:
            if isinstance(existing, dict):
                if existing.get('value') == normalized and (existing.get('attrs') or {}) == (attrs or {}):
                    return
            else:
                if not attrs and existing == normalized:
                    return

    entries.append(entry)
def _normalize_reference(value: Optional[str]) -> Optional[str]:
    """Return the reference as-is; S3 keys already encode the desired path."""
    return value
def _escape_flocat_href(value: Optional[str]) -> Optional[str]:
    """Percent-encode square brackets for METS FLocat href values."""
    if not value:
        return value
    text = str(value)
    if not text:
        return text
    return text.replace('[', '%5B').replace(']', '%5D')
def _boolean_token(value: Optional[bool]) -> Optional[str]:
    if value is None:
        return None
    return 'true' if value else 'false'
def _normalize_controlled_identifier(kind: str, token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    token = str(token).strip()
    if not token:
        return None
    if token.startswith('http://') or token.startswith('https://'):
        return token
    if kind == 'wikidata':
        cleaned = token.upper()
        if not cleaned.startswith('Q'):
            cleaned = f"Q{cleaned}"
        return f"https://www.wikidata.org/entity/{cleaned}"
    if kind == 'gnd':
        return f"https://d-nb.info/gnd/{token}"
    if kind == 'aat':
        return f"http://vocab.getty.edu/aat/{token}"
    if kind == 'lido':
        return token
    return token
def _guess_mime_type(obj: Any) -> Optional[str]:
    """Derive a MIME type from explicit metadata or file extension."""
    content_type = getattr(obj, 'content_type', None)
    if content_type:
        return content_type

    candidates = [
        getattr(obj, 'file_name', None),
        getattr(obj, 'access_url', None),
        getattr(obj, 'path', None),
        getattr(obj, 'storage_key', None),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        guess, _ = mimetypes.guess_type(candidate)
        if guess:
            return guess
    return None
def _default_language_for_resource(resource: Resource, record: ProjectRecord) -> Optional[str]:
    """Return a best-effort ISO-639-3 language code for the record."""
    org_code = resource.organization.code.lower() if resource.organization and resource.organization.code else None
    organization_defaults = {
        'fuk': 'deu',
        'khm': 'deu',
        'rsh': 'deu',
        'hmt': 'deu',
        'det': 'deu',
    }
    return organization_defaults.get(org_code)
def _rights_metadata_from_status(status: Optional[str]) -> Optional[Dict[str, Any]]:
    """Return translation and disclaimers derived from a rights status literal."""
    if not status:
        return None

    normalized = status.strip()
    if not normalized:
        return None

    simplified = normalized.lower().replace('ß', 'ss')
    if 'frei' in simplified:
        return {
            "status_de": normalized,
            "status_en": _RIGHTS_STATUS_FREE_EN,
            "disclaimers_de": [_RIGHTS_DISCLAIMER_FREE_DE],
            "disclaimers_en": [_RIGHTS_DISCLAIMER_FREE_EN],
        }
    if 'gesch' in simplified:
        return {
            "status_de": normalized,
            "status_en": _RIGHTS_STATUS_PROTECTED_EN,
            "disclaimers_de": [_RIGHTS_DISCLAIMER_PROTECTED_DE],
            "disclaimers_en": [_RIGHTS_DISCLAIMER_PROTECTED_EN],
        }

    return None
def _rights_link_uris(status: Optional[str]) -> List[str]:
    """Return external rights statement URIs appropriate for a rights status literal."""
    if not status:
        return []

    normalized = status.strip().lower().replace('ß', 'ss')
    if not normalized:
        return []

    links: List[str] = []
    if 'frei' in normalized:
        links.append("http://rightsstatements.org/vocab/NoC-OKLR/1.0/")

    if 'gesch' in normalized or 'schutz' in normalized:
        links.extend([
            "https://www.gesetze-im-internet.de/urhg/",
            "https://www.gesetze-im-internet.de/englisch_urhg/",
        ])

    # Preserve order but remove duplicates
    deduped: Dict[str, None] = {}
    for link in links:
        if link and link not in deduped:
            deduped[link] = None
    return list(deduped.keys())
def _rights_label_for_resource(resource: Resource) -> Optional[str]:
    """Translate public access configuration to a human readable rights statement."""
    mapping = {
        PublicAccessLevel.PUBLIC: "Open Access",
        PublicAccessLevel.RESTRICTED: "Restricted Access",
        PublicAccessLevel.PRIVATE: "Internal Access Only",
    }
    level = getattr(resource, 'public_access_level', None)
    if not level:
        return None
    return mapping.get(level)
def _default_rights_metadata(resource: Resource, record: ProjectRecord) -> Optional[Dict[str, Any]]:
    """Provide organization-specific fallback rights metadata when literals are absent."""
    org_code = (resource.organization.code or "").lower().strip() if resource.organization and resource.organization.code else None

    if org_code in {"khm", "hmt"}:
        status_literal = getattr(record, "rights_status", None) or "Urheberrechtlich und/oder Leistungsschutzrechtlich geschützt"
        return {
            "status_de": status_literal,
            "status_en": _RIGHTS_STATUS_PROTECTED_EN,
            "disclaimers_de": [_RIGHTS_DISCLAIMER_PROTECTED_DE],
            "disclaimers_en": [_RIGHTS_DISCLAIMER_PROTECTED_EN],
        }

    return None
def _collect_collection_labels(resource: Resource, record: ProjectRecord) -> List[str]:
    """Return descriptive collection strings suitable for dc:collection."""
    labels: List[str] = []
    if record.institution and record.institution.label:
        labels.append(record.institution.label)
    if record.institution_codes:
        labels.extend(code.upper() for code in record.institution_codes if code)
    org = getattr(resource, 'organization', None)
    if org:
        if org.name and org.name not in labels:
            labels.append(org.name)
        display_name = org.get_organization_type_display_name()
        if display_name and display_name not in labels:
            labels.append(display_name)
    return labels
def _select_primary_event_actors(record: ProjectRecord) -> List[Dict[str, Any]]:
    """Pick the actor records that should surface as creators/contributors."""

    grund_events = [
        event
        for event in record.events
        if (
            (getattr(event, "uri", None) and "/01-grundereignis/" in event.uri)
            or (getattr(event, "type", None) and "herstellung" in str(event.type).lower())
            or (getattr(event, "name", None) and "herstellung" in str(event.name).lower())
        )
    ]

    selected: List[Dict[str, Any]] = []
    seen_names: set[str] = set()

    for event in grund_events:
        for actor in getattr(event, "actors", []) or []:
            name = getattr(actor, "name", None) if not isinstance(actor, dict) else actor.get("name")
            if name and name in seen_names:
                continue
            actor_dict = {
                "name": name,
                "roles": list(getattr(actor, "roles", []) or []) if not isinstance(actor, dict) else actor.get("roles", []),
            }
            selected.append(actor_dict)
            if name:
                seen_names.add(name)

    if selected:
        return selected

    fallback: List[Dict[str, Any]] = []
    for actor in record.actors:
        name = getattr(actor, "name", None)
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        fallback.append(
            {
                "name": name,
                "roles": list(getattr(actor, "roles", []) or []),
            }
        )

    return fallback


def _extract_creators_from_junctions(resource: Resource, record: ProjectRecord) -> tuple[list, list]:
    """Extract creators and contributors from junction entities.

    Queries junction entities (Kreuztabelle) to find actor-event relationships:
    - dc:creator: actors where ist-urheberin=1 (copyright holders)
    - dc:contributor: actors where ist-urheberin=0

    Uses canonical predicate URIs to find relationships across all institutions.
    Format: "Actor Name (Role)" or just "Actor Name" if no role.
    """
    from arkumu.metadata.models.triples import Triple
    from django.db.models import Q

    creators = []
    contributors = []

    if not resource or not resource.id:
        return creators, contributors

    org_code = resource.organization.code if resource.organization else None

    # Canonical URIs for predicates and types
    CANONICAL_JUNCTION_TYPE = "http://arkumu.org/data/types/akteurin-ereignis-kreuztabelle"
    CANONICAL_PROJECT_PREDICATE = "http://arkumu.org/data/properties/projekt"
    CANONICAL_EVENT_PREDICATE = "http://arkumu.org/data/properties/ereignis"
    CANONICAL_ACTOR_PREDICATE = "http://arkumu.org/data/properties/akteurin-im-ereignis"
    CANONICAL_IST_URHEBERIN = "http://arkumu.org/data/properties/ist-urheberin"
    CANONICAL_LEISTUNGSSCHUTZ = "http://arkumu.org/data/properties/besitzt-leistungsschutzrechte"
    CANONICAL_ROLE_PREDICATE = "http://arkumu.org/data/properties/akteurin-hat-rolle"
    RDF_TYPE_URI = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

    # Get event IDs from the record's events
    event_uris = []
    for event in record.events:
        uri = getattr(event, "uri", None)
        if uri:
            event_uris.append(uri)

    # Find event resource IDs
    from arkumu.metadata.models.resource import Resource as ResourceModel
    event_ids = []
    if event_uris:
        event_resources = ResourceModel.objects.filter(uri__in=event_uris).values_list("id", flat=True)
        event_ids = list(event_resources)

    # Find event entities that link to this project via canonical "projekt" predicate
    # This covers KHM grundereignis and HMT hfm-ereignis through their canonical mappings
    linked_event_ids = []
    if resource.id:
        linked_events_qs = Triple.objects.filter(
            Q(predicate__canonical_uri=CANONICAL_PROJECT_PREDICATE)
            | Q(predicate__uri=CANONICAL_PROJECT_PREDICATE),
            object_id=resource.id,
        ).values_list("subject_id", flat=True).distinct()[:20]
        linked_event_ids = list(linked_events_qs)

    if not event_ids and not resource.id and not linked_event_ids:
        return creators, contributors

    org_filter = Q()
    if org_code:
        org_filter = Q(subject__organization__code=org_code)

    try:
        # Find junction entities by canonical type
        junction_type_subjects = (
            Triple.objects.filter(
                Q(predicate__uri=RDF_TYPE_URI)
                & (
                    Q(object__canonical_uri=CANONICAL_JUNCTION_TYPE)
                    | Q(object__uri=CANONICAL_JUNCTION_TYPE)
                )
            )
            .filter(org_filter)
            .values_list("subject_id", flat=True)
        )

        # Find junctions pointing to our events, linked events, or the project
        # Using canonical predicates: projekt, ereignis
        target_ids = list(event_ids)
        target_ids.extend(linked_event_ids)
        if resource.id:
            target_ids.append(resource.id)

        junction_ids = list(
            Triple.objects.filter(
                subject_id__in=junction_type_subjects,
                object_id__in=target_ids,
            )
            .values_list("subject_id", flat=True)
            .distinct()[:50]
        )
    except Exception:
        return creators, contributors

    if not junction_ids:
        return creators, contributors

    # Fetch junction triples
    junction_triples = Triple.objects.filter(
        subject_id__in=junction_ids
    ).select_related("predicate", "object").only(
        "subject_id",
        "predicate__uri",
        "predicate__canonical_uri",
        "object__id",
        "object__uri",
        "object__value",
        "object__name",
    )

    # Group by junction entity
    junction_data: Dict[str, Dict[str, Any]] = {}
    for t in junction_triples:
        jid = str(t.subject_id)
        if jid not in junction_data:
            junction_data[jid] = {"ist_urheberin": False, "leistungsschutz": False, "actor_id": None, "role_id": None}

        # Use canonical URI if available, otherwise fall back to direct URI
        pred_uri = t.predicate.canonical_uri or t.predicate.uri or ""
        pred_canonical = t.predicate.canonical_uri or ""

        # Check ist-urheberin via canonical URI
        if pred_canonical == CANONICAL_IST_URHEBERIN or "ist-urheberin" in pred_uri:
            val = t.object.value if hasattr(t.object, "value") else None
            junction_data[jid]["ist_urheberin"] = val in ("1", "true", True, 1)
        # Check leistungsschutz via canonical URI
        elif pred_canonical == CANONICAL_LEISTUNGSSCHUTZ or "leistungsschutz" in pred_uri:
            val = t.object.value if hasattr(t.object, "value") else None
            junction_data[jid]["leistungsschutz"] = val in ("1", "true", True, 1)
        # Check actor link via canonical URI (akteurin-im-ereignis)
        elif pred_canonical == CANONICAL_ACTOR_PREDICATE or "akteurin-im-ereignis" in pred_uri:
            # Object should be an actor/person entity
            obj_uri = (t.object.uri or "").lower()
            if obj_uri and t.object.id:
                junction_data[jid]["actor_id"] = str(t.object.id)
        # Check role link via canonical URI
        elif pred_canonical == CANONICAL_ROLE_PREDICATE or "akteurin-hat-rolle" in pred_uri:
            if t.object.uri and "/rolle" in t.object.uri.lower():
                junction_data[jid]["role_id"] = str(t.object.id)

    # Canonical name predicate
    CANONICAL_NAME_PREDICATE = "http://arkumu.org/data/properties/deutscher-name"

    # Fetch actor names via canonical deutscher-name predicate
    actor_ids = [d["actor_id"] for d in junction_data.values() if d.get("actor_id")]
    actor_names = {}
    if actor_ids:
        # Query triples using canonical predicate (covers all institution-specific mappings)
        name_triples = Triple.objects.filter(
            Q(subject_id__in=actor_ids)
            & (
                Q(predicate__canonical_uri=CANONICAL_NAME_PREDICATE)
                | Q(predicate__uri=CANONICAL_NAME_PREDICATE)
            )
        ).select_related("object").only("subject_id", "object__value")
        for t in name_triples:
            if t.object.value:
                actor_names[str(t.subject_id)] = t.object.value

    # Fetch role names via canonical deutscher-name predicate
    role_ids = [d["role_id"] for d in junction_data.values() if d.get("role_id")]
    role_names = {}
    if role_ids:
        role_triples = Triple.objects.filter(
            Q(subject_id__in=role_ids)
            & (
                Q(predicate__canonical_uri=CANONICAL_NAME_PREDICATE)
                | Q(predicate__uri=CANONICAL_NAME_PREDICATE)
            )
        ).select_related("object").only("subject_id", "object__value")
        for t in role_triples:
            if t.object.value:
                role_names[str(t.subject_id)] = t.object.value

    # Institution filter
    institution_keywords = [
        "universität", "hochschule", "akademie", "institut", "university",
        "college", "school", "academy", "institute", "stiftung", "foundation",
    ]

    def is_institution(name: str) -> bool:
        name_lower = name.lower()
        return any(kw in name_lower for kw in institution_keywords)

    # Build creator/contributor lists
    seen = set()
    for jdata in junction_data.values():
        actor_id = jdata.get("actor_id")
        if not actor_id or actor_id in seen:
            continue
        seen.add(actor_id)

        actor_name = actor_names.get(actor_id)
        if not actor_name:
            continue  # Skip if no name found
        if is_institution(actor_name):
            continue

        role_id = jdata.get("role_id")
        role_name = role_names.get(role_id) if role_id else None
        if role_name:
            formatted = f"{actor_name} ({role_name})"
        else:
            formatted = actor_name

        # Creator if ist-urheberin=1 OR besitzt-leistungsschutzrechte=1
        if jdata.get("ist_urheberin") or jdata.get("leistungsschutz"):
            creators.append(formatted)
        else:
            contributors.append(formatted)

    return creators, contributors


def _build_dc_payload_from_project(
    project: OAIProject,
    resource: Resource,
    *,
    include_event_details: bool = True,
    force_live_dc: bool = False,
) -> Dict[str, List[str]]:
    payload: Dict[str, List[str]] = {}

    record = project.record
    project_uri = getattr(resource, "uri", None)
    if project_uri:
        _add_dc_value(
            payload,
            'identifier',
            project_uri,
        )

    _add_dc_value(payload, 'title', record.title)

    _add_dc_value(payload, 'description', record.description)

    if record.institution and record.institution.label:
        _add_dc_value(payload, 'publisher', record.institution.label)

    # Try to use pre-computed DC metadata from ProjectIndex for better performance
    # Skip precomputed if force_live_dc is True (for GetRecord previews)
    project_index = getattr(resource, "project_index", None) if not force_live_dc else None
    precomputed_creators = getattr(project_index, "dc_creators", None) if project_index else None
    precomputed_contributors = getattr(project_index, "dc_contributors", None) if project_index else None

    if precomputed_creators or precomputed_contributors:
        # Use pre-computed values from ProjectIndex
        for creator in (precomputed_creators or []):
            _add_dc_value(payload, 'creator', creator)
        for contributor in (precomputed_contributors or []):
            _add_dc_value(payload, 'contributor', contributor)
    else:
        # Extract from ProjectRecord (same logic as precomputed)
        from arkumu.catalog.services.project_index_db_service import _extract_dc_metadata_from_record
        dc_meta = _extract_dc_metadata_from_record(record)
        for creator in dc_meta.creators:
            _add_dc_value(payload, 'creator', creator)
        for contributor in dc_meta.contributors:
            _add_dc_value(payload, 'contributor', contributor)

    if record.project_type and record.project_type.label:
        _add_dc_value(payload, 'type', record.project_type.label)

    for category in record.categories:
        _add_dc_value(payload, 'subject', getattr(category, 'label', None))

    for catchphrase in record.catchphrases:
        _add_dc_value(payload, 'subject', getattr(catchphrase, 'label', None))

    if include_event_details:
        _merge_event_payloads(payload, _build_event_dc_payloads(record))

    if record.year_range:
        _add_dc_value(payload, 'date', record.year_range)

    rights_meta = _rights_metadata_from_status(getattr(record, "rights_status", None))

    if getattr(resource, 'updated_at', None):
        _add_dc_value(payload, 'dateSubmitted', _format_datestamp(resource.updated_at), namespace='dcterms')

    for code in record.institution_codes:
        _add_dc_value(payload, 'isPartOf', code.upper(), namespace='dcterms')
    for label in _collect_collection_labels(resource, record):
        _add_dc_value(payload, 'isPartOf', label, namespace='dcterms')

    if project.digital_objects:
        formats_added: set[str] = set(payload.get('dc:format', []))
        for obj in project.digital_objects:
            if obj.content_type:
                if obj.content_type not in formats_added:
                    _add_dc_value(payload, 'format', obj.content_type)
                    formats_added.add(obj.content_type)

        if not payload.get('dc:format'):
            for obj in project.digital_objects:
                guess = _guess_mime_type(obj)
                if guess and guess not in formats_added:
                    _add_dc_value(payload, 'format', guess)
                    formats_added.add(guess)

    if not payload.get('dc:language'):
        language = _default_language_for_resource(resource, record)
        if language:
            _add_dc_value(payload, 'language', language)

    apply_khm_licensing = _should_apply_khm_hmt_license_rights(resource, project)
    arkumu_tokens: set[str] = set()
    fallback_rights: set[str] = set()

    def _scan_license(license_obj: Optional[Any]) -> None:
        if not license_obj:
            return
        token = license_token_from_license_info(license_obj)
        if token and token in ARKUMU_LICENSE_LABELS:
            arkumu_tokens.add(token)
            return
        candidates = [
            getattr(license_obj, "rights_statement", None),
            getattr(license_obj, "label_de", None),
            getattr(license_obj, "label_en", None),
        ]
        for candidate in candidates:
            if candidate is None:
                continue
            normalized = str(candidate).strip()
            if not normalized:
                continue
            if apply_khm_licensing and normalized in {"1", "2"}:
                continue
            fallback_rights.add(normalized)

    for obj in project.digital_objects:
        _scan_license(getattr(obj, "license", None))

    if getattr(record, "digital_objects", None):
        for raw_obj in record.digital_objects:
            _scan_license(getattr(raw_obj, "license", None))

    if "1" in ARKUMU_LICENSE_LABELS:
        arkumu_tokens = {"1"}
    else:
        arkumu_tokens.clear()

    canonical_values: set[str] = set()
    for token in sorted(arkumu_tokens):
        label = ARKUMU_LICENSE_LABELS[token]
        text = ARKUMU_LICENSE_TEXTS[token]
        _add_dc_value(payload, 'rights', label, allow_duplicates=True)
        _add_dc_value(payload, 'rights', text, allow_duplicates=True)
        canonical_values.update({label, text})

    if arkumu_tokens:
        fallback_rights.clear()
    else:
        fallback_rights.difference_update(canonical_values)
        for rights_value in sorted(fallback_rights):
            _add_dc_value(payload, 'rights', rights_value)

    if not arkumu_tokens:
        if not rights_meta:
            rights_meta = _default_rights_metadata(resource, record)

        if rights_meta:
            _add_dc_value(payload, 'rights', rights_meta.get("status_de"))
            _add_dc_value(payload, 'rights', rights_meta.get("status_en"))
            for text in rights_meta.get("disclaimers_de", []):
                _add_dc_value(payload, 'rights', text)
            for text in rights_meta.get("disclaimers_en", []):
                _add_dc_value(payload, 'rights', text)
        elif not payload.get('dc:rights'):
            rights = _rights_label_for_resource(resource)
            if rights:
                _add_dc_value(payload, 'rights', rights)

    return payload
def _merge_event_payloads(base_payload: Dict[str, List[Any]], event_payloads: List[Dict[str, List[Any]]]) -> None:
    for event_payload in event_payloads:
        for key, values in event_payload.items():
            base_payload.setdefault(key, []).extend(values)
def _build_event_dc_payloads(record: ProjectRecord) -> List[Dict[str, List[Any]]]:
    event_payloads: List[Dict[str, List[Any]]] = []
    xml_type_attr = ET.QName(XML_NS, "type")
    xml_lang_attr = ET.QName(XML_NS, "lang")

    for event in record.events:
        if getattr(event, "is_reference_only", False):
            continue
        payload: Dict[str, List[Any]] = {}
        event_name_de = getattr(event, 'name_de', None) or getattr(event, 'name', None)
        if event_name_de:
            _add_dc_value(
                payload,
                'title',
                event_name_de,
                attrs={xml_type_attr: 'event-name', xml_lang_attr: 'ger'},
            )

        event_identifier = getattr(event, 'uri', None) or getattr(event, 'id', None)
        if event_identifier:
            _add_dc_value(
                payload,
                'identifier',
                str(event_identifier),
                attrs={xml_type_attr: 'event-id'},
            )

        event_name_en = getattr(event, 'name_en', None)
        if event_name_en:
            _add_dc_value(
                payload,
                'title',
                event_name_en,
                attrs={xml_type_attr: 'event-name', xml_lang_attr: 'eng'},
            )

        event_type_de = getattr(event, 'type_label_de', None) or getattr(event, 'type', None)
        if event_type_de:
            _add_dc_value(
                payload,
                'type',
                event_type_de,
                attrs={xml_type_attr: 'event-type', xml_lang_attr: 'ger'},
            )

        event_type_en = getattr(event, 'type_label_en', None)
        if event_type_en:
            _add_dc_value(
                payload,
                'type',
                event_type_en,
                attrs={xml_type_attr: 'event-type', xml_lang_attr: 'eng'},
            )

        for synonym in getattr(event, 'type_synonyms_de', []) or []:
            _add_dc_value(
                payload,
                'type',
                synonym,
                attrs={xml_type_attr: 'event-type-synonym', xml_lang_attr: 'ger'},
            )

        for synonym in getattr(event, 'type_synonyms_en', []) or []:
            _add_dc_value(
                payload,
                'type',
                synonym,
                attrs={xml_type_attr: 'event-type-synonym', xml_lang_attr: 'eng'},
            )

        wikidata_uri = _normalize_controlled_identifier('wikidata', getattr(event, 'type_wikidata_id', None))
        if wikidata_uri:
            _add_dc_value(payload, 'type', wikidata_uri, attrs={xml_type_attr: 'dcterms:URI'})

        gnd_uri = _normalize_controlled_identifier('gnd', getattr(event, 'type_gnd_id', None))
        if gnd_uri:
            _add_dc_value(payload, 'type', gnd_uri, attrs={xml_type_attr: 'dcterms:URI'})

        aat_uri = _normalize_controlled_identifier('aat', getattr(event, 'type_aat_id', None))
        if aat_uri:
            _add_dc_value(payload, 'type', aat_uri, attrs={xml_type_attr: 'dcterms:URI'})

        lido_uri = _normalize_controlled_identifier('lido', getattr(event, 'type_lido_id', None))
        if lido_uri:
            _add_dc_value(payload, 'type', lido_uri, attrs={xml_type_attr: 'dcterms:URI'})

        if event.start:
            _add_dc_value(payload, 'date', event.start, attrs={xml_type_attr: 'event-begin'})
        if event.end and event.end != event.start:
            _add_dc_value(payload, 'date', event.end, attrs={xml_type_attr: 'event-end'})

        start_estimated = _boolean_token(getattr(event, 'start_estimated', None))
        if start_estimated is not None:
            _add_dc_value(payload, 'date', start_estimated, attrs={xml_type_attr: 'event-begin-estimated'})

        end_estimated = _boolean_token(getattr(event, 'end_estimated', None))
        if end_estimated is not None:
            _add_dc_value(payload, 'date', end_estimated, attrs={xml_type_attr: 'event-end-estimated'})

        if event.location:
            _add_dc_value(payload, 'coverage', event.location)
        if event.country:
            _add_dc_value(payload, 'coverage', event.country)

        actor_list = getattr(event, 'actors', []) or []
        has_copyright_actor = any(getattr(actor, 'is_copyright_holder', False) for actor in actor_list)
        has_neighbouring_actor = any(getattr(actor, 'is_neighbouring_rights_holder', False) for actor in actor_list)

        for actor in actor_list:
            actor_name = getattr(actor, 'name', None)
            if not actor_name:
                continue
            roles = [role for role in getattr(actor, 'roles', []) or [] if role]
            if roles:
                role_label = ", ".join(sorted(set(roles)))
                contributor_value = f"{actor_name} ({role_label})"
            else:
                contributor_value = actor_name
            _add_dc_value(
                payload,
                'contributor',
                contributor_value,
                attrs={xml_type_attr: 'actor'},
            )

        if has_copyright_actor:
            _add_dc_value(payload, 'type', EVENT_COPYRIGHT_TYPE_LABEL, attrs={xml_type_attr: 'actor-rights-type'})
            for uri in EVENT_COPYRIGHT_RIGHTS_URIS:
                _add_dc_value(payload, 'rights', uri, attrs={xml_type_attr: 'dcterms:URI'})

        if has_neighbouring_actor:
            _add_dc_value(payload, 'type', EVENT_NEIGHBOURING_TYPE_LABEL, attrs={xml_type_attr: 'actor-rights-type'})
            for uri in EVENT_NEIGHBOURING_RIGHTS_URIS:
                _add_dc_value(payload, 'rights', uri, attrs={xml_type_attr: 'dcterms:URI'})

        event_payloads.append(payload)

    return event_payloads
def _build_dc_payload_from_record(
    record: ProjectRecord,
    resource: Resource,
    *,
    include_event_details: bool = True,
) -> Dict[str, List[str]]:
    """Compatibility wrapper to build DC payloads from legacy ProjectRecord inputs."""

    builder = get_project_builder()
    project = builder.from_project_record(
        record,
        skip_shared_event_filter=_db_mode_enabled(),
        skip_format_exclusion=_db_mode_enabled(),
        use_curated_media_links=_curated_media_links_active(),
    )
    return _build_dc_payload_from_project(
        project,
        resource,
        include_event_details=include_event_details,
    )
def _iter_dc_entries(dc_payload: Dict[str, List[Any]]) -> Iterable[tuple[str, str, Any, Dict[Any, Any]]]:
    """Yield namespace URI, term, value, and attribute map for each DC payload entry."""
    for key, values in (dc_payload or {}).items():
        namespace, term = key.split(":", 1)
        ns_uri = DC_NS if namespace == "dc" else DCTERMS_NS
        for item in values:
            if isinstance(item, dict):
                text = item.get("value")
                attrs = item.get("attrs") or {}
            else:
                text = item
                attrs = {}
            if text is None:
                continue
            yield ns_uri, term, text, attrs
def _append_dc_metadata(metadata: ET._Element, dc_payload: Dict[str, List[str]]) -> ET._Element:
    dc_root = ET.SubElement(
        metadata,
        ET.QName(OAI_DC_NS, "dc"),
        nsmap={
            "oai_dc": OAI_DC_NS,
            "dc": DC_NS,
            "dcterms": DCTERMS_NS,
            "xsi": XSI_NS,
        },
    )
    dc_root.set(
        ET.QName(XSI_NS, "schemaLocation"),
        " ".join([
            OAI_DC_NS,
            "http://www.openarchives.org/OAI/2.0/oai_dc.xsd",
        ]),
    )

    for ns_uri, term, text, attrs in _iter_dc_entries(dc_payload):
        elem = ET.SubElement(dc_root, ET.QName(ns_uri, term))
        elem.text = text
        for attr_name, attr_value in attrs.items():
            if attr_value is None:
                continue
            elem.set(attr_name, attr_value)
    return dc_root
def _append_arkumu_identifier(dc_parent: ET._Element, resource: Resource) -> None:
    """Append Arkumu-specific DC identifier based on project URI."""
    identifier_value = getattr(resource, "uri", None)
    if not identifier_value:
        return
    existing = [
        elem for elem in dc_parent.findall(ET.QName(DC_NS, "identifier"))
        if elem.text == identifier_value
    ]
    if existing:
        return

    identifier_elem = ET.Element(ET.QName(DC_NS, "identifier"))
    identifier_elem.text = identifier_value
    dc_parent.insert(0, identifier_elem)
def _build_simplified_mets_from_project(
    project: OAIProject,
    resource: Resource,
    *,
    request: Optional[HttpRequest] = None,
    force_live_rdf: bool = False,
) -> ET._Element:
    """Emit the pared-down METS variant used exclusively by the DB endpoint.

    Args:
        force_live_rdf: If True, always fetch RDF on-demand (skip precomputed ProjectIndex).
                       Use for GetRecord previews; False for ListRecords harvesting.
    """
    import time as _time
    _t0 = _time.perf_counter()

    _register_rosetta_namespaces()

    record = project.record
    _t_dc0 = _time.perf_counter()
    dc_payload = _build_dc_payload_from_project(
        project,
        resource,
        include_event_details=False,
        force_live_dc=force_live_rdf,
    )
    _t_dc1 = _time.perf_counter()
    logger.info("DC payload build took %.3fs", _t_dc1 - _t_dc0)
    reference_parent = None
    for candidate in getattr(record, "reference_project_uris", []) or []:
        if candidate:
            reference_parent = candidate
            break
    if reference_parent:
        _add_dc_value(dc_payload, 'isPartOf', reference_parent, namespace='dcterms')
    mets_root = ET.Element(ET.QName(METS_NS, "mets"), nsmap=METS_NSMAP)
    # Note: OBJID and xsi:schemaLocation removed per Rosetta example

    # Note: metsHdr removed per Rosetta requirements

    dmd_sec = ET.SubElement(mets_root, ET.QName(METS_NS, "dmdSec"), {"ID": "ie-dmd"})
    md_wrap = ET.SubElement(dmd_sec, ET.QName(METS_NS, "mdWrap"), {"MDTYPE": "DC"})
    xml_data = ET.SubElement(md_wrap, ET.QName(METS_NS, "xmlData"))
    dc_record = ET.SubElement(xml_data, ET.QName(DC_NS, "record"))

    identifier_value = getattr(resource, "uri", None) or getattr(record, "uri", None)
    publisher_value = None
    if getattr(record, "institution", None) and getattr(record.institution, "label", None):
        publisher_value = record.institution.label
    elif getattr(resource, "organization", None) and getattr(resource.organization, "name", None):
        publisher_value = resource.organization.name

    if identifier_value:
        _add_dc_value(dc_payload, 'identifier', identifier_value)

    if publisher_value:
        _add_dc_value(dc_payload, 'publisher', publisher_value)

    allowed_terms = {"identifier", "title", "creator", "contributor", "publisher", "isPartOf"}
    emitted_is_part_of = False
    for ns_uri, term, text, attrs in _iter_dc_entries(dc_payload):
        if term not in allowed_terms:
            continue
        if term == "isPartOf":
            if reference_parent:
                if text != reference_parent:
                    continue
            if emitted_is_part_of:
                continue
            emitted_is_part_of = True
        elem = ET.SubElement(dc_record, ET.QName(ns_uri, term))
        elem.text = text
        for attr_name, attr_value in attrs.items():
            if attr_value is None:
                continue
            elem.set(attr_name, attr_value)

    # Add hardcoded Arkumu license rights for simplified METS
    rights_elem = ET.SubElement(dc_record, ET.QName(DC_NS, "rights"))
    rights_elem.text = SIMPLIFIED_LICENSE_LABEL

    rights_elem = ET.SubElement(dc_record, ET.QName(DC_NS, "rights"))
    rights_elem.text = SIMPLIFIED_LICENSE_NOTE

    ie_amd = ET.SubElement(mets_root, ET.QName(METS_NS, "amdSec"), {"ID": "ie-amd"})
    tech_md = ET.SubElement(ie_amd, ET.QName(METS_NS, "techMD"), {"ID": "ie-amd-tech"})
    tech_wrap = ET.SubElement(tech_md, ET.QName(METS_NS, "mdWrap"), {"MDTYPE": "OTHER", "OTHERMDTYPE": "dnx"})
    tech_xml = ET.SubElement(tech_wrap, ET.QName(METS_NS, "xmlData"))
    tech_dnx = _create_dnx_element(tech_xml, "dnx")
    general_section = _create_dnx_element(tech_dnx, "section", {"id": "generalRepCharacteristics"})
    general_record = _create_dnx_element(general_section, "record")
    _create_dnx_element(general_record, "key", {"id": "usageType"}, "VIEW")
    # Note: accessRightsPolicy removed - Rosetta creates them automatically

    rights_md = ET.SubElement(ie_amd, ET.QName(METS_NS, "rightsMD"), {"ID": "ie-amd-rights"})
    rights_wrap = ET.SubElement(
        rights_md,
        ET.QName(METS_NS, "mdWrap"),
        {"MDTYPE": "OTHER", "OTHERMDTYPE": "dnx"},
    )
    rights_xml = ET.SubElement(rights_wrap, ET.QName(METS_NS, "xmlData"))
    rights_dnx = _create_dnx_element(rights_xml, "dnx")
    granted_section = _create_dnx_element(rights_dnx, "section", {"id": "grantedRightsStatement"})
    granted_record = _create_dnx_element(granted_section, "record")
    _create_dnx_element(
        granted_record,
        "key",
        {"id": "grantedRightsStatementValue"},
        SIMPLIFIED_LICENSE_NOTE,
    )

    schema_href_map = schema_utils.build_schema_href_map(request=request)

    def _append_rdf_md(
        md_id: str,
        other_type: str,
        rdf_elem: ET._Element,
        schema_href: Optional[str] = None,
    ) -> None:
        source_md = ET.SubElement(ie_amd, ET.QName(METS_NS, "sourceMD"), {"ID": md_id})
        source_wrap = ET.SubElement(
            source_md,
            ET.QName(METS_NS, "mdWrap"),
            {
                "MDTYPE": "OTHER",
                "OTHERMDTYPE": other_type,
            },
        )
        source_xml = ET.SubElement(source_wrap, ET.QName(METS_NS, "xmlData"))
        if schema_href:
            rdf_elem.set(
                ET.QName(XSI_NS, "schemaLocation"),
                f"{RDF_NS} {schema_href}",
            )
        source_xml.append(rdf_elem)

    # Try to use pre-computed RDF/XML from ProjectIndex for better performance
    # Skip precomputed if force_live_rdf is True (for GetRecord previews)
    project_index = getattr(resource, "project_index", None) if not force_live_rdf else None
    precomputed_canonical = getattr(project_index, "canonical_rdf_xml", "") if project_index else ""
    precomputed_institutional = getattr(project_index, "institutional_rdf_xml", "") if project_index else ""

    # Also check for batch-fetched graph_data on the project (from tailored endpoint)
    # Skip prefetched if force_live_rdf is True
    prefetched_graph = getattr(project, "graph_data", None) if not force_live_rdf else None

    _t1 = _time.perf_counter()

    # Fetch graph data once, reuse for both canonical and institutional RDF
    project_graphs = None
    if not precomputed_canonical or not precomputed_institutional:
        org_code = resource.organization.code if resource.organization else None
        if org_code:
            project_graphs = get_project_graphs(str(resource.id), org_code)

    try:
        if precomputed_canonical:
            canonical_rdf = ET.fromstring(precomputed_canonical.encode("utf-8"))
        elif prefetched_graph:
            canonical_rdf = build_rdf_graph(resource, graph_data=prefetched_graph)
        elif project_graphs:
            graph_data = project_graphs.to_graph_data()
            canonical_rdf = build_rdf_graph(resource, graph_data=graph_data)
        else:
            raise ValueError("No graph data available for canonical RDF")
        _append_rdf_md(
            "simplified-rdf-canonical",
            "RDF",
            canonical_rdf,
            schema_href=schema_href_map.get("canonical"),
        )
    except Exception:
        logger.exception("Failed to build canonical RDF metadata for %s", getattr(resource, "uri", "unknown"))

    try:
        if precomputed_institutional:
            institutional_rdf = ET.fromstring(precomputed_institutional.encode("utf-8"))
        elif project_graphs:
            graph_data = project_graphs.to_graph_data()
            institutional_rdf = build_rdf_graph(resource, graph_data=graph_data, use_institutional_predicates=True)
        else:
            raise ValueError("No graph data available for institutional RDF")
    except Exception:
        logger.exception("Failed to build institutional RDF for %s", getattr(resource, "uri", "unknown"))
        institutional_rdf = None

    if institutional_rdf is not None:
        _append_rdf_md(
            "simplified-rdf-institutional",
            "RDF-INSTITUTIONAL",
            institutional_rdf,
            schema_href=schema_href_map.get("institutional"),
        )
    else:
        logger.info(
            "Simplified METS could not build institutional RDF for %s",
            getattr(resource, "uri", "unknown"),
        )

    _t2 = _time.perf_counter()

    harvestable_objects = [
        obj for obj in project.digital_objects
        if obj.harvestable and obj.preferred_location
    ]

    # Add representation amdSec with preservationType (Rosetta requirement)
    rep_amd = ET.SubElement(mets_root, ET.QName(METS_NS, "amdSec"), {"ID": "rep1-amd"})
    rep_tech = ET.SubElement(rep_amd, ET.QName(METS_NS, "techMD"), {"ID": "rep1-amd-tech"})
    rep_wrap = ET.SubElement(rep_tech, ET.QName(METS_NS, "mdWrap"), {"MDTYPE": "OTHER", "OTHERMDTYPE": "dnx"})
    rep_xml = ET.SubElement(rep_wrap, ET.QName(METS_NS, "xmlData"))
    rep_dnx = _create_dnx_element(rep_xml, "dnx")
    rep_section = _create_dnx_element(rep_dnx, "section", {"id": "generalRepCharacteristics"})
    rep_record = _create_dnx_element(rep_section, "record")
    _create_dnx_element(rep_record, "key", {"id": "preservationType"}, "PRESERVATION_MASTER")
    _create_dnx_element(rep_record, "key", {"id": "usageType"}, "VIEW")

    # Add per-file amdSec with fixity and fileOriginalPath
    file_amd_sections: List[ET._Element] = []
    for index, obj in enumerate(harvestable_objects, start=1):
        file_id = f"fid1-{index}"
        file_amd = ET.SubElement(mets_root, ET.QName(METS_NS, "amdSec"), {"ID": f"{file_id}-amd"})
        file_tech = ET.SubElement(file_amd, ET.QName(METS_NS, "techMD"), {"ID": f"{file_id}-amd-tech"})
        file_wrap = ET.SubElement(file_tech, ET.QName(METS_NS, "mdWrap"), {"MDTYPE": "OTHER", "OTHERMDTYPE": "dnx"})
        file_xml = ET.SubElement(file_wrap, ET.QName(METS_NS, "xmlData"))
        file_dnx = _create_dnx_element(file_xml, "dnx")

        # generalFileCharacteristics with fileOriginalPath
        general_keys: List[tuple] = []
        label_value = obj.display_label or obj.file_name
        if label_value:
            general_keys.append(("label", label_value))
        if obj.file_name:
            general_keys.append(("fileOriginalName", obj.file_name))
        original_path = getattr(obj, "path", None) or getattr(obj, "storage_key", None)
        if original_path:
            general_keys.append(("fileOriginalPath", original_path))
        if obj.content_type:
            general_keys.append(("fileMIMEType", obj.content_type))
        if obj.size_bytes is not None:
            general_keys.append(("fileSizeBytes", str(obj.size_bytes)))

        if general_keys:
            general_section = _create_dnx_element(file_dnx, "section", {"id": "generalFileCharacteristics"})
            general_record = _create_dnx_element(general_section, "record")
            for key_id, value in general_keys:
                _create_dnx_element(general_record, "key", {"id": key_id}, value)

        # fileFixity with checksum
        checksum_algorithm, checksum_value = obj.checksum_tuple()
        checksum_label = obj.checksum_label() if checksum_algorithm else None
        if checksum_value:
            fixity_type = _normalize_fixity_type(checksum_label or "SHA-256")
            fixity_section = _create_dnx_element(file_dnx, "section", {"id": "fileFixity"})
            fixity_record = _create_dnx_element(fixity_section, "record")
            _create_dnx_element(fixity_record, "key", {"id": "fixityType"}, fixity_type)
            _create_dnx_element(fixity_record, "key", {"id": "fixityValue"}, checksum_value)

        file_amd_sections.append((file_id, file_amd))

    file_sec = ET.SubElement(mets_root, ET.QName(METS_NS, "fileSec"))
    file_grp = ET.SubElement(file_sec, ET.QName(METS_NS, "fileGrp"), {"ID": "rep1", "ADMID": "rep1-amd"})

    struct_map = ET.SubElement(mets_root, ET.QName(METS_NS, "structMap"), {"ID": "structMap-1", "TYPE": "LOGICAL"})
    project_label = record.title or getattr(resource, "name", None) or identifier_value or "Project"
    # Note: TYPE must be 'FILE' per Rosetta METS schema requirements
    struct_root = ET.SubElement(
        struct_map,
        ET.QName(METS_NS, "div"),
        {"TYPE": "FILE", "LABEL": project_label},
    )

    for index, obj in enumerate(harvestable_objects, start=1):
        href = _escape_flocat_href(obj.preferred_location)
        if not href:
            continue
        file_id = f"fid1-{index}"
        # Note: CHECKSUM, CHECKSUMTYPE, MIMETYPE, SIZE removed per Rosetta requirements
        # Fixity info is in per-file DNX amdTech section
        file_attrs: Dict[str, str] = {"ID": file_id, "ADMID": f"{file_id}-amd"}

        file_element = ET.SubElement(file_grp, ET.QName(METS_NS, "file"), file_attrs)
        flocat_attrs = {
            "LOCTYPE": "URL",
            f"{{{XLINK_NS}}}href": href,
            f"{{{XLINK_NS}}}type": "simple",
        }
        label_value = obj.display_label or obj.file_name
        if label_value:
            flocat_attrs[f"{{{XLINK_NS}}}title"] = label_value
        ET.SubElement(file_element, ET.QName(METS_NS, "FLocat"), flocat_attrs)

        file_label = obj.display_label or obj.file_name or f"Digital Object {index}"
        file_div = ET.SubElement(
            struct_root,
            ET.QName(METS_NS, "div"),
            {
                "TYPE": "FILE",
                "LABEL": file_label,
            },
        )
        ET.SubElement(file_div, ET.QName(METS_NS, "fptr"), {"FILEID": file_id})

    _t3 = _time.perf_counter()
    logger.info(
        "METS timing %s: setup=%.3fs, rdf=%.3fs, files=%.3fs, total=%.3fs",
        getattr(resource, "uri", "?")[-25:],
        _t1 - _t0,
        _t2 - _t1,
        _t3 - _t2,
        _t3 - _t0,
    )
    return mets_root


def _build_mets_from_project(
    project: OAIProject,
    resource: Resource,
    dc_payload: Dict[str, List[str]],
    dc_source_payloads: Optional[List[Dict[str, List[Any]]]] = None,
    *,
    request: Optional[HttpRequest] = None,
) -> ET._Element:
    _register_rosetta_namespaces()

    record = project.record
    normalized_org_code = _normalized_org_code(resource, project)
    apply_khm_licensing = normalized_org_code in _KHM_HMT_LICENSE_ORGS

    mets_root = ET.Element(ET.QName(METS_NS, "mets"), nsmap=METS_NSMAP)
    # Note: OBJID and xsi:schemaLocation removed per Rosetta example

    dmd_sec = ET.SubElement(mets_root, ET.QName(METS_NS, "dmdSec"), {"ID": "ie-dmd"})
    md_wrap = ET.SubElement(dmd_sec, ET.QName(METS_NS, "mdWrap"), {"MDTYPE": "DC"})
    xml_data = ET.SubElement(md_wrap, ET.QName(METS_NS, "xmlData"))
    dc_record = ET.SubElement(xml_data, ET.QName(DC_NS, "record"))
    for ns_uri, term, text, attrs in _iter_dc_entries(dc_payload):
        elem = ET.SubElement(dc_record, ET.QName(ns_uri, term))
        elem.text = text
        for attr_name, attr_value in attrs.items():
            if attr_value is None:
                continue
            elem.set(attr_name, attr_value)
    _append_arkumu_identifier(dc_record, resource)

    schema_href_map = schema_utils.build_schema_href_map()

    rights_meta = _rights_metadata_from_status(getattr(record, "rights_status", None))
    if not rights_meta:
        rights_meta = _default_rights_metadata(resource, record)
    rights_status_literal = getattr(record, "rights_status", None) or (
        rights_meta.get("status_de") if rights_meta else None
    )
    rights_links = _rights_link_uris(rights_status_literal)

    ie_amd = ET.SubElement(mets_root, ET.QName(METS_NS, "amdSec"), {"ID": "ie-amd"})
    tech_md = ET.SubElement(ie_amd, ET.QName(METS_NS, "techMD"), {"ID": "ie-amd-tech"})
    tech_wrap = ET.SubElement(tech_md, ET.QName(METS_NS, "mdWrap"), {"MDTYPE": "OTHER", "OTHERMDTYPE": "dnx"})
    tech_xml = ET.SubElement(tech_wrap, ET.QName(METS_NS, "xmlData"))
    tech_dnx = _create_dnx_element(tech_xml, "dnx")
    _create_dnx_element(tech_dnx, "section", {"id": "objectCharacteristics"})
    _create_dnx_element(tech_dnx, "section", {"id": "objectIdentifier"})

    rights_md = ET.SubElement(ie_amd, ET.QName(METS_NS, "rightsMD"), {"ID": "ie-amd-rights"})
    rights_wrap = ET.SubElement(rights_md, ET.QName(METS_NS, "mdWrap"), {"MDTYPE": "OTHER", "OTHERMDTYPE": "dnx"})
    rights_xml = ET.SubElement(rights_wrap, ET.QName(METS_NS, "xmlData"))
    rights_dnx = _create_dnx_element(rights_xml, "dnx")

    if rights_links:
        rights_section = _create_dnx_element(rights_dnx, "section", {"id": "linkingRightsStatementIdentifier"})
        for uri in rights_links:
            record_elem = _create_dnx_element(rights_section, "record")
            _create_dnx_element(record_elem, "key", {"id": "linkingRightsStatementIdentifierType"}, "URI")
            _create_dnx_element(record_elem, "key", {"id": "linkingRightsStatementIdentifierValue"}, uri)

    granted_value: Optional[str] = None
    if rights_meta:
        for key in ("status_de", "status_en"):
            candidate = rights_meta.get(key)
            if candidate:
                granted_value = candidate
                break
    if granted_value is None:
        granted_value = _rights_label_for_resource(resource)

    if granted_value:
        granted_section = _create_dnx_element(rights_dnx, "section", {"id": "grantedRightsStatement"})
        record_elem = _create_dnx_element(granted_section, "record")
        _create_dnx_element(record_elem, "key", {"id": "grantedRightsStatementValue"}, granted_value)

    event_payloads = dc_source_payloads if dc_source_payloads is not None else _build_event_dc_payloads(record)
    if event_payloads:
        multiple_source_sections = len(event_payloads) > 1
        for index, event_payload in enumerate(event_payloads, start=1):
            source_id = "ie-amd-source-dc" if not multiple_source_sections else f"ie-amd-source-dc-{index}"
            source_dc_md = ET.SubElement(ie_amd, ET.QName(METS_NS, "sourceMD"), {"ID": source_id})
            source_dc_wrap = ET.SubElement(source_dc_md, ET.QName(METS_NS, "mdWrap"), {"MDTYPE": "DC"})
            source_dc_xml = ET.SubElement(source_dc_wrap, ET.QName(METS_NS, "xmlData"))
            for ns_uri, term, text, attrs in _iter_dc_entries(event_payload):
                elem = ET.SubElement(source_dc_xml, ET.QName(ns_uri, term))
                elem.text = text
                for attr_name, attr_value in attrs.items():
                    if attr_value is None:
                        continue
                    elem.set(attr_name, attr_value)
    source_md = ET.SubElement(ie_amd, ET.QName(METS_NS, "sourceMD"), {"ID": "ie-amd-source-OTHER"})
    source_wrap = ET.SubElement(
        source_md,
        ET.QName(METS_NS, "mdWrap"),
        {
            "MDTYPE": "OTHER",
            "OTHERMDTYPE": "RDF",
        },
    )
    source_xml = ET.SubElement(source_wrap, ET.QName(METS_NS, "xmlData"))
    schema_href_map = schema_utils.build_schema_href_map(request=request)
    org_code = resource.organization.code if resource.organization else None
    try:
        rdf_service = CanonicalGraphService(org_code=org_code)
        rdf_element = build_rdf_graph(resource, graph_service=rdf_service)
        schema_href = schema_href_map.get("canonical")
        if schema_href:
            rdf_element.set(
                ET.QName(XSI_NS, "schemaLocation"),
                f"{RDF_NS} {schema_href}",
            )
        source_xml.append(rdf_element)
    except Exception:
        logger.exception("Failed to build RDF metadata for %s", getattr(resource, "uri", "unknown"))

    if _should_emit_institutional_rdf(normalized_org_code):
        inst_element = _build_institutional_rdf_element(resource)
        if inst_element is not None:
            inst_md = ET.SubElement(
                ie_amd,
                ET.QName(METS_NS, "sourceMD"),
                {"ID": "ie-amd-source-RDF-INSTITUTIONAL"},
            )
            inst_wrap = ET.SubElement(
                inst_md,
                ET.QName(METS_NS, "mdWrap"),
                {
                    "MDTYPE": "OTHER",
                    "OTHERMDTYPE": "RDF-INSTITUTIONAL",
                },
            )
            inst_xml = ET.SubElement(inst_wrap, ET.QName(METS_NS, "xmlData"))
            schema_href = schema_href_map.get("institutional")
            if schema_href:
                inst_element.set(
                    ET.QName(XSI_NS, "schemaLocation"),
                    f"{RDF_NS} {schema_href}",
                )
            inst_xml.append(inst_element)

    digiprov_md = ET.SubElement(ie_amd, ET.QName(METS_NS, "digiprovMD"), {"ID": "ie-amd-digiprov"})
    digiprov_wrap = ET.SubElement(digiprov_md, ET.QName(METS_NS, "mdWrap"), {"MDTYPE": "OTHER", "OTHERMDTYPE": "dnx"})
    digiprov_xml = ET.SubElement(digiprov_wrap, ET.QName(METS_NS, "xmlData"))
    _create_dnx_element(digiprov_xml, "dnx")

    project_license_tokens: set[str] = set()
    for candidate_obj in project.digital_objects:
        token = license_token_from_license_info(getattr(candidate_obj, "license", None))
        if token:
            project_license_tokens.add(token)
    if not project_license_tokens:
        project_license_tokens.add("1")

    harvestable_objects = [
        obj for obj in project.digital_objects
        if obj.harvestable and obj.preferred_location
    ]
    logger.info(f"METS generation: project has {len(project.digital_objects)} digital objects, {len(harvestable_objects)} harvestable")
    rep_groups = _group_digital_objects_for_rosetta(harvestable_objects)
    logger.info(f"METS generation: {len(rep_groups)} representation groups with {sum(len(objs) for _, objs in rep_groups)} total objects")

    file_sec_entries: List[Dict[str, Any]] = []

    events_by_uri: Dict[str, ProjectEvent] = {}
    for event in record.events:
        if getattr(event, "is_reference_only", False):
            continue
        if event.uri:
            events_by_uri[event.uri] = event

    event_file_map: Dict[str, ProjectEvent] = {}

    def _remember_event_mapping(key: Optional[str], event_obj: ProjectEvent) -> None:
        if not key:
            return
        normalized = key.strip()
        event_file_map.setdefault(normalized, event_obj)
        if normalized != key:
            event_file_map.setdefault(key, event_obj)

    if events_by_uri:
        event_files_qs = (
            S3FileObject.objects.filter(
                related_resource__uri__in=list(events_by_uri.keys()),
                status__in=HARVESTABLE_FILE_STATUSES,
            )
            .select_related('related_resource')
        )
        for file_obj in event_files_qs:
            related = getattr(file_obj, 'related_resource', None)
            related_uri = getattr(related, 'uri', None)
            if not related_uri:
                continue
            event_obj = events_by_uri.get(related_uri)
            if not event_obj:
                continue
            candidates = [
                getattr(file_obj, 's3_key', None),
                getattr(file_obj, 'original_path', None),
                getattr(file_obj, 'file_name', None),
            ]
            for candidate in candidates:
                _remember_event_mapping(candidate, event_obj)

    def _object_keys(obj: NormalizedDigitalObject) -> List[str]:
        keys: List[str] = []
        sources = [
            obj.storage_key,
            obj.original_path,
            obj.rosetta_path,
            obj.preferred_location,
            obj.file_name,
        ]
        for source in sources:
            if not source:
                continue
            stripped = source.strip()
            keys.append(stripped)
            if stripped != source:
                keys.append(source)
        return keys

    def _event_for_object(obj: NormalizedDigitalObject) -> Optional[ProjectEvent]:
        for candidate in _object_keys(obj):
            event_obj = event_file_map.get(candidate)
            if event_obj:
                return event_obj
        return None

    file_counter = 1

    for rep_index, (rep_type, objects) in enumerate(rep_groups, start=1):
        rep_id = f"rep{rep_index}"

        rep_amd = ET.SubElement(mets_root, ET.QName(METS_NS, "amdSec"), {"ID": f"{rep_id}-amd"})
        rep_tech = ET.SubElement(rep_amd, ET.QName(METS_NS, "techMD"), {"ID": f"{rep_id}-amd-tech"})
        rep_wrap = ET.SubElement(rep_tech, ET.QName(METS_NS, "mdWrap"), {"MDTYPE": "OTHER", "OTHERMDTYPE": "dnx"})
        rep_xml = ET.SubElement(rep_wrap, ET.QName(METS_NS, "xmlData"))
        rep_dnx = _create_dnx_element(rep_xml, "dnx")
        section = _create_dnx_element(rep_dnx, "section", {"id": "generalRepCharacteristics"})
        rec = _create_dnx_element(section, "record")
        _create_dnx_element(rec, "key", {"id": "preservationType"}, rep_type)
        _create_dnx_element(rec, "key", {"id": "usageType"}, "VIEW")

        rep_files: List[Dict[str, Any]] = []

        for file_index, obj in enumerate(objects, start=1):
            file_id = f"fid-{rep_index}-{file_index}"
            file_counter += 1
            preferred_location = obj.preferred_location or ""
            preferred_label = obj.display_label or obj.file_name
            file_label_source = preferred_label or preferred_location or obj.original_path or f"Digital Object {file_index}"
            label_normalized = _normalize_reference(file_label_source)
            file_label = label_normalized or file_label_source
            if preferred_label:
                file_label = preferred_label

            file_amd = ET.SubElement(mets_root, ET.QName(METS_NS, "amdSec"), {"ID": f"{file_id}-amd"})
            file_tech = ET.SubElement(file_amd, ET.QName(METS_NS, "techMD"), {"ID": f"{file_id}-amd-tech"})
            file_wrap = ET.SubElement(file_tech, ET.QName(METS_NS, "mdWrap"), {"MDTYPE": "OTHER", "OTHERMDTYPE": "dnx"})
            file_xml = ET.SubElement(file_wrap, ET.QName(METS_NS, "xmlData"))
            file_dnx = _create_dnx_element(file_xml, "dnx")
            characteristics_section = _create_dnx_element(file_dnx, "section", {"id": "objectCharacteristics"})
            characteristics_record = _create_dnx_element(characteristics_section, "record")
            _create_dnx_element(characteristics_record, "key", {"id": "objectType"}, "FILE")

            general_keys: List[tuple[str, str]] = []
            label_value = preferred_label or file_label
            if label_value:
                general_keys.append(("label", label_value))
            if obj.file_name:
                general_keys.append(("fileOriginalName", obj.file_name))
            # fileOriginalPath removed per Rosetta requirements (Issue #4)
            if obj.content_type:
                general_keys.append(("fileMIMEType", obj.content_type))
            if obj.size_bytes is not None:
                general_keys.append(("fileSizeBytes", str(obj.size_bytes)))

            if general_keys:
                general_section = _create_dnx_element(file_dnx, "section", {"id": "generalFileCharacteristics"})
                general_record = _create_dnx_element(general_section, "record")
                for key_id, value in general_keys:
                    _create_dnx_element(general_record, "key", {"id": key_id}, value)

            checksum_algorithm, checksum_value = obj.checksum_tuple()
            checksum_label = obj.checksum_label() if checksum_algorithm else None
            fallback_label = checksum_label or ("MD5" if obj.source == "s3" else "SHA-256")
            fixity_type_value = _normalize_fixity_type(fallback_label)
            if checksum_value:
                fixity_section = _create_dnx_element(file_dnx, "section", {"id": "fileFixity"})
                fixity_record = _create_dnx_element(fixity_section, "record")
                _create_dnx_element(
                    fixity_record,
                    "key",
                    {"id": "fixityType"},
                    fixity_type_value,
                )
                _create_dnx_element(
                    fixity_record,
                    "key",
                    {"id": "fixityValue"},
                    checksum_value,
                )
                if checksum_label and _normalize_fixity_type(checksum_label) != fixity_type_value:
                    _create_dnx_element(
                        fixity_record,
                        "key",
                        {"id": "fixityAlgorithm"},
                        checksum_label,
                    )

            license_info = getattr(obj, "license", None)
            license_uri: Optional[str] = None
            license_identifier: Optional[str] = None
            license_rights_statement: Optional[str] = None
            license_label_de: Optional[str] = None
            license_label_en: Optional[str] = None
            license_token: Optional[str] = None

            if license_info:
                def _normalize_license_value(value: Optional[Any]) -> Optional[str]:
                    if value is None:
                        return None
                    text = str(value).strip()
                    return text or None

                license_uri = _normalize_license_value(getattr(license_info, "uri", None))
                license_identifier = _normalize_license_value(getattr(license_info, "identifier", None))
                license_rights_statement = _normalize_license_value(getattr(license_info, "rights_statement", None))
                license_label_de = _normalize_license_value(getattr(license_info, "label_de", None))
                license_label_en = _normalize_license_value(getattr(license_info, "label_en", None))
                license_token = license_token_from_license_info(license_info)

            if not license_info or not license_token:
                fallback_token = sorted(project_license_tokens)[0]
                canonical_uri = ARKUMU_LICENSE_URIS.get(fallback_token)
                if not license_info:
                    license_info = ProjectDigitalObjectLicense(
                        uri=canonical_uri,
                        identifier=fallback_token,
                        label_de=ARKUMU_LICENSE_LABELS[fallback_token],
                        rights_statement=ARKUMU_LICENSE_TEXTS[fallback_token],
                    )
                else:
                    license_info = ProjectDigitalObjectLicense(
                        uri=license_uri or canonical_uri,
                        identifier=fallback_token,
                        label_de=ARKUMU_LICENSE_LABELS[fallback_token],
                        rights_statement=ARKUMU_LICENSE_TEXTS[fallback_token],
                    )
                license_token = fallback_token
                license_uri = license_info.uri
                license_identifier = license_info.identifier
                license_rights_statement = license_info.rights_statement
                license_label_de = license_info.label_de
                license_label_en = None

                granted_statement_value = license_rights_statement or license_label_de or license_label_en
                requires_rights_md = (
                    not apply_khm_licensing
                    and any([license_uri, license_identifier, granted_statement_value])
                )

                if requires_rights_md:
                    file_rights = ET.SubElement(
                        file_amd,
                        ET.QName(METS_NS, "rightsMD"),
                        {"ID": f"{file_id}-amd-rights"},
                    )
                    file_rights_wrap = ET.SubElement(
                        file_rights,
                        ET.QName(METS_NS, "mdWrap"),
                        {"MDTYPE": "OTHER", "OTHERMDTYPE": "dnx"},
                    )
                    file_rights_xml = ET.SubElement(file_rights_wrap, ET.QName(METS_NS, "xmlData"))
                    file_rights_dnx = _create_dnx_element(file_rights_xml, "dnx")

                    if license_uri:
                        rights_section = _create_dnx_element(
                            file_rights_dnx,
                            "section",
                            {"id": "linkingRightsStatementIdentifier"},
                        )
                        rights_record = _create_dnx_element(rights_section, "record")
                        _create_dnx_element(
                            rights_record,
                            "key",
                            {"id": "linkingRightsStatementIdentifierType"},
                            "URI",
                        )
                        _create_dnx_element(
                            rights_record,
                            "key",
                            {"id": "linkingRightsStatementIdentifierValue"},
                            license_uri,
                        )

                    if license_identifier or granted_statement_value:
                        granted_section = _create_dnx_element(
                            file_rights_dnx,
                            "section",
                            {"id": "grantedRightsStatement"},
                        )
                        granted_record = _create_dnx_element(granted_section, "record")
                        if license_identifier:
                            _create_dnx_element(
                                granted_record,
                                "key",
                                {"id": "grantedRightsStatementIdentifier"},
                                license_identifier,
                            )
                        if granted_statement_value:
                            _create_dnx_element(
                                granted_record,
                                "key",
                                {"id": "grantedRightsStatementValue"},
                                granted_statement_value,
                            )

            file_source = ET.SubElement(file_amd, ET.QName(METS_NS, "sourceMD"), {"ID": f"{file_id}-amd-source-dc"})
            file_source_wrap = ET.SubElement(file_source, ET.QName(METS_NS, "mdWrap"), {"MDTYPE": "DC"})
            file_source_xml = ET.SubElement(file_source_wrap, ET.QName(METS_NS, "xmlData"))
            file_source_record = ET.SubElement(file_source_xml, ET.QName(DC_NS, "record"))

            if obj.uuid:
                identifier_elem = ET.SubElement(file_source_record, ET.QName(DC_NS, "identifier"))
                identifier_elem.text = obj.uuid
                identifier_elem.set(ET.QName(XML_NS, "type"), "Digital-Object-ID")

            file_title = obj.display_label or obj.file_name or file_label
            if file_title:
                title_elem = ET.SubElement(file_source_record, ET.QName(DC_NS, "title"))
                title_elem.text = file_title
                title_elem.set(ET.QName(XML_NS, "type"), "file-name")

            if obj.genesis_type:
                genesis_elem = ET.SubElement(file_source_record, ET.QName(DC_NS, "type"))
                genesis_elem.text = obj.genesis_type
                genesis_elem.set(ET.QName(XML_NS, "type"), "genesis-type")

            if obj.media_type:
                media_elem = ET.SubElement(file_source_record, ET.QName(DC_NS, "type"))
                media_elem.text = obj.media_type
                media_elem.set(ET.QName(XML_NS, "type"), "media-type")

            if obj.content_type:
                mimetype_elem = ET.SubElement(file_source_record, ET.QName(DC_NS, "type"))
                mimetype_elem.text = obj.content_type
                mimetype_elem.set(ET.QName(XML_NS, "type"), "mimetype")

            if obj.significant_properties_de:
                sig_de_elem = ET.SubElement(file_source_record, ET.QName(DC_NS, "description"))
                sig_de_elem.text = obj.significant_properties_de
                sig_de_elem.set(ET.QName(XML_NS, "type"), "significant-properties-german")

            if obj.significant_properties_en:
                sig_en_elem = ET.SubElement(file_source_record, ET.QName(DC_NS, "description"))
                sig_en_elem.text = obj.significant_properties_en
                sig_en_elem.set(ET.QName(XML_NS, "type"), "significant-properties-english")

            if license_info:
                xml_lang_attr = ET.QName(XML_NS, "lang")
                rights_signatures: set[tuple[str, tuple[tuple[str, str], ...]]] = set()

                def _append_rights_value(
                    value: Optional[str],
                    attrs: Optional[Dict[ET.QName, str]] = None,
                ) -> None:
                    if value is None:
                        return
                    normalized = str(value).strip()
                    if not normalized:
                        return
                    signature_attrs = tuple(sorted((str(key), val) for key, val in (attrs or {}).items()))
                    signature = (normalized, signature_attrs)
                    if signature in rights_signatures:
                        return
                    elem = ET.SubElement(file_source_record, ET.QName(DC_NS, "rights"))
                    elem.text = normalized
                    for key, val in (attrs or {}).items():
                        elem.set(key, val)
                    rights_signatures.add(signature)

                has_canonical_mapping = bool(license_token and license_token in ARKUMU_LICENSE_LABELS)
                if has_canonical_mapping:
                    _append_rights_value(ARKUMU_LICENSE_LABELS[license_token])
                    _append_rights_value(ARKUMU_LICENSE_TEXTS[license_token])

                include_additional_rights = not has_canonical_mapping
                if include_additional_rights:
                    _append_rights_value(license_label_de)
                    _append_rights_value(license_label_en)
                    _append_rights_value(license_rights_statement)

            raw_path = (
                getattr(obj, "rosetta_path", None)
                or obj.storage_key
                or obj.original_path
                or preferred_location
            )
            path_parts: List[str] = []
            if raw_path:
                path_parts = [part for part in raw_path.strip('/').split('/') if part]
            if len(path_parts) > 1:
                folder_segments = [
                    segment
                    for segment in path_parts[:-1]
                    if segment and segment.casefold() != "data"
                ]
            else:
                folder_segments = []

            # Organization-specific structMap path normalization
            # - HMT: omit intermediate folders entirely
            # - KHM: keep only the last two folders (closest to the file)
            if normalized_org_code == "hmt":
                folder_segments = []
            elif normalized_org_code == "khm":
                if len(folder_segments) > 2:
                    folder_segments = folder_segments[-2:]

            rep_files.append({
                "file_id": file_id,
                "label": file_label,
                "object": obj,
                "rep_id": rep_id,
                "rep_type": rep_type,
                "event": _event_for_object(obj),
                "folders": folder_segments,
                "order": file_index,
            })
        file_sec_entries.append({
            "rep_id": rep_id,
            "rep_type": rep_type,
            "files": rep_files,
        })

    file_sec = ET.SubElement(mets_root, ET.QName(METS_NS, "fileSec"))

    project_title = record.title or record.subtitle or record.uri or "Project"

    for entry in file_sec_entries:
        rep_id = entry["rep_id"]
        rep_type = entry["rep_type"]
        file_grp = ET.SubElement(
            file_sec,
            ET.QName(METS_NS, "fileGrp"),
            {
                "USE": "VIEW",
                "ID": rep_id,
                "ADMID": f"{rep_id}-amd",
            },
        )

        for position, file_info in enumerate(entry["files"], start=1):
            obj = file_info["object"]
            file_id = file_info["file_id"]
            attrs: Dict[str, Any] = {
                "ID": file_id,
                "ADMID": f"{file_id}-amd",
            }
            if obj.content_type:
                attrs["MIMETYPE"] = obj.content_type
            # Rosetta profile forbids CHECKSUM attributes on mets:file; fixity lives in DNX

            file_elem = ET.SubElement(file_grp, ET.QName(METS_NS, "file"), attrs)
            href = obj.preferred_location or obj.access_url or ""
            normalized_href = _normalize_reference(href)
            if normalized_href:
                href = normalized_href
            href = _escape_flocat_href(href)
            if href:
                flocat_attrs = {
                    "LOCTYPE": "URL",
                    f"{{{XLINK_NS}}}href": href,
                    f"{{{XLINK_NS}}}type": "simple",
                }
                ET.SubElement(file_elem, ET.QName(METS_NS, "FLocat"), flocat_attrs)

        struct_map = ET.SubElement(
            mets_root,
            ET.QName(METS_NS, "structMap"),
            {"ID": f"{rep_id}-1", "TYPE": "LOGICAL"},
        )

        # Root div has no attributes per Rosetta example
        project_div = ET.SubElement(
            struct_map,
            ET.QName(METS_NS, "div"),
        )

        # Representation div also simplified per Rosetta example
        rep_div = project_div

        def _event_key(event_obj: Optional[ProjectEvent]) -> str:
            if event_obj is None:
                return "__project__"
            if event_obj.uri:
                return f"uri:{event_obj.uri}"
            if event_obj.id:
                return f"id:{event_obj.id}"
            if event_obj.name:
                return f"name:{event_obj.name}"
            return f"event:{id(event_obj)}"

        event_order: List[str] = []
        files_by_event: Dict[str, List[Dict[str, Any]]] = {}
        event_meta: Dict[str, Optional[ProjectEvent]] = {}

        for event in record.events:
            key = _event_key(event)
            event_order.append(key)
            files_by_event.setdefault(key, [])
            event_meta[key] = event

        for file_info in entry["files"]:
            event_obj = file_info.get("event")
            key = _event_key(event_obj)
            if key not in files_by_event:
                event_order.append(key)
            files_by_event.setdefault(key, []).append(file_info)
            event_meta.setdefault(key, event_obj)

        folder_nodes: Dict[tuple[str, ...], ET._Element] = {}

        def _event_label(event_obj: Optional[ProjectEvent]) -> Optional[str]:
            if event_obj is None:
                return None
            return event_obj.name or event_obj.location or event_obj.uri or "Ereignis"

        for key in event_order:
            event_files = files_by_event.get(key)
            if not event_files:
                continue
            event_obj = event_meta.get(key)
            event_label = _event_label(event_obj)

            for file_info in event_files:
                parent = rep_div
                folder_key_prefix: List[str] = []
                segments = list(file_info.get("folders") or [])
                if event_label:
                    if not segments or segments[0] != event_label:
                        segments = [event_label, *segments]
                for segment in segments:
                    folder_key_prefix.append(segment)
                    folder_key = tuple(folder_key_prefix)
                    existing = folder_nodes.get(folder_key)
                    if not existing:
                        existing = ET.SubElement(
                            parent,
                            ET.QName(METS_NS, "div"),
                            {
                                "LABEL": segment,
                                "ORDERLABEL": segment,
                            },
                        )
                        folder_nodes[folder_key] = existing
                    parent = existing

                # File div per Rosetta example - TYPE="FILE", LABEL, ORDERLABEL (no ORDER)
                file_div = ET.SubElement(
                    parent,
                    ET.QName(METS_NS, "div"),
                    {
                        "TYPE": "FILE",
                        "LABEL": file_info["label"],
                        "ORDERLABEL": file_info["label"],
                    },
                )
                ET.SubElement(file_div, ET.QName(METS_NS, "fptr"), {"FILEID": file_info["file_id"]})

    return mets_root


def _build_metadata_element(
    resource: Resource,
    metadata_prefix: str,
    project_hint: Optional[OAIProject] = None,
    *,
    request: Optional[HttpRequest] = None,
    skip_validation: bool = False,
    force_live_rdf: bool = False,
) -> ET._Element:
    """Build metadata element for different formats.

    Args:
        force_live_rdf: If True, always fetch RDF on-demand (for GetRecord previews).
    """
    metadata = ET.Element("metadata")

    projects = _candidate_projects_for_resource(resource, primary_project=project_hint)

    if not projects:
        logger.warning("No snapshot record found for %s", getattr(resource, 'uri', 'unknown'))
        return metadata

    if metadata_prefix == "oai_dc":
        project = projects[0]
        dc_payload = _build_dc_payload_from_project(
            project,
            resource,
            include_event_details=False,
        )
        dc_root = _append_dc_metadata(metadata, dc_payload)
        _append_arkumu_identifier(dc_root, resource)
    elif metadata_prefix == "mets":
        import time
        simplified_mode = _tailored_mode_enabled()
        for project in projects:
            if not project.harvestable:
                continue

            t_mets_start = time.time()
            if simplified_mode:
                mets_root = _build_simplified_mets_from_project(project, resource, request=request, force_live_rdf=force_live_rdf)
            else:
                dc_payload_core = _build_dc_payload_from_project(
                    project,
                    resource,
                    include_event_details=False,
                )
                dc_payload_source = _build_event_dc_payloads(project.record)
                mets_root = _build_mets_from_project(
                    project,
                    resource,
                    dc_payload_core,
                    dc_source_payloads=dc_payload_source,
                    request=request,
                )
            t_mets_gen = time.time()

            if skip_validation:
                # Skip validation for tailored endpoint - we control generation
                logger.info(
                    "METS %s: gen=%.3fs (validation skipped)",
                    getattr(resource, "uri", "?")[-20:],
                    t_mets_gen - t_mets_start,
                )
                mets_bytes = ET.tostring(mets_root, encoding="utf-8")
                metadata.append(ET.fromstring(mets_bytes))
                break

            candidate_wrapper = ET.Element("metadata")
            candidate_wrapper.append(ET.fromstring(ET.tostring(mets_root)))

            t_parse = time.time()
            validation = rosetta_mets_validator.validate_metadata_element(
                candidate_wrapper,
                resource_uri=getattr(resource, "uri", None),
            )
            t_valid = time.time()
            logger.info(
                "METS %s: gen=%.3fs, parse=%.3fs, valid=%.3fs",
                getattr(resource, "uri", "?")[-20:],
                t_mets_gen - t_mets_start,
                t_parse - t_mets_gen,
                t_valid - t_parse,
            )

            if not validation.is_valid:
                issues = getattr(validation, "issues", [])
                if not isinstance(issues, (list, tuple)):
                    issues = [issues] if issues else []
                messages: List[str] = []
                for issue in issues:
                    if issue is None:
                        continue
                    message = getattr(issue, "message", None)
                    messages.append(str(message) if message is not None else str(issue))
                issue_summary = "; ".join(messages) or "unknown reason"
                logger.error(
                    "Generated METS payload failed validation for %s: %s; trying next candidate",
                    getattr(resource, "uri", "unknown"),
                    issue_summary,
                )
                continue

            mets_bytes = ET.tostring(mets_root, encoding="utf-8")
            metadata.append(ET.fromstring(mets_bytes))
            break
    elif metadata_prefix == "rdf":
        rdf_service = CanonicalGraphService(
            org_code=resource.organization.code if resource.organization else None
        )
        rdf_element = build_rdf_graph(resource, graph_service=rdf_service)
        metadata.append(rdf_element)

    return metadata
def _mint_arkumu_pid(resource: Resource) -> Optional[str]:
    """Mint an Arkumu local persistent identifier for a resource.

    Format: "arkumu-{org}-{local_id}"
    where local_id is derived from the typical entity URI pattern:
    .../entities/{project_id}/{item_id}

    Returns None when required parts are missing.
    """
    try:
        org_code = (resource.organization.code if resource.organization else None)
        uri = getattr(resource, "uri", None)
        if not org_code or not uri:
            return None

        # Parse URI path and attempt to extract project and item id
        path = urlparse(uri).path or ""
        parts = [p for p in path.strip("/").split("/") if p]

        # Look for the common pattern: .../entities/{project_id}/{item_id}
        project_id = None
        item_id = None
        try:
            ent_idx = parts.index("entities")
            # Expect at least two parts after 'entities'
            if len(parts) > ent_idx + 2:
                project_id = parts[ent_idx + 1]
                item_id = parts[ent_idx + 2]
            elif len(parts) > ent_idx + 1:
                # Fallback: if only one part, use it as project and try last as item
                project_id = parts[ent_idx + 1]
                item_id = parts[-1] if len(parts) - 1 > ent_idx + 1 else None
        except ValueError:
            # 'entities' not present; fallback to last two segments if available
            if len(parts) >= 2:
                project_id = parts[-2]
                item_id = parts[-1]

        if not project_id or not item_id:
            return None

        # Normalize components
        project_slug = slugify_uri_part(project_id)
        item_slug = slugify_uri_part(item_id)
        org_slug = slugify_uri_part(org_code)

        if not project_slug or not item_slug or not org_slug:
            return None

        local_id = f"{project_slug}-{item_slug}"
        return f"arkumu-{org_slug}-{local_id}"
    except Exception:
        return None
