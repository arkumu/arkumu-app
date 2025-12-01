"""
Management command to apply canonical URI mappings from the mapping editor.

Instead of requiring a separate CSV file, this reads the canonical_mapping
data that users have already configured in the workspace_columns of their
mapping, and applies those canonical URIs to the corresponding Resources.

This bridges the gap between the mapping editor UI and the canonical system.
"""

import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.users.models import Organization

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Apply canonical URI mappings from the mapping editor's workspace_columns. "
        "This updates Resource.canonical_uri based on the canonical_mapping data "
        "that users configure in the CSV mapping editor UI."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--organization",
            "-o",
            type=str,
            required=True,
            help="Organization code (e.g., hmt, khm)",
        )
        parser.add_argument(
            "--mapping-id",
            type=str,
            help="Specific mapping UUID. If not provided, uses the active mapping.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview changes without applying them.",
        )
        parser.add_argument(
            "--canonicalize-manifest",
            action="store_true",
            help="Also run canonicalize_schema_manifest after updating Resources.",
        )

    def handle(self, *args, **options):
        org_code = options["organization"]
        mapping_id = options.get("mapping_id")
        dry_run = options["dry_run"]
        canonicalize_manifest = options["canonicalize_manifest"]

        # Get organization
        try:
            organization = Organization.objects.get(code=org_code)
        except Organization.DoesNotExist:
            raise CommandError(f"Organization '{org_code}' not found")

        # Get mapping
        if mapping_id:
            try:
                mapping = Mapping.objects.get(id=mapping_id)
            except Mapping.DoesNotExist:
                raise CommandError(f"Mapping '{mapping_id}' not found")
        else:
            mapping = Mapping.objects.filter(
                organization_id=org_code, is_active=True
            ).first()
            if not mapping:
                raise CommandError(
                    f"No active mapping found for organization '{org_code}'. "
                    "Use --mapping-id to specify one."
                )

        self.stdout.write(f"Organization: {organization.name} ({org_code})")
        self.stdout.write(f"Mapping: {mapping.name} (ID: {mapping.id})")
        self.stdout.write("-" * 60)

        logger.info(
            "Starting apply_mapping_canonicals for org=%s mapping=%s",
            org_code,
            mapping.id,
        )

        # Get workspace_columns from mapping_config
        config = mapping.mapping_config or {}
        workspace_columns = config.get("workspace_columns", {})

        if not workspace_columns:
            raise CommandError("Mapping has no workspace_columns configured")

        # Process canonical mappings
        stats = self._apply_canonical_mappings(
            organization, workspace_columns, dry_run
        )

        # Display results
        self._display_results(stats, dry_run)

        # Optionally run canonicalize_schema_manifest
        if canonicalize_manifest and not dry_run and stats["updated"] > 0:
            self.stdout.write(f"\nRunning canonicalize_schema_manifest for mapping {mapping.id}...")
            from django.core.management import call_command

            call_command(
                "canonicalize_schema_manifest",
                mapping_ids=[str(mapping.id)],
                verbosity=1,
            )

    def _apply_canonical_mappings(
        self, organization: Organization, workspace_columns: dict, dry_run: bool
    ) -> dict:
        """Apply canonical URIs from workspace_columns to Resources."""
        stats = {
            "total_columns": len(workspace_columns),
            "with_canonical": 0,
            "updated": 0,
            "already_set": 0,
            "not_found": [],
            "errors": 0,
        }

        with transaction.atomic():
            for col_id, col_data in workspace_columns.items():
                canonical_mapping = col_data.get("canonical_mapping")
                if not canonical_mapping:
                    continue

                canonical_uri = canonical_mapping.get("canonical_property_uri")
                if not canonical_uri:
                    continue

                stats["with_canonical"] += 1

                # Get column metadata
                col_name = col_data.get("name")
                dataset = col_data.get("dataset") or col_data.get("source")

                if not col_name:
                    continue

                # Find the Resource for this property
                try:
                    result = self._update_resource_canonical(
                        organization,
                        col_name,
                        dataset,
                        canonical_uri,
                        dry_run,
                    )

                    if result == "updated":
                        stats["updated"] += 1
                    elif result == "already_set":
                        stats["already_set"] += 1
                    elif result == "not_found":
                        stats["not_found"].append(f"{dataset}::{col_name}")

                except Exception as e:
                    logger.exception("Error processing column %s: %s", col_id, e)
                    self.stdout.write(
                        self.style.ERROR(f"Error processing {col_id}: {e}")
                    )
                    stats["errors"] += 1

            if dry_run:
                transaction.set_rollback(True)

        logger.info(
            "apply_mapping_canonicals completed: updated=%d already_set=%d not_found=%d errors=%d",
            stats["updated"],
            stats["already_set"],
            len(stats["not_found"]),
            stats["errors"],
        )

        return stats

    def _update_resource_canonical(
        self,
        organization: Organization,
        col_name: str,
        dataset: str,
        canonical_uri: str,
        dry_run: bool,
    ) -> str:
        """Update a single Resource's canonical_uri."""
        # Find resources matching this property name
        resources = Resource.objects.filter(
            organization=organization,
            resource_type=ResourceType.PROPERTY,
            name=col_name,
            is_placeholder=False,
        )

        # If multiple matches, try to narrow down by dataset name in URI
        if resources.count() > 1 and dataset:
            from arkumu.common.uri_utils import slugify_uri_part

            dataset_slug = slugify_uri_part(dataset)
            filtered = [r for r in resources if dataset_slug in r.uri.lower()]
            if filtered:
                resources = filtered

        if not resources:
            # Try URI-based matching as fallback
            from arkumu.common.uri_utils import slugify_uri_part

            slug = slugify_uri_part(col_name)
            if slug:
                resources = Resource.objects.filter(
                    organization=organization,
                    resource_type=ResourceType.PROPERTY,
                    uri__iendswith=f"/{slug}",
                    is_placeholder=False,
                )

        if not resources:
            return "not_found"

        # Update the resource(s)
        updated_any = False
        for resource in resources:
            if resource.canonical_uri == canonical_uri:
                logger.debug(
                    "Resource %s already has canonical_uri=%s",
                    resource.uri,
                    canonical_uri,
                )
                continue

            if dry_run:
                old = resource.canonical_uri or "(none)"
                self.stdout.write(
                    f"  Would update: {resource.name} ({old} -> {canonical_uri})"
                )
            else:
                old_uri = resource.canonical_uri
                resource.canonical_uri = canonical_uri
                resource.save(update_fields=["canonical_uri"])
                logger.info(
                    "Updated Resource %s canonical_uri: %s -> %s",
                    resource.uri,
                    old_uri,
                    canonical_uri,
                )

            updated_any = True

        return "updated" if updated_any else "already_set"

    def _display_results(self, stats: dict, dry_run: bool) -> None:
        """Display processing results."""
        mode = "DRY RUN" if dry_run else "LIVE"
        self.stdout.write(f"\n=== Results ({mode}) ===")
        self.stdout.write(f"Total workspace columns: {stats['total_columns']}")
        self.stdout.write(f"Columns with canonical mapping: {stats['with_canonical']}")
        self.stdout.write(
            self.style.SUCCESS(f"Updated: {stats['updated']}")
        )
        self.stdout.write(f"Already set (unchanged): {stats['already_set']}")
        self.stdout.write(f"Not found: {len(stats['not_found'])}")
        self.stdout.write(f"Errors: {stats['errors']}")

        if stats["not_found"] and len(stats["not_found"]) <= 20:
            self.stdout.write("\nResources not found:")
            for name in stats["not_found"]:
                self.stdout.write(f"  - {name}")
        elif stats["not_found"]:
            self.stdout.write(
                f"\nResources not found (showing first 20 of {len(stats['not_found'])}):"
            )
            for name in stats["not_found"][:20]:
                self.stdout.write(f"  - {name}")

        self.stdout.write("")
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN - No changes made. Run without --dry-run to apply."
                )
            )
        else:
            if stats["updated"] > 0:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Successfully updated {stats['updated']} resources."
                    )
                )
