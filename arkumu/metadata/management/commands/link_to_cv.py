"""
Management command to link org entities to controlled vocabulary entries.

When an entity type references IDs that exist in a controlled vocabulary,
this command copies the CV data (labels, properties) to the org entities.

Usage:
    python manage.py link_to_cv --org khm --entity-type projektkategorie --cv projektkategorie --dry-run
    python manage.py link_to_cv --org khm --entity-type projektkategorie --cv projektkategorie
    python manage.py link_to_cv --org khm --entity-type projektkategorie --cv projektkategorie --rebuild-index
"""

import logging
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count

from arkumu.metadata.models import Resource, Triple, ResourceType

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Link org entities to controlled vocabulary entries"

    def add_arguments(self, parser):
        parser.add_argument(
            "--org",
            type=str,
            required=True,
            help="Organization code (e.g., khm, fuk, hmt)",
        )
        parser.add_argument(
            "--entity-type",
            type=str,
            required=True,
            help="Entity type to link (e.g., projektkategorie)",
        )
        parser.add_argument(
            "--cv",
            type=str,
            required=True,
            help="Controlled vocabulary type (e.g., projektkategorie)",
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
            help="Rebuild ProjectIndex after linking",
        )
        parser.add_argument(
            "--only-stubs",
            action="store_true",
            default=True,
            help="Only link entities that have no outgoing triples (default: True)",
        )

    def handle(self, *args, **options):
        org = options["org"]
        entity_type = options["entity_type"]
        cv_type = options["cv"]
        dry_run = options["dry_run"]
        verbose = options["verbose"]
        rebuild_index = options["rebuild_index"]
        only_stubs = options["only_stubs"]

        self._link_to_cv(org, entity_type, cv_type, dry_run, verbose, only_stubs)

        if rebuild_index and not dry_run:
            self._rebuild_index()

    def _link_to_cv(
        self, org: str, entity_type: str, cv_type: str,
        dry_run: bool, verbose: bool, only_stubs: bool
    ):
        """Link org entities to CV entries."""
        self.stdout.write(f"\nLinking {org}/{entity_type} to CV {cv_type}")
        self.stdout.write("=" * 60)

        # URI patterns
        entity_prefix = f"http://arkumu.org/data/{org}/entities/{entity_type}/"
        cv_prefix = f"http://arkumu.org/data/types/{cv_type}/project-category-"

        # Find entities to link
        entities_qs = Resource.objects.filter(
            uri__startswith=entity_prefix,
            resource_type=ResourceType.ENTITY,
        )

        if only_stubs:
            entities_qs = entities_qs.annotate(
                triple_count=Count("subject_triples")
            ).filter(triple_count=0)

        entities = list(entities_qs)
        self.stdout.write(f"Found {len(entities)} entities to link")

        if not entities:
            self.stdout.write(self.style.SUCCESS("No entities to link"))
            return

        linked = 0
        skipped = 0
        triples_created = 0

        for entity in entities:
            # Extract ID from entity URI
            entity_id = entity.uri.replace(entity_prefix, "").rstrip("/")

            # Find corresponding CV entry
            cv_uri = f"{cv_prefix}{entity_id}"
            cv_entry = Resource.objects.filter(uri=cv_uri).first()

            if not cv_entry:
                if verbose:
                    self.stdout.write(f"  No CV entry for ID {entity_id}")
                skipped += 1
                continue

            # Get triples from CV
            cv_triples = Triple.objects.filter(
                subject=cv_entry
            ).select_related("predicate", "object")

            if cv_triples.count() == 0:
                if verbose:
                    self.stdout.write(f"  CV entry {entity_id} has no triples")
                skipped += 1
                continue

            if verbose:
                self.stdout.write(
                    f"  {entity_id}: copying {cv_triples.count()} triples from CV"
                )

            if not dry_run:
                with transaction.atomic():
                    for cv_triple in cv_triples:
                        _, created = Triple.objects.get_or_create(
                            subject=entity,
                            predicate=cv_triple.predicate,
                            object=cv_triple.object,
                        )
                        if created:
                            triples_created += 1

            linked += 1

        self.stdout.write("")
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN: Would link {linked} entities, skip {skipped}"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Linked {linked} entities ({triples_created} triples created), skipped {skipped}"
                )
            )

    def _rebuild_index(self):
        """Rebuild ProjectIndex after linking."""
        self.stdout.write("\nRebuilding ProjectIndex...")

        from arkumu.catalog.services.project_index_db_service import ProjectIndexDbService

        try:
            service = ProjectIndexDbService()
            service.rebuild_from_graph()
            self.stdout.write(self.style.SUCCESS("ProjectIndex rebuilt successfully"))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Failed to rebuild index: {e}"))
