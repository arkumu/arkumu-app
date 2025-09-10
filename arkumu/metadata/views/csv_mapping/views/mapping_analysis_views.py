"""
Mapping Analysis Views - Statistics and Analysis for Executed Mappings

This module provides detailed analysis views for mapping execution results,
showing real statistics about processed data including:
- Column type distribution (regular, anchor, FK, multi-value, relationship context, external ontology)
- Processing metrics (resources, triples, relationships created)
- Data quality insights
- Performance analysis
"""
import logging
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods

from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.models import Resource, Triple
from arkumu.users.models import Organization
from arkumu.importer.services.mapping_consumer.mapping_adapter import MappingAdapter
from arkumu.importer.services.mapping_consumer.config_translator import ConfigTranslator

logger = logging.getLogger(__name__)


@login_required
@require_http_methods(['GET'])
def mapping_analysis_dashboard(request, organization_id):
    """
    Main dashboard for mapping analysis showing execution statistics
    and data insights for all mappings in the organization.
    """
    try:
        # Get organization
        organization = get_object_or_404(Organization, code=organization_id)
        
        # Get all mappings for this organization
        mappings = Mapping.objects.filter(
            organization_id=organization_id,
            validation_status='validated'
        ).order_by('-updated_at')
        
        # Collect analysis data for each mapping
        mapping_analysis = []
        for mapping in mappings:
            try:
                analysis = _analyze_mapping_execution(mapping, organization)
                if analysis:
                    mapping_analysis.append(analysis)
            except Exception as e:
                logger.warning(f"Failed to analyze mapping {mapping.name}: {e}")
                continue
        
        context = {
            'organization': organization,
            'mapping_analysis': mapping_analysis,
            'total_mappings': len(mapping_analysis)
        }
        
        return render(request, 'csv_mapping/mapping_analysis_dashboard.html', context)
        
    except Exception as e:
        logger.error(f"Error in mapping analysis dashboard: {e}")
        return render(request, 'csv_mapping/mapping_analysis_dashboard.html', {
            'error': f"Failed to load mapping analysis: {str(e)}",
            'organization': {'code': organization_id}
        })



@login_required
@require_http_methods(['GET'])
def mapping_analysis_api(request, organization_id, mapping_id):
    """
    API endpoint returning mapping analysis data as JSON
    """
    try:
        organization = get_object_or_404(Organization, code=organization_id)
        mapping = get_object_or_404(Mapping, id=mapping_id, organization_id=organization_id)
        
        analysis = _analyze_mapping_execution(mapping, organization, detailed=True)
        
        return JsonResponse({
            'success': True,
            'analysis': analysis
        })
        
    except Exception as e:
        logger.error(f"Error in mapping analysis API: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


def _analyze_mapping_execution(mapping, organization, detailed=False):
    """
    Analyze mapping execution results and return statistics
    
    Args:
        mapping: Mapping instance
        organization: Organization instance  
        detailed: Whether to include detailed analysis
        
    Returns:
        dict: Analysis data including column types, processing metrics, etc.
    """
    try:
        # Load mapping configuration
        mapping_adapter = MappingAdapter()
        config = mapping_adapter.load_mapping_config(mapping.id)
        
        # Use centralized MappingUtils for comprehensive analysis
        from arkumu.importer.utils.mapping_utils import MappingUtils
        column_analysis = MappingUtils.analyze_mapping_structure(config)
        dataset_breakdown = column_analysis.pop('dataset_breakdown', {})
        
        # Get database metrics for this organization
        total_resources = Resource.objects.filter(organization=organization).count()
        total_triples = Triple.objects.filter(source=organization).count()
        
        # Count entity resources vs other types
        entity_resources = Resource.objects.filter(
            organization=organization,
            resource_type='IRI',
            uri__contains='/entities/'
        ).count()
        
        # Count different property types
        property_triples = Triple.objects.filter(
            source=organization,
            object__resource_type='LITERAL'
        ).count()
        
        relationship_triples = Triple.objects.filter(
            source=organization,
            object__resource_type='IRI'
        ).count()
        
        analysis = {
            'mapping_name': mapping.name,
            'mapping_id': str(mapping.id),
            'total_datasets': len(execution_config.datasets),
            'total_fk_relationships': len(execution_config.fk_relationships),
            'total_relationship_contexts': len(execution_config.relationship_contexts),
            'column_analysis': column_analysis,
            'dataset_breakdown': dataset_breakdown,
            'database_metrics': {
                'total_resources': total_resources,
                'total_triples': total_triples,
                'entity_resources': entity_resources,
                'property_triples': property_triples,
                'relationship_triples': relationship_triples
            }
        }
        
        if detailed:
            # Add detailed analysis for specific view
            analysis['detailed_metrics'] = _get_detailed_metrics(organization, execution_config)
            analysis['column_type_percentages'] = _calculate_column_percentages(column_analysis)
        
        return analysis
        
    except Exception as e:
        logger.error(f"Failed to analyze mapping execution: {e}")
        return None


def _get_detailed_metrics(organization, execution_config):
    """Get detailed processing metrics"""
    
    # Analyze relationship context usage
    context_columns = []
    for dataset_config in execution_config.datasets:
        for column in dataset_config.columns:
            if column.column_type.value == 'relationship_context':
                context_columns.append({
                    'dataset': dataset_config.dataset_name,
                    'column': column.column_name,
                    'arkumu_type': column.arkumu_type
                })
    
    # Analyze multi-value columns
    multivalue_columns = []
    for dataset_config in execution_config.datasets:
        for column in dataset_config.columns:
            if column.is_multi_value:
                multivalue_columns.append({
                    'dataset': dataset_config.dataset_name,
                    'column': column.column_name,
                    'arkumu_type': column.arkumu_type,
                    'separator': column.multi_value_separator
                })
    
    # Analyze external ontology connections
    ontology_columns = []
    for dataset_config in execution_config.datasets:
        for column in dataset_config.columns:
            if column.is_external_ontology:
                ontology_columns.append({
                    'dataset': dataset_config.dataset_name,
                    'column': column.column_name,
                    'arkumu_type': column.arkumu_type,
                    'ontology_type': column.external_ontology_config.get('ontology_type', 'unknown') if column.external_ontology_config else 'unknown'
                })
    
    return {
        'relationship_context_details': context_columns,
        'multivalue_details': multivalue_columns,
        'external_ontology_details': ontology_columns,
        'junction_table_count': len([d for d in execution_config.datasets if 'kreuztabelle' in d.dataset_name.lower() or 'junction' in d.dataset_name.lower()])
    }


def _calculate_column_percentages(column_analysis):
    """Calculate percentage distribution of column types"""
    total = column_analysis['total_columns']
    if total == 0:
        return {}
    
    return {
        'regular': round((column_analysis['regular_columns'] / total) * 100, 1),
        'anchor': round((column_analysis['anchor_columns'] / total) * 100, 1),
        'foreign_key': round((column_analysis['foreign_key_columns'] / total) * 100, 1),
        'multi_value': round((column_analysis['multi_value_columns'] / total) * 100, 1),
        'relationship_context': round((column_analysis['relationship_context_columns'] / total) * 100, 1),
        'external_ontology': round((column_analysis['external_ontology_columns'] / total) * 100, 1)
    }