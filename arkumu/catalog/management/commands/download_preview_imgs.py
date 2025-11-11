from django.core.management import BaseCommand

from arkumu.catalog.services.download_previews import DownloadPreviews


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force download')

    def handle(self, *args, **options):
        DownloadPreviews().download_previews(options['force'])
