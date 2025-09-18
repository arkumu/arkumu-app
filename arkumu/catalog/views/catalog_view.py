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
from typing import Dict, List, Any, Optional, Set, Sequence

from arkumu.metadata.services.canonical_graph_service import CanonicalGraphService
from arkumu.cache.services import CacheManager
from arkumu.catalog.services.schema_manifest_service import (
    SchemaManifestService,
    CARD_SCHEMA_TEMPLATE,
    CardSchema,
    CardProperty,
)
from arkumu.catalog.services.triple_relationship_service import TripleRelationshipService
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
            # IMPORTANT: Always use FUK organization for schema manifest
            # because only FUK, RSH, and DET have proper canonical URIs
            # KHM and HMT have organization-specific URIs that don't match our canonical expectations
            schema_org_code = 'fuk'
            logger.info(f"📋 SCHEMA_OVERRIDE: Using '{schema_org_code}' organization for schema manifest (user org: {org_code})")
            card_schema = self.schema_manifest_service.get_card_schema(schema_org_code)

            # For HTMX requests without query, return empty results immediately
            if is_htmx and not query:
                logger.info("🚀 FAST_PATH: Empty HTMX request, returning empty results")
                return self.build_empty_search_response(request, query)

            # Only load projects when there's a search query
            if query:
                projects = self._get_all_projects(org_code, query, card_schema, request, relationship_org_code=None)
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

            # Enrich paginated cards with all relationship data (lazy loading)
            enriched_cards = self._enrich_cards_with_relationships(
                list(page_obj.object_list),
                card_schema,
                relationship_org_code=None  # Cross-institutional: no org filtering
            )
            # Replace the page object list with enriched cards
            page_obj.object_list = enriched_cards

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
        card_schema: Optional[CardSchema] = None,
        request = None,
        relationship_org_code: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get projects using proper cache architecture: catalog cache first, then graph cache."""
        cache_manager = CacheManager()

        # For searches, check catalog cache first (skip cache if debug param present)
        skip_cache = request and request.GET.get('nocache') == '1'
        if query and not skip_cache:
            cached_search = cache_manager.catalog.get_cached_search_results(
                query=query,
                property_name="cross_institutional_search",
                selected_class="projekt",
                user_org="global"
            )

            if cached_search and cached_search.get('results'):
                logger.info(f"✅ CATALOG_CACHE_HIT: Using cached search results for '{query}'")
                entities = cached_search['results'].get('entities', [])

                # Debug: Check what's in the cached data
                if entities:
                    first_entity = entities[0]
                    logger.info(f"🔍 CACHED_DATA_SAMPLE: First entity keys: {list(first_entity.keys())}")
                    if 'title' in first_entity:
                        logger.info(f"🔍 CACHED_DATA_SAMPLE: Title: '{first_entity['title']}'")
                    if 'institution' in first_entity:
                        logger.info(f"🔍 CACHED_DATA_SAMPLE: Institution: '{first_entity['institution']}'")
                    if 'categories' in first_entity:
                        logger.info(f"🔍 CACHED_DATA_SAMPLE: Categories: {first_entity['categories']}")

                return entities
        elif skip_cache:
            logger.info(f"🔄 CACHE_BYPASS: Skipping cache for '{query}' due to nocache=1 parameter")

        # Cache miss - need to get data from graph cache or fetch fresh
        cache_resource_uri = "arkumu:cross_institutional:all_projects"
        cache_params_hash = "cross_institutional_projects_canonical"

        # Try graph cache first (shared with OAI-PMH) - skip if nocache parameter
        cached_graph = None
        if not skip_cache:
            cached_graph = cache_manager.graph.get_traversal_result(
                resource_uri=cache_resource_uri,
                traversal_type="catalog_projects",
                params_hash=cache_params_hash
            )
        elif skip_cache:
            logger.info(f"🔄 GRAPH_CACHE_BYPASS: Skipping graph cache due to nocache=1 parameter")

        if cached_graph and cached_graph.get('result') and cached_graph['result'].get('projects'):
            logger.info(f"✅ GRAPH_CACHE_HIT: Using cached {len(cached_graph['result']['projects'])} projects")
            all_projects = cached_graph['result']['projects']

            # Debug: Check what's in the cached cards
            if all_projects:
                sample_card = all_projects[0]
                logger.info(f"🔍 CACHED_CARD_SAMPLE: Keys: {list(sample_card.keys())}")
                logger.info(f"🔍 CACHED_CARD_SAMPLE: Title: '{sample_card.get('title', 'NO_TITLE')}'")
                logger.info(f"🔍 CACHED_CARD_SAMPLE: Institution: '{sample_card.get('institution', 'NO_INSTITUTION')}'")
                logger.info(f"🔍 CACHED_CARD_SAMPLE: Categories: {sample_card.get('categories', 'NO_CATEGORIES')}")
                logger.info(f"🔍 CACHED_CARD_SAMPLE: URI: {sample_card.get('uri', 'NO_URI')}")
        else:
            # Final fallback - fetch fresh data
            logger.info(f"🔄 FRESH_FETCH: Getting fresh cross-institutional project data")
            all_projects = self._fetch_projects_from_graph(
                org_code,
                card_schema,
                relationship_org_code,
            )

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
        card_schema: Optional[CardSchema] = None,
        relationship_org_code: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch projects from graph service."""
        graph = self._fetch_fresh_graph(org_code)

        if graph:
            return self._graph_to_cards(graph, card_schema, relationship_org_code)

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
        card_schema: Optional[CardSchema] = None,
        relationship_org_code: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Convert graph data to card format without actor processing (for performance)."""
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

                card_data = self._extract_card_from_graph(
                    subject_id,
                    subject_edges,
                    edges,
                    schema,
                    edges_by_subject,
                    relationship_org_code=relationship_org_code,
                    skip_relationships=True,  # Skip all relationship processing for performance
                )
                if card_data:
                    cards.append(card_data)
                elif i == 0:  # Log why first card failed
                    logger.info(f"DEBUG: First card failed extraction for subject {subject_id}")

        # Format cards for template (convert categories list to category1, category2, etc.)
        formatted_cards = []
        for card in cards:
            # Format categories
            categories = card.get('categories', [])
            for i, category in enumerate(categories[:4]):
                card[f"category{i+1}"] = category
            if len(categories) > 4:
                card["additional_categories"] = f"{len(categories)-4} weitere"

            formatted_cards.append(card)

        logger.info(f"Converted graph to {len(formatted_cards)} cards")
        return formatted_cards



    def _extract_card_from_graph(
        self,
        subject_id: str,
        subject_edges: List[Dict],
        all_edges: List[Dict],
        card_schema: CardSchema,
        edges_by_subject: Dict[str, List[Dict]],
        *,
        relationship_org_code: Optional[str] = None,
        skip_relationships: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Extract card data from graph edges for a specific subject."""

        if not hasattr(self, '_logged_first_subject'):
            self._logged_first_subject = True
            logger.info(f"🔍 CARD_EXTRACTION: Processing first subject {subject_id} with {len(subject_edges)} edges")
            logger.info(f"🔍 CARD_SCHEMA: Available sections: {list(card_schema.sections.keys())}")

            for section_name, section in card_schema.sections.items():
                if section.available:
                    logger.info(f"  ✅ Section '{section_name}' is available with properties:")
                    for prop_name, prop in section.properties.items():
                        binding = prop.bindings[0] if prop.bindings else None
                        if binding and binding.dataset and binding.column:
                            binding_info = f"{binding.dataset}.{binding.column}"
                        else:
                            binding_info = "NO BINDINGS"
                        logger.info(f"    - {prop_name}: {prop.canonical_uri} -> {binding_info}")

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
        digital_object_path_prop = _property('digital_object', 'path')

        handled_canonical_uris = {
            prop.canonical_uri
            for section in card_schema.sections.values()
            for prop in section.properties.values()
            if prop.canonical_uri
        }

        matched_predicates: Set[str] = set()

        card = {
            'uri': subject_id,
            'title': '',
            'subtitle': '',
            'image': 'images/main/card_1.png',
            'institution': '',
            'categories': [],
            'year_range': '',
            'digital_objects': []
        }

        if not hasattr(self, '_logged_edge_processing'):
            self._logged_edge_processing = True
            logger.info(f"🔍 EDGE_PROCESSING: Checking {len(subject_edges)} edges for properties")
            sample_edge_uris = [edge.get('predicate_canonical') or edge.get('predicate_uri') for edge in subject_edges[:5]]
            logger.info(f"  Sample edge URIs: {sample_edge_uris}")

        for edge in subject_edges:
            canonical_uri = edge.get('predicate_canonical') or edge.get('predicate_uri')
            if not canonical_uri:
                continue
            if title_prop and canonical_uri == title_prop.canonical_uri and edge.get('object_value'):
                card['title'] = edge['object_value']
                matched_predicates.add(title_prop.canonical_uri)
                if not hasattr(self, '_logged_title_found'):
                    self._logged_title_found = True
                    logger.info(f"✅ TITLE_FOUND: Found title for {subject_id}: {edge['object_value']}")
            elif subtitle_prop and canonical_uri == subtitle_prop.canonical_uri and edge.get('object_value'):
                card['subtitle'] = edge['object_value']
                matched_predicates.add(subtitle_prop.canonical_uri)
            elif image_prop and canonical_uri == image_prop.canonical_uri and edge.get('object_value'):
                card['image'] = edge['object_value']
                matched_predicates.add(image_prop.canonical_uri)

        def _fk_source_for_target(section_name: str, target_property: Optional[str]) -> Optional[str]:
            if not target_property:
                return None
            section = card_schema.sections.get(section_name)
            if not section or not section.fk_relationships:
                return None
            for fk_rel in section.fk_relationships:
                if fk_rel.get('target_property') == target_property:
                    return fk_rel.get('source_property')
            return None

        # Initialize default values
        institution_label = None
        category_labels = []
        event_info = {'event_ids': [], 'event_details': {}}
        actors = []
        digital_object_paths = []

        if not skip_relationships:
            triple_service = TripleRelationshipService(relationship_org_code)

            logger.info(f"🔧 TRIPLE_SERVICE: Created for org {relationship_org_code}, processing subject {subject_id}")
            logger.info(f"🔧 CANONICAL_URIS: event={event_prop.canonical_uri if event_prop else None}, actor_link={actor_link_prop.canonical_uri if actor_link_prop else None}, actor_name={actor_name_prop.canonical_uri if actor_name_prop else None}")

            institution_label = triple_service.get_institution_data(
                subject_id,
                institution_predicate=institution_prop.canonical_uri if institution_prop else None,
                institution_label_predicate=institution_name_prop.canonical_uri if institution_name_prop else None,
                organization_code=relationship_org_code,
            )
            logger.info(f"🏛️ INSTITUTION: Got '{institution_label}' for {subject_id}")

            category_labels = triple_service.get_category_data(
                subject_id,
                category_predicate=category_prop.canonical_uri if category_prop else None,
                category_label_predicate=category_name_prop.canonical_uri if category_name_prop else None,
                organization_code=relationship_org_code,
            )

            event_info = triple_service.get_event_data(
                subject_id,
                event_predicate=event_prop.canonical_uri if event_prop else None,
                event_start_predicate=event_start_prop.canonical_uri if event_start_prop else None,
                event_end_predicate=event_end_prop.canonical_uri if event_end_prop else None,
                organization_code=relationship_org_code,
            )

            actors = triple_service.get_actor_relationships(
                subject_id,
                event_predicate=event_prop.canonical_uri if event_prop else None,
                actor_link_predicate=actor_link_prop.canonical_uri if actor_link_prop else None,
                role_link_predicate=role_link_prop.canonical_uri if role_link_prop else None,
                actor_name_predicate=actor_name_prop.canonical_uri if actor_name_prop else None,
                role_name_predicate=role_name_prop.canonical_uri if role_name_prop else None,
                event_ids=event_info.get('event_ids'),
                organization_code=relationship_org_code,
            )
            logger.info(f"🎭 ACTORS: Found {len(actors)} actors for {subject_id}")
            for i, actor in enumerate(actors[:3]):
                logger.info(f"  Actor {i+1}: {actor.get('name')} - roles: {actor.get('roles')}")

            digital_object_link_predicate = _fk_source_for_target(
                'project',
                digital_object_path_prop.canonical_uri if digital_object_path_prop else None,
            )

            digital_object_paths = triple_service.get_digital_object_paths(
                subject_id,
                link_predicate=digital_object_link_predicate,
                path_predicate=digital_object_path_prop.canonical_uri if digital_object_path_prop else None,
                organization_code=relationship_org_code,
            )

        if institution_label:
            card['institution'] = institution_label
            if institution_name_prop and institution_name_prop.canonical_uri:
                matched_predicates.add(institution_name_prop.canonical_uri)

        if category_labels:
            card['categories'] = category_labels
            if category_name_prop and category_name_prop.canonical_uri:
                matched_predicates.add(category_name_prop.canonical_uri)

        event_ids = event_info.get('event_ids', [])
        event_details = event_info.get('event_details', {})
        if event_ids:
            year_range = self._derive_year_range_from_events(event_ids, event_details)
            if year_range:
                card['year_range'] = year_range
                if event_prop and event_prop.canonical_uri:
                    matched_predicates.add(event_prop.canonical_uri)

            if event_start_prop and event_start_prop.canonical_uri:
                if any((event_details.get(event_id, {}).get('start') for event_id in event_ids)):
                    matched_predicates.add(event_start_prop.canonical_uri)
            if event_end_prop and event_end_prop.canonical_uri:
                if any((event_details.get(event_id, {}).get('end') for event_id in event_ids)):
                    matched_predicates.add(event_end_prop.canonical_uri)

        if actors:
            for index, actor in enumerate(actors[:4]):
                card[f'contributor{index + 1}_name'] = actor['name']
                if actor['roles']:
                    card[f'contributor{index + 1}_role'] = ', '.join(actor['roles'])
            if len(actors) > 4:
                card['additional_contributors'] = f"{len(actors) - 4} weitere"
            if actor_name_prop and actor_name_prop.canonical_uri:
                matched_predicates.add(actor_name_prop.canonical_uri)
            if role_name_prop and role_name_prop.canonical_uri and any(actor['roles'] for actor in actors):
                matched_predicates.add(role_name_prop.canonical_uri)

        if digital_object_paths:
            card['digital_objects'] = digital_object_paths
            if card['digital_objects'] and card['image'] == 'images/main/card_1.png':
                card['image'] = card['digital_objects'][0]
            if digital_object_path_prop and digital_object_path_prop.canonical_uri:
                matched_predicates.add(digital_object_path_prop.canonical_uri)

        if matched_predicates:
            logger.debug(
                "Subject %s matched card predicates: %s",
                subject_id,
                sorted(matched_predicates)
            )

        def get_canonical(edge: Dict[str, Any]) -> Optional[str]:
            return edge.get('predicate_canonical') or edge.get('predicate_uri')

        person_like_edges = []
        for edge in subject_edges:
            canonical_uri = get_canonical(edge)
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

    def _enrich_cards_with_relationships(
        self,
        cards: List[Dict[str, Any]],
        card_schema: Optional[CardSchema] = None,
        relationship_org_code: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Add all relationship data to cards for display (lazy loading)."""
        if not cards:
            return cards

        schema = card_schema or copy.deepcopy(CARD_SCHEMA_TEMPLATE)
        triple_service = TripleRelationshipService(relationship_org_code)

        # Get property definitions
        def _property(section: str, prop: str) -> Optional[CardProperty]:
            section_obj = schema.sections.get(section)
            if not section_obj:
                return None
            return section_obj.properties.get(prop)

        # All relationship properties
        institution_prop = _property('project', 'institution')
        institution_name_prop = _property('institution', 'german_name')
        category_prop = _property('project', 'category')
        category_name_prop = _property('project_category', 'german_name')
        event_prop = _property('project', 'event')
        event_start_prop = _property('event', 'start')
        event_end_prop = _property('event', 'end')
        actor_link_prop = _property('actor_event', 'actor_link')
        role_link_prop = _property('actor_event', 'role_link')
        actor_name_prop = _property('actor', 'name')
        role_name_prop = _property('role', 'name')
        digital_object_path_prop = _property('digital_object', 'path')

        logger.info(f"🔗 ENRICHING: Processing all relationships for {len(cards)} cards")

        for card in cards:
            subject_id = card.get('uri')
            if not subject_id:
                continue

            # Get institution data
            institution_label = triple_service.get_institution_data(
                subject_id,
                institution_predicate=institution_prop.canonical_uri if institution_prop else None,
                institution_label_predicate=institution_name_prop.canonical_uri if institution_name_prop else None,
                organization_code=relationship_org_code,
            )
            if institution_label:
                card['institution'] = institution_label

            # Get category data
            category_labels = triple_service.get_category_data(
                subject_id,
                category_predicate=category_prop.canonical_uri if category_prop else None,
                category_label_predicate=category_name_prop.canonical_uri if category_name_prop else None,
                organization_code=relationship_org_code,
            )
            if category_labels:
                card['categories'] = category_labels
                # Format categories for template
                for i, category in enumerate(category_labels[:4]):
                    card[f"category{i+1}"] = category
                if len(category_labels) > 4:
                    card["additional_categories"] = f"{len(category_labels)-4} weitere"

            # Get event data
            event_info = triple_service.get_event_data(
                subject_id,
                event_predicate=event_prop.canonical_uri if event_prop else None,
                event_start_predicate=event_start_prop.canonical_uri if event_start_prop else None,
                event_end_predicate=event_end_prop.canonical_uri if event_end_prop else None,
                organization_code=relationship_org_code,
            )
            event_ids = event_info.get('event_ids', [])
            event_details = event_info.get('event_details', {})
            if event_ids:
                year_range = self._derive_year_range_from_events(event_ids, event_details)
                if year_range:
                    card['year_range'] = year_range

            # Get actor data
            actors = triple_service.get_actor_relationships(
                subject_id,
                event_predicate=event_prop.canonical_uri if event_prop else None,
                actor_link_predicate=actor_link_prop.canonical_uri if actor_link_prop else None,
                role_link_predicate=role_link_prop.canonical_uri if role_link_prop else None,
                actor_name_predicate=actor_name_prop.canonical_uri if actor_name_prop else None,
                role_name_predicate=role_name_prop.canonical_uri if role_name_prop else None,
                event_ids=event_ids,
                organization_code=relationship_org_code,
            )
            if actors:
                for index, actor in enumerate(actors[:4]):
                    card[f'contributor{index + 1}_name'] = actor['name']
                    if actor['roles']:
                        card[f'contributor{index + 1}_role'] = ', '.join(actor['roles'])
                if len(actors) > 4:
                    card['additional_contributors'] = f"{len(actors) - 4} weitere"

            # Get digital object paths
            def _fk_source_for_target(section_name: str, target_property: Optional[str]) -> Optional[str]:
                if not target_property:
                    return None
                section = schema.sections.get(section_name)
                if not section or not section.fk_relationships:
                    return None
                for fk_rel in section.fk_relationships:
                    if fk_rel.get('target_property') == target_property:
                        return fk_rel.get('source_property')
                return None

            digital_object_link_predicate = _fk_source_for_target(
                'project',
                digital_object_path_prop.canonical_uri if digital_object_path_prop else None,
            )
            digital_object_paths = triple_service.get_digital_object_paths(
                subject_id,
                link_predicate=digital_object_link_predicate,
                path_predicate=digital_object_path_prop.canonical_uri if digital_object_path_prop else None,
                organization_code=relationship_org_code,
            )
            if digital_object_paths:
                card['digital_objects'] = digital_object_paths
                if card['digital_objects'] and card.get('image') == 'images/main/card_1.png':
                    card['image'] = card['digital_objects'][0]

        logger.info(f"🔗 ENRICHED: Added all relationship data to {len(cards)} cards")
        return cards

    @staticmethod
    def _derive_year_range_from_events(
        event_ids: Sequence[str],
        event_details: Dict[str, Dict[str, Optional[str]]],
    ) -> str:
        for event_id in event_ids:
            entry = event_details.get(event_id) or {}
            start = entry.get('start')
            end = entry.get('end')
            if start and end:
                start_year = start.split('-')[0] if '-' in start else start
                end_year = end.split('-')[0] if '-' in end else end
                return start_year if start_year == end_year else f"{start_year} bis {end_year}"
            if start:
                return start.split('-')[0] if '-' in start else start
            if end:
                return end.split('-')[0] if '-' in end else end
        return ''


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
