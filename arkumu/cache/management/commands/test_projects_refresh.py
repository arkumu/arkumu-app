"""Management command to verify project snapshot cache refresh."""

from django.core.management.base import BaseCommand

from arkumu.cache.services.project_cache_service import ProjectCacheService
from arkumu.projects.services import ProjectSnapshotService


class Command(BaseCommand):
    help = "Test the cross-institutional projects cache refresh flow"

    def handle(self, *args, **options):
        self.stdout.write("=== Testing Projects Cache Refresh ===")

        cache_service = ProjectCacheService()
        snapshot_service = ProjectSnapshotService()

        existing_snapshot = cache_service.get_cross_institutional_snapshot()
        if existing_snapshot:
            self.stdout.write(
                f"Cache before refresh: {len(existing_snapshot.projects)} projects, counts={existing_snapshot.counts}"
            )
        else:
            self.stdout.write("Cache before refresh: EMPTY")

        self.stdout.write("\nRefreshing snapshot via ProjectSnapshotService...\n")
        snapshot = snapshot_service.refresh_cross_institutional_snapshot()
        self.stdout.write(
            self.style.SUCCESS(
                f"Refresh completed: {len(snapshot.projects)} projects, counts={snapshot.counts}"
            )
        )

        post_snapshot = cache_service.get_cross_institutional_snapshot()
        if post_snapshot:
            self.stdout.write(
                f"Cache after refresh: {len(post_snapshot.projects)} projects, counts={post_snapshot.counts}"
            )
        else:
            self.stdout.write(self.style.ERROR("Cache after refresh: EMPTY"))

        self.stdout.write("=== Test Complete ===")
