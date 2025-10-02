"""Derive direct project relationship triples from canonical junction nodes."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set

from django.core.management.base import BaseCommand
from django.db import transaction

from arkumu.metadata.models import Resource, ResourceType, Triple

logger = logging.getLogger(__name__)


@dataclass
class DerivedEdgeSpec:
    """Definition of a derived edge for a project."""

    predicate_uri: str
    canonical_property: str


DERIVED_EDGE_SPECS: Dict[str, List[DerivedEdgeSpec]] = {
    "http://arkumu.org/data/properties/projekt": [
        DerivedEdgeSpec(
            predicate_uri="http://arkumu.org/data/properties/ereignis",
            canonical_property="http://arkumu.org/data/properties/ereignis",
        ),
        DerivedEdgeSpec(
            predicate_uri="http://arkumu.org/data/properties/digitales-objekt",
            canonical_property="http://arkumu.org/data/properties/digitales-objekt",
        ),
        DerivedEdgeSpec(
            predicate_uri="http://arkumu.org/data/properties/schlagwort",
            canonical_property="http://arkumu.org/data/properties/schlagwort",
        ),
        DerivedEdgeSpec(
            predicate_uri="http://arkumu.org/data/properties/equipment-und-software",
            canonical_property="http://arkumu.org/data/properties/equipment-und-software",
        ),
    ],
}

PROJECT_CANONICAL_PROPERTY = "http://arkumu.org/data/properties/projekt"


class Command(BaseCommand):
    """Generate derived project relationships from canonical junction triples."""

    help = "Derive project relationships (events, digital objects, keywords, etc.) from canonical junction triples"

    def add_arguments(self, parser):  # pragma: no cover - argparse boilerplate
        parser.add_argument(
            "--organization",
            "-o",
            action="append",
            dest="organizations",
            help="Organization code(s) to process (default: all organizations)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show actions without creating derived triples",
        )

    def handle(self, *args, **options):
        org_codes = self._resolve_org_codes(options.get("organizations"))
        if not org_codes:
            self.stdout.write(self.style.WARNING("No organizations with canonical project junctions found."))
            return

        dry_run = options.get("dry_run")

        stats = {"processed": 0, "created": 0}

        for org_code in sorted(org_codes):
            self.stdout.write(self.style.MIGRATE_HEADING(f"Organization: {org_code}"))

            subject_ids = self._collect_junction_subjects(org_code)
            if not subject_ids:
                self.stdout.write("  No canonical junction triples found.")
                continue

            self.stdout.write(
                self.style.HTTP_INFO(f"  Processing {len(subject_ids)} junction nodes")
            )
            stats["processed"] += len(subject_ids)

            created = self._derive_edges(subject_ids, dry_run=dry_run)
            stats["created"] += created

        self.stdout.write(
            self.style.SUCCESS(
                f"Derivation complete: processed={stats['processed']}, created={stats['created']}"
            )
        )

    def _resolve_org_codes(self, organizations: Optional[Iterable[str]]) -> Set[str]:
        qs = Triple.objects.filter(predicate__canonical_uri=PROJECT_CANONICAL_PROPERTY)
        if organizations:
            qs = qs.filter(subject__organization__code__in=organizations)
        return set(
            qs.values_list("subject__organization__code", flat=True)
            .exclude(subject__organization__code__isnull=True)
        )

    def _collect_junction_subjects(self, org_code: str) -> Set[str]:
        return set(
            Triple.objects.filter(
                predicate__canonical_uri=PROJECT_CANONICAL_PROPERTY,
                subject__organization__code=org_code,
            ).values_list("subject_id", flat=True)
        )

    def _derive_edges(self, subject_ids: Iterable[str], *, dry_run: bool) -> int:
        created = 0
        specs = DERIVED_EDGE_SPECS.get(PROJECT_CANONICAL_PROPERTY, [])

        for subject_id in subject_ids:
            project_id = self._resolve_object_id(subject_id, PROJECT_CANONICAL_PROPERTY)
            if not project_id:
                continue

            for spec in specs:
                target_id = self._resolve_object_id(subject_id, spec.canonical_property)
                if not target_id:
                    continue

                created += self._ensure_project_edge(project_id, spec.predicate_uri, target_id, dry_run)

        return created

    def _resolve_object_id(self, subject_id: str, canonical_property: str) -> Optional[str]:
        triple = (
            Triple.objects.filter(
                subject_id=subject_id,
                predicate__canonical_uri=canonical_property,
                object__resource_type=ResourceType.ENTITY,
            )
            .only("object_id")
            .first()
        )
        return str(triple.object_id) if triple else None

    def _ensure_project_edge(self, project_id: str, predicate_uri: str, target_id: str, dry_run: bool) -> int:
        predicate = Resource.objects.filter(uri=predicate_uri).first()
        if not predicate:
            predicate = Resource.objects.filter(canonical_uri=predicate_uri).first()
        if not predicate:
            predicate = Resource.objects.create(
                uri=predicate_uri,
                resource_type=ResourceType.PROPERTY,
            )
        if not predicate:
            logger.warning("Predicate resource not found for URI %s", predicate_uri)
            return 0

        if dry_run:
            self.stdout.write(
                f"    DRY RUN: project {project_id} -> {predicate_uri} -> {target_id}"
            )
            return 0

        with transaction.atomic():
            triple, created = Triple.objects.get_or_create(
                subject_id=project_id,
                predicate=predicate,
                object_id=target_id,
                defaults={"is_derived": True},
            )
            if created:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"    Added derived edge project={project_id} predicate={predicate_uri} object={target_id}"
                    )
                )
                return 1
        return 0
