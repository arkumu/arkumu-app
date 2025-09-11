"""
Validates all relationship types in correlation analysis.

Handles foreign key validation, relationship contexts (junction tables), 
and join requirements for comprehensive relational integrity checking.
"""

import logging
from typing import List, Dict, Any, Optional

from arkumu.importer.services.mapping_correlation.data_models import FileAnalysis
from arkumu.importer.utils.column_name_utils import ColumnNameNormalizer

logger = logging.getLogger(__name__)


class RelationshipValidator:
    """Validates all relationship types in correlation analysis"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def validate_fk_relationships(self, 
                                 fk_rels: List[Dict], 
                                 file_analyses: List[FileAnalysis]) -> Dict:
        """
        Validate FK columns exist and reference valid targets
        
        Returns:
            {
                'valid': bool,
                'issues': [
                    {
                        'type': 'missing_fk_column',
                        'dataset': 'orders',
                        'column': 'customer_id',
                        'target': 'customers.id'
                    }
                ]
            }
        """
        issues = []
        
        for fk in fk_rels:
            # Check source column exists
            source_file = self._find_file_for_dataset(
                fk['source_dataset'], file_analyses
            )
            
            if not source_file:
                issues.append({
                    'type': 'missing_source_dataset',
                    'dataset': fk['source_dataset'],
                    'relationship_id': fk.get('id')
                })
                continue
                
            # Check if FK column exists (handle structured column names with ::)
            matched_source_column = ColumnNameNormalizer.find_column_match(
                fk['source_column'], source_file.columns
            )
            if not matched_source_column:
                issues.append({
                    'type': 'missing_fk_column',
                    'dataset': fk['source_dataset'],
                    'column': fk['source_column'],
                    'target': f"{fk['target_dataset']}.{fk['target_column']}",
                    'relationship_id': fk.get('id')
                })
            
            # Check target exists
            target_file = self._find_file_for_dataset(
                fk['target_dataset'], file_analyses
            )
            
            if not target_file:
                issues.append({
                    'type': 'missing_target_dataset',
                    'dataset': fk['target_dataset'],
                    'referenced_by': f"{fk['source_dataset']}.{fk['source_column']}",
                    'relationship_id': fk.get('id')
                })
            else:
                # Check if target column exists (handle structured column names with ::)
                matched_target_column = ColumnNameNormalizer.find_column_match(
                    fk['target_column'], target_file.columns
                )
                if not matched_target_column:
                    issues.append({
                        'type': 'missing_target_column',
                        'dataset': fk['target_dataset'],
                        'column': fk['target_column'],
                        'referenced_by': f"{fk['source_dataset']}.{fk['source_column']}",
                        'relationship_id': fk.get('id')
                    })
        
        return {
            'valid': len(issues) == 0,
            'issues': issues
        }
    
    def validate_relationship_contexts(self, 
                                     contexts: List[Dict],
                                     file_analyses: List[FileAnalysis]) -> Dict:
        """Validate junction tables have required FK columns and attributes"""
        issues = []
        
        for ctx in contexts:
            # Skip contexts with missing dataset information
            if not ctx.get('dataset'):
                continue
                
            junction_file = self._find_file_for_dataset(
                ctx['dataset'], file_analyses
            )
            
            if not junction_file:
                issues.append({
                    'type': 'missing_junction_table',
                    'dataset': ctx['dataset'],
                    'context_id': ctx['context_id']
                })
                continue
            
            # Check both FK columns exist (handle structured column names with ::)
            missing_fks = []
            if not ColumnNameNormalizer.find_column_match(ctx['primary_fk'], junction_file.columns):
                missing_fks.append(ctx['primary_fk'])
            if not ColumnNameNormalizer.find_column_match(ctx['secondary_fk'], junction_file.columns):
                missing_fks.append(ctx['secondary_fk'])
                
            if missing_fks:
                issues.append({
                    'type': 'missing_junction_fks',
                    'dataset': ctx['dataset'],
                    'missing_fks': missing_fks,
                    'context_id': ctx['context_id']
                })
            
            # Check context columns (handle structured column names with ::)
            missing_attrs = []
            for attr in ctx.get('context_columns', []):
                if not ColumnNameNormalizer.find_column_match(attr, junction_file.columns):
                    missing_attrs.append(attr)
                    
            if missing_attrs:
                issues.append({
                    'type': 'missing_context_attributes',
                    'dataset': ctx['dataset'],
                    'missing_attrs': missing_attrs,
                    'context_id': ctx['context_id']
                })
        
        return {
            'valid': len(issues) == 0,
            'issues': issues
        }
    
    def validate_join_requirements(self, 
                                  relationships: List[Dict],
                                  file_analyses: List[FileAnalysis]) -> Dict:
        """Validate columns needed for joins exist in both datasets"""
        issues = []
        
        for rel in relationships:
            # Parse column references (format: "dataset.column" or just "column")
            from_col = rel.get('from_column', '')
            to_col = rel.get('to_column', '')
            
            # Check if columns have dataset prefix
            from_parts = from_col.split('.')
            to_parts = to_col.split('.')
            
            # Validate from column
            if len(from_parts) == 2:
                dataset, column = from_parts
                file_analysis = self._find_file_for_dataset(dataset, file_analyses)
                if not file_analysis:
                    issues.append({
                        'type': 'missing_join_dataset',
                        'dataset': dataset,
                        'column': column,
                        'relationship': rel.get('relationship_type'),
                        'relationship_desc': rel.get('description', '')
                    })
                elif not ColumnNameNormalizer.find_column_match(column, file_analysis.columns):
                    issues.append({
                        'type': 'missing_join_column',
                        'dataset': dataset,
                        'column': column,
                        'relationship': rel.get('relationship_type'),
                        'relationship_desc': rel.get('description', '')
                    })
            
            # Validate to column
            if len(to_parts) == 2:
                dataset, column = to_parts
                file_analysis = self._find_file_for_dataset(dataset, file_analyses)
                if not file_analysis:
                    issues.append({
                        'type': 'missing_join_dataset',
                        'dataset': dataset,
                        'column': column,
                        'relationship': rel.get('relationship_type'),
                        'relationship_desc': rel.get('description', '')
                    })
                elif not ColumnNameNormalizer.find_column_match(column, file_analysis.columns):
                    issues.append({
                        'type': 'missing_join_column',
                        'dataset': dataset,
                        'column': column,
                        'relationship': rel.get('relationship_type'),
                        'relationship_desc': rel.get('description', '')
                    })
        
        return {
            'valid': len(issues) == 0,
            'issues': issues
        }
    
    def _find_file_for_dataset(self, dataset_name: str, 
                              file_analyses: List[FileAnalysis]) -> Optional[FileAnalysis]:
        """Find file analysis matching the dataset name"""
        # Skip if dataset_name is None or empty
        if not dataset_name:
            return None
            
        for file_analysis in file_analyses:
            if file_analysis.matched_dataset_name == dataset_name:
                return file_analysis
        return None
    
    def validate_dependency_order(self, file_analyses: List[FileAnalysis], 
                                 fk_rels: List[Dict]) -> Dict:
        """
        Validate that FK dependencies don't create cycles and can be processed in order
        """
        # Build dependency graph
        dependencies = {}
        for fk in fk_rels:
            source = fk['source_dataset']
            target = fk['target_dataset']
            
            if source not in dependencies:
                dependencies[source] = set()
            dependencies[source].add(target)
        
        # Check for cycles using DFS
        visited = set()
        rec_stack = set()
        cycle_found = False
        cycle_path = []
        
        def has_cycle(node, path):
            nonlocal cycle_found, cycle_path
            if cycle_found:
                return True
                
            visited.add(node)
            rec_stack.add(node)
            path.append(node)
            
            if node in dependencies:
                for neighbor in dependencies[node]:
                    if neighbor not in visited:
                        if has_cycle(neighbor, path.copy()):
                            return True
                    elif neighbor in rec_stack:
                        cycle_found = True
                        cycle_path = path[path.index(neighbor):] + [neighbor]
                        return True
            
            rec_stack.remove(node)
            return False
        
        # Check each component
        for dataset in dependencies:
            if dataset not in visited:
                if has_cycle(dataset, []):
                    break
        
        # Compute processing order if no cycles
        processing_order = []
        if not cycle_found:
            # Topological sort - we need to reverse the dependency direction
            # because dependencies[A] = {B} means A depends on B, so B should come first
            
            # First, collect all nodes
            all_nodes = set(dependencies.keys())
            for deps in dependencies.values():
                all_nodes.update(deps)
            
            # Calculate in-degree (number of nodes that depend on this node)
            in_degree = {node: 0 for node in all_nodes}
            
            # For each dependency A -> B, increment in-degree of B
            for source, targets in dependencies.items():
                for target in targets:
                    in_degree[target] += 1
            
            # Add all nodes with no incoming edges (nothing depends on them)
            queue = [node for node, degree in in_degree.items() if degree == 0]
            
            while queue:
                node = queue.pop(0)
                processing_order.append(node)
                
                # Remove this node's outgoing edges
                if node in dependencies:
                    for target in dependencies[node]:
                        in_degree[target] -= 1
                        if in_degree[target] == 0:
                            queue.append(target)
            
            # Reverse the order so dependencies come first
            processing_order.reverse()
        
        return {
            'valid': not cycle_found,
            'has_cycles': cycle_found,
            'cycle': cycle_path if cycle_found else [],
            'processing_order': processing_order,
            'dependencies': {k: list(v) for k, v in dependencies.items()}
        }