"""Database-backed OAI snapshot service.

Simple approach: one frozen snapshot with pre-serialized XML.
Records are replaced entirely when a new snapshot is generated.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Dict, List, Optional

from django.db import transaction
from django.utils import timezone
from lxml import etree as ET

from arkumu.oaipmh.models import OAISnapshotMeta, OAISnapshotRecord
from arkumu.users.models import Organization

logger = logging.getLogger(__name__)


class OAISnapshotService:
    """Manages the single OAI snapshot in the database."""

    def get_meta(self) -> Optional[OAISnapshotMeta]:
        """Return the current snapshot metadata."""
        return OAISnapshotMeta.get_current()

    def get_generated_at(self) -> Optional[str]:
        """Return the snapshot generation timestamp as ISO string."""
        meta = self.get_meta()
        if meta:
            return meta.generated_at.isoformat()
        return None

    def get_total_count(
        self,
        *,
        organization: Optional[Organization] = None,
    ) -> int:
        """Return total record count, optionally filtered by org."""
        qs = OAISnapshotRecord.objects.all()
        if organization:
            qs = qs.filter(organization=organization)
        return qs.count()

    def get_records(
        self,
        *,
        organization: Optional[Organization] = None,
        offset: int = 0,
        limit: int = 100,
    ) -> List[OAISnapshotRecord]:
        """Return records with pagination."""
        qs = OAISnapshotRecord.objects.all()
        if organization:
            qs = qs.filter(organization=organization)
        return list(qs.order_by("position")[offset : offset + limit])

    def get_record_by_uri(self, uri: str) -> Optional[OAISnapshotRecord]:
        """Look up a single record by URI."""
        return OAISnapshotRecord.objects.filter(uri=uri).first()

    @transaction.atomic
    def replace_snapshot(
        self,
        records: List[Dict],
        generated_at=None,
    ) -> OAISnapshotMeta:
        """Replace all records with a new snapshot.

        Args:
            records: List of dicts with keys:
                - uri: str
                - datestamp: datetime
                - organization: Organization or None
                - header_xml: str
                - metadata_dc_xml: str (optional)
                - metadata_mets_xml: str (optional)
            generated_at: Timestamp for the snapshot (defaults to now)

        Returns:
            The updated OAISnapshotMeta.
        """
        generated_at = generated_at or timezone.now()

        # Delete all existing records
        OAISnapshotRecord.objects.all().delete()

        # Count by org
        org_counts: Counter = Counter()
        records_to_create: List[OAISnapshotRecord] = []

        for position, record_data in enumerate(records):
            org = record_data.get("organization")
            org_code = org.code if org else "unknown"
            org_counts[org_code] += 1

            records_to_create.append(
                OAISnapshotRecord(
                    position=position,
                    uri=record_data["uri"],
                    datestamp=record_data["datestamp"],
                    organization=org,
                    header_xml=record_data["header_xml"],
                    metadata_dc_xml=record_data.get("metadata_dc_xml", ""),
                    metadata_mets_xml=record_data.get("metadata_mets_xml", ""),
                )
            )

        if records_to_create:
            OAISnapshotRecord.objects.bulk_create(records_to_create, batch_size=500)

        # Update or create metadata
        OAISnapshotMeta.objects.all().delete()
        meta = OAISnapshotMeta.objects.create(
            generated_at=generated_at,
            total_count=len(records_to_create),
            counts_by_org=dict(org_counts),
        )

        logger.info(
            "OAISnapshotService: replaced snapshot with %d records (generated_at=%s)",
            len(records_to_create),
            generated_at.isoformat(),
        )

        return meta

    def clear_snapshot(self) -> None:
        """Delete all snapshot data."""
        OAISnapshotRecord.objects.all().delete()
        OAISnapshotMeta.objects.all().delete()
        logger.info("OAISnapshotService: cleared all snapshot data")


# Singleton instance
oai_snapshot_service = OAISnapshotService()
