import pytest
import tempfile
import csv
import os
from django.test import TestCase
from arkumu.metadata.models import Resource, ResourceType
from arkumu.users.models import Organization
from arkumu.metadata.services.integration import CanonicalUriMappingService


@pytest.mark.django_db
class TestCanonicalUriMappingService(TestCase):
    """Test canonical URI mapping service functionality."""
    
    def setUp(self):
        """Set up test data."""
        # Create test organization
        self.organization = Organization.objects.create(
            name="Test Music Academy",
            code="tma"
        )
        
        # Create test resources
        self.class_resource1 = Resource.objects.create(
            uri="http://test.org/tma/types/akteurin",
            name="Akteurin",
            resource_type=ResourceType.CLASS,
            organization=self.organization
        )
        
        self.class_resource2 = Resource.objects.create(
            uri="http://test.org/tma/types/ereignis",
            name="Ereignis", 
            resource_type=ResourceType.CLASS,
            organization=self.organization
        )
        
        self.property_resource = Resource.objects.create(
            uri="http://test.org/tma/properties/title",
            name="title",
            resource_type=ResourceType.PROPERTY,
            organization=self.organization
        )

        # Resource whose name no longer matches the CSV but whose URI should match via slug fallback
        self.property_resource_slug = Resource.objects.create(
            uri="http://test.org/tma/properties/dat-id",
            name="identifier",
            resource_type=ResourceType.PROPERTY,
            organization=self.organization
        )
        
        # Create resource with existing canonical URI
        self.existing_canonical = Resource.objects.create(
            uri="http://test.org/tma/types/projekt",
            name="Projekt",
            resource_type=ResourceType.CLASS,
            organization=self.organization,
            canonical_uri="http://arkumu.org/types/existing-project"
        )
        
        self.service = CanonicalUriMappingService("tma")
    
    def test_service_initialization_success(self):
        """Test successful service initialization."""
        service = CanonicalUriMappingService("tma")
        self.assertEqual(service.organization, self.organization)
    
    def test_service_initialization_invalid_org(self):
        """Test service initialization with invalid organization."""
        with self.assertRaises(ValueError) as cm:
            CanonicalUriMappingService("invalid")
        self.assertIn("Organization with code 'invalid' not found", str(cm.exception))
    
    def test_parse_resource_type(self):
        """Test resource type parsing."""
        self.assertEqual(self.service._parse_resource_type("Class"), ResourceType.CLASS)
        self.assertEqual(self.service._parse_resource_type("class"), ResourceType.CLASS)
        self.assertEqual(self.service._parse_resource_type("Property"), ResourceType.PROPERTY)
        self.assertEqual(self.service._parse_resource_type("property"), ResourceType.PROPERTY)
        self.assertIsNone(self.service._parse_resource_type("invalid"))
    
    def test_get_resources_without_canonical_uri(self):
        """Test getting resources without canonical URIs."""
        # All resource types
        results = self.service.get_unmapped_resources()
        self.assertEqual(len(results), 3)  # 3 resources without canonical URI
        
        # Classes only
        class_results = self.service.get_unmapped_resources(ResourceType.CLASS)
        self.assertEqual(len(class_results), 2)  # 2 classes without canonical URI
        
        # Properties only
        prop_results = self.service.get_unmapped_resources(ResourceType.PROPERTY)
        self.assertEqual(len(prop_results), 1)  # 1 property without canonical URI
    
    def test_process_csv_success(self):
        """Test successful CSV processing."""
        # Create test CSV
        csv_content = [
            ['Type', 'Target', 'Label', 'Name'],
            ['Class', 'http://arkumu.org/types/akteurin', 'Akteurin', 'Akteurin'],
            ['Class', 'http://arkumu.org/types/ereignis', 'Ereignis', 'Ereignis'],
            ['Property', 'http://arkumu.org/properties/title', 'Title', 'title']
        ]
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            writer = csv.writer(f)
            writer.writerows(csv_content)
            csv_file = f.name
        
        try:
            # Process CSV
            stats = self.service.process_canonical_mappings(csv_file, dry_run=False)
            
            # Check stats
            self.assertEqual(stats['updated'], 3)
            self.assertEqual(len(stats['not_found']), 0)  # not_found is now a list
            self.assertEqual(stats['skipped'], 0)
            self.assertEqual(stats['errors'], 0)
            
            # Check that canonical URIs were set
            self.class_resource1.refresh_from_db()
            self.class_resource2.refresh_from_db()
            self.property_resource.refresh_from_db()
            
            self.assertEqual(self.class_resource1.canonical_uri, 'http://arkumu.org/types/akteurin')
            self.assertEqual(self.class_resource2.canonical_uri, 'http://arkumu.org/types/ereignis')
            self.assertEqual(self.property_resource.canonical_uri, 'http://arkumu.org/properties/title')
            
        finally:
            os.unlink(csv_file)

    def test_process_csv_matches_uri_slug_fallback(self):
        """Ensure we can match resources by slugified URI when names diverge."""
        csv_content = [
            ['Type', 'Target', 'Label', 'Name'],
            ['Property', 'http://arkumu.org/properties/digitales-objekt', 'Digital Object', 'DAT_ID']
        ]

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            writer = csv.writer(f)
            writer.writerows(csv_content)
            csv_file = f.name

        try:
            stats = self.service.process_canonical_mappings(csv_file, dry_run=False)
            self.assertEqual(stats['updated'], 1)

            self.property_resource_slug.refresh_from_db()
            self.assertEqual(
                self.property_resource_slug.canonical_uri,
                'http://arkumu.org/properties/digitales-objekt',
            )
        finally:
            os.unlink(csv_file)
    
    def test_process_csv_dry_run(self):
        """Test CSV processing in dry run mode."""
        csv_content = [
            ['Type', 'Target', 'Label', 'Name'],
            ['Class', 'http://arkumu.org/types/akteurin', 'Akteurin', 'Akteurin']
        ]
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            writer = csv.writer(f)
            writer.writerows(csv_content)
            csv_file = f.name
        
        try:
            # Process CSV in dry run mode
            stats = self.service.process_canonical_mappings(csv_file, dry_run=True)
            
            # Check stats
            self.assertEqual(stats['updated'], 1)
            
            # Check that canonical URI was NOT set
            self.class_resource1.refresh_from_db()
            self.assertIsNone(self.class_resource1.canonical_uri)
            
        finally:
            os.unlink(csv_file)
    
    def test_process_csv_multiple_resource_names(self):
        """Test CSV processing with comma-separated resource names."""
        # Create additional resource
        Resource.objects.create(
            uri="http://test.org/tma/types/koerperschaften",
            name="Koerperschaften",
            resource_type=ResourceType.CLASS,
            organization=self.organization
        )
        
        csv_content = [
            ['Type', 'Target', 'Label', 'Name'],
            ['Class', 'http://arkumu.org/types/akteurin', 'Akteurin', 'Akteurin,Koerperschaften']
        ]
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            writer = csv.writer(f)
            writer.writerows(csv_content)
            csv_file = f.name
        
        try:
            stats = self.service.process_canonical_mappings(csv_file, dry_run=False)
            
            # Should update 2 resources (both names matched)
            self.assertEqual(stats['updated'], 2)  # Both resources updated
            
            # Check both resources got updated
            resources_updated = Resource.objects.filter(
                organization=self.organization,
                canonical_uri='http://arkumu.org/types/akteurin'
            ).count()
            self.assertEqual(resources_updated, 2)
            
        finally:
            os.unlink(csv_file)
    
    def test_process_csv_resource_not_found(self):
        """Test CSV processing when resources are not found."""
        csv_content = [
            ['Type', 'Target', 'Label', 'Name'],
            ['Class', 'http://arkumu.org/types/nonexistent', 'Non-existent', 'NonExistent']
        ]
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            writer = csv.writer(f)
            writer.writerows(csv_content)
            csv_file = f.name
        
        try:
            stats = self.service.process_canonical_mappings(csv_file, dry_run=False)
            
            self.assertEqual(stats['updated'], 0)
            self.assertTrue(len(stats['not_found']) > 0)
            self.assertEqual(stats['skipped'], 0)
            self.assertEqual(stats['errors'], 0)
            
        finally:
            os.unlink(csv_file)
    
    def test_process_csv_invalid_rows(self):
        """Test CSV processing with invalid rows."""
        csv_content = [
            ['Type', 'Target', 'Label', 'Name'],
            ['', 'http://arkumu.org/types/empty-type', 'Empty Type', 'test'],  # Missing type
            ['Class', '', 'Empty Target', 'test'],  # Missing target
            ['InvalidType', 'http://arkumu.org/types/invalid', 'Invalid Type', 'test'],  # Invalid type
        ]
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            writer = csv.writer(f)
            writer.writerows(csv_content)
            csv_file = f.name
        
        try:
            stats = self.service.process_canonical_mappings(csv_file, dry_run=False)
            
            self.assertEqual(stats['updated'], 0)
            self.assertEqual(stats['skipped'], 3)  # All 3 rows should be skipped
            
        finally:
            os.unlink(csv_file)
    
    def test_validate_csv_format_valid(self):
        """Test CSV format validation with valid file."""
        csv_content = [
            ['Type', 'Target', 'Label', 'Name'],
            ['Class', 'http://arkumu.org/types/test', 'Test', 'test']
        ]
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            writer = csv.writer(f)
            writer.writerows(csv_content)
            csv_file = f.name
        
        try:
            is_valid, errors = self.service.validate_mapping_csv(csv_file)
            self.assertTrue(is_valid)
            self.assertEqual(len(errors), 0)
            
        finally:
            os.unlink(csv_file)
    
    def test_validate_csv_format_missing_columns(self):
        """Test CSV format validation with missing required columns."""
        csv_content = [
            ['Type', 'Label'],  # Missing Target column
            ['Class', 'Test']
        ]
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            writer = csv.writer(f)
            writer.writerows(csv_content)
            csv_file = f.name
        
        try:
            is_valid, errors = self.service.validate_mapping_csv(csv_file)
            self.assertFalse(is_valid)
            self.assertTrue(any('Missing required columns' in error for error in errors))
            
        finally:
            os.unlink(csv_file)
    
    def test_validate_csv_format_no_name_column(self):
        """Test CSV format validation with missing Name column."""
        csv_content = [
            ['Type', 'Target', 'Label'],  # Missing Name column
            ['Class', 'http://arkumu.org/types/test', 'Test']
        ]
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            writer = csv.writer(f)
            writer.writerows(csv_content)
            csv_file = f.name
        
        try:
            is_valid, errors = self.service.validate_mapping_csv(csv_file)
            self.assertFalse(is_valid)
            self.assertTrue(any('Missing required columns' in error for error in errors))
            
        finally:
            os.unlink(csv_file)
    
    def test_validate_csv_format_invalid_data(self):
        """Test CSV format validation with invalid data."""
        csv_content = [
            ['Type', 'Target', 'Label', 'Name'],
            ['InvalidType', 'not-a-uri', 'Test', 'test']  # Invalid type and target
        ]
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            writer = csv.writer(f)
            writer.writerows(csv_content)
            csv_file = f.name
        
        try:
            is_valid, errors = self.service.validate_mapping_csv(csv_file)
            self.assertFalse(is_valid)
            self.assertTrue(any('Invalid Type' in error for error in errors))
            self.assertTrue(any('Target must be a valid HTTP URI' in error for error in errors))
            
        finally:
            os.unlink(csv_file)
