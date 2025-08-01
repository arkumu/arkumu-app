"""
Tests for search_with_facets method in FacetedSearchService.
"""
import pytest
from django.contrib.auth import get_user_model
from arkumu.metadata.models import Resource, Triple
from arkumu.users.models import Organization
from arkumu.metadata.models.resource import ResourceType, PublicAccessLevel
from arkumu.metadata.services.faceted_search_service import FacetedSearchService

User = get_user_model()


@pytest.mark.django_db
class TestSearchWithFacets:
    """Test faceted search functionality."""
    
    @pytest.fixture
    def search_test_setup(self):
        """Set up comprehensive test data for search testing."""
        organization = Organization.objects.create(
            name="Test University",
            code="TEST_UNI"
        )
        
        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            organization=organization
        )
        
        # Create necessary predicates
        rdf_type = Resource.objects.create(
            uri='http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
            name='rdf:type',
            resource_type=ResourceType.PROPERTY
        )
        
        owl_sameas = Resource.objects.create(
            uri='http://www.w3.org/2002/07/owl#sameAs',
            name='owl:sameAs',
            resource_type=ResourceType.PROPERTY
        )
        
        # Create types
        project_type = Resource.objects.create(
            uri='http://arkumu.org/types/projekt',
            name='Project',
            resource_type=ResourceType.CLASS
        )
        
        catalog_resource = Resource.objects.create(
            uri='http://data.arkumu.org/catalog/project',
            name='Catalog Project',
            resource_type=ResourceType.CLASS
        )
        
        # Create properties
        title_prop = Resource.objects.create(
            uri='http://test-uni.de/properties/title',
            name='Title',
            resource_type=ResourceType.PROPERTY
        )
        
        subject_prop = Resource.objects.create(
            uri='http://test-uni.de/properties/faechergruppe',
            name='Subject Area',
            resource_type=ResourceType.PROPERTY
        )
        
        # Create test projects with properties
        projects_data = [
            {
                'name': 'Machine Learning Research',
                'title': 'Advanced Machine Learning Algorithms',
                'subject': 'Computer Science'
            },
            {
                'name': 'AI Ethics Study',
                'title': 'Ethical Implications of Artificial Intelligence',
                'subject': 'Computer Science'
            },
            {
                'name': 'Quantum Physics Research',
                'title': 'Quantum Mechanics in Modern Physics',
                'subject': 'Physics'
            },
            {
                'name': 'Mathematical Modeling',
                'title': 'Statistical Models in Data Science',
                'subject': 'Mathematics'
            }
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
            
            # Add type
            Triple.objects.create(
                subject=project,
                predicate=rdf_type,
                object=project_type
            )
            
            # Add harmonization
            Triple.objects.create(
                subject=project,
                predicate=owl_sameas,
                object=catalog_resource
            )
            
            # Add title
            title_literal = Resource.objects.create(
                organization=organization,
                value=project_data['title'],
                resource_type=ResourceType.LITERAL,
                public_access_level=PublicAccessLevel.PUBLIC,
                is_public_approved=True
            )
            
            Triple.objects.create(
                subject=project,
                predicate=title_prop,
                object=title_literal
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
            'title_prop': title_prop,
            'subject_prop': subject_prop,
            'project_type': project_type
        }


class TestTextSearch(TestSearchWithFacets):
    """Test text search functionality."""
    
    def test_search_finds_matching_projects(self, search_test_setup):
        """Test that text search finds projects with matching content."""
        data = search_test_setup
        service = FacetedSearchService(data['user'])
        
        results = service.search_with_facets(
            query="Machine Learning",
            resource_type="projects"
        )
        
        # Should find the ML project
        assert results.count() == 1
        assert "Machine Learning Research" in [r.name for r in results]
    
    def test_search_case_insensitive(self, search_test_setup):
        """Test that text search is case insensitive."""
        data = search_test_setup
        service = FacetedSearchService(data['user'])
        
        results = service.search_with_facets(
            query="machine learning",  # lowercase
            resource_type="projects"
        )
        
        assert results.count() == 1
        assert "Machine Learning Research" in [r.name for r in results]
    
    def test_search_partial_match(self, search_test_setup):
        """Test that partial matches work."""
        data = search_test_setup
        service = FacetedSearchService(data['user'])
        
        results = service.search_with_facets(
            query="Ethics",
            resource_type="projects"
        )
        
        assert results.count() == 1
        assert "AI Ethics Study" in [r.name for r in results]
    
    def test_search_no_results(self, search_test_setup):
        """Test search with no matching results."""
        data = search_test_setup
        service = FacetedSearchService(data['user'])
        
        results = service.search_with_facets(
            query="Nonexistent Topic",
            resource_type="projects"
        )
        
        assert results.count() == 0


class TestFacetFiltering(TestSearchWithFacets):
    """Test facet-based filtering."""
    
    def test_facet_filter_single_value(self, search_test_setup):
        """Test filtering by single facet value."""
        data = search_test_setup
        service = FacetedSearchService(data['user'])
        
        results = service.search_with_facets(
            resource_type="projects",
            facet_filters={'faechergruppe': ['Computer Science']}
        )
        
        # Should find 2 CS projects
        assert results.count() == 2
        result_names = [r.name for r in results]
        assert "Machine Learning Research" in result_names
        assert "AI Ethics Study" in result_names
    
    def test_facet_filter_multiple_values(self, search_test_setup):
        """Test filtering by multiple facet values."""
        data = search_test_setup
        service = FacetedSearchService(data['user'])
        
        results = service.search_with_facets(
            resource_type="projects",
            facet_filters={'faechergruppe': ['Computer Science', 'Physics']}
        )
        
        # Should find CS + Physics projects (3 total)
        assert results.count() == 3
        result_names = [r.name for r in results]
        assert "Machine Learning Research" in result_names
        assert "AI Ethics Study" in result_names 
        assert "Quantum Physics Research" in result_names
    
    def test_facet_filter_no_matches(self, search_test_setup):
        """Test facet filter with no matching results."""
        data = search_test_setup
        service = FacetedSearchService(data['user'])
        
        results = service.search_with_facets(
            resource_type="projects",
            facet_filters={'faechergruppe': ['Nonexistent Subject']}
        )
        
        assert results.count() == 0


class TestCombinedSearchAndFacets(TestSearchWithFacets):
    """Test combining text search with facet filters."""
    
    def test_search_with_facet_filter(self, search_test_setup):
        """Test combining text search with facet filtering."""
        data = search_test_setup
        service = FacetedSearchService(data['user'])
        
        results = service.search_with_facets(
            query="Research",
            resource_type="projects",
            facet_filters={'faechergruppe': ['Computer Science']}
        )
        
        # Should find only CS projects containing "Research"
        assert results.count() == 1
        assert "Machine Learning Research" in [r.name for r in results]
    
    def test_search_with_facet_no_intersection(self, search_test_setup):
        """Test search + facet with no intersection."""
        data = search_test_setup
        service = FacetedSearchService(data['user'])
        
        results = service.search_with_facets(
            query="Quantum",  # Only in Physics
            resource_type="projects", 
            facet_filters={'faechergruppe': ['Computer Science']}  # CS only
        )
        
        # No intersection between "Quantum" and "Computer Science"
        assert results.count() == 0


class TestResourceTypeFiltering(TestSearchWithFacets):
    """Test resource type filtering."""
    
    def test_projects_resource_type(self, search_test_setup):
        """Test filtering by projects resource type."""
        data = search_test_setup
        service = FacetedSearchService(data['user'])
        
        results = service.search_with_facets(resource_type="projects")
        
        # Should find all 4 projects
        assert results.count() == 4
    
    def test_empty_resource_type(self, search_test_setup):
        """Test with empty resource type."""
        data = search_test_setup
        service = FacetedSearchService(data['user'])
        
        results = service.search_with_facets(resource_type="")
        
        # Should return no results for empty type
        assert results.count() == 0
    
    def test_nonexistent_resource_type(self, search_test_setup):
        """Test with non-existent resource type."""
        data = search_test_setup
        service = FacetedSearchService(data['user'])
        
        results = service.search_with_facets(resource_type="nonexistent")
        
        assert results.count() == 0


class TestPropertySpecificSearch(TestSearchWithFacets):
    """Test property-specific search functionality."""
    
    def test_search_in_specific_property(self, search_test_setup):
        """Test searching within a specific property."""
        data = search_test_setup
        service = FacetedSearchService(data['user'])
        
        results = service.search_with_facets(
            query="Statistical",
            resource_type="projects",
            search_property="title"  # Search only in title
        )
        
        # Should find the math project with "Statistical" in title
        assert results.count() == 1
        assert "Mathematical Modeling" in [r.name for r in results]
    
    def test_search_all_properties_vs_specific(self, search_test_setup):
        """Test difference between all properties and specific property search."""
        data = search_test_setup
        service = FacetedSearchService(data['user'])
        
        # Search all properties
        results_all = service.search_with_facets(
            query="Computer Science",
            resource_type="projects",
            search_property="all_properties"
        )
        
        # Search only in title
        results_title = service.search_with_facets(
            query="Computer Science", 
            resource_type="projects",
            search_property="title"
        )
        
        # "Computer Science" appears in subject area, not titles
        assert results_all.count() > results_title.count()


class TestLimitParameter(TestSearchWithFacets):
    """Test limit parameter functionality."""
    
    def test_search_respects_limit(self, search_test_setup):
        """Test that search results respect the limit parameter."""
        data = search_test_setup
        service = FacetedSearchService(data['user'])
        
        results = service.search_with_facets(
            resource_type="projects",
            limit=2
        )
        
        # Should return at most 2 results
        assert results.count() <= 2
    
    def test_search_default_limit(self, search_test_setup):
        """Test default limit behavior."""
        data = search_test_setup
        service = FacetedSearchService(data['user'])
        
        results = service.search_with_facets(resource_type="projects")
        
        # Should return all 4 projects (within default limit)
        assert results.count() == 4