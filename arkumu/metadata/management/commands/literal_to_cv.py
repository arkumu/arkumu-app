"""
Management command to convert literal values to controlled vocabulary references.

Some archives store CV values as literal strings (e.g., "Filmfestival") instead of
entity references. This command matches those literals to CV entities by label and
updates the triples to point to the CV entity.

Usage:
    python manage.py literal_to_cv --org khm --predicate ereignistyp --cv ereignistyp --dry-run
    python manage.py literal_to_cv --org khm --predicate ereignistyp --cv ereignistyp
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from arkumu.metadata.models import Resource, Triple, ResourceType


# CV label predicates to match against (German name takes priority)
CV_LABEL_PREDICATES = {
    "ereignistyp": [
        "http://arkumu.org/data/properties/deutscher-name-des-ereignistyps",
        "http://arkumu.org/data/properties/englischer-name-des-ereignistyps",
    ],
    "projektkategorie": [
        "http://arkumu.org/data/properties/deutscher-name",
        "http://arkumu.org/data/properties/englischer-name",
    ],
    "rolle": [
        "http://arkumu.org/data/properties/deutscher-name",
        "http://arkumu.org/data/properties/englischer-name",
    ],
    "projektart": [
        "http://arkumu.org/data/properties/deutscher-name-der-projektart",
        "http://arkumu.org/data/properties/englischer-name-der-projektart",
    ],
}

# CV class URIs
CV_CLASS_URIS = {
    "ereignistyp": "http://arkumu.org/data/types/ereignistyp",
    "projektkategorie": "http://arkumu.org/data/types/projektkategorie",
    "rolle": "http://arkumu.org/data/types/rolle",
    "projektart": "http://arkumu.org/data/types/projektart",
}


class Command(BaseCommand):
    help = "Convert literal values to controlled vocabulary references by matching labels"

    def add_arguments(self, parser):
        parser.add_argument(
            "--org",
            type=str,
            required=True,
            help="Organization code (e.g., khm, fuk, hmt)",
        )
        parser.add_argument(
            "--predicate",
            type=str,
            required=True,
            help="Predicate name to match (e.g., ereignistyp)",
        )
        parser.add_argument(
            "--cv",
            type=str,
            required=True,
            help="Controlled vocabulary type (e.g., ereignistyp)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without making changes",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Show detailed information",
        )

    def handle(self, *args, **options):
        org_code = options["org"]
        predicate_name = options["predicate"]
        cv_type = options["cv"]
        dry_run = options["dry_run"]
        verbose = options["verbose"]

        if cv_type not in CV_LABEL_PREDICATES:
            self.stderr.write(
                self.style.ERROR(
                    f"Unknown CV type: {cv_type}. Known types: {list(CV_LABEL_PREDICATES.keys())}"
                )
            )
            return

        # Build CV label lookup: label (lowercase) -> CV entity
        cv_lookup = self._build_cv_lookup(cv_type, verbose)
        if not cv_lookup:
            self.stderr.write(self.style.ERROR(f"No CV entities found for {cv_type}"))
            return

        self.stdout.write(f"Built CV lookup with {len(cv_lookup)} labels")

        # Find literal triples for the predicate
        predicate_pattern = f"/{predicate_name}"
        literal_triples = Triple.objects.filter(
            predicate__uri__contains=predicate_pattern,
            subject__organization__code=org_code,
            object__resource_type=ResourceType.LITERAL,
        ).select_related("subject", "object", "predicate")

        total = literal_triples.count()
        self.stdout.write(f"Found {total} literal triples for {predicate_name}")

        if total == 0:
            return

        # Match and update
        stats = {"matched": 0, "unmatched": 0, "updated": 0}
        unmatched_values = set()

        with transaction.atomic():
            for triple in literal_triples:
                literal_value = (triple.object.value or "").strip()
                lookup_key = literal_value.lower()

                cv_entity = cv_lookup.get(lookup_key)

                if cv_entity:
                    stats["matched"] += 1
                    if not dry_run:
                        triple.object = cv_entity
                        triple.save(update_fields=["object"])
                        stats["updated"] += 1
                else:
                    stats["unmatched"] += 1
                    unmatched_values.add(literal_value)

            if dry_run:
                transaction.set_rollback(True)

        # Report
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN: Would update {stats['matched']} triples"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f"Updated {stats['updated']} triples")
            )

        if unmatched_values:
            self.stdout.write(
                self.style.WARNING(
                    f"Unmatched literals ({len(unmatched_values)}): {sorted(unmatched_values)[:20]}"
                )
            )

    def _build_cv_lookup(self, cv_type: str, verbose: bool) -> dict:
        """Build lookup dict: label (lowercase) -> CV entity Resource."""
        class_uri = CV_CLASS_URIS[cv_type]
        label_predicates = CV_LABEL_PREDICATES[cv_type]

        # Find all CV entities (instances of the CV class)
        cv_prefix = class_uri + "/"
        cv_entities = Resource.objects.filter(
            uri__startswith=cv_prefix,
            resource_type=ResourceType.ENTITY,
        )

        lookup = {}
        for entity in cv_entities:
            # Get labels from label predicates
            labels = Triple.objects.filter(
                subject=entity,
                predicate__uri__in=label_predicates,
            ).values_list("object__value", flat=True)

            for label in labels:
                if label:
                    key = label.strip().lower()
                    if key not in lookup:
                        lookup[key] = entity
                    if verbose:
                        self.stdout.write(f"  CV: {label} -> {entity.uri}")

        return lookup
