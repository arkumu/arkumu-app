"""Tests for :mod:`arkumu.oaipmh.services.media_sync_planner`."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from arkumu.metadata.models.resource import PublicAccessLevel, Resource, ResourceType
from arkumu.oaipmh.models import OAIProjectMediaLink, OAIProjectPublication
from arkumu.oaipmh.services.media_sync_planner import (
    collect_publication_candidate_ids,
    collect_seed_candidate_ids,
)
from arkumu.users.models import Organization


def _project(org: Organization, uri: str) -> Resource:
    return Resource.objects.create(
        uri=uri,
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )


def _digital(org: Organization, uri: str) -> Resource:
    return Resource.objects.create(
        uri=uri,
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )


@pytest.mark.django_db
def test_collect_seed_candidate_ids_full_refresh_without_watermark():
    org = Organization.objects.create(name="Org", code="org", domain="org", is_active=True)
    full_refresh, candidate_ids = collect_seed_candidate_ids(org, since=None)

    assert full_refresh is True
    assert candidate_ids == set()


@pytest.mark.django_db
def test_collect_seed_candidate_ids_includes_curated_and_new_projects():
    org = Organization.objects.create(name="Org", code="org", domain="org", is_active=True)
    project_existing = _project(org, "https://arkumu.org/entities/projekt/seed-1")
    project_new = _project(org, "https://arkumu.org/entities/projekt/seed-2")
    project_old = _project(org, "https://arkumu.org/entities/projekt/seed-old")
    cutoff = timezone.now() - timedelta(days=1)

    link_existing = OAIProjectMediaLink.objects.create(
        project=project_existing,
        digital_object=_digital(org, "https://arkumu.org/entities/digital/seed-1"),
    )
    old_link = OAIProjectMediaLink.objects.create(
        project=project_old,
        digital_object=_digital(org, "https://arkumu.org/entities/digital/seed-old"),
    )
    # Ensure timestamps reflect relative freshness.
    Resource.objects.filter(id=project_existing.id).update(updated_at=timezone.now())
    OAIProjectMediaLink.objects.filter(id=link_existing.id).update(updated_at=timezone.now())
    Resource.objects.filter(id=project_new.id).update(updated_at=timezone.now())
    Resource.objects.filter(id=project_old.id).update(updated_at=cutoff - timedelta(days=1))
    OAIProjectMediaLink.objects.filter(id=old_link.id).update(updated_at=cutoff - timedelta(days=1))

    full_refresh, candidate_ids = collect_seed_candidate_ids(org, since=cutoff)

    assert full_refresh is False
    assert set(candidate_ids) == {project_existing.id, project_new.id}


@pytest.mark.django_db
def test_collect_seed_candidate_ids_includes_unseeded_legacy_projects():
    org = Organization.objects.create(name="Org", code="org", domain="org", is_active=True)
    legacy_project = _project(org, "https://arkumu.org/entities/projekt/unseeded")
    cutoff = timezone.now() - timedelta(days=3)

    Resource.objects.filter(id=legacy_project.id).update(updated_at=cutoff - timedelta(days=2))

    full_refresh, candidate_ids = collect_seed_candidate_ids(org, since=cutoff)

    assert full_refresh is False
    assert candidate_ids == {legacy_project.id}


@pytest.mark.django_db
def test_collect_seed_candidate_ids_include_projects_with_links_and_recent_project_updates():
    org = Organization.objects.create(name="Org", code="org", domain="org", is_active=True)
    project = _project(org, "https://arkumu.org/entities/projekt/linked")
    digital = _digital(org, "https://arkumu.org/entities/digital/linked")
    link = OAIProjectMediaLink.objects.create(project=project, digital_object=digital)
    cutoff = timezone.now() - timedelta(days=5)

    # Simulate project updates happening after the watermark while curated links stay untouched.
    Resource.objects.filter(id=project.id).update(updated_at=timezone.now())
    OAIProjectMediaLink.objects.filter(id=link.id).update(updated_at=cutoff - timedelta(days=1))

    full_refresh, candidate_ids = collect_seed_candidate_ids(org, since=cutoff)

    assert full_refresh is False
    assert candidate_ids == {project.id}


@pytest.mark.django_db
def test_collect_publication_candidate_ids_detects_recent_changes():
    org = Organization.objects.create(name="Org", code="org", domain="org", is_active=True)
    recent_project = _project(org, "https://arkumu.org/entities/projekt/pub-1")
    stale_project = _project(org, "https://arkumu.org/entities/projekt/pub-2")
    OAIProjectPublication.objects.create(project=recent_project, is_approved=True)
    old_pub = OAIProjectPublication.objects.create(project=stale_project, is_approved=False)

    cutoff = timezone.now() - timedelta(days=2)
    Resource.objects.filter(id=recent_project.id).update(updated_at=timezone.now())
    Resource.objects.filter(id=stale_project.id).update(updated_at=cutoff - timedelta(days=1))
    OAIProjectPublication.objects.filter(id=old_pub.id).update(updated_at=cutoff - timedelta(days=1))

    full_refresh, candidate_ids = collect_publication_candidate_ids(org, since=cutoff)

    assert full_refresh is False
    assert candidate_ids == {recent_project.id}
