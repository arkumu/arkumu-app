"""Link S3 file objects directly to their digital object resources in bulk."""

from __future__ import annotations

from typing import Iterable

from django.core.management.base import BaseCommand
from django.db import models, transaction

from arkumu.storage.models import S3FileObject
from arkumu.metadata.models import Resource
from arkumu.metadata.services.metatdata_s3_mapping.map_resources_to_files import (
    FileResourceMatcherService,
    MatchingConfig,
)
from arkumu.cache.services import OAICacheService


class Command(BaseCommand):
    help = (
        "Link unassigned, verified S3FileObject rows to their digital object resources "
        "using filename-to-resource matching."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--bucket",
            dest="bucket",
            help="Limit processing to files discovered in the given bucket/organization code.",
        )
        parser.add_argument(
            "--limit",
            dest="limit",
            type=int,
            help="Maximum number of S3 files to process (ordered by creation time).",
        )
        parser.add_argument(
            "--batch-size",
            dest="batch_size",
            type=int,
            default=1000,
            help="Batch size for matcher bulk updates (default: 1000).",
        )
        parser.add_argument(
            "--case-sensitive",
            dest="case_sensitive",
            action="store_true",
            help="Perform filename matching with case sensitivity (default: case-insensitive).",
        )
        parser.add_argument(
            "--dry-run",
            dest="dry_run",
            action="store_true",
            help="Compute stats without writing changes to the database.",
        )
        parser.add_argument(
            "--verbose",
            dest="verbose",
            action="store_true",
            help="Enable verbose logging to diagnose matching issues.",
        )

    def handle(self, *args, **options):
        bucket = options["bucket"]
        limit = options["limit"]
        batch_size = options["batch_size"]
        case_sensitive = options["case_sensitive"]
        dry_run = options["dry_run"]
        verbose = options["verbose"]

        queryset = S3FileObject.objects.filter(
            related_resource__isnull=True,
            status="verified",
        )

        if bucket:
            queryset = queryset.filter(
                models.Q(session__s3_bucket=bucket)
                | models.Q(organization=bucket)
            )

        queryset = queryset.order_by("created_at", "id")

        if limit:
            queryset = queryset[:limit]

        candidate_ids = list(queryset.values_list("id", flat=True))
        total_candidates = len(candidate_ids)

        if total_candidates == 0:
            self.stdout.write(self.style.WARNING("No unlinked verified S3 files matched the provided filters."))
            return

        self.stdout.write(
            f"Found {total_candidates} unlinked file(s) to process"
            + (f" in bucket '{bucket}'" if bucket else "")
            + (f" (limit {limit})" if limit else "")
            + (" [dry-run]" if dry_run else "")
        )

        if dry_run:
            return

        config = MatchingConfig(batch_size=batch_size, case_sensitive=case_sensitive, verbose=verbose)

        matcher = FileResourceMatcherService(
            logger_func=lambda msg, level="info": self.stdout.write(msg),
            config=config,
        )

        with transaction.atomic():
            processed, linked, ambiguous, errors = matcher.match_and_link_by_filename_to_resource_value(
                S3FileObject.objects.filter(id__in=candidate_ids),
                link_target="digital_object",
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Digital object linking complete. Processed: {processed}, Linked: {linked}, Ambiguous: {ambiguous}, Errors: {errors}"
            )
        )

        if linked <= 0:
            return

        updated_resource_ids = (
            S3FileObject.objects.filter(id__in=candidate_ids, related_resource__isnull=False)
            .values_list("related_resource_id", flat=True)
            .distinct()
        )

        self._warm_oai_cache(updated_resource_ids)

    def _warm_oai_cache(self, resource_ids: Iterable[int]):
        resources = list(Resource.objects.filter(id__in=resource_ids).select_related("organization"))
        if not resources:
            return

        cache = OAICacheService()
        warmed = 0
        for resource in resources:
            try:
                cache.invalidate_resource(resource.uri)
                cache.warm_resource_with_graph_integration(resource, metadata_prefixes=["oai_dc", "mets"])
                warmed += 1
            except Exception as exc:
                self.stderr.write(f"Cache warm failed for {resource.uri}: {exc}")

        self.stdout.write(self.style.SUCCESS(f"Warm OAI cache for {warmed} resource(s)."))
