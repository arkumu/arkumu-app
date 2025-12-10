"""Promote legacy Kreuz (junction) rows to canonical entity relationships.

This command inspects selected legacy junction datasets (e.g. Projekt_Projekt,
AkteurIn_AkteurIn, Ereignis_Ereignis) and derives direct triples between the
canonical entities they reference. Relationship context literals (such as
"hat Teil" or "ist Vater von") are transformed into new predicates with a
predictable naming scheme (``<dataset-prefix>-<context-slug>``). The derived
triples are marked as ``is_derived`` so provenance remains explicit while
keeping day-to-day editing on the canonical entities lightweight.

Example:

    Junction row: Projekt_Projekt_Kreuztabelle
        Ausgangsprojekt -> Projekt A
        Verknüpftes Projekt -> Projekt B
        Beziehung -> "hat Teil"

    Derived triple:
        Projekt A -- projekt-hat-teil --> Projekt B

The command reuses existing predicate resources when possible and will mint
new property URIs that include the source dataset name, allowing future audits
to trace the origin of the relationship.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, Optional, Sequence, Set

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from arkumu.common.uri_utils import (
    DEFAULT_INSTITUTION_BASE_URI,
    mint_uri,
    normalize_text_input,
    slugify_uri_part,
)
from arkumu.metadata.models import Resource, ResourceType, Triple
from arkumu.users.models import Organization

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JunctionSpec:
    """Configuration describing how to interpret a legacy junction dataset."""

    dataset_name: str
    subject_predicate: str  # canonical URI for the "self" FK (Ausgangs-*)
    object_predicate: str  # canonical URI for the related FK (Verknüpftes *)
    context_predicate: str  # canonical URI for the literal relation label
    predicate_prefix: str  # Prefix used when minting canonical predicates


JUNCTION_SPECS: Sequence[JunctionSpec] = (
    JunctionSpec(
        dataset_name="Projekt_Projekt_Kreuztabelle",
        subject_predicate="http://arkumu.org/data/properties/ausgangsprojekt",
        object_predicate="http://arkumu.org/data/properties/verknuepftes-projekt",
        context_predicate="http://arkumu.org/data/properties/beziehung",
        predicate_prefix="projekt",
    ),
    JunctionSpec(
        dataset_name="AkteurIn_AkteurIn_Kreuztabelle",
        subject_predicate="http://arkumu.org/data/properties/ausgangsakteurin",
        object_predicate="http://arkumu.org/data/properties/verknuepfter-akteurin",
        context_predicate="http://arkumu.org/data/properties/beziehung",
        predicate_prefix="akteurin",
    ),
    JunctionSpec(
        dataset_name="Ereignis_Ereignis_Kreuztabelle",
        subject_predicate="http://arkumu.org/data/properties/ausgangsereignis",
        object_predicate="http://arkumu.org/data/properties/verknuepftes-ereignis",
        context_predicate="http://arkumu.org/data/properties/beziehung",
        predicate_prefix="ereignis",
    ),
)

ACTOR_EVENT_DATASET = "AkteurIn_Ereignis_Kreuztabelle"
ACTOR_EVENT_ACTOR_PREDICATE = "http://arkumu.org/data/properties/akteurin-im-ereignis"
ACTOR_EVENT_EVENT_PREDICATE = "http://arkumu.org/data/properties/im-ereignis"
ACTOR_EVENT_ROLE_PREDICATE = "http://arkumu.org/data/properties/rollen-der-akteurin-im-ereignis"
ACTOR_EVENT_ROLE_LABEL = "hat Rolle im Ereignis"
ACTOR_EVENT_ROLE_PREFIX = "akteurin"



class PredicateMintingService:
    """Helper for minting (and caching) predicates for a given organisation."""

    def __init__(self, organization: Organization, base_uri: str) -> None:
        self.organization = organization
        self.base_uri = base_uri.rstrip("/")
        self._predicate_cache: Dict[tuple[str, str], Resource] = {}

    def ensure_predicate(self, prefix: str, label: str) -> Resource:
        """Return (and create if needed) the predicate for ``label``.

        ``prefix`` represents the dataset domain (e.g. "projekt"). ``label``
        is the human readable relationship context such as "hat Teil". The
        returned predicate belongs to the organisation and carries a canonical
        URI that omits the organisation code so that clients can match against
        shared semantics across archives.
        """

        normalized = normalize_text_input(label, blank_to_none=True)
        if not normalized:
            raise ValueError("Cannot mint predicate for empty relationship label")

        slug = slugify_uri_part(normalized)
        if not slug or slug == "n-a":
            raise ValueError(f"Unable to slugify relationship label '{label}'")

        identifier = f"{prefix}-{slug}"
        cache_key = (prefix, normalized)
        cached = self._predicate_cache.get(cache_key)
        if cached:
            return cached

        canonical_base = self.base_uri  # Canonical properties share the same base
        canonical_uri = mint_uri(canonical_base, "properties", identifier)
        org_uri = mint_uri(self.base_uri, self.organization.code, "properties", identifier)

        predicate, created = Resource.objects.get_or_create(
            uri=org_uri,
            defaults={
                "resource_type": ResourceType.PROPERTY,
                "organization": self.organization,
                "canonical_uri": canonical_uri,
                "name": normalized,
            },
        )

        updates: Dict[str, str] = {}
        if predicate.canonical_uri != canonical_uri:
            updates["canonical_uri"] = canonical_uri
        if predicate.name != normalized:
            updates["name"] = normalized
        if updates:
            Resource.objects.filter(pk=predicate.pk).update(**updates)
            predicate.refresh_from_db()

        self._predicate_cache[cache_key] = predicate
        return predicate


class JunctionPromoter:
    """Per-organisation processor that promotes legacy junction rows."""

    def __init__(self, organization: Organization, base_uri: str, stdout, style) -> None:
        self.organization = organization
        self.base_uri = base_uri.rstrip("/")
        self.stdout = stdout
        self.style = style
        self.predicate_service = PredicateMintingService(organization, self.base_uri)
        self._resource_cache: Dict[str, Optional[Resource]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def promote(self, spec: JunctionSpec, *, dry_run: bool) -> int:
        subject_map = self._collect_entity_map(spec.subject_predicate)
        if not subject_map:
            return 0

        object_map = self._collect_entity_map(spec.object_predicate)
        if not object_map:
            return 0

        subject_ids = set(subject_map.keys()) & set(object_map.keys())
        if not subject_ids:
            return 0

        context_map = self._collect_context_map(spec.context_predicate, subject_ids)
        if not context_map:
            return 0

        created = 0
        for subject_id in subject_ids:
            source = subject_map.get(subject_id)
            target = object_map.get(subject_id)
            if not source or not target:
                continue

            labels = context_map.get(subject_id)
            if not labels:
                continue

            for label in sorted(labels):
                predicate = self.predicate_service.ensure_predicate(spec.predicate_prefix, label)
                created += self._ensure_triple(
                    source,
                    predicate,
                    target,
                    junction_id=subject_id,
                    label=label,
                    dry_run=dry_run,
                )

        return created

    # ------------------------------------------------------------------
    # Data collection helpers
    # ------------------------------------------------------------------

    def promote_actor_event(self, *, dry_run: bool) -> int:
        actor_map = self._collect_entity_map(ACTOR_EVENT_ACTOR_PREDICATE)
        if not actor_map:
            return 0

        event_map = self._collect_entity_map(ACTOR_EVENT_EVENT_PREDICATE)
        if not event_map:
            return 0

        subject_ids = set(actor_map.keys()) & set(event_map.keys())
        if not subject_ids:
            return 0

        actor_to_event_pred = self.predicate_service.ensure_predicate("akteurin", "im Ereignis")
        event_to_actor_pred = self.predicate_service.ensure_predicate("ereignis", "hat AkteurIn")
        role_predicate = self.predicate_service.ensure_predicate(
            ACTOR_EVENT_ROLE_PREFIX,
            ACTOR_EVENT_ROLE_LABEL,
        )

        role_map = self._collect_context_map(
            ACTOR_EVENT_ROLE_PREDICATE,
            subject_ids,
            expect_literals=False,
        )

        created = 0
        processed_pairs: Set[tuple[str, str]] = set()

        for subject_id in subject_ids:
            actor = actor_map.get(subject_id)
            event = event_map.get(subject_id)
            if not actor or not event:
                continue

            pair_key = (str(actor.id), str(event.id))
            if pair_key in processed_pairs:
                continue

            message_actor_event = (
                f"{actor.uri or actor.id} --[{actor_to_event_pred.uri}]--> {event.uri or event.id}"
                f" (pattern=actor_event_actor_to_event, junction={subject_id})"
            )
            created += self._persist_derived_triple(
                actor,
                actor_to_event_pred,
                event,
                dry_run=dry_run,
                message=message_actor_event,
            )

            message_event_actor = (
                f"{event.uri or event.id} --[{event_to_actor_pred.uri}]--> {actor.uri or actor.id}"
                f" (pattern=actor_event_event_to_actor, junction={subject_id})"
            )
            created += self._persist_derived_triple(
                event,
                event_to_actor_pred,
                actor,
                dry_run=dry_run,
                message=message_event_actor,
            )

            processed_pairs.add(pair_key)

            created += self._promote_roles_for_participation(
                subject_id,
                role_predicate,
                role_map,
                dry_run=dry_run,
            )

        return created

    def _promote_roles_for_participation(
        self,
        subject_id: str,
        predicate: Resource,
        role_map: Mapping[str, Set[str]],
        *,
        dry_run: bool,
    ) -> int:
        role_ids = role_map.get(subject_id)
        if not role_ids:
            return 0

        subject_resource = self._get_resource(subject_id)
        if not subject_resource:
            return 0

        created = 0
        for role_id in role_ids:
            role_resource = self._get_resource(role_id)
            if not role_resource:
                continue

            message = (
                f"{subject_resource.uri or subject_resource.id} --[{predicate.uri}]-->"
                f" {role_resource.uri or role_resource.id}"
                f" (pattern=actor_event_role_projection, junction={subject_id})"
            )

            created += self._persist_derived_triple(
                subject_resource,
                predicate,
                role_resource,
                dry_run=dry_run,
                message=message,
            )

        return created

    def _get_resource(self, resource_id: str) -> Optional[Resource]:
        if resource_id in self._resource_cache:
            return self._resource_cache[resource_id]

        resource = Resource.objects.filter(id=resource_id).first()
        self._resource_cache[resource_id] = resource
        return resource

    def _collect_entity_map(self, canonical_predicate: str) -> Dict[str, Resource]:
        predicate_filter = self._predicate_filter(canonical_predicate)
        triples = Triple.objects.filter(predicate_filter, subject__organization=self.organization)
        triples = triples.select_related("object")

        entity_map: Dict[str, Resource] = {}
        for triple in triples:
            if triple.object.resource_type != ResourceType.ENTITY:
                continue
            entity_map[str(triple.subject_id)] = triple.object
        return entity_map

    def _collect_context_map(
        self,
        canonical_predicate: str,
        subject_ids: Iterable[str],
        *,
        expect_literals: bool = True,
    ) -> Dict[str, Set[str]]:
        predicate_filter = self._predicate_filter(canonical_predicate)
        triples = (
            Triple.objects.filter(predicate_filter, subject_id__in=subject_ids)
            .filter(subject__organization=self.organization)
            .select_related("object")
        )

        context_map: Dict[str, Set[str]] = {}
        for triple in triples:
            if expect_literals:
                if triple.object.resource_type != ResourceType.LITERAL:
                    continue
                label = normalize_text_input(triple.object.value, blank_to_none=True)
                if not label:
                    continue
                context_map.setdefault(str(triple.subject_id), set()).add(label)
            else:
                if triple.object.resource_type != ResourceType.ENTITY:
                    continue
                context_map.setdefault(str(triple.subject_id), set()).add(str(triple.object_id))
        return context_map

    # ------------------------------------------------------------------
    # Triple creation helper
    # ------------------------------------------------------------------

    def _ensure_triple(
        self,
        subject: Resource,
        predicate: Resource,
        obj: Resource,
        *,
        junction_id: str,
        label: str,
        dry_run: bool,
    ) -> int:
        message = (
            f"{subject.uri or subject.id} --[{predicate.uri}]--> {obj.uri or obj.id}"
            f" (label='{label}', junction={junction_id})"
        )

        return self._persist_derived_triple(subject, predicate, obj, dry_run=dry_run, message=message)

    def _persist_derived_triple(
        self,
        subject: Resource,
        predicate: Resource,
        obj: Resource,
        *,
        dry_run: bool,
        message: str,
    ) -> int:
        if dry_run:
            self.stdout.write(f"    DRY RUN: {message}")
            return 0

        with transaction.atomic():
            triple, created = Triple.objects.get_or_create(
                subject=subject,
                predicate=predicate,
                object=obj,
                defaults={"is_derived": True, "source": None},
            )

            if created:
                self._write_styled("SUCCESS", f"  {message}")
                return 1

            updates: Dict[str, Optional[object]] = {}
            if not triple.is_derived:
                updates["is_derived"] = True
            if triple.source_id is not None:
                updates["source"] = None
            if updates:
                Triple.objects.filter(pk=triple.pk).update(**updates)
                self.stdout.write(f"  Updated derived flags for {message}")
        return 0

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _predicate_filter(uri: str) -> Q:
        return Q(predicate__canonical_uri=uri) | Q(predicate__uri=uri)

    def _write_styled(self, style_name: str, message: str) -> None:
        style = getattr(self.style, style_name, None)
        if callable(style):
            self.stdout.write(style(message))
        else:
            self.stdout.write(message)


class Command(BaseCommand):
    help = "Promote legacy Kreuz junction rows into canonical derived triples"

    def add_arguments(self, parser):  # pragma: no cover - argparse boilerplate
        parser.add_argument(
            "--organization",
            "-o",
            action="append",
            dest="organizations",
            help="Limit processing to the provided organization code(s)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            default=False,
            help="Preview changes without writing to the database",
        )

    def handle(self, *args, **options):
        dry_run: bool = options.get("dry_run", False)
        requested_orgs: Optional[Iterable[str]] = options.get("organizations")
        org_queryset = Organization.objects.filter(is_active=True)
        if requested_orgs:
            org_queryset = org_queryset.filter(code__in=[code.lower() for code in requested_orgs])

        organizations = list(org_queryset)
        if not organizations:
            self.stdout.write(self.style.WARNING("No organizations matched the requested filters."))
            return

        total_created = 0
        for organization in organizations:
            base_uri = self._infer_base_uri(organization)
            promoter = JunctionPromoter(
                organization,
                base_uri,
                stdout=self.stdout,
                style=self.style,
            )

            self.stdout.write(self.style.HTTP_INFO(f"Processing organization: {organization.code}"))
            created_for_org = 0
            for spec in JUNCTION_SPECS:
                created = promoter.promote(spec, dry_run=dry_run)
                if created:
                    self.stdout.write(
                        f"    {spec.dataset_name}: created {created} derived triple(s)"
                    )
                created_for_org += created

            actor_event_created = promoter.promote_actor_event(dry_run=dry_run)
            if actor_event_created:
                self.stdout.write(
                    f"    {ACTOR_EVENT_DATASET}: created {actor_event_created} derived triple(s)"
                )
            created_for_org += actor_event_created
            total_created += created_for_org

            if not created_for_org:
                self.stdout.write("    No eligible junction rows found.")

        self.stdout.write(self.style.SUCCESS(f"Promotion complete. Created {total_created} triple(s)."))

    # ------------------------------------------------------------------
    # Base URI helper
    # ------------------------------------------------------------------

    def _infer_base_uri(self, organization: Organization) -> str:
        """Infer the URI base (without organization code) used by existing data."""

        sample_uri = (
            Resource.objects.filter(organization=organization)
            .exclude(uri__isnull=True)
            .filter(uri__contains=f"/{organization.code}/")
            .order_by("created_at")
            .values_list("uri", flat=True)
            .first()
        )

        if sample_uri:
            marker = f"/{organization.code}/"
            idx = sample_uri.find(marker)
            if idx > 0:
                return sample_uri[:idx]

        fallback = getattr(settings, "ARKUMU_ORG_BASE_URI", None)
        if fallback:
            return fallback.rstrip("/")

        return DEFAULT_INSTITUTION_BASE_URI.rstrip("/")
