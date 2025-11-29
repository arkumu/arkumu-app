"""
Management command to migrate org entity references to controlled vocabulary.

Instead of each org having copies like:
  khm/entities/projektkategorie/128
  fuk/entities/projektkategorie/128

All should reference the CV directly:
  types/projektkategorie/project-category-128

Usage:
    python manage.py migrate_to_cv --org khm --entity-type projektkategorie --cv projektkategorie --dry-run
    python manage.py migrate_to_cv --org khm --entity-type projektkategorie --cv projektkategorie
    python manage.py migrate_to_cv --all-orgs --entity-type projektkategorie --cv projektkategorie --dry-run
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from arkumu.metadata.models import Resource, Triple, ResourceType
from arkumu.users.models import Organization


class Command(BaseCommand):
    help = "Migrate org entity references to controlled vocabulary"

    def add_arguments(self, parser):
        parser.add_argument(
            "--org",
            type=str,
            help="Organization code (e.g., khm, fuk, hmt)",
        )
        parser.add_argument(
            "--all-orgs",
            action="store_true",
            help="Process all organizations",
        )
        parser.add_argument(
            "--entity-type",
            type=str,
            required=True,
            help="Entity type to migrate (e.g., projektkategorie)",
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
            "--cleanup",
            action="store_true",
            help="Delete orphaned org entities after migration",
        )
        parser.add_argument(
            "--rebuild-index",
            action="store_true",
            help="Rebuild ProjectIndex after migration",
        )

    def handle(self, *args, **options):
        org_code = options.get("org")
        all_orgs = options["all_orgs"]
        entity_type = options["entity_type"]
        cv_type = options["cv"]
        dry_run = options["dry_run"]
        verbose = options["verbose"]
        cleanup = options["cleanup"]
        rebuild_index = options["rebuild_index"]

        if not org_code and not all_orgs:
            self.stderr.write(
                self.style.ERROR("Either --org or --all-orgs is required")
            )
            return

        if all_orgs:
            orgs = Organization.objects.values_list("code", flat=True)
        else:
            orgs = [org_code]

        total_stats = {"triples_updated": 0, "entities_orphaned": 0}

        for org in orgs:
            stats = self._migrate_org(org, entity_type, cv_type, dry_run, verbose, cleanup)
            total_stats["triples_updated"] += stats["triples_updated"]
            total_stats["entities_orphaned"] += stats["entities_orphaned"]

        self.stdout.write("")
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN TOTAL: Would update {total_stats['triples_updated']} triples"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"TOTAL: Updated {total_stats['triples_updated']} triples"
                )
            )

        if rebuild_index and not dry_run:
            self._rebuild_index()

    def _migrate_org(
        self, org: str, entity_type: str, cv_type: str,
        dry_run: bool, verbose: bool, cleanup: bool
    ) -> dict:
        """Migrate one org's entity references to CV."""
        self.stdout.write(f"\nMigrating {org}/{entity_type} to CV {cv_type}")
        self.stdout.write("=" * 60)

        # URI patterns
        org_entity_prefix = f"http://arkumu.org/data/{org}/entities/{entity_type}/"
        cv_prefix = f"http://arkumu.org/data/types/{cv_type}/project-category-"

        # Find all org entities
        org_entities = Resource.objects.filter(
            uri__startswith=org_entity_prefix,
            resource_type=ResourceType.ENTITY,
        )

        entity_count = org_entities.count()
        self.stdout.write(f"Found {entity_count} org entities")

        if entity_count == 0:
            return {"triples_updated": 0, "entities_orphaned": 0}

        stats = {"triples_updated": 0, "entities_orphaned": 0}

        # Build mapping: org entity -> CV entity
        entity_map = {}
        missing_cv = []

        for org_entity in org_entities:
            entity_id = org_entity.uri.replace(org_entity_prefix, "").rstrip("/")
            cv_uri = f"{cv_prefix}{entity_id}"
            cv_entity = Resource.objects.filter(uri=cv_uri).first()

            if cv_entity:
                entity_map[org_entity.id] = cv_entity
            else:
                missing_cv.append(entity_id)

        if missing_cv and verbose:
            self.stdout.write(f"  Missing CV entries: {missing_cv[:10]}...")

        self.stdout.write(f"Mapped {len(entity_map)} entities to CV")

        if not entity_map:
            return stats

        # Find all triples that reference org entities (as object)
        triples_to_update = Triple.objects.filter(
            object_id__in=entity_map.keys()
        )

        triple_count = triples_to_update.count()
        self.stdout.write(f"Found {triple_count} triples to update")

        if not dry_run and triple_count > 0:
            with transaction.atomic():
                for triple in triples_to_update:
                    cv_entity = entity_map.get(triple.object_id)
                    if cv_entity:
                        triple.object = cv_entity
                        triple.save(update_fields=["object"])
                        stats["triples_updated"] += 1
        else:
            stats["triples_updated"] = triple_count

        # Cleanup orphaned org entities
        if cleanup and not dry_run:
            orphaned = self._cleanup_orphaned(org_entity_prefix)
            stats["entities_orphaned"] = orphaned
            self.stdout.write(f"Cleaned up {orphaned} orphaned entities")

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"  DRY RUN: Would update {stats['triples_updated']} triples"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"  Updated {stats['triples_updated']} triples"
                )
            )

        return stats

    def _cleanup_orphaned(self, prefix: str) -> int:
        """Delete org entities that are no longer referenced."""
        # Find entities with no incoming references
        entities = Resource.objects.filter(
            uri__startswith=prefix,
            resource_type=ResourceType.ENTITY,
        )

        orphaned = 0
        for entity in entities:
            # Check if any triple references this entity
            has_refs = Triple.objects.filter(object=entity).exists()
            if not has_refs:
                # Also delete outgoing triples
                Triple.objects.filter(subject=entity).delete()
                entity.delete()
                orphaned += 1

        return orphaned

    def _rebuild_index(self):
        """Rebuild ProjectIndex after migration."""
        self.stdout.write("\nRebuilding ProjectIndex...")

        from arkumu.catalog.services.project_index_db_service import ProjectIndexDbService

        try:
            service = ProjectIndexDbService()
            service.rebuild_from_graph()
            self.stdout.write(self.style.SUCCESS("ProjectIndex rebuilt successfully"))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Failed to rebuild index: {e}"))
