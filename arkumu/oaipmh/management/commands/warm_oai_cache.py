"""
Management command to warm OAI-PMH cache using Huey tasks.
"""

from django.core.management.base import BaseCommand
from arkumu.oaipmh.tasks import (
    warm_popular_records,
    warm_page_cache,
    warm_resource_cache,
    manual_refresh_oai_cache,
    manual_refresh_recent_records
)


class Command(BaseCommand):
    help = 'Warm OAI-PMH cache using Huey background tasks'

    def add_arguments(self, parser):
        parser.add_argument(
            '--mode',
            type=str,
            choices=['popular', 'pages', 'full', 'recent'],
            default='popular',
            help='Cache warming mode (default: popular)',
        )
        parser.add_argument(
            '--pages',
            type=int,
            default=10,
            help='Number of pages to warm (default: 10)',
        )
        parser.add_argument(
            '--format',
            type=str,
            choices=['oai_dc', 'mets', 'both'],
            default='both',
            help='Metadata format to warm (default: both)',
        )

    def handle(self, *args, **options):
        mode = options['mode']
        pages = options['pages']
        format_choice = options['format']

        self.stdout.write(
            self.style.SUCCESS(f'🔥 Starting OAI-PMH cache warming (mode: {mode})')
        )

        if mode == 'popular':
            # Warm popular records
            warm_popular_records.schedule()
            self.stdout.write(
                self.style.SUCCESS('✅ Scheduled popular records cache warming')
            )

        elif mode == 'pages':
            # Warm specific number of pages
            formats = ['oai_dc', 'mets'] if format_choice == 'both' else [format_choice]

            for metadata_format in formats:
                for page_num in range(pages):
                    offset = page_num * 100
                    warm_page_cache.schedule(
                        args=(metadata_format, '', '', '', offset),
                        delay=page_num * 5  # 5 second delay between pages
                    )

                self.stdout.write(
                    self.style.SUCCESS(f'✅ Scheduled {pages} pages for {metadata_format} format')
                )

        elif mode == 'full':
            # Full cache refresh (equivalent to daily task)
            try:
                from arkumu.oaipmh.tasks import HUEY_PERIODIC_AVAILABLE
                if HUEY_PERIODIC_AVAILABLE:
                    from arkumu.oaipmh.tasks import refresh_oai_cache
                    refresh_oai_cache.schedule()
                else:
                    manual_refresh_oai_cache.schedule()

                self.stdout.write(
                    self.style.SUCCESS('✅ Scheduled full OAI-PMH cache refresh')
                )
            except ImportError:
                manual_refresh_oai_cache.schedule()
                self.stdout.write(
                    self.style.SUCCESS('✅ Scheduled manual full cache refresh')
                )

        elif mode == 'recent':
            # Refresh recently updated records
            try:
                from arkumu.oaipmh.tasks import HUEY_PERIODIC_AVAILABLE
                if HUEY_PERIODIC_AVAILABLE:
                    from arkumu.oaipmh.tasks import refresh_recent_records
                    refresh_recent_records.schedule()
                else:
                    manual_refresh_recent_records.schedule()

                self.stdout.write(
                    self.style.SUCCESS('✅ Scheduled recent records cache refresh')
                )
            except ImportError:
                manual_refresh_recent_records.schedule()
                self.stdout.write(
                    self.style.SUCCESS('✅ Scheduled manual recent records refresh')
                )

        self.stdout.write(
            self.style.SUCCESS(f'🎉 Cache warming tasks scheduled! Monitor with Huey worker logs.')
        )