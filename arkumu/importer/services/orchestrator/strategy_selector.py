"""
Strategy Selector

Intelligently selects optimal processing strategy based on data characteristics.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum

from ..mapping_consumer import ExecutionConfig

logger = logging.getLogger(__name__)


class ProcessingStrategy(Enum):
    """Processing strategy options for import execution"""
    AUTO = "auto"
    STREAMING_ENTITY_CENTRIC = "streaming_entity_centric"
    MULTI_PHASE = "multi_phase"


@dataclass
class DatasetCharacteristics:
    """Characteristics of a dataset for strategy selection"""
    dataset_name: str
    estimated_rows: int
    estimated_columns: int
    estimated_size_mb: float
    has_multi_value_columns: bool
    has_fk_relationships: bool
    has_external_ontologies: bool
    dependency_depth: int
    complexity_score: float


@dataclass
class StrategyAnalysis:
    """Analysis of a processing strategy"""
    strategy: ProcessingStrategy
    feasibility_score: float  # 0-1, higher is better
    estimated_memory_mb: float
    estimated_execution_time_minutes: float
    pros: List[str]
    cons: List[str]
    recommended: bool = False


class StrategySelector:
    """
    Intelligently selects optimal processing strategy.
    
    Analyzes data characteristics, mapping complexity, and system constraints
    to recommend the best processing approach.
    """
    
    def __init__(self):
        # Strategy selection thresholds
        self.small_dataset_mb = 50
        self.medium_dataset_mb = 500
        self.small_dataset_rows = 20000
        self.medium_dataset_rows = 200000
        
        # Complexity thresholds
        self.high_fk_count = 5
        self.high_column_count = 20
        self.high_dependency_depth = 3
    
    def choose_optimal_strategy(self, 
                              execution_config: ExecutionConfig,
                              csv_sources: Dict[str, Any]) -> ProcessingStrategy:
        """
        Always returns STREAMING_ENTITY_CENTRIC (only available strategy).
        
        Args:
            execution_config: Execution configuration (for compatibility)
            csv_sources: CSV data sources (for compatibility)
            
        Returns:
            Recommended ProcessingStrategy
        """
        # Always return the only available strategy
        logger.info("Using STREAMING_ENTITY_CENTRIC strategy (only available option)")
        return ProcessingStrategy.STREAMING_ENTITY_CENTRIC
    
    def analyze_all_strategies(self,
                             execution_config: ExecutionConfig,
                             csv_sources: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze all available strategies and return detailed comparison.
        
        Args:
            execution_config: Execution configuration
            csv_sources: CSV data sources
            
        Returns:
            Strategy analysis dictionary
        """
        characteristics = self._analyze_dataset_characteristics(execution_config, csv_sources)
        strategy_analyses = self._analyze_all_strategies_internal(execution_config, characteristics)
        
        # Find recommended strategy
        recommended = max(strategy_analyses, key=lambda x: x.feasibility_score)
        recommended.recommended = True
        
        return {
            'dataset_characteristics': [
                {
                    'dataset_name': char.dataset_name,
                    'estimated_rows': char.estimated_rows,
                    'estimated_size_mb': char.estimated_size_mb,
                    'complexity_score': char.complexity_score,
                    'has_multi_value_columns': char.has_multi_value_columns,
                    'has_fk_relationships': char.has_fk_relationships,
                    'dependency_depth': char.dependency_depth
                }
                for char in characteristics
            ],
            'strategy_analyses': [
                {
                    'strategy': analysis.strategy.value,
                    'feasibility_score': analysis.feasibility_score,
                    'estimated_memory_mb': analysis.estimated_memory_mb,
                    'estimated_execution_time_minutes': analysis.estimated_execution_time_minutes,
                    'pros': analysis.pros,
                    'cons': analysis.cons,
                    'recommended': analysis.recommended
                }
                for analysis in strategy_analyses
            ],
            'recommended_strategy': recommended.strategy.value,
            'total_estimated_size_mb': sum(char.estimated_size_mb for char in characteristics),
            'total_datasets': len(characteristics),
            'complexity_assessment': self._assess_overall_complexity(characteristics)
        }
    
    def get_strategy_rationale(self,
                             execution_config: ExecutionConfig,
                             csv_sources: Dict[str, Any],
                             chosen_strategy: ProcessingStrategy) -> str:
        """
        Get rationale for why a strategy was chosen.
        
        Args:
            execution_config: Execution configuration
            csv_sources: CSV data sources
            chosen_strategy: The chosen strategy
            
        Returns:
            Human-readable rationale
        """
        characteristics = self._analyze_dataset_characteristics(execution_config, csv_sources)
        
        total_size_mb = sum(char.estimated_size_mb for char in characteristics)
        total_rows = sum(char.estimated_rows for char in characteristics)
        has_complex_relationships = any(char.has_fk_relationships for char in characteristics)
        has_dependencies = len(execution_config.fk_relationships) > 0
        
        if chosen_strategy == ProcessingStrategy.STREAMING_ENTITY_CENTRIC:
            return (f"Streaming entity-centric chosen for medium dataset ({total_size_mb:.1f}MB). "
                   f"Balances memory efficiency with entity completeness.")
        elif chosen_strategy == ProcessingStrategy.MULTI_PHASE:
            dependency_reason = "with complex dependencies" if has_dependencies else "due to size"
            return (f"Multi-phase chosen for large dataset ({total_size_mb:.1f}MB) {dependency_reason}. "
                   f"Minimizes memory usage and handles dependencies properly.")
        else:
            return f"Strategy {chosen_strategy.value} selected based on data characteristics."
    
    def _analyze_dataset_characteristics(self,
                                       execution_config: ExecutionConfig,
                                       csv_sources: Dict[str, Any]) -> List[DatasetCharacteristics]:
        """Analyze characteristics of each dataset"""
        
        characteristics = []
        
        for dataset_config in execution_config.datasets:
            dataset_name = dataset_config.dataset_name
            
            # Get CSV data if available
            csv_data = csv_sources.get(dataset_name, [])
            
            # Estimate size
            estimated_rows = len(csv_data) if isinstance(csv_data, list) else 0
            estimated_columns = len(csv_data[0]) if csv_data and isinstance(csv_data, list) else len(dataset_config.columns)
            
            # Rough size estimation (assuming average 50 bytes per cell)
            estimated_size_mb = (estimated_rows * estimated_columns * 50) / (1024 * 1024)
            
            # Analyze column types
            has_multi_value = any(col.is_multi_value for col in dataset_config.columns)
            has_external_ontology = any(col.is_external_ontology for col in dataset_config.columns)
            
            # Analyze relationships
            dataset_fk_count = len([fk for fk in execution_config.fk_relationships 
                                  if fk.source_dataset == dataset_name])
            has_fk_relationships = dataset_fk_count > 0
            
            # Calculate dependency depth
            dependency_depth = len(dataset_config.dependencies)
            
            # Calculate complexity score
            complexity_score = self._calculate_complexity_score(
                estimated_rows, estimated_columns, dataset_fk_count,
                has_multi_value, has_external_ontology, dependency_depth
            )
            
            char = DatasetCharacteristics(
                dataset_name=dataset_name,
                estimated_rows=estimated_rows,
                estimated_columns=estimated_columns,
                estimated_size_mb=estimated_size_mb,
                has_multi_value_columns=has_multi_value,
                has_fk_relationships=has_fk_relationships,
                has_external_ontologies=has_external_ontology,
                dependency_depth=dependency_depth,
                complexity_score=complexity_score
            )
            
            characteristics.append(char)
            
            logger.debug(f"Dataset {dataset_name}: {estimated_rows} rows, "
                        f"{estimated_size_mb:.1f}MB, complexity: {complexity_score:.2f}")
        
        return characteristics
    
    def _calculate_complexity_score(self,
                                  rows: int,
                                  columns: int,
                                  fk_count: int,
                                  has_multi_value: bool,
                                  has_external_ontology: bool,
                                  dependency_depth: int) -> float:
        """Calculate complexity score for a dataset (0-1, higher = more complex)"""
        
        score = 0.0
        
        # Size complexity
        if rows > self.medium_dataset_rows:
            score += 0.3
        elif rows > self.small_dataset_rows:
            score += 0.1
        
        if columns > self.high_column_count:
            score += 0.2
        elif columns > 10:
            score += 0.1
        
        # Relationship complexity
        if fk_count > self.high_fk_count:
            score += 0.2
        elif fk_count > 0:
            score += 0.1
        
        # Feature complexity
        if has_multi_value:
            score += 0.1
        if has_external_ontology:
            score += 0.1
        
        # Dependency complexity
        if dependency_depth > self.high_dependency_depth:
            score += 0.2
        elif dependency_depth > 0:
            score += 0.1
        
        return min(score, 1.0)
    
    def _analyze_all_strategies_internal(self,
                                       execution_config: ExecutionConfig,
                                       characteristics: List[DatasetCharacteristics]) -> List[StrategyAnalysis]:
        """Analyze all strategies internally"""
        
        analyses = []
        
        # Aggregate characteristics
        total_size_mb = sum(char.estimated_size_mb for char in characteristics)
        total_rows = sum(char.estimated_rows for char in characteristics)
        max_complexity = max((char.complexity_score for char in characteristics), default=0)
        has_dependencies = len(execution_config.fk_relationships) > 0
        
        # Entity-Centric strategy has been removed (no FK resolution support)
        
        # Analyze Streaming Entity-Centric
        streaming_analysis = self._analyze_streaming_entity_centric(
            total_size_mb, total_rows, max_complexity, has_dependencies
        )
        analyses.append(streaming_analysis)
        
        # Analyze Multi-Phase
        multi_phase_analysis = self._analyze_multi_phase(
            total_size_mb, total_rows, max_complexity, has_dependencies
        )
        analyses.append(multi_phase_analysis)
        
        return analyses
    
    
    def _analyze_streaming_entity_centric(self,
                                        total_size_mb: float,
                                        total_rows: int,
                                        max_complexity: float,
                                        has_dependencies: bool) -> StrategyAnalysis:
        """Analyze streaming entity-centric strategy"""
        
        # Memory usage: ~2-3x chunk size
        estimated_memory_mb = min(total_size_mb * 2.0, 150)  # Capped due to streaming
        
        # Execution time: slightly slower due to chunking overhead
        estimated_time_minutes = (total_rows / 8000) * 1.0  # 8K rows per minute
        
        # Feasibility score
        feasibility = 1.0
        
        # Size sweet spot
        if self.small_dataset_mb <= total_size_mb <= self.medium_dataset_mb:
            feasibility += 0.2  # Bonus for optimal size range
        elif total_size_mb > self.medium_dataset_mb:
            feasibility -= 0.1  # Small penalty for very large datasets
        elif total_size_mb < self.small_dataset_mb:
            feasibility -= 0.1  # Small penalty for very small datasets (overhead)
        
        # Complexity handling
        if max_complexity > 0.3:
            feasibility += 0.1  # Good for moderate complexity
        
        pros = [
            "Good balance of memory efficiency and entity completeness",
            "Handles medium datasets well",
            "Streaming reduces memory pressure",
            "Maintains entity-centric benefits"
        ]
        
        cons = []
        if total_size_mb < self.small_dataset_mb:
            cons.append("Overhead may not be justified for small datasets")
        if total_size_mb > self.medium_dataset_mb:
            cons.append("May still use significant memory for very large datasets")
        
        return StrategyAnalysis(
            strategy=ProcessingStrategy.STREAMING_ENTITY_CENTRIC,
            feasibility_score=max(feasibility, 0.0),
            estimated_memory_mb=estimated_memory_mb,
            estimated_execution_time_minutes=estimated_time_minutes,
            pros=pros,
            cons=cons
        )
    
    def _analyze_multi_phase(self,
                           total_size_mb: float,
                           total_rows: int,
                           max_complexity: float,
                           has_dependencies: bool) -> StrategyAnalysis:
        """Analyze multi-phase strategy"""
        
        # Memory usage: ~1.5x CSV size (most efficient)
        estimated_memory_mb = total_size_mb * 1.5
        
        # Execution time: slower due to multiple passes
        base_time = (total_rows / 6000) * 1.0  # 6K rows per minute
        phase_multiplier = 1.5 if has_dependencies else 1.2
        estimated_time_minutes = base_time * phase_multiplier
        
        # Feasibility score
        feasibility = 0.8  # Start lower due to complexity
        
        # Size advantages
        if total_size_mb > self.medium_dataset_mb:
            feasibility += 0.3  # Major bonus for large datasets
        elif total_size_mb > self.small_dataset_mb:
            feasibility += 0.1
        
        # Dependency handling bonus
        if has_dependencies:
            feasibility += 0.2
        
        # Memory efficiency bonus
        if estimated_memory_mb < 100:
            feasibility += 0.1
        
        pros = [
            "Most memory efficient",
            "Handles very large datasets",
            "Robust dependency resolution",
            "Scalable architecture"
        ]
        
        cons = [
            "Multiple data passes increase execution time",
            "More complex orchestration",
            "Entity fragmentation across phases"
        ]
        
        if total_size_mb < self.small_dataset_mb:
            cons.append("Overhead not justified for small datasets")
        
        return StrategyAnalysis(
            strategy=ProcessingStrategy.MULTI_PHASE,
            feasibility_score=max(feasibility, 0.0),
            estimated_memory_mb=estimated_memory_mb,
            estimated_execution_time_minutes=estimated_time_minutes,
            pros=pros,
            cons=cons
        )
    
    def _assess_overall_complexity(self, characteristics: List[DatasetCharacteristics]) -> str:
        """Assess overall complexity of the import"""
        
        if not characteristics:
            return "unknown"
        
        avg_complexity = sum(char.complexity_score for char in characteristics) / len(characteristics)
        max_complexity = max(char.complexity_score for char in characteristics)
        
        if max_complexity > 0.7 or avg_complexity > 0.5:
            return "high"
        elif max_complexity > 0.4 or avg_complexity > 0.3:
            return "medium"
        else:
            return "low"