import csv
from pathlib import Path

import pytest
from django.core.management import call_command

from arkumu.metadata.models.mappings import Mapping
from arkumu.users.models import Organization


@pytest.fixture
def organization_khm(db):
    return Organization.objects.create(name="KHM", code="khm")


def _write_csv(tmp_path: Path, rows):
    csv_path = tmp_path / "labels.csv"
    fieldnames = ["Type", "Target", "Label", "Name"]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return csv_path


@pytest.mark.django_db
def test_map_canonical_column_uris_updates_matching_columns(tmp_path, organization_khm):
    csv_path = _write_csv(
        tmp_path,
        [
            {
                "Type": "Property",
                "Target": "http://example.org/data/properties/p1",
                "Label": "P1 Label",
                "Name": "ColA",
            },
            {
                "Type": "Property",
                "Target": "http://example.org/data/properties/p2",
                "Label": "P2 Label",
                "Name": "ColB",
            },
        ],
    )

    mapping = Mapping.objects.create(
        name="Test Mapping",
        organization_id=organization_khm.code,
        source_datasets=[],
        mapping_config={
            "workspace_columns": {
                "khm::Dataset::ColA": {
                    "id": "khm::Dataset::ColA",
                    "name": "ColA",
                },
                "khm::Dataset::Other": {
                    "id": "khm::Dataset::Other",
                    "name": "Other",
                },
            },
            "fk_relationships": {},
            "relationship_contexts": {},
            "external_ontologies": {},
            "metadata": {},
        },
    )

    call_command(
        "map_canonical_column_uris",
        str(csv_path),
        "--organization",
        organization_khm.code,
    )

    mapping.refresh_from_db()
    canonical = mapping.mapping_config.get("canonical_column_mappings") or {}

    assert canonical["khm::Dataset::ColA"]["canonical_property_uri"] == "http://example.org/data/properties/p1"
    assert canonical["khm::Dataset::ColA"]["canonical_property_label"] == "P1 Label"
    assert canonical["khm::Dataset::ColA"]["source"] == csv_path.stem

    # Non-matching column should not get an entry
    assert "khm::Dataset::Other" not in canonical


@pytest.mark.django_db
def test_map_canonical_column_uris_skips_ambiguous_names(tmp_path, organization_khm):
    csv_path = _write_csv(
        tmp_path,
        [
            {
                "Type": "Property",
                "Target": "http://example.org/data/properties/p1",
                "Label": "P1 Label",
                "Name": "Ambiguous",
            },
            {
                "Type": "Property",
                "Target": "http://example.org/data/properties/p2",
                "Label": "P2 Label",
                "Name": "Ambiguous",
            },
        ],
    )

    mapping = Mapping.objects.create(
        name="Ambiguous Mapping",
        organization_id=organization_khm.code,
        source_datasets=[],
        mapping_config={
            "workspace_columns": {
                "khm::Dataset::Ambiguous": {
                    "id": "khm::Dataset::Ambiguous",
                    "name": "Ambiguous",
                },
            },
            "fk_relationships": {},
            "relationship_contexts": {},
            "external_ontologies": {},
            "metadata": {},
        },
    )

    call_command(
        "map_canonical_column_uris",
        str(csv_path),
        "--organization",
        organization_khm.code,
    )

    mapping.refresh_from_db()
    canonical = mapping.mapping_config.get("canonical_column_mappings") or {}

    # Ambiguous name should not be mapped
    assert "khm::Dataset::Ambiguous" not in canonical


@pytest.mark.django_db
def test_map_canonical_column_uris_scoped_to_organization(tmp_path, db):
    org_khm = Organization.objects.create(name="KHM", code="khm")
    org_hmt = Organization.objects.create(name="HMT", code="hmt")

    csv_path = _write_csv(
        tmp_path,
        [
            {
                "Type": "Property",
                "Target": "http://example.org/data/properties/p1",
                "Label": "P1 Label",
                "Name": "ColA",
            },
        ],
    )

    mapping_khm = Mapping.objects.create(
        name="KHM Mapping",
        organization_id=org_khm.code,
        source_datasets=[],
        mapping_config={
            "workspace_columns": {
                "khm::Dataset::ColA": {
                    "id": "khm::Dataset::ColA",
                    "name": "ColA",
                },
            },
            "fk_relationships": {},
            "relationship_contexts": {},
            "external_ontologies": {},
            "metadata": {},
        },
    )

    mapping_hmt = Mapping.objects.create(
        name="HMT Mapping",
        organization_id=org_hmt.code,
        source_datasets=[],
        mapping_config={
            "workspace_columns": {
                "hmt::Dataset::ColA": {
                    "id": "hmt::Dataset::ColA",
                    "name": "ColA",
                },
            },
            "fk_relationships": {},
            "relationship_contexts": {},
            "external_ontologies": {},
            "metadata": {},
        },
    )

    call_command(
        "map_canonical_column_uris",
        str(csv_path),
        "--organization",
        org_khm.code,
    )

    mapping_khm.refresh_from_db()
    mapping_hmt.refresh_from_db()

    canonical_khm = mapping_khm.mapping_config.get("canonical_column_mappings") or {}
    canonical_hmt = mapping_hmt.mapping_config.get("canonical_column_mappings") or {}

    assert "khm::Dataset::ColA" in canonical_khm
    assert "hmt::Dataset::ColA" not in canonical_hmt

