"""
Test foreign key validation with structured column names (containing ::)
"""

import pytest
from arkumu.importer.services.mapping_correlation.relationship_validator import RelationshipValidator
from arkumu.importer.services.mapping_correlation.data_models import FileAnalysis
from arkumu.importer.utils.column_name_utils import ColumnNameNormalizer


@pytest.mark.django_db
class TestFKStructuredColumnNames:
    """Test FK validation handles structured column names correctly"""
    
    def test_column_name_normalizer(self):
        """Test basic column name normalization"""
        test_cases = [
            ("21_PhysischesObjekt::Projekte", "Projekte"),
            ("12c_Vorschaubild::_Projekte_Export", "_Projekte_Export"),
            ("Workspace::Column", "Column"),
            ("SimpleColumn", "SimpleColumn"),
            ("Complex::Workspace::Name::Column", "Column"),
        ]
        
        for input_name, expected in test_cases:
            result = ColumnNameNormalizer.normalize_column_name(input_name)
            assert result == expected, f"Expected {expected}, got {result} for input {input_name}"
    
    def test_find_column_match(self):
        """Test finding column matches with structured names"""
        available_columns = [
            "21_PhysischesObjekt::Projekte",
            "21_PhysischesObjekt::Name", 
            "12c_Vorschaubild::_Projekte_Export",
            "SimpleColumn"
        ]
        
        # Test exact matches
        assert ColumnNameNormalizer.find_column_match("SimpleColumn", available_columns) == "SimpleColumn"
        
        # Test normalized matches
        assert ColumnNameNormalizer.find_column_match("Projekte", available_columns) == "21_PhysischesObjekt::Projekte"
        assert ColumnNameNormalizer.find_column_match("_Projekte_Export", available_columns) == "12c_Vorschaubild::_Projekte_Export"
        assert ColumnNameNormalizer.find_column_match("Name", available_columns) == "21_PhysischesObjekt::Name"
        
        # Test no match
        assert ColumnNameNormalizer.find_column_match("NonExistent", available_columns) is None
    
    def test_fk_validation_with_structured_names(self):
        """Test FK validation handles structured column names correctly"""
        validator = RelationshipValidator()
        
        # Create file analyses with structured column names
        file_analyses = [
            FileAnalysis(
                file_path="21_PhysischesObjekt.csv",
                file_name="21_PhysischesObjekt",
                column_count=2,
                row_count=10,
                columns=["21_PhysischesObjekt::Projekte", "21_PhysischesObjekt::Name"],
                column_types={},
                matched_dataset_name="21_PhysischesObjekt"
            ),
            FileAnalysis(
                file_path="00_Projekte.csv", 
                file_name="00_Projekte",
                column_count=1,
                row_count=5,
                columns=["00_Projekte::Projekt_ID"],
                column_types={},
                matched_dataset_name="00_Projekte"
            ),
            FileAnalysis(
                file_path="12c_Vorschaubild.csv",
                file_name="12c_Vorschaubild", 
                column_count=2,
                row_count=8,
                columns=["12c_Vorschaubild::_Projekte_Export", "12c_Vorschaubild::Image_Path"],
                column_types={},
                matched_dataset_name="12c_Vorschaubild"
            )
        ]
        
        # FK relationships that should work with our fix
        fk_relationships = [
            {
                'id': 'fk_1',
                'source_dataset': '21_PhysischesObjekt',
                'source_column': 'Projekte',  # Simple name - should match "21_PhysischesObjekt::Projekte"
                'target_dataset': '00_Projekte',
                'target_column': 'Projekt_ID'  # Simple name - should match "00_Projekte::Projekt_ID"
            },
            {
                'id': 'fk_2', 
                'source_dataset': '12c_Vorschaubild',
                'source_column': '_Projekte_Export',  # Simple name - should match "12c_Vorschaubild::_Projekte_Export"
                'target_dataset': '00_Projekte',
                'target_column': 'Projekt_ID'  # Simple name - should match "00_Projekte::Projekt_ID"
            }
        ]
        
        # Run validation
        result = validator.validate_fk_relationships(fk_relationships, file_analyses)
        
        # Should be valid - no FK errors
        assert result['valid'] is True, f"FK validation should pass but found issues: {result['issues']}"
        assert len(result['issues']) == 0, f"Expected no issues but found: {result['issues']}"
    
    def test_fk_validation_with_missing_columns(self):
        """Test FK validation still catches actual missing columns"""
        validator = RelationshipValidator()
        
        # File analysis missing the FK column
        file_analyses = [
            FileAnalysis(
                file_path="21_PhysischesObjekt.csv",
                file_name="21_PhysischesObjekt", 
                column_count=1,
                row_count=10,
                columns=["21_PhysischesObjekt::Name"],  # Missing Projekte column
                column_types={},
                matched_dataset_name="21_PhysischesObjekt"
            ),
            FileAnalysis(
                file_path="00_Projekte.csv",
                file_name="00_Projekte",
                column_count=1, 
                row_count=5,
                columns=["00_Projekte::Projekt_ID"],
                column_types={},
                matched_dataset_name="00_Projekte"
            )
        ]
        
        fk_relationships = [
            {
                'id': 'fk_1',
                'source_dataset': '21_PhysischesObjekt',
                'source_column': 'Projekte',  # This column doesn't exist
                'target_dataset': '00_Projekte', 
                'target_column': 'Projekt_ID'
            }
        ]
        
        # Run validation
        result = validator.validate_fk_relationships(fk_relationships, file_analyses)
        
        # Should detect the missing column
        assert result['valid'] is False
        assert len(result['issues']) == 1
        assert result['issues'][0]['type'] == 'missing_fk_column'
        assert result['issues'][0]['column'] == 'Projekte'
        assert result['issues'][0]['dataset'] == '21_PhysischesObjekt'
    
    def test_junction_table_validation_with_structured_names(self):
        """Test junction table validation handles structured column names"""
        validator = RelationshipValidator()
        
        # Junction table with structured column names
        file_analyses = [
            FileAnalysis(
                file_path="Junction_Table.csv",
                file_name="Junction_Table",
                column_count=3,
                row_count=10, 
                columns=[
                    "Junction_Table::primary_fk_col",
                    "Junction_Table::secondary_fk_col", 
                    "Junction_Table::context_attr"
                ],
                column_types={},
                matched_dataset_name="Junction_Table"
            )
        ]
        
        relationship_contexts = [
            {
                'context_id': 'ctx_1',
                'dataset': 'Junction_Table',
                'primary_fk': 'primary_fk_col',  # Should match "Junction_Table::primary_fk_col"
                'secondary_fk': 'secondary_fk_col',  # Should match "Junction_Table::secondary_fk_col" 
                'context_columns': ['context_attr']  # Should match "Junction_Table::context_attr"
            }
        ]
        
        # Run validation
        result = validator.validate_relationship_contexts(relationship_contexts, file_analyses)
        
        # Should be valid
        assert result['valid'] is True, f"Context validation should pass but found issues: {result['issues']}"
        assert len(result['issues']) == 0, f"Expected no issues but found: {result['issues']}"