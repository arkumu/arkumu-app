from __future__ import annotations

from typing import Iterable, Optional

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from arkumu.metadata.models import Resource
from arkumu.metadata.models.mappings import Mapping


DEFAULT_BASE_URI = getattr(settings, "ARKUMU_BASE_URI", "http://arkumu.org/data").rstrip("/")

CANONICAL_URIS = {
    "project": "http://arkumu.org/data/properties/projekt",
    "event": "http://arkumu.org/data/properties/ereignis",
    "digital_object": "http://arkumu.org/data/properties/digitales-objekt",
    "actor": "http://arkumu.org/data/properties/akteurin",
    "actor_in_event": "http://arkumu.org/data/properties/akteurin-im-ereignis",
    "role_in_event": "http://arkumu.org/data/properties/rollen-der-akteurin-im-ereignis",
    "in_event": "http://arkumu.org/data/properties/im-ereignis",
}

CROSS_TABLE_RULES = {
    "khm": {
        "02_kreuz_projekte_personen": {
            "properties": {
                "AS_Pers_ID": CANONICAL_URIS["actor_in_event"],
                "AS_Proj_ID": CANONICAL_URIS["event"],
                "AS_Taetigkeit_arkumu_Rolle": CANONICAL_URIS["role_in_event"],
            },
        },
        "04_kreuz_betreuende_projekte": {
            "properties": {
                "PE_ID_fk": CANONICAL_URIS["actor_in_event"],
                "Proj_ID_fk": CANONICAL_URIS["event"],
            },
        },
        "16_kreuz_events_projekte": {
            "properties": {
                "Kr_Proj_ID": CANONICAL_URIS["project"],
                "Kr_Event_ID": CANONICAL_URIS["event"],
            },
        },
    },
    "hmt": {
        "03_hfm_kreuz_ereignis_akteure": {
            "properties": {
                ("HFMT_Akteur_ID_fk", "HFMT_Koerperschaft_ID_fk"): CANONICAL_URIS["actor_in_event"],
                ("Ereignis_Nr_fk", "EreignisNr"): CANONICAL_URIS["event"],
                "Rolle": CANONICAL_URIS["role_in_event"],
            },
        },
        "05_hfm_kreuz_ereignis_koerperschaften": {
            "properties": {
                ("HFMT_Koerperschaft_ID_fk", "HFMT_Akteur_ID_fk"): CANONICAL_URIS["actor_in_event"],
                ("Ereignis_Nr_fk", "EreignisNr"): CANONICAL_URIS["event"],
            },
        },
        "01_hfm_kreuz_projekt_ereignis": {
            "properties": {
                ("HFMT_Projekt_ID_fk", "HFMT_Werk_ID", "Werk_ID_fk"): CANONICAL_URIS["project"],
                ("Ereignis_Nr_fk", "EreignisNr"): CANONICAL_URIS["event"],
            },
        },
        "07_hfm_kreuz_ereignis_digitalesobjekt": {
            "properties": {
                ("Ereignis_Nr_fk", "EreignisNr"): CANONICAL_URIS["event"],
                ("DigitalesObjekt_ID_fk", "DigitalesObjekt_ID"): CANONICAL_URIS["digital_object"],
            },
        },
    },
}


class Command(BaseCommand):
    help = (
        "Rewrite schema_manifest entries so they reference canonical Arkumu URIs. "
        "This command looks up each property/entity URI in metadata_resource, falls back "
        "to the canonical URI stored there, and persists the normalized manifest."
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._active_org: Optional[str] = None

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
            self._active_org = (mapping.organization_id or "").lower()

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

            changed |= self._apply_dataset_rules(self._active_org, dataset_name, dataset)

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

        candidate_uris: list[str] = []
        if uri_value:
            candidate_uris.append(uri_value)
        if canonical_value and canonical_value != uri_value:
            candidate_uris.append(canonical_value)

        resource = None
        for candidate in candidate_uris:
            normalized_uri = self._normalize_uri(candidate)
            if not normalized_uri:
                continue
            resource = (
                Resource.objects.filter(uri=normalized_uri)
                .only("uri", "canonical_uri")
                .first()
            )
            if resource:
                break

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

    def _apply_dataset_rules(self, organization_code: Optional[str], dataset_name: str, dataset: dict) -> bool:
        if not organization_code or not dataset_name:
            return False

        rules_for_org = CROSS_TABLE_RULES.get(organization_code)
        if not rules_for_org:
            return False

        normalized_name = self._normalize_dataset_name(dataset_name)
        dataset_rules = rules_for_org.get(normalized_name)
        if not dataset_rules:
            return False

        properties = dataset.get("properties")
        if not isinstance(properties, dict):
            return False

        changed = False
        for column_key, target_canonical in dataset_rules.get("properties", {}).items():
            column_candidates = column_key if isinstance(column_key, (list, tuple, set)) else [column_key]
            matched = False
            for prop_key, snapshot in properties.items():
                if prop_key in column_candidates or (
                    isinstance(snapshot, dict) and snapshot.get("name") in column_candidates
                ):
                    matched = True
                    if snapshot.get("canonical_uri") != target_canonical:
                        snapshot["canonical_uri"] = target_canonical
                        changed = True
            if not matched:
                for snapshot in properties.values():
                    if isinstance(snapshot, dict) and snapshot.get("uri") in column_candidates:
                        if snapshot.get("canonical_uri") != target_canonical:
                            snapshot["canonical_uri"] = target_canonical
                            changed = True
                        matched = True
                        break
        return changed

    @staticmethod
    def _normalize_dataset_name(dataset_name: str) -> str:
        normalized = dataset_name.strip().lower()
        normalized = normalized.replace(" ", "_")
        return normalized
