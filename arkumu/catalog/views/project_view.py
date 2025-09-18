"""
Project detail view using canonical URIs.
"""

from django.views.generic import View
from django.shortcuts import render
from django.contrib.auth.mixins import LoginRequiredMixin
import logging

from arkumu.catalog.services.project_views import ProjectData
from arkumu.cache.services import CacheManager

logger = logging.getLogger(__name__)


class ProjectView(LoginRequiredMixin, View):
    """Project detail view using canonical URIs."""

    def get(self, request, *args, **kwargs):
        """Display project detail page."""
        logger.info(f"🔍 ProjectView.get() called - URL: {request.get_full_path()}")
        logger.info(f"🔍 Request method: {request.method}")
        logger.info(f"🔍 GET parameters: {dict(request.GET)}")
        logger.info(f"🔍 URL kwargs: {kwargs}")

        projekt_uri = request.GET.get('projekt')

        if not projekt_uri:
            logger.error("❌ No project URI provided in request")
            return render(request, 'catalog/design_error.html', {
                'error': 'No project URI provided'
            })

        logger.info(f"✅ ProjectView - Project URI: {projekt_uri}")

        try:
            # Get project data from cache - try multiple sources
            logger.info(f"📊 Getting project from cache: {projekt_uri}")
            logger.info(f"🔍 Looking for project URI: '{projekt_uri}' (length: {len(projekt_uri)})")

            cache_manager = CacheManager()
            project_data = None

            # Strategy 1: Try catalog cache with empty query (same as catalog view for empty searches)
            logger.info(f"🔍 Strategy 1: Checking catalog cache with empty query...")
            cached_search = cache_manager.catalog.get_cached_search_results(
                query="",
                property_name="cross_institutional_search",
                selected_class="projekt",
                user_org="global"
            )

            if cached_search and cached_search.get('results'):
                projects = cached_search['results'].get('entities', [])
                logger.info(f"📊 Found {len(projects)} projects in catalog cache (empty query)")
                project_data = self._find_project_in_list(projects, projekt_uri, "catalog cache (empty)")
            else:
                logger.info(f"📊 No catalog cache results for empty query")

            # Strategy 2: Try graph cache directly (like catalog view does)
            if not project_data:
                logger.info(f"🔍 Strategy 2: Checking graph cache directly...")
                cache_resource_uri = "arkumu:cross_institutional:all_projects"
                cache_params_hash = "cross_institutional_projects_canonical"

                cached_graph = cache_manager.graph.get_traversal_result(
                    resource_uri=cache_resource_uri,
                    traversal_type="catalog_projects",
                    params_hash=cache_params_hash
                )

                if cached_graph and cached_graph.get('result'):
                    projects = cached_graph['result']
                    logger.info(f"📊 Found {len(projects)} projects in graph cache")
                    project_data = self._find_project_in_list(projects, projekt_uri, "graph cache")
                else:
                    logger.info(f"📊 No graph cache results found")

            # Strategy 3: Try recent search cache (maybe user just searched)
            if not project_data:
                logger.info(f"🔍 Strategy 3: Checking recent search caches...")
                # Try a few common recent searches
                for test_query in ["a", "e", "i", "o", "u"]:
                    cached_search = cache_manager.catalog.get_cached_search_results(
                        query=test_query,
                        property_name="cross_institutional_search",
                        selected_class="projekt",
                        user_org="global"
                    )
                    if cached_search and cached_search.get('results'):
                        projects = cached_search['results'].get('entities', [])
                        logger.info(f"📊 Found {len(projects)} projects in search cache for '{test_query}'")
                        project_data = self._find_project_in_list(projects, projekt_uri, f"search cache ({test_query})")
                        if project_data:
                            break

            if not project_data:
                logger.error(f"❌ COMPLETE FAILURE: Project not found in any cache source")
                logger.error(f"❌ Target URI: '{projekt_uri}'")
                logger.error(f"❌ Checked: catalog cache (empty), graph cache, recent search caches")

            if not project_data:
                logger.error(f"❌ Project not found: {projekt_uri}")
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

    def _find_project_in_list(self, projects, target_uri, source_name):
        """
        Find project in a list with detailed logging for debugging.
        """
        if not projects:
            logger.info(f"📊 {source_name}: Empty project list")
            return None

        logger.info(f"📊 {source_name}: Data type: {type(projects)}")
        logger.info(f"📊 {source_name}: Data length: {len(projects) if hasattr(projects, '__len__') else 'N/A'}")

        # Handle different data structures
        try:
            if isinstance(projects, dict):
                logger.info(f"📊 {source_name}: Dict keys: {list(projects.keys())}")
                # If it's a dict, maybe it has 'entities', 'results', or 'projects'
                if 'entities' in projects:
                    projects = projects['entities']
                    logger.info(f"📊 {source_name}: Using 'entities' from dict, length: {len(projects)}")
                elif 'results' in projects:
                    projects = projects['results']
                    logger.info(f"📊 {source_name}: Using 'results' from dict, length: {len(projects)}")
                elif 'projects' in projects:
                    projects = projects['projects']
                    logger.info(f"📊 {source_name}: Using 'projects' from dict, length: {len(projects)}")
                else:
                    logger.error(f"❌ {source_name}: Unknown dict structure with keys: {list(projects.keys())}")
                    return None

            if not isinstance(projects, (list, tuple)):
                logger.error(f"❌ {source_name}: Expected list/tuple, got {type(projects)}: {projects}")
                return None

            logger.info(f"📊 {source_name}: Searching {len(projects)} projects for '{target_uri}'")

            # Show sample URIs from this source (safely)
            sample_count = min(5, len(projects))
            sample_uris = []
            for i in range(sample_count):
                try:
                    uri = projects[i].get('uri', 'NO_URI') if isinstance(projects[i], dict) else str(projects[i])
                    sample_uris.append(uri)
                except Exception as e:
                    sample_uris.append(f"ERROR: {e}")
            logger.info(f"📊 {source_name}: Sample URIs: {sample_uris}")

        except Exception as e:
            logger.error(f"❌ {source_name}: Error processing projects data: {e}")
            logger.error(f"❌ {source_name}: Projects data: {projects}")
            return None

        # Method 1: Exact match
        for i, project in enumerate(projects):
            try:
                if not isinstance(project, dict):
                    logger.error(f"❌ {source_name}: Project {i} is not a dict: {type(project)}")
                    continue

                project_uri = project.get('uri', '')
                if project_uri == target_uri:
                    logger.info(f"✅ {source_name}: Found exact match!")
                    logger.info(f"✅ Project details: title='{project.get('title', 'NO_TITLE')}', uri='{project_uri}'")
                    return self._convert_cached_project_to_project_data(project)
            except Exception as e:
                logger.error(f"❌ {source_name}: Error processing project {i}: {e}")
                continue

        # Method 2: UUID suffix match (if target looks like UUID)
        if len(target_uri) == 36 and '-' in target_uri:
            logger.info(f"🔍 {source_name}: Trying UUID suffix matching...")
            for i, project in enumerate(projects):
                try:
                    if not isinstance(project, dict):
                        continue
                    project_uri = project.get('uri', '')
                    if project_uri.endswith(target_uri):
                        logger.info(f"✅ {source_name}: Found UUID suffix match!")
                        logger.info(f"✅ Full URI: '{project_uri}' matches suffix '{target_uri}'")
                        logger.info(f"✅ Project details: title='{project.get('title', 'NO_TITLE')}'")
                        return self._convert_cached_project_to_project_data(project)
                except Exception as e:
                    logger.error(f"❌ {source_name}: Error in UUID matching for project {i}: {e}")
                    continue

        # Method 3: Contains match (in case of URI format differences)
        logger.info(f"🔍 {source_name}: Trying contains matching...")
        for i, project in enumerate(projects):
            try:
                if not isinstance(project, dict):
                    continue
                project_uri = project.get('uri', '')
                if target_uri in project_uri or project_uri in target_uri:
                    logger.info(f"✅ {source_name}: Found contains match!")
                    logger.info(f"✅ Project URI: '{project_uri}' contains or is contained in '{target_uri}'")
                    logger.info(f"✅ Project details: title='{project.get('title', 'NO_TITLE')}'")
                    return self._convert_cached_project_to_project_data(project)
            except Exception as e:
                logger.error(f"❌ {source_name}: Error in contains matching for project {i}: {e}")
                continue

        # Show detailed mismatch information
        logger.error(f"❌ {source_name}: No match found")
        logger.error(f"❌ Target: '{target_uri}' (len={len(target_uri)})")

        # Show all URIs for debugging (first 10) - safely
        debug_count = min(10, len(projects))
        for i in range(debug_count):
            try:
                project = projects[i]
                if isinstance(project, dict):
                    uri = project.get('uri', 'NO_URI')
                    logger.error(f"❌ Sample {i+1}: '{uri}' (len={len(uri)})")
                else:
                    logger.error(f"❌ Sample {i+1}: Not a dict: {type(project)}")
            except Exception as e:
                logger.error(f"❌ Sample {i+1}: Error: {e}")

        return None

    def _get_project_from_graph(self, projekt_uri: str):
        """Get single project data from cached cross-institutional projects."""
        try:
            logger.info(f"🔍 _get_project_from_graph called for: {projekt_uri}")

            # Use the same catalog cache method as the search results
            logger.info(f"📊 Getting cached projects using catalog cache...")

            # Get cached search results for empty query (which returns all projects)
            cached_search = cache_manager.catalog.get_cached_search_results(
                query="",
                property_name="cross_institutional_search",
                selected_class="projekt",
                user_org="global"
            )

            logger.info(f"🔍 Cached search data type: {type(cached_search)}")

            if cached_search and cached_search.get('results'):
                projects = cached_search['results'].get('entities', [])
                logger.info(f"📊 Found {len(projects)} cached projects from catalog cache")

                # Find the specific project by URI
                for project in projects:
                    project_uri = project.get('uri')
                    if project_uri == projekt_uri:
                        logger.info(f"✅ Found project in catalog cache: {projekt_uri}")
                        return self._convert_cached_project_to_project_data(project)

                logger.warning(f"❌ Project {projekt_uri} not found in {len(projects)} cached projects")
                # Debug: show first few project URIs
                sample_uris = [p.get('uri', 'NO_URI') for p in projects[:5]]
                logger.info(f"🔍 Sample cached project URIs: {sample_uris}")
            else:
                logger.warning(f"❌ No cached search results found")

            return None

        except Exception as e:
            logger.error(f"❌ Error loading project from cache for {projekt_uri}: {e}")
            return None

    def _convert_cached_project_to_project_data(self, project_dict):
        """Convert cached project dictionary to ProjectData object."""
        return ProjectData(
            uri=project_dict.get('uri', ''),
            title=project_dict.get('title', 'Untitled Project'),
            subtitle=project_dict.get('subtitle', ''),
            image=project_dict.get('image'),
            institution=project_dict.get('institution', ''),
            event_start=project_dict.get('event_start'),
            event_end=project_dict.get('event_end'),
            categories=project_dict.get('categories', []),
            actors=project_dict.get('actors', []),
            alternative_titles=project_dict.get('alternative_titles', []),
            description=project_dict.get('description', ''),
            catchphrases=project_dict.get('catchphrases', []),
            project_type=project_dict.get('project_type', ''),
            digital_objects=project_dict.get('digital_objects', [])
        )

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

