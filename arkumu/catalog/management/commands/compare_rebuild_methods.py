"""Compare current rebuild method vs raw SQL approach.

Runs both methods and compares the resulting ProjectIndex data.
"""

import json
import time
from collections import defaultdict
from typing import Any, Dict, List, Set, Tuple

from django.core.management.base import BaseCommand
from django.db import connection

from arkumu.catalog.models import ProjectIndex
from arkumu.catalog.services.project_index_db_service import ProjectIndexDbService


class Command(BaseCommand):
    help = "Compare current rebuild method vs raw SQL approach"

    def add_arguments(self, parser):
        parser.add_argument(
            "--org",
            type=str,
            default="khm",
            help="Organization code to test (default: khm)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=10,
            help="Number of projects to compare (default: 10)",
        )
        parser.add_argument(
            "--run-raw-sql",
            action="store_true",
            help="Run raw SQL queries and compare timing",
        )

    def handle(self, *args, **options):
        org_code = options["org"]
        limit = options["limit"]
        run_raw = options["run_raw_sql"]

        self.stdout.write(f"Comparing rebuild methods for {org_code} (limit={limit})")
        self.stdout.write("=" * 60)

        # Step 1: Get current ProjectIndex data for comparison baseline
        self.stdout.write("\n1. Fetching current ProjectIndex data...")
        t0 = time.perf_counter()

        current_data = self._get_current_index_data(org_code, limit)

        t1 = time.perf_counter()
        self.stdout.write(f"   Fetched {len(current_data)} records in {t1-t0:.3f}s")

        # Step 2: Run raw SQL queries that would produce equivalent data
        if run_raw:
            self.stdout.write("\n2. Running raw SQL queries...")
            t2 = time.perf_counter()

            raw_data = self._run_raw_sql_queries(org_code, limit)

            t3 = time.perf_counter()
            self.stdout.write(f"   Raw SQL completed in {t3-t2:.3f}s")

            # Step 3: Compare results
            self.stdout.write("\n3. Comparing results...")
            self._compare_results(current_data, raw_data)
        else:
            # Just show what the raw SQL would look like
            self.stdout.write("\n2. Raw SQL query preview (use --run-raw-sql to execute):")
            self._show_raw_sql_queries(org_code, limit)

    def _get_current_index_data(self, org_code: str, limit: int) -> Dict[str, Dict]:
        """Get current ProjectIndex data as dict keyed by URI."""
        data = {}
        for row in ProjectIndex.objects.filter(org_code=org_code)[:limit]:
            data[row.uri] = {
                "uri": row.uri,
                "title": row.title,
                "subtitle": row.subtitle,
                "description": row.description,
                "category_labels": list(row.category_labels or []),
                "actor_names": list(row.actor_names or []),
                "year_values": list(row.year_values or []),
                "year_range": row.year_range,
                "institution_label": row.institution_label,
                "project_type_label": row.project_type_label,
                "digital_object_paths": list(row.digital_object_paths or []),
            }
        return data

    def _run_raw_sql_queries(self, org_code: str, limit: int) -> Dict[str, Dict]:
        """Run raw SQL queries to build equivalent data."""
        data = {}

        with connection.cursor() as cursor:
            # Query 1: Get project resources with basic info
            cursor.execute("""
                SELECT
                    r.id,
                    r.uri,
                    o.code as org_code,
                    o.label as org_label
                FROM metadata_resource r
                JOIN users_organization o ON r.organization_id = o.id
                WHERE o.code = %s
                AND r.resource_type = 'ENTITY'
                AND EXISTS (
                    SELECT 1 FROM metadata_triple t
                    JOIN metadata_resource pred ON t.predicate_id = pred.id
                    JOIN metadata_resource obj ON t.object_id = obj.id
                    WHERE t.subject_id = r.id
                    AND pred.uri = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
                    AND obj.canonical_uri = 'http://arkumu.org/data/types/projekt'
                )
                LIMIT %s
            """, [org_code, limit])

            projects = cursor.fetchall()
            self.stdout.write(f"   Found {len(projects)} project resources")

            # Query 2: Get titles for all projects in one query
            project_ids = [str(p[0]) for p in projects]
            if not project_ids:
                return data

            placeholders = ",".join(["%s"] * len(project_ids))
            cursor.execute(f"""
                SELECT
                    t.subject_id,
                    r_obj.value as title
                FROM metadata_triple t
                JOIN metadata_resource pred ON t.predicate_id = pred.id
                JOIN metadata_resource r_obj ON t.object_id = r_obj.id
                WHERE t.subject_id::text IN ({placeholders})
                AND pred.canonical_uri = 'http://arkumu.org/data/properties/titel'
            """, project_ids)

            titles_by_id = {}
            for row in cursor.fetchall():
                titles_by_id[str(row[0])] = row[1]

            # Query 3: Get categories for all projects
            cursor.execute(f"""
                SELECT
                    t.subject_id,
                    r_cat.label as category_label
                FROM metadata_triple t
                JOIN metadata_resource pred ON t.predicate_id = pred.id
                JOIN metadata_resource r_cat ON t.object_id = r_cat.id
                WHERE t.subject_id::text IN ({placeholders})
                AND pred.canonical_uri = 'http://arkumu.org/data/properties/projektkategorie'
            """, project_ids)

            categories_by_id = defaultdict(list)
            for row in cursor.fetchall():
                categories_by_id[str(row[0])].append(row[1])

            # Query 4: Get year values
            cursor.execute(f"""
                SELECT
                    t.subject_id,
                    r_obj.value as year_value
                FROM metadata_triple t
                JOIN metadata_resource pred ON t.predicate_id = pred.id
                JOIN metadata_resource r_obj ON t.object_id = r_obj.id
                WHERE t.subject_id::text IN ({placeholders})
                AND pred.canonical_uri IN (
                    'http://arkumu.org/data/properties/entstehungsjahr-von',
                    'http://arkumu.org/data/properties/entstehungsjahr-bis'
                )
            """, project_ids)

            years_by_id = defaultdict(list)
            for row in cursor.fetchall():
                try:
                    years_by_id[str(row[0])].append(int(row[1]))
                except (ValueError, TypeError):
                    pass

            # Build result dict
            for project in projects:
                pid = str(project[0])
                uri = project[1]
                data[uri] = {
                    "uri": uri,
                    "title": titles_by_id.get(pid, ""),
                    "category_labels": categories_by_id.get(pid, []),
                    "year_values": sorted(set(years_by_id.get(pid, []))),
                    "institution_label": project[3] or "",
                }

        return data

    def _show_raw_sql_queries(self, org_code: str, limit: int):
        """Show the raw SQL queries that would be used."""

        queries = [
            ("Get project resources", """
SELECT
    r.id,
    r.uri,
    o.code as org_code,
    o.label as org_label
FROM metadata_resource r
JOIN users_organization o ON r.organization_id = o.id
WHERE o.code = '{org}'
AND r.resource_type = 'ENTITY'
AND EXISTS (
    SELECT 1 FROM metadata_triple t
    JOIN metadata_resource pred ON t.predicate_id = pred.id
    JOIN metadata_resource obj ON t.object_id = obj.id
    WHERE t.subject_id = r.id
    AND pred.uri = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
    AND obj.canonical_uri = 'http://arkumu.org/data/types/projekt'
)
LIMIT {limit}
"""),
            ("Get titles (batched)", """
SELECT
    t.subject_id,
    r_obj.value as title
FROM metadata_triple t
JOIN metadata_resource pred ON t.predicate_id = pred.id
JOIN metadata_resource r_obj ON t.object_id = r_obj.id
WHERE t.subject_id IN (... project_ids ...)
AND pred.canonical_uri = 'http://arkumu.org/data/properties/titel'
"""),
            ("Get categories (batched)", """
SELECT
    t.subject_id,
    r_cat.label as category_label
FROM metadata_triple t
JOIN metadata_resource pred ON t.predicate_id = pred.id
JOIN metadata_resource r_cat ON t.object_id = r_cat.id
WHERE t.subject_id IN (... project_ids ...)
AND pred.canonical_uri = 'http://arkumu.org/data/properties/projektkategorie'
"""),
            ("Aggregated INSERT (using COPY)", """
COPY project_index (
    project_resource_id, uri, org_code, title, subtitle, ...
) FROM STDIN WITH (FORMAT csv, DELIMITER E'\\t')
"""),
        ]

        for name, sql in queries:
            self.stdout.write(f"\n   -- {name}")
            formatted = sql.format(org=org_code, limit=limit)
            for line in formatted.strip().split("\n"):
                self.stdout.write(f"   {line}")

    def _compare_results(self, current: Dict, raw: Dict):
        """Compare current ORM results with raw SQL results."""
        current_uris = set(current.keys())
        raw_uris = set(raw.keys())

        missing_in_raw = current_uris - raw_uris
        extra_in_raw = raw_uris - current_uris
        common = current_uris & raw_uris

        self.stdout.write(f"   Common URIs: {len(common)}")
        if missing_in_raw:
            self.stdout.write(f"   Missing in raw SQL: {len(missing_in_raw)}")
        if extra_in_raw:
            self.stdout.write(f"   Extra in raw SQL: {len(extra_in_raw)}")

        # Compare field values for common URIs
        field_diffs = defaultdict(int)
        for uri in common:
            c = current[uri]
            r = raw[uri]

            for field in ["title", "institution_label"]:
                if c.get(field) != r.get(field):
                    field_diffs[field] += 1

            # Compare lists (sorted)
            for field in ["category_labels", "year_values"]:
                c_val = sorted(c.get(field, []))
                r_val = sorted(r.get(field, []))
                if c_val != r_val:
                    field_diffs[field] += 1

        if field_diffs:
            self.stdout.write("   Field differences:")
            for field, count in sorted(field_diffs.items()):
                self.stdout.write(f"     {field}: {count} mismatches")
        else:
            self.stdout.write(self.style.SUCCESS("   All compared fields match!"))
