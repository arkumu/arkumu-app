"""
Debug tests for catalog functionality to identify why queries are empty.
"""

import pytest
from django.test import TestCase
from django.contrib.auth import get_user_model

from arkumu.metadata.models import Resource, Triple, HarmonizationRule
from arkumu.metadata.models.resource import ResourceType, PublicAccessLevel
from arkumu.catalog.services.catalog_navigation_service import CatalogNavigationService
from arkumu.users.models import Organization

User = get_user_model()


class CatalogDebugTestCase(TestCase):
    """Debug test case to identify catalog issues."""
    
    def setUp(self):
        """Set up test data."""
        # Create test user and organization
        self.org = Organization.objects.create(
            name="Test Organization", 
            code="TEST",
            is_active=True
        )
        
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.user.organization = self.org
        self.user.save()
        
        self.service = CatalogNavigationService(self.user)
    
    def test_debug_basic_setup(self):
        """Test basic setup and service instantiation."""
        print(f"\n=== BASIC SETUP DEBUG ===")
        print(f"User: {self.user}")
        print(f"User organization: {self.user.organization}")
        print(f"Service: {self.service}")
        print(f"Arkumu Project URI: {self.service.ARKUMU_PROJECT}")
        print(f"RDF Type URI: {self.service.RDF_TYPE}")
        
        self.assertIsNotNone(self.service)
        self.assertEqual(self.user.organization, self.org)
    
    def test_debug_harmonization_rules(self):
        """Debug harmonization rules in the database."""
        print(f"\n=== HARMONIZATION RULES DEBUG ===")
        
        # Check if any harmonization rules exist
        all_rules = HarmonizationRule.objects.all()
        print(f"Total harmonization rules in DB: {all_rules.count()}")
        
        # Check active rules
        active_rules = HarmonizationRule.objects.filter(is_active=True)
        print(f"Active harmonization rules: {active_rules.count()}")
        
        # Check rules for Project type
        project_rules = HarmonizationRule.objects.filter(
            catalog_property_uri=self.service.ARKUMU_PROJECT
        )
        print(f"Rules mapping to ARKUMU_PROJECT: {project_rules.count()}")
        
        # Show some example rules
        for rule in active_rules[:5]:
            print(f"  Rule: {rule.source_property_pattern} -> {rule.catalog_property_uri}")
        
        # Test the harmonized types method
        harmonized_types = self.service._get_harmonized_types(self.service.ARKUMU_PROJECT)
        print(f"Harmonized types for Project: {harmonized_types}")
        
        self.assertGreaterEqual(len(harmonized_types), 1)  # Should at least include the base type
    
    def test_debug_resources_and_triples(self):
        """Debug resources and triples in the database."""
        print(f"\n=== RESOURCES AND TRIPLES DEBUG ===")
        
        # Check total resources
        all_resources = Resource.objects.all()
        print(f"Total resources in DB: {all_resources.count()}")
        
        # Check resources by organization
        org_resources = Resource.objects.filter(organization=self.org)
        print(f"Resources for {self.org.code}: {org_resources.count()}")
        
        # Check for RDF type resource
        rdf_type_resource = Resource.objects.filter(uri=self.service.RDF_TYPE).first()
        print(f"RDF Type resource exists: {rdf_type_resource is not None}")
        if rdf_type_resource:
            print(f"  RDF Type resource: {rdf_type_resource}")
        
        # Check total triples
        all_triples = Triple.objects.all()
        print(f"Total triples in DB: {all_triples.count()}")
        
        # Check triples with RDF type predicate
        if rdf_type_resource:
            type_triples = Triple.objects.filter(predicate=rdf_type_resource)
            print(f"Triples with rdf:type predicate: {type_triples.count()}")
            
            # Show some examples
            for triple in type_triples[:3]:
                print(f"  {triple.subject.uri} rdf:type {triple.object.uri}")
        
        # Check triples accessible to user
        user_triples = Triple.objects.for_user(self.user)
        print(f"Triples accessible to user: {user_triples.count()}")
    
    def test_debug_resource_counts(self):
        """Debug resource counts by type."""
        print(f"\n=== RESOURCE COUNTS DEBUG ===")
        
        # Test the resource counts method
        try:
            counts = self.service.get_resource_counts_by_type()
            print(f"Resource counts: {counts}")
            
            # Check each type individually
            for type_name, count in counts.items():
                print(f"  {type_name}: {count}")
                
        except Exception as e:
            print(f"Error getting resource counts: {e}")
            import traceback
            traceback.print_exc()
    
    def test_debug_project_query(self):
        """Debug the get_all_projects query."""
        print(f"\n=== PROJECT QUERY DEBUG ===")
        
        try:
            # Test project query
            projects = self.service.get_all_projects()
            print(f"Projects found: {projects.count()}")
            
            # Check the query step by step
            project_types = self.service._get_harmonized_types(self.service.ARKUMU_PROJECT)
            print(f"Project types to search for: {project_types}")
            
            # Check if RDF type resource exists
            rdf_type_resource = Resource.objects.filter(uri=self.service.RDF_TYPE).first()
            print(f"RDF type resource: {rdf_type_resource}")
            
            if rdf_type_resource:
                # Check project type triples
                project_triples = Triple.objects.for_user(self.user).filter(
                    predicate=rdf_type_resource,
                    object__uri__in=project_types
                )
                print(f"Project type triples: {project_triples.count()}")
                
                # Show what we find
                for triple in project_triples[:3]:
                    print(f"  Subject: {triple.subject.uri} -> Type: {triple.object.uri}")
            
        except Exception as e:
            print(f"Error in project query: {e}")
            import traceback
            traceback.print_exc()
    
    def test_debug_sample_data_creation(self):
        """Create some sample data to test with."""
        print(f"\n=== CREATING SAMPLE DATA ===")
        
        # Create RDF type resource if it doesn't exist
        rdf_type_resource, created = Resource.objects.get_or_create(
            uri=self.service.RDF_TYPE,
            defaults={
                'organization': self.org,
                'resource_type': ResourceType.IRI,
                'public_access_level': PublicAccessLevel.PUBLIC,
                'is_public_approved': True
            }
        )
        print(f"RDF type resource {'created' if created else 'exists'}: {rdf_type_resource}")
        
        # Create a Project type resource
        project_type_resource, created = Resource.objects.get_or_create(
            uri=self.service.ARKUMU_PROJECT,
            defaults={
                'organization': self.org,
                'resource_type': ResourceType.IRI,
                'public_access_level': PublicAccessLevel.PUBLIC,
                'is_public_approved': True
            }
        )
        print(f"Project type resource {'created' if created else 'exists'}: {project_type_resource}")
        
        # Create a sample project resource
        sample_project, created = Resource.objects.get_or_create(
            uri="http://example.org/project/1",
            defaults={
                'name': 'Sample Project',
                'organization': self.org,
                'resource_type': ResourceType.IRI,
                'public_access_level': PublicAccessLevel.PUBLIC,
                'is_public_approved': True
            }
        )
        print(f"Sample project {'created' if created else 'exists'}: {sample_project}")
        
        # Create a triple linking project to type
        sample_triple, created = Triple.objects.get_or_create(
            subject=sample_project,
            predicate=rdf_type_resource,
            object=project_type_resource,
            defaults={
                'organization': self.org
            }
        )
        print(f"Sample triple {'created' if created else 'exists'}: {sample_triple}")
        
        # Create a harmonization rule
        sample_rule, created = HarmonizationRule.objects.get_or_create(
            source_property_pattern="http://test.org/Project",
            catalog_property_uri=self.service.ARKUMU_PROJECT,
            defaults={
                'mapping_type': 'exact',
                'priority': 1,
                'is_active': True,
                'created_by': self.user
            }
        )
        print(f"Sample harmonization rule {'created' if created else 'exists'}: {sample_rule}")
        
        # Now test the queries again
        print(f"\n=== TESTING WITH SAMPLE DATA ===")
        
        # Test resource counts
        counts = self.service.get_resource_counts_by_type()
        print(f"Resource counts after sample data: {counts}")
        
        # Test project query
        projects = self.service.get_all_projects()
        print(f"Projects found after sample data: {projects.count()}")
        
        if projects.exists():
            project = projects.first()
            print(f"First project: {project.uri}")
    
    def test_debug_data_from_bulk_mapping(self):
        """Debug actual data created by bulk mapping."""
        print(f"\n=== BULK MAPPING DATA DEBUG ===")
        
        # Check for actual organizations from bulk mapping
        det_org = Organization.objects.filter(code='DET').first()
        rsh_org = Organization.objects.filter(code='RSH').first() 
        khm_org = Organization.objects.filter(code='KHM').first()
        
        print(f"DET organization exists: {det_org is not None}")
        print(f"RSH organization exists: {rsh_org is not None}")
        print(f"KHM organization exists: {khm_org is not None}")
        
        # Check harmonization rules for these orgs
        for org_code in ['DET', 'RSH', 'KHM']:
            rules = HarmonizationRule.objects.filter(
                source_property_pattern__icontains=org_code
            )
            print(f"Rules containing '{org_code}': {rules.count()}")
        
        # Check resources from these organizations
        if det_org:
            det_resources = Resource.objects.filter(organization=det_org).count()
            print(f"DET resources: {det_resources}")
        
        if rsh_org:
            rsh_resources = Resource.objects.filter(organization=rsh_org).count()
            print(f"RSH resources: {rsh_resources}")
        
        if khm_org:
            khm_resources = Resource.objects.filter(organization=khm_org).count()
            print(f"KHM resources: {khm_resources}")


def run_debug_tests():
    """Helper function to run debug tests manually."""
    import django
    django.setup()
    
    from django.test.utils import get_runner
    from django.conf import settings
    
    TestRunner = get_runner(settings)
    test_runner = TestRunner()
    
    # Run the debug test
    result = test_runner.run_tests(["arkumu.catalog.test_catalog_debug.CatalogDebugTestCase"])
    return result


if __name__ == "__main__":
    run_debug_tests()