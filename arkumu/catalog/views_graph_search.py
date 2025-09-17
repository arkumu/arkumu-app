"""
Graph-based search views using CanonicalGraphService with canonical URIs.
"""

from django.views.generic import View
from django.shortcuts import render
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
import logging
from typing import Dict, List, Any

from arkumu.metadata.services.canonical_graph_service import CanonicalGraphService
from arkumu.cache.services.graph_cache_service import GraphCacheService

logger = logging.getLogger(__name__)


class GraphSearchView(LoginRequiredMixin, View):
    """Search using CanonicalGraphService with canonical URIs."""

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
            # Initialize cache and graph services
            cache_service = GraphCacheService()

            # Create cache key for cross-institutional search (same as design view)
            cache_resource_uri = "arkumu:cross_institutional:all_projects"
            cache_params_hash = "cross_institutional_projects_canonical"

            # Try to get cached project graph
            cached_result = cache_service.get_traversal_result(
                resource_uri=cache_resource_uri,
                traversal_type="catalog_search",
                params_hash=cache_params_hash
            )

            if cached_result:
                logger.info(f"Using cached project graph for org {org_code}")
                graph = cached_result.get('result')
            else:
                logger.info(f"Fetching whole graph for cross-institutional search")

                # Don't specify org_code for cross-institutional search
                service = CanonicalGraphService()  # No org = search all institutions

                # Use CANONICAL URI to get all projects across institutions
                canonical_project_uri = "http://arkumu.org/data/types/projekt"

                # First try canonical URI
                # Service has no org, so it searches all institutions by default
                all_subject_ids = service._find_subject_ids_by_class(
                    canonical_project_uri
                )
                logger.info(f"Found {len(all_subject_ids)} projects using canonical URI")

                # Fallback to institution-specific URIs if needed
                if not all_subject_ids:
                    logger.info("No projects via canonical URI, falling back to institution-specific")
                    institution_uris = [
                        "http://arkumu.org/data/fuk/types/projekt",
                        "http://arkumu.org/data/rsh/types/projekt",
                        "http://arkumu.org/data/det/types/projekt",
                        "http://arkumu.org/data/khm/types/projekt",
                        "http://arkumu.org/data/uk/types/projekt",
                        "http://arkumu.org/data/hfmt/types/projekt",
                    ]
                    for uri in institution_uris:
                        subject_ids = service._find_subject_ids_by_class(uri)
                        all_subject_ids.extend(subject_ids)
                        logger.info(f"Found {len(subject_ids)} subjects for {uri}")

                logger.info(f"Total subjects across all institutions: {len(all_subject_ids)}")

                # Get the whole graph for all these subjects
                edges = service._fetch_triples_for_subjects(all_subject_ids)

                if edges:
                    # Get neighbor expansion if needed
                    neighbor_ids = [e.object_id for e in edges if e.object_type != 'LITERAL'][:100]  # Limit neighbors
                    if neighbor_ids:
                        neighbor_edges = service._fetch_triples_for_subjects(neighbor_ids)
                        edges.extend(neighbor_edges)

                # Collect all nodes
                nodes = service._collect_nodes_from_edges(edges)

                # Build complete graph
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

                logger.info(f"Built whole graph: {graph['counts']['subjects']} projects, {graph['counts']['edges']} edges")

                # Cache the result for next time (same key as design view)
                cache_service.cache_traversal_result(
                    resource_uri=cache_resource_uri,
                    traversal_type="catalog_search",
                    params_hash=cache_params_hash,
                    result_data=graph
                )

            logger.info(f"Graph service returned {graph['counts']['subjects']} projects")

            # Store graph for traversal methods
            self.current_graph = graph

            # Convert graph to card data
            projects = self._graph_to_cards(graph, query)

            # Filter by search query if provided
            if query:
                projects = self._filter_projects_by_query(projects, query)

            logger.info(f"After filtering: {len(projects)} projects match query '{query}'")

            context = {
                'query': query,
                'results': projects,
                'total_results': len(projects)
            }

            return render(request, 'catalog/card_grid_template.html', context)

        except Exception as e:
            logger.error(f"Graph search error: {e}")
            return self._render_empty_results(request, query, f"Search error: {str(e)}")

    def _render_empty_results(self, request, query: str, error: str = None):
        """Render empty results template."""
        context = {
            'query': query,
            'results': [],
            'error': error
        }
        return render(request, 'catalog/card_grid_template.html', context)

    def _graph_to_cards(self, graph: Dict[str, Any], query: str = None) -> List[Dict[str, Any]]:
        """Convert graph data to card component format using canonical URIs."""
        cards = []
        nodes = graph.get('nodes', {})
        edges = graph.get('edges', [])

        # Group edges by subject (project)
        projects = {}
        for edge in edges:
            subject_id = edge['subject_id']
            if subject_id not in projects:
                projects[subject_id] = {
                    'id': subject_id,
                    'properties': {}
                }

            predicate_canonical = edge.get('predicate_canonical') or edge['predicate_uri']
            projects[subject_id]['properties'][predicate_canonical] = {
                'object_id': edge['object_id'],
                'object_value': edge.get('object_value'),
                'object_uri': edge.get('object_uri'),
                'object_type': edge['object_type']
            }

        # Convert each project to card format
        for project_id, project_data in projects.items():
            card = self._project_to_card(project_id, project_data, nodes)
            if card:
                cards.append(card)

        return cards

    def _project_to_card(self, project_id: str, project_data: Dict, nodes: Dict) -> Dict[str, Any]:
        """Convert a single project to card format using canonical URIs from specification."""
        props = project_data['properties']
        edges = self.current_graph.get('edges', [])  # Store current graph for traversal

        # Extract basic project info using canonical URIs
        card = {
            "uri": nodes.get(project_id, {}).get('uri', ''),
            "title": self._get_property_value(props, "http://arkumu.org/data/properties/bevorzugter-titel"),
            "subtitle": self._get_property_value(props, "http://arkumu.org/data/properties/bevorzugter-untertitel"),
            "image": self._get_property_value(props, "http://arkumu.org/data/properties/vorschaubild") or "images/main/card_1.png",
            "button_text": "Projekt ansehen",
            "year": "",
            "institution": "",
            "categories": [],
            "actors": {}
        }

        # Get event and extract date range
        event_prop = props.get("http://arkumu.org/data/properties/ereignis")
        if event_prop:
            card["year"] = self._get_event_date_range(event_prop['object_id'], edges, nodes)

        # Get institution and its German name
        institution_prop = props.get("http://arkumu.org/data/properties/einliefernde-hochschule")
        if institution_prop:
            card["institution"] = self._get_institution_german_name(institution_prop['object_id'], edges, nodes)

        # Get categories and their German names
        category_props = [v for k, v in props.items() if k == "http://arkumu.org/data/properties/projektkategorie"]
        categories = []
        for cat_prop in category_props:
            cat_name = self._get_category_german_name(cat_prop['object_id'], edges, nodes)
            if cat_name:
                categories.append(cat_name)
        card["categories"] = categories

        # Get actors from events (complex traversal)
        if event_prop:
            actors_dict = self._get_actors_from_event(event_prop['object_id'], edges, nodes)
            # Format actors for card template (contributor1_name, contributor1_role, etc.)
            for i, (actor_name, roles) in enumerate(list(actors_dict.items())[:4]):
                card[f"contributor{i+1}_name"] = actor_name
                card[f"contributor{i+1}_role"] = ", ".join(roles) if roles else ""

            if len(actors_dict) > 4:
                card["additional_contributors"] = f"{len(actors_dict)-4} weitere"

        # Format categories for card template (category1, category2, etc.)
        for i, category in enumerate(categories[:4]):
            card[f"category{i+1}"] = category

        if len(categories) > 4:
            card["additional_categories"] = f"{len(categories)-4} weitere"

        return card

    def _get_property_value(self, props: Dict, canonical_uri: str) -> str:
        """Get property value by canonical URI."""
        prop = props.get(canonical_uri)
        if prop and prop['object_value']:
            return prop['object_value']
        return ""

    def _get_event_date_range(self, event_id: str, edges: List, nodes: Dict) -> str:
        """Get date range from event using canonical URIs."""
        start_date = None
        end_date = None

        # Find start and end dates for this event
        for edge in edges:
            if (edge['subject_id'] == event_id and
                edge.get('predicate_canonical') == "http://arkumu.org/data/properties/ereignisbeginn"):
                start_date = edge.get('object_value')
            elif (edge['subject_id'] == event_id and
                  edge.get('predicate_canonical') == "http://arkumu.org/data/properties/ereignisende"):
                end_date = edge.get('object_value')

        # Format date range
        if start_date and end_date:
            start_year = start_date.split('-')[0] if '-' in start_date else start_date
            end_year = end_date.split('-')[0] if '-' in end_date else end_date
            if start_year == end_year:
                return start_year
            return f"{start_year} bis {end_year}"
        elif start_date:
            return start_date.split('-')[0] if '-' in start_date else start_date
        elif end_date:
            return end_date.split('-')[0] if '-' in end_date else end_date

        return ""

    def _get_institution_german_name(self, institution_id: str, edges: List, nodes: Dict) -> str:
        """Get German name of institution using canonical URIs."""
        # class institution http://arkumu.org/data/types/einliefernde-hochschule:
        #     german name: http://arkumu.org/data/properties/deutscher-name-der-einliefernden-hochschule

        for edge in edges:
            if (edge['subject_id'] == institution_id and
                edge.get('predicate_canonical') == "http://arkumu.org/data/properties/deutscher-name-der-einliefernden-hochschule"):
                return edge.get('object_value', '')

        return ""

    def _get_category_german_name(self, category_id: str, edges: List, nodes: Dict) -> str:
        """Get German name of category using canonical URIs."""
        # class project-category http://arkumu.org/data/types/projektkategorie:
        #     german name: http://arkumu.org/data/properties/deutscher-name-der-projektkategorie-breadcrumb

        for edge in edges:
            if (edge['subject_id'] == category_id and
                edge.get('predicate_canonical') == "http://arkumu.org/data/properties/deutscher-name-der-projektkategorie-breadcrumb"):
                breadcrumb = edge.get('object_value', '')
                # Extract last part of breadcrumb (after last '>')
                if '>' in breadcrumb:
                    return breadcrumb.split('>')[-1].strip()
                return breadcrumb

        return ""

    def _get_actors_from_event(self, event_id: str, edges: List, nodes: Dict) -> Dict[str, List[str]]:
        """Get actors and their roles from event using canonical URIs."""
        # Complex traversal:
        # event -> actor-event-crosstable -> actor + roles
        actors = {}

        # Find all actor-event cross-table entries for this event
        crosstable_ids = []
        for edge in edges:
            if (edge['object_id'] == event_id and
                edge.get('predicate_canonical') in [
                    "http://arkumu.org/data/properties/ereignis",
                    "im-ereignis"  # might have different canonical form
                ]):
                crosstable_ids.append(edge['subject_id'])

        # For each crosstable entry, get actor and roles
        for crosstable_id in crosstable_ids:
            actor_id = None
            role_ids = []

            # Find actor and roles from crosstable
            for edge in edges:
                if edge['subject_id'] == crosstable_id:
                    if edge.get('predicate_canonical') == "http://arkumu.org/data/properties/akteurin-im-ereignis":
                        actor_id = edge['object_id']
                    elif edge.get('predicate_canonical') == "http://arkumu.org/data/properties/rollen-der-akteurin-im-ereignis":
                        role_ids.append(edge['object_id'])

            # Get actor German name
            if actor_id:
                actor_name = self._get_actor_german_name(actor_id, edges, nodes)
                if actor_name:
                    # Get role German names
                    role_names = [self._get_role_german_name(role_id, edges, nodes) for role_id in role_ids]
                    role_names = [name for name in role_names if name]  # Filter empty names
                    actors[actor_name] = role_names

        return actors

    def _get_actor_german_name(self, actor_id: str, edges: List, nodes: Dict) -> str:
        """Get German name of actor using canonical URIs."""
        # class actor http://arkumu.org/data/types/akteurin :
        #     german name: http://arkumu.org/data/properties/deutscher-name

        for edge in edges:
            if (edge['subject_id'] == actor_id and
                edge.get('predicate_canonical') == "http://arkumu.org/data/properties/deutscher-name"):
                return edge.get('object_value', '')

        return ""

    def _get_role_german_name(self, role_id: str, edges: List, nodes: Dict) -> str:
        """Get German name of role using canonical URIs."""
        # class role http://arkumu.org/data/types/rolle :
        #     german name: http://arkumu.org/data/properties/deutscher-name-der-rolle-breadcrumb

        for edge in edges:
            if (edge['subject_id'] == role_id and
                edge.get('predicate_canonical') == "http://arkumu.org/data/properties/deutscher-name-der-rolle-breadcrumb"):
                breadcrumb = edge.get('object_value', '')
                # Extract last part of breadcrumb (after last '>')
                if '>' in breadcrumb:
                    return breadcrumb.split('>')[-1].strip()
                return breadcrumb

        return ""

    def _filter_projects_by_query(self, projects: List[Dict], query: str) -> List[Dict]:
        """Filter projects by search query (simple text matching)."""
        if not query:
            return projects

        query_lower = query.lower()
        filtered = []

        for project in projects:
            # Search in title, subtitle, institution, categories
            searchable_text = " ".join([
                project.get('title', ''),
                project.get('subtitle', ''),
                project.get('institution', ''),
                " ".join(project.get('categories', []))
            ]).lower()

            if query_lower in searchable_text:
                filtered.append(project)

        return filtered