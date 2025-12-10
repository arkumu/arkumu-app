from __future__ import annotations

import logging
from typing import Iterable, List

from django.core.exceptions import ObjectDoesNotExist
from django.core.management import call_command

from huey import crontab
from huey.contrib.djhuey import db_task, db_periodic_task

from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.services.external_sources_entity_cache_service import (
    ExternalSourcesEntityCacheService,
)

logger = logging.getLogger(__name__)


@db_task()
def ensure_cached_task(
    data_ids: Iterable[str],
    property_ids: Iterable[str],
    source: ExternalSourcesEntityCacheService.Source,
    *,
    force_refresh: bool = False,
) -> List[str]:
    ExternalSourcesEntityCacheService().ensure_cached(
        data_ids,
        property_ids,
        source,
        force_refresh=force_refresh,
    )


@db_task()
def ensure_cached_all_task(
    *,
    force_refresh: bool = False,
) -> List[str]:
    ExternalSourcesEntityCacheService().ensure_cached_all(
        force_refresh=force_refresh,
    )


def _resolve_mapping(mapping_id: str) -> Mapping:
    try:
        return Mapping.objects.get(id=mapping_id)
    except ObjectDoesNotExist as exc:  # pragma: no cover - defensive
        logger.error("Mapping %s does not exist for Huey task", mapping_id)
        raise


@db_task()
def promote_legacy_junctions_task(
    *,
    mapping_id: str,
    dry_run: bool = False,
) -> str:
    """
    Run promote_legacy_junctions for the mapping's organization.
    """
    mapping = _resolve_mapping(mapping_id)
    org_code = (mapping.organization_id or "").lower()
    if not org_code:
        raise ValueError(f"Mapping {mapping_id} is missing organization_id")

    logger.info(
        "Running promote_legacy_junctions for org=%s (mapping=%s, dry_run=%s)",
        org_code,
        mapping.id,
        dry_run,
    )
    call_command(
        "promote_legacy_junctions",
        organizations=[org_code],
        dry_run=dry_run,
    )
    return f"promote_legacy_junctions completed for org '{org_code}'"


@db_task()
def create_promoted_manifest_task(
    *,
    mapping_id: str,
    output_key: str = "promoted_manifest",
) -> str:
    """
    Run create_promoted_schema_manifest for a specific mapping.
    """
    mapping = _resolve_mapping(mapping_id)
    org_code = (mapping.organization_id or "").lower()
    if not org_code:
        raise ValueError(f"Mapping {mapping_id} is missing organization_id")

    logger.info(
        "Running create_promoted_schema_manifest for mapping=%s (org=%s, output_key=%s)",
        mapping.id,
        org_code,
        output_key,
    )
    call_command(
        "create_promoted_schema_manifest",
        organization=org_code,
        mapping_id=str(mapping.id),
        output_key=output_key,
    )
    return (
        f"create_promoted_schema_manifest completed for mapping '{mapping.id}' "
        f"(org '{org_code}', output_key '{output_key}')"
    )


@db_task()
def promote_and_reindex_task(
    *,
    organizations: List[str],
) -> str:
    """
    Promote legacy junctions for multiple organizations, then rebuild project index.

    This task:
    1. Runs promote_legacy_junctions for each organization
    2. Rebuilds the project index for all projects
    """
    org_codes = [org.lower() for org in organizations]

    logger.info("Starting promote_and_reindex for orgs=%s", org_codes)

    # Step 1: Promote legacy junctions for all orgs
    for org_code in org_codes:
        logger.info("Promoting legacy junctions for org=%s", org_code)
        call_command(
            "promote_legacy_junctions",
            organizations=[org_code],
        )
        logger.info("Completed promote_legacy_junctions for org=%s", org_code)

    # Step 2: Rebuild project index
    logger.info("Rebuilding project index...")
    call_command("rebuild_project_index")
    logger.info("Completed rebuild_project_index")

    return f"promote_and_reindex completed for orgs: {', '.join(org_codes)}"


@db_periodic_task(crontab(minute='0', hour='0'))
def nightly_promote_and_reindex():
    """
    Nightly task to promote legacy junctions and rebuild project index.

    Runs at 00:00 (midnight) every day for rsh, fuk, det organizations.
    """
    organizations = ["rsh", "fuk", "det"]
    logger.info("Starting nightly promote_and_reindex for orgs=%s", organizations)

    for org_code in organizations:
        logger.info("Promoting legacy junctions for org=%s", org_code)
        call_command(
            "promote_legacy_junctions",
            organizations=[org_code],
        )
        logger.info("Completed promote_legacy_junctions for org=%s", org_code)

    logger.info("Rebuilding project index...")
    call_command("rebuild_project_index")
    logger.info("Completed nightly promote_and_reindex")
