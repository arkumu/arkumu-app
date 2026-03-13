"""
Tests for two-phase bulk chunk processing optimization.

Verifies that MappingAwareProcessor._process_dataset_chunk_with_entities
correctly uses Phase 1 (collect) and Phase 2 (flush) to batch DB operations
for entity creation, rdf:type triples, and property triples.

Also tests ResourceManager.create_relationship_triples_bulk and
ResourceManager.create_entity_resources_from_uris_bulk.
"""
import pytest
from unittest.mock import Mock, patch, call

from arkumu.importer.services.execution.mapping_aware_processor import (
    MappingAwareProcessor, ProcessingContext
)
from arkumu.importer.services.mapping_consumer import (
    ExecutionConfig, DatasetConfig, ColumnConfig, ColumnType, ProcessingStrategy,
)
from arkumu.importer.services.execution.statistics import ExecutionStatistics
from arkumu.importer.services.execution.resource_manager import ResourceManager
from arkumu.metadata.models import Resource
from arkumu.metadata.models.resource import ResourceType
from arkumu.metadata.models.triples import Triple


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_resource(rid, uri, is_placeholder=False):
    """Create a real-ish mock Resource."""
    r = Mock(spec=Resource)
    r.id = rid
    r.uri = uri
    r.is_placeholder = is_placeholder
    r.resource_type = ResourceType.ENTITY
    r._meta = Resource._meta
    r._state = Mock()
    r._state.db = "default"
    return r


def _make_dataset_config(dataset_name, columns):
    """Build a DatasetConfig from a list of ColumnConfig objects."""
    return DatasetConfig(
        dataset_name=dataset_name,
        columns=columns,
    )


def _make_column(name, col_type=ColumnType.REGULAR, arkumu_type=None,
                 is_anchor=False, is_multi_value=False, separator=",",
                 is_external_ontology=False, external_ontology_config=None):
    return ColumnConfig(
        column_name=name,
        dataset_name="test_dataset",
        column_type=col_type,
        arkumu_type=arkumu_type or name,
        datatype="http://www.w3.org/2001/XMLSchema#string",
        is_anchor=is_anchor,
        is_multi_value=is_multi_value,
        multi_value_separator=separator,
        is_external_ontology=is_external_ontology,
        external_ontology_config=external_ontology_config,
    )


def _make_execution_config(datasets, fk_relationships=None):
    return ExecutionConfig(
        mapping_id=1,
        mapping_name="test_mapping",
        organization="TEST_ORG",
        datasets=datasets,
        fk_relationships=fk_relationships or [],
        relationship_contexts=[],
        processing_strategy=ProcessingStrategy.STREAMING_ENTITY_CENTRIC,
    )


def _make_processor(organization, base_uri, statistics):
    return MappingAwareProcessor(
        organization=organization,
        base_uri=base_uri,
        statistics=statistics,
    )


def _make_context(execution_config, csv_sources, dataset_name="test_dataset"):
    return ProcessingContext(
        execution_config=execution_config,
        current_dataset=dataset_name,
        all_csv_sources=csv_sources,
        entity_cache={},
        processed_datasets=set(),
    )


# ---------------------------------------------------------------------------
# ResourceManager bulk tests (database-backed)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestCreateEntityResourcesFromUriBulk:
    """Tests for ResourceManager.create_entity_resources_from_uris_bulk"""

    def test_creates_new_entities(self, test_organization, test_base_uri, execution_statistics):
        rm = ResourceManager(organization=test_organization, base_uri=test_base_uri, statistics=execution_statistics)

        uri_data = [
            ("http://test.arkumu.org/e/1", "entity_1"),
            ("http://test.arkumu.org/e/2", "entity_2"),
        ]
        result = rm.create_entity_resources_from_uris_bulk(uri_data)

        assert len(result) == 2
        for uri, _ in uri_data:
            assert uri in result
            assert result[uri].uri == uri
            assert result[uri].is_placeholder is False

    def test_deduplicates_within_batch(self, test_organization, test_base_uri, execution_statistics):
        rm = ResourceManager(organization=test_organization, base_uri=test_base_uri, statistics=execution_statistics)

        uri_data = [
            ("http://test.arkumu.org/e/dup", "dup"),
            ("http://test.arkumu.org/e/dup", "dup"),
            ("http://test.arkumu.org/e/other", "other"),
        ]
        result = rm.create_entity_resources_from_uris_bulk(uri_data)

        assert len(result) == 2
        assert Resource.objects.filter(uri="http://test.arkumu.org/e/dup").count() == 1

    def test_resolves_stubs(self, test_organization, test_base_uri, execution_statistics):
        rm = ResourceManager(organization=test_organization, base_uri=test_base_uri, statistics=execution_statistics)

        # Pre-create a stub
        stub = Resource.objects.create(
            uri="http://test.arkumu.org/e/stub",
            resource_type=ResourceType.ENTITY,
            name="stub",
            is_placeholder=True,
            organization=test_organization,
        )
        assert stub.is_placeholder is True

        result = rm.create_entity_resources_from_uris_bulk([
            ("http://test.arkumu.org/e/stub", "stub"),
        ])

        assert len(result) == 1
        # Verify DB was updated
        stub.refresh_from_db()
        assert stub.is_placeholder is False
        assert execution_statistics.current_metrics.fk_stub_entities_resolved == 1

    def test_returns_existing_non_stub(self, test_organization, test_base_uri, execution_statistics):
        rm = ResourceManager(organization=test_organization, base_uri=test_base_uri, statistics=execution_statistics)

        existing = Resource.objects.create(
            uri="http://test.arkumu.org/e/existing",
            resource_type=ResourceType.ENTITY,
            name="existing",
            is_placeholder=False,
            organization=test_organization,
        )

        result = rm.create_entity_resources_from_uris_bulk([
            ("http://test.arkumu.org/e/existing", "existing"),
        ])

        assert len(result) == 1
        assert result["http://test.arkumu.org/e/existing"].id == existing.id

    def test_empty_input(self, test_organization, test_base_uri, execution_statistics):
        rm = ResourceManager(organization=test_organization, base_uri=test_base_uri, statistics=execution_statistics)
        assert rm.create_entity_resources_from_uris_bulk([]) == {}

    def test_truncates_long_names(self, test_organization, test_base_uri, execution_statistics):
        rm = ResourceManager(organization=test_organization, base_uri=test_base_uri, statistics=execution_statistics)
        long_name = "x" * 200
        result = rm.create_entity_resources_from_uris_bulk([
            ("http://test.arkumu.org/e/long", long_name),
        ])
        assert len(result) == 1
        r = result["http://test.arkumu.org/e/long"]
        assert len(r.name) <= 100


@pytest.mark.django_db
class TestCreateRelationshipTriplesBulk:
    """Tests for ResourceManager.create_relationship_triples_bulk"""

    def _create_resources(self, org, n=3):
        resources = []
        for i in range(n):
            r = Resource.objects.create(
                uri=f"http://test.arkumu.org/res/{i}",
                resource_type=ResourceType.ENTITY,
                name=f"res_{i}",
                organization=org,
            )
            resources.append(r)
        return resources

    def test_creates_relationship_triples(self, test_organization, test_base_uri, execution_statistics):
        rm = ResourceManager(organization=test_organization, base_uri=test_base_uri, statistics=execution_statistics)
        resources = self._create_resources(test_organization)

        rel_data = [
            (resources[0], "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", resources[2]),
            (resources[1], "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", resources[2]),
        ]
        result = rm.create_relationship_triples_bulk(rel_data)

        assert len(result) == 2
        assert execution_statistics.current_metrics.relationships_created >= 2

    def test_deduplicates_property_resources(self, test_organization, test_base_uri, execution_statistics):
        rm = ResourceManager(organization=test_organization, base_uri=test_base_uri, statistics=execution_statistics)
        resources = self._create_resources(test_organization)

        prop_uri = "http://example.org/prop/same"
        rel_data = [
            (resources[0], prop_uri, resources[2]),
            (resources[1], prop_uri, resources[2]),
        ]
        rm.create_relationship_triples_bulk(rel_data)

        # Only one property resource should be created for the shared URI
        prop_count = Resource.objects.filter(uri=prop_uri).count()
        assert prop_count == 1

    def test_empty_input(self, test_organization, test_base_uri, execution_statistics):
        rm = ResourceManager(organization=test_organization, base_uri=test_base_uri, statistics=execution_statistics)
        assert rm.create_relationship_triples_bulk([]) == []

    def test_filters_existing_triples(self, test_organization, test_base_uri, execution_statistics):
        rm = ResourceManager(organization=test_organization, base_uri=test_base_uri, statistics=execution_statistics)
        resources = self._create_resources(test_organization)

        rel_data = [
            (resources[0], "http://example.org/rel", resources[1]),
        ]
        # Create once
        rm.create_relationship_triples_bulk(rel_data)
        first_count = execution_statistics.current_metrics.relationships_created

        # Create again — should be filtered as existing
        rm.create_relationship_triples_bulk(rel_data)
        assert execution_statistics.current_metrics.relationships_created == first_count


# ---------------------------------------------------------------------------
# Two-phase chunk processing integration tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestTwoPhaseChunkProcessing:
    """Tests for the refactored _process_dataset_chunk_with_entities"""

    def _setup_processor(self, test_organization, test_base_uri, execution_statistics, columns, dataset_name="test_dataset"):
        processor = _make_processor(test_organization, test_base_uri, execution_statistics)
        dataset_config = _make_dataset_config(dataset_name, columns)
        execution_config = _make_execution_config([dataset_config])
        csv_sources = {dataset_name: []}
        context = _make_context(execution_config, csv_sources, dataset_name)

        # Set up blueprints so rdf:type triples are created
        entity_type = Resource.objects.create(
            uri=f"http://test.arkumu.org/types/{dataset_name}",
            resource_type=ResourceType.CLASS,
            name=dataset_name,
            organization=test_organization,
        )
        processor.dataset_blueprints = {
            dataset_name: {"entity_type_resource": entity_type}
        }
        return processor, dataset_config, context, entity_type

    def test_basic_regular_columns(self, test_organization, test_base_uri, execution_statistics):
        """Regular columns produce correct entities and property triples."""
        columns = [
            _make_column("name"),
            _make_column("age"),
        ]
        processor, ds_config, context, entity_type = self._setup_processor(
            test_organization, test_base_uri, execution_statistics, columns
        )

        csv_data = [
            {"name": "Alice", "age": "30"},
            {"name": "Bob", "age": "25"},
        ]
        entities = processor._process_dataset_chunk_with_entities(ds_config, csv_data, context)

        assert len(entities) == 2
        # Verify entities in cache
        assert len(context.entity_cache) == 2
        # Verify statistics
        dc = context.dataset_counters["test_dataset"]
        assert dc["rows"] == 2
        assert dc["props_regular"] == 4  # 2 rows x 2 columns

    def test_anchor_columns(self, test_organization, test_base_uri, execution_statistics):
        """Anchor columns generate entity URIs and property triples."""
        columns = [
            _make_column("id", is_anchor=True, arkumu_type="identifier"),
            _make_column("title"),
        ]
        processor, ds_config, context, _ = self._setup_processor(
            test_organization, test_base_uri, execution_statistics, columns
        )

        csv_data = [
            {"id": "A001", "title": "First"},
            {"id": "A002", "title": "Second"},
        ]
        entities = processor._process_dataset_chunk_with_entities(ds_config, csv_data, context)

        assert len(entities) == 2
        dc = context.dataset_counters["test_dataset"]
        assert dc["props_anchor"] == 2
        assert dc["props_regular"] == 2

    def test_multi_value_columns(self, test_organization, test_base_uri, execution_statistics):
        """Multi-value columns split values and create individual triples."""
        columns = [
            _make_column("name"),
            _make_column("skills", is_multi_value=True, separator=","),
        ]
        processor, ds_config, context, _ = self._setup_processor(
            test_organization, test_base_uri, execution_statistics, columns
        )

        csv_data = [
            {"name": "Alice", "skills": "Python,Java,SQL"},
            {"name": "Bob", "skills": "Go"},
        ]
        entities = processor._process_dataset_chunk_with_entities(ds_config, csv_data, context)

        assert len(entities) == 2
        dc = context.dataset_counters["test_dataset"]
        assert dc["props_multi_items"] == 4  # 3 for Alice + 1 for Bob
        assert dc["props_multi_cells"] == 2  # Both rows had multi-value data
        assert dc["props_regular"] == 2  # name column

    def test_empty_chunk(self, test_organization, test_base_uri, execution_statistics):
        """Empty CSV data returns empty list without errors."""
        columns = [_make_column("name")]
        processor, ds_config, context, _ = self._setup_processor(
            test_organization, test_base_uri, execution_statistics, columns
        )

        result = processor._process_dataset_chunk_with_entities(ds_config, [], context)
        assert result == []

    def test_missing_values_skipped(self, test_organization, test_base_uri, execution_statistics):
        """Rows with empty/missing values don't create property triples for those columns."""
        columns = [
            _make_column("name"),
            _make_column("age"),
        ]
        processor, ds_config, context, _ = self._setup_processor(
            test_organization, test_base_uri, execution_statistics, columns
        )

        csv_data = [
            {"name": "Alice", "age": "30"},
            {"name": "", "age": "25"},   # empty name
            {"name": "Charlie", "age": ""},  # empty age
        ]
        entities = processor._process_dataset_chunk_with_entities(ds_config, csv_data, context)

        assert len(entities) == 3
        dc = context.dataset_counters["test_dataset"]
        # 2 valid names + 2 valid ages = 4 regular props
        assert dc["props_regular"] == 4

    def test_rdf_type_triples_created(self, test_organization, test_base_uri, execution_statistics):
        """Each entity gets an rdf:type triple linked to the blueprint entity type."""
        columns = [_make_column("name")]
        processor, ds_config, context, entity_type = self._setup_processor(
            test_organization, test_base_uri, execution_statistics, columns
        )

        csv_data = [
            {"name": "Alice"},
            {"name": "Bob"},
        ]
        entities = processor._process_dataset_chunk_with_entities(ds_config, csv_data, context)

        # Verify rdf:type triples exist in DB
        rdf_type_uri = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
        rdf_type_prop = Resource.objects.filter(uri=rdf_type_uri).first()
        assert rdf_type_prop is not None

        rdf_type_triples = Triple.objects.filter(
            predicate=rdf_type_prop,
            object=entity_type,
        )
        assert rdf_type_triples.count() == 2

    def test_entity_cache_populated(self, test_organization, test_base_uri, execution_statistics):
        """Entity cache in context is populated with all created entities."""
        columns = [_make_column("name")]
        processor, ds_config, context, _ = self._setup_processor(
            test_organization, test_base_uri, execution_statistics, columns
        )

        csv_data = [{"name": "Alice"}, {"name": "Bob"}, {"name": "Charlie"}]
        entities = processor._process_dataset_chunk_with_entities(ds_config, csv_data, context)

        assert len(context.entity_cache) == 3
        for entity in entities:
            assert entity.uri in context.entity_cache
            assert context.entity_cache[entity.uri] is entity

    def test_statistics_accuracy(self, test_organization, test_base_uri, execution_statistics):
        """Verify metrics are tracked correctly across the two phases."""
        columns = [
            _make_column("name"),
            _make_column("tags", is_multi_value=True, separator=","),
        ]
        processor, ds_config, context, _ = self._setup_processor(
            test_organization, test_base_uri, execution_statistics, columns
        )

        csv_data = [
            {"name": "Alice", "tags": "a,b,c"},
            {"name": "Bob", "tags": "d"},
        ]
        processor._process_dataset_chunk_with_entities(ds_config, csv_data, context)

        metrics = execution_statistics.current_metrics
        assert metrics.rows_processed == 2
        assert metrics.multi_value_items_created == 4  # a, b, c, d
        assert metrics.multi_value_cells_split == 2

    def test_fk_relationships_queued(self, test_organization, test_base_uri, execution_statistics):
        """FK columns queue relationships without creating triples during chunk processing."""
        fk_col = _make_column("dept_id", col_type=ColumnType.FOREIGN_KEY)
        fk_col.fk_config = {"target_dataset": "departments", "target_column": "id"}
        columns = [
            _make_column("name"),
            fk_col,
        ]
        processor, ds_config, context, _ = self._setup_processor(
            test_organization, test_base_uri, execution_statistics, columns
        )

        csv_data = [
            {"name": "Alice", "dept_id": "D1"},
            {"name": "Bob", "dept_id": "D2"},
        ]
        processor._process_dataset_chunk_with_entities(ds_config, csv_data, context)

        # FK relationships should be queued, not resolved
        assert len(processor.pending_relationships) == 2

    def test_duplicate_entity_uris_in_chunk(self, test_organization, test_base_uri, execution_statistics):
        """Duplicate entity URIs within a chunk are deduplicated by the bulk method."""
        columns = [
            _make_column("id", is_anchor=True),
            _make_column("value"),
        ]
        processor, ds_config, context, _ = self._setup_processor(
            test_organization, test_base_uri, execution_statistics, columns
        )

        # Two rows that produce the same entity URI
        csv_data = [
            {"id": "SAME", "value": "first"},
            {"id": "SAME", "value": "second"},
        ]
        entities = processor._process_dataset_chunk_with_entities(ds_config, csv_data, context)

        # Both rows produce entities but the bulk method deduplicates the Resource
        assert len(entities) == 2
        # Only 1 unique entity in DB
        entity_uris = {e.uri for e in entities}
        assert len(entity_uris) == 1

    def test_mixed_column_types(self, test_organization, test_base_uri, execution_statistics):
        """Chunk with regular, anchor, and multi-value columns all processed correctly."""
        columns = [
            _make_column("id", is_anchor=True, arkumu_type="identifier"),
            _make_column("name"),
            _make_column("skills", is_multi_value=True, separator=","),
        ]
        processor, ds_config, context, _ = self._setup_processor(
            test_organization, test_base_uri, execution_statistics, columns
        )

        csv_data = [
            {"id": "P1", "name": "Alice", "skills": "Python,Java"},
            {"id": "P2", "name": "Bob", "skills": "Go"},
        ]
        entities = processor._process_dataset_chunk_with_entities(ds_config, csv_data, context)

        assert len(entities) == 2
        dc = context.dataset_counters["test_dataset"]
        assert dc["props_anchor"] == 2
        assert dc["props_regular"] == 2
        assert dc["props_multi_items"] == 3  # Python, Java, Go

    def test_large_chunk(self, test_organization, test_base_uri, execution_statistics):
        """Processing a large chunk (500 rows) works correctly with bulk operations."""
        columns = [
            _make_column("id", is_anchor=True),
            _make_column("value"),
        ]
        processor, ds_config, context, _ = self._setup_processor(
            test_organization, test_base_uri, execution_statistics, columns
        )

        csv_data = [{"id": str(i), "value": f"val_{i}"} for i in range(500)]
        entities = processor._process_dataset_chunk_with_entities(ds_config, csv_data, context)

        assert len(entities) == 500
        dc = context.dataset_counters["test_dataset"]
        assert dc["rows"] == 500
        assert dc["props_anchor"] == 500
        assert dc["props_regular"] == 500

    def test_no_blueprint_skips_rdf_type(self, test_organization, test_base_uri, execution_statistics):
        """When no blueprint exists for a dataset, rdf:type triples are skipped."""
        columns = [_make_column("name")]
        processor, ds_config, context, _ = self._setup_processor(
            test_organization, test_base_uri, execution_statistics, columns
        )
        # Clear blueprints
        processor.dataset_blueprints = {}

        csv_data = [{"name": "Alice"}]
        entities = processor._process_dataset_chunk_with_entities(ds_config, csv_data, context)

        assert len(entities) == 1
        # No rdf:type property resource should be created
        rdf_type_uri = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
        rdf_type_prop = Resource.objects.filter(uri=rdf_type_uri).first()
        if rdf_type_prop:
            rdf_triples = Triple.objects.filter(predicate=rdf_type_prop)
            assert rdf_triples.count() == 0

    def test_property_triples_in_database(self, test_organization, test_base_uri, execution_statistics):
        """Verify that property triples are actually persisted to the database."""
        columns = [
            _make_column("title", arkumu_type="title"),
        ]
        processor, ds_config, context, _ = self._setup_processor(
            test_organization, test_base_uri, execution_statistics, columns
        )

        csv_data = [
            {"title": "Hello World"},
        ]
        entities = processor._process_dataset_chunk_with_entities(ds_config, csv_data, context)
        entity = entities[0]

        # Find the property resource
        prop_uri = processor._generate_property_uri("title")
        prop_resource = Resource.objects.filter(uri=prop_uri).first()
        assert prop_resource is not None

        # Verify triple exists
        triple = Triple.objects.filter(
            subject=entity,
            predicate=prop_resource,
        ).first()
        assert triple is not None
        assert triple.object.value == "Hello World"
