"""
Simple utility for normalizing column names in mapping configurations.
Handles the :: separator issue in workspace column names.
"""


class ColumnNameNormalizer:
    """Utility class for normalizing column names in mapping configurations."""
    
    WORKSPACE_SEPARATOR = "::"
    
    @classmethod
    def normalize_column_name(cls, column_name: str) -> str:
        """
        Normalize structured column names by extracting the actual column identifier.
        
        Examples:
        - "21_PhysischesObjekt::Projekte" -> "Projekte"
        - "_Projekte_Export" -> "_Projekte_Export"
        - "Workspace::Column" -> "Column"
        
        Args:
            column_name: Column name that may contain workspace separator
            
        Returns:
            str: Normalized column name (last part after ::)
        """
        if not column_name:
            return column_name
            
        if cls.WORKSPACE_SEPARATOR in column_name:
            return column_name.split(cls.WORKSPACE_SEPARATOR)[-1]
        return column_name
    
    @classmethod
    def find_column_match(cls, target_column: str, available_columns: list) -> str:
        """
        Find a matching column in the available columns list.
        First tries exact match, then normalized match.
        
        Args:
            target_column: Column name to find
            available_columns: List of available column names
            
        Returns:
            str: Matching column name from available_columns, or None if not found
        """
        if not target_column or not available_columns:
            return None
        
        # First try exact match
        if target_column in available_columns:
            return target_column
        
        # Then try to find by normalized name
        normalized_target = cls.normalize_column_name(target_column)
        for col in available_columns:
            if cls.normalize_column_name(col) == normalized_target:
                return col
        
        return None