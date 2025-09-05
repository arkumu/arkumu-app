"""
Example usage of the SearchService.

This demonstrates how to use the new SearchService to handle various search operations
in the catalog application.
"""

from arkumu.catalog.services import SearchService


def example_search_operations(user):
    """Example of using SearchService for different search operations."""
    
    # Initialize service
    search_service = SearchService(similarity_threshold=0.3)
    
    # 1. Basic full-text search
    print("=== Basic Full-Text Search ===")
    results = search_service.search("climate change", user)
    print(f"Found {results.count()} results for 'climate change'")
    for result in results[:3]:
        print(f"- {result.name}: {result.value[:50]}...")
    
    # 2. Exact search
    print("\n=== Exact Search ===")
    exact_results = search_service.search("Temperature Data", user, search_type='exact')
    print(f"Exact matches: {exact_results.count()}")
    
    # 3. Fuzzy search (typo tolerance)
    print("\n=== Fuzzy Search ===")
    fuzzy_results = search_service.search("climat", user, search_type='fuzzy')
    print(f"Fuzzy matches for 'climat': {fuzzy_results.count()}")
    
    # 4. Search suggestions/autocomplete
    print("\n=== Search Suggestions ===")
    suggestions = search_service.get_search_suggestions("clim", user, limit=5)
    print(f"Suggestions for 'clim': {suggestions}")
    
    # 5. Faceted search with filters
    print("\n=== Faceted Search ===")
    faceted_results = search_service.faceted_search(
        query="climate",
        facets={
            "year": ["2023", "2024"],
            "region": ["africa"]
        },
        limit=10
    )
    print(f"Faceted search results: {len(faceted_results.get('resources', []))}")
    print(f"Available facets: {list(faceted_results.get('facets', {}).keys())}")
    
    # 6. Multi-field search with boosting
    print("\n=== Multi-Field Search ===")
    multi_results = search_service.multi_field_search(
        "temperature",
        user,
        fields=['name', 'value'],
        boost_scores={'name': 2.0, 'value': 1.0}  # Boost name matches
    )
    print(f"Multi-field results: {multi_results.count()}")
    
    # 7. Build filters from request parameters
    print("\n=== Filter Building ===")
    request_params = {
        'q': 'climate change',
        'type': 'dataset',
        'limit': '20',
        'facet_year': ['2023'],
        'facet_region': 'global'
    }
    filters = search_service.build_search_filters(request_params)
    print(f"Built filters: {filters}")
    
    # 8. Get search snippet with highlighting
    print("\n=== Search Snippets ===")
    if results.exists():
        resource = results.first()
        snippet = search_service.get_search_snippet(
            resource, 
            "climate", 
            max_length=200
        )
        print(f"Snippet: {snippet}")
    
    # 9. Log search analytics
    search_service.log_search_analytics(
        query="climate change",
        results_count=results.count(),
        user_id=user.id if hasattr(user, 'id') else None,
        search_type="full_text"
    )
    print("Search analytics logged")


def example_view_integration():
    """Example of integrating SearchService into views."""
    
    from django.http import JsonResponse
    from django.views import View
    
    class SearchAPIView(View):
        def __init__(self):
            super().__init__()
            self.search_service = SearchService()
        
        def get(self, request):
            """Handle search API requests."""
            # Parse search parameters
            filters = self.search_service.build_search_filters(request.GET)
            
            # Perform search based on parameters
            if filters.get('facets'):
                # Faceted search
                results = self.search_service.faceted_search(
                    query=filters.get('query'),
                    facets=filters.get('facets'),
                    resource_type=filters.get('resource_type'),
                    limit=filters.get('limit', 100)
                )
                
                return JsonResponse({
                    'results': [
                        {'id': r.id, 'name': r.name, 'value': r.value}
                        for r in results.get('resources', [])[:10]
                    ],
                    'facets': results.get('facets', {}),
                    'count': results.get('count', 0)
                })
            else:
                # Regular search
                results = self.search_service.search(
                    filters.get('query', ''),
                    request.user,
                    limit=filters.get('limit', 100)
                )
                
                return JsonResponse({
                    'results': [
                        {'id': r.id, 'name': r.name, 'value': r.value}
                        for r in results[:10]
                    ],
                    'count': results.count()
                })
    
    class AutocompleteAPIView(View):
        def __init__(self):
            super().__init__()
            self.search_service = SearchService()
        
        def get(self, request):
            """Handle autocomplete requests."""
            query = request.GET.get('q', '')
            suggestions = self.search_service.get_search_suggestions(
                query, 
                request.user, 
                limit=10
            )
            
            return JsonResponse({
                'suggestions': suggestions
            })


def example_template_usage():
    """Example of using SearchService in templates via context processors or template tags."""
    
    # This would go in a context processor
    def search_context_processor(request):
        if not hasattr(request, 'user') or not request.user.is_authenticated:
            return {}
        
        search_service = SearchService()
        
        # Get recent popular searches for suggestions
        # (This would be implemented when search analytics are added)
        popular_searches = []
        
        return {
            'search_service': search_service,
            'popular_searches': popular_searches
        }
    
    # Template tag for search snippets
    from django import template
    
    register = template.Library()
    
    @register.simple_tag
    def search_snippet(resource, query, max_length=200):
        """Generate search snippet with highlighting."""
        search_service = SearchService()
        return search_service.get_search_snippet(resource, query, max_length)
    
    @register.simple_tag
    def search_suggestions(partial_query, user, limit=5):
        """Get search suggestions for autocomplete."""
        search_service = SearchService()
        return search_service.get_search_suggestions(partial_query, user, limit)


if __name__ == "__main__":
    print("SearchService Usage Examples")
    print("=" * 40)
    print()
    print("1. Import the service:")
    print("   from arkumu.catalog.services import SearchService")
    print()
    print("2. Initialize:")
    print("   search_service = SearchService(similarity_threshold=0.3)")
    print()
    print("3. Perform searches:")
    print("   results = search_service.search('climate change', user)")
    print("   suggestions = search_service.get_search_suggestions('clim', user)")
    print("   faceted = search_service.faceted_search(query='climate', facets={'year': ['2023']})")
    print()
    print("4. Use in views:")
    print("   See example_view_integration() function above")
    print()
    print("5. Template integration:")
    print("   {% load search_tags %}")
    print("   {% search_snippet resource query 200 %}")
    print("   {% search_suggestions 'clim' user 5 %}")