"""
SearchService - Specialized service for all search operations.

This service handles text queries, faceted search, autocomplete, and search intelligence.
It consolidates functionality from search_utils.py and long_content_search.py into a
unified, testable service layer.
"""

import time
from typing import List, Dict, Optional, Tuple, Any
from django.db.models import Q, F, Value, Count, QuerySet
from django.contrib.postgres.search import TrigramSimilarity, TrigramDistance
from django.utils.safestring import mark_safe
from django.template.defaultfilters import truncatewords
import re

from arkumu.metadata.models import Resource, Triple, ResourceType
from .base import BaseService


class SearchService(BaseService):
    """
    Specialized service for all search operations.
    Handles text queries, faceted search, autocomplete, and search intelligence.
    This is the ONLY service that should handle user search queries.
    """
    
    def __init__(self, similarity_threshold: float = 0.3):
        super().__init__()
        self.similarity_threshold = similarity_threshold
        self.preview_threshold = 0.4  # Higher threshold for preview search
        self._faceted_search_service = None
        
    def search(
        self,
        query: str,
        user,
        search_type: str = 'full_text',
        limit: int = 100
    ) -> QuerySet:
        """
        Main search method for any text-based query.
        
        Args:
            query: Search query string
            user: User making the request
            search_type: Type of search ('full_text', 'exact', 'fuzzy')
            limit: Maximum number of results
            
        Returns:
            QuerySet of matching resources
        """
        start_time = time.time()
        
        if not self._validate_user_access(user):
            return Resource.objects.none()
            
        if not query or len(query.strip()) < 2:
            self.logger.debug("Empty or too short query")
            return Resource.objects.none()
        
        query = query.strip()
        
        try:
            # Generate cache key
            cache_key = self._get_cache_key(
                'search',
                search_type,
                query,
                str(user.organization.id),
                str(limit)
            )
            
            # Check cache first
            cached_ids = self._cache_get(cache_key)
            if cached_ids is not None:
                results = Resource.objects.filter(id__in=cached_ids)
                duration = time.time() - start_time
                self._log_performance(
                    "search_cached", duration,
                    query_length=len(query),
                    result_count=len(cached_ids)
                )
                return results
            
            # Perform search based on type
            if search_type == 'exact':
                results = self._exact_search(query, user, limit)
            elif search_type == 'fuzzy':
                results = self._fuzzy_search(query, user, limit)
            else:  # full_text
                results = self._full_text_search(query, user, limit)
            
            # Cache results
            result_ids = [r.id for r in results]
            self._cache_set(cache_key, result_ids)
            
            duration = time.time() - start_time
            self._log_performance(
                "search", duration,
                search_type=search_type,
                query_length=len(query),
                result_count=len(result_ids)
            )
            
            return Resource.objects.filter(id__in=result_ids)
            
        except Exception as e:
            self._handle_error("search", e, query=query, search_type=search_type)
            return Resource.objects.none()
    
    def _full_text_search(self, query: str, user, limit: int) -> List[Resource]:
        """
        Intelligent search that combines preview and full content search.
        Uses optimized strategy based on query characteristics.
        """
        strategy = self._determine_search_strategy(query)
        
        if strategy == 'prefix':
            return self._prefix_search(query, user, limit)
        elif strategy == 'long_content':
            return self._long_content_search(query, user, limit)
        else:
            return self._trigram_search(query, user, limit)
    
    def _determine_search_strategy(self, query: str) -> str:
        """Determine optimal search strategy based on query characteristics."""
        # Short single words: use prefix search
        if len(query) <= 4 and ' ' not in query and query.isalnum():
            return 'prefix'
        
        # Long queries: use specialized long content search
        if len(query) > 50:
            return 'long_content'
        
        # Default: trigram search
        return 'trigram'
    
    def _prefix_search(self, query: str, user, limit: int) -> List[Resource]:
        """Fast prefix search for short queries."""
        return list(Resource.objects.for_user(user).filter(
            resource_type=ResourceType.LITERAL,
            value__istartswith=query
        ).order_by('value')[:limit])
    
    def _trigram_search(self, query: str, user, limit: int) -> List[Resource]:
        """Fuzzy search using GIN trigram index."""
        # Search in literal values
        literal_matches = Resource.objects.for_user(user).filter(
            resource_type=ResourceType.LITERAL
        ).annotate(
            similarity=TrigramSimilarity('value', query)
        ).filter(
            similarity__gt=self.similarity_threshold
        ).order_by('-similarity')[:limit]
        
        # Search in resource names and URIs
        name_matches = Resource.objects.for_user(user).exclude(
            resource_type=ResourceType.LITERAL
        ).annotate(
            similarity=TrigramSimilarity('name', query)
        ).filter(
            similarity__gt=self.similarity_threshold
        ).order_by('-similarity')[:limit//2]
        
        # Combine and deduplicate
        all_matches = list(literal_matches) + list(name_matches)
        seen = set()
        unique_matches = []
        
        for match in sorted(all_matches, key=lambda x: x.similarity, reverse=True):
            if match.id not in seen:
                seen.add(match.id)
                unique_matches.append(match)
                
        return unique_matches[:limit]
    
    def _long_content_search(self, query: str, user, limit: int) -> List[Resource]:
        """
        Multi-stage search for long content.
        Combines preview search with full content search.
        """
        # Stage 1: Fast preview search
        preview_matches = self._search_previews(query, user, limit * 2)
        preview_ids = {r.id for r in preview_matches}
        
        # Stage 2: Full content search if needed
        full_content_matches = []
        if len(preview_matches) < limit:
            remaining_limit = limit - len(preview_matches)
            full_content_matches = self._search_full_content(
                query, user, remaining_limit, exclude_ids=preview_ids
            )
        
        # Combine and rank results
        all_matches = list(preview_matches) + list(full_content_matches)
        return self._rank_by_relevance(all_matches, query)[:limit]
    
    def _search_previews(self, query: str, user, limit: int) -> List[Resource]:
        """Search using value_preview field for fast initial results."""
        from django.db import models
        
        return list(Resource.objects.for_user(user).filter(
            resource_type=ResourceType.LITERAL,
            value_preview__isnull=False
        ).annotate(
            similarity=TrigramSimilarity('value_preview', query),
            match_type=Value('preview', output_field=models.CharField())
        ).filter(
            similarity__gt=self.preview_threshold
        ).order_by('-similarity')[:limit])
    
    def _search_full_content(self, query: str, user, limit: int, exclude_ids: set) -> List[Resource]:
        """Search full content for long literals."""
        from django.db import models
        
        base_query = Resource.objects.for_user(user).filter(
            resource_type=ResourceType.LITERAL,
            has_long_content=True
        ).exclude(id__in=exclude_ids)
        
        if len(query) <= 4:
            # Short query - use contains for exact matches
            matches = base_query.filter(
                value__icontains=query
            ).annotate(
                similarity=Value(0.8, output_field=models.FloatField()),
                match_type=Value('full_exact', output_field=models.CharField())
            )[:limit]
        else:
            # Longer query - use trigram similarity
            matches = base_query.annotate(
                similarity=TrigramSimilarity('value', query),
                match_type=Value('full_trigram', output_field=models.CharField())
            ).filter(
                similarity__gt=self.similarity_threshold
            ).order_by('-similarity')[:limit]
        
        return list(matches)
    
    def _exact_search(self, query: str, user, limit: int) -> List[Resource]:
        """Exact match search."""
        return list(Resource.objects.for_user(user).filter(
            Q(value__iexact=query) | Q(name__iexact=query)
        )[:limit])
    
    def _fuzzy_search(self, query: str, user, limit: int, max_distance: int = 2) -> List[Resource]:
        """Fuzzy matching for typo tolerance."""
        return list(Resource.objects.for_user(user).annotate(
            distance=TrigramDistance('value', query)
        ).filter(
            distance__lt=0.7  # Distance threshold
        ).order_by('distance')[:limit])
    
    def _rank_by_relevance(self, resources: List[Resource], query: str) -> List[Resource]:
        """Rank search results by relevance."""
        def relevance_score(resource):
            score = getattr(resource, 'similarity', 0.0)
            
            # Boost for exact matches
            if hasattr(resource, 'value') and resource.value and query.lower() in resource.value.lower():
                score += 0.1
            
            # Boost for preview matches
            if getattr(resource, 'match_type', '') == 'preview':
                score += 0.05
            
            # Boost for shorter content
            if hasattr(resource, 'content_length') and resource.content_length and resource.content_length < 1000:
                score += 0.02
            
            return score
        
        return sorted(resources, key=relevance_score, reverse=True)
    
    def faceted_search(
        self,
        query: Optional[str] = None,
        facets: Optional[Dict[str, List[str]]] = None,
        resource_type: Optional[str] = None,
        limit: int = 100,
        user = None
    ) -> Dict:
        """
        Perform faceted search with aggregations.
        Returns results + facet counts for filtering UI.
        
        Args:
            query: Optional text search query
            facets: Dict mapping facet field names to selected values
            resource_type: Optional resource type filter
            limit: Maximum number of results
            
        Returns:
            Dict containing results, facet counts, and metadata
        """
        start_time = time.time()
        
        try:
            # Import and create FacetedSearchService with user context
            from .faceted_search_service import FacetedSearchService
            faceted_search_service = FacetedSearchService(user=user)
            
            # Use existing FacetedSearchService for now
            # This will be gradually refactored to use this service
            results = faceted_search_service.search_with_facets(
                search_query=query or "",
                property_filters=facets or {},
                resource_type=resource_type,
                limit=limit
            )
            
            duration = time.time() - start_time
            self._log_performance(
                "faceted_search", duration,
                has_query=bool(query),
                facet_count=len(facets) if facets else 0,
                result_count=len(results.get('resources', []))
            )
            
            return results
            
        except Exception as e:
            self._handle_error("faceted_search", e, query=query, facets=facets)
            return {
                'resources': [],
                'facets': {},
                'count': 0,
                'error': str(e)
            }
    
    def advanced_search(self, query_builder: Dict, user) -> QuerySet:
        """
        Execute advanced search with boolean operators.
        
        Args:
            query_builder: Complex query DSL dictionary
            user: User making the request
            
        Returns:
            QuerySet of matching resources
        """
        # Placeholder for advanced search implementation
        # This would parse query_builder and construct complex queries
        self.logger.info("Advanced search requested", extra={'query_builder': query_builder})
        return Resource.objects.none()
    
    def multi_field_search(
        self,
        query: str,
        user,
        fields: List[str],
        boost_scores: Optional[Dict[str, float]] = None
    ) -> QuerySet:
        """
        Search across specific fields with boosting.
        
        Args:
            query: Search query
            user: User making the request
            fields: List of field names to search
            boost_scores: Optional boost multipliers for fields
            
        Returns:
            QuerySet of matching resources
        """
        if not self._validate_user_access(user):
            return Resource.objects.none()
        
        boost_scores = boost_scores or {}
        
        # Build query for specified fields
        q_objects = Q()
        for field in fields:
            if field in ['value', 'name', 'uri']:
                q_objects |= Q(**{f"{field}__icontains": query})
        
        return Resource.objects.for_user(user).filter(q_objects)
    
    def get_search_suggestions(
        self,
        partial_query: str,
        user,
        limit: int = 10,
        context: Optional[Dict] = None
    ) -> List[str]:
        """
        Autocomplete suggestions based on partial query.
        
        Args:
            partial_query: Partial search string
            user: User making the request
            limit: Maximum number of suggestions
            context: Optional context for personalized suggestions
            
        Returns:
            List of suggestion strings
        """
        if not self._validate_user_access(user) or len(partial_query.strip()) < 2:
            return []
        
        try:
            cache_key = self._get_cache_key(
                'suggestions',
                partial_query,
                str(user.organization.id),
                str(limit)
            )
            
            suggestions = self._cache_get(cache_key)
            if suggestions is not None:
                return suggestions
            
            suggestions = self._generate_suggestions(partial_query, user, limit)
            self._cache_set(cache_key, suggestions, timeout=600)  # 10 minute cache
            
            return suggestions
            
        except Exception as e:
            self._handle_error("get_search_suggestions", e, query=partial_query)
            return []
    
    def _generate_suggestions(self, prefix: str, user, limit: int) -> List[str]:
        """Generate autocomplete suggestions."""
        prefix = prefix.strip()
        
        # For short prefixes, use starts-with
        if len(prefix) <= 4:
            suggestions = Resource.objects.for_user(user).filter(
                resource_type=ResourceType.LITERAL,
                value__istartswith=prefix
            ).values_list('value', flat=True).distinct()[:limit]
        else:
            # For longer prefixes, combine approaches
            prefix_suggestions = Resource.objects.for_user(user).filter(
                resource_type=ResourceType.LITERAL,
                value__istartswith=prefix
            ).values_list('value', flat=True)[:limit//2]
            
            trigram_suggestions = Resource.objects.for_user(user).filter(
                resource_type=ResourceType.LITERAL
            ).annotate(
                similarity=TrigramSimilarity('value', prefix)
            ).filter(
                similarity__gt=0.4
            ).values_list('value', flat=True)[:limit//2]
            
            suggestions = list(dict.fromkeys(list(prefix_suggestions) + list(trigram_suggestions)))
        
        return list(suggestions)[:limit]
    
    def get_related_searches(self, query: str, user) -> List[str]:
        """
        Get related search terms.
        
        Args:
            query: Original search query
            user: User making the request
            
        Returns:
            List of related search terms
        """
        # Placeholder for related search implementation
        # This could use search analytics, word embeddings, or co-occurrence analysis
        return []
    
    def get_facet_values(
        self,
        facet_field: str,
        user,
        query: Optional[str] = None,
        resource_type: Optional[str] = None
    ) -> List[Dict]:
        """
        Get available values for a specific facet.
        
        Args:
            facet_field: Name of the facet field
            user: User making the request  
            query: Optional search query to filter facet values
            resource_type: Optional resource type filter
            
        Returns:
            List of facet value dictionaries with counts
        """
        try:
            # Import and create FacetedSearchService with user context
            from .faceted_search_service import FacetedSearchService
            faceted_search_service = FacetedSearchService(user=user)
                
            return faceted_search_service.get_facet_values(
                facet_field, user, query, resource_type
            )
        except Exception as e:
            self._handle_error("get_facet_values", e, facet_field=facet_field)
            return []
    
    def build_search_filters(self, request_params: Dict) -> Dict:
        """
        Parse and validate search filters from request parameters.
        
        Args:
            request_params: Dictionary of request parameters
            
        Returns:
            Dictionary of validated search filters
        """
        filters = {}
        
        # Extract common search parameters
        if 'q' in request_params:
            filters['query'] = request_params['q'].strip()
        
        if 'type' in request_params:
            filters['resource_type'] = request_params['type']
        
        if 'limit' in request_params:
            try:
                filters['limit'] = min(int(request_params['limit']), 500)  # Cap at 500
            except (ValueError, TypeError):
                filters['limit'] = 100  # Default
        
        # Extract facet filters (parameters starting with 'facet_')
        facets = {}
        for key, value in request_params.items():
            if key.startswith('facet_'):
                facet_name = key[6:]  # Remove 'facet_' prefix
                if isinstance(value, list):
                    facets[facet_name] = value
                else:
                    facets[facet_name] = [value]
        
        if facets:
            filters['facets'] = facets
        
        return filters
    
    def get_search_history(self, user_id: Optional[int] = None) -> List[Dict]:
        """
        Get search history for personalization.
        
        Args:
            user_id: Optional user ID for personalized history
            
        Returns:
            List of search history entries
        """
        # Placeholder for search history implementation
        # This would integrate with analytics/tracking system
        return []
    
    def log_search_analytics(
        self,
        query: str,
        results_count: int,
        user_id: Optional[int] = None,
        **metadata
    ):
        """
        Track search queries for analytics.
        
        Args:
            query: Search query string
            results_count: Number of results returned
            user_id: Optional user ID
            **metadata: Additional metadata to track
        """
        try:
            # Log search analytics
            self.logger.info(
                "Search analytics",
                extra={
                    'query': query,
                    'results_count': results_count,
                    'user_id': user_id,
                    **metadata
                }
            )
        except Exception as e:
            self._handle_error("log_search_analytics", e, query=query)
    
    def get_search_snippet(self, resource: Resource, query: str, max_length: int = 300) -> str:
        """
        Extract relevant snippet from resource content around search terms.
        
        Args:
            resource: Resource to extract snippet from
            query: Search query to highlight
            max_length: Maximum snippet length
            
        Returns:
            Formatted snippet with search terms highlighted
        """
        if not resource.value:
            return resource.value_preview or ""
        
        # For short content, return as-is
        if len(resource.value) <= max_length:
            return self.highlight_search_terms(resource.value, query)
        
        # Find best snippet position
        snippet_start = self._find_best_snippet_position(resource.value, query, max_length)
        snippet_end = min(len(resource.value), snippet_start + max_length)
        
        # Extract snippet
        snippet = resource.value[snippet_start:snippet_end]
        
        # Add ellipsis indicators
        if snippet_start > 0:
            snippet = "..." + snippet
        if snippet_end < len(resource.value):
            snippet = snippet + "..."
        
        return self.highlight_search_terms(snippet, query)
    
    def _find_best_snippet_position(self, content: str, query: str, max_length: int) -> int:
        """Find optimal position for snippet extraction."""
        content_lower = content.lower()
        query_lower = query.lower()
        
        # Try exact query match first
        query_pos = content_lower.find(query_lower)
        if query_pos != -1:
            return max(0, query_pos - max_length // 3)
        
        # Find position with most query words
        query_words = query_lower.split()
        best_position = 0
        best_score = 0
        
        window_size = max_length
        for i in range(0, len(content) - window_size + 1, window_size // 4):
            window = content_lower[i:i + window_size]
            score = sum(1 for word in query_words if word in window)
            
            if score > best_score:
                best_score = score
                best_position = i
        
        return best_position
    
    def highlight_search_terms(self, text: str, query: str) -> str:
        """
        Highlight search terms in text.
        
        Args:
            text: Text to highlight
            query: Search query terms to highlight
            
        Returns:
            Text with highlighted search terms
        """
        if not query or not text:
            return text
        
        words = re.findall(r'\w+', query)
        if not words:
            return text
        
        pattern = '|'.join(re.escape(word) for word in words)
        
        def highlight_match(match):
            return f'<mark class="search-highlight">{match.group()}</mark>'
        
        highlighted = re.sub(
            f'({pattern})', 
            highlight_match, 
            text, 
            flags=re.IGNORECASE
        )
        
        return mark_safe(highlighted)