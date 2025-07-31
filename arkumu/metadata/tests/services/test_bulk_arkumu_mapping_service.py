"""
Tests for BulkArkumuMappingService.
"""

import pytest
from django.test import TestCase
from django.contrib.auth import get_user_model
from arkumu.metadata.services.bulk_arkumu_mapping_service import BulkArkumuMappingService
from arkumu.metadata.models.harmonization import HarmonizationRule, HarmonizationExecution
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.users.models import Organization

User = get_user_model()


@pytest.mark.django_db
class TestBulkArkumuMappingService(TestCase):
    """Test cases for BulkArkumuMappingService."""
    
    def setUp(self):
        """Set up test data."""
        self.service = BulkArkumuMappingService()
        
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            role='manager'
        )
        
        # Create test organizations
        self.org_det = Organization.objects.create(
            name='DET Organization',
            code='det',
            description='Test DET organization'
        )
        
        self.org_bmi = Organization.objects.create(
            name='BMI Organization', 
            code='bmi',
            description='Test BMI organization'
        )
        
        # Create test resources first
        self.det_org_unit = Resource.objects.create(
            uri='http://arkumu.org/data/det/types/organisationseinheit',
            resource_type=ResourceType.CLASS,
            organization=self.org_det
        )
        
        self.det_person = Resource.objects.create(
            uri='http://arkumu.org/data/det/types/person',
            resource_type=ResourceType.CLASS,
            organization=self.org_det
        )
        
        self.det_property = Resource.objects.create(
            uri='http://arkumu.org/data/det/properties/property-cardinality',
            resource_type=ResourceType.PROPERTY,
            organization=self.org_det
        )
        
        self.bmi_contract = Resource.objects.create(
            uri='http://arkumu.org/data/bmi/types/contract',
            resource_type=ResourceType.CLASS,
            organization=self.org_bmi
        )
        
        self.bmi_property = Resource.objects.create(
            uri='http://arkumu.org/data/bmi/properties/has-status',
            resource_type=ResourceType.PROPERTY,
            organization=self.org_bmi
        )
        
        # Create predicate resources
        self.rdf_type = Resource.objects.create(
            uri='http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
            resource_type=ResourceType.PROPERTY
        )
        
        self.rdfs_class = Resource.objects.create(
            uri='http://www.w3.org/2000/01/rdf-schema#Class',
            resource_type=ResourceType.CLASS
        )
        
        self.rdf_property = Resource.objects.create(
            uri='http://www.w3.org/1999/02/22-rdf-syntax-ns#Property',
            resource_type=ResourceType.CLASS
        )

        # Create test triples with organization-specific IRIs
        self.test_triples = [
            # DET organization triples
            Triple.objects.create(
                subject=self.det_org_unit,
                predicate=self.rdf_type,
                object=self.rdfs_class,
                source=self.org_det
            ),
            Triple.objects.create(
                subject=self.det_person,
                predicate=self.rdf_type,
                object=self.rdfs_class,
                source=self.org_det
            ),
            Triple.objects.create(
                subject=self.det_property,
                predicate=self.rdf_type,
                object=self.rdf_property,
                source=self.org_det
            ),
            # BMI organization triples
            Triple.objects.create(
                subject=self.bmi_contract,
                predicate=self.rdf_type,
                object=self.rdfs_class,
                source=self.org_bmi
            ),
            Triple.objects.create(
                subject=self.bmi_property,
                predicate=self.rdf_type,
                object=self.rdf_property,
                source=self.org_bmi
            )
        ]
    
    def test_transform_organization_iri_to_arkumu_types(self):
        """Test transformation of organization type IRIs to Arkumu model."""
        # Test DET types
        result = self.service.transform_organization_iri_to_arkumu(
            'http://arkumu.org/data/det/types/organisationseinheit'
        )
        self.assertEqual(result, 'http://arkumu.org/types/organisationseinheit')
        
        result = self.service.transform_organization_iri_to_arkumu(
            'http://arkumu.org/data/det/types/person'
        )
        self.assertEqual(result, 'http://arkumu.org/types/person')
        
        # Test BMI types
        result = self.service.transform_organization_iri_to_arkumu(
            'http://arkumu.org/data/bmi/types/contract'
        )
        self.assertEqual(result, 'http://arkumu.org/types/contract')
    
    def test_transform_organization_iri_to_arkumu_properties(self):
        """Test transformation of organization property IRIs to Arkumu model."""
        # Test DET properties
        result = self.service.transform_organization_iri_to_arkumu(
            'http://arkumu.org/data/det/properties/property-cardinality'
        )
        self.assertEqual(result, 'http://arkumu.org/properties/property-cardinality')
        
        # Test BMI properties
        result = self.service.transform_organization_iri_to_arkumu(
            'http://arkumu.org/data/bmi/properties/has-status'
        )
        self.assertEqual(result, 'http://arkumu.org/properties/has-status')
    
    def test_transform_organization_iri_invalid_cases(self):
        """Test transformation with invalid IRIs."""
        # Non-arkumu URL
        result = self.service.transform_organization_iri_to_arkumu(
            'http://example.com/data/det/types/test'
        )
        self.assertIsNone(result)
        
        # No organization pattern
        result = self.service.transform_organization_iri_to_arkumu(
            'http://arkumu.org/types/test'
        )
        self.assertIsNone(result)
        
        # Empty string
        result = self.service.transform_organization_iri_to_arkumu('')
        self.assertIsNone(result)
        
        # None
        result = self.service.transform_organization_iri_to_arkumu(None)
        self.assertIsNone(result)
    
    def test_extract_organization_code_from_iri(self):
        """Test extraction of organization code from IRI."""
        # Test valid IRIs
        result = self.service.extract_organization_code_from_iri(
            'http://arkumu.org/data/det/types/organisationseinheit'
        )
        self.assertEqual(result, 'det')
        
        result = self.service.extract_organization_code_from_iri(
            'http://arkumu.org/data/bmi/properties/has-status'
        )
        self.assertEqual(result, 'bmi')
        
        # Test invalid IRI
        result = self.service.extract_organization_code_from_iri(
            'http://arkumu.org/types/test'
        )
        self.assertIsNone(result)
    
    def test_get_organization_iris_from_resources(self):
        """Test retrieval of organization IRIs from resources."""
        result = self.service.get_organization_iris_from_resources(['det', 'bmi'])
        
        # Check DET IRIs
        self.assertIn('det', result)
        det_iris = result['det']
        self.assertIn('http://arkumu.org/data/det/types/organisationseinheit', det_iris)
        self.assertIn('http://arkumu.org/data/det/types/person', det_iris)
        self.assertIn('http://arkumu.org/data/det/properties/property-cardinality', det_iris)
        
        # Check BMI IRIs
        self.assertIn('bmi', result)
        bmi_iris = result['bmi']
        self.assertIn('http://arkumu.org/data/bmi/types/contract', bmi_iris)
        self.assertIn('http://arkumu.org/data/bmi/properties/has-status', bmi_iris)
    
    def test_create_harmonization_rules_success(self):
        """Test successful creation of harmonization rules."""
        execution = self.service.create_harmonization_rules(
            organization_codes=['det'],
            created_by=self.user,
            mapping_type='exact',
            priority=10
        )
        
        # Check execution record
        self.assertEqual(execution.status, 'completed')
        self.assertEqual(execution.execution_mode, 'manual')
        self.assertEqual(execution.created_by, self.user)
        self.assertGreater(execution.resources_processed, 0)
        self.assertGreater(execution.triples_created, 0)
        
        # Check that organizations are linked
        self.assertIn(self.org_det, execution.organizations.all())
        
        # Check that harmonization rules were created
        rules = HarmonizationRule.objects.filter(source_organization=self.org_det)
        self.assertGreater(rules.count(), 0)
        
        # Check specific rule properties
        rule = rules.first()
        self.assertEqual(rule.mapping_type, 'exact')
        self.assertEqual(rule.priority, 10)
        self.assertEqual(rule.created_by, self.user)
        self.assertTrue(rule.is_active)
        self.assertIn('Auto-generated bulk mapping', rule.notes)
    
    def test_create_harmonization_rules_multiple_organizations(self):
        """Test creation of harmonization rules for multiple organizations."""
        execution = self.service.create_harmonization_rules(
            organization_codes=['det', 'bmi'],
            created_by=self.user
        )
        
        # Check execution
        self.assertEqual(execution.status, 'completed')
        self.assertGreater(execution.resources_processed, 0)
        
        # Check that both organizations are linked
        self.assertIn(self.org_det, execution.organizations.all())
        self.assertIn(self.org_bmi, execution.organizations.all())
        
        # Check that rules were created for both organizations
        det_rules = HarmonizationRule.objects.filter(source_organization=self.org_det)
        bmi_rules = HarmonizationRule.objects.filter(source_organization=self.org_bmi)
        
        self.assertGreater(det_rules.count(), 0)
        self.assertGreater(bmi_rules.count(), 0)
    
    def test_create_harmonization_rules_nonexistent_organization(self):
        """Test handling of non-existent organization codes."""
        execution = self.service.create_harmonization_rules(
            organization_codes=['nonexistent'],
            created_by=self.user
        )
        
        # Should complete without error but process no resources
        self.assertEqual(execution.status, 'completed')
        self.assertEqual(execution.resources_processed, 0)
        self.assertEqual(execution.triples_created, 0)
    
    def test_create_harmonization_rules_duplicate_prevention(self):
        """Test that duplicate rules are not created."""
        # Create initial rules
        execution1 = self.service.create_harmonization_rules(
            organization_codes=['det'],
            created_by=self.user
        )
        
        initial_count = execution1.triples_created
        
        # Try to create the same rules again
        execution2 = self.service.create_harmonization_rules(
            organization_codes=['det'],
            created_by=self.user
        )
        
        # Second execution should create no new rules
        self.assertEqual(execution2.triples_created, 0)
        
        # Total rule count should remain the same
        total_rules = HarmonizationRule.objects.filter(source_organization=self.org_det).count()
        self.assertEqual(total_rules, initial_count)
    
    def test_preview_bulk_mapping(self):
        """Test preview of bulk mapping without creating rules."""
        preview = self.service.preview_bulk_mapping(['det', 'bmi'])
        
        # Check DET preview
        self.assertIn('det', preview)
        det_mappings = preview['det']
        self.assertGreater(len(det_mappings), 0)
        
        # Check mapping structure
        mapping = det_mappings[0]
        self.assertIn('source_iri', mapping)
        self.assertIn('target_iri', mapping)
        self.assertIn('label', mapping)
        self.assertIn('resource_type', mapping)
        
        # Verify IRI transformation
        source_iri = mapping['source_iri']
        target_iri = mapping['target_iri']
        expected_target = self.service.transform_organization_iri_to_arkumu(source_iri)
        self.assertEqual(target_iri, expected_target)
        
        # Check BMI preview
        self.assertIn('bmi', preview)
        bmi_mappings = preview['bmi']
        self.assertGreater(len(bmi_mappings), 0)
    
    def test_get_existing_mappings_count(self):
        """Test counting existing harmonization rules."""
        # Initially no rules
        counts = self.service.get_existing_mappings_count(['det', 'bmi'])
        self.assertEqual(counts['det'], 0)
        self.assertEqual(counts['bmi'], 0)
        
        # Create some rules
        self.service.create_harmonization_rules(['det'], self.user)
        
        # Check updated counts
        counts = self.service.get_existing_mappings_count(['det', 'bmi'])
        self.assertGreater(counts['det'], 0)
        self.assertEqual(counts['bmi'], 0)
    
    def test_get_existing_mappings_count_nonexistent_org(self):
        """Test counting mappings for non-existent organization."""
        counts = self.service.get_existing_mappings_count(['nonexistent'])
        self.assertEqual(counts['nonexistent'], 0)
    
    def test_validate_organization_codes(self):
        """Test validation of organization codes."""
        valid, invalid = self.service.validate_organization_codes(['det', 'bmi', 'nonexistent'])
        
        self.assertIn('det', valid)
        self.assertIn('bmi', valid)
        self.assertIn('nonexistent', invalid)
        
        self.assertEqual(len(valid), 2)
        self.assertEqual(len(invalid), 1)
    
    def test_validate_organization_codes_all_valid(self):
        """Test validation with all valid organization codes."""
        valid, invalid = self.service.validate_organization_codes(['det', 'bmi'])
        
        self.assertEqual(len(valid), 2)
        self.assertEqual(len(invalid), 0)
        self.assertIn('det', valid)
        self.assertIn('bmi', valid)
    
    def test_validate_organization_codes_all_invalid(self):
        """Test validation with all invalid organization codes."""
        valid, invalid = self.service.validate_organization_codes(['nonexistent1', 'nonexistent2'])
        
        self.assertEqual(len(valid), 0)
        self.assertEqual(len(invalid), 2)
        self.assertIn('nonexistent1', invalid)
        self.assertIn('nonexistent2', invalid)
    
    def test_validate_organization_codes_empty_list(self):
        """Test validation with empty list."""
        valid, invalid = self.service.validate_organization_codes([])
        
        self.assertEqual(len(valid), 0)
        self.assertEqual(len(invalid), 0)