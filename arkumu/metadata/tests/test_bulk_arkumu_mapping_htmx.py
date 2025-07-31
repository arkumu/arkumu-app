"""
Tests for HTMX-powered Bulk Arkumu Mapping Views

Tests verify that the HTMX conversion correctly handles preview functionality
without requiring separate AJAX endpoints or JavaScript.
"""

import pytest
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from unittest.mock import patch, Mock

from arkumu.users.models import Organization
from arkumu.metadata.services.bulk_arkumu_mapping_service import BulkArkumuMappingService

User = get_user_model()


@pytest.mark.django_db
class TestBulkArkumuMappingHTMX(TestCase):
    """Test HTMX functionality for bulk mapping preview."""
    
    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.client.force_login(self.user)
        
        # Create test organizations
        self.org1 = Organization.objects.create(
            name='Test Org 1',
            code='TEST1',
            is_active=True
        )
        self.org2 = Organization.objects.create(
            name='Test Org 2', 
            code='TEST2',
            is_active=True
        )
        
        self.url = reverse('metadata:bulk_arkumu_mapping')
    
    def test_main_view_loads_without_htmx(self):
        """Test that main view loads correctly for regular requests."""
        response = self.client.get(self.url)
        
        assert response.status_code == 200
        assert 'Quick Preview' in response.content.decode()
        assert 'hx-post' in response.content.decode(), "HTMX attributes should be present"
        assert 'hx-target' in response.content.decode(), "HTMX target should be present"
        
    @patch.object(BulkArkumuMappingService, 'preview_bulk_mapping')
    @patch.object(BulkArkumuMappingService, 'validate_organization_codes')
    @patch.object(BulkArkumuMappingService, 'get_existing_mappings_count')
    def test_htmx_preview_request_success(self, mock_existing_counts, mock_validate, mock_preview):
        """Test successful HTMX preview request."""
        # Mock service responses
        mock_validate.return_value = (['TEST1', 'TEST2'], [])
        mock_preview.return_value = {
            'TEST1': [
                {
                    'source_iri': 'http://test1.com/class1',
                    'target_iri': 'http://arkumu.com/class1', 
                    'resource_type': 'Class'
                }
            ],
            'TEST2': [
                {
                    'source_iri': 'http://test2.com/prop1',
                    'target_iri': 'http://arkumu.com/prop1',
                    'resource_type': 'Property'
                }
            ]
        }
        mock_existing_counts.return_value = {'TEST1': 5, 'TEST2': 3}
        
        # Make HTMX preview request
        response = self.client.post(self.url, {
            'organizations': [self.org1.pk, self.org2.pk],
            'mapping_type': 'exact',
            'priority': '10',
            'preview': 'true'
        }, HTTP_HX_REQUEST='true')
        
        assert response.status_code == 200
        content = response.content.decode()
        
        # Check that response contains preview data
        assert 'Found <strong>2</strong> potential new mappings' in content
        assert 'TEST1' in content
        assert 'TEST2' in content
        assert '1 new mapping' in content  # Each org has 1 mapping
        assert '5 existing' in content
        assert '3 existing' in content
        
        # Check service was called correctly
        mock_validate.assert_called_once_with(['TEST1', 'TEST2'])
        mock_preview.assert_called_once_with(['TEST1', 'TEST2'])
        mock_existing_counts.assert_called_once_with(['TEST1', 'TEST2'])
    
    @patch.object(BulkArkumuMappingService, 'validate_organization_codes')
    def test_htmx_preview_invalid_organizations(self, mock_validate):
        """Test HTMX preview with invalid organization codes."""
        mock_validate.return_value = (['TEST1'], ['INVALID'])
        
        response = self.client.post(self.url, {
            'organizations': [self.org1.pk],
            'mapping_type': 'exact', 
            'priority': '10',
            'preview': 'true'
        }, HTTP_HX_REQUEST='true')
        
        assert response.status_code == 200
        content = response.content.decode()
        assert 'Invalid organization codes: INVALID' in content
        assert 'alert-danger' in content
    
    def test_htmx_preview_no_organizations_selected(self):
        """Test HTMX preview with no organizations selected."""
        response = self.client.post(self.url, {
            'organizations': [],
            'mapping_type': 'exact',
            'priority': '10', 
            'preview': 'true'
        }, HTTP_HX_REQUEST='true')
        
        assert response.status_code == 200
        content = response.content.decode()
        assert 'Please select at least one organization' in content
        assert 'alert-danger' in content
    
    @patch.object(BulkArkumuMappingService, 'preview_bulk_mapping')
    @patch.object(BulkArkumuMappingService, 'validate_organization_codes')
    def test_htmx_preview_service_error(self, mock_validate, mock_preview):
        """Test HTMX preview when service throws an error."""
        mock_validate.return_value = (['TEST1'], [])
        mock_preview.side_effect = Exception('Service error')
        
        response = self.client.post(self.url, {
            'organizations': [self.org1.pk],
            'mapping_type': 'exact',
            'priority': '10',
            'preview': 'true'
        }, HTTP_HX_REQUEST='true')
        
        assert response.status_code == 200
        content = response.content.decode()
        assert 'Error generating preview: Service error' in content
        assert 'alert-danger' in content
    
    def test_regular_form_submission_still_works(self):
        """Test that regular form submission (non-HTMX) still works."""
        with patch.object(BulkArkumuMappingService, 'validate_organization_codes') as mock_validate:
            mock_validate.return_value = (['TEST1'], [])
            
            response = self.client.post(self.url, {
                'organizations': [self.org1.pk],
                'mapping_type': 'exact',
                'priority': '10',
                'preview_only': True
            })
            
            # Should redirect to preview page (existing functionality)
            assert response.status_code == 302
            assert 'bulk_arkumu_mapping_preview' in response.url
    
    def test_form_validation_errors_in_htmx(self):
        """Test form validation errors are handled properly in HTMX."""
        response = self.client.post(self.url, {
            'organizations': [],  # Required field
            'mapping_type': '',   # Required field
            'priority': 'invalid', # Invalid integer
            'preview': 'true'
        }, HTTP_HX_REQUEST='true')
        
        assert response.status_code == 200
        content = response.content.decode()
        assert 'Please correct the form errors' in content
        assert 'alert-danger' in content
    
    def test_htmx_headers_properly_detected(self):
        """Test that HTMX requests are properly detected."""
        # Without HX-Request header - should be treated as regular request
        response = self.client.post(self.url, {
            'organizations': [self.org1.pk],
            'mapping_type': 'exact',
            'priority': '10',
            'preview': 'true'
        })
        
        # Should redirect (regular form handling)
        assert response.status_code == 302
        
        # With HX-Request header - should return HTML fragment
        response = self.client.post(self.url, {
            'organizations': [self.org1.pk],
            'mapping_type': 'exact', 
            'priority': '10',
            'preview': 'true'
        }, HTTP_HX_REQUEST='true')
        
        # Should return HTML fragment (200)
        assert response.status_code == 200


@pytest.mark.django_db
class TestBulkArkumuMappingHTMXIntegration(TestCase):
    """Integration tests for the complete HTMX workflow."""
    
    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.user = User.objects.create_user(
            username='integrationuser',
            email='integration@example.com',
            password='testpass123'
        )
        self.client.force_login(self.user)
        
        self.org = Organization.objects.create(
            name='Integration Test Org',
            code='INTEG',
            is_active=True
        )
        
        self.url = reverse('metadata:bulk_arkumu_mapping')
    
    def test_complete_htmx_workflow(self):
        """Test the complete HTMX workflow from form to preview."""
        # Step 1: Load the main form
        response = self.client.get(self.url)
        assert response.status_code == 200
        
        # Step 2: Submit HTMX preview request
        with patch.object(BulkArkumuMappingService, 'validate_organization_codes') as mock_validate, \
             patch.object(BulkArkumuMappingService, 'preview_bulk_mapping') as mock_preview, \
             patch.object(BulkArkumuMappingService, 'get_existing_mappings_count') as mock_existing:
            
            mock_validate.return_value = (['INTEG'], [])
            mock_preview.return_value = {
                'INTEG': [
                    {
                        'source_iri': 'http://integration.com/test',
                        'target_iri': 'http://arkumu.com/test',
                        'resource_type': 'Class'
                    }
                ]
            }
            mock_existing.return_value = {'INTEG': 0}
            
            preview_response = self.client.post(self.url, {
                'organizations': [self.org.pk],
                'mapping_type': 'exact',
                'priority': '5',
                'preview': 'true'
            }, HTTP_HX_REQUEST='true')
            
            assert preview_response.status_code == 200
            preview_content = preview_response.content.decode()
            
            # Verify preview content
            assert 'Found <strong>1</strong> potential new mappings' in preview_content
            assert 'INTEG' in preview_content
            assert 'http://integration.com/test' in preview_content
            assert 'http://arkumu.com/test' in preview_content
            assert 'Create 1 Mapping' in preview_content