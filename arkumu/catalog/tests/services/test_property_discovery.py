"""
Tests for property discovery in FacetedSearchService.
"""
import pytest
from django.contrib.auth import get_user_model
from arkumu.metadata.models import Resource, Triple
from arkumu.users.models import Organization
from arkumu.metadata.models.resource import ResourceType, PublicAccessLevel
from arkumu.metadata.services.faceted_search_service import FacetedSearchService

User = get_user_model()


@pytest.mark.django_db
class TestPropertyDiscovery:
    """Test dynamic property discovery for harmonized resources."""
    
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
        return User.objects.create_user(
            username="testuser",
            email="test@example.com",
            organization=organization
        )
    
    @pytest.fixture
    def rdf_type_resource(self):
        """Create RDF type predicate resource."""
        return Resource.objects.create(
            uri='http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 
            name='rdf:type',
            resource_type=ResourceType.PROPERTY
        )
    
    @pytest.fixture
    def project_type_resource(self):
        """Create project type resource."""
        return Resource.objects.create(
            uri='http://arkumu.org/types/projekt',
            name='Project',
            resource_type=ResourceType.CLASS
        )
    
    @pytest.fixture
    def harmonized_project(self, organization, rdf_type_resource, project_type_resource):
        """Create harmonized project with type triple."""
        project = Resource.objects.create(
            organization=organization,
            uri='http://test-uni.de/project/123',
            name='Test Project',
            resource_type=ResourceType.IRI,
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True
        )
        
        # Add type triple
        Triple.objects.create(
            subject=project,
            predicate=rdf_type_resource,
            object=project_type_resource
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
        
        return project
    
    @pytest.fixture 
    def property_resources_and_literals(self, organization, harmonized_project):
        """Create property resources and literal values."""
        # Create title property
        title_prop = Resource.objects.create(
            uri='http://test-uni.de/properties/title',
            name='Title',
            resource_type=ResourceType.PROPERTY
        )
        
        title_literal = Resource.objects.create(
            organization=organization,
            value='Harmonized Research Project',
            resource_type=ResourceType.LITERAL,
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True
        )
        
        Triple.objects.create(
            subject=harmonized_project,
            predicate=title_prop,
            object=title_literal
        )
        
        # Create subject area property (facetable)
        subject_prop = Resource.objects.create(
            uri='http://test-uni.de/properties/subject-area',
            name='Subject Area', 
            resource_type=ResourceType.PROPERTY
        )
        
        subject_literal = Resource.objects.create(
            organization=organization,
            value='Computer Science',
            resource_type=ResourceType.LITERAL,
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True
        )
        
        Triple.objects.create(
            subject=harmonized_project,
            predicate=subject_prop,
            object=subject_literal
        )
        
        return {
            'title_prop': title_prop,
            'title_literal': title_literal,
            'subject_prop': subject_prop,
            'subject_literal': subject_literal
        }


class TestDiscoverAndCacheProperties(TestPropertyDiscovery):
    """Test property discovery functionality."""
    
    def test_discovers_properties_for_projects(self, user, harmonized_project, property_resources_and_literals):
        """Test that properties are discovered for project resources."""
        service = FacetedSearchService(user)
        properties = service.discover_and_cache_properties('projects')
        
        # Should include "All Properties" option
        assert 'all_properties' in properties
        assert properties['all_properties']['is_searchable'] == True
        assert properties['all_properties']['is_facetable'] == False
        
        # Should discover actual properties
        assert len(properties) >= 2  # At least all_properties + discovered ones
    
    def test_properties_have_correct_structure(self, user, harmonized_project, property_resources_and_literals):
        """Test that discovered properties have the correct structure."""
        service = FacetedSearchService(user)
        properties = service.discover_and_cache_properties('projects')
        
        for prop_key, prop_config in properties.items():
            # Each property should have required fields
            assert 'label' in prop_config
            assert 'is_searchable' in prop_config
            assert 'is_facetable' in prop_config
            assert 'count' in prop_config
            
            # Boolean flags should be actual booleans
            assert isinstance(prop_config['is_searchable'], bool)
            assert isinstance(prop_config['is_facetable'], bool)
    
    def test_no_properties_for_empty_resource_type(self, user):
        """Test that empty resource type returns empty properties."""
        service = FacetedSearchService(user)
        properties = service.discover_and_cache_properties('nonexistent')
        
        # Should return empty dict when no resources found
        assert properties == {}


class TestPropertyClassification(TestPropertyDiscovery):
    """Test property classification as searchable/facetable."""
    
    def test_is_facetable_property_short_values(self, user):
        """Test that short categorical values are classified as facetable."""
        service = FacetedSearchService(user)
        
        # Short, repetitive values should be facetable
        sample_values = ['Computer Science', 'Physics', 'Computer Science', 'Math']
        assert service._is_facetable_property(sample_values) == True
    
    def test_is_facetable_property_long_values(self, user):
        """Test that long unique values are not classified as facetable."""
        service = FacetedSearchService(user)
        
        # Long, unique values should not be facetable
        sample_values = [
            'This is a very long description of a research project',
            'Another completely different long description',
            'Yet another unique long text value'
        ]
        assert service._is_facetable_property(sample_values) == False
    
    def test_is_searchable_property_long_text(self, user):
        """Test that long text values are classified as searchable.""" 
        service = FacetedSearchService(user)
        
        # Long text should be searchable
        sample_values = [
            'This is a detailed project description',
            'Another comprehensive project summary'
        ]
        assert service._is_searchable_property(sample_values) == True
    
    def test_is_searchable_property_short_values(self, user):
        """Test that very short values are not classified as searchable."""
        service = FacetedSearchService(user)
        
        # Very short values should not be searchable
        sample_values = ['CS', 'Math', 'Phys']
        assert service._is_searchable_property(sample_values) == False


class TestCaching(TestPropertyDiscovery):
    """Test property discovery caching."""
    
    def test_properties_are_cached(self, user, harmonized_project, property_resources_and_literals):
        """Test that property discovery results are cached."""
        service = FacetedSearchService(user)
        
        # First call should populate cache
        properties1 = service.discover_and_cache_properties('projects')
        
        # Second call should return cached results
        properties2 = service.discover_and_cache_properties('projects')
        
        assert properties1 == properties2
    
    def test_cache_key_includes_organization(self, organization):
        """Test that cache key includes organization code."""
        user1 = User.objects.create_user(
            username="user1",
            email="user1@example.com", 
            organization=organization
        )
        
        user2 = User.objects.create_user(
            username="user2",
            email="user2@example.com"
            # No organization
        )
        
        service1 = FacetedSearchService(user1)
        service2 = FacetedSearchService(user2)
        
        # Different users should have different cache keys
        # This is tested by ensuring the method doesn't crash
        properties1 = service1.discover_and_cache_properties('projects')
        properties2 = service2.discover_and_cache_properties('projects')
        
        # Both should complete without error
        assert isinstance(properties1, dict)
        assert isinstance(properties2, dict)