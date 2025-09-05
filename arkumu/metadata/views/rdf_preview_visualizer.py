from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from arkumu.metadata.models import Mapping
from arkumu.users.models import Organization
from arkumu.importer.services.schema_service import SchemaService
from arkumu.common.uri_utils import slugify_uri_part
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def convert_schema_data_to_blueprint(schema_data, schema_service, organization_id):
    """Convert SchemaService visualization data to blueprint format for RDF generation."""
    blueprint = {
        'organization': organization_id,
        'entities': {},
        'relationships': {},
        'junctions': {}
    }
    
    # Convert nodes to entities
    for node in schema_data.get('nodes', []):
        entity_key = node['id']
        properties = {}
        
        # Get multi-value and external ontology info directly from node
        multi_value_columns = node.get('multi_value_columns', [])
        external_ontologies = node.get('external_ontologies', [])
        anchor_columns = node.get('anchor_columns', [])
        
        # Build properties from schema
        for prop_name in node.get('properties', []):
            properties[prop_name] = {
                'property_uri': f"http://arkumu.org/data/{organization_id}/properties/{slugify_uri_part(prop_name)}",
                'source_column': prop_name,
                'data_type': 'string',  # Default type, could be enhanced
                'is_anchor': prop_name in anchor_columns,
                'is_multi_value': prop_name in multi_value_columns,
                'external_ontology': prop_name if prop_name in external_ontologies else None
            }
        
        blueprint['entities'][entity_key] = {
            'entity_type': node.get('entity_type', 'Entity'),
            'properties': properties,
            'anchor_columns': anchor_columns,
            'is_junction': node.get('is_junction', False),
            'multi_value_columns': multi_value_columns,
            'external_ontologies': external_ontologies
        }
    
    # Convert edges to relationships
    for edge in schema_data.get('edges', []):
        rel_key = f"{edge['source']}_to_{edge['target']}"
        blueprint['relationships'][rel_key] = {
            'source_entity': edge['source'],
            'target_entity': edge['target'],
            'relationship_type': edge.get('relationship_type', 'relatedTo'),
            'edge_type': edge.get('type', 'relationship')
        }
    
    # Handle junctions - identify junction tables and their relationships
    for entity_key, entity_info in blueprint['entities'].items():
        if entity_info.get('is_junction'):
            # Find junction relationships (edges going FROM this junction table)
            junction_edges = [e for e in schema_data.get('edges', []) if e['source'] == entity_key]
            if len(junction_edges) >= 2:
                blueprint['junctions'][entity_key] = {
                    'primary_entity': junction_edges[0]['target'],
                    'secondary_entity': junction_edges[1]['target'],
                    'context_attributes': [p for p in entity_info['properties'].keys() 
                                         if not entity_info['properties'][p].get('is_anchor')],
                    'multi_value_columns': entity_info.get('multi_value_columns', []),
                    'external_ontologies': entity_info.get('external_ontologies', [])
                }
    
    return blueprint



def generate_uri_patterns(blueprint):
    """Generate URI generation patterns from blueprint."""
    patterns = {}
    org_name = blueprint.get('organization', 'org')
    
    # Entity URI patterns
    patterns['entities'] = {}
    for entity_key, entity_config in blueprint.get('entities', {}).items():
        slugified_entity = slugify_uri_part(entity_key)
        patterns['entities'][entity_key] = {
            'pattern': f"http://arkumu.org/data/{org_name}/entities/{slugified_entity}/{{anchor_value}}",
            'example': f"http://arkumu.org/data/{org_name}/entities/{slugified_entity}/{slugify_uri_part('john_doe_123')}",
            'anchor_columns': entity_config.get('anchor_columns', [])
        }
    
    # Property URI patterns
    patterns['properties'] = {}
    for entity_key, entity_config in blueprint.get('entities', {}).items():
        for prop_name, prop_config in entity_config.get('properties', {}).items():
            prop_uri = prop_config.get('property_uri', f"http://arkumu.org/data/{org_name}/properties/{slugify_uri_part(prop_name)}")
            patterns['properties'][prop_name] = {
                'uri': prop_uri,
                'source_column': prop_config.get('source_column', prop_name),
                'external_ontology': prop_config.get('external_ontology')
            }
    
    # Dataset URI patterns
    patterns['datasets'] = {}
    for entity_key in blueprint.get('entities', {}).keys():
        patterns['datasets'][entity_key] = f"http://arkumu.org/data/{org_name}/datasets/{slugify_uri_part(entity_key)}"
    
    # Junction URI patterns
    patterns['junctions'] = {}
    for junction_key, junction_config in blueprint.get('junctions', {}).items():
        primary_entity = junction_config.get('primary_entity')
        secondary_entity = junction_config.get('secondary_entity')
        slugified_junction = slugify_uri_part(junction_key)
        patterns['junctions'][junction_key] = {
            'pattern': f"http://arkumu.org/data/{org_name}/junctions/{slugified_junction}/{{primary_id}}_{{secondary_id}}",
            'example': f"http://arkumu.org/data/{org_name}/junctions/{slugified_junction}/{slugify_uri_part('john_123_acme')}",
            'primary_entity': primary_entity,
            'secondary_entity': secondary_entity,
            'context_attributes': junction_config.get('context_attributes', [])
        }
    
    return patterns


def generate_property_mappings(blueprint):
    """Generate property mapping table from blueprint."""
    mappings = []
    
    for entity_key, entity_config in blueprint.get('entities', {}).items():
        for prop_name, prop_config in entity_config.get('properties', {}).items():
            mapping = {
                'entity': entity_key,
                'source_column': prop_config.get('source_column', prop_name),
                'rdf_property': prop_config.get('property_uri', f"arkumu:{prop_name}"),
                'data_type': prop_config.get('data_type', 'string'),
                'is_anchor': prop_config.get('is_anchor', False),
                'is_multi_value': prop_config.get('is_multi_value', False),
                'external_ontology': prop_config.get('external_ontology')
            }
            mappings.append(mapping)
    
    return mappings


@login_required
def rdf_preview_visualizer(request, mapping_id):
    """Display the RDF preview showing sample triples and URI patterns."""
    mapping = get_object_or_404(Mapping, pk=mapping_id)
    
    try:
        # Generate schema data using SchemaService (use consistent URI pattern)
        organization = get_object_or_404(Organization, pk=mapping.organization_id)
        schema_service = SchemaService(
            mapping_id=str(mapping.id),
            institution=organization.code,
            base_uri="http://arkumu.org/data"
        )
        schema_data = schema_service.get_schema_visualization_data()
        
        # Convert schema data to blueprint format for our RDF generation
        blueprint = convert_schema_data_to_blueprint(schema_data, schema_service, mapping.organization_id)
        
        # Generate RDF preview components
        uri_patterns = generate_uri_patterns(blueprint)
        property_mappings = generate_property_mappings(blueprint)
        
        # Generate summary statistics
        stats = {
            'total_entities': len(schema_data.get('nodes', [])),
            'total_properties': sum(len(node.get('properties', [])) for node in schema_data.get('nodes', [])),
            'total_relationships': len(schema_data.get('edges', [])),
            'total_junctions': sum(1 for node in schema_data.get('nodes', []) if node.get('is_junction', False))
        }
        
        context = {
            'mapping': mapping,
            'blueprint': blueprint,
            'uri_patterns': uri_patterns,
            'property_mappings': property_mappings,
            'stats': stats,
            'error': None
        }
        
    except Exception as e:
        import traceback
        logger.error(f"Error generating RDF preview: {e}")
        logger.error(traceback.format_exc())
        
        context = {
            'mapping': mapping,
            'blueprint': None,
            'uri_patterns': {},
            'property_mappings': [],
            'stats': {},
            'error': f"Error generating RDF preview: {str(e)}"
        }
    
    return render(request, 'metadata/rdf_preview_visualizer.html', context)


@login_required
def rdf_preview_property_mappings_sorted(request, mapping_id):
    """Return sorted property mappings table for HTMX."""
    mapping = get_object_or_404(Mapping, pk=mapping_id)
    
    try:
        # Generate schema data using SchemaService (use consistent URI pattern)
        organization = get_object_or_404(Organization, pk=mapping.organization_id)
        schema_service = SchemaService(
            mapping_id=str(mapping.id),
            institution=organization.code,
            base_uri="http://arkumu.org/data"
        )
        schema_data = schema_service.get_schema_visualization_data()
        
        # Convert schema data to blueprint format for our RDF generation
        blueprint = convert_schema_data_to_blueprint(schema_data, schema_service, mapping.organization_id)
        
        # Generate property mappings
        property_mappings = generate_property_mappings(blueprint)
        
        # Get sort parameters
        sort_by = request.GET.get('sort', 'entity')  # Default sort by entity
        sort_order = request.GET.get('order', 'asc')  # Default ascending
        
        # Sort the mappings
        reverse_sort = sort_order == 'desc'
        
        if sort_by == 'entity':
            property_mappings.sort(key=lambda x: x['entity'], reverse=reverse_sort)
        elif sort_by == 'source_column':
            property_mappings.sort(key=lambda x: x['source_column'], reverse=reverse_sort)
        elif sort_by == 'rdf_property':
            property_mappings.sort(key=lambda x: x['rdf_property'], reverse=reverse_sort)
        elif sort_by == 'data_type':
            property_mappings.sort(key=lambda x: x['data_type'], reverse=reverse_sort)
        
        context = {
            'property_mappings': property_mappings,
            'sort_by': sort_by,
            'sort_order': sort_order,
            'mapping_id': mapping_id
        }
        
        return render(request, 'metadata/partials/rdf_property_mappings_table.html', context)
        
    except Exception as e:
        logger.error(f"Error generating sorted property mappings: {e}")
        return render(request, 'metadata/partials/rdf_property_mappings_table.html', {
            'property_mappings': [],
            'sort_by': 'entity',
            'sort_order': 'asc',
            'mapping_id': mapping_id,
            'error': str(e)
        })