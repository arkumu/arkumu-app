"""
Tests for facet value retrieval in FacetedSearchService.
"""
import pytest
from django.contrib.auth import get_user_model
from arkumu.metadata.models import Resource, Triple
from arkumu.users.models import Organization
from arkumu.metadata.models.resource import ResourceType, PublicAccessLevel
from arkumu.metadata.services.faceted_search_service import FacetedSearchService

User = get_user_model()


@pytest.mark.django_db
class TestFacetValues:
    """Test facet value retrieval for harmonized resources."""
    
    @pytest.fixture
    def setup_facet_test_data(self):
        """Set up test data for facet testing."""
        organization = Organization.objects.create(
            name="Test University",
            code="TEST_UNI"
        )
        
        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            organization=organization
        )
        
        # Create RDF type resource
        rdf_type = Resource.objects.create(
            uri='http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
            name='rdf:type',
            resource_type=ResourceType.PROPERTY
        )
        
        # Create project type
        project_type = Resource.objects.create(
            uri='http://arkumu.org/types/projekt',
            name='Project',
            resource_type=ResourceType.CLASS
        )
        
        # Create harmonization resources
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
        
        # Create subject area property
        subject_prop = Resource.objects.create(
            uri='http://test-uni.de/properties/faechergruppe',
            name='Subject Area',
            resource_type=ResourceType.PROPERTY
        )
        
        # Create multiple projects with different subject areas
        projects_data = [
            {'name': 'CS Project 1', 'subject': 'Computer Science'},
            {'name': 'CS Project 2', 'subject': 'Computer Science'},
            {'name': 'Physics Project', 'subject': 'Physics'},
            {'name': 'Math Project', 'subject': 'Mathematics'},
        ]
        
        projects = []
        for i, project_data in enumerate(projects_data):
            # Create project
            project = Resource.objects.create(
                organization=organization,
                uri=f'http://test-uni.de/project/{i+1}',
                name=project_data['name'],
                resource_type=ResourceType.IRI,
                public_access_level=PublicAccessLevel.PUBLIC,
                is_public_approved=True
            )
            
            # Add type triple
            Triple.objects.create(
                subject=project,
                predicate=rdf_type,
                object=project_type
            )
            
            # Add harmonization mapping
            Triple.objects.create(
                subject=project,
                predicate=owl_sameas,
                object=catalog_resource
            )
            
            # Add subject area
            subject_literal = Resource.objects.create(
                organization=organization,
                value=project_data['subject'],
                resource_type=ResourceType.LITERAL,
                public_access_level=PublicAccessLevel.PUBLIC,
                is_public_approved=True
            )
            
            Triple.objects.create(
                subject=project,
                predicate=subject_prop,
                object=subject_literal
            )
            
            projects.append(project)
        
        return {
            'user': user,
            'organization': organization,
            'projects': projects,
            'subject_prop': subject_prop,
            'rdf_type': rdf_type,
            'project_type': project_type
        }


class TestGetFacetValues(TestFacetValues):
    """Test individual facet value retrieval."""
    
    def test_get_facet_values_returns_counts(self, setup_facet_test_data):
        """Test that facet values include correct counts."""
        data = setup_facet_test_data
        service = FacetedSearchService(data['user'])
        
        facet_values = service.get_facet_values('projects', 'faechergruppe')
        
        # Should return facet values with counts
        assert len(facet_values) > 0
        
        # Find Computer Science entry (should have count of 2)
        cs_entry = next((item for item in facet_values if item['value'] == 'Computer Science'), None)
        assert cs_entry is not None
        assert cs_entry['count'] == 2
        
        # Find Physics entry (should have count of 1)
        physics_entry = next((item for item in facet_values if item['value'] == 'Physics'), None)
        assert physics_entry is not None
        assert physics_entry['count'] == 1
    
    def test_get_facet_values_ordered_by_count(self, setup_facet_test_data):
        """Test that facet values are ordered by count (descending)."""
        data = setup_facet_test_data
        service = FacetedSearchService(data['user'])
        
        facet_values = service.get_facet_values('projects', 'faechergruppe')
        
        # Should be ordered by count descending
        counts = [item['count'] for item in facet_values]
        assert counts == sorted(counts, reverse=True)
        
        # Computer Science should be first (highest count)
        assert facet_values[0]['value'] == 'Computer Science'
        assert facet_values[0]['count'] == 2
    
    def test_get_facet_values_nonexistent_facet(self, setup_facet_test_data):
        """Test that non-existent facet returns empty list."""
        data = setup_facet_test_data
        service = FacetedSearchService(data['user'])
        
        facet_values = service.get_facet_values('projects', 'nonexistent-facet')
        
        assert facet_values == []
    
    def test_get_facet_values_respects_limit(self, setup_facet_test_data):
        """Test that facet values respect the limit parameter."""
        data = setup_facet_test_data
        service = FacetedSearchService(data['user'])
        
        facet_values = service.get_facet_values('projects', 'faechergruppe', limit=2)
        
        # Should return at most 2 values
        assert len(facet_values) <= 2


class TestGetAllFacetValues(TestFacetValues):
    """Test retrieval of all facet values."""
    
    def test_get_all_facet_values_includes_facetable_only(self, setup_facet_test_data):
        """Test that get_all_facet_values only includes facetable properties."""
        data = setup_facet_test_data
        service = FacetedSearchService(data['user'])
        
        all_facets = service.get_all_facet_values('projects')
        
        # Should be a dictionary of facet_key -> values
        assert isinstance(all_facets, dict)
        
        # Should only include facetable properties (not searchable-only)
        for facet_key, facet_values in all_facets.items():
            assert isinstance(facet_values, list)
            # Each value should have the expected structure
            if facet_values:  # If not empty
                for value in facet_values:
                    assert 'value' in value
                    assert 'count' in value
                    assert 'label' in value
    
    def test_get_all_facet_values_empty_for_no_resources(self, setup_facet_test_data):
        """Test that get_all_facet_values returns empty dict when no resources."""
        data = setup_facet_test_data
        service = FacetedSearchService(data['user'])
        
        all_facets = service.get_all_facet_values('nonexistent-type')
        
        assert all_facets == {}


class TestFacetValueStructure(TestFacetValues):
    """Test the structure of returned facet values."""
    
    def test_facet_value_has_required_fields(self, setup_facet_test_data):
        """Test that each facet value has required fields."""
        data = setup_facet_test_data
        service = FacetedSearchService(data['user'])
        
        facet_values = service.get_facet_values('projects', 'faechergruppe')
        
        for value in facet_values:
            # Required fields
            assert 'value' in value
            assert 'count' in value  
            assert 'label' in value
            
            # Types
            assert isinstance(value['value'], str)
            assert isinstance(value['count'], int)
            assert isinstance(value['label'], str)
            
            # Count should be positive
            assert value['count'] > 0
    
    def test_facet_value_label_equals_value(self, setup_facet_test_data):
        """Test that facet value label equals the value by default."""
        data = setup_facet_test_data
        service = FacetedSearchService(data['user'])
        
        facet_values = service.get_facet_values('projects', 'faechergruppe')
        
        for value in facet_values:
            assert value['label'] == value['value']


class TestHarmonizationFiltering(TestFacetValues):
    """Test that facet values only include harmonized resources."""
    
    def test_facet_values_exclude_non_harmonized(self, setup_facet_test_data):
        """Test that facet values don't include non-harmonized resources."""
        data = setup_facet_test_data
        
        # Create a non-harmonized project with same subject area
        non_harmonized = Resource.objects.create(
            organization=data['organization'],
            uri='http://test-uni.de/project/non-harmonized',
            name='Non-Harmonized Project',
            resource_type=ResourceType.INSTANCE,
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True
        )
        
        # Add type triple
        Triple.objects.create(
            subject=non_harmonized,
            predicate=data['rdf_type'],
            object=data['project_type']
        )
        
        # Add subject area (but no harmonization mapping)
        subject_literal = Resource.objects.create(
            organization=data['organization'],
            value='Computer Science',  # Same as harmonized ones
            resource_type=ResourceType.LITERAL,
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True
        )
        
        Triple.objects.create(
            subject=non_harmonized,
            predicate=data['subject_prop'],
            object=subject_literal
        )
        
        service = FacetedSearchService(data['user'])
        facet_values = service.get_facet_values('projects', 'faechergruppe')
        
        # Computer Science count should still be 2 (not 3)
        cs_entry = next((item for item in facet_values if item['value'] == 'Computer Science'), None)
        assert cs_entry is not None
        assert cs_entry['count'] == 2  # Only harmonized resources counted