import pytest
from django.contrib.auth import get_user_model
from arkumu.metadata.models import Resource, Triple, HarmonizationRule
from arkumu.metadata.models.resource import ResourceType, PublicAccessLevel
from arkumu.metadata.services.catalog_navigation_service import CatalogNavigationService
from arkumu.users.models import Organization

User = get_user_model()


@pytest.mark.django_db
class TestCatalogNavigationService:
    
    @pytest.fixture
    def test_org(self):
        """Create test organization."""
        return Organization.objects.create(
            name="Test Archive",
            code="TEST"
        )
    
    @pytest.fixture
    def test_user(self, test_org):
        """Create test user with organization."""
        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass"
        )
        user.organization = test_org
        user.role = "admin"
        user.save()
        return user
    
    @pytest.fixture
    def rdf_predicates(self, test_org):
        """Create common RDF predicates."""
        rdf_type = Resource.objects.create(
            uri=CatalogNavigationService.RDF_TYPE,
            resource_type=ResourceType.PROPERTY,
            organization=test_org,
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True
        )
        
        rdfs_label = Resource.objects.create(
            uri=CatalogNavigationService.RDFS_LABEL,
            resource_type=ResourceType.PROPERTY,
            organization=test_org,
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True
        )
        
        has_event = Resource.objects.create(
            uri=CatalogNavigationService.HAS_EVENT,
            resource_type=ResourceType.PROPERTY,
            organization=test_org,
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True
        )
        
        return {
            'rdf_type': rdf_type,
            'rdfs_label': rdfs_label,
            'has_event': has_event
        }
    
    @pytest.fixture
    def arkumu_types(self, test_org):
        """Create Arkumu model type resources."""
        project_type = Resource.objects.create(
            uri=CatalogNavigationService.ARKUMU_PROJECT,
            resource_type=ResourceType.CLASS,
            organization=test_org,
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True
        )
        
        event_type = Resource.objects.create(
            uri=CatalogNavigationService.ARKUMU_EVENT,
            resource_type=ResourceType.CLASS,
            organization=test_org,
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True
        )
        
        return {
            'project': project_type,
            'event': event_type
        }
    
    @pytest.fixture
    def org_specific_types(self, test_org):
        """Create organization-specific type resources."""
        org_project_type = Resource.objects.create(
            uri=f"http://arkumu.org/data/{test_org.code}/types/Project",
            resource_type=ResourceType.CLASS,
            organization=test_org
        )
        
        org_event_type = Resource.objects.create(
            uri=f"http://arkumu.org/data/{test_org.code}/types/Event",
            resource_type=ResourceType.CLASS,
            organization=test_org
        )
        
        return {
            'project': org_project_type,
            'event': org_event_type
        }
    
    @pytest.fixture
    def harmonization_rules(self, arkumu_types, org_specific_types):
        """Create harmonization rules mapping org types to Arkumu types."""
        project_rule = HarmonizationRule.objects.create(
            source_organization=org_specific_types['project'].organization,
            source_property_pattern=org_specific_types['project'].uri,
            catalog_property_uri=arkumu_types['project'].uri,
            catalog_property_label="Project",
            mapping_type='exact',
            priority=1,
            is_active=True
        )
        
        event_rule = HarmonizationRule.objects.create(
            source_organization=org_specific_types['event'].organization,
            source_property_pattern=org_specific_types['event'].uri,
            catalog_property_uri=arkumu_types['event'].uri,
            catalog_property_label="Event",
            mapping_type='exact',
            priority=1,
            is_active=True
        )
        
        return {
            'project': project_rule,
            'event': event_rule
        }
    
    @pytest.fixture
    def sample_projects(self, test_org, rdf_predicates, org_specific_types):
        """Create sample project resources with relationships."""
        # Create project resources
        project1 = Resource.objects.create(
            uri=f"http://arkumu.org/data/{test_org.code}/project/1",
            resource_type=ResourceType.IRI,
            organization=test_org
        )
        
        project2 = Resource.objects.create(
            uri=f"http://arkumu.org/data/{test_org.code}/project/2",
            resource_type=ResourceType.IRI,
            organization=test_org,
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True
        )
        
        # Create labels
        label1 = Resource.objects.create(
            value="Test Project 1",
            resource_type=ResourceType.LITERAL,
            organization=test_org
        )
        
        label2 = Resource.objects.create(
            value="Public Project 2",
            resource_type=ResourceType.LITERAL,
            organization=test_org
        )
        
        # Type the projects (using org-specific types)
        Triple.objects.create(
            subject=project1,
            predicate=rdf_predicates['rdf_type'],
            object=org_specific_types['project'],
            source=test_org
        )
        
        Triple.objects.create(
            subject=project2,
            predicate=rdf_predicates['rdf_type'],
            object=org_specific_types['project'],
            source=test_org
        )
        
        # Add labels
        Triple.objects.create(
            subject=project1,
            predicate=rdf_predicates['rdfs_label'],
            object=label1,
            source=test_org
        )
        
        Triple.objects.create(
            subject=project2,
            predicate=rdf_predicates['rdfs_label'],
            object=label2,
            source=test_org
        )
        
        return {
            'project1': project1,
            'project2': project2,
            'label1': label1,
            'label2': label2
        }
    
    @pytest.fixture
    def sample_events(self, test_org, rdf_predicates, org_specific_types, sample_projects):
        """Create sample event resources linked to projects."""
        # Create event resources
        event1 = Resource.objects.create(
            uri=f"http://arkumu.org/data/{test_org.code}/event/1",
            resource_type=ResourceType.IRI,
            organization=test_org
        )
        
        event_label = Resource.objects.create(
            value="Project Meeting 2024",
            resource_type=ResourceType.LITERAL,
            organization=test_org
        )
        
        # Type the event
        Triple.objects.create(
            subject=event1,
            predicate=rdf_predicates['rdf_type'],
            object=org_specific_types['event'],
            source=test_org
        )
        
        # Add label
        Triple.objects.create(
            subject=event1,
            predicate=rdf_predicates['rdfs_label'],
            object=event_label,
            source=test_org
        )
        
        # Link event to project
        Triple.objects.create(
            subject=sample_projects['project1'],
            predicate=rdf_predicates['has_event'],
            object=event1,
            source=test_org
        )
        
        return {
            'event1': event1,
            'event_label': event_label
        }
    
    def test_get_harmonized_types(self, test_user, arkumu_types, org_specific_types, harmonization_rules):
        """Test getting all URIs that map to an Arkumu type."""
        service = CatalogNavigationService(test_user)
        
        # Get all URIs that represent "Project"
        project_uris = service._get_harmonized_types(CatalogNavigationService.ARKUMU_PROJECT)
        
        assert CatalogNavigationService.ARKUMU_PROJECT in project_uris
        assert org_specific_types['project'].uri in project_uris
        assert len(project_uris) == 2
    
    def test_get_all_projects_basic(self, test_user, sample_projects, harmonization_rules):
        """Test getting all projects without related resources."""
        service = CatalogNavigationService(test_user)
        
        projects = service.get_all_projects(
            include_events=False,
            include_participants=False,
            include_documents=False
        )
        
        # Should get both projects (user's org data)
        assert projects.count() == 2
        project_uris = [p.uri for p in projects]
        assert sample_projects['project1'].uri in project_uris
        assert sample_projects['project2'].uri in project_uris
    
    def test_get_all_projects_with_events(self, test_user, sample_projects, sample_events, harmonization_rules):
        """Test getting projects with related events."""
        service = CatalogNavigationService(test_user)
        
        projects = service.get_all_projects(
            include_events=True,
            include_participants=False,
            include_documents=False
        )
        
        assert projects.count() == 2
        
        # Check that event triples are prefetched
        for project in projects:
            if project.uri == sample_projects['project1'].uri:
                # This project has an event
                assert hasattr(project, 'event_triples')
                event_triples = project.event_triples
                assert len(event_triples) == 1
                assert event_triples[0].object.uri == sample_events['event1'].uri
    
    def test_get_project_with_full_graph(self, test_user, sample_projects, sample_events, harmonization_rules):
        """Test getting a project with its full relationship graph."""
        service = CatalogNavigationService(test_user)
        
        result = service.get_project_with_full_graph(
            sample_projects['project1'].uri,
            depth=2
        )
        
        assert result is not None
        assert result['project']['uri'] == sample_projects['project1'].uri
        assert 'Test Project 1' in result['project']['labels']
        
        # Check relationships
        relationships = result['project']['relationships']
        assert CatalogNavigationService.HAS_EVENT in relationships
        assert len(relationships[CatalogNavigationService.HAS_EVENT]) == 1
        
        # Check related resources (depth > 1)
        assert 'related_resources' in result
        # Event should be in related resources
        event_id = relationships[CatalogNavigationService.HAS_EVENT][0]['id']
        assert event_id in result['related_resources']
    
    def test_get_resource_counts_by_type(self, test_user, sample_projects, sample_events, harmonization_rules):
        """Test getting resource counts by type."""
        service = CatalogNavigationService(test_user)
        
        counts = service.get_resource_counts_by_type()
        
        assert counts['projects'] == 2
        assert counts['events'] == 1
        assert counts['persons'] == 0
        assert counts['organizations'] == 0
        assert counts['documents'] == 0
    
    def test_search_resources(self, test_user, sample_projects, harmonization_rules):
        """Test searching resources by label/value."""
        service = CatalogNavigationService(test_user)
        
        # Search without type filter
        results = service.search_resources("Project")
        assert results.count() == 2  # Both project labels contain "Project"
        
        # Search for actual project names (not labels)
        results = service.search_resources("project/1")
        assert results.count() == 1
        assert results.first().uri == sample_projects['project1'].uri
    
    def test_user_access_control(self, test_org, sample_projects, harmonization_rules):
        """Test that users only see appropriate resources."""
        # Create a user from a different organization
        other_org = Organization.objects.create(
            name="Other Archive",
            code="OTHER"
        )
        other_user = User.objects.create_user(
            username="otheruser",
            email="other@example.com",
            password="testpass"
        )
        other_user.organization = other_org
        other_user.role = "admin"
        other_user.save()
        
        service = CatalogNavigationService(other_user)
        projects = service.get_all_projects()
        
        # Should only see the public approved project
        assert projects.count() == 1
        assert projects.first().uri == sample_projects['project2'].uri
    
    def test_anonymous_user_access(self, sample_projects, rdf_predicates, org_specific_types, harmonization_rules):
        """Test that anonymous users only see public approved resources."""
        # Create anonymous user (not authenticated)
        class AnonymousUser:
            is_authenticated = False
            organization = None
        
        # Create a derived triple for the public project (anonymous users only see derived triples)
        Triple.objects.filter(
            subject=sample_projects['project2'],
            predicate=rdf_predicates['rdf_type']
        ).update(is_derived=True, source=None)
        
        anon_user = AnonymousUser()
        service = CatalogNavigationService(anon_user)
        
        projects = service.get_all_projects()
        
        # Should only see public approved project
        assert projects.count() == 1
        assert projects.first().uri == sample_projects['project2'].uri
    
    def test_prefetch_optimization(self, test_user, sample_projects, sample_events, harmonization_rules, django_assert_num_queries):
        """Test that queries are optimized with prefetch_related."""
        service = CatalogNavigationService(test_user)
        
        # Get projects with all relationships
        with django_assert_num_queries(7):  # Adjust based on actual query count
            projects = list(service.get_all_projects(
                include_events=True,
                include_participants=True,
                include_documents=True
            ))
            
            # Access prefetched data - should not trigger additional queries
            for project in projects:
                if hasattr(project, 'label_triples'):
                    _ = project.label_triples
                if hasattr(project, 'event_triples'):
                    _ = project.event_triples