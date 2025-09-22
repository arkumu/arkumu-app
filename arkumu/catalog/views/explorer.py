"""Catalog Explorer Views housed within the views package."""

import logging
from typing import Any, Dict, List, Optional

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.views.generic import TemplateView

from arkumu.cache.services import CatalogCacheService
from arkumu.catalog.services.graph_search_service import GraphSearchService
from arkumu.metadata.views.csv_mapping.mixins.template_helpers import (
    CSVMappingTemplateHelperMixin,
)


class CatalogExplorerView(LoginRequiredMixin, TemplateView, CSVMappingTemplateHelperMixin):
    """Graph-based data exploration view."""

    template_name = "catalog/explorer_sidebar.html"
    logger = logging.getLogger(__name__)

    def get(self, request, *args, **kwargs):
        """Handle GET requests, including HTMX requests."""
        if request.headers.get("HX-Request"):
            return self._handle_htmx_request(request)
        return super().get(request, *args, **kwargs)

    def _handle_htmx_request(self, request):
        """Handle HTMX requests for dynamic content updates using OOB."""
        hx_target = request.headers.get("HX-Target", "")

        self.logger.info(
            "HTMX Request - Target: '%s', Organization: '%s'",
            hx_target,
            request.GET.get("organization", ""),
        )

        context = self._get_context_data()

        if hx_target in ["classes-section", "#classes-section"]:
            classes_html = render_to_string(
                "catalog/partials/classes_list.html", context, request=request
            )
            properties_html = ""

            oob_classes = (
                f'<div id="classes-section" hx-swap-oob="outerHTML">{classes_html}</div>'
            )
            oob_properties = (
                f'<div id="properties-section" hx-swap-oob="outerHTML">{properties_html}</div>'
            )
            response_html = f"{oob_classes}{oob_properties}"
            self.logger.info("Manual OOB response length: %s", len(response_html))
            return HttpResponse(response_html)

        content_html = render_to_string(
            "catalog/partials/explorer_content.html", context, request=request
        )
        return HttpResponse(content_html)

    def _get_context_data(self) -> Dict[str, Any]:
        catalog_cache = CatalogCacheService()

        selected_class = self.request.GET.get("class", "")
        selected_organization = self.request.GET.get("organization", "")
        property_name = self.request.GET.get("property", "title")

        sidebar = catalog_cache.get_explorer_sidebar_context(
            selected_class=selected_class,
            organization_code=selected_organization or None,
        )

        self.logger.debug(
            "Explorer sidebar cache: %s classes, %s properties for class %s",
            len(sidebar.get("available_classes", {})),
            len(sidebar.get("available_properties", {})),
            selected_class,
        )

        sidebar.update(
            {
                "selected_class": selected_class,
                "selected_property": property_name,
                "selected_organization": selected_organization,
                "has_results": False,
                "show_initial_message": True,
            }
        )
        return sidebar

    def get_context_data(self, **kwargs) -> Dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context.update(self._get_context_data())
        return context


class CatalogExplorerPropertiesView(LoginRequiredMixin, TemplateView):
    """HTMX endpoint for loading properties of a selected class."""

    def get(self, request, *args, **kwargs):
        selected_class = request.GET.get("class", "")
        selected_organization = request.GET.get("organization", "")

        if not selected_class:
            return HttpResponse("")

        catalog_cache = CatalogCacheService()
        properties_map = catalog_cache.get_class_properties_map(
            selected_class, selected_organization or None
        )
        available_properties = list(properties_map.values())

        context = {
            "available_properties": {
                item["uri"]: {
                    "name": item.get("name", item["uri"]),
                    "usage_count": item.get("usage_count", 0),
                }
                for item in available_properties
            },
            "selected_class": selected_class,
            "selected_property": request.GET.get("property", ""),
        }

        html = render_to_string(
            "catalog/partials/properties_list.html", context, request=request
        )
        return HttpResponse(html)


class CatalogExplorerLiteralsView(LoginRequiredMixin, TemplateView):
    """HTMX endpoint for browsing literal values of a selected property."""

    logger = logging.getLogger(__name__)

    def get(self, request, *args, **kwargs):
        property_uri = request.GET.get("property", "")
        class_uri = request.GET.get("class", "")
        organization_code = request.GET.get("organization", "")
        search_term = request.GET.get("search", "")
        page = int(request.GET.get("page", 1))
        per_page = 20

        if not property_uri:
            return HttpResponse("")

        graph_service = GraphSearchService(user=request.user)
        catalog_cache = CatalogCacheService()
        user_org = (
            request.user.organization.code
            if hasattr(request.user, "organization") and request.user.organization
            else None
        )

        try:
            offset = (page - 1) * per_page

            cache_key_params = (
                f"{property_uri}_{class_uri}_{organization_code}_{search_term}_{offset}_{per_page}"
            )
            cached_results = catalog_cache.get_cached_search_results(
                query=cache_key_params,
                property_name=property_uri,
                selected_class=class_uri or "",
                user_org=user_org,
            )

            if cached_results:
                self.logger.debug("Using cached search results for %s", property_uri)
                literals_data = cached_results["results"]
            else:
                self.logger.debug("Cache miss - fetching search results for %s", property_uri)
                literals_data = graph_service.browse_property_values(
                    property_uri=property_uri,
                    class_uri=class_uri or None,
                    organization_code=organization_code or None,
                    search_term=search_term or None,
                    offset=offset,
                    limit=per_page,
                )

                catalog_cache.cache_search_results(
                    query=cache_key_params,
                    property_name=property_uri,
                    results=literals_data,
                    selected_class=class_uri or "",
                    user_org=user_org,
                )

            total_pages = (literals_data["unique_values"] + per_page - 1) // per_page

            page_obj = type(
                "PageObj",
                (),
                {
                    "number": page,
                    "has_previous": page > 1,
                    "has_next": page < total_pages,
                    "previous_page_number": page - 1 if page > 1 else None,
                    "next_page_number": page + 1 if page < total_pages else None,
                    "paginator": type("Paginator", (), {"num_pages": total_pages})(),
                },
            )()

            literals_data["page_obj"] = page_obj

            context = {
                "literals_data": literals_data,
                "property_uri": property_uri,
                "class_uri": class_uri,
                "search_term": search_term,
                "page_obj": page_obj,
                "current_page": page,
            }

            if not search_term and page == 1:
                html = render_to_string(
                    "catalog/partials/literals_list.html", context, request=request
                )
                return HttpResponse(html)

            results_html = self._render_literals_results(context, request)
            header_html = (
                f'<h2 class="text-xl font-semibold">{literals_data["property_name"].title()} '
                f'Values</h2><span class="badge badge-primary badge-lg font-mono ml-8">'
                f"{literals_data['total_values']} usages</span>"
            )
            oob_html = (
                '<div id="literals-header" hx-swap-oob="innerHTML">'
                f'<div class="flex justify-between items-center mb-4">{header_html}</div>'
                "</div>"
            )

            return HttpResponse(f"{results_html}{oob_html}")

        except Exception as exc:
            self.logger.error("Error browsing literals: %s", exc)
            return HttpResponse(
                f"<p class='text-red-500'>Error loading literals: {exc}</p>"
            )

    def _render_literals_results(self, context, request):
        """Render just the results section (grid + pagination) for OOB updates."""
        return render_to_string(
            "catalog/partials/literals_results_section.html", context, request=request
        )


__all__ = [
    "CatalogExplorerView",
    "CatalogExplorerPropertiesView",
    "CatalogExplorerLiteralsView",
]
