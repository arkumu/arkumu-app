"""Project detail view backed by cached project snapshots."""

from django.views.generic import View
from django.shortcuts import render
from django.contrib.auth.mixins import LoginRequiredMixin
import logging
from typing import Dict, List, Optional

from arkumu.projects import ProjectRecord
from arkumu.projects.services import ProjectSnapshotService

logger = logging.getLogger(__name__)


class ProjectView(LoginRequiredMixin, View):
    """Render a single project using the shared snapshot."""

    def get(self, request, *args, **kwargs):
        projekt_uri = request.GET.get('projekt')
        if not projekt_uri:
            logger.error("ProjectView: missing 'projekt' query parameter")
            return self._render_error(request, 'No project URI provided')

        try:
            snapshot_service = ProjectSnapshotService()
            snapshot = snapshot_service.get_cross_institutional_snapshot()
            record = self._find_record(snapshot.projects, projekt_uri)

            if not record:
                logger.warning("ProjectView: project not found in snapshot: %s", projekt_uri)
                return self._render_error(request, f'Project not found: {projekt_uri}')

            context = {'project': self._build_context(record)}
            return render(request, 'catalog/projekt.html', context)

        except Exception as exc:
            logger.exception("ProjectView: error loading project %s", projekt_uri)
            return self._render_error(request, f'Error loading project: {exc}')

    @staticmethod
    def _find_record(records: List[ProjectRecord], uri: str) -> Optional[ProjectRecord]:
        for record in records:
            if record.uri == uri:
                return record
        return None

    def _build_context(self, record: ProjectRecord) -> Dict[str, object]:
        image = record.image
        if not image and record.digital_objects:
            image = record.digital_objects[0].path
        image = image or 'images/main/card_1.png'

        alternative_title = record.alternative_titles[0].value if record.alternative_titles else ''
        catchphrases = [item.label for item in record.catchphrases if item.label]
        categories = [item.label for item in record.categories if item.label]
        digital_objects = [item.path for item in record.digital_objects if item.path]
        actors = [
            {
                'name': actor.name,
                'roles': actor.roles,
            }
            for actor in record.actors
            if actor.name
        ]
        events = [
            {
                'start': event.start,
                'end': event.end,
            }
            for event in record.events
            if event.start or event.end
        ]

        if not record.year_range and events:
            year_range = self._derive_year_range(events)
        else:
            year_range = record.year_range or ''

        return {
            'uri': record.uri,
            'title': record.title or 'Untitled Project',
            'subtitle': record.subtitle or '',
            'alternative_title': alternative_title,
            'descriptions': [record.description] if record.description else [],
            'image': image,
            'institution': record.institution.label if record.institution and record.institution.label else '',
            'projektart': record.project_type.label if record.project_type and record.project_type.label else '',
            'year_range': year_range,
            'categories': categories,
            'actors': actors,
            'catchphrases': catchphrases,
            'digital_objects': digital_objects,
            'events': events,
        }

    @staticmethod
    def _derive_year_range(events: List[Dict[str, str]]) -> str:
        for event in events:
            start = event.get('start')
            end = event.get('end')
            if start and end:
                start_year = start.split('-')[0]
                end_year = end.split('-')[0]
                return start_year if start_year == end_year else f"{start_year} bis {end_year}"
            if start:
                return start.split('-')[0]
            if end:
                return end.split('-')[0]
        return ''

    @staticmethod
    def _render_error(request, message: str):
        return render(request, 'catalog/design_error.html', {'error': message})
