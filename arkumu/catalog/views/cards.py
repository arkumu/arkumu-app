"""Card search view backed by reusable project snapshots."""

from django.views.generic import View
from django.shortcuts import render
from django.contrib.auth.mixins import LoginRequiredMixin
import logging

from arkumu.projects.services import ProjectSnapshotService

logger = logging.getLogger(__name__)


class GraphSearchView(LoginRequiredMixin, View):
    """Search projects using the cached snapshot shared by catalog and OAI."""

    def get(self, request, *args, **kwargs):
        """Handle search requests using graph service."""
        query = request.GET.get('query', '').strip()
        is_htmx_request = request.headers.get('HX-Request') is not None

        # Get user's organization
        org_code = None
        if hasattr(request.user, 'organization') and request.user.organization:
            org_code = request.user.organization.code

        logger.info(f"Graph Search Request - Query: '{query}', Org: {org_code}, HTMX: {is_htmx_request}, User: {request.user.username}")

        if not org_code:
            logger.error(f"User {request.user.username} has no organization")
            return self._render_empty_results(request, query, "User has no organization")

        try:
            snapshot_service = ProjectSnapshotService()
            snapshot = snapshot_service.get_cross_institutional_snapshot()
            records = snapshot.projects
            logger.info(
                "GraphSearchView: snapshot generated %s with %d projects",
                snapshot.generated_at.isoformat(),
                len(records),
            )

            if query:
                records = [record for record in records if record.matches_query(query)]

            logger.info("Project snapshot returned %d matching projects", len(records))

            cards = [record.to_card_dict() for record in records]

            context = {
                'query': query,
                'results': cards,
                'total_results': len(cards)
            }

            return render(request, 'catalog/card_grid_template.html', context)

        except Exception as e:
            logger.error(f"Project snapshot error: {e}")
            return self._render_empty_results(request, query, f"Search error: {str(e)}")

    def _render_empty_results(self, request, query: str, error: str = None):
        """Render empty results template."""
        context = {
            'query': query,
            'results': [],
            'error': error
        }
        return render(request, 'catalog/card_grid_template.html', context)
