# Catalog Explorer Endpoints Audit

Scope: Assess the new Catalog Explorer endpoints and identify deprecated/unused service usage, required removals, and targeted enhancements.

Access Points
- Catalog Explorer: `/catalog/explorer/`
- API Endpoint: `/catalog/explorer/api/`
- Graph Explorer: `/catalog/explorer/graph/`

Code Locations
- URL wiring: `arkumu/catalog/urls.py`
- Explorer views: `arkumu/catalog/views_explorer.py`
- Core catalog views: `arkumu/catalog/views.py`
- Services referenced:
  - Simple faceted: `arkumu/catalog/services/simple_faceted_search_service.py`
  - Faceted (legacy/complex): `arkumu/catalog/services/faceted_search_service.py`
  - Flexible catalog: `arkumu/catalog/services/flexible_catalog_service.py`
  - Canonical graph: `arkumu/metadata/services/canonical_graph_service.py`

## Findings At A Glance
- API view for explorer uses the wrong service (legacy `FacetedSearchService`) and contains bugs (undefined variables and response shape).
- Graph Explorer view references a non‑existent template (`catalog/graph_explorer.html`).
- Explorer view imports `FlexibleCatalogService` but does not use it.
- `FacetedSearchService` implementation shows multiple inconsistencies and appears legacy for explorer usage (undefined vars, mixed strategies), while `SimpleFacetedSearchService` is consistent with the explorer UI.
- Several service interfaces are misaligned (e.g., `SearchService.get_facet_values` calling `FacetedSearchService.get_facet_values` with a mismatched signature).

## Remove / Deprecate
- Explorer API dependency on legacy `FacetedSearchService`.
  - File: `arkumu/catalog/views_explorer.py` (class `CatalogExplorerAPIView`)
  - Symptoms:
    - Uses `FacetedSearchService` but does not import it.
    - Expects a dict result (`results['resources']`) which matches `SimpleFacetedSearchService`, not `FacetedSearchService` (which returns a QuerySet in `search_with_facets`).
    - References undefined variable `selected_facets` in the JSON response.
  - Action: Replace with `SimpleFacetedSearchService` and align response fields.

- Unused import/variable in Explorer template view.
  - File: `arkumu/catalog/views_explorer.py` (class `CatalogExplorerView`)
  - Issue: Instantiates `FlexibleCatalogService` but never uses it.
  - Action: Remove the unused import and variable to avoid confusion and potential import-time coupling.

- Treat `FacetedSearchService` as legacy for Explorer endpoints.
  - File: `arkumu/catalog/services/faceted_search_service.py`
  - Issues observed:
    - `search_resources` references undefined names (`harmonized_resources`, `base_access_filter` reuse, `harmonized_resource_ids`).
    - Logic overlaps with `CatalogNavigationService` and mixes harmonized/accessible strategies.
  - Action: Do not use this service in Explorer; keep for main catalog until refactor is planned.

## Enhance / Fix
- Explorer API behavior and payload
  - Switch to `SimpleFacetedSearchService`:
    - Import: `from arkumu.catalog.services.simple_faceted_search_service import SimpleFacetedSearchService`
    - Use `results = faceted_service.search_with_facets(...)` and then read `results['resources']`, `results['facets']`, `results['total_count']`.
  - Define `selected_facets` properly: use the parsed dict from `_parse_facets(request.GET)`.
  - Optional: Use `django.views.View` instead of `TemplateView` for clarity since this is JSON-only.
  - Consider adding basic input validation and consistent pagination controls (`limit`, `page`).

- Graph Explorer template
  - File: missing `arkumu/catalog/templates/catalog/graph_explorer.html` referenced by `CatalogGraphExplorerView`.
  - Options:
    - Add a minimal template that renders the graph metadata and dumps JSON for `graph_data`, or
    - Convert the view to return JSON (`JsonResponse`) for faster iteration.

- Type dropdown in Explorer
  - The `CatalogExplorerView` computes type counts server-side. Consider caching for 5–10 minutes to avoid repeated aggregation under load.

- Cleanup service exposure and docs
  - Add a clear note or docstring marking `FacetedSearchService` as legacy for explorer usage; prefer `SimpleFacetedSearchService` in explorer paths.
  - Ensure `SimpleFacetedSearchService` is exported if needed (optional) and referenced consistently where faceted behavior is simple, org-access-aware, and not harmonization-dependent.

## Risk / Impact Notes
- The main catalog views (`arkumu/catalog/views.py`) still use `FacetedSearchService`. Do not remove/alter that service without a broader refactor and test pass.
- Explorer endpoints are dev-focused (`LoginRequiredMixin`). Changes here are low-risk to public interfaces.
- Creating the missing graph template prevents runtime 500s on `/catalog/explorer/graph/`.

## Suggested Next Steps (Checklist)
- [ ] Update `CatalogExplorerAPIView` to use `SimpleFacetedSearchService` and fix `selected_facets`.
- [ ] Remove unused `FlexibleCatalogService` import/instantiation from `CatalogExplorerView`.
- [ ] Add `catalog/graph_explorer.html` (minimal) or switch to JSON response.
- [ ] Optionally cache `available_types` query in `CatalogExplorerView` (e.g., 10 minutes).
- [ ] Document Explorer endpoints in README or a short dev guide.
- [ ] Plan a separate refactor for `FacetedSearchService` or migrate main catalog search to a clearer, tested service.

## References
- URL config: `arkumu/catalog/urls.py` defines `/explorer/`, `/explorer/api/`, `/explorer/graph/`.
- Explorer view: `arkumu/catalog/views_explorer.py` uses `SimpleFacetedSearchService` for the page view, but API path uses legacy `FacetedSearchService`.
- Services:
  - Simple faceted: `arkumu/catalog/services/simple_faceted_search_service.py`
  - Faceted (legacy/complex): `arkumu/catalog/services/faceted_search_service.py`
  - Flexible catalog (experimental; unused in explorer): `arkumu/catalog/services/flexible_catalog_service.py`
  - Canonical graph for Graph Explorer: `arkumu/metadata/services/canonical_graph_service.py`

