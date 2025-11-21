from django.core.management.base import BaseCommand
from django.db import transaction
from arkumu.storage.models import S3FileObject
from arkumu.metadata.models.resource import Resource
from arkumu.metadata.models.triples import Triple


class Command(BaseCommand):
    help = "Link S3FileObjects to Resources by matching s3_key to dateipfad triples"

    def add_arguments(self, parser):
        parser.add_argument(
            '-o', '--organization',
            help='Organization code to process (e.g., fuk, khm)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be linked without making changes',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=500,
            help='Number of files to process per batch',
        )

    def handle(self, *args, **options):
        org_code = options.get('organization')
        dry_run = options.get('dry_run', False)
        batch_size = options.get('batch_size', 500)

        # Dateipfad canonical URIs
        dateipfad_uris = [
            'http://arkumu.org/data/properties/dateipfad',
        ]

        # Get unlinked S3FileObjects
        s3_qs = S3FileObject.objects.filter(
            related_resource_id__isnull=True,
            status__in=['completed', 'verified'],
        ).exclude(s3_key='').exclude(s3_key__isnull=True)

        if org_code:
            s3_qs = s3_qs.filter(organization=org_code)

        total_files = s3_qs.count()
        self.stdout.write(f"Found {total_files} unlinked S3 files")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - no changes will be made"))

        linked_count = 0
        not_found_count = 0

        # Process in batches
        for offset in range(0, total_files, batch_size):
            batch = list(s3_qs[offset:offset + batch_size])
            self.stdout.write(f"Processing batch {offset // batch_size + 1} ({len(batch)} files)...")

            with transaction.atomic():
                for s3file in batch:
                    # Normalize the s3_key for matching
                    s3_key = s3file.s3_key.replace('\\', '/').replace('//', '/')

                    # Try to find resource with matching dateipfad
                    matching_triple = Triple.objects.filter(
                        predicate__canonical_uri__in=dateipfad_uris
                    ).select_related('subject', 'object').filter(
                        object__value__icontains=s3file.file_name
                    ).first()

                    if matching_triple:
                        resource = matching_triple.subject

                        if not dry_run:
                            s3file.related_resource = resource
                            s3file.save(update_fields=['related_resource'])

                        linked_count += 1

                        if linked_count % 50 == 0:
                            self.stdout.write(f"  Linked {linked_count} files so far...")
                    else:
                        not_found_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"\nCompleted: {linked_count} linked, {not_found_count} not found"
            )
        )

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN completed - no changes were made")
            )
