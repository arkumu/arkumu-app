"""Tests for institution-specific OAI publication auto-approval rules."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from arkumu.metadata.models.resource import PublicAccessLevel, Resource, ResourceType
from arkumu.oaipmh import media_link_views
from arkumu.oaipmh.media_link_views import _sync_oai_publication_for_org
from arkumu.oaipmh.models import OAIProjectPublication
from arkumu.users.models import Organization


def _make_project(org: Organization, slug: str) -> Resource:
    return Resource.objects.create(
        uri=f"https://arkumu.org/entities/projekt/{slug}",
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )


def _patch_assembler(monkeypatch):
    class DummyAssembler:
        def build_record(self, context):  # pragma: no cover - simple stub
            return object()

    monkeypatch.setattr(media_link_views, "OAIProjectAssembler", lambda: DummyAssembler())


def _patch_builder(monkeypatch, digital_objects):
    class DummyBuilder:
        def from_project_record(self, record, **kwargs):  # pragma: no cover - simple stub
            return SimpleNamespace(digital_objects=list(digital_objects))

    monkeypatch.setattr(media_link_views, "OAIProjectBuilder", lambda: DummyBuilder())


@pytest.mark.django_db
def test_publication_sync_auto_approves_non_s3_when_digital_objects_present(settings, monkeypatch):
    settings.OAI_S3_HARVESTABLE_ORGS = ("fuk", "det", "rsh")
    organization = Organization.objects.create(name="HMT", code="hmt", domain="example.org", is_active=True)
    project = _make_project(organization, "non-s3")

    _patch_assembler(monkeypatch)
    _patch_builder(monkeypatch, [SimpleNamespace(harvestable=False)])

    summary = _sync_oai_publication_for_org(organization)

    assert summary["projects"] == 1
    assert summary["auto_approved"] == 1

    publication = OAIProjectPublication.objects.get(project=project)
    assert publication.is_approved is True
    assert publication.approved_at is not None


@pytest.mark.django_db
def test_publication_sync_skips_s3_projects_without_harvestable_digital_objects(settings, monkeypatch):
    settings.OAI_S3_HARVESTABLE_ORGS = ("fuk",)
    organization = Organization.objects.create(name="FUK", code="fuk", domain="example.org", is_active=True)
    _make_project(organization, "s3-no-harvestable")

    _patch_assembler(monkeypatch)
    _patch_builder(monkeypatch, [SimpleNamespace(harvestable=False)])

    summary = _sync_oai_publication_for_org(organization)

    assert summary["projects"] == 1
    assert summary["auto_approved"] == 0
    assert OAIProjectPublication.objects.count() == 0
