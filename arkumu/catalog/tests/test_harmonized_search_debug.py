"""
Test to debug harmonized search issues.
"""
import pytest
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from arkumu.metadata.models import Resource, Triple, HarmonizationRule
from arkumu.metadata.models.resource import ResourceType, PublicAccessLevel
from arkumu.users.models import Organization
from arkumu.metadata.services.faceted_search_service import FacetedSearchService
from arkumu.catalog.views import HarmonizedSearchView, LiveSearchFilterView

User = get_user_model()


@pytest.mark.django_db
class TestHarmonizedSearchDebug(TestCase):
    """Debug harmonized search issues with real data patterns."""
    
    def setUp(self):
        """Set up test data matching production patterns."""
        # Create organizations
        self.rsh_org = Organization.objects.create(
            id=1,
            name="RSH",
            code="rsh"
        )
        self.det_org = Organization.objects.create(
            id=5,
            name="DET",
            code="det"
        )
        self.khm_org = Organization.objects.create(
            id=3,
            name="KHM",
            code="khm"
        )
        
        # Create user
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            organization=self.rsh_org
        )
        
        # Create RDF type predicate with proper access control
        self.rdf_type = Resource.objects.create(
            uri='http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
            name='rdf:type',
            resource_type=ResourceType.PROPERTY,
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True
        )
        
        # Create Arkumu project type with proper access control
        self.arkumu_project = Resource.objects.create(
            uri='http://arkumu.org/types/projekt',
            name='Project',
            resource_type=ResourceType.CLASS,
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True
        )
        
        # Create organization-specific project types with proper access control
        self.rsh_project_type = Resource.objects.create(
            uri='http://rsh.de/types/projekt',
            name='RSH Project Type',
            resource_type=ResourceType.CLASS,
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True
        )
        
        self.det_project_type = Resource.objects.create(
            uri='http://det.de/types/projekt',
            name='DET Project Type',
            resource_type=ResourceType.CLASS,
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True
        )
        
        # Create harmonization rules for organizations 1 and 5 only
        HarmonizationRule.objects.create(
            source_organization_id=1,  # rsh
            source_property_pattern='http://rsh.de/types/projekt',
            catalog_property_uri='http://arkumu.org/types/projekt',
            is_active=True
        )
        HarmonizationRule.objects.create(
            source_organization_id=5,  # det
            source_property_pattern='http://det.de/types/projekt',
            catalog_property_uri='http://arkumu.org/types/projekt',
            is_active=True
        )
        # Note: No harmonization rule for KHM (org_id=3)
        
        # Create resources from different organizations
        self.rsh_project = Resource.objects.create(
            organization=self.rsh_org,
            uri='http://rsh.de/projects/1',
            name='RSH Project',
            resource_type=ResourceType.IRI,
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True
        )
        
        self.det_project = Resource.objects.create(
            organization=self.det_org,
            uri='http://det.de/projects/1',
            name='DET Project',
            resource_type=ResourceType.IRI,
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True
        )
        
        self.khm_project = Resource.objects.create(
            organization=self.khm_org,
            uri='http://khm.de/projects/1',
            name='KHM Project (should be excluded)',
            resource_type=ResourceType.IRI,
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True
        )
        
        # Add type triples - use organization-specific types
        Triple.objects.create(
            subject=self.rsh_project,
            predicate=self.rdf_type,
            object=self.rsh_project_type  # RSH projects use RSH type
        )
        Triple.objects.create(
            subject=self.det_project,
            predicate=self.rdf_type,
            object=self.det_project_type  # DET projects use DET type
        )
        Triple.objects.create(
            subject=self.khm_project,
            predicate=self.rdf_type,
            object=self.arkumu_project  # KHM uses generic type (no harmonization)
        )
    
    def test_harmonization_rule_lookup(self):
        """Test that harmonization rules are correctly identified."""
        from django.db.models import Q
        
        harmonized_org_ids = HarmonizationRule.objects.filter(
            is_active=True
        ).values_list('source_organization_id', flat=True).distinct()
        
        harmonized_org_ids_list = list(harmonized_org_ids)
        print(f"Harmonized org IDs: {harmonized_org_ids_list}")
        
        # Should have organizations 1 and 5
        self.assertIn(1, harmonized_org_ids_list)
        self.assertIn(5, harmonized_org_ids_list)
        self.assertNotIn(3, harmonized_org_ids_list)  # KHM should not be included
    
    def test_resource_organization_ids(self):
        """Test that resources have correct organization_id values."""
        print(f"RSH project org_id: {self.rsh_project.organization_id}")
        print(f"DET project org_id: {self.det_project.organization_id}")
        print(f"KHM project org_id: {self.khm_project.organization_id}")
        
        self.assertEqual(self.rsh_project.organization_id, 1)
        self.assertEqual(self.det_project.organization_id, 5)
        self.assertEqual(self.khm_project.organization_id, 3)
    
    def test_harmonized_types_lookup(self):
        """Test that _get_harmonized_types returns correct organization-specific types."""
        from arkumu.metadata.services.catalog_navigation_service import CatalogNavigationService
        
        service = CatalogNavigationService(self.user)
        harmonized_types = service._get_harmonized_types('http://arkumu.org/types/projekt')
        
        print(f"Harmonized types for projects: {harmonized_types}")
        
        # Should include the generic Arkumu type and org-specific types
        self.assertIn('http://arkumu.org/types/projekt', harmonized_types)
        self.assertIn('http://rsh.de/types/projekt', harmonized_types)
        self.assertIn('http://det.de/types/projekt', harmonized_types)
    
    def test_harmonized_base_queryset(self):
        """Test the harmonized base queryset logic."""
        service = FacetedSearchService(self.user)
        
        # Test the harmonized base queryset
        harmonized_queryset = service._get_harmonized_base_queryset()
        harmonized_count = harmonized_queryset.count()
        
        print(f"Harmonized queryset count: {harmonized_count}")
        print(f"Harmonized resources: {list(harmonized_queryset.values_list('id', 'organization_id', 'name'))}")
        
        # Should include RSH and DET projects, exclude KHM
        self.assertEqual(harmonized_count, 2)
        
        harmonized_ids = set(harmonized_queryset.values_list('id', flat=True))
        self.assertIn(self.rsh_project.id, harmonized_ids)
        self.assertIn(self.det_project.id, harmonized_ids)
        self.assertNotIn(self.khm_project.id, harmonized_ids)
    
    def test_search_with_facets_no_query(self):
        """Test search with facets when no query is provided."""
        service = FacetedSearchService(self.user)
        
        # Debug the individual steps
        print("\n=== DEBUG search_with_facets for projects ===")
        
        # Check harmonized base queryset
        harmonized_resources = service._get_harmonized_base_queryset()
        print(f"Harmonized base queryset count: {harmonized_resources.count()}")
        print(f"Harmonized resources: {list(harmonized_resources.values_list('id', 'organization_id', 'name'))}")
        
        # Check harmonized types
        project_types = service._get_harmonized_types(service.ARKUMU_PROJECT)
        print(f"Project types: {project_types}")
        
        # Check RDF type resource
        rdf_type_resource = Resource.objects.filter(uri=service.RDF_TYPE).first()
        print(f"RDF type resource: {rdf_type_resource}")
        
        # Check project triples
        if rdf_type_resource:
            # First, let's see what triples actually exist (without access control)
            all_rdf_type_triples_raw = Triple.objects.filter(
                predicate=rdf_type_resource,
                subject__in=harmonized_resources
            )
            print(f"All rdf:type triples (raw): {all_rdf_type_triples_raw.count()}")
            print(f"All rdf:type triples (raw): {list(all_rdf_type_triples_raw.values_list('subject_id', 'object__uri', 'object__name'))}")
            
            # Now with access control
            all_rdf_type_triples = Triple.objects.for_user(self.user).filter(
                predicate=rdf_type_resource,
                subject__in=harmonized_resources
            )
            print(f"All rdf:type triples (for_user): {all_rdf_type_triples.count()}")
            print(f"All rdf:type triples (for_user): {list(all_rdf_type_triples.values_list('subject_id', 'object__uri', 'object__name'))}")
            
            project_triples = Triple.objects.for_user(self.user).filter(
                predicate=rdf_type_resource,
                object__uri__in=project_types,
                subject__in=harmonized_resources
            )
            print(f"Project triples count: {project_triples.count()}")
            print(f"Project triples: {list(project_triples.values_list('subject_id', 'object__uri'))}")
            
            project_ids = list(project_triples.values_list('subject_id', flat=True))
            print(f"Project IDs from triples: {project_ids}")
        
        # Search for projects without query
        results = service.search_with_facets(
            query="",
            resource_type="projects",
            facet_filters={},
            limit=50
        )
        
        result_count = results.count()
        print(f"Final search results count: {result_count}")
        print(f"Final search results: {list(results.values_list('id', 'organization_id', 'name'))}")
        
        # Should return harmonized projects only
        self.assertEqual(result_count, 2)
        
        result_ids = set(results.values_list('id', flat=True))
        self.assertIn(self.rsh_project.id, result_ids)
        self.assertIn(self.det_project.id, result_ids)
        self.assertNotIn(self.khm_project.id, result_ids)
    
    def test_search_with_text_query(self):
        """Test text search in harmonized resources."""
        service = FacetedSearchService(self.user)
        
        # Add some literal properties for text search
        title_prop = Resource.objects.create(
            uri='http://example.org/title',
            name='Title',
            resource_type=ResourceType.PROPERTY
        )
        
        rsh_title = Resource.objects.create(
            organization=self.rsh_org,
            value="Searchable RSH Project Title",
            resource_type=ResourceType.LITERAL,
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True
        )
        
        Triple.objects.create(
            subject=self.rsh_project,
            predicate=title_prop,
            object=rsh_title
        )
        
        # Search for "Searchable"
        results = service.search_with_facets(
            query="Searchable",
            resource_type="projects",
            facet_filters={},
            limit=50
        )
        
        result_count = results.count()
        print(f"Text search results count: {result_count}")
        print(f"Text search results: {list(results.values_list('id', 'organization_id', 'name'))}")
        
        # Should find the RSH project
        self.assertEqual(result_count, 1)
        self.assertEqual(results.first().id, self.rsh_project.id)
    
    def test_harmonized_search_view(self):
        """Test the HarmonizedSearchView."""
        factory = RequestFactory()
        request = factory.get('/catalog/search/', {
            'type': 'projects'
        })
        request.user = self.user
        
        view = HarmonizedSearchView()
        view.request = request
        
        queryset = view.get_queryset()
        context = view.get_context_data()
        
        print(f"View queryset count: {queryset.count()}")
        print(f"View context result_count: {context.get('result_count', 'Not set')}")
        
        # Should return harmonized projects
        self.assertEqual(queryset.count(), 2)
        
        # Context should have proper data
        self.assertIn('available_types', context)
        self.assertIn('all_properties', context)
    
    def test_live_search_filter_view(self):
        """Test the LiveSearchFilterView for HTMX updates."""
        factory = RequestFactory()
        request = factory.get('/catalog/search/filter/', {
            'type': 'projects',
            'q': ''
        })
        request.user = self.user
        
        view = LiveSearchFilterView()
        response = view.get(request)
        
        print(f"Live search response status: {response.status_code}")
        print(f"Live search response content length: {len(response.content)}")
        
        # Should return HTTP 200
        self.assertEqual(response.status_code, 200)
        
        # Response should contain HTML with results
        response_content = response.content.decode('utf-8')
        self.assertIn('RSH Project', response_content)
        self.assertIn('DET Project', response_content)
        self.assertNotIn('KHM Project', response_content)
    
    def test_debug_null_organization_ids(self):
        """Test handling of resources with NULL organization_id."""
        # Create resource with NULL organization_id
        null_org_resource = Resource.objects.create(
            organization=None,  # This creates NULL organization_id
            uri='http://example.org/null-org-resource',
            name='Null Org Resource',
            resource_type=ResourceType.IRI,
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True
        )
        
        # Add type triple
        Triple.objects.create(
            subject=null_org_resource,
            predicate=self.rdf_type,
            object=self.arkumu_project
        )
        
        service = FacetedSearchService(self.user)
        harmonized_queryset = service._get_harmonized_base_queryset()
        
        print(f"NULL org resource organization_id: {null_org_resource.organization_id}")
        print(f"Harmonized queryset with NULL org: {harmonized_queryset.count()}")
        
        # NULL organization_id should be excluded from harmonized results
        harmonized_ids = set(harmonized_queryset.values_list('id', flat=True))
        self.assertNotIn(null_org_resource.id, harmonized_ids)