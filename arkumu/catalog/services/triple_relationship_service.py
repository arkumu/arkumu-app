"""Triple-based relationship helpers for catalog cards."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence
import uuid

from django.db.models import Q

from arkumu.metadata.models.triples import Triple
from arkumu.metadata.models import Resource, ResourceType, WikidataEntity
from arkumu.users.models import Organization


def _looks_placeholder(value: Optional[str]) -> bool:
    """Return True when a literal looks like an opaque identifier rather than a label."""

    if not value:
        return False

    stripped = value.strip()
    if not stripped:
        return False

    if stripped.isdigit():
        return True

    if stripped.upper().startswith('Q') and stripped[1:].isdigit():
        return True

    return False


class TripleRelationshipService:
    """Service for traversing catalog relationships using Triple records."""

    def __init__(self, organization_code: Optional[str] = None) -> None:
        self.organization_code = organization_code
        self._organization: Optional[Organization] = None
        self._org_cache: Dict[str, Optional[Organization]] = {}
        self._location_label_cache: Dict[str, Optional[str]] = {}
        if organization_code:
            self._organization = self._get_org_by_code(organization_code)

    def _resolve_location_label(self, location_id: str) -> Optional[str]:
        """Try to resolve a human-readable label for a Wikidata QID."""

        if not location_id:
            return None

        if location_id in self._location_label_cache:
            return self._location_label_cache[location_id]

        label: Optional[str] = None

        matching_triples = (
            Triple.objects.filter(
                predicate__canonical_uri="http://arkumu.org/data/properties/wikidata-id",
                object__value=location_id,
            )
            .select_related("subject")
        )

        label_predicates = (
            "http://arkumu.org/data/properties/deutscher-name-des-ortes",
            "http://arkumu.org/data/properties/deutscher-name-der-einliefernden-hochschule",
            "http://arkumu.org/data/properties/deutscher-name",
        )

        for match in matching_triples:
            subject_id = match.subject_id

            label_triple = None
            for predicate_uri in label_predicates:
                label_triple = Triple.objects.filter(
                    subject_id=subject_id,
                    predicate__canonical_uri=predicate_uri,
                ).first()
                if label_triple:
                    break

            if label_triple and label_triple.object and label_triple.object.value:
                label = label_triple.object.value
                break

            subject_resource = match.subject
            if subject_resource and subject_resource.name:
                label = subject_resource.name
                break

        self._location_label_cache[location_id] = label
        return label

    def _resolve_entity_labels(
        self,
        entity_ids: Iterable[str],
        label_predicates: Sequence[str],
        *,
        organization_code: Optional[str] = None,
    ) -> Dict[str, str]:
        """Resolve labels for referenced entity IDs using preferred predicates."""

        entity_ids = [entity_id for entity_id in entity_ids if entity_id]
        if not entity_ids:
            return {}

        labels: Dict[str, str] = {}

        for predicate_uri in label_predicates:
            literal_map = self._collect_literal_values(
                subject_ids=entity_ids,
                predicate_uri=predicate_uri,
                organization_code=organization_code,
            )
            for entity_id, value in literal_map.items():
                if entity_id not in labels and value:
                    labels[entity_id] = value

            if len(labels) == len(set(entity_ids)):
                break

        missing_ids = [entity_id for entity_id in entity_ids if entity_id not in labels]
        if missing_ids:
            resources = Resource.objects.filter(id__in=missing_ids)
            for resource in resources:
                fallback = resource.name or resource.value or resource.uri
                if fallback:
                    labels.setdefault(str(resource.id), fallback)

        return labels

    def get_related_entities(
        self,
        subject_id: str,
        predicate_uri: Optional[str],
        *,
        organization_code: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return object resource data for triples matching the predicate."""

        if not predicate_uri:
            return []

        triples = self._fetch_triples(
            subject_ids=[subject_id],
            predicate_uris=[predicate_uri],
            organization_code=organization_code,
        )

        results: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for triple in triples:
            obj = triple.object
            object_id = str(obj.id)
            if object_id in seen:
                continue
            seen.add(object_id)
            results.append(
                {
                    'id': object_id,
                    'uri': obj.uri,
                    'canonical_uri': obj.canonical_uri,
                    'name': obj.name,
                    'value': obj.value,
                    'resource_type': obj.resource_type,
                }
            )
        return results

    def get_institution_data(
        self,
        project_id: str,
        *,
        institution_predicate: Optional[str],
        institution_label_predicate: Optional[str],
        organization_code: Optional[str] = None,
    ) -> Optional[str]:
        """Return the institution label for the project if available."""

        institutions = self.get_related_entities(
            project_id,
            institution_predicate,
            organization_code=organization_code,
        )
        institution_ids = [entry['id'] for entry in institutions if self._is_entity(entry)]
        if not institution_ids or not institution_label_predicate:
            return None

        label_map = self._collect_literal_values(
            subject_ids=institution_ids,
            predicate_uri=institution_label_predicate,
            organization_code=organization_code,
        )
        for inst_id in institution_ids:
            label = label_map.get(inst_id)
            if label:
                return label
        return None

    def get_category_data(
        self,
        project_id: str,
        *,
        category_predicate: Optional[str],
        category_label_predicate: Optional[str],
        organization_code: Optional[str] = None,
    ) -> List[str]:
        """Return normalized category labels for the project."""

        categories = self.get_related_entities(
            project_id,
            category_predicate,
            organization_code=organization_code,
        )
        category_ids = [entry['id'] for entry in categories if self._is_entity(entry)]
        if not category_ids or not category_label_predicate:
            return []

        label_map = self._collect_literal_values(
            subject_ids=category_ids,
            predicate_uri=category_label_predicate,
            organization_code=organization_code,
        )

        results: List[str] = []
        for cat_id in category_ids:
            label = label_map.get(cat_id)
            if not label:
                continue
            value = label.split('>')[-1].strip() if '>' in label else label.strip()
            if value and value not in results:
                results.append(value)
        return results

    def get_event_data(
        self,
        project_id: str,
        *,
        event_predicate: Optional[str],
        event_start_predicate: Optional[str],
        event_end_predicate: Optional[str],
        organization_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return event IDs and their start/end values for a project."""

        events = self.get_related_entities(
            project_id,
            event_predicate,
            organization_code=organization_code,
        )

        event_ids = [entry['id'] for entry in events if self._is_entity(entry)]
        event_details = {event_id: {'start': None, 'end': None} for event_id in event_ids}

        predicates = [p for p in [event_start_predicate, event_end_predicate] if p]
        if event_ids and predicates:
            time_triples = self._fetch_triples(
                subject_ids=event_ids,
                predicate_uris=predicates,
                organization_code=organization_code,
            )
            for triple in time_triples:
                predicate_canonical = triple.predicate.canonical_uri or triple.predicate.uri
                value = triple.object.value
                subject_key = str(triple.subject_id)
                if not value or subject_key not in event_details:
                    continue
                if event_start_predicate and predicate_canonical == event_start_predicate:
                    event_details[subject_key]['start'] = value
                elif event_end_predicate and predicate_canonical == event_end_predicate:
                    event_details[subject_key]['end'] = value

        return {
            'event_ids': event_ids,
            'event_details': event_details,
        }

    def get_detailed_event_data(
        self,
        project_id: str,
        *,
        event_predicate: Optional[str],
        event_start_predicate: Optional[str],
        event_end_predicate: Optional[str],
        event_name_predicate: Optional[str] = None,
        event_description_predicate: Optional[str] = None,
        event_location_predicate: Optional[str] = None,
        event_location_wikidata_predicate: Optional[str] = None,
        event_type_predicate: Optional[str] = None,
        organization_code: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return detailed event information including names, descriptions, locations."""

        # First get basic event data
        basic_event_data = self.get_event_data(
            project_id,
            event_predicate=event_predicate,
            event_start_predicate=event_start_predicate,
            event_end_predicate=event_end_predicate,
            organization_code=organization_code,
        )

        event_ids = basic_event_data.get('event_ids', [])
        event_details = basic_event_data.get('event_details', {})

        if not event_ids:
            return []

        # Collect all event property predicates
        event_property_predicates = []
        if event_name_predicate:
            event_property_predicates.append(event_name_predicate)
        if event_description_predicate:
            event_property_predicates.append(event_description_predicate)
        if event_location_predicate:
            event_property_predicates.append(event_location_predicate)
        if event_location_wikidata_predicate:
            event_property_predicates.append(event_location_wikidata_predicate)
        if event_type_predicate:
            event_property_predicates.append(event_type_predicate)

        # Get additional event properties
        event_properties: Dict[str, Dict[str, Dict[str, Optional[str]]]] = {}
        entity_reference_map: Dict[str, set[str]] = defaultdict(set)
        if event_property_predicates:
            property_triples = self._fetch_triples(
                subject_ids=event_ids,
                predicate_uris=event_property_predicates,
                organization_code=organization_code,
            )

            for triple in property_triples:
                event_id = str(triple.subject_id)
                predicate_canonical = triple.predicate.canonical_uri or triple.predicate.uri

                if event_id not in event_properties:
                    event_properties[event_id] = {}

                entry = event_properties[event_id].get(predicate_canonical)
                if not entry:
                    entry = {
                        'value': None,
                        'entity_id': None,
                    }

                if triple.object.resource_type == ResourceType.LITERAL:
                    literal_value = triple.object.value
                    if literal_value:
                        if not entry.get('value') or entry['value'] == entry.get('entity_id'):
                            entry['value'] = literal_value
                        elif literal_value and _looks_placeholder(entry['value']):
                            entry['value'] = literal_value
                else:
                    entity_id = str(triple.object_id)
                    entry['entity_id'] = entity_id
                    entity_reference_map[predicate_canonical].add(entity_id)

                event_properties[event_id][predicate_canonical] = entry

        if entity_reference_map:
            label_predicates_map: Dict[str, Sequence[str]] = {}
            if event_description_predicate:
                label_predicates_map[event_description_predicate] = (
                    "http://arkumu.org/data/properties/ereignisbeschreibung",
                    "http://arkumu.org/data/properties/beschreibung",
                    "http://arkumu.org/data/properties/deutscher-name",
                )
            if event_location_predicate:
                label_predicates_map[event_location_predicate] = (
                    "http://arkumu.org/data/properties/deutscher-name-des-ortes",
                    "http://arkumu.org/data/properties/deutscher-name",
                    "http://arkumu.org/data/properties/name",
                )
            if event_type_predicate:
                label_predicates_map[event_type_predicate] = (
                    "http://arkumu.org/data/properties/deutscher-name-des-ereignistyps",
                    "http://arkumu.org/data/properties/deutscher-name",
                )

            for predicate_uri, entity_ids in entity_reference_map.items():
                label_predicates = label_predicates_map.get(predicate_uri, ())
                resolved_labels = self._resolve_entity_labels(
                    entity_ids,
                    label_predicates,
                    organization_code=organization_code,
                )

                if not resolved_labels:
                    continue

                for event_id, props in event_properties.items():
                    entry = props.get(predicate_uri)
                    if not entry or not entry.get('entity_id'):
                        continue
                    if entry.get('value') and not _looks_placeholder(entry.get('value')):
                        continue
                    label = resolved_labels.get(entry['entity_id'])
                    if label:
                        entry['value'] = label

        # Build detailed event list
        detailed_events = []
        def _extract_property(
            properties: Dict[str, Dict[str, Optional[str]]],
            predicate_uri: Optional[str],
        ) -> tuple[Optional[str], Optional[str]]:
            if not predicate_uri or predicate_uri not in properties:
                return None, None
            entry = properties[predicate_uri]
            if isinstance(entry, dict):
                return entry.get('value'), entry.get('entity_id')
            # Backward compatibility: handle legacy str storage
            return entry, None

        for event_id in event_ids:
            event_info = {
                'id': event_id,
                'start': event_details.get(event_id, {}).get('start'),
                'end': event_details.get(event_id, {}).get('end'),
            }

            # Add additional properties
            properties = event_properties.get(event_id, {})
            name_value, _ = _extract_property(properties, event_name_predicate)
            if name_value:
                event_info['name'] = name_value

            description_value, description_entity_id = _extract_property(properties, event_description_predicate)
            if description_value:
                event_info['description'] = description_value
            elif description_entity_id:
                event_info['description'] = description_entity_id

            location_value, location_entity_id = _extract_property(properties, event_location_predicate)
            wikidata_value, _ = _extract_property(properties, event_location_wikidata_predicate)

            location_identifier = location_entity_id or wikidata_value
            if location_identifier:
                event_info['location_id'] = location_identifier
            elif location_value and location_value.strip().upper().startswith('Q'):
                event_info['location_id'] = location_value.strip()

            location_display = location_value
            if not location_display and wikidata_value:
                location_ids = [loc_id.strip() for loc_id in str(wikidata_value).split(',') if loc_id.strip()]
                if location_ids:
                    cached_entities = {
                        entity.wikidata_id: entity
                        for entity in WikidataEntity.objects.filter(
                            wikidata_id__in=[loc for loc in location_ids if loc.startswith('Q')]
                        )
                    }

                    location_names: List[str] = []
                    for loc_id in location_ids:
                        if loc_id.startswith('Q'):
                            cached_entity = cached_entities.get(loc_id)
                            display_name = (
                                cached_entity.label_de
                                or cached_entity.label_en
                                if cached_entity
                                else None
                            )
                            if not display_name:
                                display_name = self._resolve_location_label(loc_id)
                            location_names.append(display_name or loc_id)
                        else:
                            resolved_label = self._resolve_location_label(loc_id)
                            location_names.append(resolved_label or loc_id)

                    if location_names:
                        location_display = ', '.join(location_names)
                    elif wikidata_value:
                        location_display = str(wikidata_value)

            if not location_display and location_entity_id:
                location_display = self._resolve_location_label(location_entity_id) or location_entity_id

            if location_display and _looks_placeholder(location_display):
                resolved = self._resolve_location_label(location_display)
                if resolved:
                    location_display = resolved

            if location_display:
                event_info['location'] = location_display

            event_type_value, event_type_entity_id = _extract_property(properties, event_type_predicate)
            if not event_type_value and event_type_entity_id:
                event_type_value = self._resolve_entity_labels(
                    [event_type_entity_id],
                    (
                        "http://arkumu.org/data/properties/deutscher-name-des-ereignistyps",
                        "http://arkumu.org/data/properties/deutscher-name",
                    ),
                    organization_code=organization_code,
                ).get(event_type_entity_id)

            event_info['type'] = event_type_value

            detailed_events.append(event_info)

        return detailed_events

    def get_alternative_titles(
        self,
        project_id: str,
        *,
        alternative_title_set_predicate: Optional[str],
        alternative_title_predicate: Optional[str],
        organization_code: Optional[str] = None,
    ) -> List[str]:
        """Return alternative titles for the project."""

        if not alternative_title_set_predicate or not alternative_title_predicate:
            return []

        # Get alternative title entities
        alt_title_entities = self.get_related_entities(
            project_id,
            alternative_title_set_predicate,
            organization_code=organization_code,
        )

        alt_title_ids = [entry['id'] for entry in alt_title_entities if self._is_entity(entry)]
        if not alt_title_ids:
            return []

        # Get actual alternative title values
        title_map = self._collect_literal_values(
            subject_ids=alt_title_ids,
            predicate_uri=alternative_title_predicate,
            organization_code=organization_code,
        )

        results = []
        for alt_id in alt_title_ids:
            title = title_map.get(alt_id)
            if title and title.strip() and title.strip() not in results:
                results.append(title.strip())

        return results

    def get_project_description(
        self,
        project_id: str,
        *,
        description_predicate: Optional[str],
        organization_code: Optional[str] = None,
    ) -> Optional[str]:
        """Return project description."""

        if not description_predicate:
            return None

        descriptions = self._collect_literal_values(
            subject_ids=[project_id],
            predicate_uri=description_predicate,
            organization_code=organization_code,
        )
        description_value = descriptions.get(project_id)

        entity_entries = self.get_related_entities(
            project_id,
            description_predicate,
            organization_code=organization_code,
        )
        entity_ids = [entry['id'] for entry in entity_entries if self._is_entity(entry)]

        if entity_ids:
            label_map = self._collect_literal_values(
                subject_ids=entity_ids,
                predicate_uri='http://arkumu.org/data/properties/beschreibung',
                organization_code=organization_code,
            )
            for entity_id in entity_ids:
                label = label_map.get(entity_id)
                if label:
                    return label

        return description_value

    def get_project_type(
        self,
        project_id: str,
        *,
        project_type_predicate: Optional[str],
        organization_code: Optional[str] = None,
    ) -> Optional[str]:
        """Return project type resolved to German name."""

        if not project_type_predicate:
            return None

        project_types = self._collect_literal_values(
            subject_ids=[project_id],
            predicate_uri=project_type_predicate,
            organization_code=organization_code,
        )

        project_type_id = project_types.get(project_id)
        # Collect related project type entities (if any) for richer resolution
        entity_entries = self.get_related_entities(
            project_id,
            project_type_predicate,
            organization_code=organization_code,
        )
        entity_ids = [entry['id'] for entry in entity_entries if self._is_entity(entry)]

        if entity_ids:
            label_map = self._collect_literal_values(
                subject_ids=entity_ids,
                predicate_uri='http://arkumu.org/data/properties/deutscher-name-der-projektart',
                organization_code=organization_code,
            )
            for entity_id in entity_ids:
                label = label_map.get(entity_id)
                if label:
                    return label

            # Fallback to resource name if literal label missing
            from arkumu.metadata.models import Resource

            for entity_id in entity_ids:
                try:
                    resource = Resource.objects.filter(id=entity_id).first()
                except Exception:  # pragma: no cover - defensive
                    resource = None
                if resource and resource.name:
                    return resource.name

        if not project_type_id:
            return None

        # Resolve project type ID to German name
        return self._resolve_project_type_name(project_type_id)

    def _resolve_project_type_name(self, project_type_id: str) -> Optional[str]:
        """Resolve project type ID to German name (e.g., '1' -> 'Bachelorarbeit')."""
        if not project_type_id:
            return None

        # Construct the project type entity URI
        project_type_uri = f"http://arkumu.org/data/fuk/entities/projektart/{project_type_id}"

        try:
            from arkumu.metadata.models import Resource, Triple, ResourceType

            # Get the project type entity
            project_type_entity = Resource.objects.filter(uri=project_type_uri).first()
            if not project_type_entity:
                return None

            # Get the German name
            german_name_triple = Triple.objects.filter(
                subject=project_type_entity,
                predicate__canonical_uri='http://arkumu.org/data/properties/deutscher-name-der-projektart'
            ).first()

            if german_name_triple and german_name_triple.object:
                return german_name_triple.object.value

        except Exception as exc:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to resolve project type '{project_type_id}': {exc}")

        return None

    def get_catchphrases(
        self,
        project_id: str,
        *,
        catchphrase_predicate: Optional[str],
        catchphrase_label_predicate: Optional[str],
        organization_code: Optional[str] = None,
    ) -> List[str]:
        """Return catchphrase labels for the project."""

        if not catchphrase_predicate or not catchphrase_label_predicate:
            return []

        # Get catchphrase entities
        catchphrase_entities = self.get_related_entities(
            project_id,
            catchphrase_predicate,
            organization_code=organization_code,
        )

        catchphrase_ids = [entry['id'] for entry in catchphrase_entities if self._is_entity(entry)]
        if not catchphrase_ids:
            return []

        # Get catchphrase labels
        label_map = self._collect_literal_values(
            subject_ids=catchphrase_ids,
            predicate_uri=catchphrase_label_predicate,
            organization_code=organization_code,
        )

        results = []
        for catchphrase_id in catchphrase_ids:
            label = label_map.get(catchphrase_id)
            if label and label.strip() and label.strip() not in results:
                results.append(label.strip())

        return results

    def get_actor_relationships(
        self,
        project_id: str,
        *,
        event_predicate: Optional[str],
        actor_link_predicate: Optional[str],
        role_link_predicate: Optional[str],
        actor_name_predicate: Optional[str],
        role_name_predicate: Optional[str],
        event_ids: Optional[Sequence[str]] = None,
        organization_code: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return actors with collected roles for the project."""

        if not actor_link_predicate:
            return []

        if event_ids is None:
            event_data = self.get_event_data(
                project_id,
                event_predicate=event_predicate,
                event_start_predicate=None,
                event_end_predicate=None,
                organization_code=organization_code,
            )
            event_ids = event_data['event_ids']

        if not event_ids:
            return self._direct_project_actor_edges(
                project_id,
                actor_link_predicate=actor_link_predicate,
                actor_name_predicate=actor_name_predicate,
                organization_code=organization_code,
            )

        # First find crosstables that link TO these events (reverse lookup)
        im_ereignis_predicate = 'http://arkumu.org/data/properties/im-ereignis'
        crosstable_triples = self._fetch_triples(
            object_ids=list(event_ids),
            predicate_uris=[im_ereignis_predicate],
            organization_code=organization_code,
        )

        crosstable_ids: set[str] = set()
        crosstable_to_events: Dict[str, set[str]] = defaultdict(set)
        for triple in crosstable_triples:
            crosstable_id = str(triple.subject_id)
            event_id = str(triple.object_id)
            crosstable_ids.add(crosstable_id)
            crosstable_to_events[crosstable_id].add(event_id)

        if not crosstable_ids:
            event_results = self._actors_from_event_edges(
                event_ids,
                actor_link_predicate=actor_link_predicate,
                role_link_predicate=role_link_predicate,
                actor_name_predicate=actor_name_predicate,
                role_name_predicate=role_name_predicate,
                organization_code=organization_code,
            )
            if event_results:
                return event_results
            return self._direct_project_actor_edges(
                project_id,
                actor_link_predicate=actor_link_predicate,
                actor_name_predicate=actor_name_predicate,
                organization_code=organization_code,
            )

        relation_predicates = [p for p in [actor_link_predicate, role_link_predicate] if p]
        actor_role_triples = self._fetch_triples(
            subject_ids=list(crosstable_ids),
            predicate_uris=relation_predicates,
            organization_code=organization_code,
        )

        crosstable_actor_map: Dict[str, str] = {}
        crosstable_role_map: Dict[str, set[str]] = defaultdict(set)
        for triple in actor_role_triples:
            predicate_canonical = triple.predicate.canonical_uri or triple.predicate.uri
            obj = triple.object
            if obj.resource_type == ResourceType.LITERAL:
                continue
            subject_key = str(triple.subject_id)
            object_id = str(obj.id)
            if predicate_canonical == actor_link_predicate:
                crosstable_actor_map[subject_key] = object_id
            elif role_link_predicate and predicate_canonical == role_link_predicate:
                crosstable_role_map[subject_key].add(object_id)

        if not crosstable_actor_map:
            event_results = self._actors_from_event_edges(
                event_ids,
                actor_link_predicate=actor_link_predicate,
                role_link_predicate=role_link_predicate,
                actor_name_predicate=actor_name_predicate,
                role_name_predicate=role_name_predicate,
                organization_code=organization_code,
            )
            if event_results:
                return event_results
            return self._direct_project_actor_edges(
                project_id,
                actor_link_predicate=actor_link_predicate,
                actor_name_predicate=actor_name_predicate,
                organization_code=organization_code,
            )

        actor_ids = list({actor_id for actor_id in crosstable_actor_map.values()})
        role_ids = list({role_id for roles in crosstable_role_map.values() for role_id in roles})

        actor_names = self._collect_literal_values(
            subject_ids=actor_ids,
            predicate_uri=actor_name_predicate,
            organization_code=organization_code,
        ) if actor_name_predicate else {}

        role_names = self._collect_literal_values(
            subject_ids=role_ids,
            predicate_uri=role_name_predicate,
            organization_code=organization_code,
        ) if role_name_predicate and role_ids else {}

        if role_names:
            for role_id, value in list(role_names.items()):
                if not value:
                    continue
                role_names[role_id] = value.split('>')[-1].strip() if '>' in value else value.strip()

        actors: Dict[str, Dict[str, Any]] = {}
        for crosstable_id, actor_id in crosstable_actor_map.items():
            entry = actors.setdefault(
                actor_id,
                {
                    'event_ids': set(),
                    'roles': set(),
                },
            )
            entry['event_ids'].update(crosstable_to_events.get(crosstable_id, set()))
            for role_id in crosstable_role_map.get(crosstable_id, set()):
                role_label = role_names.get(role_id)
                if role_label:
                    entry['roles'].add(role_label)

        results: List[Dict[str, Any]] = []
        for actor_id, payload in actors.items():
            name = actor_names.get(actor_id)
            if not name:
                continue
            results.append(
                {
                    'id': actor_id,
                    'name': name,
                    'roles': sorted(payload['roles']),
                    'event_ids': sorted(payload['event_ids']),
                }
            )

        if results:
            return sorted(results, key=lambda item: item['name'])

        event_results = self._actors_from_event_edges(
            event_ids,
            actor_link_predicate=actor_link_predicate,
            role_link_predicate=role_link_predicate,
            actor_name_predicate=actor_name_predicate,
            role_name_predicate=role_name_predicate,
            organization_code=organization_code,
        )
        if event_results:
            return event_results

        return self._direct_project_actor_edges(
            project_id,
            actor_link_predicate=actor_link_predicate,
            actor_name_predicate=actor_name_predicate,
            organization_code=organization_code,
        )

    def _actors_from_event_edges(
        self,
        event_ids: Sequence[str],
        *,
        actor_link_predicate: str,
        role_link_predicate: Optional[str],
        actor_name_predicate: Optional[str],
        role_name_predicate: Optional[str],
        organization_code: Optional[str],
    ) -> List[Dict[str, Any]]:
        if not event_ids:
            return []

        relation_predicates = [actor_link_predicate]
        if role_link_predicate:
            relation_predicates.append(role_link_predicate)

        triples = self._fetch_triples(
            subject_ids=list(event_ids),
            predicate_uris=relation_predicates,
            organization_code=organization_code,
        )

        direct_event_actor_map: Dict[str, set[str]] = defaultdict(set)
        crosstable_event_map: Dict[str, set[str]] = defaultdict(set)

        object_ids: set[str] = set()
        for triple in triples:
            predicate_canonical = triple.predicate.canonical_uri or triple.predicate.uri
            obj = triple.object
            if obj.resource_type == ResourceType.LITERAL:
                continue
            if predicate_canonical != actor_link_predicate:
                continue
            event_id = str(triple.subject_id)
            target_id = str(obj.id)
            object_ids.add(target_id)
            direct_event_actor_map[event_id].add(target_id)

        actor_names = self._collect_literal_values(
            subject_ids=list(object_ids),
            predicate_uri=actor_name_predicate,
            organization_code=organization_code,
        ) if object_ids and actor_name_predicate else {}

        for event_id, targets in list(direct_event_actor_map.items()):
            for target_id in list(targets):
                if actor_names.get(target_id):
                    continue
                # Treat as crosstable candidate
                targets.remove(target_id)
                crosstable_event_map[event_id].add(target_id)

        crosstable_ids = {cid for ids in crosstable_event_map.values() for cid in ids}
        crosstable_actor_map: Dict[str, str] = {}
        crosstable_role_map: Dict[str, set[str]] = defaultdict(set)

        if crosstable_ids:
            crosstable_triples = self._fetch_triples(
                subject_ids=list(crosstable_ids),
                predicate_uris=relation_predicates,
                organization_code=organization_code,
            )
            for triple in crosstable_triples:
                predicate_canonical = triple.predicate.canonical_uri or triple.predicate.uri
                obj = triple.object
                if obj.resource_type == ResourceType.LITERAL:
                    continue
                crosstable_id = str(triple.subject_id)
                object_id = str(obj.id)
                if predicate_canonical == actor_link_predicate:
                    crosstable_actor_map[crosstable_id] = object_id
                elif role_link_predicate and predicate_canonical == role_link_predicate:
                    crosstable_role_map[crosstable_id].add(object_id)

            derived_actor_ids = list(crosstable_actor_map.values())
            if derived_actor_ids and actor_name_predicate:
                actor_names.update(
                    self._collect_literal_values(
                        subject_ids=derived_actor_ids,
                        predicate_uri=actor_name_predicate,
                        organization_code=organization_code,
                    )
                )

        role_labels: Dict[str, str] = {}
        if role_link_predicate and role_name_predicate:
            role_ids = sorted({
                role_id
                for crosstable_roles in crosstable_role_map.values()
                for role_id in crosstable_roles
            })
            if role_ids:
                role_names = self._collect_literal_values(
                    subject_ids=role_ids,
                    predicate_uri=role_name_predicate,
                    organization_code=organization_code,
                )
                role_labels = {
                    role_id: (value.split('>')[-1].strip() if value and '>' in value else value)
                    for role_id, value in role_names.items()
                    if value
                }

        actor_payload: Dict[str, Dict[str, Any]] = {}

        for event_id, actor_ids in direct_event_actor_map.items():
            for actor_id in actor_ids:
                payload = actor_payload.setdefault(
                    actor_id,
                    {
                        'event_ids': set(),
                        'roles': set(),
                    },
                )
                payload['event_ids'].add(event_id)

        for event_id, crosstables in crosstable_event_map.items():
            for crosstable_id in crosstables:
                actor_id = crosstable_actor_map.get(crosstable_id)
                if not actor_id:
                    continue
                payload = actor_payload.setdefault(
                    actor_id,
                    {
                        'event_ids': set(),
                        'roles': set(),
                    },
                )
                payload['event_ids'].add(event_id)
                for role_id in crosstable_role_map.get(crosstable_id, set()):
                    label = role_labels.get(role_id)
                    if label:
                        payload['roles'].add(label)

        results: List[Dict[str, Any]] = []
        for actor_id, payload in actor_payload.items():
            name = actor_names.get(actor_id)
            if not name:
                continue
            results.append(
                {
                    'id': actor_id,
                    'name': name,
                    'roles': sorted(payload['roles']),
                    'event_ids': sorted(payload['event_ids']),
                }
            )

        return sorted(results, key=lambda item: item['name'])

    def _direct_project_actor_edges(
        self,
        project_id: str,
        *,
        actor_link_predicate: str,
        actor_name_predicate: Optional[str],
        organization_code: Optional[str],
    ) -> List[Dict[str, Any]]:
        """Fallback using direct project→actor edges when crosstables are unavailable."""

        ACTOR_CANONICAL_URI = "http://arkumu.org/data/properties/akteurin"

        predicate_candidates = [actor_link_predicate]
        if actor_link_predicate != ACTOR_CANONICAL_URI:
            predicate_candidates.append(ACTOR_CANONICAL_URI)

        triples = self._fetch_triples(
            subject_ids=[project_id],
            predicate_uris=predicate_candidates,
            organization_code=organization_code,
        )

        actor_ids: List[str] = []
        for triple in triples:
            obj = triple.object
            if obj.resource_type == ResourceType.LITERAL:
                continue
            predicate_canonical = triple.predicate.canonical_uri or triple.predicate.uri
            if predicate_canonical not in predicate_candidates:
                continue
            actor_ids.append(str(obj.id))

        actor_ids = list(dict.fromkeys(actor_ids))
        if not actor_ids:
            return []

        actor_names = self._collect_literal_values(
            subject_ids=actor_ids,
            predicate_uri=actor_name_predicate,
            organization_code=organization_code,
        ) if actor_name_predicate else {}

        results: List[Dict[str, Any]] = []
        for actor_id in actor_ids:
            name = actor_names.get(actor_id)
            if not name:
                try:
                    actor_resource = Resource.objects.only('name', 'value').get(id=actor_id)
                    name = actor_resource.name or actor_resource.value
                except Resource.DoesNotExist:  # pragma: no cover - defensive
                    name = None
            if not name:
                continue
            results.append(
                {
                    'id': actor_id,
                    'name': name,
                    'roles': [],
                    'event_ids': [],
                }
            )

        return sorted(results, key=lambda item: item['name'])

    def get_digital_object_paths(
        self,
        project_id: str,
        *,
        link_predicate: Optional[str],
        path_predicate: Optional[str],
        organization_code: Optional[str] = None,
    ) -> List[str]:
        """Return normalized digital object paths for the project."""

        digital_objects = self.get_related_entities(
            project_id,
            link_predicate,
            organization_code=organization_code,
        )
        object_ids = [entry['id'] for entry in digital_objects if self._is_entity(entry)]
        if not object_ids or not path_predicate:
            return []

        path_map = self._collect_literal_values(
            subject_ids=object_ids,
            predicate_uri=path_predicate,
            organization_code=organization_code,
        )

        results: List[str] = []
        for object_id in object_ids:
            value = path_map.get(object_id)
            if not value:
                continue
            normalized = value.strip()
            if normalized and normalized not in results:
                results.append(normalized)
        return results

    def get_literal_map(
        self,
        subject_ids: Sequence[str],
        predicate_uri: Optional[str],
        *,
        organization_code: Optional[str] = None,
    ) -> Dict[str, str]:
        """Return a mapping of subject ID to literal value for the predicate."""

        return self._collect_literal_values(
            subject_ids=subject_ids,
            predicate_uri=predicate_uri,
            organization_code=organization_code,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _collect_literal_values(
        self,
        *,
        subject_ids: Sequence[str],
        predicate_uri: Optional[str],
        organization_code: Optional[str] = None,
    ) -> Dict[str, str]:
        if not predicate_uri or not subject_ids:
            return {}

        triples = self._fetch_triples(
            subject_ids=list(subject_ids),
            predicate_uris=[predicate_uri],
            organization_code=organization_code,
        )

        values: Dict[str, str] = {}
        for triple in triples:
            obj = triple.object
            if obj.resource_type != ResourceType.LITERAL or not obj.value:
                continue
            subject_key = str(triple.subject_id)
            values.setdefault(subject_key, obj.value)
        return values

    def _fetch_triples(
        self,
        *,
        subject_ids: Optional[Sequence[str]] = None,
        object_ids: Optional[Sequence[str]] = None,
        predicate_uris: Optional[Sequence[str]] = None,
        organization_code: Optional[str] = None,
    ) -> Iterable[Triple]:
        qs = (
            Triple.objects.select_related('predicate', 'object')
            .only(
                'id',
                'subject_id',
                'predicate__uri',
                'predicate__canonical_uri',
                'object__id',
                'object__uri',
                'object__canonical_uri',
                'object__name',
                'object__value',
                'object__resource_type',
            )
        )

        qs = self._apply_organization_scope(qs, organization_code)

        if subject_ids:
            qs = qs.filter(subject_id__in=subject_ids)
        if object_ids:
            qs = qs.filter(object_id__in=object_ids)
        if predicate_uris:
            predicates = [uri for uri in predicate_uris if uri]
            if predicates:
                qs = qs.filter(
                    Q(predicate__canonical_uri__in=predicates)
                    | Q(predicate__uri__in=predicates)
                )

        return qs.iterator(chunk_size=1000)

    def _apply_organization_scope(self, qs, organization_code: Optional[str]):
        organization = self._get_org_by_code(organization_code)
        if organization:
            return qs.filter(Q(source=organization) | Q(source__isnull=True))
        if self._organization:
            return qs.filter(Q(source=self._organization) | Q(source__isnull=True))
        return qs

    def _get_org_by_code(self, organization_code: Optional[str]) -> Optional[Organization]:
        if not organization_code:
            return None
        if organization_code == self.organization_code and self._organization:
            return self._organization
        if organization_code in self._org_cache:
            return self._org_cache[organization_code]
        org = Organization.objects.filter(code=organization_code).first()
        self._org_cache[organization_code] = org
        return org

    @staticmethod
    def _is_entity(entry: Dict[str, Any]) -> bool:
        return entry.get('resource_type') != ResourceType.LITERAL
