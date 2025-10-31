from huey.contrib.djhuey import db_task
from typing import Iterable, List
from arkumu.metadata.services.external_sources_entity_cache_service import ExternalSourcesEntityCacheService

@db_task()
def ensure_cached_task(
    data_ids: Iterable[str],
    property_ids: Iterable[str],
    source: ExternalSourcesEntityCacheService.Source,
    *,
    force_refresh: bool = False,
) -> List[str]:
    ExternalSourcesEntityCacheService().ensure_cached(data_ids, property_ids, source, force_refresh=force_refresh)

@db_task()
def ensure_cached_all_task(
    *,
    force_refresh: bool = False,
) -> List[str]:
    ExternalSourcesEntityCacheService().ensure_cached_all(force_refresh=force_refresh)
