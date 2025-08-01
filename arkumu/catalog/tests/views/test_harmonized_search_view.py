"""
Tests for HarmonizedSearchView.
"""
import pytest
from django.test import Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from arkumu.metadata.models import Resource, Triple
from arkumu.users.models import Organization
from arkumu.metadata.models.resource import ResourceType, PublicAccessLevel

User = get_user_model()


@pytest.mark.django_db
class TestHarmonizedSearchView:
    """Test the main harmonized search view."""
    
    @pytest.fixture
    def client(self):
        """Create test client."""
        return Client()
    
    @pytest.fixture
    def search_setup(self):
        """Set up data for search view testing."""
        organization = Organization.objects.create(
            name="Test University",
            code="TEST_UNI"
        )
        
        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            organization=organization
        )
        
        # Create harmonized project
        project = Resource.objects.create(
            organization=organization,
            uri='http://test-uni.de/project/123',
            name='Test Harmonized Project',
            resource_type=ResourceType.IRI,
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True
        )
        
        # Add harmonization mapping
        owl_sameas = Resource.objects.create(
            uri='http://www.w3.org/2002/07/owl#sameAs',
            name='owl:sameAs',
            resource_type=ResourceType.PROPERTY
        )
        
        catalog_resource = Resource.objects.create(
            uri='http://data.arkumu.org/catalog/project',
            name='Catalog Project',
            resource_type=ResourceType.CLASS
        )
        
        Triple.objects.create(
            subject=project,
            predicate=owl_sameas,
            object=catalog_resource
        )
        
        return {
            'user': user,
            'organization': organization,
            'project': project
        }


class TestSearchPageAccess(TestHarmonizedSearchView):
    """Test basic access to search page."""
    
    def test_search_page_requires_login(self, client):
        """Test that search page requires authentication."""
        response = client.get(reverse('catalog:search'))
        
        # Should redirect to login
        assert response.status_code == 302
        assert '/accounts/login/' in response.url
    
    def test_search_page_loads_for_authenticated_user(self, client, search_setup):
        """Test that search page loads for authenticated users."""
        data = search_setup
        client.force_login(data['user'])
        
        response = client.get(reverse('catalog:search'))
        
        assert response.status_code == 200
        assert 'search_results.html' in [t.name for t in response.templates]
    
    def test_search_page_contains_search_form(self, client, search_setup):
        """Test that search page contains the expected form elements."""
        data = search_setup
        client.force_login(data['user'])
        
        response = client.get(reverse('catalog:search'))
        content = response.content.decode()
        
        # Should contain search form elements
        assert 'name="q"' in content  # Search query input
        assert 'name="type"' in content  # Resource type selector
        assert 'hx-get' in content  # HTMX attributes


class TestSearchFunctionality(TestHarmonizedSearchView):
    """Test search functionality through the view."""
    
    def test_search_with_query_parameter(self, client, search_setup):
        """Test search with query parameter."""
        data = search_setup
        client.force_login(data['user'])
        
        response = client.get(reverse('catalog:search'), {
            'q': 'Test',
            'type': 'projects'
        })
        
        assert response.status_code == 200
        
        # Should include search results
        context = response.context
        assert 'results' in context
        assert 'search_query' in context
        assert context['search_query'] == 'Test'
    
    def test_search_with_resource_type_filter(self, client, search_setup):
        """Test search with resource type filtering."""
        data = search_setup
        client.force_login(data['user'])
        
        response = client.get(reverse('catalog:search'), {
            'type': 'projects'
        })
        
        assert response.status_code == 200
        
        context = response.context
        assert 'selected_type' in context
        assert context['selected_type'] == 'projects'
    
    def test_search_with_facet_filters(self, client, search_setup):
        """Test search with facet filtering."""
        data = search_setup
        client.force_login(data['user'])
        
        response = client.get(reverse('catalog:search'), {
            'type': 'projects',
            'faechergruppe': 'Computer Science'
        })
        
        assert response.status_code == 200
        
        # Should process facet filters
        context = response.context
        assert 'selected_facets' in context


class TestHTMXLiveSearch(TestHarmonizedSearchView):
    """Test HTMX live search functionality."""
    
    def test_live_search_endpoint(self, client, search_setup):
        """Test the live search filter endpoint."""
        data = search_setup
        client.force_login(data['user'])
        
        response = client.get(reverse('catalog:live_filter'), {
            'q': 'Test',
            'type': 'projects'
        }, HTTP_HX_REQUEST='true')
        
        # HTMX requests should return 200
        assert response.status_code == 200
    
    def test_live_search_returns_oob_updates(self, client, search_setup):
        """Test that live search returns out-of-band updates."""
        data = search_setup
        client.force_login(data['user'])
        
        response = client.get(reverse('catalog:live_filter'), {
            'q': 'Test',
            'type': 'projects'
        }, HTTP_HX_REQUEST='true')
        
        content = response.content.decode()
        
        # Should contain OOB swap elements
        assert 'hx-swap-oob' in content
        assert 'id="search-results"' in content or 'id="result-count"' in content
    
    def test_live_search_without_htmx_header(self, client, search_setup):
        """Test live search endpoint without HTMX header."""
        data = search_setup
        client.force_login(data['user'])
        
        response = client.get(reverse('catalog:live_filter'), {
            'q': 'Test',
            'type': 'projects'
        })
        
        # Should still work (fallback behavior)
        assert response.status_code == 200


class TestContextData(TestHarmonizedSearchView):
    """Test context data provided to templates."""
    
    def test_context_includes_required_data(self, client, search_setup):
        """Test that context includes all required data."""
        data = search_setup
        client.force_login(data['user'])
        
        response = client.get(reverse('catalog:search'), {
            'type': 'projects'
        })
        
        context = response.context
        
        # Should include all required context variables
        required_keys = [
            'results',
            'search_query', 
            'selected_type',
            'available_types',
            'all_properties',
            'searchable_properties',
            'facets',
            'selected_facets',
            'result_count'
        ]
        
        for key in required_keys:
            assert key in context, f"Missing required context key: {key}"
    
    def test_context_available_types_structure(self, client, search_setup):
        """Test structure of available_types in context."""
        data = search_setup
        client.force_login(data['user'])
        
        response = client.get(reverse('catalog:search'))
        
        available_types = response.context['available_types']
        
        assert isinstance(available_types, list)
        if available_types:  # If not empty
            for type_info in available_types:
                assert 'key' in type_info
                assert 'label' in type_info  
                assert 'count' in type_info
    
    def test_context_facets_structure(self, client, search_setup):
        """Test structure of facets in context."""
        data = search_setup
        client.force_login(data['user'])
        
        response = client.get(reverse('catalog:search'), {
            'type': 'projects'
        })
        
        facets = response.context['facets']
        
        assert isinstance(facets, dict)
        # Each facet should be a list of value objects
        for facet_key, facet_values in facets.items():
            assert isinstance(facet_values, list)


class TestErrorHandling(TestHarmonizedSearchView):
    """Test error handling in search views."""
    
    def test_search_with_invalid_parameters(self, client, search_setup):
        """Test search with invalid parameters doesn't crash."""
        data = search_setup
        client.force_login(data['user'])
        
        response = client.get(reverse('catalog:search'), {
            'type': 'invalid-type',
            'q': 'test',
            'invalid_param': 'invalid_value'
        })
        
        # Should not crash, return valid response
        assert response.status_code == 200
    
    def test_live_search_with_malformed_request(self, client, search_setup):
        """Test live search with malformed request."""
        data = search_setup
        client.force_login(data['user'])
        
        response = client.get(reverse('catalog:live_filter'), {
            'type': '',  # Empty type
            'q': '',     # Empty query
        }, HTTP_HX_REQUEST='true')
        
        # Should handle gracefully
        assert response.status_code == 200