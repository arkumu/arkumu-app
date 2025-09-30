"""Helpers for exposing metadata vocabulary options to other apps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from django.db.models import Q

from arkumu.metadata.models import Resource, Triple
from arkumu.metadata.services.canonical_graph_service import RDF_TYPE_URI


@dataclass(frozen=True)
class UriOption:
    """Lightweight representation of a selectable resource."""

    uri: str
    label: str


# Mapping of canonical type URIs to the canonical predicate URI that stores the
# human-readable label for resources of that type.
_TYPE_LABEL_PREDICATES: Dict[str, str] = {
    "http://arkumu.org/data/types/einliefernde-hochschule": "http://arkumu.org/data/properties/deutscher-name-der-einliefernden-hochschule",
    "http://arkumu.org/data/types/projektkategorie": "http://arkumu.org/data/properties/deutscher-name-der-projektkategorie-breadcrumb",
    "http://arkumu.org/data/types/projektart": "http://arkumu.org/data/properties/deutscher-name-der-projektart",
    "http://arkumu.org/data/types/akteurin": "http://arkumu.org/data/properties/deutscher-name",
    "http://arkumu.org/data/types/rolle": "http://arkumu.org/data/properties/deutscher-name-der-rolle-breadcrumb",
    "http://arkumu.org/data/types/schlagwort": "http://arkumu.org/data/properties/deutsches-wikidata-label",
    "http://arkumu.org/data/types/projekt": "http://arkumu.org/data/properties/bevorzugter-titel",
    "http://arkumu.org/data/types/beschreibung": "http://arkumu.org/data/properties/beschreibung",
    "http://arkumu.org/data/types/ereignisbeschreibung": "http://arkumu.org/data/properties/ereignisbeschreibung",
}


# Default key-to-type mapping used by storage forms.
_DEFAULT_TYPE_URI_KEYS: Dict[str, str] = {
    "institution": "http://arkumu.org/data/types/einliefernde-hochschule",
    "project_category": "http://arkumu.org/data/types/projektkategorie",
    "project_type": "http://arkumu.org/data/types/projektart",
    "actor": "http://arkumu.org/data/types/akteurin",
    "role": "http://arkumu.org/data/types/rolle",
    "catchphrase": "http://arkumu.org/data/types/schlagwort",
    "project": "http://arkumu.org/data/types/projekt",
    "description": "http://arkumu.org/data/types/beschreibung",
    "event_description": "http://arkumu.org/data/types/ereignisbeschreibung",
}


def get_uri_options_for_types(
    type_canonical_uris: Sequence[str],
    *,
    organization=None,
) -> Dict[str, List[UriOption]]:
    """Return form-ready options for the supplied canonical type URIs.

    The lookup tolerates multiple resources sharing the same canonical URI by
    aggregating across all matching records.
    """

    if not type_canonical_uris:
        return {}

    # Gather all resources that represent the requested types.
    type_resources = Resource.objects.filter(canonical_uri__in=type_canonical_uris)
    if organization is not None:
        type_resources = type_resources.filter(Q(organization=organization) | Q(organization__isnull=True))

    type_resources = list(type_resources)
    if not type_resources:
        return {key: [] for key in type_canonical_uris}

    type_id_to_canonical = {res.id: res.canonical_uri for res in type_resources}

    # Resolve subjects connected by rdf:type to any of the gathered type resources.
    type_triples = (
        Triple.objects.filter(
            predicate__uri=RDF_TYPE_URI,
            object__in=type_resources,
        )
        .select_related("subject")
        .distinct()
    )

    subjects_by_type: Dict[str, Dict[str, Resource]] = {key: {} for key in type_canonical_uris}
    for triple in type_triples:
        subject = triple.subject
        if not subject.uri:
            continue
        canonical_uri = type_id_to_canonical.get(triple.object_id)
        if canonical_uri:
            subjects_by_type.setdefault(canonical_uri, {})[subject.id] = subject

    # Build label mappings so each resource is shown with its human-readable name.
    label_predicates = Resource.objects.filter(
        canonical_uri__in=[_TYPE_LABEL_PREDICATES[uri] for uri in type_canonical_uris if uri in _TYPE_LABEL_PREDICATES]
    )
    predicate_map: Dict[str, List[Resource]] = {}
    for predicate in label_predicates:
        predicate_map.setdefault(predicate.canonical_uri, []).append(predicate)

    options: Dict[str, List[UriOption]] = {}
    for type_uri in type_canonical_uris:
        subjects = list(subjects_by_type.get(type_uri, {}).values())
        predicate_candidates = predicate_map.get(_TYPE_LABEL_PREDICATES.get(type_uri, ""), [])
        label_lookup = _build_label_lookup(subjects, predicate_candidates)

        options[type_uri] = [
            UriOption(uri=resource.uri, label=_resolve_label(resource, label_lookup.get(resource.id)))
            for resource in subjects
        ]
        options[type_uri].sort(key=lambda option: option.label)

    return options


def build_metadata_option_map(
    type_uri_keys: Mapping[str, str],
    *,
    organization=None,
) -> Dict[str, List[Tuple[str, str]]]:
    """Return choice tuples keyed by the supplied logical identifiers.

    Parameters
    ----------
    type_uri_keys:
        Mapping of consumer-facing identifiers (e.g. "institution") to the
        canonical RDF type URI used to resolve resources.
    organization:
        Optional organization; when provided, the underlying lookups only
        include resources scoped to the organization or global records.
    """

    if not type_uri_keys:
        return {}

    canonical_uris = list(type_uri_keys.values())
    options_by_canonical = get_uri_options_for_types(
        canonical_uris,
        organization=organization,
    )

    option_map: Dict[str, List[Tuple[str, str]]] = {}
    for key, canonical_uri in type_uri_keys.items():
        uri_options = options_by_canonical.get(canonical_uri, [])
        option_map[key] = [(option.uri, option.label) for option in uri_options]

    return option_map


def get_default_metadata_option_map(*, organization=None) -> Dict[str, List[Tuple[str, str]]]:
    """Return the default metadata option map used by storage forms."""

    return build_metadata_option_map(_DEFAULT_TYPE_URI_KEYS, organization=organization)


def _build_label_lookup(
    subjects: Iterable[Resource],
    predicates: Sequence[Resource],
) -> Dict[str, str]:
    if not subjects or not predicates:
        return {}

    triples = (
        Triple.objects.filter(
            subject__in=subjects,
            predicate__in=predicates,
        )
        .select_related("subject", "object")
    )

    labels: Dict[str, str] = {}
    for triple in triples:
        if triple.subject_id in labels:
            continue
        obj = triple.object
        label = obj.value or obj.name or obj.uri
        if label:
            labels[triple.subject_id] = label

    return labels


def _resolve_label(resource: Resource, label: Optional[str]) -> str:
    if label and label != "fehlendes Label":
        return label

    fallback = resource.value or resource.name or resource.uri or str(resource.id)
    return f"Unbekannter Eintrag ({fallback})"
