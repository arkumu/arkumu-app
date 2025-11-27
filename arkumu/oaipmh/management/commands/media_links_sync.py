from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from arkumu.oaipmh.media_link_views import (
    _resolve_organization_by_code,
    _run_media_link_seed,
    _sync_oai_publication_for_org,
)
from arkumu.oaipmh.services import media_sync_jobs
from arkumu.oaipmh.tasks import run_media_link_seed_and_sync_job


class Command(BaseCommand):
    help = "Run curated media-link seed + OAI publication sync (same flow as dashboard buttons)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--organization",
            required=True,
            help="Organization code (e.g., fuk, khm)",
        )
        parser.add_argument(
            "--full",
            action="store_true",
            help="Force full refresh (process all projects instead of incremental).",
        )
        parser.add_argument(
            "--approvals-only",
            action="store_true",
            help="Skip seeding and only recompute OAI approvals.",
        )
        parser.add_argument(
            "--queue",
            action="store_true",
            help="Queue the seed+sync job via Huey instead of running inline.",
        )

    def handle(self, *args, **options):
        org_code = options["organization"]
        force_full = bool(options.get("full"))
        approvals_only = bool(options.get("approvals_only"))
        queue = bool(options.get("queue"))

        organization = _resolve_organization_by_code(org_code)
        if not organization:
            raise CommandError(f"Unknown organization code '{org_code}'.")

        if approvals_only and queue:
            raise CommandError("--approvals-only cannot be combined with --queue.")

        if queue:
            filters = {
                "project_access_filter": "all",
                "oai_publish_filter": "all",
                "harvestable_filter": "all",
                "search_query": "",
                "page_number": 1,
            }
            job_id = media_sync_jobs.create_job(
                organization_code=organization.code or "",
                user_id=None,
                filters=filters,
                force_full_refresh=force_full,
                message="Queued background media sync.",
            )
            run_media_link_seed_and_sync_job.schedule(args=(job_id,), delay=0)
            self.stdout.write(self.style.SUCCESS(f"Queued Huey job {job_id} for {organization.code.upper()}"))
            return

        if approvals_only:
            sync_summary = _sync_oai_publication_for_org(
                organization,
                user=None,
                force_full_refresh=force_full,
            )
            approved = sync_summary.get("auto_approved", 0)
            errors = sync_summary.get("errors", 0)
            self.stdout.write(
                self.style.SUCCESS(
                    f"OAI approval sync complete for {organization.code.upper()}: "
                    f"auto-approved {approved}, errors {errors}."
                )
            )
            return

        seed_summary = _run_media_link_seed(
            organization,
            force_full_refresh=force_full,
        )
        sync_summary = _sync_oai_publication_for_org(
            organization,
            user=None,
            force_full_refresh=force_full,
        )

        created = seed_summary.get("created", 0)
        refreshed = seed_summary.get("refreshed", 0)
        stale = seed_summary.get("stale", 0)
        skipped = seed_summary.get("skipped", 0)
        total_projects = seed_summary.get("projects", 0)

        approved = sync_summary.get("auto_approved", 0)
        errors = sync_summary.get("errors", 0)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seed+sync complete for {organization.code.upper()}: "
                f"projects {total_projects}, created {created}, refreshed {refreshed}, "
                f"stale {stale}, skipped {skipped}; auto-approved {approved}, errors {errors}."
            )
        )
