import time

from django.views.generic import View
from django.shortcuts import render
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.middleware.csrf import get_token
import logging
from typing import Any, Dict, List, Optional

from arkumu.cache.services import CacheManager
from arkumu.projects.services import ProjectSnapshotService
from .catalog_template_helpers import CatalogTemplateHelperMixin
from arkumu.users.mixins import GeneralLoginRequiredMixin
from arkumu.metadata.models import ExternalSourcesEntity
from ..services import wikidata_service
from ..services.wikidata_service import WikidataService
from ...projects import ProjectRecord

logger = logging.getLogger(__name__)


class AdvancedSearchView(GeneralLoginRequiredMixin, View, CatalogTemplateHelperMixin):
    """
    Erweiterte Suche mit Filterung nach Institution, Projektart, Akteur, Kategorie und Schlagwort.
    """
    ITEMS_PER_PAGE = 10
    CACHE_TIMEOUT = 3600

    def get(self, request, *args, **kwargs):
        start_time = time.time()

        # Extrahiere Suchparameter
        query = request.GET.get('query', '').strip()
        institution = request.GET.getlist('institution', '').strip()
        project_type = request.GET.getlist('project_type', '').strip()
        actor = request.GET.getlist('actor', '').strip()
        category = request.GET.getlist('category', '').strip()
        keyword = request.GET.getlist('keyword', '').strip()
        page = request.GET.get('page', 1)
        is_htmx = request.headers.get('HX-Request') is not None

        logger.info(
            f"🔍 ADVANCED_SEARCH: Institution={institution}, Type={project_type}, Actor={actor}, Category={category}, Keyword={keyword}")

        try:
            # Hole alle Projekte
            projects = self._get_all_projects(request)

            # Filtere Projekte basierend auf Parametern
            filtered_projects = []
            for project in projects:
                if query and not project.matches_query(query):
                    continue
                if institution and not project.matches_institution(institution):
                    continue
                if project_type and not project.matches_project_type(project_type):
                    continue
                if actor and not project.matches_actor(actor):
                    continue
                if category and not project.matches_category(category):
                    continue
                if keyword and not project.matches_keyword(keyword):
                    continue
                filtered_projects.append(project)

            # Paginierung
            paginator = Paginator(filtered_projects, self.ITEMS_PER_PAGE)
            try:
                page_obj = paginator.page(page)
            except PageNotAnInteger:
                page_obj = paginator.page(1)
            except EmptyPage:
                page_obj = paginator.page(paginator.num_pages)

            categories = []
            for p in filtered_projects:
                for i in p.categories:
                    categories.append(i.label)
            categories = sorted(set(categories))
            categories_name = []
            wikidata_service = WikidataService()
            for i, w in enumerate(categories):
                categories_name.append(wikidata_service.get_entity_label(wikidata_id=w))
            categories = [
                    {"id": cid, "name": cname}
                    for cid, cname in zip(categories, categories_name)
            ]

            dropdown_option = {
                "hochschulen": sorted(set([i.institution.label for i in filtered_projects])),
                "akteur": sorted(set({actor.name for p in filtered_projects for actor in p.actors})),
                "kategorien": categories
            }




            # Kontext für Template
            context = {
                'institution': institution,
                'project_type': project_type,
                'actor': actor,
                'category': category,
                'keyword': keyword,
                'results': [p.to_card_dict() for p in page_obj.object_list],
                'total_results': paginator.count,
                'current_page': page_obj.number,
                'total_pages': paginator.num_pages,
                'csrf_token': get_token(request),
                'dropdown_option': dropdown_option,
            }

            processing_time = time.time() - start_time
            logger.info(f"⚡ ADVANCED_SEARCH_COMPLETE: {len(filtered_projects)} results in {processing_time:.3f}s")

            return render(request, 'catalog/advanced_search_test.html', context)

        except Exception as e:
            logger.error(f"❌ ADVANCED_SEARCH_ERROR: {e}")
            return render(request, 'catalog/error.html', {'error': str(e)})

    def _get_all_projects(self, request) -> List[ProjectRecord]:
        snapshot_service = ProjectSnapshotService()


        # Lade Projekte neu
        snapshot = snapshot_service.get_cross_institutional_snapshot()
        projects = snapshot.projects
        logger.info(f"📦 LOADED {len(projects)} PROJECTS FROM SNAPSHOT")

        # Cache für zukünftige Anfragen
        return projects
