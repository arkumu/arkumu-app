# Property-Based Graph Search Implementation

## Overview

Replace the current broken faceted search with a property-specific search that returns complete connected graphs instead of isolated entity IDs.

## Core Concept

**Search Flow:**
1. User searches "Machine Learning" in `title` property
2. Find all entities that have `title` containing "Machine Learning"
3. For each matching entity, retrieve the complete connected graph
4. Return rich data with all related entities and their properties

## Implementation

### 1. New Graph Search Service

**File:** `arkumu/catalog/services/graph_search_service.py`

```python
"""
Property-Based Graph Search Service

Replaces faceted search with graph-based exploration starting from property searches.
"""

from typing import Dict, List, Optional, Any, Set
import logging
from django.db.models import Q
from arkumu.metadata.models import Resource, Triple, ResourceType

logger = logging.getLogger(__name__)


class GraphSearchService:
    """
    Property-based search with complete graph retrieval.

    Allows searching for specific property values and returns the complete
    connected data graph for matching entities.
    """

    def __init__(self, user=None):
        self.user = user

    def search_by_property_with_graph(self,
                                    query: str,
                                    property_name: str,
                                    resource_type: str = None,
                                    limit: int = 50) -> List[Dict]:
        """
        Search for entities by property value and return complete graphs.

        Args:
            query: Search term to find in property values
            property_name: Property to search in (e.g., 'title', 'name', 'description')
            resource_type: Optional entity type filter (e.g., 'project', 'person')
            limit: Maximum number of results

        Returns:
            List of entity graphs with complete connected data
        """
        logger.info(f"Graph search: '{query}' in property '{property_name}'")

        # Generate property URI
        property_uri = self._generate_property_uri(property_name)

        # Find triples: subject -[property]-> literal_containing_query
        matching_triples_query = Triple.objects.filter(
            predicate__uri=property_uri,
            object__resource_type=ResourceType.LITERAL,
            object__value__icontains=query
        ).select_related('subject', 'object')

        # Apply resource type filter if specified
        if resource_type:
            type_uri = self._generate_type_uri(resource_type)
            # Filter subjects that have rdf:type matching resource_type
            matching_triples_query = matching_triples_query.filter(
                subject__in=Triple.objects.filter(
                    predicate__uri='http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
                    object__uri=type_uri
                ).values_list('subject_id', flat=True)
            )

        # Execute query with limit
        matching_triples = matching_triples_query[:limit * 2]  # Buffer for deduplication

        # Extract unique entities
        matching_entities = list({triple.subject.id: triple.subject
                                for triple in matching_triples}.values())[:limit]

        logger.info(f"Found {len(matching_entities)} entities matching search")

        # Get complete graph for each entity
        results = []
        for entity in matching_entities:
            entity_graph = self._get_complete_entity_graph(entity)
            results.append(entity_graph)

        return results

    def _get_complete_entity_graph(self, entity: Resource) -> Dict:
        """
        Get the complete connected graph for an entity.

        Includes:
        - All literal properties of the entity
        - All outgoing relationships (entity -> other entities)
        - All incoming relationships (other entities -> entity)
        - Full property data for all connected entities
        """
        logger.debug(f"Building graph for entity: {entity.uri}")

        # Get all outgoing triples (this entity as subject)
        outgoing_triples = Triple.objects.filter(
            subject=entity
        ).select_related('predicate', 'object')

        # Get all incoming triples (this entity as object)
        incoming_triples = Triple.objects.filter(
            object=entity,
            subject__resource_type=ResourceType.IRI  # Only entity -> entity relationships
        ).select_related('predicate', 'subject')

        # Initialize entity data structure
        entity_data = {
            'entity_uri': entity.uri,
            'entity_type': self._extract_entity_type(entity),
            'properties': {},  # Direct literal properties
            'outgoing_relations': {},  # This entity -> other entities
            'incoming_relations': {},  # Other entities -> this entity
            'connected_entities': {}  # Full data for connected entities
        }

        # Track connected entity IDs for batch loading
        connected_entity_ids = set()

        # Process outgoing relationships
        for triple in outgoing_triples:
            property_name = self._extract_property_name(triple.predicate.uri)

            if triple.object.resource_type == ResourceType.LITERAL:
                # Direct property: entity -> property -> literal
                if property_name not in entity_data['properties']:
                    entity_data['properties'][property_name] = []
                entity_data['properties'][property_name].append(triple.object.value)

            elif triple.object.resource_type == ResourceType.IRI:
                # Relationship: entity -> property -> other_entity
                if property_name not in entity_data['outgoing_relations']:
                    entity_data['outgoing_relations'][property_name] = []
                entity_data['outgoing_relations'][property_name].append({
                    'uri': triple.object.uri,
                    'type': self._extract_entity_type(triple.object)
                })
                connected_entity_ids.add(triple.object.id)

        # Process incoming relationships
        for triple in incoming_triples:
            property_name = self._extract_property_name(triple.predicate.uri)

            if property_name not in entity_data['incoming_relations']:
                entity_data['incoming_relations'][property_name] = []
            entity_data['incoming_relations'][property_name].append({
                'uri': triple.subject.uri,
                'type': self._extract_entity_type(triple.subject)
            })
            connected_entity_ids.add(triple.subject.id)

        # Get full data for all connected entities (batch loading)
        if connected_entity_ids:
            connected_entities = Resource.objects.filter(
                id__in=connected_entity_ids,
                resource_type=ResourceType.IRI
            )

            for connected_entity in connected_entities:
                entity_data['connected_entities'][connected_entity.uri] = \
                    self._get_entity_basic_data(connected_entity)

        # Flatten single-item property lists for cleaner output
        for prop_name, values in entity_data['properties'].items():
            if len(values) == 1:
                entity_data['properties'][prop_name] = values[0]

        logger.debug(f"Graph built: {len(entity_data['properties'])} properties, "
                    f"{len(connected_entity_ids)} connected entities")

        return entity_data

    def _get_entity_basic_data(self, entity: Resource) -> Dict:
        """
        Get basic property data for connected entities.

        Only includes literal properties, no further graph traversal
        to avoid infinite recursion.
        """
        properties = {}

        # Get all literal properties for this entity
        property_triples = Triple.objects.filter(
            subject=entity,
            object__resource_type=ResourceType.LITERAL
        ).select_related('predicate', 'object')

        for triple in property_triples:
            property_name = self._extract_property_name(triple.predicate.uri)
            if property_name not in properties:
                properties[property_name] = []
            properties[property_name].append(triple.object.value)

        # Flatten single-item lists
        for prop_name, values in properties.items():
            if len(values) == 1:
                properties[prop_name] = values[0]

        return {
            'uri': entity.uri,
            'type': self._extract_entity_type(entity),
            'properties': properties
        }

    def _extract_property_name(self, property_uri: str) -> str:
        """Extract property name from URI."""
        # http://arkumu.org/data/properties/title -> "title"
        return property_uri.split('/')[-1].replace('-', '_')

    def _extract_entity_type(self, entity: Resource) -> str:
        """Extract entity type from rdf:type relationships."""
        try:
            rdf_type_triple = Triple.objects.filter(
                subject=entity,
                predicate__uri='http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
            ).first()

            if rdf_type_triple:
                return rdf_type_triple.object.uri.split('/')[-1]
            return 'entity'
        except Exception:
            return 'entity'

    def _generate_property_uri(self, property_name: str) -> str:
        """Generate property URI from property name."""
        # This should match the URI generation logic from your importer
        # For now, assume canonical form
        property_slug = property_name.replace('_', '-')
        return f"http://arkumu.org/data/properties/{property_slug}"

    def _generate_type_uri(self, type_name: str) -> str:
        """Generate type URI from type name."""
        # This should match the URI generation logic from your importer
        type_slug = type_name.replace('_', '-')
        return f"http://arkumu.org/data/types/{type_slug}"

    def get_available_properties(self, resource_type: str = None) -> List[Dict]:
        """
        Get list of searchable properties, optionally filtered by resource type.

        Returns properties that actually exist in the data with usage counts.
        """
        query = Triple.objects.filter(
            object__resource_type=ResourceType.LITERAL
        ).values('predicate__uri').distinct()

        if resource_type:
            type_uri = self._generate_type_uri(resource_type)
            # Filter to properties used by entities of the specified type
            entities_of_type = Triple.objects.filter(
                predicate__uri='http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
                object__uri=type_uri
            ).values_list('subject_id', flat=True)

            query = query.filter(subject_id__in=entities_of_type)

        properties = []
        for result in query[:50]:  # Limit for performance
            property_uri = result['predicate__uri']
            property_name = self._extract_property_name(property_uri)

            # Get usage count
            usage_count = Triple.objects.filter(
                predicate__uri=property_uri,
                object__resource_type=ResourceType.LITERAL
            ).count()

            properties.append({
                'name': property_name,
                'uri': property_uri,
                'usage_count': usage_count
            })

        # Sort by usage count
        properties.sort(key=lambda x: x['usage_count'], reverse=True)
        return properties
```

### 2. Integration with Explorer

**Update:** `arkumu/catalog/views_explorer.py`

```python
# Add import
from arkumu.catalog.services.graph_search_service import GraphSearchService

class CatalogExplorerView(LoginRequiredMixin, TemplateView):
    # ... existing code ...

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Get query parameters
        query = self.request.GET.get('q', '')
        property_name = self.request.GET.get('property', 'title')  # Default to title search
        resource_type = self.request.GET.get('class', '')

        if query:
            # Use graph search instead of faceted search
            graph_service = GraphSearchService(user=self.request.user)

            search_results = graph_service.search_by_property_with_graph(
                query=query,
                property_name=property_name,
                resource_type=resource_type,
                limit=20
            )

            context['search_results'] = search_results
            context['search_query'] = query
            context['search_property'] = property_name
            context['result_count'] = len(search_results)

        # Get available properties for search
        graph_service = GraphSearchService(user=self.request.user)
        context['available_properties'] = graph_service.get_available_properties(resource_type)

        return context
```

### 3. New Template Structure

**File:** `arkumu/catalog/templates/catalog/graph_explorer.html`

```html
{% extends "base.html" %}
{% load static catalog_tags %}

{% block title %}Graph Explorer{% endblock %}

{% block content %}
<div class="container-fluid mx-auto px-4 py-6">
    <h1 class="text-2xl font-bold mb-4">Graph Search</h1>

    <!-- Search Form -->
    <form method="get" class="mb-6">
        <div class="flex gap-4 mb-4">
            <!-- Search Query -->
            <input type="text" name="q" value="{{ search_query }}"
                   placeholder="Search for content..."
                   class="flex-1 px-4 py-2 border rounded-lg">

            <!-- Property Selection -->
            <select name="property" class="px-4 py-2 border rounded-lg">
                {% for prop in available_properties %}
                <option value="{{ prop.name }}" {% if prop.name == search_property %}selected{% endif %}>
                    {{ prop.name|title }} ({{ prop.usage_count }})
                </option>
                {% endfor %}
            </select>

            <!-- Resource Type Filter -->
            <select name="class" class="px-4 py-2 border rounded-lg">
                <option value="">All Types</option>
                <!-- Add available types here -->
            </select>

            <button type="submit" class="px-6 py-2 bg-blue-500 text-white rounded-lg">
                Search Graph
            </button>
        </div>
    </form>

    <!-- Search Results -->
    {% if search_results %}
    <div class="mb-4">
        <h2 class="text-lg font-semibold">Found {{ result_count }} connected graphs</h2>
    </div>

    <div class="space-y-6">
        {% for entity_graph in search_results %}
        <div class="border rounded-lg p-6 bg-white shadow-sm">

            <!-- Main Entity Header -->
            <div class="border-b pb-4 mb-4">
                <div class="flex justify-between items-start">
                    <div>
                        <h3 class="text-xl font-bold text-blue-600">
                            {{ entity_graph.properties.title|default:entity_graph.properties.name|default:"Untitled" }}
                        </h3>
                        <p class="text-sm text-gray-500">{{ entity_graph.entity_type|title }} • {{ entity_graph.entity_uri }}</p>
                    </div>
                </div>
            </div>

            <!-- Main Entity Properties -->
            <div class="grid md:grid-cols-2 gap-6">

                <!-- Primary Properties -->
                <div>
                    <h4 class="font-semibold mb-2 text-gray-700">Properties</h4>
                    <div class="space-y-2">
                        {% for prop_name, value in entity_graph.properties.items %}
                        <div class="flex">
                            <span class="font-medium text-gray-600 w-24">{{ prop_name|title }}:</span>
                            <span class="text-gray-900">
                                {% if value|length > 100 %}
                                    {{ value|truncatechars:100 }}
                                {% else %}
                                    {{ value }}
                                {% endif %}
                            </span>
                        </div>
                        {% endfor %}
                    </div>
                </div>

                <!-- Connected Entities -->
                <div>
                    <h4 class="font-semibold mb-2 text-gray-700">Connected Data</h4>

                    <!-- Outgoing Relationships -->
                    {% if entity_graph.outgoing_relations %}
                    <div class="mb-4">
                        <h5 class="text-sm font-medium text-gray-600 mb-2">Related To:</h5>
                        {% for relation_type, related_entities in entity_graph.outgoing_relations.items %}
                        <div class="mb-2">
                            <span class="text-xs font-medium text-blue-600">{{ relation_type|title }}:</span>
                            <div class="ml-4">
                                {% for related in related_entities %}
                                <div class="text-sm bg-blue-50 rounded px-2 py-1 mb-1 inline-block mr-2">
                                    {% if related.uri in entity_graph.connected_entities %}
                                        {% with connected=entity_graph.connected_entities|get_item:related.uri %}
                                        <strong>{{ connected.properties.name|default:connected.properties.title|default:related.type }}</strong>
                                        {% if connected.properties.description %}
                                            <br><span class="text-xs text-gray-600">{{ connected.properties.description|truncatechars:50 }}</span>
                                        {% endif %}
                                        {% endwith %}
                                    {% else %}
                                        {{ related.type|title }}
                                    {% endif %}
                                </div>
                                {% endfor %}
                            </div>
                        </div>
                        {% endfor %}
                    </div>
                    {% endif %}

                    <!-- Incoming Relationships -->
                    {% if entity_graph.incoming_relations %}
                    <div>
                        <h5 class="text-sm font-medium text-gray-600 mb-2">Referenced By:</h5>
                        {% for relation_type, related_entities in entity_graph.incoming_relations.items %}
                        <div class="mb-2">
                            <span class="text-xs font-medium text-green-600">{{ relation_type|title }}:</span>
                            <div class="ml-4">
                                {% for related in related_entities %}
                                <div class="text-sm bg-green-50 rounded px-2 py-1 mb-1 inline-block mr-2">
                                    {% if related.uri in entity_graph.connected_entities %}
                                        {% with connected=entity_graph.connected_entities|get_item:related.uri %}
                                        <strong>{{ connected.properties.name|default:connected.properties.title|default:related.type }}</strong>
                                        {% endwith %}
                                    {% else %}
                                        {{ related.type|title }}
                                    {% endif %}
                                </div>
                                {% endfor %}
                            </div>
                        </div>
                        {% endfor %}
                    </div>
                    {% endif %}
                </div>
            </div>

            <!-- Detailed Connected Entities (Expandable) -->
            {% if entity_graph.connected_entities %}
            <details class="mt-4">
                <summary class="cursor-pointer text-sm font-medium text-gray-700 hover:text-blue-600">
                    View Detailed Connected Data ({{ entity_graph.connected_entities|length }} entities)
                </summary>
                <div class="mt-2 space-y-3 max-h-96 overflow-y-auto">
                    {% for uri, connected in entity_graph.connected_entities.items %}
                    <div class="border-l-4 border-gray-200 pl-4 py-2">
                        <div class="flex justify-between items-start">
                            <div>
                                <h6 class="font-medium text-gray-800">
                                    {{ connected.properties.name|default:connected.properties.title|default:connected.type|title }}
                                </h6>
                                <p class="text-xs text-gray-500">{{ connected.type|title }}</p>
                            </div>
                        </div>

                        {% if connected.properties %}
                        <div class="mt-2 grid grid-cols-2 gap-2 text-sm">
                            {% for prop_name, value in connected.properties.items %}
                            {% if prop_name != 'name' and prop_name != 'title' %}
                            <div>
                                <span class="text-gray-600">{{ prop_name|title }}:</span>
                                <span class="text-gray-900">{{ value|truncatechars:50 }}</span>
                            </div>
                            {% endif %}
                            {% endfor %}
                        </div>
                        {% endif %}
                    </div>
                    {% endfor %}
                </div>
            </details>
            {% endif %}
        </div>
        {% endfor %}
    </div>

    {% else %}
    <div class="text-center py-12 text-gray-500">
        {% if search_query %}
            <p class="text-lg">No graphs found for "{{ search_query }}" in {{ search_property }}</p>
            <p class="text-sm mt-2">Try searching with different terms or properties</p>
        {% else %}
            <p class="text-lg">Enter a search term to explore connected data graphs</p>
        {% endif %}
    </div>
    {% endif %}
</div>
{% endblock %}
```

## Example Result Structure

```json
{
    "entity_uri": "http://arkumu.org/data/fuk/entities/project/q123",
    "entity_type": "project",
    "properties": {
        "title": "Machine Learning Research",
        "description": "Advanced ML techniques for data analysis",
        "start_date": "2023-01-01",
        "budget": "50000"
    },
    "outgoing_relations": {
        "has_researcher": [
            {"uri": "http://arkumu.org/.../person/q456", "type": "person"}
        ],
        "has_funding": [
            {"uri": "http://arkumu.org/.../grant/q789", "type": "grant"}
        ]
    },
    "incoming_relations": {
        "works_on": [
            {"uri": "http://arkumu.org/.../person/q456", "type": "person"}
        ]
    },
    "connected_entities": {
        "http://arkumu.org/.../person/q456": {
            "uri": "http://arkumu.org/.../person/q456",
            "type": "person",
            "properties": {
                "name": "Dr. Jane Smith",
                "orcid_id": "0000-0002-1234-5678",
                "affiliation": "University of Example"
            }
        },
        "http://arkumu.org/.../grant/q789": {
            "uri": "http://arkumu.org/.../grant/q789",
            "type": "grant",
            "properties": {
                "title": "NSF AI Research Grant",
                "amount": "50000",
                "source": "National Science Foundation"
            }
        }
    }
}
```

## Benefits

1. **Meaningful Search**: Users search actual content, not entity IDs
2. **Complete Context**: See all related data in one view
3. **Relationship Visibility**: Understand how entities connect
4. **Property-Specific**: Target searches to specific fields (title, name, description)
5. **Rich Results**: Full property data for all connected entities

## URL Structure

```
/catalog/graph-search/?q=Machine+Learning&property=title&class=project
/catalog/graph-search/?q=Jane+Smith&property=name&class=person
/catalog/graph-search/?q=climate&property=description
```

This replaces the broken faceted search with a powerful graph exploration tool that shows the richness of your connected RDF data.