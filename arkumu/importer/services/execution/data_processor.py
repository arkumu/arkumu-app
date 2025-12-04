"""
Data processing utilities with Polars optimization.
"""

import logging
import polars as pl
from typing import Dict, List, Any, Optional, Union, Tuple
import re

logger = logging.getLogger(__name__)


class DataProcessor:
    """
    High-performance data processing using Polars DataFrames.
    
    Handles data cleaning, normalization, and transformation operations
    with vectorized processing for optimal performance.
    """
    
    def __init__(self, multi_value_threshold: float = 0.2):
        """
        Initialize the data processor.
        
        Args:
            multi_value_threshold: Threshold for detecting multi-value columns (0.2 = 20%)
        """
        self.multi_value_threshold = multi_value_threshold
    
    def ensure_dataframe(self, data: Union[List[Dict[str, Any]], pl.DataFrame]) -> pl.DataFrame:
        """Convert data to Polars DataFrame if it's not already."""
        if isinstance(data, pl.DataFrame):
            return data
        elif isinstance(data, list):
            # Validate that it's a list of dictionaries
            if not data:
                return pl.DataFrame()  # Empty list -> empty DataFrame
            if not all(isinstance(item, dict) for item in data):
                raise ValueError("List data must contain only dictionaries")
            return pl.DataFrame(data)
        else:
            # Invalid data type - raise clear error like working implementation expects
            raise TypeError(f"Data must be a Polars DataFrame or list of dictionaries, got {type(data)}")
    
    def normalize_unicode_vectorized(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Vectorized Unicode normalization using Polars built-in string methods.
        This is much more efficient than normalizing each cell individually in Python.
        
        Args:
            df: Input DataFrame
            
        Returns:
            DataFrame with all string columns normalized to NFC
        """
        # Get all string columns
        string_columns = [col for col in df.columns if df[col].dtype == pl.Utf8]
        
        if not string_columns:
            return df
        
        logger.debug(f"Applying vectorized Unicode NFC normalization to {len(string_columns)} string columns")
        
        # Apply NFC normalization to all string columns at once
        normalized_columns = [
            pl.col(col).str.normalize("NFC").alias(col) for col in string_columns
        ]
        
        # Keep non-string columns unchanged
        non_string_columns = [col for col in df.columns if col not in string_columns]
        all_columns = non_string_columns + normalized_columns
        
        return df.with_columns(all_columns)
    
    def add_row_identifiers(self, df: pl.DataFrame, start_offset: int = 0) -> pl.DataFrame:
        """
        Add row identifiers to the DataFrame.
        
        Args:
            df: Input DataFrame
            start_offset: Starting offset for row IDs
            
        Returns:
            DataFrame with row_id column added
        """
        return df.with_row_index(name='row_id', offset=start_offset)
    
    def detect_delimiter_in_column(self, df: pl.DataFrame, column_name: str, potential_delimiters: List[str] = None) -> Optional[Tuple[str, float]]:
        """
        Detect the most likely delimiter in a column using heuristics.
        
        Args:
            df: Input DataFrame
            column_name: Name of column to analyze
            potential_delimiters: List of delimiters to test (defaults to common ones)
        
        Returns:
            Tuple of (delimiter, confidence_score) or None if no delimiter detected
        """
        if potential_delimiters is None:
            # Note: '/' excluded to prevent splitting URLs
            potential_delimiters = [',', '|', ';']
        
        # Get non-null values from the column
        try:
            column_values = df.select(pl.col(column_name).drop_nulls()).to_series().to_list()
            if not column_values:
                return None
            
            # Sample up to 1000 values for performance
            sample_size = min(1000, len(column_values))
            sample_values = column_values[:sample_size]
            
            delimiter_scores = {}
            
            for delimiter in potential_delimiters:
                delimiter_count = 0
                total_occurrences = 0
                
                for value in sample_values:
                    if isinstance(value, str) and delimiter in value:
                        delimiter_count += 1
                        total_occurrences += value.count(delimiter)
                
                if delimiter_count > 0:
                    # Calculate confidence: percentage of rows with delimiter + average occurrences
                    percentage = delimiter_count / len(sample_values)
                    avg_occurrences = total_occurrences / delimiter_count if delimiter_count > 0 else 0
                    
                    # Confidence boost for systematic patterns (e.g., ranges like "1-5")
                    pattern_boost = 0.0
                    if delimiter == '-':
                        # Look for number-number patterns
                        import re
                        number_pattern = re.compile(r'\d+\-\d+')
                        pattern_matches = sum(1 for v in sample_values[:100] if isinstance(v, str) and number_pattern.search(v))
                        if pattern_matches > len(sample_values[:100]) * 0.1:  # 10% threshold
                            pattern_boost = 0.3
                    
                    confidence = percentage + (avg_occurrences * 0.1) + pattern_boost
                    delimiter_scores[delimiter] = min(1.0, confidence)  # Cap at 1.0
            
            if not delimiter_scores:
                return None
                
            # Return delimiter with highest confidence if above threshold
            best_delimiter = max(delimiter_scores.items(), key=lambda x: x[1])
            if best_delimiter[1] >= 0.15:  # 15% threshold
                return best_delimiter
                
        except Exception as e:
            logger.warning(f"Error detecting delimiter in column '{column_name}': {e}")
        
        return None
    
    def detect_multi_value_columns(self, df: pl.DataFrame, mapping_config: Optional[Dict] = None) -> Dict[str, Dict[str, Any]]:
        """
        Detect multi-value columns based on mapping configuration with efficient heuristic detection.
        Only runs heuristic detection on columns already marked as multi-value in the mapping.
        
        Args:
            df: Input DataFrame
            mapping_config: Optional mapping configuration that may specify multi-value columns
            
        Returns:
            Dictionary mapping column names to multi-value analysis
        """
        if df.height == 0:
            logger.debug("Empty DataFrame provided for multi-value detection")
            return {}
        
        multi_value_analysis = {}
        mapped_multi_value_columns = []
        
        # First pass: identify columns marked as multi-value in mapping config
        for column_name in df.columns:
            if column_name == 'row_id':
                continue
            
            # Check if mapping config specifies this as multi-value
            is_multi_value_from_config = False
            separator = ','  # default separator
            column_config = None
            config_structure_used = None
            
            if mapping_config:
                # Try different possible mapping config structures
                
                # Structure 1: mapping_config['columns'][column_name]
                if 'columns' in mapping_config:
                    column_config = mapping_config['columns'].get(column_name, {})
                    if column_config:
                        config_structure_used = 'columns'
                
                # Structure 2: mapping_config['workspace_columns'] with qualified names
                elif 'workspace_columns' in mapping_config:
                    # Look for column in workspace_columns with various name patterns
                    workspace_columns = mapping_config['workspace_columns']
                    for qualified_name, config in workspace_columns.items():
                        # Match by exact name or if qualified name ends with our column name
                        if (qualified_name == column_name or 
                            qualified_name.endswith(f"::{column_name}") or
                            qualified_name.endswith(f".{column_name}")):
                            column_config = config
                            config_structure_used = f'workspace_columns[{qualified_name}]'
                            break
                
                if column_config and isinstance(column_config, dict):
                    is_multi_value_from_config = column_config.get('is_multi_value', False)
                    # Check for both 'separator' and 'multi_value_separator' fields
                    separator = column_config.get('separator') or column_config.get('multi_value_separator', ',')
                    if is_multi_value_from_config:
                        logger.debug(f"Found multi-value column '{column_name}' via {config_structure_used} with separator '{separator}'")
                        mapped_multi_value_columns.append(column_name)
                    else:
                        logger.debug(f"Column '{column_name}' found in {config_structure_used} but is_multi_value=False")
            
            if is_multi_value_from_config:
                # Use mapping configuration (separator already extracted above)
                multi_value_analysis[column_name] = {
                    "is_multi_value": True,
                    "separator": separator,
                    "source": "mapping_config",
                    "stats": {"confidence_score": 1.0}
                }
            else:
                # For non-mapped columns, mark as not multi-value (no heuristic detection)
                multi_value_analysis[column_name] = {
                    "is_multi_value": False,
                    "separator": None,
                    "source": "mapping_config",
                    "stats": {"confidence_score": 0.0}
                }
        
        # Second pass: run heuristic detection ONLY on mapped multi-value columns
        # This detects better delimiters for columns already marked as multi-value
        if mapped_multi_value_columns:
            logger.debug(f"Running delimiter detection on {len(mapped_multi_value_columns)} mapped multi-value columns")
            
            delimiter_updates = []
            for column_name in mapped_multi_value_columns:
                current_separator = multi_value_analysis[column_name]['separator']
                
                # Run heuristic detection to potentially find a better delimiter
                delimiter_result = self.detect_delimiter_in_column(df, column_name)
                
                if delimiter_result and delimiter_result[1] >= 0.2:  # 20% confidence threshold
                    detected_delimiter, confidence = delimiter_result
                    
                    # If we detected a different delimiter with high confidence, use it
                    if detected_delimiter != current_separator and confidence >= 0.5:
                        logger.info(f"🔍 Updated delimiter for '{column_name}': '{current_separator}' → '{detected_delimiter}' (confidence: {confidence:.2f})")
                        multi_value_analysis[column_name]['separator'] = detected_delimiter
                        multi_value_analysis[column_name]['source'] = "mapping_config_with_heuristic"
                        multi_value_analysis[column_name]['stats'] = {
                            "confidence_score": confidence,
                            "total_rows": df.height,
                            "original_separator": current_separator
                        }
                        delimiter_updates.append(f"{column_name}: {detected_delimiter}")
                    else:
                        logger.debug(f"Confirmed separator '{current_separator}' for '{column_name}'")
        
        multi_value_count = sum(1 for col in multi_value_analysis.values() if col['is_multi_value'])
        
        if multi_value_count > 0:
            multi_value_columns = [col for col, config in multi_value_analysis.items() if config['is_multi_value']]
            logger.info(f"Multi-value columns ({multi_value_count}): {multi_value_columns}")
        
        return multi_value_analysis
    
    def split_multi_value_cells(self, df: pl.DataFrame, multi_value_config: Dict[str, Dict[str, Any]]) -> pl.DataFrame:
        """
        Split multi-value cells based on configuration.
        
        Args:
            df: Input DataFrame
            multi_value_config: Multi-value column configuration
            
        Returns:
            DataFrame with multi-value cells potentially expanded
        """
        # For now, return the original DataFrame
        # Multi-value splitting will be implemented when mapping configurations are consumed
        logger.debug("Multi-value cell splitting placeholder - returning original DataFrame")
        return df
    
    def clean_and_validate_data(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Clean and validate data in the DataFrame.
        
        Following the working pattern: individual value stripping like 
        smart_bulk_updater_polars.py does on line 212: str(value).strip()
        
        Args:
            df: Input DataFrame
            
        Returns:
            DataFrame with basic cleaning applied
        """
        logger.debug(f"Basic data cleaning for {df.height} rows and {len(df.columns)} columns")
        
        # Handle empty DataFrame early (like working implementation)
        if df.height == 0 or len(df.columns) == 0:
            logger.debug("Empty DataFrame, skipping cleaning")
            return df
        
        # Step 1: Apply individual value stripping (like working implementation)
        # Process each row and strip whitespace from string values
        cleaned_rows = []
        for row_idx in range(df.height):
            row_data = df.row(row_idx, named=True)
            cleaned_row = {}
            has_content = False
            
            for col_name, value in row_data.items():
                if value is not None:
                    # Apply individual string stripping like working implementation
                    cleaned_value = str(value).strip() if isinstance(value, str) else value
                    # Convert back to original type if it was numeric
                    if not isinstance(value, str) and cleaned_value != str(value):
                        cleaned_value = value  # Keep original non-string values
                    cleaned_row[col_name] = cleaned_value
                    
                    # Check if this row has any meaningful content
                    # Exclude row_id column from content check since it's artificial
                    if col_name != 'row_id':
                        # For strings, check if stripped value is not empty
                        # For non-strings, any non-None value counts as content
                        if isinstance(value, str):
                            if cleaned_value and cleaned_value.strip():
                                has_content = True
                        else:
                            has_content = True  # Non-string, non-None values always count as content
                else:
                    cleaned_row[col_name] = value
            
            # Only keep rows that have some content
            if has_content:
                cleaned_rows.append(cleaned_row)
        
        # Step 2: Create cleaned DataFrame
        if not cleaned_rows:
            # All rows were empty, return empty DataFrame with same schema
            logger.debug("All rows are empty after cleaning")
            return df.head(0)
        
        cleaned_df = pl.DataFrame(cleaned_rows)
        
        rows_removed = df.height - cleaned_df.height
        if rows_removed > 0:
            logger.debug(f"Removed {rows_removed} completely empty rows")
        
        return cleaned_df
    
    def validate_column_constraints(self, df: pl.DataFrame, mapping_config: Optional[Dict] = None) -> List[str]:
        """
        Validate column constraints based on mapping configuration.
        
        Following the working pattern, we avoid DataFrame-level string operations
        and check constraints during individual value processing.
        
        Args:
            df: Input DataFrame
            mapping_config: Optional mapping configuration
            
        Returns:
            List of validation error messages
        """
        errors = []
        
        if not mapping_config or 'columns' not in mapping_config:
            return errors
        
        for column_name, column_config in mapping_config['columns'].items():
            if column_name not in df.columns:
                if column_config.get('required', False):
                    errors.append(f"Required column '{column_name}' not found in data")
                continue
            
            column_data = df[column_name]
            
            # Check for required non-null values (safe approach)
            if column_config.get('required', False):
                null_count = column_data.null_count()
                
                # Count empty values by iterating (safe approach like working implementation)
                empty_count = 0
                for value in column_data:
                    if value is not None and str(value).strip() == "":
                        empty_count += 1
                
                if null_count + empty_count > 0:
                    errors.append(f"Column '{column_name}' has {null_count + empty_count} empty values but is marked as required")
            
            # Check data type constraints
            expected_type = column_config.get('datatype')
            if expected_type and expected_type != 'string':
                # Add specific data type validation here
                pass
        
        return errors
    
    def prepare_for_processing(self, data: Union[List[Dict[str, Any]], pl.DataFrame], 
                              mapping_config: Optional[Dict] = None) -> pl.DataFrame:
        """
        Complete data preparation pipeline.
        
        Following the exact pattern from smart_bulk_updater_polars.py:
        - Only NFC normalization at DataFrame level
        - Individual value stripping during processing, not here
        
        Args:
            data: Raw data from CSV
            mapping_config: Optional mapping configuration
            
        Returns:
            Prepared DataFrame ready for processing
        """
        logger.info("Starting data preparation pipeline")
        
        # Step 1: Ensure DataFrame
        df = self.ensure_dataframe(data)
        
        # Step 2: Unicode normalization (vectorized, safe) - ONLY this at DataFrame level
        # This exactly matches the working implementation pattern
        df = self.normalize_unicode_vectorized(df)
        
        # Step 3: Add row identifiers (matches working implementation)
        df = self.add_row_identifiers(df)
        
        # Step 4: Clean and validate (minimal, only remove completely empty rows)
        df = self.clean_and_validate_data(df)
        
        # Step 5: Detect multi-value columns for analysis
        multi_value_analysis = self.detect_multi_value_columns(df, mapping_config)
        
        # Step 6: Validate constraints (warnings only)
        validation_errors = self.validate_column_constraints(df, mapping_config)
        if validation_errors:
            logger.warning(f"Data validation warnings: {validation_errors}")
        
        logger.info(f"Data preparation completed: {df.height} rows ready for processing")
        return df 