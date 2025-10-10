from __future__ import annotations

from typing import Iterable, Optional

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from arkumu.metadata.models import Resource
from arkumu.metadata.models.mappings import Mapping


DEFAULT_BASE_URI = getattr(settings, "ARKUMU_BASE_URI", "http://arkumu.org/data").rstrip("/")


class Command(BaseCommand):
    help = (
        "Rewrite schema_manifest entries so they reference canonical Arkumu URIs. "
        "This command looks up each property/entity URI in metadata_resource, falls back "
        "to the canonical URI stored there, and persists the normalized manifest."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--organization",
            action="append",
            dest="organizations",
            help="Organization code to process (can be supplied multiple times).",
        )
        parser.add_argument(
            "--mapping-id",
            action="append",
            dest="mapping_ids",
            help="Specific mapping UUID to process (can be supplied multiple times).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview the mappings that would be rewritten without persisting changes.",
        )

    def handle(self, *args, **options):
        org_codes: Optional[list[str]] = options["organizations"]
        mapping_ids: Optional[list[str]] = options["mapping_ids"]
        dry_run: bool = options["dry_run"]

        if not org_codes and not mapping_ids:
            raise CommandError("Provide --organization and/or --mapping-id.")

        queryset = Mapping.objects.all()
        if org_codes:
            queryset = queryset.filter(organization_id__in=org_codes)
        if mapping_ids:
            queryset = queryset.filter(id__in=mapping_ids)

        mappings = list(queryset)
        if not mappings:
            self.stdout.write(self.style.WARNING("No mappings matched the supplied filters."))
            return

        self.stdout.write(f"Found {len(mappings)} mapping(s). Normalizing schema manifests…")

        processed = 0
        skipped = 0

        for mapping in mappings:
            manifest = mapping.mapping_config.get("schema_manifest")
            if not manifest:
                skipped += 1
                continue

            updated = self._canonicalize_manifest(manifest)
            if not updated:
                skipped += 1
                continue

            processed += 1
            if dry_run:
                continue

            config = dict(mapping.mapping_config)
            config["schema_manifest"] = manifest
            mapping.mapping_config = config
            mapping.save(update_fields=["mapping_config", "updated_at"])

        if dry_run:
            self.stdout.write(self.style.WARNING(f"Dry-run complete. {processed} mapping(s) would be updated."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Updated {processed} mapping(s); skipped {skipped}."))

    def _canonicalize_manifest(self, manifest: dict) -> bool:
        changed = False
        for dataset_name, dataset in manifest.items():
            if not isinstance(dataset, dict):
                continue

            # Entity type
            entity_info = dataset.get("entity_type")
            if entity_info:
                changed |= self._normalize_snapshot_entry(entity_info)

            # Properties
            properties = dataset.get("properties") or {}
            for snapshot in properties.values():
                changed |= self._normalize_snapshot_entry(snapshot)

            # FK relationships
            for relation in dataset.get("fk_relationships") or []:
                changed |= self._normalize_fk_entry(relation)

            # Relationship contexts
            for context in dataset.get("relationship_contexts") or []:
                changed |= self._normalize_relationship_context(context)

        return changed

    def _normalize_relationship_context(self, entry: dict) -> bool:
        changed = False
        changed |= self._maybe_replace_uri(entry, "context_property_uri", "context_canonical_property")
        changed |= self._maybe_replace_uri(entry, "primary_property_uri", "primary_canonical_property")
        changed |= self._maybe_replace_uri(entry, "secondary_property_uri", "secondary_canonical_property")
        return changed

    def _normalize_fk_entry(self, entry: dict) -> bool:
        changed = False
        changed |= self._maybe_replace_uri(entry, "source_property_uri", "source_canonical_property")
        changed |= self._maybe_replace_uri(entry, "target_property_uri", "target_canonical_property")
        return changed

    def _normalize_snapshot_entry(self, snapshot: dict) -> bool:
        return self._maybe_replace_uri(snapshot, "uri", "canonical_uri")

    def _maybe_replace_uri(self, data: dict, uri_key: str, canonical_key: str) -> bool:
        if not isinstance(data, dict):
            return False

        uri_value = data.get(uri_key)
        canonical_value = data.get(canonical_key)

        # Try canonical first (so we can update canonical even if URI is already normalized)
        resource_uri = canonical_value or uri_value
        normalized_uri = self._normalize_uri(resource_uri)
        if not normalized_uri:
            return False

        resource = Resource.objects.filter(uri=normalized_uri).only("uri", "canonical_uri").first()
        if not resource:
            return False

        new_uri = resource.uri
        new_canonical = resource.canonical_uri or resource.uri

        changed = False
        if uri_value != new_uri:
            data[uri_key] = new_uri
            changed = True
        if canonical_value != new_canonical:
            data[canonical_key] = new_canonical
            changed = True
        return changed

    def _normalize_uri(self, uri: Optional[str]) -> Optional[str]:
        if not uri:
            return None
        if uri.startswith("http://") or uri.startswith("https://"):
            return uri
        if uri.startswith("/"):
            return f"{DEFAULT_BASE_URI}{uri}"
        # Sometimes manifests stored relative pieces without leading slash
        if "://" not in uri:
            return f"{DEFAULT_BASE_URI}/{uri}"
        return uri
