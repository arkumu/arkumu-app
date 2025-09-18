"""
Catalog view with pagination and caching.
"""

from django.views.generic import View
from django.shortcuts import render
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.middleware.csrf import get_token
import logging
from typing import Dict, List, Any

from arkumu.metadata.services.canonical_graph_service import CanonicalGraphService
from arkumu.cache.services import CacheManager
from .catalog_template_helpers import CatalogTemplateHelperMixin

logger = logging.getLogger(__name__)


class CatalogView(LoginRequiredMixin, View, CatalogTemplateHelperMixin):
    """
    Catalog view with pagination and caching.
    """

    ITEMS_PER_PAGE = 10
    CACHE_TIMEOUT = 3600

    def get(self, request, *args, **kwargs):
        """Handle catalog page with fast HTMX search and OOB updates."""
        import time
        start_time = time.time()

        query = request.GET.get('query', '').strip()
        page = request.GET.get('page', 1)
        is_htmx = request.headers.get('HX-Request') is not None

        # Get user's organization
        org_code = None
        if hasattr(request.user, 'organization') and request.user.organization:
            org_code = request.user.organization.code

        logger.info(f"🔍 CATALOG_SEARCH: Query: '{query}', Page: {page}, Org: {org_code}, HTMX: {is_htmx}")

        if not org_code:
            logger.error(f"User {request.user.username} has no organization")
            return self._render_error(request, "User has no organization")

        try:
            # For HTMX requests without query, return empty results immediately
            if is_htmx and not query:
                logger.info("🚀 FAST_PATH: Empty HTMX request, returning empty results")
                return self.build_empty_search_response(request, query)

            # Only load projects when there's a search query
            if query:
                projects = self._get_all_projects(org_code, query)
                logger.info(f"📊 SEARCH_RESULTS: Found {len(projects)} projects for '{query}'")
            else:
                # Empty results when no query - lazy loading
                projects = []

            # Paginate results
            paginator = Paginator(projects, self.ITEMS_PER_PAGE)

            try:
                page_obj = paginator.page(page)
            except PageNotAnInteger:
                page_obj = paginator.page(1)
            except EmptyPage:
                page_obj = paginator.page(paginator.num_pages)

            # Calculate result range for display
            total_results = paginator.count
            start_result = (page_obj.number - 1) * self.ITEMS_PER_PAGE + 1 if total_results > 0 else 0
            end_result = min(page_obj.number * self.ITEMS_PER_PAGE, total_results)

            # Build pagination context
            pagination_context = {
                'current_page': page_obj.number,
                'total_pages': paginator.num_pages,
                'total_results': total_results,
                'start_result': start_result,
                'end_result': end_result,
                'has_previous': page_obj.has_previous(),
                'has_next': page_obj.has_next(),
                'previous_page': page_obj.previous_page_number() if page_obj.has_previous() else None,
                'next_page': page_obj.next_page_number() if page_obj.has_next() else None,
                'page_range': self._get_page_range(page_obj.number, paginator.num_pages)
            }

            processing_time = time.time() - start_time

            # For HTMX requests, return unified results container
            if is_htmx:
                logger.info(f"⚡ HTMX_RESPONSE: Returning unified results container in {processing_time:.3f}s")
                response = self.build_search_response(
                    request=request,
                    results=page_obj.object_list,
                    pagination_context=pagination_context,
                    query=query,
                    total_results=total_results
                )
                return self.add_search_performance_headers(response, query, total_results, processing_time)

            # For regular requests, return full page
            context = {
                'query': query,
                'results': page_obj.object_list,
                'pagination': pagination_context,
                # Also include individual pagination values for template
                'total_results': total_results,
                'start_result': pagination_context['start_result'],
                'end_result': pagination_context['end_result'],
                'current_page': pagination_context['current_page'],
                'total_pages': pagination_context['total_pages'],
                'has_previous': pagination_context['has_previous'],
                'has_next': pagination_context['has_next'],
                'previous_page': pagination_context['previous_page'],
                'next_page': pagination_context['next_page'],
                'page_range': pagination_context['page_range'],
                'csrf_token': get_token(request)
            }

            logger.info(f"📄 FULL_PAGE: Returning full page in {processing_time:.3f}s")
            return render(request, 'catalog/design.html', context)

        except Exception as e:
            logger.error(f"❌ CATALOG_ERROR: {e}")
            if is_htmx:
                return self.build_empty_search_response(request, query)
            return self._render_error(request, f"Error loading catalog: {str(e)}")

    def _get_all_projects(self, org_code: str, query: str = "") -> List[Dict[str, Any]]:
        """Get projects using proper cache architecture: catalog cache first, then graph cache."""
        cache_manager = CacheManager()

        # For searches, check catalog cache first
        if query:
            cached_search = cache_manager.catalog.get_cached_search_results(
                query=query,
                property_name="cross_institutional_search",
                selected_class="projekt",
                user_org="global"
            )

            if cached_search and cached_search.get('results'):
                logger.info(f"✅ CATALOG_CACHE_HIT: Using cached search results for '{query}'")
                return cached_search['results'].get('entities', [])

        # Cache miss - need to get data from graph cache or fetch fresh
        cache_resource_uri = "arkumu:cross_institutional:all_projects"
        cache_params_hash = "cross_institutional_projects_canonical"

        # Try graph cache first (shared with OAI-PMH)
        cached_graph = cache_manager.graph.get_traversal_result(
            resource_uri=cache_resource_uri,
            traversal_type="catalog_projects",
            params_hash=cache_params_hash
        )

        if cached_graph and cached_graph.get('result') and cached_graph['result'].get('projects'):
            logger.info(f"✅ GRAPH_CACHE_HIT: Using cached {len(cached_graph['result']['projects'])} projects")
            all_projects = cached_graph['result']['projects']
        else:
            # Final fallback - fetch fresh data
            logger.info(f"🔄 FRESH_FETCH: Getting fresh cross-institutional project data")
            all_projects = self._fetch_projects_from_graph(org_code)

            # Cache in graph cache for reuse by other services
            cache_manager.graph.cache_traversal_result(
                resource_uri=cache_resource_uri,
                traversal_type="catalog_projects",
                params_hash=cache_params_hash,
                result_data={'projects': all_projects}
            )
            logger.info(f"💾 GRAPH_CACHED: Stored {len(all_projects)} projects for reuse")

        # Filter by query
        if query:
            filtered_projects = self._filter_projects_by_query(all_projects, query)
            logger.info(f"🔍 FILTERED: {len(filtered_projects)} projects match '{query}'")

            # Cache the search results in catalog cache
            cache_manager.catalog.cache_search_results(
                query=query,
                property_name="cross_institutional_search",
                results={'entities': filtered_projects},
                selected_class="projekt",
                user_org="global"
            )
            logger.info(f"💾 CATALOG_CACHED: Stored search results for '{query}'")

            return filtered_projects

        return all_projects

    def _fetch_projects_from_graph(self, org_code: str) -> List[Dict[str, Any]]:
        """Fetch projects from graph service."""
        graph = self._fetch_fresh_graph(org_code)

        if graph:
            return self._graph_to_cards(graph)

        return []

    def _fetch_fresh_graph(self, org_code: str) -> Dict[str, Any]:
        """Fetch fresh graph data from service with consistent string subject IDs."""
        logger.info(f"Fetching fresh graph for cross-institutional canonical search")

        service = CanonicalGraphService()  # No org_code = all institutions
        canonical_project_uri = "http://arkumu.org/data/types/projekt"

        # Get ALL projects with canonical URI mapping (using private method for now)
        all_subject_ids = service._find_subject_ids_by_class(canonical_project_uri)
        logger.info(f"Found {len(all_subject_ids)} projects with canonical URI mapping")

        # Convert UUID objects to strings for consistent lookup
        all_subject_ids_str = [str(uid) for uid in all_subject_ids]
        logger.info(f"Sample project IDs: {all_subject_ids_str[:3]}")

        # Get edges for all subjects
        edges = service._fetch_triples_for_subjects(all_subject_ids)
        logger.info(f"Fetched {len(edges)} edges for {len(all_subject_ids)} subjects")

        # Get neighbor expansion
        if edges:
            neighbor_ids = [e.object_id for e in edges if e.object_type != 'LITERAL']
            if neighbor_ids:
                neighbor_edges = service._fetch_triples_for_subjects(neighbor_ids)
                edges.extend(neighbor_edges)

        # Build graph
        nodes = service._collect_nodes_from_edges(edges)

        return {
            "organization": "cross-institutional",
            "dataset": "Projekt",
            "subjects": all_subject_ids_str,  # Use string IDs for consistent lookup
            "nodes": nodes,
            "edges": [e.__dict__ for e in edges],
            "counts": {
                "subjects": len(all_subject_ids),
                "nodes": len(nodes),
                "edges": len(edges),
            },
        }

    def _graph_to_cards(self, graph: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Convert graph data to card format."""
        cards = []
        nodes = graph.get('nodes', {})
        edges = graph.get('edges', [])

        # Group edges by subject for easier lookup
        edges_by_subject = {}
        logger.info(f"Processing {len(edges)} edges. Sample edge keys: {list(edges[0].keys()) if edges else 'No edges'}")

        for edge in edges:
            # Try different possible subject ID keys
            subject_id = edge.get('subject_id') or edge.get('subject') or edge.get('s')
            if not subject_id:
                logger.warning(f"No subject ID found in edge: {edge}")
                continue

            if subject_id not in edges_by_subject:
                edges_by_subject[subject_id] = []
            edges_by_subject[subject_id].append(edge)

        logger.info(f"Grouped edges by subject: {len(edges_by_subject)} subjects have edges")

        # Process each subject (project) to create a card
        subjects = graph.get('subjects', [])
        logger.info(f"Processing {len(subjects)} subjects for card extraction")

        # Debug: check mismatch between subjects and edge subjects
        edge_subject_sample = list(edges_by_subject.keys())[:3]
        graph_subject_sample = subjects[:3]
        logger.info(f"DEBUG: Edge subjects sample: {edge_subject_sample}")
        logger.info(f"DEBUG: Graph subjects sample: {graph_subject_sample}")
        logger.info(f"DEBUG: First graph subject in edge subjects? {graph_subject_sample[0] in edges_by_subject if graph_subject_sample else 'No subjects'}")

        for i, subject_id in enumerate(subjects):
            subject_edges = edges_by_subject.get(subject_id, [])
            if subject_edges:
                # Debug first subject
                if i == 0:
                    sample_uris = set()
                    for edge in subject_edges:
                        canonical_uri = edge.get('predicate_canonical') or edge['predicate_uri']
                        sample_uris.add(canonical_uri)
                    logger.info(f"DEBUG: Sample canonical URIs for first subject: {list(sample_uris)[:10]}")

                card_data = self._extract_card_from_graph(subject_id, subject_edges, edges)
                if card_data:
                    cards.append(card_data)
                elif i == 0:  # Log why first card failed
                    logger.info(f"DEBUG: First card failed extraction for subject {subject_id}")

        logger.info(f"Converted graph to {len(cards)} cards")
        return cards

    def _extract_card_from_graph(self, subject_id: str, subject_edges: List[Dict], all_edges: List[Dict]) -> Dict[str, Any]:
        """Extract card data from graph edges for a specific subject."""
        # Canonical URIs for card data extraction
        TITLE_URI = "http://arkumu.org/data/properties/bevorzugter-titel"
        SUBTITLE_URI = "http://arkumu.org/data/properties/bevorzugter-untertitel"
        IMAGE_URI = "http://arkumu.org/data/properties/vorschaubild"
        INSTITUTION_URI = "http://arkumu.org/data/properties/einliefernde-hochschule"
        CATEGORY_URI = "http://arkumu.org/data/properties/projektkategorie"
        EVENT_URI = "http://arkumu.org/data/properties/ereignis"

        # Institution and category German name URIs
        INSTITUTION_GERMAN_NAME = "http://arkumu.org/data/properties/deutscher-name-der-einliefernden-hochschule"
        CATEGORY_GERMAN_NAME = "http://arkumu.org/data/properties/deutscher-name-der-projektkategorie-breadcrumb"

        # Event date URIs
        EVENT_START_URI = "http://arkumu.org/data/properties/ereignisbeginn"
        EVENT_END_URI = "http://arkumu.org/data/properties/ereignisende"

        # Initialize card data
        card = {
            'uri': subject_id,
            'title': '',
            'subtitle': '',
            'image': 'images/main/card_1.png',  # default image
            'institution': '',
            'categories': [],
            'year_range': ''
        }


        # Extract basic properties
        for edge in subject_edges:
            canonical_uri = edge.get('predicate_canonical') or edge['predicate_uri']

            if canonical_uri == TITLE_URI and edge.get('object_value'):
                card['title'] = edge['object_value']
                logger.debug(f"Found title for {subject_id}: {edge['object_value']}")
            elif canonical_uri == SUBTITLE_URI and edge.get('object_value'):
                card['subtitle'] = edge['object_value']
            elif canonical_uri == IMAGE_URI and edge.get('object_value'):
                card['image'] = edge['object_value']

        # Extract institution name
        for edge in subject_edges:
            canonical_uri = edge.get('predicate_canonical') or edge['predicate_uri']
            if canonical_uri == INSTITUTION_URI and edge.get('object_id'):
                institution_id = edge['object_id']
                # Find the German name for this institution
                institution_edges = [e for e in all_edges if e.get('subject_id') == institution_id]
                for inst_edge in institution_edges:
                    inst_canonical = inst_edge.get('predicate_canonical') or inst_edge['predicate_uri']
                    if inst_canonical == INSTITUTION_GERMAN_NAME and inst_edge.get('object_value'):
                        card['institution'] = inst_edge['object_value']
                        break

        # Extract categories
        for edge in subject_edges:
            canonical_uri = edge.get('predicate_canonical') or edge['predicate_uri']
            if canonical_uri == CATEGORY_URI and edge.get('object_id'):
                category_id = edge['object_id']
                # Find the German name for this category
                category_edges = [e for e in all_edges if e.get('subject_id') == category_id]
                for cat_edge in category_edges:
                    cat_canonical = cat_edge.get('predicate_canonical') or cat_edge['predicate_uri']
                    if cat_canonical == CATEGORY_GERMAN_NAME and cat_edge.get('object_value'):
                        category_name = cat_edge['object_value']
                        # Extract final part after '>' if breadcrumb format
                        if '>' in category_name:
                            category_name = category_name.split('>')[-1].strip()
                        card['categories'].append(category_name)
                        break

        # Extract event and date information
        for edge in subject_edges:
            canonical_uri = edge.get('predicate_canonical') or edge['predicate_uri']
            if canonical_uri == EVENT_URI and edge.get('object_id'):
                event_id = edge['object_id']
                # Find start and end dates for this event
                event_edges = [e for e in all_edges if e.get('subject_id') == event_id]
                event_start = None
                event_end = None

                for event_edge in event_edges:
                    event_canonical = event_edge.get('predicate_canonical') or event_edge['predicate_uri']
                    if event_canonical == EVENT_START_URI and event_edge.get('object_value'):
                        event_start = event_edge['object_value']
                    elif event_canonical == EVENT_END_URI and event_edge.get('object_value'):
                        event_end = event_edge['object_value']

                # Format year range
                if event_start and event_end:
                    start_year = event_start.split('-')[0] if '-' in event_start else event_start
                    end_year = event_end.split('-')[0] if '-' in event_end else event_end
                    if start_year == end_year:
                        card['year_range'] = start_year
                    else:
                        card['year_range'] = f"{start_year} bis {end_year}"
                elif event_start:
                    card['year_range'] = event_start.split('-')[0] if '-' in event_start else event_start
                break

        # Only return card if it has a title
        if card['title']:
            return card

        return None

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
        if total <= 7:
            return list(range(1, total + 1))

        if current <= 3:
            return list(range(1, min(6, total + 1))) + ([total] if total > 6 else [])
        elif current >= total - 2:
            return [1] + list(range(max(total - 4, 2), total + 1))
        else:
            return [1] + list(range(current - 1, min(current + 2, total + 1))) + ([total] if current + 2 < total else [])


    def _render_error(self, request, error_message: str):
        """Render error page."""
        context = {
            'error': error_message
        }
        return render(request, 'catalog/design_error.html', context)