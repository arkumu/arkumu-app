"""
Import Analysis Views - Post-Execution Analysis of Import Results

This module provides analysis views for completed imports, showing:
- Actual processing results and statistics
- Resource and triple creation metrics
- Relationship context processing analysis
- Column type distribution from real executions
- Import session performance analysis
"""
import logging
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods

from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.models import Resource, Triple
from arkumu.metadata.models.resource import ResourceType
from arkumu.users.models import Organization
from arkumu.importer.models.ingest_sessions import IngestSession
from arkumu.importer.utils.mapping_utils import MappingUtils
from arkumu.importer.models.import_task import ImportTask
from arkumu.importer.services.mapping_consumer.mapping_adapter import MappingAdapter
from arkumu.importer.services.mapping_consumer.config_translator import ConfigTranslator

logger = logging.getLogger(__name__)


@login_required
@require_http_methods(['GET'])
def import_results_dashboard(request):
    """
    Dashboard showing import execution results and statistics
    for all completed imports in the current organization.
    
    This view shows POST-EXECUTION analysis - what was actually imported,
    not just the mapping configuration.
    """
    try:
        # Get current organization from session (following importer pattern)
        from arkumu.importer.views.ingest_views import IngestDataView
        view_instance = IngestDataView()
        current_org = view_instance.get_current_organization(request)
        
        if not current_org:
            return render(request, 'importer/import_results_dashboard.html', {
                'error': 'No organization selected. Please select an organization first.',
                'organizations_available': True
            })
        
        # Get the actual Organization model instance
        try:
            org_instance = Organization.objects.get(code=current_org['code'])
        except Organization.DoesNotExist:
            return render(request, 'importer/import_results_dashboard.html', {
                'error': f"Organization {current_org['code']} not found.",
                'current_org': current_org
            })
        
        # Get all completed ingest sessions for this organization
        ingest_sessions = IngestSession.objects.filter(
            organization=org_instance,
            status='completed'
        ).order_by('-completed_at')
        
        # Analyze import results for each ingest session
        import_analysis = []
        for session in ingest_sessions:
            try:
                analysis = _analyze_ingest_session_results(session, org_instance)
                # Enrich with fast FK totals for dashboard using mapping definitions
                try:
                    if session.mapping:
                        adapter = MappingAdapter()
                        translator = ConfigTranslator()
                        raw_config = adapter.load_mapping_config(session.mapping.id)
                        exec_cfg = translator.translate_mapping_config(raw_config)
                        # Build property URIs for all FK relationship types
                        from arkumu.common.uri_utils import mint_uri, slugify_uri_part
                        def prop_uri(arkumu_type: str) -> str:
                            return mint_uri('http://arkumu.org', org_instance.code, "properties", slugify_uri_part(arkumu_type))
                        fk_predicates = set()
                        for fk in exec_cfg.fk_relationships:
                            fk_predicates.add(prop_uri(fk.relationship_type))
                        # Count triples matching any FK predicate
                        fk_total = 0
                        if fk_predicates:
                            from arkumu.importer.models.triple import Triple as TripleModel
                            fk_total = TripleModel.objects.filter(
                                source=org_instance,
                                predicate__uri__in=list(fk_predicates),
                                subject__uri__contains='/entities/',
                                object__resource_type__in=[ResourceType.ENTITY, ResourceType.IRI],
                                object__uri__contains='/entities/'
                            ).count()
                        analysis.setdefault('import_results', {})['fk_relationships_total'] = fk_total
                except Exception as e:
                    logger.debug(f"FK dashboard enrichment failed for session {session.id}: {e}")
                if analysis:
                    import_analysis.append(analysis)
            except Exception as e:
                logger.warning(f"Failed to analyze ingest session {session.id}: {e}")
                continue
        
        # Calculate organization-wide statistics
        org_stats = _calculate_organization_stats(org_instance, import_analysis)
        
        context = {
            'current_org': current_org,
            'import_analysis': import_analysis,
            'organization_stats': org_stats,
            'total_mappings_with_data': len(import_analysis)
        }
        
        return render(request, 'importer/import_results_dashboard.html', context)
        
    except Exception as e:
        logger.error(f"Error in import results dashboard: {e}")
        return render(request, 'importer/import_results_dashboard.html', {
            'error': f"Failed to load import analysis: {str(e)}",
            'current_org': {'code': 'unknown'}
        })


@login_required  
@require_http_methods(['GET'])
def import_results_detail(request, session_id):
    """
    Detailed analysis view for a specific mapping's import results.
    
    Shows comprehensive statistics about what was actually processed:
    - Resources and triples created
    - Column type processing results
    - Relationship context analysis
    - Sample generated data
    """
    try:
        # Get current organization
        from arkumu.importer.views.ingest_views import IngestDataView
        view_instance = IngestDataView()
        current_org = view_instance.get_current_organization(request)
        
        if not current_org:
            return render(request, 'importer/import_results_detail.html', {
                'error': 'No organization selected'
            })
        
        # Get the actual Organization model instance
        try:
            org_instance = Organization.objects.get(code=current_org['code'])
        except Organization.DoesNotExist:
            return render(request, 'importer/import_results_detail.html', {
                'error': f"Organization {current_org['code']} not found.",
                'current_org': current_org
            })
        
        # Get ingest session
        ingest_session = get_object_or_404(IngestSession, id=session_id, organization=org_instance)
        
        # Get detailed analysis
        analysis = _analyze_ingest_session_results(ingest_session, org_instance, detailed=True)
        if not analysis:
            return render(request, 'importer/import_results_detail.html', {
                'error': 'No import data available for this session.',
                'session': ingest_session,
                'current_org': current_org
            })
        
        # Get sample data from actual import results
        sample_resources = Resource.objects.filter(
            organization=org_instance,
            uri__contains=f'/data/{current_org["code"]}'
        ).select_related().prefetch_related('subject_triples', 'object_triples')[:15]
        
        # Get REAL import analysis - not samples
        real_analysis = _get_real_import_analysis(org_instance, ingest_session)
        
        # Get REAL data organized by column types for template
        real_data = _get_real_column_data_by_types(org_instance, ingest_session)
        
        # Get sample triples including relationship context triples
        sample_triples = Triple.objects.filter(
            source=org_instance
        ).select_related('subject', 'predicate', 'object')[:25]
        
        context = {
            'current_org': current_org,
            'session': ingest_session,
            'analysis': analysis,
            'sample_resources': sample_resources,
            'sample_triples': sample_triples,
            **real_data  # Unpack real data by column types
        }
        
        return render(request, 'importer/import_results_detail.html', context)
        
    except IngestSession.DoesNotExist:
        return render(request, 'importer/import_results_detail.html', {
            'error': 'This import session was not found or has been removed.'
        }, status=404)
    except Exception as e:
        logger.error(f"Error in import results detail: {e}")
        return render(request, 'importer/import_results_detail.html', {
            'error': f"Failed to load detailed import analysis: {str(e)}",
            'current_org': {'code': 'unknown'},
            'mapping': {'name': 'Unknown Mapping'}
        }, status=500)


@login_required
@require_http_methods(['GET'])
def import_results_api(request, mapping_id):
    """
    API endpoint returning import results analysis data as JSON
    """
    try:
        from arkumu.importer.views.ingest_views import IngestDataView
        view_instance = IngestDataView()
        current_org = view_instance.get_current_organization(request)
        
        if not current_org:
            return JsonResponse({
                'success': False,
                'error': 'No organization selected'
            }, status=400)
        
        # Get the actual Organization model instance
        try:
            org_instance = Organization.objects.get(code=current_org['code'])
        except Organization.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': f"Organization {current_org['code']} not found."
            }, status=404)
        
        mapping = get_object_or_404(Mapping, id=mapping_id, organization_id=current_org['code'])
        analysis = _analyze_import_results(mapping, org_instance, detailed=True)
        
        return JsonResponse({
            'success': True,
            'analysis': analysis
        })
        
    except Exception as e:
        logger.error(f"Error in import results API: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


def _analyze_ingest_session_results(ingest_session, organization, detailed=False):
    """
    Analyze actual import results from an IngestSession.
    
    This analyzes REAL DATA that was imported via the session.
    
    Args:
        ingest_session: IngestSession instance
        organization: Organization instance  
        detailed: Whether to include detailed analysis
        
    Returns:
        dict: Analysis data including actual processing results
    """
    try:
        # Get mapping configuration if available - USE RAW WORKSPACE_COLUMNS FORMAT
        mapping_analysis = None
        execution_config = None
        if ingest_session.mapping:
            mapping_analysis = _analyze_raw_mapping_columns(ingest_session.mapping)
            # Also load full execution config for richer, per-dataset alignment
            try:
                adapter = MappingAdapter()
                translator = ConfigTranslator()
                raw_config = adapter.load_mapping_config(ingest_session.mapping.id)
                execution_config = translator.translate_mapping_config(raw_config)
            except Exception as e:
                logger.warning(f"Execution config unavailable for session {ingest_session.id}: {e}")
        
        # Get import tasks for this session
        import_tasks = ImportTask.objects.filter(ingest_session=ingest_session)
        
        # Get ACTUAL results from database for mapping verification
        # For verification, we analyze ALL data for this organization/mapping, not just session-specific data
        session_resources = Resource.objects.filter(organization=organization)
        session_triples = Triple.objects.filter(source=organization)
        
        total_resources = session_resources.count()
        total_triples = session_triples.count()
        
        # Count different types of resources
        entity_resources = session_resources.filter(
            resource_type='IRI',
            uri__contains='/entities/'
        ).count()
        
        # Count junction table entities (entities from Kreuztabelle datasets)
        junction_entities = session_resources.filter(
            resource_type='IRI',
            uri__contains='/entities/'
        ).filter(
            uri__iregex=r'.*(kreuztabelle|junction|_junction_|_link_).*'
        ).count()
        
        # Count relationship context properties
        context_property_triples = session_triples.filter(
            subject__uri__contains='/entities/',
            object__resource_type='LITERAL'
        ).exclude(
            predicate__uri__contains='ID'
        ).count()
        
        # Count different types of triples
        property_triples = session_triples.filter(
            object__resource_type='LITERAL'
        ).count()
        
        # Count FK relationships (entity-to-entity IRI relationships, excluding dataset membership)
        relationship_triples = session_triples.filter(
            subject__uri__contains='/entities/',
            object__resource_type__in=[ResourceType.ENTITY, ResourceType.IRI],
            object__uri__contains='/entities/'
        ).exclude(
            predicate__uri__contains='isPartOf'
        ).count()
        
        analysis = {
            'session_id': str(ingest_session.id),
            'session_name': f"Import Session {ingest_session.created_at.strftime('%Y-%m-%d %H:%M')}",
            'mapping_name': ingest_session.mapping.name if ingest_session.mapping else "No Mapping",
            'mapping_id': str(ingest_session.mapping.id) if ingest_session.mapping else None,
            'created_at': ingest_session.created_at,
            'completed_at': ingest_session.completed_at,
            'status': ingest_session.status,
            
            # Dataset information
            'datasets_processed': import_tasks.count(),
            'dataset_names': list(import_tasks.values_list('dataset_name', flat=True)),
            
            # Column analysis from mapping if available
            'column_analysis': mapping_analysis or {
                'regular_columns': 0,
                'anchor_columns': 0,
                'foreign_key_columns': 0,
                'multi_value_columns': 0,
                'relationship_context_columns': 0,
                'external_ontology_columns': 0,
                'total_columns': 0
            },
            
            # ACTUAL import results - matching mapping_aware_processor statistics
            'import_results': {
                'total_resources': total_resources,
                'total_triples': total_triples,
                'entity_resources': entity_resources,
                'junction_entities': junction_entities,
                'context_property_triples': context_property_triples,
                'property_triples': property_triples,
                'relationship_triples': relationship_triples,
                # Additional metrics from mapping_aware_processor
                'rows_processed': total_resources,  # Approximate - each resource typically represents one processed row
                'resources_created': total_resources,
                'triples_created': total_triples,
                'relationships_created': relationship_triples,
                'multi_value_items_created': _count_multi_value_items(organization),
                'multi_value_cells_split': _count_multi_value_cells(organization),
                'fk_relationships_total': relationship_triples,
                'fk_relationships_resolved': relationship_triples,  # Assume all were resolved for completed sessions
                'per_dataset_stats': _analyze_per_dataset_statistics(organization, ingest_session)
            },
            
            # Processing efficiency
            'processing_efficiency': {
                'resources_per_dataset': round(total_resources / max(import_tasks.count(), 1), 2),
                'triples_per_resource': round(total_triples / max(total_resources, 1), 2),
                'properties_per_entity': round(property_triples / max(entity_resources, 1), 2)
            }
        }
        
        if detailed:
            # Add detailed analysis for specific view
            analysis['detailed_analysis'] = _get_detailed_ingest_analysis(organization, ingest_session)
            if mapping_analysis:
                analysis['column_type_percentages'] = _calculate_column_percentages(mapping_analysis)
            if execution_config:
                # Provide dataset breakdown and top datasets by actual entities
                analysis['dataset_breakdown'] = _analyze_dataset_breakdown(execution_config)
                top_datasets = []
                for ds in execution_config.datasets:
                    count = session_resources.filter(uri__contains=f"/entities/{ds.dataset_name}/").count()
                    top_datasets.append({'dataset': ds.dataset_name, 'entities': count})
                analysis['top_datasets'] = sorted(top_datasets, key=lambda x: x['entities'], reverse=True)[:5]
                
                # Add per-dataset statistics similar to mapping_aware_processor
                analysis['per_dataset_stats'] = _analyze_per_dataset_statistics(organization, execution_config)
        
        return analysis
        
    except Exception as e:
        logger.error(f"Failed to analyze ingest session results: {e}")
        return None


def _analyze_import_results(mapping, organization, detailed=False):
    """
    Analyze actual import results from the database for a given mapping.
    
    This analyzes REAL DATA that was imported, not just configuration.
    
    Args:
        mapping: Mapping instance
        organization: Organization instance  
        detailed: Whether to include detailed analysis
        
    Returns:
        dict: Analysis data including actual processing results
    """
    try:
        # Load mapping configuration to understand what was supposed to be processed
        mapping_adapter = MappingAdapter()
        config_translator = ConfigTranslator()
        
        config = mapping_adapter.load_mapping_config(mapping.id)
        execution_config = config_translator.translate_mapping_config(config)
        
        # Get ACTUAL results from database
        total_resources = Resource.objects.filter(organization=organization).count()
        total_triples = Triple.objects.filter(source=organization).count()
        
        # Count different types of resources
        entity_resources = Resource.objects.filter(
            organization=organization,
            resource_type='IRI',
            uri__contains='/entities/'
        ).count()
        
        dataset_resources = Resource.objects.filter(
            organization=organization,
            resource_type='IRI',
            uri__contains='/datasets/'
        ).count()
        
        # Count different types of triples
        property_triples = Triple.objects.filter(
            source=organization,
            object__resource_type='LITERAL'
        ).count()
        
        # Count FK relationships (entity-to-entity IRI relationships, excluding dataset membership)
        relationship_triples = Triple.objects.filter(
            source=organization,
            subject__uri__contains='/entities/',
            object__resource_type='IRI',
            object__uri__contains='/entities/'
        ).exclude(
            predicate__uri__contains='isPartOf'
        ).count()
        
        # Analyze relationship context processing results
        context_property_triples = Triple.objects.filter(
            source=organization,
            subject__uri__contains='/entities/',
            object__resource_type='LITERAL'
        ).exclude(
            predicate__uri__contains='ID'
        ).count()
        
        # Count junction table entities (entities from datasets with 'kreuztabelle' or similar)
        junction_entities = Resource.objects.filter(
            organization=organization,
            resource_type='IRI',
            uri__contains='/entities/'
        ).filter(
            uri__iregex=r'.*(kreuztabelle|junction|_junction_|_link_).*'
        ).count()
        
        # Analyze column configuration vs actual results
        column_analysis = _analyze_column_configuration(execution_config)
        
        analysis = {
            'mapping_name': mapping.name,
            'mapping_id': str(mapping.id),
            'last_updated': mapping.updated_at,
            
            # Configuration analysis
            'total_datasets': len(execution_config.datasets),
            'total_fk_relationships': len(execution_config.fk_relationships),
            'total_relationship_contexts': len(execution_config.relationship_contexts),
            'column_analysis': column_analysis,
            
            # ACTUAL import results
            'import_results': {
                'total_resources': total_resources,
                'total_triples': total_triples,
                'entity_resources': entity_resources,
                'dataset_resources': dataset_resources,
                'property_triples': property_triples,
                'relationship_triples': relationship_triples,
                'context_property_triples': context_property_triples,
                'junction_entities': junction_entities
            },
            
            # Processing efficiency
            'processing_efficiency': {
                'resources_per_dataset': round(total_resources / len(execution_config.datasets), 2) if execution_config.datasets else 0,
                'triples_per_resource': round(total_triples / total_resources, 2) if total_resources else 0,
                'properties_per_entity': round(property_triples / entity_resources, 2) if entity_resources else 0
            }
        }
        
        if detailed:
            # Add detailed analysis for specific view
            analysis['detailed_analysis'] = _get_detailed_import_analysis(organization, execution_config)
            analysis['column_type_percentages'] = _calculate_column_percentages(column_analysis)
            analysis['dataset_breakdown'] = _analyze_dataset_breakdown(execution_config)
        
        return analysis
        
    except Exception as e:
        logger.error(f"Failed to analyze import results: {e}")
        return None


def _analyze_raw_mapping_columns(mapping):
    """
    Analyze column configuration using centralized MappingUtils.
    Uses comprehensive mapping analysis that properly handles all column type combinations.
    """
    from arkumu.importer.utils.mapping_utils import MappingUtils
    return MappingUtils.analyze_mapping_structure(mapping.mapping_config)


def _analyze_column_configuration(execution_config):
    """Analyze column types from the execution configuration"""
    column_analysis = {
        'regular_columns': 0,
        'anchor_columns': 0,
        'foreign_key_columns': 0,
        'multi_value_columns': 0,
        'relationship_context_columns': 0,
        'external_ontology_columns': 0,
        'total_columns': 0
    }
    
    for dataset_config in execution_config.datasets:
        for column in dataset_config.columns:
            column_analysis['total_columns'] += 1
            
            if column.is_anchor:
                column_analysis['anchor_columns'] += 1
            elif column.column_type.value == 'foreign_key':
                column_analysis['foreign_key_columns'] += 1
            elif column.is_multi_value:
                column_analysis['multi_value_columns'] += 1
            elif column.column_type.value == 'relationship_context':
                column_analysis['relationship_context_columns'] += 1
            elif column.is_external_ontology:
                column_analysis['external_ontology_columns'] += 1
            else:
                column_analysis['regular_columns'] += 1
    
    return column_analysis


def _calculate_organization_stats(organization, import_analysis):
    """Calculate organization-wide statistics"""
    if not import_analysis:
        return {
            'total_resources': 0,
            'total_triples': 0,
            'total_entities': 0,
            'total_junction_entities': 0,
            'avg_processing_efficiency': 0
        }
    
    total_resources = sum(a['import_results']['total_resources'] for a in import_analysis)
    total_triples = sum(a['import_results']['total_triples'] for a in import_analysis)
    total_entities = sum(a['import_results']['entity_resources'] for a in import_analysis)
    total_junction = sum(a['import_results']['junction_entities'] for a in import_analysis)
    
    return {
        'total_resources': total_resources,
        'total_triples': total_triples,
        'total_entities': total_entities,
        'total_junction_entities': total_junction,
        'avg_resources_per_mapping': round(total_resources / len(import_analysis), 2) if import_analysis else 0,
        'avg_triples_per_mapping': round(total_triples / len(import_analysis), 2) if import_analysis else 0
    }


def _get_detailed_ingest_analysis(organization, ingest_session):
    """Get detailed analysis for ingest session results including all column types"""
    
    # Get mapping configuration if available
    mapping_details = None
    if ingest_session.mapping:
        try:
            mapping_adapter = MappingAdapter()
            config_translator = ConfigTranslator()
            
            config = mapping_adapter.load_mapping_config(ingest_session.mapping.id)
            execution_config = config_translator.translate_mapping_config(config)
            mapping_details = _get_detailed_mapping_analysis(execution_config)
        except Exception as e:
            logger.warning(f"Could not load mapping details: {e}")
    
    # Find actual junction table patterns in the data
    junction_patterns = []
    junction_resources = Resource.objects.filter(
        organization=organization,
        resource_type='IRI',
        uri__contains='/entities/'
    ).filter(
        uri__iregex=r'.*(kreuztabelle|junction|_junction_|_link_).*'
    )[:10]  # Sample of junction resources
    
    for resource in junction_resources:
        # Get properties of this junction entity
        properties = Triple.objects.filter(
            source=organization,
            subject=resource,
            object__resource_type='LITERAL'
        ).exclude(
            predicate__uri__contains='ID'
        )[:5]
        
        if properties:
            junction_patterns.append({
                'entity_uri': resource.uri,
                'properties': [
                    {
                        'predicate': prop.predicate.uri,
                        'value': prop.object.value[:100]  # Truncate long values
                    }
                    for prop in properties
                ]
            })
    
    # Analyze actual multi-value properties
    multivalue_patterns = []
    # Look for properties that appear multiple times for the same subject (indicating multi-value)
    from django.db.models import Count
    multivalue_subjects = Triple.objects.filter(
        source=organization,
        object__resource_type='LITERAL'
    ).values('subject', 'predicate').annotate(
        count=Count('id')
    ).filter(count__gt=1)[:10]
    
    for mv in multivalue_subjects:
        subject_uri = Resource.objects.get(id=mv['subject']).uri
        predicate_uri = Resource.objects.get(id=mv['predicate']).uri
        values = Triple.objects.filter(
            source=organization,
            subject_id=mv['subject'],
            predicate_id=mv['predicate']
        ).values_list('object__value', flat=True)[:5]
        
        multivalue_patterns.append({
            'subject_uri': subject_uri,
            'predicate_uri': predicate_uri,
            'values': list(values),
            'total_count': mv['count']
        })
    
    # Analyze FK relationships (entity-to-entity IRI relationships)
    fk_patterns = []
    fk_triples = Triple.objects.filter(
        source=organization,
        subject__uri__contains='/entities/',
        object__resource_type='IRI',
        object__uri__contains='/entities/'
    ).exclude(
        predicate__uri__contains='isPartOf'
    )[:10]
    
    for fk_triple in fk_triples:
        fk_patterns.append({
            'subject_uri': fk_triple.subject.uri,
            'predicate_uri': fk_triple.predicate.uri,
            'target_uri': fk_triple.object.uri
        })
    
    # Analyze external ontology usage (URIs that don't contain the organization's domain)
    external_ontology_patterns = []
    external_triples = Triple.objects.filter(
        source=organization,
        object__resource_type='IRI'
    ).exclude(
        object__uri__contains=f'/data/{organization.code}'
    ).exclude(
        object__uri__contains='/entities/'
    )[:10]
    
    for ext_triple in external_triples:
        external_ontology_patterns.append({
            'subject_uri': ext_triple.subject.uri,
            'predicate_uri': ext_triple.predicate.uri,
            'external_uri': ext_triple.object.uri
        })
    
    # Get dataset information from import tasks
    import_tasks = ImportTask.objects.filter(ingest_session=ingest_session)
    datasets_info = []
    for task in import_tasks[:15]:  # More datasets for better overview
        datasets_info.append({
            'dataset_name': task.dataset_name,
            'file_path': task.file_path.split('/')[-1],  # Just filename
            'status': task.status,
            'started_at': task.started_at,
            'completed_at': task.completed_at,
            'duration': _calculate_task_duration(task)
        })
    
    return {
        'mapping_details': mapping_details,
        'junction_patterns': junction_patterns,
        'multivalue_patterns': multivalue_patterns,
        'fk_patterns': fk_patterns,
        'external_ontology_patterns': external_ontology_patterns,
        'relationship_context_usage': len(junction_patterns) > 0,
        'multivalue_usage': len(multivalue_patterns) > 0,
        'fk_usage': len(fk_patterns) > 0,
        'external_ontology_usage': len(external_ontology_patterns) > 0,
        'datasets_info': datasets_info,
        'session_duration': _calculate_session_duration(ingest_session)
    }


def _get_detailed_mapping_analysis(execution_config):
    """Get detailed mapping configuration analysis"""
    
    # Analyze relationship context columns
    context_columns = []
    multivalue_columns = []
    fk_columns = []
    external_ontology_columns = []
    
    for dataset_config in execution_config.datasets:
        for column in dataset_config.columns:
            if column.column_type.value == 'relationship_context':
                context_columns.append({
                    'dataset': dataset_config.dataset_name,
                    'column': column.column_name,
                    'arkumu_type': column.arkumu_type
                })
            elif column.is_multi_value:
                multivalue_columns.append({
                    'dataset': dataset_config.dataset_name,
                    'column': column.column_name,
                    'arkumu_type': column.arkumu_type,
                    'separator': column.multi_value_separator
                })
            elif column.column_type.value == 'foreign_key':
                fk_columns.append({
                    'dataset': dataset_config.dataset_name,
                    'column': column.column_name,
                    'arkumu_type': column.arkumu_type,
                    'target': column.fk_config.get('target_dataset', 'Unknown') if column.fk_config else 'Unknown'
                })
            elif column.is_external_ontology:
                external_ontology_columns.append({
                    'dataset': dataset_config.dataset_name,
                    'column': column.column_name,
                    'arkumu_type': column.arkumu_type,
                    'ontology_type': column.external_ontology_config.get('ontology_type', 'unknown') if column.external_ontology_config else 'unknown'
                })
    
    return {
        'relationship_context_details': context_columns,
        'multivalue_details': multivalue_columns,
        'fk_details': fk_columns,
        'external_ontology_details': external_ontology_columns
    }


def _calculate_task_duration(task):
    """Calculate how long an import task took"""
    if task.started_at and task.completed_at:
        duration = task.completed_at - task.started_at
        return str(duration).split('.')[0]  # Remove microseconds
    return None


def _calculate_session_duration(ingest_session):
    """Calculate how long the ingest session took"""
    if ingest_session.started_at and ingest_session.completed_at:
        duration = ingest_session.completed_at - ingest_session.started_at
        return {
            'total_seconds': duration.total_seconds(),
            'formatted': str(duration).split('.')[0]  # Remove microseconds
        }
    return None


def _get_detailed_import_analysis(organization, execution_config):
    """Get detailed analysis for import results"""
    
    # Find actual junction table patterns in the data
    junction_patterns = []
    junction_resources = Resource.objects.filter(
        organization=organization,
        resource_type='IRI',
        uri__contains='/entities/'
    ).filter(
        uri__iregex=r'.*(kreuztabelle|junction|_junction_|_link_).*'
    )[:10]  # Sample of junction resources
    
    for resource in junction_resources:
        # Get properties of this junction entity
        properties = Triple.objects.filter(
            source=organization,
            subject=resource,
            object__resource_type='LITERAL'
        ).exclude(
            predicate__uri__contains='ID'
        )[:5]
        
        if properties:
            junction_patterns.append({
                'entity_uri': resource.uri,
                'properties': [
                    {
                        'predicate': prop.predicate.uri,
                        'value': prop.object.value[:100]  # Truncate long values
                    }
                    for prop in properties
                ]
            })
    
    return {
        'junction_patterns': junction_patterns,
        'relationship_context_usage': len(junction_patterns) > 0
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


def _analyze_dataset_breakdown(execution_config):
    """Analyze column breakdown by dataset"""
    dataset_breakdown = {}
    
    for dataset_config in execution_config.datasets:
        stats = {
            'regular': 0,
            'anchor': 0,
            'foreign_key': 0,
            'multi_value': 0,
            'relationship_context': 0,
            'external_ontology': 0,
            'total': len(dataset_config.columns)
        }
        
        for column in dataset_config.columns:
            if column.is_anchor:
                stats['anchor'] += 1
            elif column.column_type.value == 'foreign_key':
                stats['foreign_key'] += 1
            elif column.is_multi_value:
                stats['multi_value'] += 1
            elif column.column_type.value == 'relationship_context':
                stats['relationship_context'] += 1
            elif column.is_external_ontology:
                stats['external_ontology'] += 1
            else:
                stats['regular'] += 1
        
        dataset_breakdown[dataset_config.dataset_name] = stats
    
    return dataset_breakdown


def _classify_sample_annotations_old(organization, ingest_session):
    """
    Show the ACTUAL annotations from the REAL mapping configuration.
    No more guessing - use the actual FK relationships and column types that were defined.
    """
    from arkumu.importer.utils.mapping_utils import MappingUtils
    
    result = {
        'sample_regular_annotations': [],
        'sample_anchor_annotations': [],
        'sample_fk_annotations': [],
        'sample_multivalue_annotations': [],
        'sample_multivalue_fk_annotations': [],
        'sample_context_annotations': [],
        'sample_external_annotations': []
    }
    
    if not ingest_session.mapping:
        return result
    
    try:
        # Load the ACTUAL mapping configuration
        from arkumu.importer.services.mapping_consumer.mapping_adapter import MappingAdapter
        from arkumu.importer.services.mapping_consumer.config_translator import ConfigTranslator
        
        mapping_adapter = MappingAdapter()
        config_translator = ConfigTranslator()
        
        # Get the raw mapping config
        config = mapping_adapter.load_mapping_config(ingest_session.mapping.id)
        
        # Get the execution config with FK relationships
        execution_config = config_translator.translate_mapping_config(config)
        
        logger.info(f"=== REAL MAPPING DATA ===")
        logger.info(f"Datasets: {[d.dataset_name for d in execution_config.datasets]}")
        logger.info(f"FK Relationships: {len(execution_config.fk_relationships)}")
        logger.info(f"Relationship Contexts: {len(execution_config.relationship_contexts)}")
        
        # Show ACTUAL FK relationships that were configured
        for fk_rel in execution_config.fk_relationships[:8]:
            # Debug the FK relationship object to see what attributes it has
            logger.info(f"FK object attributes: {dir(fk_rel)}")
            logger.info(f"FK: {fk_rel.source_dataset} -> {fk_rel.target_dataset}")
            
            # Find actual triples that were created for this FK relationship
            # Look for triples that match the FK relationship pattern
            fk_triples = Triple.objects.filter(
                source=organization,
                object__resource_type='IRI',
                subject__uri__contains=f'/entities/{fk_rel.source_dataset.lower()}',
                object__uri__contains=f'/entities/{fk_rel.target_dataset.lower()}'
            ).select_related('subject', 'predicate', 'object')[:3]
            
            logger.info(f"Found {len(fk_triples)} FK triples for {fk_rel.source_dataset} -> {fk_rel.target_dataset}")
            
            for triple in fk_triples:
                result['sample_fk_annotations'].append({
                    'from_entity': triple.subject.uri,
                    'relationship': triple.predicate.uri,
                    'to_entity': triple.object.uri,
                    'from_dataset': fk_rel.source_dataset,
                    'to_dataset': fk_rel.target_dataset,
                    'column_name': getattr(fk_rel, 'relationship_name', getattr(fk_rel, 'relationship_type', 'FK')),
                    'fk_target': fk_rel.target_dataset
                })
        
        # Show ACTUAL column types from the mapping
        for dataset_config in execution_config.datasets:
            logger.info(f"Dataset: {dataset_config.dataset_name} ({len(dataset_config.columns)} columns)")
            
            for column in dataset_config.columns[:5]:  # Sample first 5 columns per dataset
                # Generate the predicate URI that should exist for this column
                predicate_uri = f"http://arkumu.org/data/{organization.code}/properties/{column.arkumu_type}"
                
                # Find actual triples for this column
                sample_triples = Triple.objects.filter(
                    source=organization,
                    predicate__uri=predicate_uri
                ).select_related('subject', 'predicate', 'object')[:2]
                
                if sample_triples:
                    # Classify based on the ACTUAL column configuration
                    if column.is_anchor:
                        for triple in sample_triples:
                            result['sample_anchor_annotations'].append({
                                'subject_uri': triple.subject.uri,
                                'predicate_uri': triple.predicate.uri,
                                'value': str(triple.object.value)[:100],
                                'dataset': dataset_config.dataset_name,
                                'column_name': column.column_name,
                                'is_primary_key': True
                            })
                            
                    elif column.column_type.value == 'relationship_context':
                        for triple in sample_triples:
                            result['sample_context_annotations'].append({
                                'junction_entity': triple.subject.uri,
                                'context_property': triple.predicate.uri,
                                'context_value': str(triple.object.value)[:100],
                                'dataset': dataset_config.dataset_name,
                                'column_name': column.column_name
                            })
                            
                    elif column.is_multi_value:
                        # Get all values for this multi-value column
                        if sample_triples:
                            first_triple = sample_triples[0]
                            all_values = Triple.objects.filter(
                                source=organization,
                                predicate=first_triple.predicate,
                                subject=first_triple.subject
                            ).values_list('object__value', flat=True)[:5]
                            
                            result['sample_multivalue_annotations'].append({
                                'subject_uri': first_triple.subject.uri,
                                'predicate_uri': first_triple.predicate.uri,
                                'values': list(all_values),
                                'value_count': len(all_values),
                                'dataset': dataset_config.dataset_name,
                                'column_name': column.column_name,
                                'separator': column.multi_value_separator or ';'
                            })
                            
                    elif column.is_external_ontology:
                        for triple in sample_triples:
                            external_uri = triple.object.uri if triple.object.resource_type == 'IRI' else triple.object.value
                            result['sample_external_annotations'].append({
                                'subject_uri': triple.subject.uri,
                                'predicate_uri': triple.predicate.uri,
                                'external_uri': external_uri,
                                'ontology_domain': _extract_ontology_domain(external_uri),
                                'dataset': dataset_config.dataset_name,
                                'column_name': column.column_name
                            })
                            
                    else:  # Regular column
                        for triple in sample_triples:
                            result['sample_regular_annotations'].append({
                                'subject_uri': triple.subject.uri,
                                'predicate_uri': triple.predicate.uri,
                                'value': str(triple.object.value if triple.object.resource_type == 'LITERAL' else triple.object.uri)[:100],
                                'dataset': dataset_config.dataset_name,
                                'column_name': column.column_name
                            })
        
    except Exception as e:
        logger.error(f"Error classifying sample annotations: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
    
    # Debug logging to see what we found
    total_annotations = sum(len(annotations) for annotations in result.values())
    logger.info(f"Classification complete. Found {total_annotations} total annotations:")
    for annotation_type, annotations in result.items():
        logger.info(f"  {annotation_type}: {len(annotations)} samples")
    
    return result


def _get_real_import_analysis(organization, ingest_session):
    """
    SHOW THE REAL FUCKING DATA - NO SAMPLES, ACTUAL ANALYSIS
    """
    from arkumu.importer.utils.mapping_utils import MappingUtils
    from django.db.models import Count, Q
    
    result = {
        'mapping_definition': {},
        'actual_database_content': {},
        'samples': {  # For template compatibility
            'sample_regular_annotations': [],
            'sample_anchor_annotations': [],
            'sample_fk_annotations': [],
            'sample_multivalue_annotations': [],
            'sample_multivalue_fk_annotations': [],
            'sample_context_annotations': [],
            'sample_external_annotations': []
        }
    }
    
    if not ingest_session.mapping:
        logger.error("No mapping found for session!")
        return result
    
    try:
        # PART 1: MAPPING DEFINITION - What SHOULD be there
        mapping_config = ingest_session.mapping.mapping_config
        
        # Use MappingUtils to analyze the mapping
        mapping_analysis = MappingUtils.analyze_mapping_structure(mapping_config)
        workspace_columns = MappingUtils.get_workspace_columns(mapping_config)
        
        result['mapping_definition'] = {
            'total_columns': mapping_analysis['total_columns'],
            'column_types': {
                'regular': mapping_analysis['regular_columns'],
                'anchor': mapping_analysis['anchor_columns'],
                'foreign_key': mapping_analysis['foreign_key_columns'],
                'multi_value': mapping_analysis['multi_value_columns'],
                'multi_value_fk': mapping_analysis['multi_value_fk_columns'],
                'relationship_context': mapping_analysis['relationship_context_columns'],
                'external_ontology': mapping_analysis['external_ontology_columns']
            },
            'datasets': list(mapping_analysis['dataset_breakdown'].keys()),
            'all_columns': []
        }
        
        # List ALL columns with their FULL configuration
        for col_name, col_config in workspace_columns.items():
            result['mapping_definition']['all_columns'].append({
                'name': col_name,
                'dataset': col_config.get('dataset', 'Unknown'),
                'arkumu_type': col_config.get('arkumu_type', ''),
                'type': MappingUtils.detect_column_type(col_config),
                'is_anchor': col_config.get('is_anchor', False),
                'is_fk': col_config.get('is_fk', False) or bool(col_config.get('fk_config')),
                'fk_config': col_config.get('fk_config', {}),
                'is_multi_value': col_config.get('is_multi_value', False),
                'separator': col_config.get('multi_value_separator', ''),
                'is_relationship_context': col_config.get('is_relationship_context', False)
            })
        
        # PART 2: ACTUAL DATABASE CONTENT - What IS there
        
        # Count all triples by type
        total_triples = Triple.objects.filter(source=organization).count()
        literal_triples = Triple.objects.filter(source=organization, object__resource_type='LITERAL').count()
        iri_triples = Triple.objects.filter(source=organization, object__resource_type='IRI').count()
        
        # Count resources
        total_resources = Resource.objects.filter(organization=organization).count()
        entity_resources = Resource.objects.filter(
            organization=organization,
            uri__contains='/entities/'
        ).count()
        
        # Analyze predicates - what properties actually exist
        predicate_counts = Triple.objects.filter(source=organization).values('predicate__uri').annotate(
            count=Count('id')
        ).order_by('-count')[:20]
        
        result['actual_database_content'] = {
            'total_triples': total_triples,
            'literal_triples': literal_triples,
            'iri_triples': iri_triples,
            'total_resources': total_resources,
            'entity_resources': entity_resources,
            'top_predicates': list(predicate_counts),
            'actual_fk_relationships': [],
            'actual_columns_with_data': []
        }
        
        # PART 3: MATCH MAPPING TO ACTUAL DATA
        # For each column in mapping, find if data exists
        for col_name, col_config in workspace_columns.items():
            # Use the column name itself to build the predicate URI
            column_name = col_config.get('name', '')
            if not column_name:
                continue
                
            # Build the expected predicate URI from the column name
            # Transform column name to match the actual database format (lowercase, hyphens)
            normalized_name = column_name.lower().replace(' ', '-')
            predicate_uri = f"http://arkumu.org/data/{organization.code}/properties/{normalized_name}"
            
            # Count how many triples exist for this predicate
            triple_count = Triple.objects.filter(
                source=organization,
                predicate__uri=predicate_uri
            ).count()
            
            if triple_count > 0:
                # Get a few actual examples
                example_triples = Triple.objects.filter(
                    source=organization,
                    predicate__uri=predicate_uri
                ).select_related('subject', 'predicate', 'object')[:3]
                
                examples = []
                for t in example_triples:
                    examples.append({
                        'subject': t.subject.uri,
                        'predicate': t.predicate.uri,
                        'value': t.object.uri if t.object.resource_type == 'IRI' else str(t.object.value)[:100]
                    })
                
                result['actual_database_content']['actual_columns_with_data'].append({
                    'column_name': col_name,
                    'dataset': col_config.get('dataset', ''),
                    'column_name_simple': column_name,
                    'column_type': MappingUtils.detect_column_type(col_config),
                    'triple_count': triple_count,
                    'examples': examples
                })
                
                # Add to appropriate sample category for template
                col_type = MappingUtils.detect_column_type(col_config)
                for example in examples[:2]:  # Add a couple examples
                    if col_type == 'anchor':
                        result['samples']['sample_anchor_annotations'].append({
                            'subject_uri': example['subject'],
                            'predicate_uri': example['predicate'],
                            'value': example['value'],
                            'dataset': col_config.get('dataset', ''),
                            'column_name': col_name
                        })
                    elif col_type == 'foreign_key':
                        result['samples']['sample_fk_annotations'].append({
                            'from_entity': example['subject'],
                            'relationship': example['predicate'],
                            'to_entity': example['value'],
                            'from_dataset': col_config.get('dataset', ''),
                            'to_dataset': col_config.get('fk_config', {}).get('target_dataset', ''),
                            'column_name': col_name,
                            'fk_target': col_config.get('fk_config', {}).get('target_dataset', '')
                        })
                    elif col_type == 'relationship_context':
                        result['samples']['sample_context_annotations'].append({
                            'junction_entity': example['subject'],
                            'context_property': example['predicate'],
                            'context_value': example['value'],
                            'dataset': col_config.get('dataset', ''),
                            'column_name': col_name
                        })
                    else:
                        result['samples']['sample_regular_annotations'].append({
                            'subject_uri': example['subject'],
                            'predicate_uri': example['predicate'],
                            'value': example['value'],
                            'dataset': col_config.get('dataset', ''),
                            'column_name': col_name
                        })
        
        # Find ACTUAL FK relationships (IRI to IRI)
        fk_relationships = Triple.objects.filter(
            source=organization,
            object__resource_type='IRI',
            object__uri__contains='/entities/'
        ).values('predicate__uri').annotate(
            count=Count('id')
        ).order_by('-count')[:10]
        
        for fk_rel in fk_relationships:
            # Get examples of this FK relationship
            examples = Triple.objects.filter(
                source=organization,
                predicate__uri=fk_rel['predicate__uri'],
                object__resource_type='IRI'
            ).select_related('subject', 'object')[:3]
            
            result['actual_database_content']['actual_fk_relationships'].append({
                'predicate': fk_rel['predicate__uri'],
                'count': fk_rel['count'],
                'examples': [
                    {
                        'from': ex.subject.uri,
                        'to': ex.object.uri
                    } for ex in examples
                ]
            })
        
        # Log the results
        logger.info("=== REAL IMPORT ANALYSIS ===")
        logger.info(f"Mapping defines {result['mapping_definition']['total_columns']} columns")
        logger.info(f"Database contains {result['actual_database_content']['total_triples']} triples")
        logger.info(f"Found {len(result['actual_database_content']['actual_columns_with_data'])} columns with actual data")
        
    except Exception as e:
        logger.error(f"Error in real import analysis: {e}")
        import traceback
        logger.error(traceback.format_exc())
    
    return result


def _get_real_column_data_by_types(organization, ingest_session):
    """Get real data from database organized by column types for template display"""
    if not ingest_session.mapping:
        logger.error("No mapping found for session!")
        return {
            'real_fk_data': [],
            'real_multivalue_data': [], 
            'real_context_data': [],
            'real_anchor_data': [],
            'real_regular_data': []
        }
    
    try:
        mapping_config = ingest_session.mapping.mapping_config
        workspace_columns = MappingUtils.get_workspace_columns(mapping_config)
        
        result = {
            'real_fk_data': [],
            'real_multivalue_data': [],
            'real_context_data': [], 
            'real_anchor_data': [],
            'real_regular_data': []
        }
        
        # Process each column by type
        for col_name, col_config in workspace_columns.items():
            column_name = col_config.get('name', '')
            if not column_name:
                continue
                
            # Build predicate URI  
            normalized_name = column_name.lower().replace(' ', '-')
            predicate_uri = f"http://arkumu.org/data/{organization.code}/properties/{normalized_name}"
            
            # Get actual triples for this column
            triples = Triple.objects.filter(
                source=organization,
                predicate__uri=predicate_uri
            ).select_related('subject', 'predicate', 'object')[:50]  # Show more triples
            
            if not triples.exists():
                continue
                
            # Determine column type
            col_type = MappingUtils.detect_column_type(col_config)
            dataset = col_config.get('dataset', 'Unknown')
            
            triple_data = []
            for triple in triples:
                triple_data.append({
                    'subject_uri': triple.subject.uri,
                    'predicate_uri': triple.predicate.uri,
                    'object_value': triple.object.uri if triple.object.resource_type == 'IRI' else str(triple.object.value),
                    'object_type': triple.object.resource_type,
                    'is_iri': triple.object.resource_type == 'IRI'
                })
            
            column_data = {
                'column_name': column_name,
                'full_column_name': col_name,
                'dataset': dataset,
                'predicate_uri': predicate_uri,
                'triple_count': triples.count(),
                'triples': triple_data
            }
            
            # Categorize by column type
            if col_type == 'foreign_key':
                # For FKs, also get the FK config details
                fk_config = col_config.get('fk_config', {})
                column_data.update({
                    'target_dataset': fk_config.get('target_dataset', 'Unknown'),
                    'target_column': fk_config.get('target_column', 'Unknown')
                })
                result['real_fk_data'].append(column_data)
            elif col_type == 'multi_value':
                # For multi-value, show the separator used
                column_data['separator'] = col_config.get('multi_value_separator', ',')
                result['real_multivalue_data'].append(column_data)
            elif col_type == 'relationship_context':
                result['real_context_data'].append(column_data)
            elif col_type == 'anchor':
                result['real_anchor_data'].append(column_data)
            else:
                result['real_regular_data'].append(column_data)
        
        logger.info(f"Real data by types - FK: {len(result['real_fk_data'])}, Multi: {len(result['real_multivalue_data'])}, Context: {len(result['real_context_data'])}, Anchor: {len(result['real_anchor_data'])}, Regular: {len(result['real_regular_data'])}")
        
    except Exception as e:
        logger.error(f"Error getting real column data by types: {e}")
        import traceback
        logger.error(traceback.format_exc())
    
    return result


def _classify_sample_annotations(organization, ingest_session):
    """Backwards compatibility wrapper"""
    analysis = _get_real_import_analysis(organization, ingest_session)
    return analysis.get('samples', {})


def _classify_sample_annotations_old2(organization, ingest_session):
    """Old version - kept for reference"""
    if not ingest_session.mapping:
        logger.error("No mapping found for session!")
        return result
    
    try:
        # USE MAPPINGUTILS - THE TOOL WE BUILT FOR THIS!
        mapping_config = ingest_session.mapping.mapping_config
        
        # Analyze the mapping structure properly
        analysis = MappingUtils.analyze_mapping_structure(mapping_config)
        logger.info(f"=== MAPPING ANALYSIS from MappingUtils ===")
        logger.info(f"Analysis results: {analysis}")
        
        # Group columns by type - this returns column NAMES, not configs!
        grouped_column_names = MappingUtils.group_columns_by_type(mapping_config)
        
        # Get the actual workspace columns with full configs
        workspace_columns = MappingUtils.get_workspace_columns(mapping_config)
        
        # Now get datasets from mapping_config properly
        datasets = mapping_config.get('datasets', {})
        
        logger.info(f"=== GROUPED COLUMNS ===")
        for col_type, column_names in grouped_column_names.items():
            logger.info(f"{col_type}: {len(column_names)} columns")
            for col_name in column_names[:2]:  # Log first 2 of each type
                if col_name in workspace_columns:
                    col_config = workspace_columns[col_name]
                    logger.info(f"  - {col_config.get('dataset', 'unknown')}.{col_name} ({col_config.get('arkumu_type', 'unknown')})")
        
        # Now get ACTUAL data for each column type
        
        # 1. FK COLUMNS - Get the actual FK relationships
        for col_name in grouped_column_names.get('foreign_key', [])[:5]:
            if col_name not in workspace_columns:
                continue
            fk_col = workspace_columns[col_name]
            dataset = fk_col.get('dataset', '')
            arkumu_type = fk_col.get('arkumu_type', '')
            fk_config = fk_col.get('fk_config', {})
            
            # Build the predicate URI for this FK column
            predicate_uri = f"http://arkumu.org/data/{organization.code}/properties/{arkumu_type}"
            
            # Find actual FK triples
            fk_triples = Triple.objects.filter(
                source=organization,
                predicate__uri=predicate_uri,
                object__resource_type='IRI'
            ).select_related('subject', 'predicate', 'object')[:3]
            
            logger.info(f"FK column {dataset}.{col_name}: found {len(fk_triples)} triples")
            
            for triple in fk_triples:
                result['sample_fk_annotations'].append({
                    'from_entity': triple.subject.uri,
                    'relationship': triple.predicate.uri,
                    'to_entity': triple.object.uri,
                    'from_dataset': dataset,
                    'to_dataset': fk_config.get('target_dataset', 'Unknown'),
                    'column_name': col_name,
                    'fk_target': fk_config.get('target_dataset', 'Unknown')
                })
        
        # 2. ANCHOR COLUMNS - Get ID fields
        for col_name in grouped_column_names.get('anchor', [])[:5]:
            if col_name not in workspace_columns:
                continue
            anchor_col = workspace_columns[col_name]
            dataset = anchor_col.get('dataset', '')
            arkumu_type = anchor_col.get('arkumu_type', '')
            
            predicate_uri = f"http://arkumu.org/data/{organization.code}/properties/{arkumu_type}"
            
            anchor_triples = Triple.objects.filter(
                source=organization,
                predicate__uri=predicate_uri
            ).select_related('subject', 'predicate', 'object')[:3]
            
            for triple in anchor_triples:
                result['sample_anchor_annotations'].append({
                    'subject_uri': triple.subject.uri,
                    'predicate_uri': triple.predicate.uri,
                    'value': str(triple.object.value)[:100],
                    'dataset': dataset,
                    'column_name': col_name,
                    'is_primary_key': True
                })
        
        # 3. RELATIONSHIP CONTEXT COLUMNS - Junction table data
        for col_name in grouped_column_names.get('relationship_context', [])[:5]:
            if col_name not in workspace_columns:
                continue
            context_col = workspace_columns[col_name]
            dataset = context_col.get('dataset', '')
            arkumu_type = context_col.get('arkumu_type', '')
            
            predicate_uri = f"http://arkumu.org/data/{organization.code}/properties/{arkumu_type}"
            
            context_triples = Triple.objects.filter(
                source=organization,
                predicate__uri=predicate_uri
            ).select_related('subject', 'predicate', 'object')[:3]
            
            for triple in context_triples:
                result['sample_context_annotations'].append({
                    'junction_entity': triple.subject.uri,
                    'context_property': triple.predicate.uri,
                    'context_value': str(triple.object.value if triple.object.resource_type == 'LITERAL' else triple.object.uri)[:100],
                    'dataset': dataset,
                    'column_name': col_name
                })
        
        # 4. MULTI-VALUE COLUMNS
        for col_name in grouped_column_names.get('multi_value', [])[:5]:
            if col_name not in workspace_columns:
                continue
            mv_col = workspace_columns[col_name]
            dataset = mv_col.get('dataset', '')
            arkumu_type = mv_col.get('arkumu_type', '')
            separator = mv_col.get('multi_value_separator', ';')
            
            predicate_uri = f"http://arkumu.org/data/{organization.code}/properties/{arkumu_type}"
            
            # Get one subject that has this predicate
            sample_triple = Triple.objects.filter(
                source=organization,
                predicate__uri=predicate_uri
            ).first()
            
            if sample_triple:
                # Get all values for this subject-predicate combination
                all_values = Triple.objects.filter(
                    source=organization,
                    subject=sample_triple.subject,
                    predicate=sample_triple.predicate
                ).values_list('object__value', flat=True)[:5]
                
                result['sample_multivalue_annotations'].append({
                    'subject_uri': sample_triple.subject.uri,
                    'predicate_uri': sample_triple.predicate.uri,
                    'values': list(all_values),
                    'value_count': len(all_values),
                    'dataset': dataset,
                    'column_name': col_name,
                    'separator': separator
                })
        
        # 5. REGULAR COLUMNS
        for col_name in grouped_column_names.get('regular', [])[:5]:
            if col_name not in workspace_columns:
                continue
            reg_col = workspace_columns[col_name]
            dataset = reg_col.get('dataset', '')
            arkumu_type = reg_col.get('arkumu_type', '')
            
            predicate_uri = f"http://arkumu.org/data/{organization.code}/properties/{arkumu_type}"
            
            regular_triples = Triple.objects.filter(
                source=organization,
                predicate__uri=predicate_uri
            ).select_related('subject', 'predicate', 'object')[:3]
            
            for triple in regular_triples:
                result['sample_regular_annotations'].append({
                    'subject_uri': triple.subject.uri,
                    'predicate_uri': triple.predicate.uri,
                    'value': str(triple.object.value if triple.object.resource_type == 'LITERAL' else triple.object.uri)[:100],
                    'dataset': dataset,
                    'column_name': col_name
                })
        
        # Log final results
        logger.info(f"=== FINAL CLASSIFICATION ===")
        for key, items in result.items():
            logger.info(f"{key}: {len(items)} items")
                    
    except Exception as e:
        logger.error(f"Error in classification: {e}")
        import traceback
        logger.error(traceback.format_exc())
    
    return result


def _extract_dataset_name(uri):
    """Extract dataset name from a resource URI"""
    try:
        # URIs typically look like: http://arkumu.org/data/ORG/datasets/DATASET_NAME/...
        if '/datasets/' in uri:
            return uri.split('/datasets/')[1].split('/')[0]
        return "Unknown"
    except:
        return "Unknown"


def _extract_ontology_domain(uri):
    """Extract ontology domain from an external URI"""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(uri)
        return parsed.netloc or "Unknown domain"
    except:
        return "Unknown domain"


def _extract_dataset_name_from_uri(uri):
    """Extract dataset name from a resource URI"""
    try:
        # URIs like: .../entities/akteurin-ereignis-kreuztabelle/542
        if '/entities/' in uri:
            parts = uri.split('/entities/')
            if len(parts) > 1:
                entity_part = parts[1].split('/')[0]  # Get the dataset part
                return entity_part.replace('-', ' ').title()
        elif '/datasets/' in uri:
            return uri.split('/datasets/')[1].split('/')[0].replace('-', ' ').title()
        return "Unknown Dataset"
    except:
        return "Unknown Dataset"


def _extract_column_name_from_predicate(uri):
    """Extract column name from a predicate URI"""
    try:
        # URIs like: .../properties/ist-urheberin
        if '/properties/' in uri:
            column_part = uri.split('/properties/')[-1]
            return column_part.replace('-', ' ').title()
        elif uri.endswith('#type'):
            return "RDF Type"
        else:
            # Extract last part of URI
            return uri.split('/')[-1].replace('-', ' ').title()
    except:
        return "Unknown Column"


def _count_multi_value_items(organization):
    """Count total multi-value items created (similar to mapping_aware_processor)"""
    try:
        from django.db.models import Count
        # Look for properties that appear multiple times for the same subject (indicating multi-value)
        multivalue_subjects = Triple.objects.filter(
            source=organization,
            object__resource_type='LITERAL'
        ).values('subject', 'predicate').annotate(
            count=Count('id')
        ).filter(count__gt=1)
        
        # Sum up all the individual values
        total_items = sum(mv['count'] for mv in multivalue_subjects)
        return total_items
    except Exception as e:
        logger.warning(f"Failed to count multi-value items: {e}")
        return 0


def _count_multi_value_cells(organization):
    """Count multi-value cells processed (similar to mapping_aware_processor)"""
    try:
        from django.db.models import Count
        # Count unique subject-predicate combinations that have multiple values
        multivalue_cells = Triple.objects.filter(
            source=organization,
            object__resource_type='LITERAL'
        ).values('subject', 'predicate').annotate(
            count=Count('id')
        ).filter(count__gt=1).count()
        
        return multivalue_cells
    except Exception as e:
        logger.warning(f"Failed to count multi-value cells: {e}")
        return 0


def _analyze_per_dataset_statistics(organization, execution_config):
    """Analyze per-dataset statistics similar to mapping_aware_processor dataset_counters"""
    per_dataset_stats = {}
    
    try:
        for dataset_config in execution_config.datasets:
            dataset_name = dataset_config.dataset_name
            
            # Count entities for this dataset
            dataset_entities = Resource.objects.filter(
                organization=organization,
                uri__contains=f"/entities/{dataset_name.lower()}/"
            )
            entity_count = dataset_entities.count()
            
            # Count different types of properties for this dataset
            dataset_triples = Triple.objects.filter(
                source=organization,
                subject__in=dataset_entities
            )
            
            # Count regular properties (literal values, non-ID)
            regular_props = dataset_triples.filter(
                object__resource_type='LITERAL'
            ).exclude(
                predicate__uri__contains='ID'
            ).count()
            
            # Count FK relationships (IRI objects)
            fk_resolved = dataset_triples.filter(
                object__resource_type='IRI',
                object__uri__contains='/entities/'
            ).exclude(
                predicate__uri__contains='isPartOf'
            ).count()
            
            # Count multi-value items for this dataset
            from django.db.models import Count
            mv_items = dataset_triples.filter(
                object__resource_type='LITERAL'
            ).values('subject', 'predicate').annotate(
                count=Count('id')
            ).filter(count__gt=1)
            
            multi_value_items = sum(mv['count'] for mv in mv_items)
            multi_value_cells = mv_items.count()
            
            # Count junction entities (if dataset name contains junction indicators)
            junction_count = 0
            if any(indicator in dataset_name.lower() for indicator in ['kreuztabelle', 'junction', '_link_']):
                junction_count = entity_count
            
            per_dataset_stats[dataset_name] = {
                'rows': entity_count,  # Each entity represents a processed row
                'props_regular': regular_props,
                'props_anchor': 0,  # Would need to identify anchor columns specifically
                'props_multi_items': multi_value_items,
                'props_multi_cells': multi_value_cells,
                'fk_resolved': fk_resolved,
                'fk_failed': 0,  # Would need error tracking
                'fk_missing': 0,  # Would need error tracking
                'fk_stubs': 0,  # Would need to identify stub entities
                'junctions': junction_count,
                'junction_attrs': regular_props if junction_count > 0 else 0
            }
            
    except Exception as e:
        logger.warning(f"Failed to analyze per-dataset statistics: {e}")
    
    return per_dataset_stats


def _count_multi_value_items(organization):
    """
    Count multi-value items created - approximated by counting triples 
    where the same subject-predicate pair has multiple objects
    """
    try:
        from django.db.models import Count
        
        # Count triples grouped by subject-predicate pairs that have multiple values
        multi_value_pairs = Triple.objects.filter(
            subject__in=Resource.objects.filter(organization=organization)
        ).values('subject', 'predicate').annotate(
            count=Count('id')
        ).filter(count__gt=1)
        
        # Sum up all the "extra" items (count - 1 for each multi-value pair)
        total_items = sum(pair['count'] - 1 for pair in multi_value_pairs)
        return total_items
        
    except Exception as e:
        logger.warning(f"Failed to count multi-value items: {e}")
        return 0


def _count_multi_value_cells(organization):
    """
    Count multi-value cells split - approximated by counting columns that likely had multi-values
    """
    try:
        from django.db.models import Count
        
        # Count distinct predicate URIs that have multi-value patterns
        multi_value_predicates = Triple.objects.filter(
            subject__in=Resource.objects.filter(organization=organization)
        ).values('predicate').annotate(
            total_uses=Count('id'),
            unique_subjects=Count('subject', distinct=True)
        )
        
        # Filter to predicates where total uses > unique subjects (indicating multi-values)
        count = 0
        for pred in multi_value_predicates:
            if pred['total_uses'] > pred['unique_subjects']:
                count += 1
        
        return count
        
    except Exception as e:
        logger.warning(f"Failed to count multi-value cells: {e}")
        return 0
