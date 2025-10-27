from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from arkumu.projects.services.s3_key_index import get_s3_key_map
from arkumu.storage.models import S3FileObject
from arkumu.storage.services.upload.upload_utils import normalize_s3_key
from arkumu.oaipmh.oai_project import HARVESTABLE_STORAGE_STATUSES


class Command(BaseCommand):
    help = (
        "Export dump-key to fixity mapping for digital-only OAI orgs. "
        "Reads data/{org}_s3_keys.txt, matches against harvestable S3FileObjects, "
        "and writes TSV with dump key, S3 key, and checksum/ETag."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--org",
            dest="org_codes",
            action="append",
            help="Limit export to specific organization codes (e.g. fuk).",
        )
        parser.add_argument(
            "--output",
            dest="output_dir",
            default=str(Path("data")),
            help="Directory to write TSV files (default: data/).",
        )

    def handle(self, *args, **options):
        org_codes = options.get("org_codes")
        output_dir = Path(options.get("output_dir") or "data")

        configured_orgs = getattr(
            settings,
            "OAI_DIGITAL_OBJECT_LINK_ORGS",
            ("fuk", "det", "rsh"),
        )
        digital_orgs = {
            code.lower().strip()
            for code in configured_orgs
            if code
        }
        if not digital_orgs:
            raise CommandError("No digital-object organizations configured")

        if org_codes:
            requested = {
                code.lower().strip()
                for code in org_codes
                if code and code.strip()
            }
            unknown = requested - digital_orgs
            if unknown:
                raise CommandError(f"Unsupported org codes: {', '.join(sorted(unknown))}")
            target_orgs = sorted(requested)
        else:
            target_orgs = sorted(digital_orgs)

        if not target_orgs:
            self.stdout.write(self.style.WARNING("No organizations selected; nothing to do."))
            return

        data_dir = Path("data")
        if not data_dir.exists():
            raise CommandError("data/ directory not found; dump files are expected there")

        output_dir.mkdir(parents=True, exist_ok=True)

        for org_code in target_orgs:
            dump_path = data_dir / f"{org_code}_s3_keys.txt"
            if not dump_path.exists():
                self.stdout.write(
                    self.style.WARNING(f"Skipping {org_code}: dump file missing at {dump_path}")
                )
                continue

            lookup = get_s3_key_map(org_code)
            rows = self._collect_rows(org_code, dump_path, lookup)

            if not rows:
                self.stdout.write(
                    self.style.WARNING(f"No matches found for {org_code}; TSV not created")
                )
                continue

            output_file = output_dir / f"{org_code}_s3_fixity.tsv"
            with output_file.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle, delimiter="\t")
                writer.writerow(
                    [
                        "dump_key",
                        "matched_s3_key",
                        "checksum_or_etag",
                        "source_status",
                        "related_resource_id",
                        "related_resource_uri",
                    ]
                )
                writer.writerows(rows)

            self.stdout.write(
                self.style.SUCCESS(
                    f"Exported {len(rows)} rows for {org_code} to {output_file}"
                )
            )

    def _collect_rows(
        self,
        org_code: str,
        dump_path: Path,
        lookup,
    ) -> List[Tuple[str, str, str, str, str, str]]:
        s3_index = self._build_s3_index(org_code)
        rows: List[Tuple[str, str, str, str, str, str]] = []

        with dump_path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                dump_key = raw_line.strip()
                if not dump_key:
                    continue
                match = self._match_dump_entry(dump_key, lookup, s3_index)
                if match is None:
                    continue
                rows.append(match)
        return rows

    def _build_s3_index(self, org_code: str) -> Dict[str, Tuple[str, str, str, str]]:
        qs = (
            S3FileObject.objects
            .filter(organization__iexact=org_code, status__in=HARVESTABLE_STORAGE_STATUSES)
            .values_list("s3_key", "sha256_checksum", "etag", "status", "related_resource__id", "related_resource__uri")
        )

        index: Dict[str, Tuple[str, str, str, str, Optional[str], Optional[str]]] = {}
        for s3_key, checksum, etag, status, related_id, related_uri in qs:
            if not s3_key:
                continue
            normalized = normalize_s3_key(s3_key)
            if normalized.startswith("data/"):
                normalized = normalized[5:]
            index.setdefault(
                normalized,
                (
                    s3_key,
                    checksum or "",
                    etag or "",
                    status,
                    str(related_id) if related_id else "",
                    related_uri or "",
                ),
            )
        return index

    def _match_dump_entry(
        self,
        dump_key: str,
        lookup,
        s3_index: Dict[str, Tuple[str, str, str, str, Optional[str], Optional[str]]],
    ) -> Optional[Tuple[str, str, str, str, str, str]]:
        normalized_candidates = self._normalize_candidates(dump_key)

        # First try the dump lookup which preserves original key mapping
        resolved = lookup.find(normalized_candidates)
        if resolved:
            candidate = normalize_s3_key(resolved)
            if candidate.startswith("data/"):
                candidate = candidate[5:]
            metadata = s3_index.get(candidate)
            if metadata:
                s3_key, checksum, etag, status, related_id, related_uri = metadata
                checksum_or_etag = checksum or etag or ""
                return dump_key, s3_key, checksum_or_etag, status, related_id or "", related_uri or ""

        # Fall back to direct normalized lookup inside the S3 index
        for normalized in normalized_candidates:
            if normalized.startswith("data/"):
                normalized = normalized[5:]
            metadata = s3_index.get(normalized)
            if metadata:
                s3_key, checksum, etag, status, related_id, related_uri = metadata
                checksum_or_etag = checksum or etag or ""
                return dump_key, s3_key, checksum_or_etag, status, related_id or "", related_uri or ""

        return None

    @staticmethod
    def _normalize_candidates(value: str) -> List[str]:
        variants = {value.strip()}
        if not variants:
            return []
        original = next(iter(variants))
        if "\\" in original:
            variants.add(original.replace("\\", "/"))
        normalized: List[str] = []
        seen: set[str] = set()
        for variant in variants:
            norm = normalize_s3_key(variant)
            if not norm:
                continue
            if norm not in seen:
                normalized.append(norm)
                seen.add(norm)
        return normalized
