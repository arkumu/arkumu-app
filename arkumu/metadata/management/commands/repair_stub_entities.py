"""
Management command to repair stub entities by copying triples from source entities within the same org.

Stub entities are entities that have incoming references but no outgoing triples.
This command copies triples from one entity type to another when both share the same ID.

Use case: When entity type A references entity type B by ID, but B has no data.
If another entity type C has the same IDs with data, copy from C to B.

Usage:
    python manage.py repair_stub_entities --org khm --dry-run
    python manage.py repair_stub_entities --org khm --stub-type schlagwort --source-type 08-keywords
    python manage.py repair_stub_entities --org khm --stub-type schlagwort --source-type 08-keywords --rebuild-index

Note: For copying from controlled vocabularies, use repair_from_cv instead.
"""

import logging
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count

from arkumu.metadata.models import Resource, Triple, ResourceType

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Repair stub entities by copying triples from corresponding source entities"

    def add_arguments(self, parser):
        parser.add_argument(
            "--org",
            type=str,
            required=True,
            help="Organization code (e.g., khm, fuk, hmt)",
        )
        parser.add_argument(
            "--stub-type",
            type=str,
            help="Entity type pattern for stubs (e.g., projektkategorie)",
        )
        parser.add_argument(
            "--source-type",
            type=str,
            help="Entity type pattern for source entities (e.g., 08-keywords)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without making changes",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Show detailed information",
        )
        parser.add_argument(
            "--rebuild-index",
            action="store_true",
            help="Rebuild ProjectIndex after repair",
        )

    def handle(self, *args, **options):
        org = options["org"]
        stub_type = options.get("stub_type")
        source_type = options.get("source_type")
        dry_run = options["dry_run"]
        verbose = options["verbose"]
        rebuild_index = options["rebuild_index"]

        # If no specific types provided, analyze what stubs exist
        if not stub_type:
            self._analyze_stubs(org, verbose)
            return

        if not source_type:
            self.stderr.write(
                self.style.ERROR("--source-type is required when --stub-type is specified")
            )
            return

        self._repair_stubs(org, stub_type, source_type, dry_run, verbose)

        if rebuild_index and not dry_run:
            self._rebuild_index(org)

    def _analyze_stubs(self, org: str, verbose: bool):
        """Analyze and report stub entities for an organization."""
        self.stdout.write(f"\nAnalyzing stub entities for org: {org}")
        self.stdout.write("=" * 60)

        # Find entities with incoming references but no outgoing triples
        org_uri_prefix = f"http://arkumu.org/data/{org}/entities/"

        # Get all entity types for this org
        entity_types = (
            Resource.objects.filter(
                uri__startswith=org_uri_prefix,
                resource_type=ResourceType.ENTITY,
            )
            .values_list("uri", flat=True)
        )

        # Group by entity type (extract from URI pattern)
        type_counts = {}
        stub_counts = {}

        for uri in entity_types:
            # Extract type from URI like: .../entities/projektkategorie/135
            parts = uri.replace(org_uri_prefix, "").split("/")
            if parts:
                entity_type = parts[0]
                type_counts[entity_type] = type_counts.get(entity_type, 0) + 1

        self.stdout.write(f"\nEntity types found: {len(type_counts)}")

        # For each type, count stubs (entities with no outgoing triples)
        for entity_type in sorted(type_counts.keys()):
            type_prefix = f"{org_uri_prefix}{entity_type}/"

            total = Resource.objects.filter(
                uri__startswith=type_prefix,
                resource_type=ResourceType.ENTITY,
            ).count()

            # Stubs = entities with no outgoing triples
            stubs = Resource.objects.filter(
                uri__startswith=type_prefix,
                resource_type=ResourceType.ENTITY,
            ).annotate(
                triple_count=Count("subject_triples")
            ).filter(
                triple_count=0
            ).count()

            if stubs > 0:
                stub_counts[entity_type] = stubs
                pct = (stubs / total * 100) if total > 0 else 0
                self.stdout.write(
                    self.style.WARNING(
                        f"  {entity_type}: {stubs}/{total} stubs ({pct:.1f}%)"
                    )
                )
            elif verbose:
                self.stdout.write(f"  {entity_type}: {total} entities (no stubs)")

        if stub_counts:
            self.stdout.write(
                f"\nTo repair, run with --stub-type and --source-type arguments"
            )
            self.stdout.write(
                f"Example: python manage.py repair_stub_entities --org {org} "
                f"--stub-type projektkategorie --source-type 08-keywords --dry-run"
            )
        else:
            self.stdout.write(self.style.SUCCESS("\nNo stub entities found!"))

    def _repair_stubs(
        self, org: str, stub_type: str, source_type: str, dry_run: bool, verbose: bool
    ):
        """Repair stub entities by copying triples from source entities."""
        self.stdout.write(f"\nRepairing {stub_type} stubs from {source_type} for org: {org}")
        self.stdout.write("=" * 60)

        org_uri_prefix = f"http://arkumu.org/data/{org}/entities/"
        stub_prefix = f"{org_uri_prefix}{stub_type}/"
        source_prefix = f"{org_uri_prefix}{source_type}/"

        # Find stub entities
        stubs = Resource.objects.filter(
            uri__startswith=stub_prefix,
            resource_type=ResourceType.ENTITY,
        ).annotate(
            triple_count=Count("subject_triples")
        ).filter(
            triple_count=0
        )

        stub_count = stubs.count()
        self.stdout.write(f"Found {stub_count} stub entities")

        if stub_count == 0:
            self.stdout.write(self.style.SUCCESS("No stubs to repair"))
            return

        repaired = 0
        skipped = 0
        triples_created = 0

        for stub in stubs:
            # Extract numeric ID from stub URI
            stub_id = stub.uri.replace(stub_prefix, "").rstrip("/")

            # Find corresponding source entity
            source_uri = f"{source_prefix}{stub_id}"
            source = Resource.objects.filter(uri=source_uri).first()

            if not source:
                if verbose:
                    self.stdout.write(f"  No source found for {stub_id}")
                skipped += 1
                continue

            # Get triples from source
            source_triples = Triple.objects.filter(
                subject_id=source.id
            ).select_related("predicate", "object")

            if source_triples.count() == 0:
                if verbose:
                    self.stdout.write(f"  Source {stub_id} has no triples")
                skipped += 1
                continue

            if verbose:
                self.stdout.write(
                    f"  {stub_id}: copying {source_triples.count()} triples from {source_type}"
                )

            if not dry_run:
                with transaction.atomic():
                    for src_triple in source_triples:
                        # Create matching triple for stub
                        Triple.objects.get_or_create(
                            subject=stub,
                            predicate=src_triple.predicate,
                            object=src_triple.object,
                        )
                        triples_created += 1

            repaired += 1

        self.stdout.write("")
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN: Would repair {repaired} stubs, skip {skipped}"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Repaired {repaired} stubs ({triples_created} triples created), skipped {skipped}"
                )
            )

    def _rebuild_index(self, org: str):
        """Rebuild ProjectIndex after repair."""
        self.stdout.write("\nRebuilding ProjectIndex...")

        from arkumu.catalog.services.project_index_db_service import ProjectIndexDbService

        try:
            service = ProjectIndexDbService()
            service.rebuild_from_graph()
            self.stdout.write(self.style.SUCCESS("ProjectIndex rebuilt successfully"))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Failed to rebuild index: {e}"))
