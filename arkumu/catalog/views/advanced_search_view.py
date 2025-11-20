import random
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
        view = request.GET.get('view', 'card').strip()
        query = request.GET.get('query', '').strip()
        institution = request.GET.getlist('hochschule', '')
        category = request.GET.getlist('kategorie', '')
        actor = request.GET.getlist('aktuer', '')
        logger.info(
            f"🔍 ADVANCED_SEARCH: Institution={institution}, Type={category}, Actor={actor}")

        try:
            # Hole alle Projekte
            projects = self._get_all_projects(request)

            # Filtere Projekte basierend auf Parametern
            total_results = 0
            filtered_projects = []
            if not query and not institution and not category and not actor:
                filtered_projects = random.sample(projects, k=15)
                total_results = len(projects)
            else:
                for project in projects:
                    if query and not project.matches_query(query):
                        continue
                    if institution and not project.matches_institution(institution):
                        continue
                    if category and not project.matches_category(category):
                        continue
                    if actor and not project.matches_actor(actor):
                        continue
                    filtered_projects.append(project)
                total_results = len(filtered_projects)

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
            categories = sorted(categories, key=lambda x: x["name"])
            hochschulen = set([i.institution.label for i in projects])
            hochschulen = sorted(hochschulen.difference(set(institution)))
            akteur_options = set({actor.name for p in projects for actor in p.actors})
            akteur = sorted(akteur_options.difference(set(actor)))

            filtered_projects = [p.to_card_dict() for p in filtered_projects]
            for i, project in enumerate(filtered_projects):
                print(project)
                if project["categories"]:
                    if len(project["categories"]) > 0:
                        project["category1_name"] = wikidata_service.get_entity_label(wikidata_id=project["categories"][0])
                    if len(project["categories"]) > 1:
                        project["category2_name"] = wikidata_service.get_entity_label(wikidata_id=project["categories"][1])
                    if len(project["categories"]) > 2:
                        project["category3_name"] = wikidata_service.get_entity_label(wikidata_id=project["categories"][2])



            dropdown_option = {
                "hochschulen": hochschulen,
                "akteur": akteur,
                "kategorien": categories
            }

            # Create active filters list
            active_filters = []


            # Institution filters
            for inst in institution:
                q = request.GET.copy()
                q.setlist('hochschule', [i for i in institution if i != inst])
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
                active_filters.append({
                    'type': 'aktuer',
                    'value': act,
                    'display_name': act,
                    'remove_url': f"{request.path}?{q.urlencode()}"
                })

            query_params = request.GET.copy()  # mutable copy

            # kompletten 'view'-Parameter entfernen
            query_params.pop('view', None)

            request_path = f"{request.path}?{query_params.urlencode()}"

            # Kontext für Template
            context = {
                'institution': institution,
                'active_filters': active_filters,
                'actor': actor,
                'category': category,
                'results': filtered_projects,
                'total_results': total_results,
                'csrf_token': get_token(request),
                'dropdown_option': dropdown_option,
                'query': query,
                'view': view,
                'request_path': request_path,
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
