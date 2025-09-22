"""Cache service for reusable project snapshots."""

from __future__ import annotations

from typing import Optional

from django.utils import timezone

from .base_cache_service import BaseCacheService
from arkumu.projects import ProjectSnapshot


class ProjectCacheService(BaseCacheService):
    """Store and retrieve cached project snapshots."""

    def __init__(self) -> None:
        super().__init__('projects')

    def get_cross_institutional_snapshot(self) -> Optional[ProjectSnapshot]:
        payload = self.get_cached('snapshot', scope='cross_institutional')
        if not payload:
            return None
        return ProjectSnapshot.from_payload(payload)

    def set_cross_institutional_snapshot(self, snapshot: ProjectSnapshot) -> None:
        payload = snapshot.to_payload()
        payload['cached_at'] = timezone.now().isoformat()
        self.set_cached(
            'snapshot',
            payload,
            'project_snapshot',
            scope='cross_institutional',
        )

    def invalidate_cross_institutional_snapshot(self) -> None:
        self.invalidate('snapshot', scope='cross_institutional')
