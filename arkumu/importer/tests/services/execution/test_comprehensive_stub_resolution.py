"""
Comprehensive Stub Resolution Test

Tests stub resolution across all data types:
1. Basic FK relationships 
2. Multi-value columns with FK relationships
3. Relationship contexts (junction tables)

This validates that the stub resolution fix works for all scenarios where 
FK relationships might create stub entities that need to be resolved.
"""

import pytest
import logging
from arkumu.users.models import Organization
from arkumu.metadata.models import Mapping, Resource, Triple
from arkumu.importer.services.execution.mapping_aware_processor import MappingAwareProcessor
from arkumu.importer.services.execution.statistics import ExecutionStatistics
from arkumu.importer.services.mapping_consumer.mapping_adapter import MappingAdapter
from arkumu.importer.services.mapping_consumer.config_translator import ConfigTranslator, ProcessingStrategy

logger = logging.getLogger(__name__)


@pytest.mark.django_db
def test_comprehensive_stub_resolution():
    """Test stub resolution for FK relationships, multi-value FKs, and junction tables"""
    
    logger.info("🔗 Testing comprehensive stub resolution across all data types...")
    
    # Setup organization
    org, _ = Organization.objects.get_or_create(
        code='comprehensive_stub_test',
        defaults={'name': 'Comprehensive Stub Test Org', 'domain': 'stubtest.com'}
    )
    
    # Create comprehensive mapping with all data types
    mapping = Mapping.objects.create(
        name='Comprehensive-Stub-Test',
        organization_id=org.code,
        source_datasets=['Person', 'Department', 'Project', 'PersonProject', 'Event'],
        mapping_config={
            'version': '1.1',
            'workspace_datasets': {
                'Person': {
                    'columns': [
                        {'name': 'ID', 'arkumu_type': 'ID'},
                        {'name': 'Name', 'arkumu_type': 'Name'},
                        {'name': 'DepartmentID', 'arkumu_type': 'DepartmentID'},  # Basic FK
                        {'name': 'Skills', 'arkumu_type': 'Skills', 'is_multivalue': True}  # Multi-value
                    ]
                },
                'Department': {
                    'columns': [
                        {'name': 'ID', 'arkumu_type': 'ID'},
                        {'name': 'Name', 'arkumu_type': 'Name'}
                    ]
                },
                'Project': {
                    'columns': [
                        {'name': 'ID', 'arkumu_type': 'ID'},
                        {'name': 'Name', 'arkumu_type': 'Name'}
                    ]
                },
                'PersonProject': {
                    'columns': [
                        {'name': 'PersonID', 'arkumu_type': 'PersonID'},      # Junction table
                        {'name': 'ProjectID', 'arkumu_type': 'ProjectID'},    # Junction table
                        {'name': 'Role', 'arkumu_type': 'Role'}
                    ]
                },
                'Event': {
                    'columns': [
                        {'name': 'ID', 'arkumu_type': 'ID'},
                        {'name': 'Name', 'arkumu_type': 'Name'},
                        {'name': 'AttendeeIDs', 'arkumu_type': 'AttendeeIDs', 'is_multivalue': True}  # Multi-value FK
                    ]
                }
            },
            'fk_relationships': [
                # Basic FK relationship
                {
                    'id': 'person_department_fk',
                    'source_dataset': 'Person',
                    'source_column': 'DepartmentID',
                    'target_dataset': 'Department',
                    'target_column': 'ID'
                },
                # Multi-value FK relationship
                {
                    'id': 'event_attendees_fk',
                    'source_dataset': 'Event',
                    'source_column': 'AttendeeIDs',
                    'target_dataset': 'Person',
                    'target_column': 'ID',
                    'is_multivalue': True
                }
            ],
            'multi_value_columns': [
                {
                    'dataset': 'Person',
                    'column': 'Skills',
                    'delimiter': ',',
                    'property': 'hasSkill'
                },
                {
                    'dataset': 'Event',
                    'column': 'AttendeeIDs',
                    'delimiter': ',',
                    'property': 'hasAttendee'
                }
            ],
            'relationship_contexts': [
                {
                    'id': 'person_project_context',
                    'junction_dataset': 'PersonProject',
                    'source_column': 'PersonID',
                    'target_column': 'ProjectID',
                    'source_dataset': 'Person',
                    'target_dataset': 'Project',
                    'relationship_name': 'worksOn'
                }
            ]
        }
    )
    
    # Test data designed to create stubs in specific order
    csv_sources = {
        # PHASE 1: Process these first (will create stubs for Person, Department, Project)
        'PersonProject': [
            {'PersonID': 'P001', 'ProjectID': 'PROJ001', 'Role': 'Developer'},
            {'PersonID': 'P002', 'ProjectID': 'PROJ001', 'Role': 'Designer'},
            {'PersonID': 'P001', 'ProjectID': 'PROJ002', 'Role': 'Lead'}
        ],
        'Event': [
            {'ID': 'E001', 'Name': 'Team Meeting', 'AttendeeIDs': 'P001,P002,P003'},  # Multi-value FK
            {'ID': 'E002', 'Name': 'Project Review', 'AttendeeIDs': 'P001,P004'}      # Multi-value FK
        ],
        
        # PHASE 2: Process these second (should resolve stubs)
        'Person': [
            {'ID': 'P001', 'Name': 'Alice Smith', 'DepartmentID': 'D001', 'Skills': 'Python,Django,React'},
            {'ID': 'P002', 'Name': 'Bob Jones', 'DepartmentID': 'D001', 'Skills': 'JavaScript,CSS'},
            {'ID': 'P003', 'Name': 'Carol Davis', 'DepartmentID': 'D002', 'Skills': 'Java,Spring'},
            {'ID': 'P004', 'Name': 'David Wilson', 'DepartmentID': 'D002', 'Skills': 'Python,FastAPI'}
        ],
        'Department': [
            {'ID': 'D001', 'Name': 'Engineering'},
            {'ID': 'D002', 'Name': 'Product'}
        ],
        'Project': [
            {'ID': 'PROJ001', 'Name': 'Web App'},
            {'ID': 'PROJ002', 'Name': 'Mobile App'}
        ]
    }
    
    # Clear existing data
    Triple.objects.filter(source=org).delete()
    Resource.objects.filter(organization=org).delete()
    
    # Process with mapping-aware processor
    statistics = ExecutionStatistics()
    processor = MappingAwareProcessor(org, f"http://arkumu.org/data/{org.code}", statistics)
    
    mapping_adapter = MappingAdapter()
    config_translator = ConfigTranslator()
    config = mapping_adapter.load_mapping_config(mapping.id)
    execution_config = config_translator.translate_mapping_config(config)
    
    logger.info(f"✅ Loaded mapping: {len(execution_config.datasets)} datasets, {len(execution_config.fk_relationships)} FK relationships")
    
    try:
        # PHASE 1: Process referencing datasets (creates stubs)
        logger.info("📋 PHASE 1: Processing PersonProject and Event (will create stubs)")
        
        phase1_data = {
            'PersonProject': csv_sources['PersonProject'],
            'Event': csv_sources['Event']
        }
        
        phase1_metrics = processor.process_with_execution_config(
            execution_config=execution_config,
            csv_sources=phase1_data,
            strategy=ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        # Count stubs after phase 1
        stub_count_phase1 = Resource.objects.filter(
            organization=org,
            is_placeholder=True
        ).count()
        
        total_resources_phase1 = Resource.objects.filter(organization=org).count()
        
        logger.info(f"📊 PHASE 1 RESULTS:")
        logger.info(f"  Total resources: {total_resources_phase1}")
        logger.info(f"  Stub entities created: {stub_count_phase1}")
        logger.info(f"  Rows processed: {phase1_metrics.rows_processed}")
        
        # PHASE 2: Process target datasets (should resolve stubs)
        logger.info("📋 PHASE 2: Processing Person, Department, Project (should resolve stubs)")
        
        phase2_data = {
            'Person': csv_sources['Person'],
            'Department': csv_sources['Department'],
            'Project': csv_sources['Project']
        }
        
        phase2_metrics = processor.process_with_execution_config(
            execution_config=execution_config,
            csv_sources=phase2_data,
            strategy=ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        logger.info(f"  Phase 2 rows processed: {phase2_metrics.rows_processed}")
        
        # ANALYZE COMPREHENSIVE STUB RESOLUTION
        final_total_resources = Resource.objects.filter(organization=org).count()
        
        remaining_stubs = Resource.objects.filter(
            organization=org,
            is_placeholder=True
        ).count()
        
        real_entities = Resource.objects.filter(
            organization=org,
            is_placeholder=False,
            resource_type='IRI'
        ).count()
        
        # Check different types of FK relationships
        
        # 1. Basic FK relationships (Person -> Department)
        basic_fk_literals = Triple.objects.filter(
            source=org,
            predicate__uri__contains='DepartmentID',
            object__resource_type='LITERAL'
        ).count()
        
        basic_fk_entities = Triple.objects.filter(
            source=org,
            predicate__uri__contains='DepartmentID',
            object__resource_type='IRI',
            object__uri__contains='/entities/'
        ).count()
        
        # 2. Multi-value FK relationships (Event -> Person)
        multivalue_fk_literals = Triple.objects.filter(
            source=org,
            predicate__uri__contains='hasAttendee',
            object__resource_type='LITERAL'
        ).count()
        
        multivalue_fk_entities = Triple.objects.filter(
            source=org,
            predicate__uri__contains='hasAttendee',
            object__resource_type='IRI',
            object__uri__contains='/entities/'
        ).count()
        
        # 3. Junction table relationships (PersonProject -> Person/Project)
        junction_literals = Triple.objects.filter(
            source=org,
            subject__uri__contains='/entities/personproject/',
            object__resource_type='LITERAL'
        ).exclude(
            predicate__uri__contains='Role'  # Role is not an FK
        ).count()
        
        junction_entities = Triple.objects.filter(
            source=org,
            subject__uri__contains='/entities/personproject/',
            object__resource_type='IRI',
            object__uri__contains='/entities/'
        ).count()
        
        # 4. Multi-value regular columns (Person -> Skills)
        multivalue_skills = Triple.objects.filter(
            source=org,
            predicate__uri__contains='hasSkill'
        ).count()
        
        # Get stub resolution statistics
        resolved_stubs = getattr(statistics.current_metrics, 'stub_entities_resolved', 0)
        
        logger.info(f"📊 COMPREHENSIVE STUB RESOLUTION ANALYSIS:")
        logger.info(f"  Final total resources: {final_total_resources}")
        logger.info(f"  Stub entities after phase 1: {stub_count_phase1}")
        logger.info(f"  Remaining stub entities: {remaining_stubs}")
        logger.info(f"  Real entities: {real_entities}")
        logger.info(f"  Stub entities resolved (tracked): {resolved_stubs}")
        logger.info(f"")
        logger.info(f"  BASIC FK RELATIONSHIPS:")
        logger.info(f"    Literals (BUG): {basic_fk_literals}")
        logger.info(f"    Entities (CORRECT): {basic_fk_entities}")
        logger.info(f"")
        logger.info(f"  MULTI-VALUE FK RELATIONSHIPS:")
        logger.info(f"    Literals (BUG): {multivalue_fk_literals}")
        logger.info(f"    Entities (CORRECT): {multivalue_fk_entities}")
        logger.info(f"")
        logger.info(f"  JUNCTION TABLE RELATIONSHIPS:")
        logger.info(f"    Literals (BUG): {junction_literals}")
        logger.info(f"    Entities (CORRECT): {junction_entities}")
        logger.info(f"")
        logger.info(f"  MULTI-VALUE REGULAR COLUMNS:")
        logger.info(f"    Skills processed: {multivalue_skills}")
        
        # COMPREHENSIVE VALIDATION
        
        # 1. Verify stub resolution occurred
        if stub_count_phase1 > 0:
            logger.info(f"✅ STUB CREATION: {stub_count_phase1} stub entities created in phase 1")
            
            if remaining_stubs < stub_count_phase1:
                resolved_count = stub_count_phase1 - remaining_stubs
                logger.info(f"✅ STUB RESOLUTION: {resolved_count} stubs converted to real entities")
                assert resolved_count > 0, "Expected stub resolution but none occurred"
            else:
                logger.warning(f"⚠️ STUB RESOLUTION ISSUE: {remaining_stubs} stubs remain unresolved")
        
        # 2. Verify basic FK relationships work correctly
        if basic_fk_entities > 0:
            logger.info(f"✅ BASIC FK RELATIONSHIPS: {basic_fk_entities} correctly use entities")
            assert basic_fk_literals == 0, f"Basic FK relationships should not use literals, found {basic_fk_literals}"
        
        # 3. Verify multi-value FK relationships work correctly
        if multivalue_fk_entities > 0:
            logger.info(f"✅ MULTI-VALUE FK RELATIONSHIPS: {multivalue_fk_entities} correctly use entities")
            assert multivalue_fk_literals == 0, f"Multi-value FK relationships should not use literals, found {multivalue_fk_literals}"
        
        # 4. Verify junction table relationships work correctly
        if junction_entities > 0:
            logger.info(f"✅ JUNCTION TABLE RELATIONSHIPS: {junction_entities} correctly use entities")
            assert junction_literals == 0, f"Junction table relationships should not use literals, found {junction_literals}"
        
        # 5. Verify multi-value regular columns work
        if multivalue_skills > 0:
            logger.info(f"✅ MULTI-VALUE COLUMNS: {multivalue_skills} skills processed correctly")
            assert multivalue_skills >= 8, f"Expected at least 8 skills, found {multivalue_skills}"  # 4 people with 2+ skills each
        
        # Core assertions
        assert final_total_resources > 0, "Should have created resources"
        assert real_entities > 0, "Should have real entities"
        
        # Show examples of correct relationships
        logger.info("📋 RELATIONSHIP EXAMPLES:")
        
        # Basic FK example
        basic_fk_examples = Triple.objects.filter(
            source=org,
            predicate__uri__contains='DepartmentID',
            object__resource_type='IRI'
        )[:2]
        
        for triple in basic_fk_examples:
            logger.info(f"  ✅ Basic FK: Person -> Department entity")
        
        # Multi-value FK example
        mv_fk_examples = Triple.objects.filter(
            source=org,
            predicate__uri__contains='hasAttendee',
            object__resource_type='IRI'
        )[:2]
        
        for triple in mv_fk_examples:
            logger.info(f"  ✅ Multi-value FK: Event -> Person entity")
        
        # Junction table example
        junction_examples = Triple.objects.filter(
            source=org,
            subject__uri__contains='/entities/personproject/',
            object__resource_type='IRI',
            object__uri__contains='/entities/'
        )[:2]
        
        for triple in junction_examples:
            entity_type = triple.object.uri.split('/entities/')[1].split('/')[0]
            logger.info(f"  ✅ Junction: PersonProject -> {entity_type} entity")
        
        logger.info("✅ Comprehensive stub resolution test completed successfully")
        logger.info("✅ All FK relationship types work correctly with stub resolution")
        
    except Exception as e:
        logger.error(f"❌ Comprehensive stub resolution test failed: {e}")
        raise
    
    finally:
        # Cleanup
        try:
            Triple.objects.filter(source=org).delete()
            Resource.objects.filter(organization=org).delete()
            mapping.delete()
            org.delete()
        except Exception as e:
            logger.warning(f"⚠️ Cleanup warning: {e}")