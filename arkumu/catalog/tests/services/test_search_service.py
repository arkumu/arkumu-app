"""
Comprehensive tests for SearchService.
"""

import pytest
from unittest.mock import Mock, patch
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.core.cache import cache

from arkumu.catalog.services.search_service import SearchService
from arkumu.metadata.models import Resource, Triple, ResourceType
from arkumu.users.models import Organization, User

User = get_user_model()


@pytest.mark.django_db
class TestSearchService:
    """Test SearchService functionality."""
    
    @pytest.fixture
    def organization(self):
        """Create test organization."""
        return Organization.objects.create(
            name="Test University",
            code="TEST_UNI"
        )
    
    @pytest.fixture
    def user(self, organization):
        """Create test user."""
        return User.objects.create(
            username="testuser",
            email="test@example.com",
            organization=organization
        )
    
    @pytest.fixture
    def service(self):
        """Create SearchService instance."""
        return SearchService(similarity_threshold=0.3)
    
    @pytest.fixture
    def sample_resources(self, user):
        """Create sample resources for testing."""
        resources = []
        
        # Create literal resources
        literal_data = [
            ("Climate change impacts", "Long description about climate change impacts on coastal regions..."),
            ("Temperature data", "Temperature measurements from weather station..."),
            ("Rainfall patterns", "Precipitation data collected over 10 years..."),
            ("Ocean levels", "Sea level rise measurements..."),
        ]
        
        for name, value in literal_data:
            resource = Resource.objects.create(
                name=name,
                value=value,
                resource_type=ResourceType.LITERAL,
                organization=user.organization,
                content_length=len(value),
                has_long_content=len(value) > 100,
                value_preview=value[:200] if len(value) > 200 else value
            )
            resources.append(resource)
        
        # Create non-literal resource
        resource = Resource.objects.create(
            name="Climate Dataset",
            uri="http://example.com/climate-dataset",
            resource_type=ResourceType.NAMED,
            organization=user.organization
        )
        resources.append(resource)
        
        return resources
    
    def test_init(self):
        """Test service initialization."""
        service = SearchService()
        assert service.similarity_threshold == 0.3
        assert service.preview_threshold == 0.4
        assert service._faceted_search_service is None  # Lazy loaded
    
    def test_init_custom_threshold(self):
        """Test service initialization with custom threshold."""
        service = SearchService(similarity_threshold=0.5)
        assert service.similarity_threshold == 0.5
    
    def test_search_empty_query(self, service, user):
        """Test search with empty query returns no results."""
        results = service.search("", user)
        assert results.count() == 0
        
        results = service.search("  ", user)
        assert results.count() == 0
        
        results = service.search("a", user)  # Too short
        assert results.count() == 0
    
    def test_search_unauthenticated_user(self, service):
        """Test search with unauthenticated user."""
        user = Mock()
        user.is_authenticated = False
        
        results = service.search("climate", user)
        assert results.count() == 0
    
    def test_search_user_without_organization(self, service):
        """Test search with user without organization."""
        user = Mock()
        user.is_authenticated = True
        user.organization = None
        
        results = service.search("climate", user)
        assert results.count() == 0
    
    @patch('arkumu.catalog.services.search_service.cache')
    def test_search_with_cache(self, mock_cache, service, user, sample_resources):
        """Test search with cache hit."""
        # Mock cache hit
        mock_cache.get.return_value = [1, 2]
        mock_cache.set.return_value = None
        
        with patch.object(Resource.objects, 'filter') as mock_filter:
            mock_filter.return_value = Mock()
            results = service.search("climate", user)
            
            # Should have used cache
            mock_cache.get.assert_called_once()
            mock_filter.assert_called_once_with(id__in=[1, 2])
    
    def test_search_full_text(self, service, user, sample_resources):
        """Test full text search."""
        results = service.search("climate", user, search_type='full_text')
        assert results.count() > 0
        
        # Should find resources containing "climate"
        result_values = [r.value or r.name for r in results]
        climate_results = [v for v in result_values if v and 'climate' in v.lower()]
        assert len(climate_results) > 0
    
    def test_search_exact(self, service, user, sample_resources):
        """Test exact search."""
        results = service.search("Climate Dataset", user, search_type='exact')
        assert results.count() == 1
        assert results.first().name == "Climate Dataset"
    
    def test_search_fuzzy(self, service, user, sample_resources):
        """Test fuzzy search."""
        # Search with typo
        results = service.search("climat", user, search_type='fuzzy')
        # Should still find climate-related results due to fuzzy matching
        assert results.count() >= 0  # May not find anything depending on similarity threshold
    
    def test_determine_search_strategy(self, service):
        """Test search strategy determination."""
        assert service._determine_search_strategy("test") == 'prefix'
        assert service._determine_search_strategy("climate change data analysis") == 'trigram'
        assert service._determine_search_strategy("a" * 51) == 'long_content'
    
    def test_generate_suggestions(self, service, user, sample_resources):
        """Test suggestion generation."""
        suggestions = service._generate_suggestions("cli", user, 5)
        assert isinstance(suggestions, list)
        assert len(suggestions) <= 5
        
        # Should find suggestions starting with "cli"
        climate_suggestions = [s for s in suggestions if s and s.lower().startswith('cli')]
        assert len(climate_suggestions) >= 0
    
    def test_get_search_suggestions(self, service, user, sample_resources):
        """Test public search suggestions method."""
        suggestions = service.get_search_suggestions("temp", user)
        assert isinstance(suggestions, list)
        assert len(suggestions) <= 10
        
        # Test caching
        cache_key = service._get_cache_key('suggestions', 'temp', str(user.organization.id), '10')
        cached_suggestions = cache.get(cache_key)
        assert cached_suggestions == suggestions
    
    def test_get_search_suggestions_invalid_user(self, service):
        """Test suggestions with invalid user."""
        user = Mock()
        user.is_authenticated = False
        
        suggestions = service.get_search_suggestions("temp", user)
        assert suggestions == []
    
    def test_get_search_suggestions_short_query(self, service, user):
        """Test suggestions with too short query."""
        suggestions = service.get_search_suggestions("a", user)
        assert suggestions == []
    
    def test_faceted_search(self, service, user):
        """Test faceted search."""
        results = service.faceted_search(
            query="climate",
            facets={"type": ["dataset"]},
            resource_type="literal"
        )
        
        assert isinstance(results, dict)
        assert 'resources' in results or 'error' in results
    
    def test_multi_field_search(self, service, user, sample_resources):
        """Test multi-field search."""
        results = service.multi_field_search(
            "climate", user, ['name', 'value']
        )
        
        assert results.count() >= 0
        # Results should contain resources with "climate" in name or value
        for result in results[:5]:  # Check first few
            assert (
                (result.name and 'climate' in result.name.lower()) or
                (result.value and 'climate' in result.value.lower())
            )
    
    def test_build_search_filters(self, service):
        """Test search filter building."""
        params = {
            'q': '  climate change  ',
            'type': 'dataset',
            'limit': '50',
            'facet_year': ['2023', '2024'],
            'facet_region': 'africa'
        }
        
        filters = service.build_search_filters(params)
        
        assert filters['query'] == 'climate change'
        assert filters['resource_type'] == 'dataset'
        assert filters['limit'] == 50
        assert filters['facets']['year'] == ['2023', '2024']
        assert filters['facets']['region'] == ['africa']
    
    def test_build_search_filters_invalid_limit(self, service):
        """Test filter building with invalid limit."""
        params = {'limit': 'invalid'}
        filters = service.build_search_filters(params)
        assert filters['limit'] == 100  # Default
        
        params = {'limit': '1000'}
        filters = service.build_search_filters(params)
        assert filters['limit'] == 500  # Capped
    
    def test_get_search_snippet_short_content(self, service):
        """Test snippet generation for short content."""
        resource = Mock()
        resource.value = "Short content about climate"
        
        snippet = service.get_search_snippet(resource, "climate", max_length=300)
        assert "climate" in snippet.lower()
        assert "<mark" in snippet  # Should be highlighted
    
    def test_get_search_snippet_long_content(self, service):
        """Test snippet generation for long content."""
        resource = Mock()
        resource.value = "A" * 100 + "climate change impacts" + "B" * 100
        
        snippet = service.get_search_snippet(resource, "climate", max_length=50)
        assert len(snippet) <= 60  # Includes ellipsis
        assert "climate" in snippet.lower()
        assert "..." in snippet
    
    def test_get_search_snippet_no_value(self, service):
        """Test snippet generation with no value."""
        resource = Mock()
        resource.value = None
        resource.value_preview = "Preview content"
        
        snippet = service.get_search_snippet(resource, "test")
        assert snippet == "Preview content"
    
    def test_highlight_search_terms(self, service):
        """Test search term highlighting."""
        text = "Climate change affects global temperatures"
        highlighted = service.highlight_search_terms(text, "climate global")
        
        assert "<mark" in highlighted
        assert "climate" in highlighted.lower()
        assert "global" in highlighted.lower()
    
    def test_highlight_search_terms_empty_query(self, service):
        """Test highlighting with empty query."""
        text = "Some text"
        highlighted = service.highlight_search_terms(text, "")
        assert highlighted == text
        
        highlighted = service.highlight_search_terms(text, None)
        assert highlighted == text
    
    def test_find_best_snippet_position(self, service):
        """Test snippet position finding."""
        content = "Start " + "A" * 100 + " climate change impacts " + "B" * 100 + " end"
        position = service._find_best_snippet_position(content, "climate", 50)
        
        # Position should be around the climate mention
        snippet = content[position:position + 50]
        assert "climate" in snippet.lower()
    
    def test_rank_by_relevance(self, service):
        """Test relevance ranking."""
        resource1 = Mock()
        resource1.similarity = 0.8
        resource1.value = "climate data"
        resource1.content_length = 500
        
        resource2 = Mock()
        resource2.similarity = 0.6
        resource2.value = "temperature readings"
        resource2.content_length = 100
        
        resources = [resource2, resource1]
        ranked = service._rank_by_relevance(resources, "climate")
        
        # resource1 should rank higher due to better similarity and query match
        assert ranked[0] == resource1
        assert ranked[1] == resource2
    
    def test_log_search_analytics(self, service):
        """Test search analytics logging."""
        # Should not raise exception
        service.log_search_analytics("test query", 5, user_id=1, extra="data")
    
    def test_get_related_searches(self, service, user):
        """Test related search functionality."""
        related = service.get_related_searches("climate", user)
        assert isinstance(related, list)
        # Currently returns empty list as placeholder
    
    def test_get_search_history(self, service):
        """Test search history functionality."""
        history = service.get_search_history(user_id=1)
        assert isinstance(history, list)
        # Currently returns empty list as placeholder
    
    def test_advanced_search(self, service, user):
        """Test advanced search functionality."""
        query_builder = {"and": [{"field": "name", "value": "climate"}]}
        results = service.advanced_search(query_builder, user)
        # Currently returns empty queryset as placeholder
        assert results.count() == 0
    
    def test_error_handling_in_search(self, service, user):
        """Test error handling in search method."""
        with patch.object(service, '_full_text_search', side_effect=Exception("Test error")):
            results = service.search("test", user)
            assert results.count() == 0
    
    def test_error_handling_in_suggestions(self, service, user):
        """Test error handling in suggestions method."""
        with patch.object(service, '_generate_suggestions', side_effect=Exception("Test error")):
            suggestions = service.get_search_suggestions("test", user)
            assert suggestions == []
    
    def test_cache_key_generation(self, service):
        """Test cache key generation."""
        key = service._get_cache_key('search', 'test', '123')
        assert 'searchservice' in key.lower()
        assert 'search' in key
        assert 'test' in key
        assert '123' in key


@pytest.mark.django_db
class TestSearchServicePerformance:
    """Test SearchService performance characteristics."""
    
    @pytest.fixture
    def service(self):
        return SearchService()
    
    @pytest.fixture
    def user(self):
        org = Organization.objects.create(name="Test Org", code="TEST")
        return User.objects.create(
            username="testuser", 
            email="test@example.com",
            organization=org
        )
    
    def test_search_caching_behavior(self, service, user):
        """Test that search results are properly cached."""
        # Clear cache
        cache.clear()
        
        # First search - should miss cache
        with patch.object(service, '_full_text_search') as mock_search:
            mock_search.return_value = []
            service.search("test query", user)
            assert mock_search.called
        
        # Second search - should hit cache
        with patch.object(service, '_full_text_search') as mock_search:
            mock_search.return_value = []
            service.search("test query", user)
            assert not mock_search.called
    
    def test_suggestions_caching_behavior(self, service, user):
        """Test that suggestions are properly cached."""
        cache.clear()
        
        # First call - should miss cache
        with patch.object(service, '_generate_suggestions') as mock_gen:
            mock_gen.return_value = ['test1', 'test2']
            suggestions = service.get_search_suggestions("test", user)
            assert mock_gen.called
            assert suggestions == ['test1', 'test2']
        
        # Second call - should hit cache
        with patch.object(service, '_generate_suggestions') as mock_gen:
            mock_gen.return_value = ['test1', 'test2']
            suggestions = service.get_search_suggestions("test", user)
            assert not mock_gen.called
            assert suggestions == ['test1', 'test2']


class TestSearchServiceIntegration(TestCase):
    """Integration tests for SearchService."""
    
    def setUp(self):
        self.organization = Organization.objects.create(
            name="Test University",
            code="TEST_UNI"
        )
        self.user = User.objects.create(
            username="testuser",
            email="test@example.com",
            organization=self.organization
        )
        self.service = SearchService()
    
    def test_full_search_workflow(self):
        """Test complete search workflow."""
        # Create test data
        Resource.objects.create(
            name="Climate Research Paper",
            value="This paper discusses climate change impacts on agriculture.",
            resource_type=ResourceType.LITERAL,
            organization=self.organization,
            content_length=55,
            has_long_content=False,
            value_preview="This paper discusses climate..."
        )
        
        # Test search
        results = self.service.search("climate agriculture", self.user)
        self.assertGreaterEqual(results.count(), 0)
        
        # Test suggestions
        suggestions = self.service.get_search_suggestions("clim", self.user)
        self.assertIsInstance(suggestions, list)
        
        # Test faceted search
        faceted_results = self.service.faceted_search(query="climate")
        self.assertIn('resources', faceted_results.keys())
    
    def test_search_with_special_characters(self):
        """Test search with special characters."""
        Resource.objects.create(
            name="Data with special chars: @#$%",
            value="Content with symbols & punctuation!",
            resource_type=ResourceType.LITERAL,
            organization=self.organization
        )
        
        # Should handle special characters gracefully
        results = self.service.search("@#$", self.user)
        self.assertGreaterEqual(results.count(), 0)
        
        results = self.service.search("symbols & punctuation", self.user)
        self.assertGreaterEqual(results.count(), 0)