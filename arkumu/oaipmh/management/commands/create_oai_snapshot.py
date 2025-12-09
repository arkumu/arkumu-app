"""Management command to create/refresh the OAI snapshot in the database.

Reads ProjectRecord from ProjectIndex.record_jsonb (pre-computed):
1. ProjectIndex.to_record() -> ProjectRecord
2. OAIProjectBuilder.from_project_record() -> OAIProject
3. Legacy _build_metadata_element for XML serialization
4. Write to DB in batches

No graph queries needed - uses pre-computed data from ProjectIndex.
"""

import logging
import time
from collections import Counter
from typing import Dict, List, Optional

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone
from lxml import etree as ET

from arkumu.catalog.models import ProjectIndex
from arkumu.metadata.models.resource import Resource, PublicAccessLevel
from arkumu.oaipmh.models import OAISnapshotMeta, OAISnapshotRecord
from arkumu.oaipmh.oai_project import OAIProjectBuilder
from arkumu.oaipmh.views.legacy import (
    _build_metadata_element,
    _build_record_header,
    _db_assembler_override,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Create OAI snapshot from ProjectIndex (pre-computed ProjectRecord data)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Clear existing snapshot without creating a new one.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=50,
            help="Number of records to write per DB batch (default: 50).",
        )
        parser.add_argument(
            "--skip-mets",
            action="store_true",
            help="Skip METS serialization (faster, DC only).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Count records without creating snapshot.",
        )

    def handle(self, *args, **options):
        if options["clear"]:
            OAISnapshotRecord.objects.all().delete()
            OAISnapshotMeta.objects.all().delete()
            self.stdout.write(self.style.SUCCESS("Cleared OAI snapshot"))
            return

        batch_size = options["batch_size"]
        skip_mets = options["skip_mets"]
        dry_run = options["dry_run"]

        t_start = time.time()

        # Step 1: Load ProjectIndex entries with record_jsonb
        self.stdout.write("Loading ProjectIndex entries...")
        t_load_start = time.time()

        project_indices = list(
            ProjectIndex.objects
            .exclude(record_jsonb={})
            .select_related("project_resource__organization")
        )
        t_load = time.time() - t_load_start
        self.stdout.write(f"  Loaded {len(project_indices)} entries in {t_load:.1f}s")

        # Step 2: Convert to ProjectRecord and filter harvestable
        self.stdout.write("Building ProjectRecords...")
        t_records_start = time.time()

        project_builder = OAIProjectBuilder()
        harvestable_projects = []

        for idx in project_indices:
            record = idx.to_record()
            if not record:
                continue

            project = project_builder.from_project_record(
                record,
                skip_shared_event_filter=False,
                skip_format_exclusion=False,
                use_curated_media_links=False,
            )

            if project.harvestable:
                harvestable_projects.append((idx, project))

        t_records = time.time() - t_records_start
        self.stdout.write(f"  {len(harvestable_projects)} harvestable in {t_records:.1f}s")

        if dry_run:
            self.stdout.write(f"Dry run - not creating snapshot")
            return

        # Clear existing data
        self.stdout.write("Clearing existing snapshot...")
        OAISnapshotRecord.objects.all().delete()
        OAISnapshotMeta.objects.all().delete()

        # Step 3: Load resources for header/access check
        self.stdout.write("Loading resources...")
        project_uris = [idx.uri for idx, _ in harvestable_projects]

        access_clause = Q(public_access_level=PublicAccessLevel.RESTRICTED) | (
            Q(public_access_level=PublicAccessLevel.PUBLIC) & Q(is_public_approved=True)
        )

        resources_by_uri: Dict[str, Resource] = {}
        for resource in (
            Resource.objects.filter(uri__in=project_uris)
            .filter(access_clause)
            .select_related("organization")
        ):
            resources_by_uri[resource.uri] = resource

        self.stdout.write(f"  {len(resources_by_uri)} accessible resources")

        # Step 4: Serialize and write in batches
        batch: List[OAISnapshotRecord] = []
        position = 0
        errors = 0
        org_counts: Counter = Counter()

        total = len(harvestable_projects)
        self.stdout.write(f"Serializing {total} records...")

        for idx, project in harvestable_projects:
            resource = resources_by_uri.get(project.uri)
            if not resource:
                continue

            try:
                snapshot_record = self._serialize_to_record(
                    position, resource, project, skip_mets=skip_mets,
                )
                if snapshot_record:
                    batch.append(snapshot_record)
                    org_code = resource.organization.code if resource.organization else "unknown"
                    org_counts[org_code] += 1
                    position += 1
            except Exception as exc:
                logger.exception("Failed to serialize %s: %s", project.uri, exc)
                errors += 1

            if len(batch) >= batch_size:
                OAISnapshotRecord.objects.bulk_create(batch)
                batch = []
                elapsed = time.time() - t_start
                rate = position / elapsed if elapsed > 0 else 0
                self.stdout.write(
                    f"  {position}/{total} ({rate:.1f}/sec), {errors} errors"
                )

        if batch:
            OAISnapshotRecord.objects.bulk_create(batch)

        OAISnapshotMeta.objects.create(
            generated_at=timezone.now(),
            total_count=position,
            counts_by_org=dict(org_counts),
        )

        elapsed = time.time() - t_start
        self.stdout.write(
            self.style.SUCCESS(f"Created snapshot with {position} records in {elapsed:.1f}s")
        )
        self.stdout.write(f"  Counts by org: {dict(org_counts)}")
        if errors:
            self.stdout.write(self.style.WARNING(f"  Errors: {errors}"))

    def _serialize_to_record(
        self,
        position: int,
        resource: Resource,
        project,
        *,
        skip_mets: bool,
    ) -> Optional[OAISnapshotRecord]:
        """Serialize a project to OAISnapshotRecord."""

        # Force non-simplified mode for Rosetta-compatible METS (no metsHdr)
        _db_assembler_override.set(False)

        try:
            header_elem = _build_record_header(resource)
            header_xml = ET.tostring(header_elem, encoding="unicode")

            dc_metadata_elem = _build_metadata_element(
                resource,
                "oai_dc",
                project_hint=project,
            )
            dc_xml = ET.tostring(dc_metadata_elem, encoding="unicode")

            mets_xml = ""
            if not skip_mets:
                mets_metadata_elem = _build_metadata_element(
                    resource,
                    "mets",
                    project_hint=project,
                )
                mets_xml = ET.tostring(mets_metadata_elem, encoding="unicode")

            return OAISnapshotRecord(
                position=position,
                uri=resource.uri,
                datestamp=resource.updated_at,
                organization=resource.organization,
                header_xml=header_xml,
                metadata_dc_xml=dc_xml,
                metadata_mets_xml=mets_xml,
            )
        finally:
            _db_assembler_override.set(None)
