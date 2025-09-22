"""
Simple test version of search - bypasses materialized view for immediate testing.
"""

from django.views.generic import View
from django.shortcuts import render
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from arkumu.metadata.models import Resource, Triple, ResourceType
import logging

logger = logging.getLogger(__name__)


class SimpleTestSearchView(LoginRequiredMixin, View):
    """Simple search test - direct database queries."""

    def get(self, request, *args, **kwargs):
        """Simple search using direct queries."""
        query = request.GET.get('query', '').strip()

        try:
            if query:
                logger.info(f"Testing search with query: '{query}'")

                # Simple search in project titles
                title_predicate_uri = 'http://arkumu.org/data/properties/bevorzugter-titel'

                # Find projects by searching in title literals
                title_triples = Triple.objects.filter(
                    predicate__canonical_uri=title_predicate_uri,
                    object__resource_type=ResourceType.LITERAL,
                    object__value__icontains=query
                ).select_related('subject', 'object')[:10]

                results = []
                for triple in title_triples:
                    project_uri = triple.subject.uri
                    title = triple.object.value

                    results.append({
                        "uri": project_uri,
                        "title": title,
                        "subtitle": "",
                        "institution": "Test Institution",
                        "year": "2024",
                        "image": "images/main/card_1.png",
                        "button_text": "Projekt ansehen",
                        "contributor1_name": "Test Contributor",
                        "contributor1_role": "Test Role",
                        "category1": "Test Category"
                    })

                logger.info(f"Found {len(results)} projects")

            else:
                # Get some sample projects
                sample_triples = Triple.objects.filter(
                    predicate__canonical_uri='http://arkumu.org/data/properties/bevorzugter-titel',
                    object__resource_type=ResourceType.LITERAL
                ).select_related('subject', 'object')[:5]

                results = []
                for triple in sample_triples:
                    results.append({
                        "uri": triple.subject.uri,
                        "title": triple.object.value,
                        "subtitle": "",
                        "institution": "Sample Institution",
                        "year": "2024",
                        "image": "images/main/card_1.png",
                        "button_text": "Projekt ansehen"
                    })

            context = {
                'query': query,
                'results': results,
                'test_mode': True
            }

            return render(request, 'catalog/card_grid_template.html', context)

        except Exception as e:
            logger.error(f"Search error: {e}")
            context = {
                'query': query,
                'results': [],
                'error': f'Search error: {str(e)}'
            }
            return render(request, 'catalog/card_grid_template.html', context)


class SimpleTestProjektView(LoginRequiredMixin, View):
    """Simple project detail test."""

    def get(self, request, *args, **kwargs):
        projekt_uri = request.GET.get('projekt', None)

        context = {
            'project': {
                'title': 'Test Project',
                'subtitle': 'Test Subtitle',
                'institution': 'Test Institution',
                'year_range': '2024',
                'descriptions': ['Test description'],
                'categories': ['Test Category']
            }
        }

        template = 'catalog/projekt_detail_partial.html' if request.headers.get('HX-Request') else 'catalog/projekt.html'
        return render(request, template, context)


# Backward compatibility
Card = type('Card', (), {
    'search_cards': staticmethod(SimpleTestSearchView.as_view())
})

ProjektShow = type('ProjektShow', (), {
    'projekt': staticmethod(SimpleTestProjektView.as_view())
})