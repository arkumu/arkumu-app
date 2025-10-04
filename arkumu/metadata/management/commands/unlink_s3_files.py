from django.core.management.base import BaseCommand
from arkumu.storage.models import S3FileObject

class Command(BaseCommand):
    help = "Unlink S3FileObject rows from their related resources."

    def add_arguments(self, parser):
        parser.add_argument('--bucket', dest='bucket', help='Limit to files uploaded via sessions for this bucket/org code.')
        parser.add_argument('--uri-prefix', dest='uri_prefix', help='Limit to resources whose URI starts with this prefix.')
        parser.add_argument('--mime-prefix', dest='mime_prefix', help='Limit to files whose MIME type starts with this value.')
        parser.add_argument('--dry-run', action='store_true', help='Report how many files would be unlinked without applying changes.')

    def handle(self, *args, **options):
        qs = S3FileObject.objects.exclude(related_resource__isnull=True)
        bucket = options['bucket']
        uri_prefix = options['uri_prefix']
        mime_prefix = options['mime_prefix']

        if bucket:
            qs = qs.filter(session__s3_bucket=bucket)
        if uri_prefix:
            qs = qs.filter(related_resource__uri__startswith=uri_prefix)
        if mime_prefix:
            qs = qs.filter(content_type__startswith=mime_prefix)

        count = qs.count()
        if count == 0:
            self.stdout.write(self.style.WARNING('No matching linked files found.'))
            return

        if options['dry_run']:
            self.stdout.write(f"[dry-run] Would unlink {count} S3 file(s).")
            return

        updated = qs.update(related_resource=None)
        self.stdout.write(self.style.SUCCESS(f"Unlinked {updated} S3 file(s)."))
