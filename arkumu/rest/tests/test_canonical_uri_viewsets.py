"""
Tests for Canonical URI Mapping REST API ViewSets.
"""

import json
import csv
from io import StringIO
from django.core.files.uploadedfile import SimpleUploadedFile

import pytest
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from django.contrib.auth import get_user_model

from arkumu.metadata.models import Resource, ResourceType
from arkumu.users.models import Organization

User = get_user_model()


@pytest.mark.django_db
class TestCanonicalUriViewSets(TestCase):
    """Test canonical URI mapping REST API viewsets."""
    
    def setUp(self):
        """Set up test data."""
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        
        # Create test organization
        self.organization = Organization.objects.create(
            name="Test Organization",
            code="test"
        )
        
        # Create test resources
        self.class_resource = Resource.objects.create(
            uri="http://test.org/test/types/akteurin",
            name="Akteurin",
            resource_type=ResourceType.CLASS,
            organization=self.organization
        )
        
        self.property_resource = Resource.objects.create(
            uri="http://test.org/test/properties/title",
            name="title",
            resource_type=ResourceType.PROPERTY,
            organization=self.organization
        )
        
        # Create authenticated API client
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
    
    def create_csv_file(self, content):
        """Helper to create CSV file for upload."""
        csv_buffer = StringIO()
        writer = csv.writer(csv_buffer)
        for row in content:
            writer.writerow(row)
        csv_content = csv_buffer.getvalue()
        return SimpleUploadedFile("test.csv", csv_content.encode('utf-8'), content_type="text/csv")
    
    def test_process_mappings_success(self):
        """Test successful processing of canonical URI mappings."""
        csv_content = [
            ['Type', 'Target', 'Label', 'Name'],
            ['Class', 'http://arkumu.org/types/akteurin', 'Akteurin', 'Akteurin'],
            ['Property', 'http://arkumu.org/properties/title', 'Title', 'title']
        ]
        
        csv_file = self.create_csv_file(csv_content)
        
        url = reverse('api:canonical-uri-process-mappings')
        response = self.client.post(
            url,
            {
                'organization_code': 'test',
                'csv_file': csv_file,
                'dry_run': False
            },
            format='multipart'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        self.assertTrue(data['success'])
        self.assertEqual(data['stats']['updated'], 2)
        self.assertEqual(len(data['stats']['not_found']), 0)
        
        # Check that resources were updated
        self.class_resource.refresh_from_db()
        self.property_resource.refresh_from_db()
        
        self.assertEqual(self.class_resource.canonical_uri, 'http://arkumu.org/types/akteurin')
        self.assertEqual(self.property_resource.canonical_uri, 'http://arkumu.org/properties/title')
    
    def test_process_mappings_dry_run(self):
        """Test dry run mode doesn't update resources."""
        csv_content = [
            ['Type', 'Target', 'Label', 'Name'],
            ['Class', 'http://arkumu.org/types/akteurin', 'Akteurin', 'Akteurin']
        ]
        
        csv_file = self.create_csv_file(csv_content)
        
        url = reverse('api:canonical-uri-process-mappings')
        response = self.client.post(
            url,
            {
                'organization_code': 'test',
                'csv_file': csv_file,
                'dry_run': True
            },
            format='multipart'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        self.assertTrue(data['success'])
        self.assertTrue(data['dry_run'])
        self.assertEqual(data['stats']['updated'], 1)
        
        # Check that resource was NOT updated
        self.class_resource.refresh_from_db()
        self.assertIsNone(self.class_resource.canonical_uri)
    
    def test_process_mappings_invalid_organization(self):
        """Test error handling for invalid organization."""
        csv_content = [['Type', 'Target', 'Label', 'Name']]
        csv_file = self.create_csv_file(csv_content)
        
        url = reverse('api:canonical-uri-process-mappings')
        response = self.client.post(
            url,
            {
                'organization_code': 'invalid',
                'csv_file': csv_file,
                'dry_run': False
            },
            format='multipart'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('Organization', data['error'])
    
    def test_validate_csv_success(self):
        """Test CSV validation endpoint."""
        csv_content = [
            ['Type', 'Target', 'Label', 'Name'],
            ['Class', 'http://arkumu.org/types/test', 'Test', 'TestResource']
        ]
        
        csv_file = self.create_csv_file(csv_content)
        
        url = reverse('api:canonical-uri-validate-csv')
        response = self.client.post(
            url,
            {
                'organization_code': 'test',
                'csv_file': csv_file
            },
            format='multipart'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        self.assertTrue(data['success'])
        self.assertTrue(data['is_valid'])
        self.assertEqual(len(data['errors']), 0)
        self.assertEqual(len(data['sample_rows']), 1)
    
    def test_validate_csv_invalid_format(self):
        """Test validation with invalid CSV format."""
        csv_content = [
            ['Type', 'Target'],  # Missing required columns
            ['Class', 'http://arkumu.org/types/test']
        ]
        
        csv_file = self.create_csv_file(csv_content)
        
        url = reverse('api:canonical-uri-validate-csv')
        response = self.client.post(
            url,
            {
                'organization_code': 'test',
                'csv_file': csv_file
            },
            format='multipart'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        self.assertTrue(data['success'])
        self.assertFalse(data['is_valid'])
        self.assertTrue(len(data['errors']) > 0)
    
    def test_get_unmapped_resources(self):
        """Test getting resources without canonical URIs."""
        # Create additional unmapped resource
        Resource.objects.create(
            uri="http://test.org/test/types/unmapped",
            name="UnmappedResource",
            resource_type=ResourceType.CLASS,
            organization=self.organization
        )
        
        url = reverse('api:canonical-uri-get-unmapped-resources')
        response = self.client.get(url, {
            'organization_code': 'test',
            'resource_type': 'class'
        })
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        self.assertTrue(data['success'])
        self.assertEqual(len(data['unmapped_resources']), 2)  # Both class resources
        self.assertEqual(data['total_count'], 2)
        self.assertEqual(data['organization'], 'Test Organization')
    
    def test_get_unmapped_resources_with_limit(self):
        """Test limiting unmapped resources results."""
        # Create multiple unmapped resources
        for i in range(5):
            Resource.objects.create(
                uri=f"http://test.org/test/types/unmapped{i}",
                name=f"Unmapped{i}",
                resource_type=ResourceType.CLASS,
                organization=self.organization
            )
        
        url = reverse('api:canonical-uri-get-unmapped-resources')
        response = self.client.get(url, {
            'organization_code': 'test',
            'limit': '3'
        })
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        self.assertTrue(data['success'])
        self.assertEqual(len(data['unmapped_resources']), 3)  # Limited to 3
        self.assertEqual(data['total_count'], 7)  # Total is 7 (2 original + 5 new)
    
    def test_batch_update_canonical_uris(self):
        """Test batch updating canonical URIs."""
        request_data = {
            'organization_code': 'test',
            'updates': [
                {
                    'resource_name': 'Akteurin',
                    'resource_type': 'class',
                    'canonical_uri': 'http://arkumu.org/types/akteurin'
                },
                {
                    'resource_name': 'title',
                    'resource_type': 'property',
                    'canonical_uri': 'http://arkumu.org/properties/title'
                }
            ],
            'dry_run': False
        }
        
        url = reverse('api:canonical-uri-batch-update')
        response = self.client.post(url, request_data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        self.assertTrue(data['success'])
        self.assertEqual(data['updated'], 2)
        self.assertEqual(len(data['not_found']), 0)
        
        # Check that resources were updated
        self.class_resource.refresh_from_db()
        self.property_resource.refresh_from_db()
        
        self.assertEqual(self.class_resource.canonical_uri, 'http://arkumu.org/types/akteurin')
        self.assertEqual(self.property_resource.canonical_uri, 'http://arkumu.org/properties/title')
    
    def test_batch_update_with_not_found(self):
        """Test batch update with non-existent resources."""
        request_data = {
            'organization_code': 'test',
            'updates': [
                {
                    'resource_name': 'NonExistent',
                    'resource_type': 'class',
                    'canonical_uri': 'http://arkumu.org/types/nonexistent'
                }
            ],
            'dry_run': False
        }
        
        url = reverse('api:canonical-uri-batch-update')
        response = self.client.post(url, request_data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        self.assertTrue(data['success'])
        self.assertEqual(data['updated'], 0)
        self.assertEqual(len(data['not_found']), 1)
        self.assertIn('class: NonExistent', data['not_found'])
    
    def test_authentication_required(self):
        """Test that authentication is required for API endpoints."""
        # Create unauthenticated client
        client = APIClient()
        
        # Test process endpoint
        url = reverse('api:canonical-uri-process-mappings')
        response = client.post(url, {'organization_code': 'test'})
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])
        
        # Test validate endpoint
        url = reverse('api:canonical-uri-validate-csv')
        response = client.post(url, {'organization_code': 'test'})
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])
        
        # Test unmapped endpoint
        url = reverse('api:canonical-uri-get-unmapped-resources')
        response = client.get(url, {'organization_code': 'test'})
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])
        
        # Test batch update endpoint
        url = reverse('api:canonical-uri-batch-update')
        response = client.post(url, {'organization_code': 'test'}, format='json')
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])