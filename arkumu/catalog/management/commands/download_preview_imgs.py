import hashlib

from django.db.models import Q
from django.core.management import BaseCommand

from arkumu.catalog.models import PreviewImages
from arkumu.catalog.services.download_previews import DownloadPreviews


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force download')
        parser.add_argument(
            '--backfill-etags',
            action='store_true',
            help='Backfill ETags for existing images without re-downloading')
        parser.add_argument(
            '--cleanup',
            action='store_true',
            help='Remove images with un-normalized paths (backslashes or spaces)')

    def handle(self, *args, **options):
        if options['cleanup']:
            self._cleanup_unnormalized()
        elif options['backfill_etags']:
            self._backfill_etags()
        else:
            DownloadPreviews().download_previews(options['force'])

    def _backfill_etags(self):
        qs = PreviewImages.objects.filter(etag='')
        total = qs.count()
        self.stdout.write(f'Found {total} images without ETag')

        updated = 0
        for img in qs.iterator():
            img.etag = hashlib.md5(img.img).hexdigest()
            img.save(update_fields=['etag'])
            updated += 1

        self.stdout.write(self.style.SUCCESS(f'Updated {updated} images'))

    def _cleanup_unnormalized(self):
        qs = PreviewImages.objects.filter(Q(path__contains='\\') | Q(path__contains=' '))
        count = qs.count()
        self.stdout.write(f'Found {count} images with un-normalized paths')
        deleted, _ = qs.delete()
        self.stdout.write(self.style.SUCCESS(f'Deleted {deleted} images'))
