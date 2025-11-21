from __future__ import annotations

import itertools
import os
import threading
import time
from typing import Iterable, Sequence, Tuple

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection

from arkumu.metadata.canonical import canonical_uri
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.users.models import Organization


class Command(BaseCommand):
    """Materialize direct project→digital-object triples.

    - KHM: direct/shared-subject join (no events). Uses subjects that have both a
      project edge and a ``digitales-objekt`` edge, so we capture project↔digital pairs
      without traversing events.
    - Others: event-based join (event→project ∩ event→digital).

    Inserts derived triples with predicate set to the canonical ``digitales-objekt``.
    """

    help = "Materialize derived project→digital-object triples."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "-o",
            "--organization",
            action="append",
            dest="org_codes",
            help="Organization code to process (may be passed multiple times). Defaults to all organizations.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Only report counts; do not write triples.",
        )
        parser.add_argument(
            "--log-interval",
            type=int,
            nargs="?",
            const=50,
            default=0,
            dest="log_interval",
            help="Log progress every N batches (scan/insert). 0 disables progress logging.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=int(os.environ.get("PROJECT_DIGITAL_BATCH_SIZE", "2000")),
            dest="batch_size",
            help="Fetch/insert batch size (default 2000). Larger batches reduce round trips.",
        )
        parser.add_argument(
            "--skip-event-org",
            action="append",
            dest="skip_event_orgs",
            default=None,
            nargs="?",
            const="*",
            help="Org code to skip event-based flattening for (may be passed multiple times). Defaults to settings.PROJECT_DIGITAL_SKIP_EVENT_ORGS.",
        )

    def handle(self, *args, **options) -> None:
        org_codes: Iterable[str] | None = options.get("org_codes")
        dry_run: bool = bool(options.get("dry_run"))
        log_interval: int = max(int(options.get("log_interval") or 0), 0)
        batch_size: int = max(int(options.get("batch_size") or 2000), 1)

        cfg_skip: Iterable[str] = getattr(settings, "PROJECT_DIGITAL_SKIP_EVENT_ORGS", ("khm",))
        cli_skip_raw = options.get("skip_event_orgs")
        if cli_skip_raw is not None:
            skip_event_orgs = {code.lower().strip() for code in cli_skip_raw if code}
        else:
            skip_event_orgs = {code.lower().strip() for code in cfg_skip if code}
        skip_all = "*" in skip_event_orgs

        if org_codes:
            targets: Sequence[str] = [code.lower().strip() for code in org_codes if code]
        else:
            targets = (
                Organization.objects.filter(is_active=True)
                .values_list("code", flat=True)
                .order_by()
            )

        if not targets:
            self.stdout.write(self.style.WARNING("No organizations found."))
            return

        project_predicate_uri = canonical_uri("project")
        event_predicate_uri = canonical_uri("event")
        digital_predicate_uri = canonical_uri("digital_object")

        predicate_model = Resource
        digital_predicate_id = predicate_model.objects.filter(
            canonical_uri=digital_predicate_uri
        ).values_list("id", flat=True).first()
        if not digital_predicate_id:
            self.stdout.write(self.style.ERROR("Digital predicate resource not found; aborting."))
            return

        triple_table = Triple._meta.db_table
        resource_table = Triple._meta.get_field("subject").related_model._meta.db_table

        for code in targets:
            if not code:
                continue
            org = Organization.objects.filter(code__iexact=code).first()
            if not org:
                self.stdout.write(self.style.WARNING(f"[{code}] Organization not found."))
                continue

            self.stdout.write(f"Processing organization `{code}` (batch_size={batch_size}, log_interval={log_interval or 'off'})…")

            if code == "khm":
                pairs = self._collect_shared_subject_pairs_for_org(
                    org_id=str(org.id),
                    triple_table=triple_table,
                    resource_table=resource_table,
                    project_predicate_uri=project_predicate_uri,
                    digital_bridge_predicate=digital_predicate_uri,
                    target_predicate_id=digital_predicate_id,
                    log_interval=log_interval,
                    log_fn=self.stdout.write if log_interval else None,
                    batch_size=batch_size,
                )
            else:
                if skip_all or code in skip_event_orgs:
                    self.stdout.write("  Skipping event-based flattening for this org (configured to use direct project→digital only).")
                    continue
                pairs = self._collect_project_digital_pairs_for_org(
                    org_id=str(org.id),
                    triple_table=triple_table,
                    resource_table=resource_table,
                    project_predicate_uri=project_predicate_uri,
                    digital_predicate_uri=digital_predicate_uri,
                    event_predicate_uri=event_predicate_uri,
                    log_interval=log_interval,
                    log_fn=self.stdout.write if log_interval else None,
                    batch_size=batch_size,
                )

            if not pairs:
                self.stdout.write("  No project↔digital pairs found.\n")
                continue

            self.stdout.write(f"  Found {len(pairs)} unique project↔digital pairs.")

            if dry_run:
                self.stdout.write("  Dry-run enabled; skipping triple creation.\n")
                continue

            created = self._bulk_create_triples(
                pairs,
                log_interval=log_interval,
                log_fn=self.stdout.write if log_interval else None,
                batch_size=batch_size,
            )

            self.stdout.write(
                self.style.SUCCESS(
                    f"  Created {created} derived project→digital-object triple(s).\n"
                )
            )

    def _bulk_create_triples(
        self,
        pairs: set[Tuple[str, str, str]],
        *,
        log_interval: int = 0,
        log_fn=None,
        batch_size: int = 2000,
    ) -> int:
        """Insert derived triples in batches, ignoring existing rows."""

        if not pairs:
            return 0

        created = 0
        iterator = iter(pairs)
        batch_num = 0
        log_interval = max(int(log_interval or 0), 0)

        while True:
            batch = list(itertools.islice(iterator, batch_size))
            if not batch:
                break
            batch_num += 1

            triples = [
                Triple(
                    subject_id=subject_id,
                    predicate_id=predicate_id,
                    object_id=object_id,
                    source=None,
                    is_derived=True,
                )
                for subject_id, predicate_id, object_id in batch
            ]
            created += len(
                Triple.objects.bulk_create(
                    triples,
                    batch_size=batch_size,
                    ignore_conflicts=True,
                )
            )
            if log_interval and log_fn and batch_num % log_interval == 0:
                log_fn(f"  … inserted batch {batch_num:,} (total created so far: {created:,})")

        return created

    def _collect_project_digital_pairs_for_org(
        self,
        *,
        org_id: str,
        triple_table: str,
        resource_table: str,
        project_predicate_uri: str,
        digital_predicate_uri: str,
        event_predicate_uri: str | None = None,
        log_interval: int = 0,
        log_fn=None,
        batch_size: int = 2000,
    ) -> set[Tuple[str, str, str]]:
        """Event-based: project_id from event→project; digital_id from event→digital."""

        event_predicate_uri = event_predicate_uri or project_predicate_uri
        log_interval = max(int(log_interval or 0), 0)
        batch_size = max(int(batch_size or 2000), 1)

        if log_fn:
            log_fn(
                f"  … query predicates project={project_predicate_uri}, event={event_predicate_uri}, digital={digital_predicate_uri}"
            )

        sql = f"""
            WITH project_events AS (
                SELECT tp.object_id AS project_id, te.object_id AS event_id
                FROM {triple_table} tp
                JOIN {triple_table} te ON te.subject_id = tp.subject_id
                JOIN {resource_table} subj ON subj.id = tp.subject_id
                JOIN {resource_table} pred_p ON pred_p.id = tp.predicate_id
                JOIN {resource_table} pred_e ON pred_e.id = te.predicate_id
                JOIN {resource_table} obj_p ON obj_p.id = tp.object_id
                JOIN {resource_table} obj_e ON obj_e.id = te.object_id
                WHERE pred_p.canonical_uri = %s
                  AND pred_e.canonical_uri = %s
                  AND subj.organization_id = %s
                  AND subj.resource_type = %s
                  AND obj_p.resource_type = %s
                  AND obj_e.resource_type = %s
            ),
            event_digital AS (
                SELECT te.object_id AS event_id, td.object_id AS digital_id, td.predicate_id AS digital_predicate_id
                FROM {triple_table} td
                JOIN {triple_table} te ON te.subject_id = td.subject_id
                JOIN {resource_table} subj ON subj.id = td.subject_id
                JOIN {resource_table} pred_e ON pred_e.id = te.predicate_id
                JOIN {resource_table} pred_d ON pred_d.id = td.predicate_id
                JOIN {resource_table} obj_e ON obj_e.id = te.object_id
                JOIN {resource_table} obj_d ON obj_d.id = td.object_id
                WHERE pred_e.canonical_uri = %s
                  AND pred_d.canonical_uri = %s
                  AND subj.organization_id = %s
                  AND subj.resource_type = %s
                  AND obj_e.resource_type = %s
                  AND obj_d.resource_type = %s
            )
            SELECT pe.project_id, ed.digital_id, ed.digital_predicate_id
            FROM project_events pe
            JOIN event_digital ed ON ed.event_id = pe.event_id
        """
        params = [
            project_predicate_uri,
            event_predicate_uri,
            org_id,
            ResourceType.ENTITY,
            ResourceType.ENTITY,
            ResourceType.ENTITY,
            event_predicate_uri,
            digital_predicate_uri,
            org_id,
            ResourceType.ENTITY,
            ResourceType.ENTITY,
            ResourceType.ENTITY,
        ]

        pairs: set[Tuple[str, str, str]] = set()
        scanned_batches = 0

        if log_interval and log_fn:
            log_fn("  … collecting pairs (may take a moment before the first batch)…")
            log_fn("  … executing query (this may take 30-60 seconds on large datasets)…")

        # Heartbeat thread to show progress while query executes
        def heartbeat(interval, log_fn, stop_event):
            """Print 'still waiting' messages periodically."""
            count = 0
            while not stop_event.is_set():
                time.sleep(interval)
                if not stop_event.is_set():
                    count += 1
                    log_fn(f"  … still waiting for query results ({count * interval}s elapsed)…")

        stop_event = threading.Event()
        heartbeat_thread = None
        if log_interval and log_fn:
            heartbeat_thread = threading.Thread(target=heartbeat, args=(5, log_fn, stop_event), daemon=True)
            heartbeat_thread.start()

        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                if log_interval and log_fn:
                    stop_event.set()
                    log_fn("  … query returned, processing results…")

                while True:
                    rows = cursor.fetchmany(batch_size)
                    if not rows:
                        break
                    scanned_batches += 1
                    if log_interval and log_fn and scanned_batches % log_interval == 0:
                        log_fn(
                            f"  … scanned batch {scanned_batches:,} "
                            f"(unique pairs so far: {len(pairs):,})"
                        )
                    for project_id, digital_id, predicate_id in rows:
                        if project_id and digital_id and predicate_id:
                            pairs.add((str(project_id), str(predicate_id), str(digital_id)))
        finally:
            if log_interval and log_fn:
                stop_event.set()
                if heartbeat_thread:
                    heartbeat_thread.join(timeout=1)

        if log_interval and log_fn:
            log_fn(f"  … finished scan after {scanned_batches:,} batches, {len(pairs):,} unique pairs")

        return pairs

    def _collect_shared_subject_pairs_for_org(
        self,
        *,
        org_id: str,
        triple_table: str,
        resource_table: str,
        project_predicate_uri: str,
        digital_bridge_predicate: str,
        target_predicate_id: str,
        log_interval: int = 0,
        log_fn=None,
        batch_size: int = 2000,
    ) -> set[Tuple[str, str, str]]:
        """KHM-only: subjects with a project edge and a digital bridge edge."""

        log_interval = max(int(log_interval or 0), 0)
        batch_size = max(int(batch_size or 2000), 1)

        if log_fn:
            log_fn(
                f"  … shared-subject query predicates project={project_predicate_uri}, bridge={digital_bridge_predicate}"
            )

        sql = f"""
            SELECT tp.object_id AS project_id, td.object_id AS digital_id
            FROM {triple_table} tp
            JOIN {triple_table} td ON td.subject_id = tp.subject_id
            JOIN {resource_table} subj ON subj.id = tp.subject_id
            JOIN {resource_table} pred_p ON pred_p.id = tp.predicate_id
            JOIN {resource_table} pred_d ON pred_d.id = td.predicate_id
            JOIN {resource_table} obj_p ON obj_p.id = tp.object_id
            JOIN {resource_table} obj_d ON obj_d.id = td.object_id
            WHERE pred_p.canonical_uri = %s
              AND pred_d.canonical_uri = %s
              AND subj.organization_id = %s
              AND subj.resource_type = %s
              AND obj_p.resource_type = %s
              AND obj_d.resource_type = %s
        """
        params = [
            project_predicate_uri,
            digital_bridge_predicate,
            org_id,
            ResourceType.ENTITY,
            ResourceType.ENTITY,
            ResourceType.ENTITY,
        ]

        pairs: set[Tuple[str, str, str]] = set()
        scanned_batches = 0

        if log_interval and log_fn:
            log_fn("  … collecting shared-subject pairs (may take a moment before first batch)…")
            log_fn("  … executing query (this may take 30-60 seconds on large datasets)…")

        # Heartbeat thread to show progress while query executes
        def heartbeat(interval, log_fn, stop_event):
            """Print 'still waiting' messages periodically."""
            count = 0
            while not stop_event.is_set():
                time.sleep(interval)
                if not stop_event.is_set():
                    count += 1
                    log_fn(f"  … still waiting for query results ({count * interval}s elapsed)…")

        stop_event = threading.Event()
        heartbeat_thread = None
        if log_interval and log_fn:
            heartbeat_thread = threading.Thread(target=heartbeat, args=(5, log_fn, stop_event), daemon=True)
            heartbeat_thread.start()

        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                if log_interval and log_fn:
                    stop_event.set()
                    log_fn("  … query returned, processing results…")

                while True:
                    rows = cursor.fetchmany(batch_size)
                    if not rows:
                        break
                    scanned_batches += 1
                    if log_interval and log_fn and scanned_batches % log_interval == 0:
                        log_fn(
                            f"  … scanned batch {scanned_batches:,} "
                            f"(unique pairs so far: {len(pairs):,})"
                        )
                    for project_id, digital_id in rows:
                        if project_id and digital_id:
                            pairs.add((str(project_id), str(target_predicate_id), str(digital_id)))
        finally:
            if log_interval and log_fn:
                stop_event.set()
                if heartbeat_thread:
                    heartbeat_thread.join(timeout=1)

        if log_interval and log_fn:
            log_fn(
                f"  … finished shared-subject scan after {scanned_batches:,} batches, {len(pairs):,} unique pairs"
            )

        return pairs
