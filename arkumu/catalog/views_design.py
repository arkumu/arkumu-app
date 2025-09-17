"""
Optimized catalog design view with server-side rendering and pagination.
"""

from django.views.generic import View
from django.shortcuts import render
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.middleware.csrf import get_token
import logging
from typing import Dict, List, Any

from arkumu.metadata.services.canonical_graph_service import CanonicalGraphService
from arkumu.cache.services.graph_cache_service import GraphCacheService
from arkumu.catalog.services.project_views import get_card_view_data

logger = logging.getLogger(__name__)


class CatalogDesignView(LoginRequiredMixin, View):
    """
    Optimized catalog design view with built-in pagination and caching.

    This replaces the simple TemplateView to provide:
    - Server-side rendering of initial results
    - Efficient pagination
    - Graph data caching
    - HTMX support for seamless navigation
    """

    ITEMS_PER_PAGE = 20  # Configurable page size
    CACHE_TIMEOUT = 3600  # 1 hour cache

    def get(self, request, *args, **kwargs):
        """Handle catalog design page with optional HTMX pagination."""
        query = request.GET.get('query', '').strip()
        page = request.GET.get('page', 1)
        is_htmx = request.headers.get('HX-Request') is not None

        # Get user's organization
        org_code = None
        if hasattr(request.user, 'organization') and request.user.organization:
            org_code = request.user.organization.code

        logger.info(f"CatalogDesignView - Query: '{query}', Page: {page}, Org: {org_code}, HTMX: {is_htmx}")

        if not org_code:
            logger.error(f"User {request.user.username} has no organization")
            return self._render_error(request, "User has no organization")

        try:
            # Get all projects (from cache or service)
            projects = self._get_all_projects(org_code, query)

            # Paginate results
            paginator = Paginator(projects, self.ITEMS_PER_PAGE)

            try:
                page_obj = paginator.page(page)
            except PageNotAnInteger:
                page_obj = paginator.page(1)
            except EmptyPage:
                page_obj = paginator.page(paginator.num_pages)

            # Calculate result range for display
            start_result = (page_obj.number - 1) * self.ITEMS_PER_PAGE + 1
            end_result = min(page_obj.number * self.ITEMS_PER_PAGE, paginator.count)

            # Build pagination context
            pagination_context = {
                'current_page': page_obj.number,
                'total_pages': paginator.num_pages,
                'total_results': paginator.count,
                'start_result': start_result,
                'end_result': end_result,
                'has_previous': page_obj.has_previous(),
                'has_next': page_obj.has_next(),
                'previous_page': page_obj.previous_page_number() if page_obj.has_previous() else None,
                'next_page': page_obj.next_page_number() if page_obj.has_next() else None,
                'page_range': self._get_page_range(page_obj.number, paginator.num_pages)
            }

            context = {
                'query': query,
                'results': page_obj.object_list,
                'pagination': pagination_context,
                'csrf_token': get_token(request)
            }

            # For HTMX requests, return partial template with OOB updates
            if is_htmx:
                return self._render_htmx_response(request, context)

            # For regular requests, return full page
            return render(request, 'catalog/design_optimized.html', context)

        except Exception as e:
            logger.error(f"CatalogDesignView error: {e}")
            return self._render_error(request, f"Error loading catalog: {str(e)}")

    def _get_all_projects(self, org_code: str, query: str = "") -> List[Dict[str, Any]]:
        """
        Get all projects using shared graph cache (same as OAI-PMH).

        Returns filtered list of project cards.
        """
        # Use shared GraphCacheService (same cache used by OAI-PMH)
        cache_service = GraphCacheService()

        # Create shared cache key for cross-institutional projects
        cache_resource_uri = "arkumu:cross_institutional:all_projects"
        cache_params_hash = "cross_institutional_projects_canonical"

        # Try to get cached graph data (shared with OAI-PMH)
        cached_result = cache_service.get_traversal_result(
            resource_uri=cache_resource_uri,
            traversal_type="catalog_projects",
            params_hash=cache_params_hash
        )

        if cached_result and cached_result.get('result'):
            logger.info(f"Using shared graph cache for cross-institutional projects")
            projects = cached_result['result'].get('projects', [])
        else:
            # Fetch fresh data and cache it for sharing with OAI-PMH
            logger.info(f"Fetching fresh cross-institutional project data")
            projects = self._fetch_projects_from_graph(org_code)

            # Cache using shared graph cache service
            if projects:
                cache_service.cache_traversal_result(
                    resource_uri=cache_resource_uri,
                    traversal_type="catalog_projects",
                    params_hash=cache_params_hash,
                    result_data={'projects': projects}
                )
                logger.info(f"Cached {len(projects)} cross-institutional projects in shared cache")

        # Filter by query if provided
        if query:
            projects = self._filter_projects_by_query(projects, query)
            logger.info(f"Filtered to {len(projects)} projects matching '{query}'")

        return projects

    def _fetch_projects_from_graph(self, org_code: str) -> List[Dict[str, Any]]:
        """Fetch projects from graph service (no additional caching here)."""
        # Fetch fresh graph data - caching is handled at higher level
        graph = self._fetch_fresh_graph(org_code)

        # Convert graph to cards
        if graph:
            return self._graph_to_cards(graph)

        return []

    def _fetch_fresh_graph(self, org_code: str) -> Dict[str, Any]:
        """Fetch fresh graph data from service."""
        logger.info(f"Fetching fresh graph for cross-institutional canonical search")

        # Don't specify org_code for cross-institutional search
        service = CanonicalGraphService()

        # Use ONLY canonical URI - no fallbacks
        canonical_project_uri = "http://arkumu.org/data/types/projekt"

        # Get ALL projects with canonical URI mapping - no limits
        all_subject_ids = service._find_subject_ids_by_class(
            canonical_project_uri
        )

        logger.info(f"Found {len(all_subject_ids)} projects with canonical URI mapping")

        # Get edges for all subjects
        edges = service._fetch_triples_for_subjects(all_subject_ids)

        # Get neighbor expansion - no limits
        if edges:
            neighbor_ids = [e.object_id for e in edges if e.object_type != 'LITERAL']
            if neighbor_ids:
                neighbor_edges = service._fetch_triples_for_subjects(neighbor_ids)
                edges.extend(neighbor_edges)

        # Build graph
        nodes = service._collect_nodes_from_edges(edges)

        graph = {
            "organization": "cross-institutional",
            "dataset": "Projekt",
            "subjects": all_subject_ids,
            "nodes": nodes,
            "edges": [e.__dict__ for e in edges],
            "counts": {
                "subjects": len(all_subject_ids),
                "nodes": len(nodes),
                "edges": len(edges),
            },
        }

        # Store for traversal methods
        self.current_graph = graph

        return graph

    def _graph_to_cards(self, graph: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Convert graph data to card format using new project_views service."""
        from arkumu.metadata.models.resource import Resource

        cards = []
        project_subjects = graph.get('subjects', [])
        logger.info(f"Converting {len(project_subjects)} projects to cards using project_views service")

        for project_id in project_subjects:
            try:
                # Get the project URI from Resource model using the project_id
                resource = Resource.objects.get(id=project_id)
                project_uri = resource.uri

                logger.info(f"Found project URI: {project_uri} for ID: {project_id}")

                # Use the new service to extract card data
                card_data = get_card_view_data(project_uri)

                if card_data:
                    # Convert CardData to template format
                    card = self._card_data_to_template_format(card_data)
                    cards.append(card)
                    logger.info(f"Successfully converted project {project_uri} to card")
                else:
                    logger.warning(f"Failed to extract card data for project: {project_uri}")

            except Resource.DoesNotExist:
                logger.error(f"Resource not found for project ID: {project_id}")
                continue
            except Exception as e:
                logger.error(f"Error processing project {project_id}: {e}")
                continue

        logger.info(f"Successfully converted {len(cards)} projects to cards")
        return cards

    def _card_data_to_template_format(self, card_data) -> Dict[str, Any]:
        """Convert CardData object to template format."""
        card = {
            "uri": card_data.uri,
            "title": card_data.title or "",
            "subtitle": card_data.subtitle or "",
            "image": card_data.image or "images/main/card_1.png",
            "button_text": "Projekt ansehen",
            "year": "",
            "institution": card_data.institution,
            "description": "",
            "project_type": "",
            "catchphrases": []
        }

        # Format event dates
        if card_data.event_start and card_data.event_end:
            start_year = card_data.event_start.split('-')[0] if '-' in card_data.event_start else card_data.event_start
            end_year = card_data.event_end.split('-')[0] if '-' in card_data.event_end else card_data.event_end
            if start_year == end_year:
                card["year"] = start_year
            else:
                card["year"] = f"{start_year} bis {end_year}"
        elif card_data.event_start:
            card["year"] = card_data.event_start.split('-')[0] if '-' in card_data.event_start else card_data.event_start

        # Format categories
        for i, category in enumerate(card_data.categories[:4]):
            card[f"category{i+1}"] = category

        if len(card_data.categories) > 4:
            card["additional_categories"] = f"{len(card_data.categories)-4} weitere"

        # Format actors
        for i, actor in enumerate(card_data.actors[:4]):
            card[f"contributor{i+1}_name"] = actor.get('name', '')
            card[f"contributor{i+1}_role"] = ", ".join(actor.get('roles', []))

        if len(card_data.actors) > 4:
            card["additional_contributors"] = f"{len(card_data.actors)-4} weitere"

        logger.info(f"Template card: {card}")
        return card


    def _filter_projects_by_query(self, projects: List[Dict], query: str) -> List[Dict]:
        """Filter projects by search query."""
        if not query:
            return projects

        query_lower = query.lower()
        filtered = []

        for project in projects:
            searchable_text = " ".join([
                project.get('title', ''),
                project.get('subtitle', ''),
                project.get('institution', ''),
                " ".join(project.get('categories', []))
            ]).lower()

            if query_lower in searchable_text:
                filtered.append(project)

        return filtered

    def _get_page_range(self, current: int, total: int) -> List[int]:
        """Get list of page numbers to display in pagination."""
        # Show max 5 pages around current
        if total <= 7:
            return list(range(1, total + 1))

        if current <= 3:
            return list(range(1, min(6, total + 1))) + ([total] if total > 6 else [])
        elif current >= total - 2:
            return [1] + list(range(max(total - 4, 2), total + 1))
        else:
            return [1] + list(range(current - 1, min(current + 2, total + 1))) + ([total] if current + 2 < total else [])

    def _render_htmx_response(self, request, context):
        """Render HTMX response with OOB updates."""
        from django.http import HttpResponse
        from django.template.loader import render_to_string

        # Render main card grid
        cards_html = render_to_string(
            'catalog/partials/card_grid.html',
            {'results': context['results']},
            request=request
        )

        # Render pagination with OOB
        pagination_html = render_to_string(
            'catalog/partials/pagination_htmx.html',
            context['pagination'],
            request=request
        )

        # Build response with OOB updates
        response_html = f"""
        {cards_html}
        <div id="pagination-container" hx-swap-oob="true">
            {pagination_html}
        </div>
        <div id="results-count" hx-swap-oob="true">
            Ergebnisse {context['pagination']['start_result']}-{context['pagination']['end_result']} von {context['pagination']['total_results']}
        </div>
        """

        return HttpResponse(response_html)

    def _render_error(self, request, error_message: str):
        """Render error page."""
        context = {
            'error': error_message
        }
        return render(request, 'catalog/design_error.html', context)


class ProjectDetailView(LoginRequiredMixin, View):
    """Project detail view using canonical URIs."""

    def get(self, request, *args, **kwargs):
        """Display project detail page."""
        projekt_uri = request.GET.get('projekt')

        if not projekt_uri:
            return render(request, 'catalog/design_error.html', {
                'error': 'No project URI provided'
            })

        logger.info(f"ProjectDetailView - Project URI: {projekt_uri}")

        try:
            # Use the modern project_views service
            from arkumu.catalog.services.project_views import get_project_view_data

            project_data = get_project_view_data(projekt_uri)

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

            # Convert ProjectData to template context matching the expected structure
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