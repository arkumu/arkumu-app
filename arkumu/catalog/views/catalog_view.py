"""
Catalog view with pagination and caching.
"""

from django.views.generic import View
from django.shortcuts import render
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.middleware.csrf import get_token
import logging
import copy
from typing import Dict, List, Any, Optional

from arkumu.metadata.services.canonical_graph_service import CanonicalGraphService
from arkumu.cache.services import CacheManager
from arkumu.catalog.services.schema_manifest_service import (
    SchemaManifestService,
    CARD_SCHEMA_TEMPLATE,
    CardSchema,
    CardProperty,
)
from .catalog_template_helpers import CatalogTemplateHelperMixin

logger = logging.getLogger(__name__)


class CatalogView(LoginRequiredMixin, View, CatalogTemplateHelperMixin):
    """
    Catalog view with pagination and caching.
    """

    ITEMS_PER_PAGE = 10
    CACHE_TIMEOUT = 3600
    schema_manifest_service = SchemaManifestService()

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
            card_schema = self.schema_manifest_service.get_card_schema(org_code)

            # For HTMX requests without query, return empty results immediately
            if is_htmx and not query:
                logger.info("🚀 FAST_PATH: Empty HTMX request, returning empty results")
                return self.build_empty_search_response(request, query)

            # Only load projects when there's a search query
            if query:
                projects = self._get_all_projects(org_code, query, card_schema)
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

    def _get_all_projects(
        self,
        org_code: str,
        query: str = "",
        card_schema: Optional[CardSchema] = None
    ) -> List[Dict[str, Any]]:
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
            all_projects = self._fetch_projects_from_graph(org_code, card_schema)

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

    def _fetch_projects_from_graph(
        self,
        org_code: str,
        card_schema: Optional[CardSchema] = None
    ) -> List[Dict[str, Any]]:
        """Fetch projects from graph service."""
        graph = self._fetch_fresh_graph(org_code)

        if graph:
            return self._graph_to_cards(graph, card_schema)

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

    def _graph_to_cards(
        self,
        graph: Dict[str, Any],
        card_schema: Optional[CardSchema] = None
    ) -> List[Dict[str, Any]]:
        """Convert graph data to card format."""
        cards = []
        nodes = graph.get('nodes', {})
        edges = graph.get('edges', [])

        schema = card_schema or copy.deepcopy(CARD_SCHEMA_TEMPLATE)

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

                card_data = self._extract_card_from_graph(subject_id, subject_edges, edges, schema)
                if card_data:
                    cards.append(card_data)
                elif i == 0:  # Log why first card failed
                    logger.info(f"DEBUG: First card failed extraction for subject {subject_id}")

        logger.info(f"Converted graph to {len(cards)} cards")
        return cards

    def _extract_card_from_graph(
        self,
        subject_id: str,
        subject_edges: List[Dict],
        all_edges: List[Dict],
        card_schema: CardSchema
    ) -> Optional[Dict[str, Any]]:
        """Extract card data from graph edges for a specific subject."""

        def _property(section: str, prop: str) -> Optional[CardProperty]:
            section_obj = card_schema.sections.get(section)
            if not section_obj:
                return None
            return section_obj.properties.get(prop)

        title_prop = _property('project', 'title')
        subtitle_prop = _property('project', 'subtitle')
        image_prop = _property('project', 'image')
        event_prop = _property('project', 'event')
        institution_prop = _property('project', 'institution')
        category_prop = _property('project', 'category')

        event_start_prop = _property('event', 'start')
        event_end_prop = _property('event', 'end')

        actor_link_prop = _property('actor_event', 'actor_link')
        role_link_prop = _property('actor_event', 'role_link')
        actor_name_prop = _property('actor', 'name')
        role_name_prop = _property('role', 'name')

        institution_name_prop = _property('institution', 'german_name')
        category_name_prop = _property('project_category', 'german_name')

        handled_canonical_uris = {
            prop.canonical_uri
            for section in card_schema.sections.values()
            for prop in section.properties.values()
            if prop.canonical_uri
        }

        matched_predicates: List[str] = []
        event_subject_ids: List[str] = []

        card = {
            'uri': subject_id,
            'title': '',
            'subtitle': '',
            'image': 'images/main/card_1.png',
            'institution': '',
            'categories': [],
            'year_range': ''
        }

        for edge in subject_edges:
            canonical_uri = edge.get('predicate_canonical') or edge.get('predicate_uri')
            if title_prop and canonical_uri == title_prop.canonical_uri and edge.get('object_value'):
                card['title'] = edge['object_value']
                matched_predicates.append(title_prop.canonical_uri)
                logger.debug("Found title for %s: %s", subject_id, edge['object_value'])
            elif subtitle_prop and canonical_uri == subtitle_prop.canonical_uri and edge.get('object_value'):
                card['subtitle'] = edge['object_value']
                matched_predicates.append(subtitle_prop.canonical_uri)
            elif image_prop and canonical_uri == image_prop.canonical_uri and edge.get('object_value'):
                card['image'] = edge['object_value']
                matched_predicates.append(image_prop.canonical_uri)
            elif event_prop and canonical_uri == event_prop.canonical_uri and edge.get('object_id'):
                event_subject_ids.append(edge['object_id'])

        if institution_prop and institution_name_prop:
            for edge in subject_edges:
                canonical_uri = edge.get('predicate_canonical') or edge.get('predicate_uri')
                if canonical_uri == institution_prop.canonical_uri and edge.get('object_id'):
                    institution_edges = [
                        e for e in all_edges if e.get('subject_id') == edge['object_id']
                    ]
                    for inst_edge in institution_edges:
                        inst_canonical = inst_edge.get('predicate_canonical') or inst_edge.get('predicate_uri')
                        if inst_canonical == institution_name_prop.canonical_uri and inst_edge.get('object_value'):
                            card['institution'] = inst_edge['object_value']
                            matched_predicates.append(institution_prop.canonical_uri)
                            break

        if category_prop and category_name_prop:
            category_names: List[str] = []
            for edge in subject_edges:
                canonical_uri = edge.get('predicate_canonical') or edge.get('predicate_uri')
                if canonical_uri == category_prop.canonical_uri and edge.get('object_id'):
                    category_edges = [
                        e for e in all_edges if e.get('subject_id') == edge['object_id']
                    ]
                    for cat_edge in category_edges:
                        cat_canonical = cat_edge.get('predicate_canonical') or cat_edge.get('predicate_uri')
                        if cat_canonical == category_name_prop.canonical_uri and cat_edge.get('object_value'):
                            category_name = cat_edge.get('object_value')
                            if '>' in category_name:
                                category_name = category_name.split('>')[-1].strip()
                            if category_name not in category_names:
                                category_names.append(category_name)
                            matched_predicates.append(category_prop.canonical_uri)
                            break
            card['categories'] = category_names

        if event_subject_ids and (event_start_prop or event_end_prop):
            for event_id in event_subject_ids:
                event_edges = [e for e in all_edges if e.get('subject_id') == event_id]
                event_start = None
                event_end = None
                for event_edge in event_edges:
                    event_canonical = event_edge.get('predicate_canonical') or event_edge.get('predicate_uri')
                    if event_start_prop and event_canonical == event_start_prop.canonical_uri and event_edge.get('object_value'):
                        event_start = event_edge['object_value']
                    elif event_end_prop and event_canonical == event_end_prop.canonical_uri and event_edge.get('object_value'):
                        event_end = event_edge['object_value']

                if event_start and event_end:
                    start_year = event_start.split('-')[0] if '-' in event_start else event_start
                    end_year = event_end.split('-')[0] if '-' in event_end else event_end
                    card['year_range'] = start_year if start_year == end_year else f"{start_year} bis {end_year}"
                elif event_start:
                    card['year_range'] = event_start.split('-')[0] if '-' in event_start else event_start
                elif event_end:
                    card['year_range'] = event_end.split('-')[0] if '-' in event_end else event_end

                if event_prop and (event_start or event_end):
                    matched_predicates.append(event_prop.canonical_uri)
                if card['year_range']:
                    break

        actors_by_name: Dict[str, set] = {}
        if event_subject_ids and actor_link_prop and role_link_prop and actor_name_prop:
            candidate_crosstable_ids = {
                edge.get('subject_id')
                for edge in all_edges
                if (edge.get('predicate_canonical') or edge.get('predicate_uri')) == actor_link_prop.canonical_uri
                and edge.get('subject_id')
            }

            crosstable_ids: List[str] = []
            for candidate in candidate_crosstable_ids:
                if not candidate:
                    continue
                has_event_link = any(
                    (edge.get('subject_id') == candidate)
                    and edge.get('object_id') in event_subject_ids
                    for edge in all_edges
                )
                if has_event_link:
                    crosstable_ids.append(candidate)

            for crosstable_id in crosstable_ids:
                actor_id: Optional[str] = None
                role_ids: List[str] = []

                for edge in all_edges:
                    if edge.get('subject_id') != crosstable_id:
                        continue
                    canonical_uri = edge.get('predicate_canonical') or edge.get('predicate_uri')
                    if canonical_uri == actor_link_prop.canonical_uri and edge.get('object_id'):
                        actor_id = edge['object_id']
                        matched_predicates.append(actor_link_prop.canonical_uri)
                    elif canonical_uri == role_link_prop.canonical_uri and edge.get('object_id'):
                        role_ids.append(edge['object_id'])
                        matched_predicates.append(role_link_prop.canonical_uri)

                actor_name: Optional[str] = None
                if actor_id:
                    for edge in all_edges:
                        if edge.get('subject_id') != actor_id:
                            continue
                        canonical_uri = edge.get('predicate_canonical') or edge.get('predicate_uri')
                        if canonical_uri == actor_name_prop.canonical_uri and edge.get('object_value'):
                            actor_name = edge['object_value']
                            break

                role_names: List[str] = []
                if role_name_prop:
                    for role_id in role_ids:
                        for edge in all_edges:
                            if edge.get('subject_id') != role_id:
                                continue
                            canonical_uri = edge.get('predicate_canonical') or edge.get('predicate_uri')
                            if canonical_uri == role_name_prop.canonical_uri and edge.get('object_value'):
                                role_name = edge.get('object_value')
                                if '>' in role_name:
                                    role_name = role_name.split('>')[-1].strip()
                                role_names.append(role_name)
                                break

                if actor_name:
                    actors_by_name.setdefault(actor_name, set()).update(role_names)

        if actors_by_name:
            sorted_actors = sorted(actors_by_name.items(), key=lambda item: item[0])
            for index, (actor_name, roles) in enumerate(sorted_actors[:4]):
                card[f'contributor{index + 1}_name'] = actor_name
                if roles:
                    card[f'contributor{index + 1}_role'] = ', '.join(sorted(roles))
            if len(sorted_actors) > 4:
                card['additional_contributors'] = f"{len(sorted_actors) - 4} weitere"

        if matched_predicates:
            logger.debug(
                "Subject %s matched card predicates: %s",
                subject_id,
                sorted(set(matched_predicates))
            )

        person_like_edges = []
        for edge in subject_edges:
            canonical_uri = edge.get('predicate_canonical') or edge.get('predicate_uri')
            if not canonical_uri:
                continue
            if canonical_uri not in handled_canonical_uris:
                normalized = canonical_uri.lower()
                if any(keyword in normalized for keyword in ("person", "akteur", "actor", "creator", "autor", "künstler")):
                    person_like_edges.append({
                        'predicate': canonical_uri,
                        'object_id': edge.get('object_id'),
                        'object_value': edge.get('object_value')
                    })

        if person_like_edges:
            logger.info(
                "Subject %s has unhandled actor/creator predicates: %s",
                subject_id,
                person_like_edges[:5]
            )

        return card if card['title'] else None

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
