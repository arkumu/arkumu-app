from __future__ import annotations

from datetime import datetime

import pytest

from arkumu.metadata.models.resource import Resource, ResourceType, PublicAccessLevel
from arkumu.metadata.services.oai_stats import build_oai_dashboard_snapshot
from arkumu.projects import (
    ProjectDigitalObject,
    ProjectInstitution,
    ProjectRecord,
    ProjectSnapshot,
)


class _FakeSnapshotService:
    def __init__(self, snapshot: ProjectSnapshot) -> None:
        self._snapshot = snapshot

    def get_cross_institutional_snapshot(self):  # pragma: no cover - simple delegate
        return self._snapshot


class _FakeCacheService:
    def __init__(self, snapshot: ProjectSnapshot | None) -> None:
        self._snapshot = snapshot

    def get_cross_institutional_snapshot(self):  # pragma: no cover - simple delegate
        return self._snapshot


def _make_project(
    *,
    uri: str,
    institution: ProjectInstitution | None,
    digital_objects: list[ProjectDigitalObject],
) -> ProjectRecord:
    return ProjectRecord(
        subject_id=uri,
        uri=uri,
        institution=institution,
        digital_objects=digital_objects,
)


@pytest.mark.django_db
def test_build_snapshot_counts_harvestable_projects(settings):
    harvestable_s3 = ProjectDigitalObject(
        path="/data/fuk/master1.tif",
        storage_key="projects/fuk/master1.tif",
        storage_status="verified",
        content_type="image/tiff",
    )
    harvestable_s3_2 = ProjectDigitalObject(
        path="/data/fuk/master2.tif",
        storage_key="projects/fuk/master2.tif",
        storage_status="completed",
        content_type="image/tiff",
    )
    pending_s3 = ProjectDigitalObject(
        path="/data/fuk/draft1.tif",
        storage_key="projects/fuk/draft1.tif",
        storage_status="processing",
        content_type="image/tiff",
    )

    rosetta_obj = ProjectDigitalObject(
        path="/rosetta/khm/rep/master1.tif",
        storage_status="completed",
        content_type="image/tiff",
    )

    ad_hoc_obj = ProjectDigitalObject(
        storage_key="misc/project.pdf",
        path="/data/misc/project.pdf",
        storage_status="completed",
        content_type="application/pdf",
    )

    snapshot = ProjectSnapshot(
        projects=[
            _make_project(
                uri="http://arkumu.org/data/project/fuk-1",
                institution=ProjectInstitution(label="FUK", code="fuk"),
                digital_objects=[harvestable_s3, harvestable_s3_2],
            ),
            _make_project(
                uri="http://arkumu.org/data/project/fuk-2",
                institution=ProjectInstitution(label="FUK", code="fuk"),
                digital_objects=[pending_s3],
            ),
            _make_project(
                uri="http://arkumu.org/data/project/khm-1",
                institution=ProjectInstitution(label="KHM", code="khm"),
                digital_objects=[rosetta_obj],
            ),
            _make_project(
                uri="http://arkumu.org/data/project/anon-1",
                institution=None,
                digital_objects=[ad_hoc_obj],
            ),
        ],
        counts={"projects": 4},
        generated_at=datetime(2024, 1, 1, 12, 0, 0),
    )

    Resource.objects.bulk_create(
        [
            Resource(
                uri="http://arkumu.org/data/project/fuk-1",
                resource_type=ResourceType.ENTITY,
                public_access_level=PublicAccessLevel.PUBLIC,
                is_public_approved=True,
            ),
            Resource(
                uri="http://arkumu.org/data/project/khm-1",
                resource_type=ResourceType.ENTITY,
                public_access_level=PublicAccessLevel.RESTRICTED,
                is_public_approved=False,
            ),
            Resource(
                uri="http://arkumu.org/data/project/anon-1",
                resource_type=ResourceType.ENTITY,
                public_access_level=PublicAccessLevel.PRIVATE,
                is_public_approved=False,
            ),
        ]
    )

    fake_service = _FakeSnapshotService(snapshot)

    dashboard_snapshot = build_oai_dashboard_snapshot(snapshot_service=fake_service)

    assert dashboard_snapshot.total_projects == 3
    assert dashboard_snapshot.total_accessible_projects == 2
    assert dashboard_snapshot.total_blocked_projects == 1
    assert dashboard_snapshot.total_missing_resources == 0
    assert dashboard_snapshot.total_harvestable_objects == 4

    codes_to_counts = {
        summary.code: summary.project_count for summary in dashboard_snapshot.institution_summaries
    }

    assert codes_to_counts == {
        "fuk": 1,  # Only one harvestable project – pending status filtered out
        "khm": 1,
        "unknown": 1,
    }

    accessible_by_code = {
        summary.code: summary.accessible_count for summary in dashboard_snapshot.institution_summaries
    }
    blocked_by_code = {
        summary.code: summary.blocked_count for summary in dashboard_snapshot.institution_summaries
    }

    assert accessible_by_code == {"fuk": 1, "khm": 1, "unknown": 0}
    assert blocked_by_code == {"fuk": 0, "khm": 0, "unknown": 1}

    labels = {summary.code: summary.label for summary in dashboard_snapshot.institution_summaries}
    assert labels["fuk"] == "FUK"
    assert labels["khm"] == "KHM"
    assert labels["unknown"] is None


@pytest.mark.django_db
def test_build_snapshot_without_cached_data():
    dashboard_snapshot = build_oai_dashboard_snapshot(cache_service=_FakeCacheService(None))

    assert dashboard_snapshot.total_projects == 0
    assert dashboard_snapshot.total_accessible_projects == 0
    assert dashboard_snapshot.total_blocked_projects == 0
    assert dashboard_snapshot.total_missing_resources == 0
    assert dashboard_snapshot.total_harvestable_objects == 0
    assert dashboard_snapshot.institution_summaries == []
