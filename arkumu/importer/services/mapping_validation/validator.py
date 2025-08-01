"""
Centralized validation service for all mapping-related validation.

This module provides a single source of truth for validation rules across the application,
eliminating duplication and ensuring consistent validation logic.
"""

import logging
import os
from typing import Dict, List, Optional, Any, Tuple, Set
from pathlib import Path
import csv
import json
import io
import urllib3.exceptions
from botocore.exceptions import ClientError

from arkumu.storage.services.bucket_service import BucketService
# Validation enums and classes (previously from validation_result module)
from enum import Enum

class ValidationSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

class ValidationCategory(Enum):
    FILE_STRUCTURE = "file_structure"
    COLUMN_MAPPING = "column_mapping"
    DATA_TYPE = "data_type"
    RELATIONSHIP = "relationship"
    COMPLETENESS = "completeness"

class ValidationErrorCodes(Enum):
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    INVALID_FORMAT = "INVALID_FORMAT"
    MISSING_COLUMN = "MISSING_COLUMN"
    TYPE_MISMATCH = "TYPE_MISMATCH"
    INVALID_RELATIONSHIP = "INVALID_RELATIONSHIP"
    INCOMPLETE_MAPPING = "INCOMPLETE_MAPPING"

class ValidationIssue:
    def __init__(self, severity: ValidationSeverity, category: ValidationCategory, 
                 error_code: ValidationErrorCodes, message: str, details: dict = None):
        self.severity = severity
        self.category = category
        self.error_code = error_code
        self.message = message
        self.details = details or {}

logger = logging.getLogger(__name__)


class MappingValidator:
    """
    Centralized validation service for all mapping-related validation.
    This is a stateless service that can be used by any component.
    """
    
    def __init__(self):
        """Initialize the mapping validator."""
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.bucket_service = BucketService()
        
        # Configuration
        self.max_file_size = 500 * 1024 * 1024  # 500MB
        self.supported_encodings = ['utf-8', 'latin1', 'cp1252']
        self.supported_delimiters = [',', ';', '\t', '|']
    
    @staticmethod
    def iterate_workspace_columns(workspace_columns):
        """
        Utility method to safely iterate through workspace_columns in either dict or list format.
        
        Args:
            workspace_columns: Can be dict or list format
            
        Yields:
            Tuple of (col_id, col_config) for each column
        """
        if isinstance(workspace_columns, dict):
            for col_id, col_config in workspace_columns.items():
                if isinstance(col_config, dict):
                    yield col_id, col_config
        elif isinstance(workspace_columns, list):
            for i, col_config in enumerate(workspace_columns):
                if isinstance(col_config, dict):
                    yield str(i), col_config

    @staticmethod
    def validate_column_mappings(workspace_columns: Dict[str, Any], 
                               file_columns: List[str]) -> Dict[str, Any]:
        """
        Validate column mappings between workspace and files.
        
        Args:
            workspace_columns: Dictionary of workspace column configurations
            file_columns: List of column names from files
            
        Returns:
            Dict containing validation results with keys:
                - mapped_columns: Dict of mapped column names to their configurations
                - unmapped_columns: List of file columns not mapped
                - missing_required_columns: List of workspace columns not found in files
                - coverage_percentage: Percentage of file columns that are mapped
                - issues: List of validation issues found
        """
        logger.info(f"Validating column mappings: {len(workspace_columns)} workspace columns, {len(file_columns)} file columns")
        
        # Initialize result structure
        result = {
            'mapped_columns': {},
            'unmapped_columns': [],
            'missing_required_columns': [],
            'coverage_percentage': 0.0,
            'issues': []
        }
        
        # Convert file columns to set for efficient lookup
        file_columns_set = set(file_columns)
        workspace_column_names = set()
        
        # Process workspace columns using the utility method
        for col_id, col_config in MappingValidator.iterate_workspace_columns(workspace_columns):
            col_name = col_config.get('name', '')
            if col_name:
                workspace_column_names.add(col_name)
                
                # Check if column exists in files
                if col_name in file_columns_set:
                    result['mapped_columns'][col_name] = col_config
                else:
                    result['missing_required_columns'].append(col_name)
                    result['issues'].append({
                        'code': 'REQUIRED_COLUMN_MISSING',
                        'severity': 'ERROR',
                        'category': 'COLUMN_MAPPING',
                        'message': f'Required column missing from files: {col_name}',
                        'column_name': col_name,
                        'suggested_fix': 'Add the missing column to the data files or remove it from the mapping'
                    })
        
        # Find unmapped columns
        result['unmapped_columns'] = list(file_columns_set - workspace_column_names)
        
        # Add warnings for unmapped columns
        for unmapped_col in result['unmapped_columns']:
            result['issues'].append({
                'code': 'UNMAPPED_COLUMN',
                'severity': 'WARNING',
                'category': 'COLUMN_MAPPING',
                'message': f'Column not mapped: {unmapped_col}',
                'column_name': unmapped_col,
                'suggested_fix': 'Consider mapping this column if it contains useful data'
            })
        
        # Calculate coverage percentage
        if file_columns:
            result['coverage_percentage'] = (len(result['mapped_columns']) / len(file_columns)) * 100
        
        logger.info(f"Column mapping validation complete: {len(result['mapped_columns'])} mapped, "
                   f"{len(result['unmapped_columns'])} unmapped, "
                   f"{len(result['missing_required_columns'])} missing")
        
        return result
    
    @staticmethod
    def validate_relationships(workspace_columns: Dict[str, Any], 
                             fk_relationships: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Validate foreign key relationships.
        
        Args:
            workspace_columns: Dictionary of workspace column configurations
            fk_relationships: Dictionary of foreign key relationship configurations
            
        Returns:
            List of validation issues found
        """
        issues = []
        
        for fk_column_id, fk_config in fk_relationships.items():
            # Validate that FK column exists in workspace
            if fk_column_id not in workspace_columns:
                issues.append({
                    'code': 'FK_COLUMN_NOT_FOUND',
                    'severity': 'ERROR',
                    'category': 'RELATIONSHIP',
                    'message': f'Foreign key column not found in workspace: {fk_column_id}',
                    'column_name': fk_column_id,
                    'suggested_fix': 'Ensure the foreign key column is added to the workspace'
                })
                continue
            
            # Validate FK configuration
            target_dataset = fk_config.get('target_dataset')
            target_column = fk_config.get('target_column')
            
            if not target_dataset:
                issues.append({
                    'code': 'FK_MISSING_TARGET_DATASET',
                    'severity': 'ERROR',
                    'category': 'RELATIONSHIP',
                    'message': f'Foreign key configuration missing target dataset: {fk_column_id}',
                    'column_name': fk_column_id,
                    'suggested_fix': 'Specify the target dataset for this foreign key'
                })
            
            if not target_column:
                issues.append({
                    'code': 'FK_MISSING_TARGET_COLUMN',
                    'severity': 'ERROR',
                    'category': 'RELATIONSHIP',
                    'message': f'Foreign key configuration missing target column: {fk_column_id}',
                    'column_name': fk_column_id,
                    'suggested_fix': 'Specify the target column for this foreign key'
                })
        
        return issues
    
    def validate_file_structure(self, file_path: str, organization_code: str) -> List[Dict[str, Any]]:
        """
        Validate file structure, encoding, readability.
        
        Args:
            file_path: Path to the file to validate (can be S3 path)
            organization_code: Organization code for S3 bucket access
            
        Returns:
            List of validation issues found
        """
        issues = []
        
        try:
            # Determine if this is an S3 path
            is_s3_path = self._is_s3_path(file_path)
            
            if is_s3_path:
                # Validate S3 file
                bucket_name = self.bucket_service.get_organization_bucket(organization_code)
                file_exists, file_size = self._check_s3_file_exists(bucket_name, file_path)
                
                if not file_exists:
                    issues.append({
                        'code': 'FILE_NOT_FOUND',
                        'severity': 'ERROR',
                        'category': 'FILE_STRUCTURE',
                        'message': f'File not found in S3: {file_path}',
                        'file_path': file_path
                    })
                    return issues
                
                if file_size == 0:
                    issues.append({
                        'code': 'FILE_EMPTY',
                        'severity': 'ERROR',
                        'category': 'FILE_STRUCTURE',
                        'message': f'File is empty: {file_path}',
                        'file_path': file_path
                    })
                    return issues
                
                if file_size > self.max_file_size:
                    issues.append({
                        'code': 'FILE_TOO_LARGE',
                        'severity': 'WARNING',
                        'category': 'FILE_STRUCTURE',
                        'message': f'File is too large: {file_size / (1024*1024):.1f}MB',
                        'file_path': file_path,
                        'suggested_fix': 'Consider splitting the file into smaller chunks'
                    })
            else:
                # Validate local file
                if not os.path.exists(file_path):
                    issues.append({
                        'code': 'FILE_NOT_FOUND',
                        'severity': 'ERROR',
                        'category': 'FILE_STRUCTURE',
                        'message': f'File not found: {file_path}',
                        'file_path': file_path
                    })
                    return issues
                
                if not os.access(file_path, os.R_OK):
                    issues.append({
                        'code': 'FILE_NOT_READABLE',
                        'severity': 'ERROR',
                        'category': 'FILE_STRUCTURE',
                        'message': f'File not readable: {file_path}',
                        'file_path': file_path
                    })
                    return issues
                
                file_size = os.path.getsize(file_path)
                if file_size == 0:
                    issues.append({
                        'code': 'FILE_EMPTY',
                        'severity': 'ERROR',
                        'category': 'FILE_STRUCTURE',
                        'message': f'File is empty: {file_path}',
                        'file_path': file_path
                    })
                    return issues
                
                if file_size > self.max_file_size:
                    issues.append({
                        'code': 'FILE_TOO_LARGE',
                        'severity': 'WARNING',
                        'category': 'FILE_STRUCTURE',
                        'message': f'File is too large: {file_size / (1024*1024):.1f}MB',
                        'file_path': file_path,
                        'suggested_fix': 'Consider splitting the file into smaller chunks'
                    })
            
            # Validate file format
            file_extension = Path(file_path).suffix.lower()
            if file_extension not in ['.csv', '.tsv', '.txt', '.json']:
                issues.append({
                    'code': 'INVALID_FILE_FORMAT',
                    'severity': 'WARNING',
                    'category': 'FILE_STRUCTURE',
                    'message': f'Unsupported file format: {file_extension}',
                    'file_path': file_path
                })
            
        except Exception as e:
            self.logger.error(f"File structure validation failed for {file_path}: {str(e)}")
            issues.append({
                'code': 'VALIDATION_FAILED',
                'severity': 'ERROR',
                'category': 'FILE_STRUCTURE',
                'message': f'Validation failed: {str(e)}',
                'file_path': file_path,
                'details': {'exception': str(e)}
            })
        
        return issues
    
    @staticmethod
    def validate_data_types(workspace_columns: Dict[str, Any], 
                          sample_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Validate data types match expectations.
        
        Args:
            workspace_columns: Dictionary of workspace column configurations
            sample_data: Sample data rows to validate types against
            
        Returns:
            List of validation issues found
        """
        issues = []
        
        if not sample_data:
            return issues
        
        # Check each column's data type
        for col_id, col_config in workspace_columns.items():
            if not isinstance(col_config, dict):
                continue
                
            col_name = col_config.get('name', '')
            expected_type = col_config.get('type', 'string')
            
            if not col_name:
                continue
            
            # Sample values from the data
            values = []
            for row in sample_data[:10]:  # Check first 10 rows
                if col_name in row:
                    values.append(row[col_name])
            
            if not values:
                continue
            
            # Type validation
            if expected_type == 'integer':
                for val in values:
                    if val and not isinstance(val, int):
                        try:
                            int(val)
                        except (ValueError, TypeError):
                            issues.append({
                                'code': 'TYPE_MISMATCH',
                                'severity': 'WARNING',
                                'category': 'DATA_TYPE',
                                'message': f'Column {col_name} expected integer but found: {type(val).__name__}',
                                'column_name': col_name,
                                'suggested_fix': f'Convert values to integer or change column type'
                            })
                            break
            
            elif expected_type == 'float':
                for val in values:
                    if val and not isinstance(val, (int, float)):
                        try:
                            float(val)
                        except (ValueError, TypeError):
                            issues.append({
                                'code': 'TYPE_MISMATCH',
                                'severity': 'WARNING',
                                'category': 'DATA_TYPE',
                                'message': f'Column {col_name} expected float but found: {type(val).__name__}',
                                'column_name': col_name,
                                'suggested_fix': f'Convert values to float or change column type'
                            })
                            break
            
            elif expected_type == 'boolean':
                for val in values:
                    if val and str(val).lower() not in ['true', 'false', '1', '0', 'yes', 'no']:
                        issues.append({
                            'code': 'TYPE_MISMATCH',
                            'severity': 'WARNING',
                            'category': 'DATA_TYPE',
                            'message': f'Column {col_name} expected boolean but found: {val}',
                            'column_name': col_name,
                            'suggested_fix': f'Convert values to boolean format or change column type'
                        })
                        break
        
        return issues
    
    @staticmethod
    def validate_mapping_completeness(mapping_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate mapping has all required components.
        
        Args:
            mapping_config: Complete mapping configuration
            
        Returns:
            Dict containing validation results with keys:
                - is_complete: Boolean indicating if mapping is complete
                - missing_components: List of missing required components
                - issues: List of validation issues found
        """
        result = {
            'is_complete': True,
            'missing_components': [],
            'issues': []
        }
        
        # Check required top-level components
        required_components = ['workspace_columns', 'organization_id']
        
        for component in required_components:
            if component not in mapping_config or not mapping_config[component]:
                result['is_complete'] = False
                result['missing_components'].append(component)
                result['issues'].append({
                    'code': 'MISSING_CONFIGURATION',
                    'severity': 'ERROR',
                    'category': 'CONFIGURATION',
                    'message': f'Missing required component: {component}',
                    'suggested_fix': f'Add {component} to the mapping configuration'
                })
        
        # Check workspace columns structure
        if 'workspace_columns' in mapping_config:
            workspace_columns = mapping_config['workspace_columns']
            if not isinstance(workspace_columns, (dict, list)):
                result['is_complete'] = False
                result['issues'].append({
                    'code': 'INVALID_CONFIGURATION',
                    'severity': 'ERROR',
                    'category': 'CONFIGURATION',
                    'message': 'workspace_columns must be a dictionary or list',
                    'suggested_fix': 'Ensure workspace_columns is properly formatted'
                })
            elif not workspace_columns:
                result['is_complete'] = False
                result['issues'].append({
                    'code': 'EMPTY_CONFIGURATION',
                    'severity': 'ERROR',
                    'category': 'CONFIGURATION',
                    'message': 'No columns defined in workspace',
                    'suggested_fix': 'Add at least one column to the mapping'
                })
        
        # Check for at least one mapped column
        if 'workspace_columns' in mapping_config and mapping_config['workspace_columns']:
            has_mapped_column = False
            columns = mapping_config['workspace_columns']
            
            if isinstance(columns, dict):
                has_mapped_column = any(
                    isinstance(col, dict) and col.get('name') 
                    for col in columns.values()
                )
            elif isinstance(columns, list):
                has_mapped_column = any(
                    isinstance(col, dict) and col.get('name') 
                    for col in columns
                )
            
            if not has_mapped_column:
                result['is_complete'] = False
                result['issues'].append({
                    'code': 'NO_MAPPED_COLUMNS',
                    'severity': 'ERROR',
                    'category': 'CONFIGURATION',
                    'message': 'No valid column mappings found',
                    'suggested_fix': 'Define at least one column mapping'
                })
        
        return result
    
    def _is_s3_path(self, file_path: str) -> bool:
        """Check if the file path is an S3 path."""
        return file_path.startswith('s3://') or file_path.startswith('/') and 'metadata/' in file_path
    
    def _check_s3_file_exists(self, bucket_name: str, file_path: str) -> Tuple[bool, int]:
        """
        Check if an S3 file exists and get its size.
        
        Returns:
            Tuple of (exists, size_in_bytes)
        """
        try:
            # Clean up the file path
            if file_path.startswith('s3://'):
                # Extract key from s3:// URL
                parts = file_path.replace('s3://', '').split('/', 1)
                if len(parts) > 1:
                    file_path = parts[1]
            elif file_path.startswith('/'):
                file_path = file_path.lstrip('/')
            
            # Get file info from S3
            s3_client = self.bucket_service.get_s3_client()
            response = s3_client.head_object(Bucket=bucket_name, Key=file_path)
            
            return True, response.get('ContentLength', 0)
        except urllib3.exceptions.HeaderParsingError:
            # MinIO header parsing fallback - try list_objects_v2
            try:
                s3_client = self.bucket_service.get_s3_client()
                list_response = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=file_path, MaxKeys=1)
                objects = list_response.get('Contents', [])
                if objects and objects[0]['Key'] == file_path:
                    return True, objects[0].get('Size', 0)
                else:
                    return False, 0
            except Exception as fallback_e:
                self.logger.debug(f"S3 fallback check failed for {file_path}: {str(fallback_e)}")
                return False, 0
        except Exception as e:
            self.logger.debug(f"S3 file check failed for {file_path}: {str(e)}")
            return False, 0