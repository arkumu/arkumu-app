"""
Project detail view using canonical URIs.
"""

from django.views.generic import View
from django.shortcuts import render
from django.contrib.auth.mixins import LoginRequiredMixin
import logging

from arkumu.metadata.services.canonical_graph_service import CanonicalGraphService
from arkumu.catalog.services.project_views import ProjectData

logger = logging.getLogger(__name__)


class ProjectView(LoginRequiredMixin, View):
    """Project detail view using canonical URIs."""

    def get(self, request, *args, **kwargs):
        """Display project detail page."""
        projekt_uri = request.GET.get('projekt')

        if not projekt_uri:
            return render(request, 'catalog/design_error.html', {
                'error': 'No project URI provided'
            })

        logger.info(f"ProjectView - Project URI: {projekt_uri}")

        try:
            # Get project data from graph
            project_data = self._get_project_from_graph(projekt_uri)

            if not project_data:
                return render(request, 'catalog/design_error.html', {
                    'error': f'Project not found: {projekt_uri}'
                })

            # Format date range
            year_range = ''
            if project_data.event_start and project_data.event_end:
                start_year = project_data.event_start.split('-')[0] if '-' in project_data.event_start else project_data.event_start
                end_year = project_data.event_end.split('-')[0] if '-' in project_data.event_end else project_data.event_end
                if start_year == end_year:
                    year_range = start_year
                else:
                    year_range = f"{start_year} bis {end_year}"
            elif project_data.event_start:
                year_range = project_data.event_start.split('-')[0] if '-' in project_data.event_start else project_data.event_start

            # Convert ProjectData to template context
            context = {
                'project': {
                    'uri': project_data.uri,
                    'title': project_data.title or 'Untitled Project',
                    'subtitle': project_data.subtitle or '',
                    'alternative_title': project_data.alternative_titles[0] if project_data.alternative_titles else '',
                    'descriptions': [project_data.description] if project_data.description else [],
                    'image': project_data.image or 'images/main/card_1.png',
                    'institution': project_data.institution or '',
                    'projektart': project_data.project_type or '',
                    'year_range': year_range,
                    'categories': project_data.categories or [],
                    'actors': project_data.actors or [],
                    'catchphrases': project_data.catchphrases or [],
                    'digital_objects': project_data.digital_objects or [],
                }
            }

            logger.info(f"Successfully loaded project data for: {projekt_uri}")
            return render(request, 'catalog/projekt.html', context)

        except Exception as e:
            logger.error(f"Error loading project {projekt_uri}: {e}")
            return render(request, 'catalog/design_error.html', {
                'error': f'Error loading project: {str(e)}'
            })

    def _get_project_from_graph(self, projekt_uri: str):
        """Get single project data using canonical graph service."""
        service = CanonicalGraphService()

        try:
            # Get project graph for this specific project
            project_graph = service.get_entity_graph(
                resource_uri=projekt_uri,
                predicate_canon_whitelist=None,
                include_incoming=False,
                expand_neighbors=True,
                depth=2
            )

            if not project_graph:
                logger.warning(f"No graph data for project: {projekt_uri}")
                return None

            logger.info(f"Loaded single project graph: {projekt_uri}")

            # Extract project data from the entity graph
            return self._extract_project_from_entity_graph(projekt_uri, project_graph)

        except Exception as e:
            logger.error(f"Error loading project graph for {projekt_uri}: {e}")
            return None

    def _extract_project_from_entity_graph(self, projekt_uri: str, project_graph):
        """Extract project data from entity graph."""
        nodes = project_graph.get('nodes', {})
        edges = project_graph.get('edges', [])

        # Find properties for this project
        project_props = {}
        for edge in edges:
            if edge['subject_id'] == project_graph['root_id']:
                canonical_uri = edge.get('predicate_canonical') or edge['predicate_uri']
                project_props[canonical_uri] = edge

        # Extract basic properties using canonical URIs
        title = self._get_edge_value(project_props, "http://arkumu.org/data/properties/bevorzugter-titel")
        subtitle = self._get_edge_value(project_props, "http://arkumu.org/data/properties/bevorzugter-untertitel")

        logger.info(f"Extracted project data: title='{title}', subtitle='{subtitle}'")

        return ProjectData(
            uri=projekt_uri,
            title=title or 'Untitled Project',
            subtitle=subtitle or '',
            image=None,
            institution='',
            event_start=None,
            event_end=None,
            categories=[],
            actors=[],
            alternative_titles=[],
            description='',
            catchphrases=[],
            project_type='',
            digital_objects=[]
        )

    def _get_edge_value(self, props, canonical_uri):
        """Get edge value by canonical URI."""
        edge = props.get(canonical_uri)
        if edge and edge.get('object_value'):
            return edge['object_value']
        return None