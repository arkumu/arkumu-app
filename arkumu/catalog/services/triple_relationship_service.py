"""Triple-based relationship helpers for catalog cards."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence

from django.db.models import Q

from arkumu.metadata.models.triples import Triple
from arkumu.metadata.models.resource import ResourceType
from arkumu.users.models import Organization


class TripleRelationshipService:
    """Service for traversing catalog relationships using Triple records."""

    def __init__(self, organization_code: Optional[str] = None) -> None:
        self.organization_code = organization_code
        self._organization: Optional[Organization] = None
        self._org_cache: Dict[str, Optional[Organization]] = {}
        if organization_code:
            self._organization = self._get_org_by_code(organization_code)

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
            return []

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
            return []

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
            return []

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
