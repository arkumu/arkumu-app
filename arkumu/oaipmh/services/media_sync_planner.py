"""Helpers for durable media-sync planning."""

from __future__ import annotations

from datetime import datetime
from typing import Set, Tuple

from django.db.models import Q

from arkumu.oaipmh.models import OAIMediaSyncState, OAIProjectMediaLink
from arkumu.oaipmh.services.project_scope import project_queryset_for_org
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

    project_queryset = project_queryset_for_org(organization)

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
        project_queryset.filter(
            id__in=project_ids_with_links,
            updated_at__gt=since,
        ).values_list("id", flat=True)
    )

    new_project_ids = set(
        project_queryset.filter(
            updated_at__gt=since,
        )
        .exclude(oai_media_links__isnull=False)
        .values_list("id", flat=True)
    )

    # Catch older projects that never received curated links because they were
    # imported before an initial seed watermark. These have no media links at
    # all and should be processed once even if their updated_at is <= since.
    unseeded_project_ids = set(
        project_queryset.filter(
            oai_media_links__isnull=True,
            updated_at__lte=since,
        )
        .values_list("id", flat=True)
    )

    return False, curated_ids | project_ids_from_resource | new_project_ids | unseeded_project_ids


def collect_publication_candidate_ids(
    organization: Organization,
    *,
    since: datetime | None,
) -> Tuple[bool, Set[int]]:
    """Return project IDs requiring OAI publication evaluation."""

    if since is None:
        return True, set()

    project_queryset = project_queryset_for_org(organization)

    ids = set(
        project_queryset.filter(
            Q(updated_at__gt=since)
            | Q(oai_publication__updated_at__gt=since)
        )
        .values_list("id", flat=True)
    )

    return False, ids
