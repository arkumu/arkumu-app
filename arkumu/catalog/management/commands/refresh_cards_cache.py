from django.core.management.base import BaseCommand

from arkumu.catalog.services.project_index_service import (
    invalidate_cards_cache,
    warm_cards_cache,
)


class Command(BaseCommand):
    help = "Refresh the Redis cards cache for catalog search."

    def handle(self, *args, **options):
        self.stdout.write("Invalidating cards cache...")
        invalidate_cards_cache()

        self.stdout.write("Warming cards cache...")
        count = warm_cards_cache()

        self.stdout.write(
            self.style.SUCCESS(f"Cache refreshed: {count} cards loaded")
        )
