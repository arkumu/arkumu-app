"""
Example usage of the CatalogNavigationService for optimized queries.

This demonstrates how to use the service to efficiently retrieve projects
and their related resources using the harmonization mappings.
"""

from django.contrib.auth import get_user_model
from arkumu.catalog.services.catalog_navigation_service import CatalogNavigationService

User = get_user_model()


def example_get_all_projects_with_events(user):
    """
    Example: Get all projects with their events.
    
    This uses optimized queries with prefetch_related to minimize database hits.
    """
    service = CatalogNavigationService(user)
    
    # Get all projects with events prefetched
    projects = service.get_all_projects(
        include_events=True,
        include_participants=False,
        include_documents=False
    )
    
    # Iterate through projects - events are already loaded
    for project in projects:
        print(f"Project: {project.uri}")
        
        # Access labels (if prefetched)
        if hasattr(project, 'label_triples'):
            for triple in project.label_triples:
                print(f"  Label: {triple.object.value}")
        
        # Access events (if prefetched)
        if hasattr(project, 'event_triples'):
            for triple in project.event_triples:
                event = triple.object
                print(f"  Event: {event.uri}")


def example_get_project_full_graph(user, project_uri):
    """
    Example: Get a single project with its complete relationship graph.
    
    This retrieves a project and follows relationships up to a specified depth.
    """
    service = CatalogNavigationService(user)
    
    # Get project with relationships up to 2 levels deep
    result = service.get_project_with_full_graph(project_uri, depth=2)
    
    if result:
        project = result['project']
        print(f"Project: {project['uri']}")
        print(f"Labels: {', '.join(project['labels'])}")
        
        # Show relationships
        for predicate_uri, objects in project['relationships'].items():
            print(f"\nRelationship: {predicate_uri}")
            for obj in objects:
                print(f"  - {obj['uri'] or obj['value']}")
        
        # Show related resources (depth > 1)
        if 'related_resources' in result:
            print("\nRelated Resources:")
            for resource_id, resource_data in result['related_resources'].items():
                print(f"  {resource_data['uri']}")


def example_catalog_overview(user):
    """
    Example: Get overview counts for catalog display.
    
    This efficiently counts resources by type using the harmonization mappings.
    """
    service = CatalogNavigationService(user)
    
    # Get counts by type
    counts = service.get_resource_counts_by_type()
    
    print("Catalog Overview:")
    print(f"  Projects: {counts['projects']}")
    print(f"  Events: {counts['events']}")
    print(f"  Persons: {counts['persons']}")
    print(f"  Organizations: {counts['organizations']}")
    print(f"  Documents: {counts['documents']}")


def example_search_projects(user, search_query):
    """
    Example: Search for projects by name/label.
    
    This searches across all accessible resources with optional type filtering.
    """
    service = CatalogNavigationService(user)
    
    # Search for projects containing the query
    results = service.search_resources(
        query=search_query,
        resource_types=[CatalogNavigationService.ARKUMU_PROJECT],
        limit=20
    )
    
    print(f"Search results for '{search_query}':")
    for resource in results:
        print(f"  - {resource.uri}")
        if resource.value:
            print(f"    Value: {resource.value}")


def example_django_view_usage():
    """
    Example: How to use in a Django view for catalog display.
    """
    from django.shortcuts import render
    from django.views.generic import ListView
    
    class ProjectCatalogView(ListView):
        template_name = 'catalog/projects.html'
        context_object_name = 'projects'
        paginate_by = 20
        
        def get_queryset(self):
            service = CatalogNavigationService(self.request.user)
            return service.get_all_projects(
                include_events=True,
                include_participants=True,
                include_documents=False
            )
        
        def get_context_data(self, **kwargs):
            context = super().get_context_data(**kwargs)
            service = CatalogNavigationService(self.request.user)
            
            # Add resource counts for navigation
            context['resource_counts'] = service.get_resource_counts_by_type()
            
            return context


# Template usage example:
"""
<!-- catalog/projects.html -->
<div class="catalog-nav">
    <h3>Resources</h3>
    <ul>
        <li>Projects ({{ resource_counts.projects }})</li>
        <li>Events ({{ resource_counts.events }})</li>
        <li>Persons ({{ resource_counts.persons }})</li>
    </ul>
</div>

<div class="project-list">
    {% for project in projects %}
        <div class="project-card">
            <h4>{{ project.uri }}</h4>
            
            <!-- Labels are prefetched -->
            {% if project.label_triples %}
                <p>
                {% for triple in project.label_triples %}
                    {{ triple.object.value }}{% if not forloop.last %}, {% endif %}
                {% endfor %}
                </p>
            {% endif %}
            
            <!-- Events are prefetched -->
            {% if project.event_triples %}
                <h5>Events:</h5>
                <ul>
                {% for triple in project.event_triples %}
                    <li>{{ triple.object.uri }}</li>
                {% endfor %}
                </ul>
            {% endif %}
        </div>
    {% endfor %}
</div>
"""