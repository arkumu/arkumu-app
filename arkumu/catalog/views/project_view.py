from __future__ import annotations

"""Project detail view using canonical URIs."""

from django.views.generic import View
from django.shortcuts import render
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse
from django.http import HttpResponseBadRequest, HttpResponseNotFound
from typing import Optional, Tuple, Dict, Any
import logging

from arkumu.catalog.services.project_views import ProjectData, ProjectURIs, CardURIs
from arkumu.cache.services import CacheManager
from arkumu.catalog.services.schema_manifest_service import SchemaManifestService
from arkumu.catalog.services.triple_relationship_service import TripleRelationshipService

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
            enriched_project, project_data = self._load_project(projekt_uri)
        except LookupError:
            logger.error(f"❌ Project not found: {projekt_uri}")
            return render(request, 'catalog/design_error.html', {
                'error': f'Project not found: {projekt_uri}'
            })
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error(f"Error loading project {projekt_uri}: {exc}")
            return render(request, 'catalog/design_error.html', {
                'error': f'Error loading project: {exc}'
            })

        project_context = self._build_project_context(project_data)
        metadata = self._build_metadata(enriched_project, project_data)

        context = {
            'project': project_context,
            'metadata': metadata,
            'tab_endpoint': reverse('catalog:projekt_tab'),
        }

        logger.info(f"Successfully loaded project data for: {projekt_uri}")
        return render(request, 'catalog/projekt.html', context)

    def _load_project(self, projekt_uri: str) -> Tuple[Dict[str, Any], ProjectData]:
        """Load enriched project payload and converted ProjectData."""
        logger.info(f"📊 Getting project from cached graph: {projekt_uri}")

        cache_manager = CacheManager()
        graph_cache = cache_manager.graph

        cached_graph = graph_cache.get_traversal_result(
            resource_uri="arkumu:cross_institutional:all_projects",
            traversal_type="catalog_projects",
            params_hash="cross_institutional_projects_canonical"
        )

        if not cached_graph or 'result' not in cached_graph or 'projects' not in cached_graph['result']:
            logger.error("❌ No cached graph found")
            raise LookupError("Project cache unavailable")

        projects = cached_graph['result']['projects']
        logger.info(f"📊 Found {len(projects)} projects in cached graph")

        for project in projects:
            if project.get('uri') != projekt_uri:
                continue

            detail_cache = graph_cache.get_traversal_result(
                resource_uri=projekt_uri,
                traversal_type="catalog_project_detail",
                params_hash="canonical"
            )

            if detail_cache and detail_cache.get('result'):
                logger.info("📦 Using cached project detail payload")
                enriched_project = detail_cache['result']
            else:
                logger.info("♻️ Detail cache miss – enriching project relationships")
                enriched_project = self._enrich_project_with_relationships(project)
                if enriched_project:
                    graph_cache.cache_traversal_result(
                        resource_uri=projekt_uri,
                        traversal_type="catalog_project_detail",
                        params_hash="canonical",
                        result_data=enriched_project,
                    )

            project_data = self._convert_cached_project_to_project_data(enriched_project)
            return enriched_project, project_data

        raise LookupError("Project not found")

    def _build_project_context(self, project_data: ProjectData) -> Dict[str, Any]:
        """Shape project data for templates."""
        year_range = ''
        if project_data.event_start and project_data.event_end:
            start_year = project_data.event_start.split('-')[0] if '-' in project_data.event_start else project_data.event_start
            end_year = project_data.event_end.split('-')[0] if '-' in project_data.event_end else project_data.event_end
            year_range = start_year if start_year == end_year else f"{start_year} bis {end_year}"
        elif project_data.event_start:
            year_range = project_data.event_start.split('-')[0] if '-' in project_data.event_start else project_data.event_start

        return {
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
            'events': project_data.events or [],
        }

    def _build_metadata(self, enriched_project: Dict[str, Any], project_data: ProjectData) -> list[Dict[str, Any]]:
        """Prepare metadata tab payload."""

        def _entry(label: str, value: Any) -> Dict[str, Any]:
            if isinstance(value, (list, tuple, set)):
                values = [item for item in value if item]
                return {'key': label, 'values': values} if values else {'key': label, 'value': '—'}
            return {'key': label, 'value': value or '—'}

        metadata_entries = [
            _entry('Projekt URI', project_data.uri),
            _entry('Institution', project_data.institution),
            _entry('Projektart', project_data.project_type),
            _entry('Schlagworte', project_data.catchphrases or []),
            _entry('Kategorien', project_data.categories or []),
            _entry('Digitale Objekte', project_data.digital_objects or []),
            _entry('Alternative Titel', project_data.alternative_titles or []),
        ]

        if enriched_project and enriched_project.get('events'):
            metadata_entries.append(_entry('Anzahl Ereignisse', len(enriched_project['events'])))

        return metadata_entries

    def _convert_entity_graph_to_project_data(self, project_graph: dict, projekt_uri: str) -> Optional[ProjectData]:
        """Convert entity graph from CanonicalGraphService to ProjectData."""
        try:
            # The entity graph contains nodes and edges for this specific project
            nodes = project_graph.get('nodes', {})
            edges = project_graph.get('edges', [])
            root_id = project_graph.get('root_id')

            if not root_id:
                logger.error(f"No root_id in entity graph for {projekt_uri}")
                return None

            # Extract project properties from edges
            project_props = {}
            for edge in edges:
                if edge['subject_id'] == root_id:
                    canonical_uri = edge.get('predicate_canonical') or edge['predicate_uri']
                    project_props[canonical_uri] = edge

            # Extract basic properties using canonical URIs
            title = self._get_edge_value(project_props, "http://arkumu.org/data/properties/bevorzugter-titel")
            subtitle = self._get_edge_value(project_props, "http://arkumu.org/data/properties/bevorzugter-untertitel")
            description = self._get_edge_value(project_props, "http://arkumu.org/data/properties/beschreibung")
            institution = self._get_edge_value(project_props, "http://arkumu.org/data/properties/institution")

            # Extract event dates
            event_start = self._get_edge_value(project_props, "http://arkumu.org/data/properties/ereignisbeginn")
            event_end = self._get_edge_value(project_props, "http://arkumu.org/data/properties/ereignisende")

            logger.info(f"✅ Converted entity graph to ProjectData: title='{title}', subtitle='{subtitle}'")

            return ProjectData(
                uri=projekt_uri,
                title=title or 'Untitled Project',
                subtitle=subtitle or '',
                image=None,  # TODO: Extract from graph if available
                institution=institution or '',
                event_start=event_start,
                event_end=event_end,
                categories=[],  # TODO: Extract from graph if available
                actors=[],  # TODO: Extract from graph if available
                alternative_titles=[],  # TODO: Extract from graph if available
                description=description or '',
                catchphrases=[],  # TODO: Extract from graph if available
                project_type='',  # TODO: Extract from graph if available
                digital_objects=[]  # TODO: Extract from graph if available
            )

        except Exception as e:
            logger.error(f"Error converting entity graph to ProjectData for {projekt_uri}: {e}")
            return None

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
            digital_objects=project_dict.get('digital_objects', []),
            events=project_dict.get('events', [])  # Add events data
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

    def _enrich_project_with_relationships(self, project_dict):
        """Enrich project data with relationships (same logic as catalog view)."""
        try:
            logger.info(f"🔗 ENRICHING project {project_dict.get('uri')} with relationship data")

            # Get schema
            schema_service = SchemaManifestService()
            schema = schema_service.get_card_schema('fuk')

            # Initialize triple service with no org filtering (cross-institutional)
            triple_service = TripleRelationshipService(None)

            # Helper function to get property
            def _property(section: str, prop: str):
                section_obj = schema.sections.get(section)
                if not section_obj:
                    return None
                return section_obj.properties.get(prop)

            # Get property definitions
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

            # Additional project properties for detailed view
            title_prop = _property('project', 'title')
            subtitle_prop = _property('project', 'subtitle')
            image_prop = _property('project', 'image')

            subject_id = project_dict.get('uri')
            if not subject_id:
                return project_dict

            # Make a copy to avoid modifying the original
            enriched_project = project_dict.copy()

            # Get project description
            description = triple_service.get_project_description(
                subject_id,
                description_predicate='http://arkumu.org/data/properties/beschreibung',
                organization_code=None,
            )
            if description:
                enriched_project['description'] = description

            # Get project type
            project_type = triple_service.get_project_type(
                subject_id,
                project_type_predicate='http://arkumu.org/data/properties/projektart',
                organization_code=None,
            )
            if project_type:
                enriched_project['project_type'] = project_type

            # Get alternative titles
            alternative_titles = triple_service.get_alternative_titles(
                subject_id,
                alternative_title_set_predicate='http://arkumu.org/data/fuk/properties/alternativer-titel-set',
                alternative_title_predicate='http://arkumu.org/data/properties/alternativer-titel',
                organization_code=None,
            )
            if alternative_titles:
                enriched_project['alternative_titles'] = alternative_titles

            # Get catchphrases
            catchphrases = triple_service.get_catchphrases(
                subject_id,
                catchphrase_predicate='http://arkumu.org/data/properties/schlagwort',
                catchphrase_label_predicate='http://arkumu.org/data/properties/deutsches-wikidata-label',
                organization_code=None,
            )
            if catchphrases:
                enriched_project['catchphrases'] = catchphrases

            # Get institution data
            institution_label = triple_service.get_institution_data(
                subject_id,
                institution_predicate=institution_prop.canonical_uri if institution_prop else None,
                institution_label_predicate=institution_name_prop.canonical_uri if institution_name_prop else None,
                organization_code=None,
            )
            if institution_label:
                enriched_project['institution'] = institution_label

            # Get category data
            category_labels = triple_service.get_category_data(
                subject_id,
                category_predicate=category_prop.canonical_uri if category_prop else None,
                category_label_predicate=category_name_prop.canonical_uri if category_name_prop else None,
                organization_code=None,
            )
            if category_labels:
                enriched_project['categories'] = category_labels

            # Get detailed event data
            detailed_events = triple_service.get_detailed_event_data(
                subject_id,
                event_predicate=event_prop.canonical_uri if event_prop else None,
                event_start_predicate=event_start_prop.canonical_uri if event_start_prop else None,
                event_end_predicate=event_end_prop.canonical_uri if event_end_prop else None,
                event_name_predicate='http://arkumu.org/data/properties/ereignisname',
                event_description_predicate='http://arkumu.org/data/properties/ereignisbeschreibung',
                event_location_predicate='http://arkumu.org/data/properties/ereignisort',
                event_type_predicate='http://arkumu.org/data/properties/ereignistyp',
                organization_code=None,
            )

            if detailed_events:
                # Store detailed events
                enriched_project['events'] = detailed_events

                # Extract dates from first event for compatibility
                first_event = detailed_events[0]
                if first_event.get('start'):
                    enriched_project['event_start'] = first_event['start']
                if first_event.get('end'):
                    enriched_project['event_end'] = first_event['end']

                # Use event IDs for actor lookup
                event_ids = [event['id'] for event in detailed_events]
            else:
                event_ids = []

            # Get actor data
            actors = triple_service.get_actor_relationships(
                subject_id,
                event_predicate=event_prop.canonical_uri if event_prop else None,
                actor_link_predicate=actor_link_prop.canonical_uri if actor_link_prop else None,
                role_link_predicate=role_link_prop.canonical_uri if role_link_prop else None,
                actor_name_predicate=actor_name_prop.canonical_uri if actor_name_prop else None,
                role_name_predicate=role_name_prop.canonical_uri if role_name_prop else None,
                event_ids=event_ids,
                organization_code=None,
            )
            if actors:
                # Convert to the format expected by ProjectData
                actor_list = []
                for actor in actors:
                    actor_entry = {
                        'name': actor['name'],
                        'roles': actor['roles']
                    }
                    actor_list.append(actor_entry)
                enriched_project['actors'] = actor_list

            # Get digital object paths
            digital_object_paths = triple_service.get_digital_object_paths(
                subject_id,
                link_predicate='http://arkumu.org/data/properties/digitales-objekt',
                path_predicate=digital_object_path_prop.canonical_uri if digital_object_path_prop else None,
                organization_code=None,
            )
            if digital_object_paths:
                enriched_project['digital_objects'] = digital_object_paths
                # Set first digital object as image if no image is set
                if not enriched_project.get('image') or enriched_project.get('image') == 'images/main/card_1.png':
                    enriched_project['image'] = digital_object_paths[0]

            logger.info(f"🔗 ENRICHED project with institution='{enriched_project.get('institution')}', categories={len(enriched_project.get('categories', []))}, actors={len(enriched_project.get('actors', []))}")

            return enriched_project

        except Exception as e:
            logger.error(f"❌ Error enriching project with relationships: {e}")
            return project_dict


class ProjectTabView(LoginRequiredMixin, View):
    """Serve tab content for project detail via HTMX."""

    def get(self, request, *args, **kwargs):
        projekt_uri = request.GET.get('projekt')
        tab = request.GET.get('tab', 'overview').lower()

        if not projekt_uri:
            return HttpResponseBadRequest("Missing project URI")

        helper = ProjectView()
        try:
            enriched_project, project_data = helper._load_project(projekt_uri)
        except LookupError:
            return HttpResponseNotFound("Project not found")

        project_context = helper._build_project_context(project_data)
        metadata = helper._build_metadata(enriched_project, project_data)

        if tab == 'events':
            events = self._build_event_payload(projekt_uri)
            return render(request, 'catalog/partials/project_events.html', {'events': events})

        if tab == 'metadata':
            return render(request, 'catalog/partials/project_metadata.html', {'metadata': metadata})

        return render(request, 'catalog/partials/project_overview.html', {'project': project_context})

    @staticmethod
    def _build_event_payload(projekt_uri: str) -> list[dict[str, Any]]:
        triple_service = TripleRelationshipService(None)

        events = triple_service.get_detailed_event_data(
            projekt_uri,
            event_predicate=ProjectURIs.EVENT,
            event_start_predicate=ProjectURIs.EVENT_START,
            event_end_predicate=ProjectURIs.EVENT_END,
            event_name_predicate=ProjectURIs.EVENT_NAME,
            event_description_predicate=ProjectURIs.EVENT_DESCRIPTION,
            event_location_predicate=ProjectURIs.EVENT_LOCATION,
            event_type_predicate=ProjectURIs.EVENT_TYPE,
            organization_code=None,
        )

        event_ids = [event.get('id') for event in events if event.get('id')]

        actors = triple_service.get_actor_relationships(
            projekt_uri,
            event_predicate=ProjectURIs.EVENT,
            actor_link_predicate=CardURIs.ACTOR_IN_EVENT,
            role_link_predicate=CardURIs.ACTOR_ROLE,
            actor_name_predicate=CardURIs.ACTOR_GERMAN_NAME,
            role_name_predicate=CardURIs.ROLE_GERMAN_NAME,
            event_ids=event_ids,
            organization_code=None,
        )

        actors_by_event: Dict[str, list[dict[str, Any]]] = {}
        for actor in actors:
            actor_entry = {
                'name': actor.get('name'),
                'roles': actor.get('roles', []),
            }
            for event_id in actor.get('event_ids', []):
                actors_by_event.setdefault(event_id, []).append(actor_entry)

        for event in events:
            event_id = event.get('id')
            event['actors'] = actors_by_event.get(event_id, [])

        return events
