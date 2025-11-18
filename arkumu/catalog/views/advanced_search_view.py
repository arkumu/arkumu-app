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
        institution = request.GET.getlist('hochschule', '')
        category = request.GET.getlist('kategorie', '')
        actor = request.GET.getlist('aktuer', '')
        # keyword = request.GET.getlist('keyword', '').strip()
        page = request.GET.get('page', 1)
        is_htmx = request.headers.get('HX-Request') is not None
        logger.info(
            f"🔍 ADVANCED_SEARCH: Institution={institution}, Type={category}, Actor={actor}")

        try:
            # Hole alle Projekte
            projects = self._get_all_projects(request)

            # Filtere Projekte basierend auf Parametern
            filtered_projects = []
            for project in projects:
                print(project.categories)
                if query and not project.matches_query(query):
                    continue
                if institution and not project.matches_institution(institution):
                    continue
                if category and not project.matches_category(category):
                    continue
                if actor and not project.matches_actor(actor):
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
            for p in projects:
                for i in p.categories:
                     categories.append(i.label)
            categories = set(categories).difference(set(category))
            categories_name = []
            wikidata_service = WikidataService()
            for i, w in enumerate(categories):
                categories_name.append(wikidata_service.get_entity_label(wikidata_id=w))
            categories = [
                    {"id": cid, "name": cname}
                    for cid, cname in zip(categories, categories_name)
            ]
            hochschulen = set([i.institution.label for i in projects])
            hochschulen = sorted(hochschulen.difference(set(institution)))
            akteur_options = set({actor.name for p in projects for actor in p.actors})
            akteur = sorted(akteur_options.difference(set(actor)))

            dropdown_option = {
                "hochschulen": hochschulen,
                "akteur": akteur,
                "kategorien": categories
            }

            # Create active filters list
            active_filters = []

            # Create mapping for category IDs to names
            # category_id_to_name = {cat['id']: cat['name'] for cat in dropdown_option['kategorien']}

            # Institution filters
            for inst in institution:
                q = request.GET.copy()
                q.setlist('hochschule', [i for i in institution if i != inst])
                q['page'] = '1'  # Reset to first page
                active_filters.append({
                    'type': 'hochschule',
                    'value': inst,
                    'display_name': inst,
                    'remove_url': f"{request.path}?{q.urlencode()}"
                })

            # Category filters
            for cat_id in category:
                q = request.GET.copy()
                q.setlist('kategorie', [c for c in category if c != cat_id])
                q['page'] = '1'
                active_filters.append({
                    'type': 'kategorie',
                    'value': cat_id,
                    'display_name': wikidata_service.get_entity_label(cat_id),
                    'remove_url': f"{request.path}?{q.urlencode()}"
                })

            # Actor filters
            for act in actor:
                q = request.GET.copy()
                q.setlist('aktuer', [a for a in actor if a != act])
                q['page'] = '1'
                active_filters.append({
                    'type': 'aktuer',
                    'value': act,
                    'display_name': act,
                    'remove_url': f"{request.path}?{q.urlencode()}"
                })


            # Kontext für Template
            context = {
                'institution': institution,
                # 'project_type': project_type,
                'active_filters': active_filters,
                'actor': actor,
                'category': category,
                # 'keyword': keyword,
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
