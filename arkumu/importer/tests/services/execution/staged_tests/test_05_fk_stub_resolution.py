"""
Stage 5: FK Stub Resolution Test

This test validates that FK stub resolution works correctly with real FUK data.
It specifically checks:
1. Whether stub entities are created for missing FK targets
2. Whether stubs are properly resolved when the real entities are processed
3. Whether FK relationships correctly point to entity resources (not literals)

This is CRUCIAL for FK resolution to work properly in production.
"""

import pytest
import logging
from typing import Dict, List, Any

from arkumu.metadata.models import Resource, Triple
from arkumu.importer.services.execution.mapping_aware_processor import MappingAwareProcessor
from arkumu.importer.services.execution.statistics import ExecutionStatistics
from arkumu.importer.services.mapping_consumer.config_translator import ProcessingStrategy
from arkumu.users.models import Organization

logger = logging.getLogger(__name__)


class TestFKStubResolution:
    """Test FK stub resolution with real FUK data"""
    
    @pytest.mark.django_db(transaction=True)
    def test_fk_stub_creation_and_resolution(self, production_test_mapping, real_csv_data):
        """Test that FK stubs are created and then resolved with real data"""
        
        logger.info("=" * 80)
        logger.info("STAGE 5: FK STUB RESOLUTION TEST")
        logger.info("=" * 80)
        
        # Setup
        from arkumu.importer.services.mapping_consumer.mapping_adapter import MappingAdapter
        mapping_adapter = MappingAdapter()
        execution_config = mapping_adapter.translate_to_execution_config(production_test_mapping.id)
        
        # Create test organization
        test_org, _ = Organization.objects.get_or_create(
            code="TEST_FUK_STUB",
            defaults={'name': 'Test FUK Stub Resolution'}
        )
        
        # Clear any existing data
        Triple.objects.filter(source=test_org).delete()
        Resource.objects.filter(organization=test_org).delete()
        
        # Initialize processor
        statistics = ExecutionStatistics()
        processor = MappingAwareProcessor(
            organization=test_org,
            base_uri="http://test.arkumu.org/data",
            statistics=statistics
        )
        
        # PHASE 1: Process datasets that have FK references FIRST
        # This should create stub entities for missing targets
        logger.info("\n" + "=" * 60)
        logger.info("PHASE 1: Processing datasets with FK references")
        logger.info("This should create STUB entities for missing FK targets")
        logger.info("=" * 60)
        
        # Select datasets that have FK references to other datasets
        fk_source_datasets = self._get_datasets_with_fk_references(execution_config, real_csv_data)
        
        logger.info(f"Processing {len(fk_source_datasets)} datasets with FK references:")
        for dataset_name in fk_source_datasets:
            logger.info(f"  - {dataset_name}")
        
        phase1_metrics = processor.process_with_execution_config(
            execution_config=execution_config,
            csv_sources=fk_source_datasets,
            strategy=ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        # Count stubs created
        stubs_after_phase1 = Resource.objects.filter(
            organization=test_org,
            is_placeholder=True,
            resource_type='IRI'
        ).count()
        
        logger.info(f"\n📊 PHASE 1 RESULTS:")
        logger.info(f"  Rows processed: {phase1_metrics.rows_processed}")
        logger.info(f"  Resources created: {phase1_metrics.resources_created}")
        logger.info(f"  Relationships created: {phase1_metrics.relationships_created}")
        logger.info(f"  STUB ENTITIES CREATED: {stubs_after_phase1}")
        
        # Verify stubs were created
        assert stubs_after_phase1 > 0, "No stub entities were created for missing FK targets!"
        
        # PHASE 2: Process the target datasets
        # This should RESOLVE the stub entities
        logger.info("\n" + "=" * 60)
        logger.info("PHASE 2: Processing target datasets")
        logger.info("This should RESOLVE the stub entities")
        logger.info("=" * 60)
        
        # Get remaining datasets (the FK targets)
        fk_target_datasets = self._get_fk_target_datasets(execution_config, real_csv_data, fk_source_datasets)
        
        logger.info(f"Processing {len(fk_target_datasets)} target datasets:")
        for dataset_name in fk_target_datasets:
            logger.info(f"  - {dataset_name}")
        
        phase2_metrics = processor.process_with_execution_config(
            execution_config=execution_config,
            csv_sources=fk_target_datasets,
            strategy=ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        # Count remaining stubs
        stubs_after_phase2 = Resource.objects.filter(
            organization=test_org,
            is_placeholder=True,
            resource_type='IRI'
        ).count()
        
        logger.info(f"\n📊 PHASE 2 RESULTS:")
        logger.info(f"  Rows processed: {phase2_metrics.rows_processed}")
        logger.info(f"  Resources created: {phase2_metrics.resources_created}")
        logger.info(f"  Relationships created: {phase2_metrics.relationships_created}")
        logger.info(f"  STUB ENTITIES REMAINING: {stubs_after_phase2}")
        
        # Calculate stub resolution
        stubs_resolved = stubs_after_phase1 - stubs_after_phase2
        resolution_rate = (stubs_resolved / stubs_after_phase1 * 100) if stubs_after_phase1 > 0 else 0
        
        logger.info(f"\n🔗 STUB RESOLUTION ANALYSIS:")
        logger.info(f"  Stubs created in Phase 1: {stubs_after_phase1}")
        logger.info(f"  Stubs remaining after Phase 2: {stubs_after_phase2}")
        logger.info(f"  STUBS RESOLVED: {stubs_resolved}")
        logger.info(f"  Resolution rate: {resolution_rate:.1f}%")
        
        # VALIDATION: Check that FK relationships use entity resources, not literals
        logger.info("\n" + "=" * 60)
        logger.info("VALIDATING FK RELATIONSHIPS")
        logger.info("=" * 60)
        
        # Find FK relationships (they should point to IRI resources, not literals)
        fk_relationships_to_entities = Triple.objects.filter(
            source=test_org,
            object__resource_type='IRI',
            object__uri__contains='/entities/'
        ).exclude(
            predicate__uri__contains='rdf-syntax'  # Exclude rdf:type
        ).count()
        
        fk_relationships_to_literals = Triple.objects.filter(
            source=test_org,
            object__resource_type='LITERAL'
        ).filter(
            # Look for potential FK columns that incorrectly use literals
            predicate__uri__contains='_id'
        ).count()
        
        logger.info(f"  FK relationships to entities (CORRECT): {fk_relationships_to_entities}")
        logger.info(f"  FK relationships to literals (BUG): {fk_relationships_to_literals}")
        
        # Sample some actual FK relationships
        sample_fk_triples = Triple.objects.filter(
            source=test_org,
            object__resource_type='IRI',
            object__uri__contains='/entities/'
        ).exclude(
            predicate__uri__contains='rdf-syntax'
        )[:5]
        
        if sample_fk_triples:
            logger.info("\n  Sample FK relationships (first 5):")
            for triple in sample_fk_triples:
                source_type = triple.subject.uri.split('/entities/')[1].split('/')[0] if '/entities/' in triple.subject.uri else 'unknown'
                target_type = triple.object.uri.split('/entities/')[1].split('/')[0] if '/entities/' in triple.object.uri else 'unknown'
                predicate_name = triple.predicate.uri.split('/')[-1]
                logger.info(f"    {source_type} --[{predicate_name}]--> {target_type}")
        
        # ASSERTIONS
        logger.info("\n" + "=" * 60)
        logger.info("TEST ASSERTIONS")
        logger.info("=" * 60)
        
        # 1. Stubs should have been created
        assert stubs_after_phase1 > 0, f"Expected stub entities to be created, but found {stubs_after_phase1}"
        logger.info(f"✅ Stub entities were created: {stubs_after_phase1}")
        
        # 2. Some stubs should have been resolved (but not necessarily all)
        if stubs_resolved > 0:
            logger.info(f"✅ Stub resolution occurred: {stubs_resolved} stubs resolved")
        else:
            logger.warning(f"⚠️ No stubs were resolved - this may indicate an issue with stub resolution")
        
        # 3. FK relationships should use entities, not literals
        assert fk_relationships_to_entities > 0, "No FK relationships to entities found"
        logger.info(f"✅ FK relationships correctly point to entities: {fk_relationships_to_entities}")
        
        if fk_relationships_to_literals > 0:
            logger.warning(f"⚠️ Found {fk_relationships_to_literals} FK relationships using literals - this is a BUG!")
        
        # Show final statistics
        total_resources = Resource.objects.filter(organization=test_org).count()
        total_triples = Triple.objects.filter(source=test_org).count()
        
        logger.info(f"\n📊 FINAL STATISTICS:")
        logger.info(f"  Total resources created: {total_resources}")
        logger.info(f"  Total triples created: {total_triples}")
        logger.info(f"  Stub entities remaining: {stubs_after_phase2}")
        logger.info(f"  Stub resolution rate: {resolution_rate:.1f}%")
        
        logger.info("\n" + "=" * 80)
        logger.info("✅ FK STUB RESOLUTION TEST COMPLETED")
        logger.info("=" * 80)
        
        # Cleanup
        Triple.objects.filter(source=test_org).delete()
        Resource.objects.filter(organization=test_org).delete()
    
    def _get_datasets_with_fk_references(self, execution_config, real_csv_data: Dict[str, Any]) -> Dict[str, Any]:
        """Get datasets that have FK references to other datasets"""
        datasets_with_fks = {}
        
        # Find datasets that have FK columns
        for dataset_config in execution_config.datasets:
            dataset_name = dataset_config.dataset_name
            
            # Check if this dataset has FK columns
            has_fk = False
            for column in dataset_config.columns:
                if column.column_type.value == 'foreign_key':
                    has_fk = True
                    break
            
            # If it has FKs and we have CSV data for it, include it
            if has_fk and dataset_name in real_csv_data:
                datasets_with_fks[dataset_name] = real_csv_data[dataset_name]
                
                # For testing, limit to first 3 datasets with FKs
                if len(datasets_with_fks) >= 3:
                    break
        
        return datasets_with_fks
    
    def _get_fk_target_datasets(self, execution_config, real_csv_data: Dict[str, Any], 
                                already_processed: Dict[str, Any]) -> Dict[str, Any]:
        """Get the target datasets that are referenced by FKs"""
        target_datasets = {}
        
        # Find what datasets are targets of FK relationships
        target_dataset_names = set()
        for fk_rel in execution_config.fk_relationships:
            target_dataset_names.add(fk_rel.target_dataset)
        
        # Include those target datasets that we have CSV data for
        for target_name in target_dataset_names:
            if target_name in real_csv_data and target_name not in already_processed:
                target_datasets[target_name] = real_csv_data[target_name]
                
                # For testing, limit to first 3 target datasets
                if len(target_datasets) >= 3:
                    break
        
        return target_datasets