"""
Tests for FacetedSearchService focusing on harmonization filtering.
"""
import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase
from arkumu.metadata.models import Resource, Triple
from arkumu.users.models import Organization
from arkumu.metadata.models.resource import ResourceType, PublicAccessLevel
from arkumu.metadata.services.faceted_search_service import FacetedSearchService
from arkumu.users.models import User

User = get_user_model()


@pytest.mark.django_db
class TestFacetedSearchService:
    """Test harmonization filtering in FacetedSearchService."""
    
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
    def harmonization_predicates(self):
        """Create harmonization predicate resources."""
        owl_sameas = Resource.objects.create(
            uri='http://www.w3.org/2002/07/owl#sameAs',
            name='owl:sameAs',
            resource_type=ResourceType.PROPERTY
        )
        skos_exactmatch = Resource.objects.create(
            uri='http://www.w3.org/2004/02/skos/core#exactMatch',
            name='skos:exactMatch',
            resource_type=ResourceType.PROPERTY
        )
        return {'owl_sameas': owl_sameas, 'skos_exactmatch': skos_exactmatch}
    
    @pytest.fixture
    def catalog_resource(self):
        """Create catalog target resource."""
        return Resource.objects.create(
            uri='http://data.arkumu.org/catalog/project',
            name='Catalog Project',
            resource_type=ResourceType.CLASS
        )
    
    @pytest.fixture
    def harmonized_resource(self, organization, harmonization_predicates, catalog_resource):
        """Create a harmonized resource with mapping triple."""
        resource = Resource.objects.create(
            organization=organization,
            uri='http://test-uni.de/project/123',
            name='Harmonized Project',
            resource_type=ResourceType.IRI,
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True
        )
        
        # Create harmonization mapping triple
        Triple.objects.create(
            subject=resource,
            predicate=harmonization_predicates['owl_sameas'],
            object=catalog_resource
        )
        
        return resource
    
    @pytest.fixture
    def non_harmonized_resource(self, organization):
        """Create a non-harmonized resource without mapping triple."""
        return Resource.objects.create(
            organization=organization,
            uri='http://test-uni.de/project/456',
            name='Non-Harmonized Project',
            resource_type=ResourceType.IRI,
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True
        )


class TestHarmonizationFiltering(TestFacetedSearchService):
    """Test that only harmonized resources are returned."""
    
    def test_harmonized_base_queryset_includes_harmonized(self, user, harmonized_resource):
        """Test that harmonized resources are included in base queryset."""
        service = FacetedSearchService(user)
        queryset = service._get_harmonized_base_queryset()
        
        assert harmonized_resource in queryset
        assert queryset.count() == 1
    
    def test_harmonized_base_queryset_excludes_non_harmonized(self, user, non_harmonized_resource):
        """Test that non-harmonized resources are excluded from base queryset."""
        service = FacetedSearchService(user)
        queryset = service._get_harmonized_base_queryset()
        
        assert non_harmonized_resource not in queryset
        assert queryset.count() == 0
    
    def test_harmonized_base_queryset_mixed_resources(self, user, harmonized_resource, non_harmonized_resource):
        """Test that only harmonized resources are returned when both types exist."""
        service = FacetedSearchService(user)
        queryset = service._get_harmonized_base_queryset()
        
        assert harmonized_resource in queryset
        assert non_harmonized_resource not in queryset
        assert queryset.count() == 1


class TestSearchResourcesHarmonization(TestFacetedSearchService):
    """Test search_resources method with harmonization filtering."""
    
    def test_search_resources_finds_harmonized_only(self, user, harmonized_resource, non_harmonized_resource):
        """Test that text search only finds harmonized resources."""
        service = FacetedSearchService(user)
        results = service.search_resources(query="Project")
        
        assert harmonized_resource in results
        assert non_harmonized_resource not in results
        assert results.count() == 1
    
    def test_search_resources_empty_query_returns_none(self, user):
        """Test that empty query returns no results."""
        service = FacetedSearchService(user)
        results = service.search_resources(query="")
        
        assert results.count() == 0
        
    def test_search_resources_no_harmonized_returns_empty(self, user, non_harmonized_resource):
        """Test that search returns empty when no harmonized resources match."""
        service = FacetedSearchService(user)
        results = service.search_resources(query="Project")
        
        assert results.count() == 0


class TestAccessControl(TestFacetedSearchService):
    """Test access control with harmonization filtering."""
    
    def test_anonymous_user_sees_public_harmonized_only(self, harmonized_resource):
        """Test that anonymous users only see public harmonized resources."""
        from django.contrib.auth.models import AnonymousUser
        
        service = FacetedSearchService(AnonymousUser())
        queryset = service._get_harmonized_base_queryset()
        
        assert harmonized_resource in queryset
        assert queryset.count() == 1
    
    def test_private_harmonized_resource_hidden_from_anonymous(self, organization, harmonization_predicates, catalog_resource):
        """Test that private harmonized resources are hidden from anonymous users."""
        from django.contrib.auth.models import AnonymousUser
        
        private_resource = Resource.objects.create(
            organization=organization,
            uri='http://test-uni.de/private/123',
            name='Private Harmonized Project',
            resource_type=ResourceType.IRI,
            public_access_level=PublicAccessLevel.PRIVATE,
            is_public_approved=False
        )
        
        # Add harmonization mapping
        Triple.objects.create(
            subject=private_resource,
            predicate=harmonization_predicates['owl_sameas'],
            object=catalog_resource
        )
        
        service = FacetedSearchService(AnonymousUser())
        queryset = service._get_harmonized_base_queryset()
        
        assert private_resource not in queryset
        assert queryset.count() == 0