from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from django.db import transaction
from django.db.models import Q

from arkumu.metadata.canonical import canonical_uri
from arkumu.metadata.derivations.kreuz_config import (
    DCTERMS_IS_PART_OF,
    SUBJECT_PLACEHOLDER,
    all_configured_canonical_properties,
)
from arkumu.metadata.models import Resource, ResourceType, Triple
from arkumu.metadata.services.junction_pattern_service import JunctionPatternService

PROJECT = canonical_uri("project")
DIGITAL_OBJECT = canonical_uri("digital_object")
ACTOR_IN_EVENT = canonical_uri("actor_in_event")


@dataclass
class SubjectContext:
    subject_id: str
    dataset_name: Optional[str]
    canonical_objects: Dict[str, Set[str]] = field(default_factory=dict)


@dataclass
class DerivationStats:
    processed: int = 0
    created: int = 0


class DerivedRelationshipService:
    """Derive relationship triples from Kreuz-based junction datasets."""

    def __init__(self, organization_code: str, *, mapping_config: Optional[Mapping[str, object]] = None):
        self.organization_code = organization_code.lower()
        self.mapping_config = mapping_config or {}
        self._canonical_uris: Set[str] = set(all_configured_canonical_properties())
        self._canonical_filter: Q = self._build_predicate_filter(self._canonical_uris)
        self._dataset_filter: Q = self._build_predicate_filter({DCTERMS_IS_PART_OF})
        self._resource_cache: Dict[str, Optional[Resource]] = {}
        self._predicate_cache: Dict[str, Optional[Resource]] = {}
        self._pattern_service = JunctionPatternService(
            mapping_config=self.mapping_config,
            organization_code=self.organization_code,
            include_static_patterns=True,
        )

    def derive(self, *, dry_run: bool = False) -> DerivationStats:
        stats = DerivationStats()
        created_category_links = self._materialize_literal_categories(dry_run=dry_run)
        stats.created += created_category_links
        contexts = self._collect_subject_contexts()
        stats.processed = len(contexts)
        stats.created += self._derive_for_contexts(contexts, dry_run=dry_run)
        stats.created += self._derive_project_actor_links(contexts, dry_run=dry_run)
        stats.created += self._derive_event_digital_links(dry_run=dry_run)
        return stats

    # ------------------------------------------------------------------
    # Discovery helpers
    # ------------------------------------------------------------------
    def _build_predicate_filter(self, uris: Iterable[str]) -> Q:
        uris = tuple(set(uris))
        return Q(predicate__canonical_uri__in=uris) | Q(predicate__uri__in=uris)

    def _collect_subject_contexts(self) -> Dict[str, SubjectContext]:
        junction_subjects = set(
            Triple.objects.filter(self._canonical_filter, subject__organization__code=self.organization_code)
            .filter(object__resource_type=ResourceType.ENTITY)
            .values_list("subject_id", flat=True)
        )
        if not junction_subjects:
            return {}

        dataset_map: Dict[str, Optional[str]] = {}
        dataset_links = (
            Triple.objects.filter(subject_id__in=junction_subjects)
            .filter(self._dataset_filter)
            .select_related("object")
        )
        for link in dataset_links:
            dataset_name = link.object.name or link.object.value or link.object.uri
            dataset_map[str(link.subject_id)] = dataset_name

        property_triples = (
            Triple.objects.filter(subject_id__in=junction_subjects)
            .filter(self._canonical_filter)
            .filter(object__resource_type=ResourceType.ENTITY)
            .select_related("predicate")
        )

        contexts: Dict[str, SubjectContext] = {
            str(subject_id): SubjectContext(
                subject_id=str(subject_id),
                dataset_name=dataset_map.get(str(subject_id)),
            )
            for subject_id in junction_subjects
        }

        for triple in property_triples:
            subject_id = str(triple.subject_id)
            context = contexts.get(subject_id)
            if not context:
                continue
            canonical_uri = triple.predicate.canonical_uri or triple.predicate.uri
            if canonical_uri not in self._canonical_uris:
                continue
            context.canonical_objects.setdefault(canonical_uri, set()).add(str(triple.object_id))

        return {
            subject_id: ctx
            for subject_id, ctx in contexts.items()
            if ctx.canonical_objects
        }

    # ------------------------------------------------------------------
    # Derivation logic
    # ------------------------------------------------------------------
    def _derive_for_contexts(self, contexts: Mapping[str, SubjectContext], *, dry_run: bool) -> int:
        created = 0
        grouped: Dict[str, List[Tuple[str, SubjectContext]]] = defaultdict(list)
        for subject_id, ctx in contexts.items():
            label = ctx.dataset_name or "<unknown dataset>"
            grouped[label].append((subject_id, ctx))

        for dataset_label in sorted(grouped.keys()):
            entries = grouped[dataset_label]
            for subject_id, ctx in entries:
                patterns = self._pattern_service.iter_patterns(
                    dataset_name=ctx.dataset_name,
                    canonical_predicates=ctx.canonical_objects.keys(),
                )
                if not patterns:
                    continue
                created += self._apply_patterns(subject_id, ctx, patterns, dry_run=dry_run)
        return created

    def _materialize_literal_categories(self, *, dry_run: bool) -> int:
        category_literal = "http://arkumu.org/data/properties/synonyme"
        category_link = "http://arkumu.org/data/properties/projektkategorie"

        literal_triples = list(
            Triple.objects.filter(
                predicate__canonical_uri=category_literal,
                subject__organization__code=self.organization_code,
                object__resource_type=ResourceType.LITERAL,
            ).select_related("subject", "object", "subject__organization")
        )
        if not literal_triples:
            return 0

        created = 0
        for triple in literal_triples:
            subject = triple.subject
            organization = subject.organization
            if not subject or subject.resource_type != ResourceType.ENTITY:
                continue

            raw_value = (triple.object.value or "").replace(";", ",")
            tokens = [token.strip() for token in raw_value.split(",") if token.strip()]
            if not tokens:
                continue

            for token in tokens:
                entity_uri = f"http://arkumu.org/data/{self.organization_code}/entities/projektkategorie/{token}"
                category_resource = Resource.objects.filter(uri=entity_uri).first()
                if not category_resource and not dry_run:
                    category_resource = Resource.objects.create(
                        uri=entity_uri,
                        resource_type=ResourceType.ENTITY,
                        organization=organization,
                        name=token,
                        is_placeholder=True,
                    )

                if not category_resource:
                    continue

                created += self._emit_derived_triple(
                    str(subject.id),
                    category_link,
                    str(category_resource.id),
                    dry_run=dry_run,
                    pattern_name="project_category_literal_bridge",
                    source_subject=str(triple.subject_id),
                )
        return created

    def _apply_patterns(
        self,
        subject_id: str,
        context: SubjectContext,
        patterns: Sequence,
        *,
        dry_run: bool,
    ) -> int:
        created = 0

        def _resolve_values(key: Optional[str]) -> Optional[Set[str]]:
            if not key:
                return None
            if key == SUBJECT_PLACEHOLDER:
                return {context.subject_id}
            return context.canonical_objects.get(key)

        for pattern in patterns:
            for recipe in pattern.recipes:
                subjects = _resolve_values(recipe.subject_property)
                targets = _resolve_values(recipe.object_property)
                if not subjects or not targets:
                    continue
                for derived_subject_id in subjects:
                    for derived_object_id in targets:
                        created += self._emit_derived_triple(
                            derived_subject_id,
                            recipe.predicate_uri,
                            derived_object_id,
                            dry_run=dry_run,
                            pattern_name=pattern.name,
                            source_subject=subject_id,
                        )
        return created

    # ------------------------------------------------------------------
    # Triple emission helpers
    # ------------------------------------------------------------------
    def _emit_derived_triple(
        self,
        subject_resource_id: str,
        predicate_uri: str,
        object_resource_id: str,
        *,
        dry_run: bool,
        pattern_name: str,
        source_subject: str,
    ) -> int:
        predicate = self._get_predicate_resource(predicate_uri)
        subject_resource = self._get_resource(subject_resource_id)
        object_resource = self._get_resource(object_resource_id)
        if not predicate or not subject_resource or not object_resource:
            return 0

        message = (
            f"{subject_resource_id} --[{predicate_uri}]--> {object_resource_id}"
            f" (pattern={pattern_name}, junction={source_subject})"
        )
        if dry_run:
            return 0

        with transaction.atomic():
            triple, created = Triple.objects.get_or_create(
                subject=subject_resource,
                predicate=predicate,
                object=object_resource,
                defaults={"is_derived": True, "source": None},
            )
            if created:
                return 1
            if not triple.is_derived or triple.source_id is not None:
                Triple.objects.filter(pk=triple.pk).update(is_derived=True, source=None)
        return 0

    def _get_resource(self, resource_id: str) -> Optional[Resource]:
        if resource_id not in self._resource_cache:
            self._resource_cache[resource_id] = Resource.objects.filter(id=resource_id).first()
        return self._resource_cache[resource_id]

    def _get_predicate_resource(self, predicate_uri: str) -> Optional[Resource]:
        if predicate_uri in self._predicate_cache:
            return self._predicate_cache[predicate_uri]

        predicate = Resource.objects.filter(uri=predicate_uri).first()
        if not predicate:
            predicate = Resource.objects.filter(canonical_uri=predicate_uri).first()
        if not predicate:
            predicate = Resource.objects.create(
                uri=predicate_uri,
                resource_type=ResourceType.PROPERTY,
            )
        self._predicate_cache[predicate_uri] = predicate
        return predicate

    # ------------------------------------------------------------------
    # Bridge helpers
    # ------------------------------------------------------------------
    def _derive_event_digital_links(self, *, dry_run: bool) -> int:
        digital_predicate = DIGITAL_OBJECT
        project_predicate = PROJECT
        project_to_digitals: Dict[str, Set[str]] = defaultdict(set)
        triples = Triple.objects.filter(
            predicate__canonical_uri=digital_predicate,
            subject__organization__code=self.organization_code,
            object__resource_type=ResourceType.ENTITY,
        ).values_list("subject_id", "object_id")

        for subject_id, object_id in triples:
            project_to_digitals[str(subject_id)].add(str(object_id))

        event_to_projects: Dict[str, Set[str]] = defaultdict(set)
        event_project_triples = Triple.objects.filter(
            predicate__canonical_uri=project_predicate,
            subject__organization__code=self.organization_code,
            object__resource_type=ResourceType.ENTITY,
        ).values_list("subject_id", "object_id")

        for subject_id, object_id in event_project_triples:
            event_to_projects[str(subject_id)].add(str(object_id))

        created = 0
        for event_id, project_ids in event_to_projects.items():
            digital_ids: Set[str] = set()
            for project_id in project_ids:
                digital_ids.update(project_to_digitals.get(project_id, set()))
            for digital_id in digital_ids:
                created += self._emit_derived_triple(
                    event_id,
                    digital_predicate,
                    digital_id,
                    dry_run=dry_run,
                    pattern_name="event_digital_bridge",
                    source_subject=event_id,
                )
        return created

    def _derive_project_actor_links(self, contexts: Mapping[str, SubjectContext], *, dry_run: bool) -> int:
        predicate_uri = ACTOR_IN_EVENT
        created = 0
        for subject_id, ctx in contexts.items():
            projects = ctx.canonical_objects.get(PROJECT)
            actors = ctx.canonical_objects.get(predicate_uri)
            if not projects or not actors:
                continue
            for project_id in projects:
                for actor_id in actors:
                    created += self._emit_derived_triple(
                        project_id,
                        predicate_uri,
                        actor_id,
                        dry_run=dry_run,
                        pattern_name="project_actor_bridge",
                        source_subject=subject_id,
                    )
        return created
