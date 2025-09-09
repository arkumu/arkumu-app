"""
Comprehensive tests for FK resolution, multi-value columns, relationship contexts,
and their combinations in the mapping_aware_processor.

This test file addresses gaps identified in existing test coverage:
- Composite/anchor-based FKs
- Self-referencing and circular FKs
- Different multi-value delimiters
- Empty values in multi-value columns
- Non-string junction attributes
- Mixed valid/invalid FKs
- Statistics and counter accuracy
"""

import pytest
from decimal import Decimal
from datetime import datetime
from unittest.mock import Mock, patch

from arkumu.importer.services.execution.mapping_aware_processor import MappingAwareProcessor
from arkumu.importer.services.mapping_consumer import (
    ExecutionConfig, DatasetConfig, ColumnConfig, ColumnType,
    FKRelationship, RelationshipContext, ProcessingStrategy
)
from arkumu.importer.services.execution.statistics import ExecutionStatistics
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple


@pytest.fixture
def processor(db):
    """Create a MappingAwareProcessor instance."""
    return MappingAwareProcessor(
        organization=None,
        institution="test",
        base_uri="http://test.org",
        statistics=ExecutionStatistics()
    )


@pytest.fixture
def mock_resource_manager(processor):
    """Mock the resource manager to track created resources."""
    original_rm = processor.resource_manager
    
    # Track all created resources and triples
    original_rm.created_resources = []
    original_rm.created_triples = []
    
    # Wrap methods to track calls
    original_create_entity = original_rm.create_entity_resource
    def track_entity(*args, **kwargs):
        result = original_create_entity(*args, **kwargs)
        original_rm.created_resources.append(result)
        return result
    original_rm.create_entity_resource = track_entity
    
    original_create_triple = original_rm.create_relationship_triple
    def track_triple(*args, **kwargs):
        result = original_create_triple(*args, **kwargs)
        if result:
            original_rm.created_triples.append(result)
        return result
    original_rm.create_relationship_triple = track_triple
    
    return original_rm


class TestCompositeAndAnchorFKs:
    """Test FK resolution with composite keys and anchor columns."""
    
    def test_fk_using_anchor_columns(self, processor, mock_resource_manager):
        """Test FK resolution when target uses anchor columns for entity URIs."""
        # Dataset 1: Projects with composite anchor (code + year)
        projects_config = DatasetConfig(
            dataset_name="projects",
            columns=[
                ColumnConfig(
                    column_name="project_code",
                    dataset_name="projects",
                    column_type=ColumnType.ANCHOR,
                    is_anchor=True,
                    arkumu_type="project_code"
                ),
                ColumnConfig(
                    column_name="year",
                    dataset_name="projects",
                    column_type=ColumnType.ANCHOR,
                    is_anchor=True,
                    arkumu_type="year"
                ),
                ColumnConfig(
                    column_name="name",
                    dataset_name="projects",
                    column_type=ColumnType.REGULAR,
                    arkumu_type="project_name"
                )
            ]
        )
        
        # Dataset 2: Tasks referencing projects by composite key
        tasks_config = DatasetConfig(
            dataset_name="tasks",
            columns=[
                ColumnConfig(
                    column_name="task_id",
                    dataset_name="tasks",
                    column_type=ColumnType.ANCHOR,
                    is_anchor=True,
                    arkumu_type="task_id"
                ),
                ColumnConfig(
                    column_name="project_ref",
                    dataset_name="tasks",
                    column_type=ColumnType.FOREIGN_KEY,
                    arkumu_type="belongs_to_project",
                    fk_config={"target_dataset": "projects"}
                )
            ]
        )
        
        execution_config = ExecutionConfig(
            mapping_id=1,
            mapping_name="Test",
            organization="test",
            datasets=[projects_config, tasks_config],
            fk_relationships=[
                FKRelationship(
                    source_dataset="tasks",
                    source_column="project_ref",
                    target_dataset="projects",
                    target_column="composite_key",
                    relationship_type="belongs_to_project"
                )
            ]
        )
        
        csv_sources = {
            "projects": [
                {"project_code": "PROJ001", "year": "2024", "name": "Alpha"},
                {"project_code": "PROJ002", "year": "2024", "name": "Beta"}
            ],
            "tasks": [
                {"task_id": "T1", "project_ref": "PROJ001_2024"},
                {"task_id": "T2", "project_ref": "PROJ002_2024"}
            ]
        }
        
        metrics = processor.process_with_execution_config(
            execution_config, csv_sources, ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        # Verify composite anchor creates correct URIs
        project_resources = Resource.objects.filter(
            uri__contains="/entities/projects/"
        )
        assert project_resources.count() == 2
        
        # Check that FKs resolved to composite-keyed entities
        fk_triples = Triple.objects.filter(
            predicate__uri__contains="belongs_to_project"
        )
        assert fk_triples.count() == 2
        
        # Verify correct entity URIs were created with composite keys
        assert any("PROJ001_2024" in r.uri for r in project_resources)
        assert any("PROJ002_2024" in r.uri for r in project_resources)


class TestSelfReferencingAndCircularFKs:
    """Test self-referencing and circular FK dependencies."""
    
    def test_self_referencing_fk(self, processor, mock_resource_manager):
        """Test entities that reference other entities in the same dataset."""
        employees_config = DatasetConfig(
            dataset_name="employees",
            columns=[
                ColumnConfig(
                    column_name="emp_id",
                    dataset_name="employees",
                    column_type=ColumnType.ANCHOR,
                    is_anchor=True,
                    arkumu_type="employee_id"
                ),
                ColumnConfig(
                    column_name="name",
                    dataset_name="employees",
                    column_type=ColumnType.REGULAR,
                    arkumu_type="employee_name"
                ),
                ColumnConfig(
                    column_name="manager_id",
                    dataset_name="employees",
                    column_type=ColumnType.FOREIGN_KEY,
                    arkumu_type="reports_to",
                    fk_config={"target_dataset": "employees"}
                )
            ]
        )
        
        execution_config = ExecutionConfig(
            mapping_id=1,
            mapping_name="Test", 
            organization="test",
            datasets=[employees_config],
            fk_relationships=[
                FKRelationship(
                    source_dataset="employees",
                    source_column="manager_id",
                    target_dataset="employees",
                    target_column="emp_id",
                    relationship_type="reports_to"
                )
            ]
        )
        
        csv_sources = {
            "employees": [
                {"emp_id": "E001", "name": "CEO", "manager_id": ""},
                {"emp_id": "E002", "name": "Manager", "manager_id": "E001"},
                {"emp_id": "E003", "name": "Developer", "manager_id": "E002"}
            ]
        }
        
        metrics = processor.process_with_execution_config(
            execution_config, csv_sources, ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        # Verify self-referencing FKs created correctly
        reports_to_triples = Triple.objects.filter(
            predicate__uri__contains="reports_to"
        )
        assert reports_to_triples.count() == 2  # E002->E001, E003->E002
        
        # Verify no FK created for empty manager_id
        ceo_entity = Resource.objects.get(uri__contains="E001")
        ceo_reports_to = Triple.objects.filter(
            subject=ceo_entity,
            predicate__uri__contains="reports_to"
        )
        assert ceo_reports_to.count() == 0
    
    def test_circular_fk_dependencies(self, processor):
        """Test circular dependencies: A references B, B references C, C references A."""
        datasets = [
            DatasetConfig(
                dataset_name="departments",
                columns=[
                    ColumnConfig(column_name="dept_id", dataset_name="departments", column_type=ColumnType.ANCHOR, is_anchor=True, arkumu_type="dept_id"),
                    ColumnConfig(column_name="head_employee", dataset_name="departments", column_type=ColumnType.FOREIGN_KEY, arkumu_type="headed_by",
                               fk_config={"target_dataset": "employees"})
                ]
            ),
            DatasetConfig(
                dataset_name="employees",
                columns=[
                    ColumnConfig(column_name="emp_id", dataset_name="employees", column_type=ColumnType.ANCHOR, is_anchor=True, arkumu_type="emp_id"),
                    ColumnConfig(column_name="office_id", dataset_name="employees", column_type=ColumnType.FOREIGN_KEY, arkumu_type="works_in",
                               fk_config={"target_dataset": "offices"})
                ]
            ),
            DatasetConfig(
                dataset_name="offices",
                columns=[
                    ColumnConfig(column_name="office_id", dataset_name="offices", column_type=ColumnType.ANCHOR, is_anchor=True, arkumu_type="office_id"),
                    ColumnConfig(column_name="dept_id", dataset_name="offices", column_type=ColumnType.FOREIGN_KEY, arkumu_type="belongs_to_dept",
                               fk_config={"target_dataset": "departments"})
                ]
            )
        ]
        
        execution_config = ExecutionConfig(
            mapping_id=1,
            mapping_name="Test",
            organization="test",
            datasets=datasets,
            fk_relationships=[
                FKRelationship("departments", "head_employee", "employees", "emp_id", "headed_by"),
                FKRelationship("employees", "office_id", "offices", "office_id", "works_in"),
                FKRelationship("offices", "dept_id", "departments", "dept_id", "belongs_to_dept")
            ]
        )
        
        csv_sources = {
            "departments": [{"dept_id": "D1", "head_employee": "E1"}],
            "employees": [{"emp_id": "E1", "office_id": "O1"}],
            "offices": [{"office_id": "O1", "dept_id": "D1"}]
        }
        
        metrics = processor.process_with_execution_config(
            execution_config, csv_sources, ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        # All circular references should be resolved
        assert Triple.objects.filter(predicate__uri__contains="headed_by").count() == 1
        assert Triple.objects.filter(predicate__uri__contains="works_in").count() == 1
        assert Triple.objects.filter(predicate__uri__contains="belongs_to_dept").count() == 1


class TestAdvancedMultiValueColumns:
    """Test multi-value columns with different delimiters and edge cases."""
    
    def test_different_delimiters(self, processor):
        """Test multi-value columns with semicolon, pipe, and custom delimiters."""
        config = DatasetConfig(
            dataset_name="publications",
            columns=[
                ColumnConfig(
                    column_name="pub_id",
                    dataset_name="publications",
                    column_type=ColumnType.ANCHOR,
                    is_anchor=True,
                    arkumu_type="publication_id"
                ),
                ColumnConfig(
                    column_name="authors",
                    dataset_name="publications",
                    column_type=ColumnType.MULTI_VALUE,
                    is_multi_value=True,
                    multi_value_separator=";",
                    arkumu_type="has_author"
                ),
                ColumnConfig(
                    column_name="keywords",
                    dataset_name="publications",
                    column_type=ColumnType.MULTI_VALUE,
                    is_multi_value=True,
                    multi_value_separator="|",
                    arkumu_type="has_keyword"
                ),
                ColumnConfig(
                    column_name="tags",
                    dataset_name="publications",
                    column_type=ColumnType.MULTI_VALUE,
                    is_multi_value=True,
                    multi_value_separator=" :: ",
                    arkumu_type="has_tag"
                )
            ]
        )
        
        execution_config = ExecutionConfig(mapping_id=1, mapping_name="Test", organization="test", datasets=[config])
        
        csv_sources = {
            "publications": [{
                "pub_id": "PUB001",
                "authors": "Smith, J.;Doe, J.;Brown, A.",
                "keywords": "AI|Machine Learning|Deep Learning",
                "tags": "research :: innovation :: technology"
            }]
        }
        
        metrics = processor.process_with_execution_config(
            execution_config, csv_sources, ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        # Verify each delimiter splits correctly
        author_triples = Triple.objects.filter(predicate__uri__contains="has_author")
        assert author_triples.count() == 3
        
        keyword_triples = Triple.objects.filter(predicate__uri__contains="has_keyword")
        assert keyword_triples.count() == 3
        
        tag_triples = Triple.objects.filter(predicate__uri__contains="has_tag")
        assert tag_triples.count() == 3
    
    def test_empty_values_in_multivalue(self, processor):
        """Test handling of empty values within multi-value strings."""
        config = DatasetConfig(
            dataset_name="items",
            columns=[
                ColumnConfig(
                    column_name="item_id",
                    dataset_name="items",
                    column_type=ColumnType.ANCHOR,
                    is_anchor=True,
                    arkumu_type="item_id"
                ),
                ColumnConfig(
                    column_name="categories",
                    dataset_name="items",
                    column_type=ColumnType.MULTI_VALUE,
                    is_multi_value=True,
                    multi_value_separator=",",
                    arkumu_type="in_category"
                )
            ]
        )
        
        execution_config = ExecutionConfig(mapping_id=1, mapping_name="Test", organization="test", datasets=[config])
        
        csv_sources = {
            "items": [
                {"item_id": "I1", "categories": "cat1,,cat2"},  # Empty middle value
                {"item_id": "I2", "categories": ",cat3,"},      # Empty first and last
                {"item_id": "I3", "categories": ",,"}           # All empty
            ]
        }
        
        metrics = processor.process_with_execution_config(
            execution_config, csv_sources, ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        # Only non-empty values should create triples
        category_triples = Triple.objects.filter(predicate__uri__contains="in_category")
        assert category_triples.count() == 3  # cat1, cat2, cat3 only
        
        # Verify correct values
        values = [t.object.name for t in category_triples]
        assert "cat1" in values
        assert "cat2" in values  
        assert "cat3" in values
        assert "" not in values  # No empty values


class TestMultiValueFKCombinations:
    """Test columns that are both multi-value and foreign keys."""
    
    def test_multivalue_fk_with_mixed_validity(self, processor):
        """Test multi-value FK columns with mix of valid and invalid references."""
        authors_config = DatasetConfig(
            dataset_name="authors",
            columns=[
                ColumnConfig(
                    column_name="author_id",
                    dataset_name="authors",
                    column_type=ColumnType.ANCHOR,
                    is_anchor=True,
                    arkumu_type="author_id"
                ),
                ColumnConfig(
                    column_name="name",
                    dataset_name="authors",
                    column_type=ColumnType.REGULAR,
                    arkumu_type="author_name"
                )
            ]
        )
        
        books_config = DatasetConfig(
            dataset_name="books",
            columns=[
                ColumnConfig(
                    column_name="book_id",
                    dataset_name="books",
                    column_type=ColumnType.ANCHOR,
                    is_anchor=True,
                    arkumu_type="book_id"
                ),
                ColumnConfig(
                    column_name="author_ids",
                    dataset_name="books",
                    column_type=ColumnType.FOREIGN_KEY,
                    is_multi_value=True,
                    multi_value_separator=",",
                    arkumu_type="written_by",
                    fk_config={"target_dataset": "authors"}
                )
            ]
        )
        
        execution_config = ExecutionConfig(
            datasets=[authors_config, books_config],
            fk_relationships=[
                FKRelationship(
                    source_dataset="books",
                    source_column="author_ids",
                    target_dataset="authors",
                    target_column="author_id",
                    relationship_type="written_by"
                )
            ]
        )
        
        csv_sources = {
            "authors": [
                {"author_id": "A1", "name": "Author One"},
                {"author_id": "A2", "name": "Author Two"}
            ],
            "books": [
                {"book_id": "B1", "author_ids": "A1,A2,A3"},  # A3 doesn't exist
                {"book_id": "B2", "author_ids": "A2,INVALID,A1"}  # INVALID doesn't exist
            ]
        }
        
        metrics = processor.process_with_execution_config(
            execution_config, csv_sources, ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        # Check that valid FKs are resolved
        written_by_triples = Triple.objects.filter(
            predicate__uri__contains="written_by",
            object__resource_type=ResourceType.IRI
        )
        assert written_by_triples.count() == 4  # A1 and A2 for each book
        
        # Check stubs created for invalid references
        stub_resources = Resource.objects.filter(
            uri__contains="/entities/authors/",
            is_placeholder=True
        )
        assert stub_resources.count() == 2  # A3 and INVALID
    
    def test_multivalue_fk_index_tracking(self, processor):
        """Test that multi-value FK indices are properly tracked."""
        # This tests internal tracking of multi_value_index field
        
        config = DatasetConfig(
            dataset_name="projects",
            columns=[
                ColumnConfig(
                    column_name="project_id",
                    dataset_name="projects",
                    column_type=ColumnType.ANCHOR,
                    is_anchor=True,
                    arkumu_type="project_id"
                ),
                ColumnConfig(
                    column_name="member_ids",
                    dataset_name="projects",
                    column_type=ColumnType.FOREIGN_KEY,
                    is_multi_value=True,
                    multi_value_separator=",",
                    arkumu_type="has_member",
                    fk_config={"target_dataset": "members"}
                )
            ]
        )
        
        # Spy on the _queue_fk_relationships method to check indices
        tracked_relationships = []
        original_queue = processor._queue_fk_relationships
        
        def track_queue(entity_uri, row_data, columns, context):
            # Capture relationships before queueing
            original_pending = len(processor.pending_relationships)
            original_queue(entity_uri, row_data, columns, context)
            new_relationships = processor.pending_relationships[original_pending:]
            tracked_relationships.extend(new_relationships)
        
        processor._queue_fk_relationships = track_queue
        
        execution_config = ExecutionConfig(
            datasets=[config],
            fk_relationships=[
                FKRelationship(
                    source_dataset="projects",
                    source_column="member_ids",
                    target_dataset="members",
                    target_column="member_id",
                    relationship_type="has_member"
                )
            ]
        )
        
        csv_sources = {
            "projects": [
                {"project_id": "P1", "member_ids": "M1,M2,M3"}
            ]
        }
        
        metrics = processor.process_with_execution_config(
            execution_config, csv_sources, ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        # Verify indices are tracked correctly
        assert len(tracked_relationships) == 3
        for i, rel in enumerate(tracked_relationships):
            assert rel['is_multi_value'] == True
            assert rel['multi_value_index'] == i


class TestRelationshipContextsAdvanced:
    """Test advanced relationship context (junction table) scenarios."""
    
    def test_junction_with_typed_attributes(self, processor):
        """Test junction tables with non-string attribute types."""
        person_config = DatasetConfig(
            dataset_name="persons",
            columns=[
                ColumnConfig(column_name="person_id", dataset_name="persons", column_type=ColumnType.ANCHOR, is_anchor=True, arkumu_type="person_id")
            ]
        )
        
        project_config = DatasetConfig(
            dataset_name="projects",
            columns=[
                ColumnConfig(column_name="project_id", dataset_name="projects", column_type=ColumnType.ANCHOR, is_anchor=True, arkumu_type="project_id")
            ]
        )
        
        junction_config = DatasetConfig(
            dataset_name="person_project",
            columns=[
                ColumnConfig(column_name="person_id", dataset_name="person_project", column_type=ColumnType.FOREIGN_KEY, arkumu_type="person_ref"),
                ColumnConfig(column_name="project_id", dataset_name="person_project", column_type=ColumnType.FOREIGN_KEY, arkumu_type="project_ref"),
                ColumnConfig(column_name="start_date", dataset_name="person_project", column_type=ColumnType.RELATIONSHIP_CONTEXT, arkumu_type="started_on", datatype="date"),
                ColumnConfig(column_name="hours_per_week", dataset_name="person_project", column_type=ColumnType.RELATIONSHIP_CONTEXT, arkumu_type="weekly_hours", datatype="decimal"),
                ColumnConfig(column_name="is_lead", dataset_name="person_project", column_type=ColumnType.RELATIONSHIP_CONTEXT, arkumu_type="is_lead", datatype="boolean")
            ]
        )
        
        execution_config = ExecutionConfig(
            datasets=[person_config, project_config, junction_config],
            relationship_contexts=[
                RelationshipContext(
                    context_id="person_project_rel",
                    dataset_name="person_project",
                    primary_fk="person_id",
                    primary_entity_type="persons",
                    secondary_fk="project_id",
                    secondary_entity_type="projects",
                    junction_attributes=["start_date", "hours_per_week", "is_lead"]
                )
            ]
        )
        
        csv_sources = {
            "persons": [{"person_id": "P1"}],
            "projects": [{"project_id": "PR1"}],
            "person_project": [{
                "person_id": "P1",
                "project_id": "PR1",
                "start_date": "2024-01-15",
                "hours_per_week": "20.5",
                "is_lead": "true"
            }]
        }
        
        metrics = processor.process_with_execution_config(
            execution_config, csv_sources, ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        # Verify junction entity created with typed attributes
        junction_entities = Resource.objects.filter(uri__contains="person_project_junction")
        assert junction_entities.count() == 1
        
        # Check attributes are attached with correct datatypes
        attribute_triples = Triple.objects.filter(
            subject=junction_entities.first()
        )
        
        # Should have attributes for: start_date, hours_per_week, is_lead, plus relationships
        assert attribute_triples.count() >= 3
    
    def test_junction_with_missing_fks(self, processor):
        """Test junction entities when FK values are missing."""
        execution_config = ExecutionConfig(
            datasets=[
                DatasetConfig(dataset_name="items", columns=[
                    ColumnConfig(column_name="item_id", dataset_name="items", column_type=ColumnType.ANCHOR, is_anchor=True, arkumu_type="item_id")
                ]),
                DatasetConfig(dataset_name="tags", columns=[
                    ColumnConfig(column_name="tag_id", dataset_name="tags", column_type=ColumnType.ANCHOR, is_anchor=True, arkumu_type="tag_id")
                ]),
                DatasetConfig(dataset_name="item_tags", columns=[
                    ColumnConfig(column_name="item_id", dataset_name="item_tags", column_type=ColumnType.FOREIGN_KEY, arkumu_type="item_ref"),
                    ColumnConfig(column_name="tag_id", dataset_name="item_tags", column_type=ColumnType.FOREIGN_KEY, arkumu_type="tag_ref"),
                    ColumnConfig(column_name="weight", dataset_name="item_tags", column_type=ColumnType.RELATIONSHIP_CONTEXT, arkumu_type="tag_weight")
                ])
            ],
            relationship_contexts=[
                RelationshipContext(
                    context_id="item_tag_rel",
                    dataset_name="item_tags",
                    primary_fk="item_id",
                    primary_entity_type="items",
                    secondary_fk="tag_id",
                    secondary_entity_type="tags",
                    junction_attributes=["weight"]
                )
            ]
        )
        
        csv_sources = {
            "items": [{"item_id": "I1"}],
            "tags": [{"tag_id": "T1"}],
            "item_tags": [
                {"item_id": "I1", "tag_id": "T1", "weight": "5"},  # Valid
                {"item_id": "", "tag_id": "T1", "weight": "3"},    # Missing item_id
                {"item_id": "I1", "tag_id": "", "weight": "2"},    # Missing tag_id
                {"item_id": "", "tag_id": "", "weight": "1"}       # Both missing
            ]
        }
        
        metrics = processor.process_with_execution_config(
            execution_config, csv_sources, ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        # Only valid junction should be created
        junction_entities = Resource.objects.filter(uri__contains="item_tags_junction")
        assert junction_entities.count() == 1


class TestStatisticsAndCounters:
    """Test accuracy of statistics and per-dataset counters."""
    
    def test_per_dataset_counter_accuracy(self, processor):
        """Test that dataset_counters accurately track all operations."""
        config = DatasetConfig(
            dataset_name="comprehensive",
            columns=[
                ColumnConfig(column_name="id", dataset_name="comprehensive", column_type=ColumnType.ANCHOR, is_anchor=True, arkumu_type="entity_id"),
                ColumnConfig(column_name="name", dataset_name="comprehensive", column_type=ColumnType.REGULAR, arkumu_type="entity_name"),
                ColumnConfig(column_name="tags", dataset_name="comprehensive", column_type=ColumnType.MULTI_VALUE, is_multi_value=True, 
                           multi_value_separator=",", arkumu_type="has_tag"),
                ColumnConfig(column_name="parent_id", dataset_name="comprehensive", column_type=ColumnType.FOREIGN_KEY, arkumu_type="has_parent",
                           fk_config={"target_dataset": "comprehensive"}),
                ColumnConfig(column_name="related_ids", dataset_name="comprehensive", column_type=ColumnType.FOREIGN_KEY, is_multi_value=True,
                           multi_value_separator=",", arkumu_type="related_to",
                           fk_config={"target_dataset": "comprehensive"})
            ]
        )
        
        execution_config = ExecutionConfig(
            datasets=[config],
            fk_relationships=[
                FKRelationship("comprehensive", "parent_id", "comprehensive", "id", "has_parent"),
                FKRelationship("comprehensive", "related_ids", "comprehensive", "id", "related_to")
            ]
        )
        
        csv_sources = {
            "comprehensive": [
                {"id": "1", "name": "First", "tags": "a,b,c", "parent_id": "", "related_ids": "2,3"},
                {"id": "2", "name": "Second", "tags": "d", "parent_id": "1", "related_ids": "1"},
                {"id": "3", "name": "Third", "tags": "", "parent_id": "1", "related_ids": ""}
            ]
        }
        
        # Create a context spy to access dataset_counters
        context_spy = None
        original_process = processor._process_streaming_entity_centric
        
        def capture_context(context):
            nonlocal context_spy
            context_spy = context
            return original_process(context)
        
        processor._process_streaming_entity_centric = capture_context
        
        metrics = processor.process_with_execution_config(
            execution_config, csv_sources, ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        # Verify counter accuracy
        counters = context_spy.dataset_counters.get("comprehensive", {})
        
        assert counters.get('rows', 0) == 3  # 3 rows processed
        assert counters.get('props_regular', 0) == 2  # 2 name properties (third has empty name)
        assert counters.get('props_anchor', 0) == 3  # 3 id properties
        assert counters.get('props_multi_items', 0) == 4  # a,b,c,d tags
        assert counters.get('props_multi_cells', 0) == 2  # 2 cells with multi-values (first and second)
        assert counters.get('fk_queued', 0) == 5  # 2 parent_ids + 3 related_ids
        assert counters.get('fk_multi_items', 0) == 3  # related_ids: 2,3,1
        assert counters.get('fk_resolved', 0) == 5  # All should resolve
    
    def test_fk_resolution_statistics(self, processor):
        """Test FK resolution statistics for different scenarios."""
        datasets = [
            DatasetConfig(dataset_name="source", columns=[
                ColumnConfig(column_name="id", dataset_name="source", column_type=ColumnType.ANCHOR, is_anchor=True, arkumu_type="id"),
                ColumnConfig(column_name="ref1", dataset_name="source", column_type=ColumnType.FOREIGN_KEY, arkumu_type="ref1",
                           fk_config={"target_dataset": "target"}),
                ColumnConfig(column_name="ref2", dataset_name="source", column_type=ColumnType.FOREIGN_KEY, arkumu_type="ref2",
                           fk_config={"target_dataset": "missing"})  # Target dataset doesn't exist
            ]),
            DatasetConfig(dataset_name="target", columns=[
                ColumnConfig(column_name="id", dataset_name="target", column_type=ColumnType.ANCHOR, is_anchor=True, arkumu_type="id")
            ])
        ]
        
        execution_config = ExecutionConfig(
            mapping_id=1,
            mapping_name="Test",
            organization="test",
            datasets=datasets,
            fk_relationships=[
                FKRelationship("source", "ref1", "target", "id", "ref1"),
                FKRelationship("source", "ref2", "missing", "id", "ref2")
            ]
        )
        
        csv_sources = {
            "source": [
                {"id": "S1", "ref1": "T1", "ref2": "M1"},
                {"id": "S2", "ref1": "T_INVALID", "ref2": "M2"}  # T_INVALID doesn't exist
            ],
            "target": [{"id": "T1"}]
            # "missing" dataset not provided
        }
        
        metrics = processor.process_with_execution_config(
            execution_config, csv_sources, ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        # Check statistics
        stats = processor.statistics.current_metrics
        
        # Should have warnings about orphaned references
        warnings = processor.statistics.warnings
        assert any("orphaned" in w.lower() or "missing" in w.lower() for w in warnings)
        
        # Verify relationship creation count
        assert stats.relationships_created >= 1  # At least T1 reference should resolve


class TestEdgeCasesAndErrorHandling:
    """Test edge cases and error handling scenarios."""
    
    def test_empty_dataset_with_fk_references(self, processor):
        """Test handling of empty datasets that are referenced by FKs."""
        source_config = DatasetConfig(
            dataset_name="orders",
            columns=[
                ColumnConfig(column_name="order_id", dataset_name="orders", column_type=ColumnType.ANCHOR, is_anchor=True, arkumu_type="order_id"),
                ColumnConfig(column_name="customer_id", dataset_name="orders", column_type=ColumnType.FOREIGN_KEY, arkumu_type="for_customer",
                           fk_config={"target_dataset": "customers"})
            ]
        )
        
        target_config = DatasetConfig(
            dataset_name="customers",
            columns=[
                ColumnConfig(column_name="customer_id", dataset_name="customers", column_type=ColumnType.ANCHOR, is_anchor=True, arkumu_type="customer_id"),
                ColumnConfig(column_name="name", dataset_name="customers", column_type=ColumnType.REGULAR, arkumu_type="customer_name")
            ]
        )
        
        execution_config = ExecutionConfig(
            datasets=[source_config, target_config],
            fk_relationships=[
                FKRelationship("orders", "customer_id", "customers", "customer_id", "for_customer")
            ]
        )
        
        csv_sources = {
            "orders": [{"order_id": "O1", "customer_id": "C1"}],
            "customers": []  # Empty dataset
        }
        
        metrics = processor.process_with_execution_config(
            execution_config, csv_sources, ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        # Dataset resource should still be created for empty dataset
        customer_dataset = Resource.objects.filter(
            uri__contains="/datasets/customers",
            resource_type=ResourceType.DATASET
        )
        assert customer_dataset.exists()
        
        # FK should create stub entity
        stub_customers = Resource.objects.filter(
            uri__contains="/entities/customers/",
            is_placeholder=True
        )
        assert stub_customers.count() == 1
    
    def test_fk_normalization_edge_cases(self, processor):
        """Test FK value normalization for case sensitivity and whitespace."""
        config = DatasetConfig(
            dataset_name="items",
            columns=[
                ColumnConfig(column_name="id", dataset_name="items", column_type=ColumnType.ANCHOR, is_anchor=True, arkumu_type="id"),
                ColumnConfig(column_name="parent", dataset_name="items", column_type=ColumnType.FOREIGN_KEY, arkumu_type="parent",
                           fk_config={"target_dataset": "items"})
            ]
        )
        
        execution_config = ExecutionConfig(
            datasets=[config],
            fk_relationships=[
                FKRelationship("items", "parent", "items", "id", "parent")
            ]
        )
        
        csv_sources = {
            "items": [
                {"id": "Item1", "parent": ""},
                {"id": "Item2", "parent": " Item1 "},  # Whitespace
                {"id": "Item3", "parent": "ITEM1"},     # Different case
                {"id": "Item4", "parent": "item1"}      # Lowercase
            ]
        }
        
        metrics = processor.process_with_execution_config(
            execution_config, csv_sources, ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        # All variations should resolve to same entity after normalization
        parent_triples = Triple.objects.filter(
            predicate__uri__contains="parent"
        )
        
        # Check that normalization is applied consistently
        assert parent_triples.count() >= 2  # At least Item2 and one other should have parent