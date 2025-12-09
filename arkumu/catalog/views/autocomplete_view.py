"""HTMX autocomplete endpoints for advanced search filters."""

from django.http import HttpResponse
from django.views import View
from django.template.loader import render_to_string

from arkumu.users.mixins import GeneralLoginRequiredMixin
from arkumu.catalog.models import ProjectIndex
from arkumu.metadata.models import PublicAccessLevel


class FilterAutocompleteView(GeneralLoginRequiredMixin, View):
    """HTMX endpoint for filter autocomplete suggestions."""

    MAX_RESULTS = 20

    def get(self, request, filter_type):
        query = request.GET.get('q', '').strip().lower()
        # Get selected values based on filter type's param name
        param_map = {'akteur': 'akteur', 'kategorie': 'kategorie', 'hochschule': 'hochschule'}
        param_name = param_map.get(filter_type, filter_type)
        selected = request.GET.getlist(param_name, [])

        if filter_type == 'akteur':
            options = self._get_actor_options(query, selected)
        elif filter_type == 'kategorie':
            options = self._get_category_options(query, selected)
        elif filter_type == 'hochschule':
            options = self._get_institution_options(query, selected)
        else:
            options = []

        html = render_to_string(
            'components/inputs/autocomplete_dropdown.html',
            {'options': options, 'filter_type': filter_type}
        )
        return HttpResponse(html)

    def _get_base_queryset(self):
        return ProjectIndex.objects.filter(
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True,
        )

    def _get_actor_options(self, query, selected):
        qs = self._get_base_queryset()
        all_actors = set()
        for names in qs.values_list('actor_names', flat=True):
            if names:
                all_actors.update(names)

        filtered = [
            a for a in sorted(all_actors)
            if a and a not in selected and (not query or query in a.lower())
        ]
        return filtered[:self.MAX_RESULTS]

    def _get_category_options(self, query, selected):
        qs = self._get_base_queryset()
        all_categories = set()
        for cats in qs.values_list('category_labels', flat=True):
            if cats:
                all_categories.update(cats)

        filtered = [
            c for c in sorted(all_categories)
            if c and c not in selected and (not query or query in c.lower())
        ]
        return filtered[:self.MAX_RESULTS]

    def _get_institution_options(self, query, selected):
        qs = self._get_base_queryset()
        all_institutions = sorted(set(
            qs.exclude(institution_label='')
            .values_list('institution_label', flat=True)
            .distinct()
        ))

        filtered = [
            i for i in all_institutions
            if i and i not in selected and (not query or query in i.lower())
        ]
        return filtered[:self.MAX_RESULTS]
