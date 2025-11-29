"""
Management command to split comma-separated literal values into proper entity triples.

When a column is imported with is_multi_value: false, comma-separated values like
"135,124,126" are stored as a single literal instead of separate entity references.

This command fixes that by:
1. Finding triples with literal objects containing comma-separated values
2. Splitting the values
3. Creating proper entity triples for each value
4. Optionally deleting the old literal triples

Usage:
    python manage.py split_multivalue_literals --org khm --dry-run
    python manage.py split_multivalue_literals --org khm --predicate projekte-export-projektkategorien-arkumu --target-type projektkategorie
    python manage.py split_multivalue_literals --org khm --predicate projekte-export-projektkategorien-arkumu --target-type projektkategorie --delete-literals
"""

import logging
import re
from django.core.management.base import BaseCommand
from django.db import transaction

from arkumu.metadata.models import Resource, Triple, ResourceType

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Split comma-separated literal values into proper entity triples"

    def add_arguments(self, parser):
        parser.add_argument(
            "--org",
            type=str,
            required=True,
            help="Organization code (e.g., khm, fuk, hmt)",
        )
        parser.add_argument(
            "--predicate",
            type=str,
            help="Predicate name pattern to find (e.g., projekte-export-projektkategorien-arkumu)",
        )
        parser.add_argument(
            "--target-type",
            type=str,
            help="Entity type to create references to (e.g., projektkategorie, 08-keywords)",
        )
        parser.add_argument(
            "--target-predicate",
            type=str,
            help="Predicate to use for new triples (defaults to canonical projektkategorie)",
        )
        parser.add_argument(
            "--separator",
            type=str,
            default=",",
            help="Value separator (default: comma)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without making changes",
        )
        parser.add_argument(
            "--delete-literals",
            action="store_true",
            help="Delete the original literal triples after splitting",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Show detailed information",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Limit number of triples to process (0 = no limit)",
        )
        parser.add_argument(
            "--include-single-values",
            action="store_true",
            help="Also convert single-value literals (not just comma-separated)",
        )

    def handle(self, *args, **options):
        org = options["org"]
        predicate_pattern = options.get("predicate")
        target_type = options.get("target_type")
        target_predicate = options.get("target_predicate")
        separator = options["separator"]
        dry_run = options["dry_run"]
        delete_literals = options["delete_literals"]
        verbose = options["verbose"]
        limit = options["limit"]
        include_single = options["include_single_values"]

        # If no specific predicate, analyze what literals exist
        if not predicate_pattern:
            self._analyze_multivalue_literals(org, separator, verbose)
            return

        if not target_type:
            self.stderr.write(
                self.style.ERROR("--target-type is required when --predicate is specified")
            )
            return

        self._split_literals(
            org, predicate_pattern, target_type, target_predicate,
            separator, dry_run, delete_literals, verbose, limit, include_single
        )

    def _analyze_multivalue_literals(self, org: str, separator: str, verbose: bool):
        """Analyze and report literals with comma-separated values."""
        self.stdout.write(f"\nAnalyzing multi-value literals for org: {org}")
        self.stdout.write("=" * 60)

        org_uri_prefix = f"http://arkumu.org/data/{org}/"

        # Find predicates that have literal objects with separators
        predicates_with_multival = {}

        # Get all triples with literal objects for this org
        triples = Triple.objects.filter(
            subject__uri__startswith=org_uri_prefix,
            object__resource_type=ResourceType.LITERAL,
        ).select_related("predicate", "object")

        for triple in triples:
            obj_value = triple.object.value or triple.object.name or ""
            if separator in obj_value:
                # Check if it looks like a list of IDs
                parts = [p.strip() for p in obj_value.split(separator)]
                if len(parts) > 1 and all(self._looks_like_id(p) for p in parts):
                    pred_name = triple.predicate.name or triple.predicate.uri.split("/")[-1]
                    if pred_name not in predicates_with_multival:
                        predicates_with_multival[pred_name] = {
                            "count": 0,
                            "uri": triple.predicate.uri,
                            "samples": [],
                        }
                    predicates_with_multival[pred_name]["count"] += 1
                    if len(predicates_with_multival[pred_name]["samples"]) < 3:
                        predicates_with_multival[pred_name]["samples"].append(obj_value[:50])

        if predicates_with_multival:
            self.stdout.write(f"\nPredicates with multi-value literals:")
            for pred_name, data in sorted(predicates_with_multival.items(), key=lambda x: -x[1]["count"]):
                self.stdout.write(
                    self.style.WARNING(f"\n  {pred_name}: {data['count']} literals")
                )
                self.stdout.write(f"    URI: {data['uri']}")
                self.stdout.write(f"    Samples: {data['samples']}")

            self.stdout.write(
                f"\nTo split, run with --predicate and --target-type arguments"
            )
            self.stdout.write(
                f"Example: python manage.py split_multivalue_literals --org {org} "
                f"--predicate <predicate-name> --target-type <entity-type> --dry-run"
            )
        else:
            self.stdout.write(self.style.SUCCESS("\nNo multi-value literals found!"))

    def _looks_like_id(self, value: str) -> bool:
        """Check if a value looks like an ID (numeric or alphanumeric)."""
        value = value.strip()
        if not value:
            return False
        # Numeric ID
        if value.isdigit():
            return True
        # Alphanumeric ID (like UUID parts)
        if re.match(r'^[A-Za-z0-9_-]+$', value) and len(value) < 50:
            return True
        return False

    def _split_literals(
        self, org: str, predicate_pattern: str, target_type: str,
        target_predicate: str, separator: str, dry_run: bool,
        delete_literals: bool, verbose: bool, limit: int, include_single: bool
    ):
        """Split multi-value literals into proper entity triples."""
        self.stdout.write(f"\nSplitting multi-value literals for org: {org}")
        self.stdout.write(f"Predicate pattern: {predicate_pattern}")
        self.stdout.write(f"Target entity type: {target_type}")
        self.stdout.write("=" * 60)

        org_uri_prefix = f"http://arkumu.org/data/{org}/"
        entity_prefix = f"{org_uri_prefix}entities/{target_type}/"

        # Find the predicate
        predicate = Resource.objects.filter(
            uri__icontains=predicate_pattern,
            uri__startswith=org_uri_prefix,
            resource_type=ResourceType.PROPERTY,
        ).first()

        if not predicate:
            # Try without org prefix
            predicate = Resource.objects.filter(
                uri__icontains=predicate_pattern,
                resource_type=ResourceType.PROPERTY,
            ).first()

        if not predicate:
            self.stderr.write(self.style.ERROR(f"Predicate not found: {predicate_pattern}"))
            return

        self.stdout.write(f"Found predicate: {predicate.uri}")

        # Find the target predicate for new triples
        if target_predicate:
            new_pred = Resource.objects.filter(
                uri__icontains=target_predicate,
                resource_type=ResourceType.PROPERTY,
            ).first()
        else:
            # Use canonical projektkategorie or try to find one
            new_pred = Resource.objects.filter(
                uri="http://arkumu.org/data/properties/projektkategorie",
                resource_type=ResourceType.PROPERTY,
            ).first()
            if not new_pred:
                # Try org-specific
                new_pred = Resource.objects.filter(
                    uri__startswith=org_uri_prefix,
                    uri__icontains="projektkategorie",
                    resource_type=ResourceType.PROPERTY,
                ).exclude(uri__icontains="export").first()

        if not new_pred:
            self.stderr.write(self.style.ERROR("Could not find target predicate for new triples"))
            return

        self.stdout.write(f"Target predicate for new triples: {new_pred.uri}")

        # Find triples with literal objects
        triples_qs = Triple.objects.filter(
            predicate=predicate,
            object__resource_type=ResourceType.LITERAL,
        ).select_related("subject", "object")

        if limit > 0:
            triples_qs = triples_qs[:limit]

        triples = list(triples_qs)
        self.stdout.write(f"Found {len(triples)} triples with literal objects")

        stats = {
            "triples_processed": 0,
            "values_split": 0,
            "entities_created": 0,
            "entities_existing": 0,
            "triples_created": 0,
            "literals_deleted": 0,
            "skipped": 0,
        }

        for triple in triples:
            obj_value = triple.object.value or triple.object.name or ""

            # Split by separator
            parts = [p.strip() for p in obj_value.split(separator) if p.strip()]

            # Skip empty values
            if not parts:
                stats["skipped"] += 1
                continue

            # Skip single values unless --include-single-values is set
            if len(parts) == 1 and not include_single:
                stats["skipped"] += 1
                continue

            stats["triples_processed"] += 1
            stats["values_split"] += len(parts)

            if verbose:
                self.stdout.write(f"\n  Subject: {triple.subject.uri}")
                self.stdout.write(f"  Literal: {obj_value}")
                self.stdout.write(f"  Split into: {parts}")

            if not dry_run:
                with transaction.atomic():
                    for value in parts:
                        # Find or create entity
                        entity_uri = f"{entity_prefix}{value}"
                        entity, created = Resource.objects.get_or_create(
                            uri=entity_uri,
                            defaults={
                                "name": value,
                                "resource_type": ResourceType.ENTITY,
                            }
                        )

                        if created:
                            stats["entities_created"] += 1
                            if verbose:
                                self.stdout.write(f"    Created entity: {entity_uri}")
                        else:
                            stats["entities_existing"] += 1

                        # Create triple
                        _, t_created = Triple.objects.get_or_create(
                            subject=triple.subject,
                            predicate=new_pred,
                            object=entity,
                        )
                        if t_created:
                            stats["triples_created"] += 1

                    # Delete original literal triple if requested
                    if delete_literals:
                        triple.delete()
                        stats["literals_deleted"] += 1
            else:
                # Dry run - just count
                for value in parts:
                    entity_uri = f"{entity_prefix}{value}"
                    exists = Resource.objects.filter(uri=entity_uri).exists()
                    if exists:
                        stats["entities_existing"] += 1
                    else:
                        stats["entities_created"] += 1
                    stats["triples_created"] += 1

                if delete_literals:
                    stats["literals_deleted"] += 1

        # Report
        self.stdout.write("")
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN: Would process {stats['triples_processed']} triples, "
                    f"split {stats['values_split']} values"
                )
            )
            self.stdout.write(
                f"  Would create {stats['entities_created']} new entities"
            )
            self.stdout.write(
                f"  Would reuse {stats['entities_existing']} existing entities"
            )
            self.stdout.write(
                f"  Would create {stats['triples_created']} new triples"
            )
            if delete_literals:
                self.stdout.write(
                    f"  Would delete {stats['literals_deleted']} literal triples"
                )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Processed {stats['triples_processed']} triples, "
                    f"split {stats['values_split']} values"
                )
            )
            self.stdout.write(
                f"  Created {stats['entities_created']} new entities"
            )
            self.stdout.write(
                f"  Reused {stats['entities_existing']} existing entities"
            )
            self.stdout.write(
                f"  Created {stats['triples_created']} new triples"
            )
            if delete_literals:
                self.stdout.write(
                    f"  Deleted {stats['literals_deleted']} literal triples"
                )

        if stats["skipped"] > 0:
            self.stdout.write(f"  Skipped {stats['skipped']} (no separator or single value)")
