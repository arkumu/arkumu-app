import pytest
from unittest.mock import Mock, patch
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from arkumu.catalog.views_explorer import CatalogExplorerView

User = get_user_model()


class TestGraphSearchView(TestCase):
    """Test the graph search view functionality."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.url = reverse('catalog:explorer')

    def test_view_requires_login(self):
        """Test that the view requires authentication."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_view_loads_for_authenticated_user(self):
        """Test that authenticated users can access the view."""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Graph Explorer')

    @patch('arkumu.catalog.views_explorer.GraphSearchService')
    def test_search_with_query_parameter(self, mock_service_class):
        """Test search with query parameter."""
        # Mock the service
        mock_service = Mock()
        mock_service_class.return_value = mock_service

        # Mock search results
        mock_service.search_by_property_with_graph.return_value = [
            {
                'entity_uri': 'http://example.org/entity/1',
                'entity_type': 'http://example.org/types/Project',
                'properties': {'name': 'Test Project'},
                'outgoing_relations': [],
                'incoming_relations': [],
                'connected_entities': []
            }
        ]

        # Mock class and property discovery
        mock_service.get_available_types.return_value = [
            {
                'uri': 'http://example.org/types/Project',
                'name': 'project',
                'display_name': 'Project',
                'count': 1
            }
        ]

        mock_service.get_available_properties.return_value = []

        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(self.url, {'q': 'test project'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Project')
        mock_service.search_by_property_with_graph.assert_called_once()

    @patch('arkumu.catalog.views_explorer.GraphSearchService')
    def test_api_endpoint(self, mock_service_class):
        """Test the JSON API endpoint."""
        # Mock the service
        mock_service = Mock()
        mock_service_class.return_value = mock_service

        # Mock search results
        mock_service.search_by_property_with_graph.return_value = [
            {
                'entity_uri': 'http://example.org/entity/1',
                'entity_type': 'http://example.org/types/Project',
                'properties': {'name': 'Test Project'},
                'outgoing_relations': [],
                'incoming_relations': [],
                'connected_entities': []
            }
        ]

        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(
            reverse('catalog:explorer_api'),
            {'q': 'test', 'class': 'http://example.org/types/Project'},
            HTTP_ACCEPT='application/json'
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')

        data = response.json()
        self.assertIn('results', data)
        self.assertEqual(len(data['results']), 1)
        self.assertEqual(data['results'][0]['title'], 'Test Project')

    def test_api_endpoint_requires_login(self):
        """Test that the API endpoint requires authentication."""
        response = self.client.get(reverse('catalog:explorer_api'))
        self.assertEqual(response.status_code, 302)

    @patch('arkumu.catalog.views_explorer.GraphSearchService')
    def test_api_error_handling(self, mock_service_class):
        """Test API error handling."""
        # Mock the service to raise an exception
        mock_service = Mock()
        mock_service_class.return_value = mock_service
        mock_service.search_by_property_with_graph.side_effect = Exception("Search failed")

        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(
            reverse('catalog:explorer_api'),
            {'q': 'test'},
            HTTP_ACCEPT='application/json'
        )

        self.assertEqual(response.status_code, 500)
        data = response.json()
        self.assertIn('error', data)