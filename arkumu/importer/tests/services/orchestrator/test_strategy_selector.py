"""
Tests for StrategySelector.

Comprehensive tests for intelligent strategy selection based on data
characteristics, mapping complexity, and system constraints.
"""

import pytest
from unittest.mock import Mock, MagicMock

from arkumu.importer.services.orchestrator.strategy_selector import (
    StrategySelector, ProcessingStrategy, DatasetCharacteristics, StrategyAnalysis
)
from arkumu.importer.services.mapping_consumer import ExecutionConfig, DatasetConfig, ColumnConfig, FKRelationship


class TestStrategySelector:
    """Test suite for StrategySelector class"""

    @pytest.fixture
    def strategy_selector(self):
        """Create a StrategySelector instance"""
        return StrategySelector()

    @pytest.fixture
    def small_execution_config(self):
        """Small execution configuration for testing"""
        dataset_config = Mock(spec=DatasetConfig)
        dataset_config.dataset_name = 'small_dataset'
        dataset_config.columns = []
        dataset_config.dependencies = []
        
        config = Mock(spec=ExecutionConfig)
        config.mapping_id = 1
        config.mapping_name = 'Small Mapping'
        config.datasets = [dataset_config]
        config.column_configurations = []
        config.fk_relationships = []
        
        return config

    @pytest.fixture
    def medium_execution_config(self):
        """Medium-sized execution configuration for testing"""
        dataset_configs = []
        for i in range(3):
            dataset_config = Mock(spec=DatasetConfig)
            dataset_config.dataset_name = f'dataset_{i}'
            dataset_config.columns = []
            dataset_config.dependencies = []
            dataset_configs.append(dataset_config)
        
        # Create some FK relationships
        fk_rel = Mock(spec=FKRelationship)
        fk_rel.source_dataset = 'dataset_1'
        fk_rel.target_dataset = 'dataset_0'
        
        config = Mock(spec=ExecutionConfig)
        config.mapping_id = 2
        config.mapping_name = 'Medium Mapping'
        config.datasets = dataset_configs
        config.column_configurations = []
        config.fk_relationships = [fk_rel]
        
        return config

    @pytest.fixture
    def complex_execution_config(self):
        """Complex execution configuration for testing"""
        dataset_configs = []
        for i in range(5):
            dataset_config = Mock(spec=DatasetConfig)
            dataset_config.dataset_name = f'complex_dataset_{i}'
            dataset_config.columns = []
            dataset_config.dependencies = [f'complex_dataset_{j}' for j in range(i)]
            dataset_configs.append(dataset_config)
        
        # Create multiple FK relationships
        fk_relationships = []
        for i in range(3):
            fk_rel = Mock(spec=FKRelationship)
            fk_rel.source_dataset = f'complex_dataset_{i+1}'
            fk_rel.target_dataset = f'complex_dataset_{i}'
            fk_relationships.append(fk_rel)
        
        config = Mock(spec=ExecutionConfig)
        config.mapping_id = 3
        config.mapping_name = 'Complex Mapping'
        config.datasets = dataset_configs
        config.column_configurations = []
        config.fk_relationships = fk_relationships
        
        return config

    @pytest.fixture
    def small_csv_sources(self):
        """Small CSV data sources"""
        return {
            'small_dataset': [
                ['id', 'name', 'value'],
                ['1', 'Item 1', 'Value 1'],
                ['2', 'Item 2', 'Value 2'],
                ['3', 'Item 3', 'Value 3']
            ]
        }

    @pytest.fixture
    def medium_csv_sources(self):
        """Medium-sized CSV data sources"""
        sources = {}
        for i in range(3):
            data = [['id', 'name', 'data']]
            # Create medium-sized datasets (5000 rows each)
            for j in range(5000):
                data.append([str(j), f'Item {j}', f'Data {j}'])
            sources[f'dataset_{i}'] = data
        return sources

    @pytest.fixture
    def large_csv_sources(self):
        """Large CSV data sources"""
        sources = {}
        for i in range(2):
            data = [['id', 'name', 'data', 'extra1', 'extra2']]
            # Create large datasets (30000 rows each)
            for j in range(30000):
                data.append([str(j), f'Item {j}', f'Data {j}', f'Extra1 {j}', f'Extra2 {j}'])
            sources[f'large_dataset_{i}'] = data
        return sources

    def test_init_default_thresholds(self, strategy_selector):
        """Test StrategySelector initialization with default thresholds"""
        assert strategy_selector.small_dataset_mb == 50
        assert strategy_selector.medium_dataset_mb == 500
        assert strategy_selector.small_dataset_rows == 20000
        assert strategy_selector.medium_dataset_rows == 200000
        assert strategy_selector.high_fk_count == 5
        assert strategy_selector.high_column_count == 20
        assert strategy_selector.high_dependency_depth == 3

    def test_choose_optimal_strategy_small_dataset(self, strategy_selector, small_execution_config, small_csv_sources):
        """Test strategy selection for small dataset returns streaming entity-centric"""
        strategy = strategy_selector.choose_optimal_strategy(small_execution_config, small_csv_sources)
        
        assert strategy == ProcessingStrategy.STREAMING_ENTITY_CENTRIC

    def test_choose_optimal_strategy_medium_dataset(self, strategy_selector, medium_execution_config, medium_csv_sources):
        """Test strategy selection for medium dataset favors streaming"""
        strategy = strategy_selector.choose_optimal_strategy(medium_execution_config, medium_csv_sources)
        
        # Should choose streaming entity-centric or multi-phase for medium-sized data
        assert strategy in [ProcessingStrategy.STREAMING_ENTITY_CENTRIC, ProcessingStrategy.MULTI_PHASE]

    def test_choose_optimal_strategy_large_dataset(self, strategy_selector, complex_execution_config, large_csv_sources):
        """Test strategy selection for large dataset with dependencies favors multi-phase"""
        # Adjust dataset names to match large CSV sources
        for i, dataset in enumerate(complex_execution_config.datasets):
            if i < 2:
                dataset.dataset_name = f'large_dataset_{i}'
            else:
                dataset.dataset_name = f'complex_dataset_{i}'
        
        strategy = strategy_selector.choose_optimal_strategy(complex_execution_config, large_csv_sources)
        
        # Should choose multi-phase for large data with dependencies
        assert strategy in [ProcessingStrategy.MULTI_PHASE, ProcessingStrategy.STREAMING_ENTITY_CENTRIC]

    def test_analyze_all_strategies(self, strategy_selector, medium_execution_config, medium_csv_sources):
        """Test comprehensive strategy analysis"""
        analysis = strategy_selector.analyze_all_strategies(medium_execution_config, medium_csv_sources)
        
        # Verify analysis structure
        assert 'dataset_characteristics' in analysis
        assert 'strategy_analyses' in analysis
        assert 'recommended_strategy' in analysis
        assert 'total_estimated_size_mb' in analysis
        assert 'total_datasets' in analysis
        assert 'complexity_assessment' in analysis
        
        # Verify dataset characteristics
        assert len(analysis['dataset_characteristics']) == 3  # 3 datasets
        for char in analysis['dataset_characteristics']:
            assert 'dataset_name' in char
            assert 'estimated_rows' in char
            assert 'estimated_size_mb' in char
            assert 'complexity_score' in char
        
        # Verify strategy analyses
        assert len(analysis['strategy_analyses']) == 2  # 2 strategies analyzed
        strategy_names = [s['strategy'] for s in analysis['strategy_analyses']]
        assert 'streaming_entity_centric' in strategy_names
        assert 'multi_phase' in strategy_names
        
        # Verify one strategy is recommended
        recommended_count = sum(1 for s in analysis['strategy_analyses'] if s['recommended'])
        assert recommended_count == 1

    def test_get_strategy_rationale_streaming_small(self, strategy_selector, small_execution_config, small_csv_sources):
        """Test strategy rationale for streaming entity-centric selection on small dataset"""
        rationale = strategy_selector.get_strategy_rationale(
            small_execution_config, 
            small_csv_sources, 
            ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        assert "Streaming entity-centric chosen" in rationale
        assert "memory efficiency" in rationale

    def test_get_strategy_rationale_streaming(self, strategy_selector, medium_execution_config, medium_csv_sources):
        """Test strategy rationale for streaming entity-centric selection"""
        rationale = strategy_selector.get_strategy_rationale(
            medium_execution_config, 
            medium_csv_sources, 
            ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        assert "Streaming entity-centric chosen for medium dataset" in rationale
        assert "memory efficiency" in rationale

    def test_get_strategy_rationale_multi_phase(self, strategy_selector, complex_execution_config, large_csv_sources):
        """Test strategy rationale for multi-phase selection"""
        rationale = strategy_selector.get_strategy_rationale(
            complex_execution_config, 
            large_csv_sources, 
            ProcessingStrategy.MULTI_PHASE
        )
        
        assert "Multi-phase chosen for large dataset" in rationale
        assert "dependencies" in rationale or "size" in rationale

    def test_analyze_dataset_characteristics_small(self, strategy_selector, small_execution_config, small_csv_sources):
        """Test dataset characteristics analysis for small dataset"""
        characteristics = strategy_selector._analyze_dataset_characteristics(small_execution_config, small_csv_sources)
        
        assert len(characteristics) == 1
        char = characteristics[0]
        
        assert char.dataset_name == 'small_dataset'
        assert char.estimated_rows == 4  # 4 total rows including header
        assert char.estimated_columns == 3  # 3 columns
        assert char.estimated_size_mb < 1  # Very small
        assert char.has_fk_relationships is False
        assert char.dependency_depth == 0
        assert char.complexity_score < 0.5  # Low complexity

    def test_analyze_dataset_characteristics_with_multi_value_columns(self, strategy_selector, small_execution_config):
        """Test dataset characteristics with multi-value columns"""
        # Mock column with multi-value
        mock_column = Mock(spec=ColumnConfig)
        mock_column.is_multi_value = True
        mock_column.is_external_ontology = False
        
        small_execution_config.datasets[0].columns = [mock_column]
        
        csv_sources = {
            'small_dataset': [
                ['id', 'tags'],
                ['1', 'tag1,tag2,tag3'],
                ['2', 'tag4,tag5']
            ]
        }
        
        characteristics = strategy_selector._analyze_dataset_characteristics(small_execution_config, csv_sources)
        
        assert len(characteristics) == 1
        char = characteristics[0]
        assert char.has_multi_value_columns is True
        assert char.complexity_score >= 0.1  # Should increase complexity

    def test_analyze_dataset_characteristics_with_external_ontology(self, strategy_selector, small_execution_config):
        """Test dataset characteristics with external ontology columns"""
        # Mock column with external ontology
        mock_column = Mock(spec=ColumnConfig)
        mock_column.is_multi_value = False
        mock_column.is_external_ontology = True
        
        small_execution_config.datasets[0].columns = [mock_column]
        
        csv_sources = {
            'small_dataset': [
                ['id', 'orcid'],
                ['1', '0000-0000-0000-0001'],
                ['2', '0000-0000-0000-0002']
            ]
        }
        
        characteristics = strategy_selector._analyze_dataset_characteristics(small_execution_config, csv_sources)
        
        assert len(characteristics) == 1
        char = characteristics[0]
        assert char.has_external_ontologies is True
        assert char.complexity_score >= 0.1  # Should increase complexity

    def test_calculate_complexity_score_low(self, strategy_selector):
        """Test complexity score calculation for low complexity"""
        score = strategy_selector._calculate_complexity_score(
            rows=100,
            columns=5,
            fk_count=0,
            has_multi_value=False,
            has_external_ontology=False,
            dependency_depth=0
        )
        
        assert score == 0.0  # No complexity factors

    def test_calculate_complexity_score_high(self, strategy_selector):
        """Test complexity score calculation for high complexity"""
        score = strategy_selector._calculate_complexity_score(
            rows=300000,  # > medium_dataset_rows
            columns=25,   # > high_column_count
            fk_count=8,   # > high_fk_count
            has_multi_value=True,
            has_external_ontology=True,
            dependency_depth=5  # > high_dependency_depth
        )
        
        # Should be high complexity (close to 1.0)
        assert score > 0.8
        assert score <= 1.0


    def test_analyze_streaming_entity_centric_strategy(self, strategy_selector):
        """Test streaming entity-centric strategy analysis"""
        analysis = strategy_selector._analyze_streaming_entity_centric(
            total_size_mb=150.0,  # In sweet spot
            total_rows=50000,
            max_complexity=0.4,
            has_dependencies=False
        )
        
        assert isinstance(analysis, StrategyAnalysis)
        assert analysis.strategy == ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        assert analysis.feasibility_score > 0.8  # Should be highly feasible
        assert analysis.estimated_memory_mb < 200  # Capped due to streaming
        assert "memory efficiency" in analysis.pros[0].lower()

    def test_analyze_streaming_too_small_penalty(self, strategy_selector):
        """Test streaming analysis with too small dataset penalty"""
        analysis = strategy_selector._analyze_streaming_entity_centric(
            total_size_mb=5.0,  # Too small
            total_rows=1000,
            max_complexity=0.2,
            has_dependencies=False
        )
        
        assert analysis.feasibility_score < 1.0  # Should be penalized
        assert any("overhead" in con.lower() for con in analysis.cons)

    def test_analyze_multi_phase_strategy(self, strategy_selector):
        """Test multi-phase strategy analysis"""
        analysis = strategy_selector._analyze_multi_phase(
            total_size_mb=800.0,  # Large dataset
            total_rows=500000,
            max_complexity=0.7,
            has_dependencies=True
        )
        
        assert isinstance(analysis, StrategyAnalysis)
        assert analysis.strategy == ProcessingStrategy.MULTI_PHASE
        assert analysis.feasibility_score > 0.8  # Should be highly feasible for large + dependencies
        assert analysis.estimated_memory_mb < analysis.estimated_memory_mb * 3  # Most memory efficient
        assert "memory efficient" in analysis.pros[0].lower()
        assert "dependency resolution" in analysis.pros[2].lower()

    def test_analyze_multi_phase_small_dataset_penalty(self, strategy_selector):
        """Test multi-phase analysis with small dataset penalty"""
        analysis = strategy_selector._analyze_multi_phase(
            total_size_mb=10.0,  # Small dataset
            total_rows=5000,
            max_complexity=0.2,
            has_dependencies=False
        )
        
        assert analysis.feasibility_score < 1.0  # Should start lower
        assert any("overhead not justified" in con.lower() for con in analysis.cons)

    def test_assess_overall_complexity_low(self, strategy_selector):
        """Test overall complexity assessment for low complexity"""
        characteristics = [
            DatasetCharacteristics(
                dataset_name='test1',
                estimated_rows=1000,
                estimated_columns=5,
                estimated_size_mb=5.0,
                has_multi_value_columns=False,
                has_fk_relationships=False,
                has_external_ontologies=False,
                dependency_depth=0,
                complexity_score=0.1
            ),
            DatasetCharacteristics(
                dataset_name='test2',
                estimated_rows=2000,
                estimated_columns=3,
                estimated_size_mb=3.0,
                has_multi_value_columns=False,
                has_fk_relationships=False,
                has_external_ontologies=False,
                dependency_depth=0,
                complexity_score=0.2
            )
        ]
        
        assessment = strategy_selector._assess_overall_complexity(characteristics)
        assert assessment == "low"

    def test_assess_overall_complexity_medium(self, strategy_selector):
        """Test overall complexity assessment for medium complexity"""
        characteristics = [
            DatasetCharacteristics(
                dataset_name='test1',
                estimated_rows=50000,
                estimated_columns=15,
                estimated_size_mb=50.0,
                has_multi_value_columns=True,
                has_fk_relationships=True,
                has_external_ontologies=False,
                dependency_depth=1,
                complexity_score=0.4
            ),
            DatasetCharacteristics(
                dataset_name='test2',
                estimated_rows=30000,
                estimated_columns=12,
                estimated_size_mb=35.0,
                has_multi_value_columns=False,
                has_fk_relationships=True,
                has_external_ontologies=True,
                dependency_depth=2,
                complexity_score=0.5
            )
        ]
        
        assessment = strategy_selector._assess_overall_complexity(characteristics)
        assert assessment == "medium"

    def test_assess_overall_complexity_high(self, strategy_selector):
        """Test overall complexity assessment for high complexity"""
        characteristics = [
            DatasetCharacteristics(
                dataset_name='test1',
                estimated_rows=500000,
                estimated_columns=25,
                estimated_size_mb=500.0,
                has_multi_value_columns=True,
                has_fk_relationships=True,
                has_external_ontologies=True,
                dependency_depth=4,
                complexity_score=0.8
            )
        ]
        
        assessment = strategy_selector._assess_overall_complexity(characteristics)
        assert assessment == "high"

    def test_assess_overall_complexity_empty_list(self, strategy_selector):
        """Test overall complexity assessment with empty characteristics list"""
        assessment = strategy_selector._assess_overall_complexity([])
        assert assessment == "unknown"


class TestProcessingStrategy:
    """Test suite for ProcessingStrategy enum"""

    def test_processing_strategy_values(self):
        """Test ProcessingStrategy enum values"""
        assert ProcessingStrategy.STREAMING_ENTITY_CENTRIC.value == "streaming_entity_centric"
        assert ProcessingStrategy.MULTI_PHASE.value == "multi_phase"
        assert ProcessingStrategy.AUTO.value == "auto"

    def test_processing_strategy_from_string(self):
        """Test creating ProcessingStrategy from string"""
        assert ProcessingStrategy("streaming_entity_centric") == ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        assert ProcessingStrategy("multi_phase") == ProcessingStrategy.MULTI_PHASE
        assert ProcessingStrategy("auto") == ProcessingStrategy.AUTO

    def test_processing_strategy_invalid_string(self):
        """Test creating ProcessingStrategy from invalid string raises ValueError"""
        with pytest.raises(ValueError):
            ProcessingStrategy("invalid_strategy")


class TestDatasetCharacteristics:
    """Test suite for DatasetCharacteristics dataclass"""

    def test_dataset_characteristics_creation(self):
        """Test DatasetCharacteristics creation"""
        char = DatasetCharacteristics(
            dataset_name='test_dataset',
            estimated_rows=1000,
            estimated_columns=5,
            estimated_size_mb=10.5,
            has_multi_value_columns=True,
            has_fk_relationships=False,
            has_external_ontologies=False,
            dependency_depth=2,
            complexity_score=0.3
        )
        
        assert char.dataset_name == 'test_dataset'
        assert char.estimated_rows == 1000
        assert char.estimated_columns == 5
        assert char.estimated_size_mb == 10.5
        assert char.has_multi_value_columns is True
        assert char.has_fk_relationships is False
        assert char.has_external_ontologies is False
        assert char.dependency_depth == 2
        assert char.complexity_score == 0.3


class TestStrategyAnalysis:
    """Test suite for StrategyAnalysis dataclass"""

    def test_strategy_analysis_creation(self):
        """Test StrategyAnalysis creation"""
        analysis = StrategyAnalysis(
            strategy=ProcessingStrategy.STREAMING_ENTITY_CENTRIC,
            feasibility_score=0.85,
            estimated_memory_mb=150.0,
            estimated_execution_time_minutes=5.5,
            pros=["Fast execution", "Complete entities"],
            cons=["High memory usage"],
            recommended=True
        )
        
        assert analysis.strategy == ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        assert analysis.feasibility_score == 0.85
        assert analysis.estimated_memory_mb == 150.0
        assert analysis.estimated_execution_time_minutes == 5.5
        assert len(analysis.pros) == 2
        assert len(analysis.cons) == 1
        assert analysis.recommended is True

    def test_strategy_analysis_default_recommended(self):
        """Test StrategyAnalysis default recommended value"""
        analysis = StrategyAnalysis(
            strategy=ProcessingStrategy.STREAMING_ENTITY_CENTRIC,
            feasibility_score=0.7,
            estimated_memory_mb=100.0,
            estimated_execution_time_minutes=8.0,
            pros=["Balanced approach"],
            cons=["Moderate complexity"]
        )
        
        assert analysis.recommended is False  # Default value