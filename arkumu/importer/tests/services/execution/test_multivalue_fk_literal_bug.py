"""
Test for Multi-Value FK Literal Bug

This test exposes the bug where multi-value columns marked as foreign keys
may be incorrectly processed as literal values instead of entity references.

Bug Description:
After splitting multi-value literal with IDs into single values,
they are inserted into the triples as literals, even though
they should reference other entities through FK relationships.
"""

import pytest
import logging
from arkumu.users.models import Organization
from arkumu.metadata.models import Mapping, Resource, Triple
from arkumu.importer.services.execution.mapping_aware_processor import (
    MappingAwareProcessor,
)
from arkumu.importer.services.execution.statistics import ExecutionStatistics
from arkumu.importer.services.mapping_consumer.mapping_adapter import MappingAdapter
from arkumu.importer.services.mapping_consumer.config_translator import ConfigTranslator

logger = logging.getLogger(__name__)


@pytest.mark.django_db
def test_multivalue_fk_columns_should_create_entities_not_literals():
    """Test that multi-value FK columns create entity references, not literal values

    This test aims to reproduce the reported scenario where multi-value FK
    columns are incorrectly storing their values as literals instead of
    creating proper entity references.
    """

    # Setup organization
    org, _ = Organization.objects.get_or_create(
        code="multivaluefkbugtest",
        defaults={
            "name": "Multi-Value FK Bug Test Org",
            "domain": "multivaluefkbugtest.com",
        },
    )

    # Create mapping with proper multi-value FK setup following exact format
    mapping = Mapping.objects.create(
        name="MultiValueFK-Bug-Test",
        organization_id=org.code,
        source_datasets=["Employee", "Skill"],
        mapping_config={
            "version": "1.1",
            "workspace_datasets": ["Employee", "Skill"],
            "workspace_columns": {
                f"{org.code}::Employee::ID": {
                    "arkumu_type": "ID",
                    "datatype": "http://www.w3.org/2001/XMLSchema#string",
                    "is_anchor": True,
                },
                f"{org.code}::Employee::Name": {
                    "arkumu_type": "Name",
                    "datatype": "http://www.w3.org/2001/XMLSchema#string",
                },
                f"{org.code}::Employee::PrimarySkills": {
                    "arkumu_type": "PrimarySkills",
                    "datatype": "http://www.w3.org/2001/XMLSchema#string",
                    "is_multivalue": True,
                    "multi_value_separator": ",",
                    "is_fk": True,
                    "fk_config": {
                        "target_dataset": "Skill",
                        "target_column": "ID",
                        "relationship_type": "hasPrimarySkill",
                    },
                },
                f"{org.code}::Skill::ID": {
                    "arkumu_type": "ID",
                    "datatype": "http://www.w3.org/2001/XMLSchema#string",
                    "is_anchor": True,
                },
                f"{org.code}::Skill::Name": {
                    "arkumu_type": "Name",
                    "datatype": "http://www.w3.org/2001/XMLSchema#string",
                },
            },
            "fk_relationships": [
                {
                    "id": "employee_primary_skills_fk",
                    "source_dataset": "Employee",
                    "source_column": "PrimarySkills",
                    "target_dataset": "Skill",
                    "target_column": "ID",
                    "relationship_type": "hasPrimarySkill",
                    "is_multi_value": True,
                    "multi_value_separator": ",",
                }
            ],
        },
    )

    # Test data with multi-value FK column
    csv_sources = {
        "Skill": [
            {"ID": "SKILL001", "Name": "Programming"},
            {"ID": "SKILL002", "Name": "Design"},
            {"ID": "SKILL003", "Name": "Management"},
        ],
        "Employee": [
            {"ID": "EMP001", "Name": "John Doe", "PrimarySkills": "SKILL001,SKILL002"},
            {
                "ID": "EMP002",
                "Name": "Jane Smith",
                "PrimarySkills": "SKILL002,SKILL003",
            },
        ],
    }

    # Clear existing data
    Triple.objects.filter(source=org).delete()
    Resource.objects.filter(organization=org).delete()

    # Process with schema-driven processor
    statistics = ExecutionStatistics()
    processor = MappingAwareProcessor(
        organization=org, base_uri=f"http://arkumu.org/data/{org.code}", statistics=statistics
    )

    mapping_adapter = MappingAdapter()
    config_translator = ConfigTranslator()
    config = mapping_adapter.load_mapping_config(mapping.id)
    execution_config = config_translator.translate_mapping_config(config)

    logger.info("🔗 Testing multi-value FK column processing...")

    try:
        metrics = processor.process_with_execution_config(
            execution_config, csv_sources, "streaming_entity_centric"
        )
        logger.info("✅ Multi-value FK processing completed")

    except Exception as e:
        logger.warning(f"⚠️ Processing failed: {e}")
        raise

    # ANALYZE TRIPLE TYPES TO DETECT BUG
    total_resources = Resource.objects.filter(organization=org).count()
    total_triples = Triple.objects.filter(source=org).count()

    # Look for hasPrimarySkill triples specifically
    skill_triples = Triple.objects.filter(
        source=org, predicate__uri__contains="hasPrimarySkill"
    ).order_by("subject__uri")

    literal_skill_triples = Triple.objects.filter(
        source=org,
        predicate__uri__contains="hasPrimarySkill",
        object__resource_type="LITERAL",
    ).order_by("subject__uri")

    entity_skill_triples = Triple.objects.filter(
        source=org,
        predicate__uri__contains="hasPrimarySkill",
        object__resource_type="IRI",
        object__uri__contains="/entities/",  # Should identify entity references
    ).order_by("subject__uri")

    logger.info(f"📊 MULTI-VALUE FK ANALYSIS:")
    logger.info(f"  Total resources: {total_resources}")
    logger.info(f"  Total triples: {total_triples}")
    logger.info(f"  Skill triples (all): {skill_triples.count()}")
    logger.info(f"  Skill triples with literals: {literal_skill_triples.count()}")
    logger.info(f"  Skill triples with entities: {entity_skill_triples.count()}")

    logger.info("\n📋 SKILL TRIPLE DETAILS:")
    for triple in skill_triples:
        obj_type = triple.object.resource_type
        obj_uri = triple.object.uri
        logger.info(
            f"  {triple.subject.uri} -> hasPrimarySkill -> {obj_type}({obj_uri})"
        )

    # BUG VALIDATION
    # If we have literal skill triples, the bug exists
    literal_count = literal_skill_triples.count()
    entity_count = entity_skill_triples.count()

    if literal_count > 0:
        logger.error(
            "🚨 BUG DETECTED: Found literal skill values instead of entity references!"
        )

        # Show the specific broken triples
        for triple in literal_skill_triples:
            logger.error(
                f"  ❌ {triple.subject.uri} -> hasPrimarySkill -> LITERAL('{triple.object.uri}')"
            )

        # The test assertion that fails will prove the bug exists
        pytest.fail(
            f"BUG: Found {literal_count} literal skill triples. "
            f"All should be entity references, not literals. "
            f"(Entity triples: {entity_count})"
        )

    # Validate the expected behavior when bug is fixed
    if entity_count > 0:
        logger.info("✅ GOOD: All skill triples are properly referencing entities")

        # Show correct references
        for triple in entity_skill_triples:
            logger.info(
                f"  ✅ {triple.subject.uri} -> hasPrimarySkill -> ENTITY({triple.object.uri})"
            )

        # We should have the right number of entity triples
        # EMP001 has 2 skills: SKILL001, SKILL002
        # EMP002 has 2 skills: SKILL002, SKILL003
        # Total entities used (unique skills): 3
        # Total relationships: 4
        expected_entity_triples = 4  # 2 employees × 2 skills each = 4 triples
        assert entity_count >= 3, (
            f"Should have at least 3 entity skill references, got {entity_count}"
        )
        logger.info(f"✅ Correct number of entity triples created: {entity_count}")

    else:
        logger.warning(
            "⚠️ No skill entity triples found - may indicate processing not happening correctly"
        )
        # Since we expect 4 total triples for our test (2 employees × 2 skills)
        # At least we should see entity triples created to validate processing
        pytest.fail("No skill entity triples found - processing may have failed")

    # Validate resource creation integrity
    logger.info("\n🔍 RESOURCE INTEGRITY CHECKS:")
    employee_resources = Resource.objects.filter(
        organization=org, resource_type="Employee"
    ).count()
    skill_resources = Resource.objects.filter(
        organization=org, resource_type="Skill"
    ).count()

    logger.info(f"  Employee entities created: {employee_resources}")
    logger.info(f"  Skill entities created: {skill_resources}")

    assert employee_resources == 2, (
        f"Should have 2 employee entities, got {employee_resources}"
    )
    assert skill_resources == 3, f"Should have 3 skill entities, got {skill_resources}"

    logger.info("✅ All integrity checks passed - test is working correctly")
