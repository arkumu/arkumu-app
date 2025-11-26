"""Load project detail data from ProjectDetailIndex for views."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from arkumu.catalog.models import ProjectDetailIndex

logger = logging.getLogger(__name__)


class ProjectDetailLoader:
    """Load project details from the ProjectDetailIndex table."""

    def get_detail_by_uri(self, uri: str) -> Optional[ProjectDetailIndex]:
        """Load ProjectDetailIndex entry by project URI."""
        if not uri:
            return None

        try:
            return ProjectDetailIndex.objects.get(uri=uri)
        except ProjectDetailIndex.DoesNotExist:
            return None
        except Exception:
            logger.exception("ProjectDetailLoader: error loading %s", uri)
            return None

    def get_view_context(self, uri: str) -> Optional[Dict[str, Any]]:
        """Load project detail context dict for view templates."""
        entry = self.get_detail_by_uri(uri)
        if not entry:
            return None
        return entry.to_view_context()
