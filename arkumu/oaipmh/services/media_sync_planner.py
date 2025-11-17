"""Helpers for durable media-sync planning."""

from __future__ import annotations

from datetime import datetime
from typing import Set, Tuple

from django.db.models import Q

from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.oaipmh.models import OAIMediaSyncState, OAIProjectMediaLink
from arkumu.users.models import Organization


def get_sync_state(
    organization: Organization,
    *,
    profile: str = OAIMediaSyncState.PROFILE_TAILORED,
) -> OAIMediaSyncState:
    """Return or create the sync state row for the given organization/profile."""

    state, _ = OAIMediaSyncState.objects.get_or_create(
        organization=organization,
        profile=profile,
    )
    return state


def collect_seed_candidate_ids(
    organization: Organization,
    *,
    since: datetime | None,
) -> Tuple[bool, Set[int]]:
    """Return project IDs that require seeding."""

    if since is None:
        return True, set()

    curated_ids = set(
        OAIProjectMediaLink.objects.filter(
            project__organization=organization,
            updated_at__gt=since,
        ).values_list("project_id", flat=True)
    )

    project_ids_with_links = list(
        OAIProjectMediaLink.objects.filter(project__organization=organization)
        .values_list("project_id", flat=True)
        .distinct()
    )
    project_ids_from_resource = set(
        Resource.objects.filter(
            id__in=project_ids_with_links,
            organization=organization,
            resource_type=ResourceType.ENTITY,
            updated_at__gt=since,
            uri__icontains="/entities/projekt/",
        ).values_list("id", flat=True)
    )

    new_project_ids = set(
        Resource.objects.filter(
            organization=organization,
            resource_type=ResourceType.ENTITY,
            updated_at__gt=since,
            uri__icontains="/entities/projekt/",
        )
        .exclude(oai_media_links__isnull=False)
        .values_list("id", flat=True)
    )

    return False, curated_ids | project_ids_from_resource | new_project_ids


def collect_publication_candidate_ids(
    organization: Organization,
    *,
    since: datetime | None,
) -> Tuple[bool, Set[int]]:
    """Return project IDs requiring OAI publication evaluation."""

    if since is None:
        return True, set()

    ids = set(
        Resource.objects.filter(
            organization=organization,
            resource_type=ResourceType.ENTITY,
            uri__icontains="/entities/projekt/",
        )
        .filter(
            Q(updated_at__gt=since)
            | Q(oai_publication__updated_at__gt=since)
        )
        .values_list("id", flat=True)
    )

    return False, ids
