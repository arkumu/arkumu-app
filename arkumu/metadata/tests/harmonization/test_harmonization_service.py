"""
Tests for HarmonizationService
"""

import pytest
from django.contrib.auth import get_user_model
from arkumu.users.models import Organization
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.harmonization import HarmonizationRule, HarmonizationExecution
from arkumu.metadata.services.harmonization import HarmonizationService

User = get_user_model()


@pytest.fixture
def test_organization():
    """Create a test organization."""
    return Organization.objects.create(
        name="Test Museum",
        code="test_museum",
        domain="test.museum"
    )


@pytest.fixture
def test_user():
    """Create a test user."""
    return User.objects.create_user(
        username="testuser",
        email="test@example.com"
    )


@pytest.fixture
def test_resources(test_organization):
    """Create test resources."""
    resources = []
    
    # Create property resources
    property_names = ["artwork_title", "painting_name", "artist_name", "creation_date"]
    for name in property_names:
        resource = Resource.objects.create(
            uri=f"http://test.museum/{name}",
            name=name,
            resource_type=ResourceType.PROPERTY,
            source=test_organization
        )
        resources.append(resource)
    
    # Create class resources  
    class_names = ["Artwork", "Painting", "Artist"]
    for name in class_names:
        resource = Resource.objects.create(
            uri=f"http://test.museum/{name}",
            name=name,
            resource_type=ResourceType.CLASS,
            source=test_organization
        )
        resources.append(resource)
    
    return resources


@pytest.fixture
def test_rules(test_organization, test_user):
    """Create test harmonization rules."""
    rules = []
    
    # Rule for title properties
    rule1 = HarmonizationRule.objects.create(
        source_organization=test_organization,
        source_property_pattern=".*title.*",
        catalog_property_uri="http://arkumu.org/data/catalog/catalog/properties/title",
        catalog_property_label="title",
        mapping_type="exact",
        priority=10,
        created_by=test_user
    )
    rules.append(rule1)
    
    # Rule for artist properties
    rule2 = HarmonizationRule.objects.create(
        source_organization=test_organization,
        source_property_pattern="artist_name",
        catalog_property_uri="http://arkumu.org/data/catalog/catalog/properties/creator",
        catalog_property_label="creator", 
        mapping_type="close",
        priority=5,
        created_by=test_user
    )
    rules.append(rule2)
    
    return rules


@pytest.mark.django_db
class TestHarmonizationService:
    """Test cases for HarmonizationService."""
    
    def test_service_initialization(self):
        """Test that service initializes correctly."""
        service = HarmonizationService()
        
        assert service.catalog_uri_generator is not None
        assert service.alignment_generator is not None
        assert service.rule_matcher is not None
        assert service.bulk_processor is not None
        assert service.conflict_resolver is not None
    
    def test_create_harmonization_rule(self, test_organization, test_user):
        """Test creating a harmonization rule."""
        service = HarmonizationService()
        
        rule = service.create_harmonization_rule(
            source_organization=test_organization,
            source_property_pattern="test_property",
            catalog_property_name="test_catalog_property",
            mapping_type="exact",
            priority=10,
            user=test_user,
            notes="Test rule"
        )
        
        assert rule.source_organization == test_organization
        assert rule.source_property_pattern == "test_property"
        assert rule.catalog_property_label == "test_catalog_property"
        assert rule.mapping_type == "exact"
        assert rule.priority == 10
        assert rule.created_by == test_user
        assert "test_catalog_property" in rule.catalog_property_uri
    
    def test_validate_organization_rules(self, test_organization, test_rules):
        """Test rule validation."""
        service = HarmonizationService()
        
        results = service.validate_organization_rules(test_organization)
        
        assert "valid_rules" in results
        assert "invalid_rules" in results
        assert "warnings" in results
        assert len(results["valid_rules"]) == 2  # Both test rules should be valid
    
    def test_preview_harmonization(self, test_organization, test_resources, test_rules):
        """Test harmonization preview."""
        service = HarmonizationService()
        
        preview = service.preview_harmonization(test_organization, limit=10)
        
        assert "total_resources_analyzed" in preview
        assert "resources_with_matches" in preview
        assert "resources_with_conflicts" in preview
        assert "estimated_triples" in preview
        assert "catalog_properties_to_create" in preview
        assert "sample_matches" in preview
        
        # Should analyze our test resources
        assert preview["total_resources_analyzed"] > 0
        # Should have matches based on our rules
        assert preview["resources_with_matches"] > 0
    
    def test_harmonize_organization(self, test_organization, test_resources, test_rules, test_user):
        """Test full organization harmonization."""
        service = HarmonizationService()
        
        execution = service.harmonize_organization(
            organization=test_organization,
            user=test_user,
            execution_mode='manual',
            cleanup_existing=False
        )
        
        assert execution.status == 'completed'
        assert execution.created_by == test_user
        assert execution.resources_processed > 0
        assert execution.triples_created >= 0
        assert test_organization in execution.organizations.all()
    
    def test_harmonize_resources(self, test_resources, test_rules, test_user):
        """Test harmonizing specific resources."""
        service = HarmonizationService()
        
        # Test with a subset of resources
        subset_resources = test_resources[:3]
        
        execution = service.harmonize_resources(
            resources=subset_resources,
            user=test_user,
            execution_mode='manual'
        )
        
        assert execution.status == 'completed'
        assert execution.created_by == test_user
        assert execution.resources_processed == len(subset_resources)
    
    def test_get_harmonization_status(self, test_organization, test_resources, test_rules):
        """Test getting harmonization status."""
        service = HarmonizationService()
        
        status = service.get_harmonization_status(test_organization)
        
        assert "organization" in status
        assert "total_resources" in status
        assert "aligned_resources" in status
        assert "alignment_percentage" in status
        assert "active_rules" in status
        assert "pending_conflicts" in status
        assert "recent_executions" in status
        
        assert status["organization"] == test_organization.name
        assert status["total_resources"] > 0
        assert status["active_rules"] == 2  # Our test rules
    
    def test_resolve_conflicts(self, test_organization, test_user):
        """Test conflict resolution.""" 
        service = HarmonizationService()
        
        # Initially no conflicts
        stats = service.resolve_conflicts(organization=test_organization)
        
        assert "resolved" in stats
        assert "failed" in stats  
        assert "skipped" in stats
        assert stats["resolved"] == 0  # No conflicts initially


@pytest.mark.django_db
class TestHarmonizationServiceIntegration:
    """Integration tests for HarmonizationService."""
    
    def test_full_harmonization_workflow(self, test_organization, test_user):
        """Test complete harmonization workflow."""
        service = HarmonizationService()
        
        # 1. Create resources
        resource1 = Resource.objects.create(
            uri="http://test.museum/artwork_title",
            name="artwork_title",
            resource_type=ResourceType.PROPERTY,
            source=test_organization
        )
        
        resource2 = Resource.objects.create(
            uri="http://test.museum/painting_title", 
            name="painting_title",
            resource_type=ResourceType.PROPERTY,
            source=test_organization
        )
        
        # 2. Create rule that matches both
        rule = service.create_harmonization_rule(
            source_organization=test_organization,
            source_property_pattern=".*title.*",
            catalog_property_name="title",
            mapping_type="exact",
            priority=10,
            user=test_user
        )
        
        # 3. Preview harmonization
        preview = service.preview_harmonization(test_organization)
        assert preview["resources_with_matches"] == 2
        assert preview["estimated_triples"] == 2
        
        # 4. Run harmonization
        execution = service.harmonize_organization(
            organization=test_organization,
            user=test_user
        )
        
        assert execution.status == 'completed'
        assert execution.resources_processed == 2
        assert execution.triples_created == 2
        
        # 5. Check final status
        status = service.get_harmonization_status(test_organization)
        assert status["aligned_resources"] == 2
        assert status["alignment_percentage"] == 100.0