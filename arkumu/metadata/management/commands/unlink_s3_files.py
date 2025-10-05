from django.core.management.base import BaseCommand
from django.db import models

from arkumu.storage.models import S3FileObject

class Command(BaseCommand):
    help = "Unlink S3FileObject rows from their related resources."

    def add_arguments(self, parser):
        parser.add_argument('--bucket', dest='bucket', help='Limit to files belonging to this organization/bucket code.')
        parser.add_argument('--uri-prefix', dest='uri_prefix', help='Limit to resources whose URI starts with this prefix.')
        parser.add_argument('--mime-prefix', dest='mime_prefix', help='Limit to files whose MIME type starts with this value.')
        parser.add_argument('--status', dest='status', choices=['pending', 'uploading', 'completed', 'failed', 'verified'], help='Limit to files with the given status.')
        parser.add_argument('--missing-only', dest='missing_only', action='store_true', help='Only unlink files that no longer exist in S3.')
        parser.add_argument('--dry-run', action='store_true', help='Report how many files would be unlinked without applying changes.')

    def handle(self, *args, **options):
        qs = S3FileObject.objects.exclude(related_resource__isnull=True)
        bucket = options['bucket']
        uri_prefix = options['uri_prefix']
        mime_prefix = options['mime_prefix']
        status = options['status']
        missing_only = options['missing_only']

        if bucket:
            qs = qs.filter(
                models.Q(session__s3_bucket=bucket) |
                models.Q(organization=bucket)
            )
        if uri_prefix:
            qs = qs.filter(related_resource__uri__startswith=uri_prefix)
        if mime_prefix:
            qs = qs.filter(content_type__startswith=mime_prefix)
        if status:
            qs = qs.filter(status=status)

        if missing_only:
            ids = []
            for obj in qs.iterator():
                if not obj.exists_in_s3():
                    ids.append(obj.id)
            qs = S3FileObject.objects.filter(id__in=ids)

        count = qs.count()
        if count == 0:
            self.stdout.write(self.style.WARNING('No matching linked files found.'))
            return

        if options['dry_run']:
            self.stdout.write(f"[dry-run] Would unlink {count} S3 file(s).")
            return

        updated = qs.update(related_resource=None)
        self.stdout.write(self.style.SUCCESS(f"Unlinked {updated} S3 file(s)."))
