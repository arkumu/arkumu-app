"""
Django management command to debug catalog functionality with real data.
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

from arkumu.metadata.models import Resource, Triple, HarmonizationRule
from arkumu.catalog.services.catalog_navigation_service import CatalogNavigationService
from arkumu.users.models import Organization

User = get_user_model()


class Command(BaseCommand):
    help = 'Debug catalog functionality with real database data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--username',
            type=str,
            default='fco',
            help='Username to test with (default: fco)'
        )

    def handle(self, *args, **options):
        username = options['username']
        
        self.stdout.write(
            self.style.SUCCESS(f'=== CATALOG DEBUG FOR USER: {username} ===')
        )
        
        # Get user
        try:
            user = User.objects.get(username=username)
            self.stdout.write(f'User found: {user}')
            self.stdout.write(f'User organization: {user.organization}')
        except User.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'User {username} not found')
            )
            return
        
        # Create service
        service = CatalogNavigationService(user)
        
        # Debug basic info
        self.debug_basic_info(service)
        
        # Debug organizations
        self.debug_organizations()
        
        # Debug harmonization rules  
        self.debug_harmonization_rules(service)
        
        # Debug resources and triples
        self.debug_resources_and_triples(service, user)
        
        # Debug resource counts
        self.debug_resource_counts(service)
        
        # Debug project query
        self.debug_project_query(service)

    def debug_basic_info(self, service):
        """Debug basic service information."""
        self.stdout.write('\n=== BASIC INFO ===')
        self.stdout.write(f'Arkumu Project URI: {service.ARKUMU_PROJECT}')
        self.stdout.write(f'RDF Type URI: {service.RDF_TYPE}')
        self.stdout.write(f'Has Event URI: {service.HAS_EVENT}')

    def debug_organizations(self):
        """Debug organizations in the database."""
        self.stdout.write('\n=== ORGANIZATIONS ===')
        
        orgs = Organization.objects.all()
        self.stdout.write(f'Total organizations: {orgs.count()}')
        
        for org in orgs:
            self.stdout.write(f'  {org.code}: {org.name} (Active: {org.is_active})')
        
        # Check specific organizations
        for code in ['DET', 'RSH', 'KHM']:
            org = Organization.objects.filter(code=code).first()
            if org:
                resources_count = Resource.objects.filter(organization=org).count()
                self.stdout.write(f'  {code} has {resources_count} resources')

    def debug_harmonization_rules(self, service):
        """Debug harmonization rules."""
        self.stdout.write('\n=== HARMONIZATION RULES ===')
        
        all_rules = HarmonizationRule.objects.all()
        self.stdout.write(f'Total harmonization rules: {all_rules.count()}')
        
        active_rules = HarmonizationRule.objects.filter(is_active=True)
        self.stdout.write(f'Active harmonization rules: {active_rules.count()}')
        
        # Rules by target type
        for arkumu_type in [service.ARKUMU_PROJECT, service.ARKUMU_EVENT, service.ARKUMU_PERSON]:
            rules = HarmonizationRule.objects.filter(
                catalog_property_uri=arkumu_type,
                is_active=True
            )
            type_name = arkumu_type.split('/')[-1]
            self.stdout.write(f'  {type_name} rules: {rules.count()}')
            
            # Show first few rules
            for rule in rules[:3]:
                self.stdout.write(f'    {rule.source_property_pattern} -> {rule.catalog_property_uri}')
        
        # Test harmonized types method
        project_types = service._get_harmonized_types(service.ARKUMU_PROJECT)
        self.stdout.write(f'Harmonized Project types: {len(project_types)}')
        for ptype in project_types[:5]:
            self.stdout.write(f'  {ptype}')

    def debug_resources_and_triples(self, service, user):
        """Debug resources and triples."""
        self.stdout.write('\n=== RESOURCES AND TRIPLES ===')
        
        # Total resources
        all_resources = Resource.objects.all()
        self.stdout.write(f'Total resources: {all_resources.count()}')
        
        # Resources by type
        for resource_type in ['IRI', 'CLASS', 'PROPERTY', 'LITERAL']:
            count = Resource.objects.filter(resource_type=resource_type).count()
            self.stdout.write(f'  {resource_type} resources: {count}')
        
        # Check RDF type resource
        rdf_type_resource = Resource.objects.filter(uri=service.RDF_TYPE).first()
        self.stdout.write(f'RDF type resource exists: {rdf_type_resource is not None}')
        
        # Total triples
        all_triples = Triple.objects.all()
        self.stdout.write(f'Total triples: {all_triples.count()}')
        
        # User accessible triples
        user_triples = Triple.objects.for_user(user)
        self.stdout.write(f'User accessible triples: {user_triples.count()}')
        
        # Type triples
        if rdf_type_resource:
            type_triples = Triple.objects.filter(predicate=rdf_type_resource)
            self.stdout.write(f'Type triples (rdf:type): {type_triples.count()}')
            
            # Show some examples
            for triple in type_triples[:3]:
                self.stdout.write(f'  {triple.subject.uri} rdf:type {triple.object.uri}')

    def debug_resource_counts(self, service):
        """Debug resource counts by type."""
        self.stdout.write('\n=== RESOURCE COUNTS ===')
        
        try:
            counts = service.get_resource_counts_by_type()
            self.stdout.write(f'Resource counts: {counts}')
            
            total = sum(counts.values())
            self.stdout.write(f'Total harmonized resources: {total}')
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error getting resource counts: {e}')
            )
            import traceback
            traceback.print_exc()

    def debug_project_query(self, service):
        """Debug project query step by step."""
        self.stdout.write('\n=== PROJECT QUERY DEBUG ===')
        
        try:
            # Get harmonized types
            project_types = service._get_harmonized_types(service.ARKUMU_PROJECT)
            self.stdout.write(f'Looking for project types: {project_types}')
            
            # Check RDF type resource
            rdf_type_resource = Resource.objects.filter(uri=service.RDF_TYPE).first()
            if not rdf_type_resource:
                self.stdout.write(self.style.ERROR('No RDF type resource found!'))
                return
            
            # Find triples with these types
            type_triples = Triple.objects.filter(
                predicate=rdf_type_resource,
                object__uri__in=project_types
            )
            self.stdout.write(f'Type triples found: {type_triples.count()}')
            
            # Show examples
            for triple in type_triples[:5]:
                self.stdout.write(f'  {triple.subject.uri} -> {triple.object.uri}')
            
            # Get subject IDs
            project_ids = list(type_triples.values_list('subject_id', flat=True))
            self.stdout.write(f'Project IDs found: {len(project_ids)}')
            
            # Try the actual service call
            projects = service.get_all_projects()
            self.stdout.write(f'Service returned projects: {projects.count()}')
            
            # Show first few projects
            for project in projects[:3]:
                self.stdout.write(f'  Project: {project.uri} (Org: {project.organization})')
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error in project query: {e}')
            )
            import traceback
            traceback.print_exc()