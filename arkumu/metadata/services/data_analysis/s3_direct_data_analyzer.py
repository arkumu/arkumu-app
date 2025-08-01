"""
S3 Direct Data Analysis Service

Efficiently analyzes data source files in S3 buckets using Polars
without importing them into the database first. Provides fast table previews,
column analysis, and relationship discovery directly from S3 files.

This approach is more memory-efficient and faster than reconstructing
data from the database after import. Integrates with the existing BucketService
architecture following the same pattern as the archivist dashboard.
"""

import logging
import polars as pl
import io
from typing import Dict, List, Any, Optional, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime
import tempfile
import os
import urllib3.exceptions
from botocore.exceptions import ClientError

from arkumu.storage.services.bucket_service import BucketService
# SmartBulkUpdaterPolars removed - using modular services instead
from arkumu.metadata.services.relationship_discovery import RelationshipDiscoveryService
# BulkDataAnalyzer removed - functionality integrated into S3DirectDataAnalyzer

logger = logging.getLogger(__name__)


@dataclass
class S3DataSourceInfo:
    """Information about a data source file in S3."""
    bucket_name: str
    object_key: str
    name: str  # File name without extension
    format: str  # 'csv', 'excel', 'parquet', etc.
    size_bytes: Optional[int] = None
    modified_date: Optional[datetime] = None
    sheet_names: Optional[List[str]] = None  # For Excel files


@dataclass
class S3TablePreview:
    """Preview data for a table/dataset from S3."""
    column_headers: List[str]
    data_rows: List[List[Any]]
    total_rows: int
    showing_rows: int
    offset: int
    has_more: bool
    column_types: Dict[str, str]
    sample_size: int
    multi_value_columns: Dict[str, Dict[str, Any]] = field(default_factory=dict)


@dataclass
class S3DatasetAnalysis:
    """Complete analysis of a dataset from S3."""
    source_info: S3DataSourceInfo
    row_count: int
    column_count: int
    column_types: Dict[str, str]
    preview: S3TablePreview
    multi_value_analysis: Dict[str, Dict[str, Any]]
    data_quality_metrics: Dict[str, Any]
    suggested_import_strategy: str
    relationship_analysis: Optional[Dict[str, Any]] = None


class S3DirectDataAnalyzer:
    """
    Service for directly analyzing S3 data files using Polars.
    
    Provides efficient table previews, column analysis, and relationship
    discovery without importing data into the database first.
    Integrates with the existing BucketService architecture.
    """
    
    def __init__(self, 
                 default_preview_rows: int = 50,
                 sample_size_for_analysis: int = 1000):
        """
        Initialize the S3 direct data analyzer.
        
        Args:
            default_preview_rows: Default number of rows to show in previews
            sample_size_for_analysis: Sample size for column type inference and analysis
        """
        self.default_preview_rows = default_preview_rows
        self.sample_size_for_analysis = sample_size_for_analysis
        
        # Initialize services for S3 access and analysis
        self.bucket_service = BucketService()
        self.relationship_service = RelationshipDiscoveryService()
        # Note: BulkDataAnalyzer functionality integrated into S3DirectDataAnalyzer
        
        # Initialize bulk updater only when needed (lazy initialization)
        self._bulk_updater = None
    
    def _safe_head_object(self, bucket_name: str, s3_key: str) -> Dict[str, Any]:
        """
        Safely perform head_object call with fallback for MinIO header parsing issues.
        
        Args:
            bucket_name: S3 bucket name
            s3_key: S3 object key
            
        Returns:
            Dictionary with object metadata or None if failed
        """
        try:
            s3_client = self.bucket_service.base_s3_service.s3_client
            return s3_client.head_object(
                Bucket=bucket_name,
                Key=s3_key
            )
        except urllib3.exceptions.HeaderParsingError as e:
            logger.warning(f"MinIO header parsing error for {s3_key}: {e}")
            # For empty files, MinIO sometimes has header parsing issues
            # Try to get object info via list_objects_v2 as fallback
            try:
                s3_client = self.bucket_service.base_s3_service.s3_client
                response = s3_client.list_objects_v2(
                    Bucket=bucket_name,
                    Prefix=s3_key,
                    MaxKeys=1
                )
                objects = response.get('Contents', [])
                if objects and objects[0]['Key'] == s3_key:
                    obj = objects[0]
                    return {
                        'ContentLength': obj.get('Size', 0),
                        'LastModified': obj.get('LastModified'),
                        'ETag': obj.get('ETag', ''),
                        'ContentType': 'application/octet-stream',
                        'Metadata': {}
                    }
                else:
                    logger.error(f"Object {s3_key} not found in fallback list_objects_v2")
                    return None
            except ClientError as fallback_e:
                logger.error(f"Fallback list_objects_v2 also failed for {s3_key}: {fallback_e}")
                return None
        except ClientError as e:
            # Let ClientError bubble up as it's expected for 404s, etc.
            raise e
    
    @property
    def bulk_updater(self):
        """Lazy initialization of bulk updater only when needed."""
        if self._bulk_updater is None:
            from arkumu.importer.services.execution.execution_engine import MappingExecutionEngine
            self._bulk_updater = MappingExecutionEngine(
                organization_id="default",
                base_uri="http://arkumu.org/data"
            )
        return self._bulk_updater
    
    def discover_s3_data_sources(self, organization_id: str) -> List[S3DataSourceInfo]:
        """
        Discover all available data source files in an organization's S3 bucket.
        
        Args:
            organization_id: Organization ID to determine the S3 bucket
            
        Returns:
            List of S3DataSourceInfo objects for discovered files
        """
        sources = []
        
        supported_extensions = {
            '.csv': 'csv',
            '.xlsx': 'excel', 
            '.xls': 'excel',
            '.parquet': 'parquet',
            '.json': 'json',
            '.jsonl': 'jsonl'
        }
        
        try:
            # Get the bucket name for this organization
            bucket_name = self.bucket_service.get_organization_bucket(organization_id)
            logger.info(f"Discovering data sources in bucket: {bucket_name}")
            
            # Use the existing organization browsing infrastructure
            # Get all files through the same method as the archivist dashboard
            s3_objects = self._get_all_files_in_organization(organization_id)
            
            for s3_obj in s3_objects:
                # Handle the format returned by BucketService.list_bucket_contents
                logger.info(f"Processing S3 object: {s3_obj}")
                
                if s3_obj.get('type') != 'file':
                    logger.info(f"Skipping non-file item: {s3_obj.get('name', 'unknown')} (type: {s3_obj.get('type')})")
                    continue  # Skip folders
                    
                object_key = s3_obj['path']  # BucketService uses 'path' instead of 'Key'
                file_name = s3_obj['name']   # BucketService provides 'name' directly
                name, ext = os.path.splitext(file_name)
                
                logger.info(f"File analysis: name='{name}', ext='{ext}', size={s3_obj.get('size', 0)}")
                
                # Skip mapping configuration files - these are not datasets
                if self._is_mapping_config_file(object_key, name):
                    logger.info(f"Skipping mapping config file: {file_name}")
                    continue
                
                if ext.lower() in supported_extensions and s3_obj.get('size', 0) > 0:
                    try:
                        source_info = S3DataSourceInfo(
                            bucket_name=bucket_name,
                            object_key=object_key,
                            name=name,
                            format=supported_extensions[ext.lower()],
                            size_bytes=s3_obj.get('size'),  # BucketService uses 'size'
                            modified_date=s3_obj.get('last_modified')  # BucketService uses 'last_modified'
                        )
                        
                        # For Excel files, get sheet names (this requires downloading metadata)
                        if source_info.format == 'excel':
                            try:
                                sheet_names = self._get_excel_sheet_names(bucket_name, object_key)
                                source_info.sheet_names = sheet_names
                            except Exception as e:
                                logger.warning(f"Could not read Excel sheet names from {object_key}: {e}")
                        
                        sources.append(source_info)
                        logger.info(f"Added source: {source_info.name} (format: {source_info.format})")
                        
                    except Exception as e:
                        logger.warning(f"Could not analyze S3 object {object_key}: {e}")
                else:
                    logger.info(f"Skipping file: {file_name} (ext: {ext}, size: {s3_obj.get('size', 0)}, supported: {ext.lower() in supported_extensions})")
        
        except Exception as e:
            logger.error(f"Error discovering S3 data sources for organization {organization_id}: {e}")
        
        logger.info(f"Total sources found: {len(sources)}")
        return sorted(sources, key=lambda x: x.name)
    
    def _is_mapping_config_file(self, object_key: str, file_name: str) -> bool:
        """
        Determine if a file is a mapping configuration file that should be excluded 
        from data source discovery.
        
        Args:
            object_key: Full S3 object key/path
            file_name: Just the file name
            
        Returns:
            True if this is a mapping config file, False if it's a data file
        """
        # Be very specific - only skip actual mapping configuration files
        # NOT all files in metadata/ since that's where datasets live too
        
        # Skip specific mapping config files by name pattern
        if file_name.endswith('_mapping.json') or file_name.endswith('_mapping.yaml'):
            return True
            
        # Skip HTML error/log files
        if file_name.endswith('.html') and ('error' in file_name.lower() or 'log' in file_name.lower()):
            return True
            
        # Skip hidden/system files
        if file_name.startswith('.'):
            return True
            
        # Skip system/config directories only - not metadata directories
        system_paths = ['config/', 'configs/', '.arkumu/', 'system/', 'admin/']
        if any(config_path in object_key for config_path in system_paths):
            return True
            
        return False
    
    def _get_all_files_in_organization(self, organization_id: str) -> List[Dict[str, Any]]:
        """
        Get all files for an organization using the same logic as the archivist dashboard.
        This leverages the existing file browsing infrastructure.
        
        Args:
            organization_id: Organization ID
            
        Returns:
            List of file objects with standardized format
        """
        try:
            # Use the existing organization browsing method from BucketService
            # This follows the same pattern as the archivist dashboard
            org_data = self.bucket_service.get_root_level_items(organization_id)
            
            all_files = []
            
            # Get files from root level
            root_files = org_data.get('files', [])
            for file_info in root_files:
                # Convert to the format expected by the rest of the method
                all_files.append({
                    'name': file_info['name'],
                    'path': file_info['path'], 
                    'type': 'file',
                    'size': file_info['size'],
                    'last_modified': file_info.get('last_modified')
                })
            
            # For folders, we need to browse them too
            # This is where we leverage the existing infrastructure
            folders = org_data.get('folders', [])
            for folder_info in folders:
                folder_path = folder_info['path']
                logger.info(f"Scanning folder: {folder_path}")
                
                # Get the bucket name for this organization
                bucket_name = self.bucket_service.get_organization_bucket(organization_id)
                
                # Get files from this folder
                folder_contents = self.bucket_service.list_bucket_contents(bucket_name, folder_path)
                for item in folder_contents:
                    if item.get('type') == 'file':
                        all_files.append(item)
            
            logger.info(f"Found {len(all_files)} total files for organization {organization_id}")
            return all_files
            
        except Exception as e:
            logger.error(f"Error getting files for organization {organization_id}: {e}")
            return []
    
    def get_dataset_names_from_s3_source(self, source_info: S3DataSourceInfo) -> List[str]:
        """
        Get dataset names from an S3 source file.
        For single-sheet files: returns [source_name]
        For multi-sheet Excel: returns sheet names
        
        Args:
            source_info: Information about the S3 data source
            
        Returns:
            List of dataset names available in this source
        """
        if source_info.format == 'excel' and source_info.sheet_names:
            return source_info.sheet_names
        else:
            return [source_info.name]
    
    def _get_excel_sheet_names(self, bucket_name: str, object_key: str) -> List[str]:
        """Get sheet names from an Excel file in S3."""
        # Download a small portion or use a temporary file to read Excel metadata
        with tempfile.NamedTemporaryFile(suffix='.xlsx') as temp_file:
            self.bucket_service.base_s3_service.s3_client.download_file(
                bucket_name, object_key, temp_file.name
            )
            
            # Use openpyxl or xlrd to read sheet names without loading data
            try:
                import openpyxl
                workbook = openpyxl.load_workbook(temp_file.name, read_only=True)
                return workbook.sheetnames
            except ImportError:
                # Fallback to pandas/polars if openpyxl not available
                df_dict = pl.read_excel(temp_file.name, sheet_name=None)
                return list(df_dict.keys()) if isinstance(df_dict, dict) else [object_key]
    
    def _read_s3_source_lazy(self, 
                           source_info: S3DataSourceInfo, 
                           dataset_name: Optional[str] = None,
                           max_rows_for_schema: Optional[int] = None) -> pl.LazyFrame:
        """
        Create a lazy frame for reading S3 data efficiently.
        
        Args:
            source_info: Information about the S3 data source
            dataset_name: For Excel files, the sheet name to read
            max_rows_for_schema: Limit rows read for schema inference
            
        Returns:
            Polars LazyFrame for efficient data processing
        """
        # Download file to temporary location for processing
        with tempfile.NamedTemporaryFile(suffix=f'.{source_info.format}', delete=False) as temp_file:
            temp_file_path = temp_file.name
            
        try:
            # Download the file from S3
            self.bucket_service.base_s3_service.s3_client.download_file(
                source_info.bucket_name, 
                source_info.object_key, 
                temp_file_path
            )
            
            if source_info.format == 'csv':
                # Use semicolon delimiter as default (following import_metadata.py pattern)
                # For large files, limit schema inference to improve performance
                n_rows = max_rows_for_schema if max_rows_for_schema else self.sample_size_for_analysis
                return pl.scan_csv(
                    temp_file_path, 
                    separator=';',  # Use semicolon as default like import_metadata.py
                    infer_schema_length=n_rows,
                    ignore_errors=True  # Handle malformed rows gracefully
                )
            
            elif source_info.format == 'parquet':
                return pl.scan_parquet(temp_file_path)
            
            elif source_info.format == 'excel':
                # Excel requires eager reading, but we can still optimize
                sheet_name = dataset_name if dataset_name else 0
                df = pl.read_excel(temp_file_path, sheet_name=sheet_name)
                return df.lazy()
            
            elif source_info.format in ['json', 'jsonl']:
                # Determine if this is NDJSON or regular JSON
                try:
                    # Try reading as NDJSON first (more common for data files)
                    return pl.scan_ndjson(temp_file_path)
                except Exception as ndjson_error:
                    # If NDJSON fails, try reading as regular JSON
                    try:
                        import json
                        with open(temp_file_path, 'r') as f:
                            json_data = json.load(f)
                        
                        # Convert JSON to DataFrame format
                        if isinstance(json_data, list):
                            # JSON array of objects
                            df = pl.DataFrame(json_data)
                        elif isinstance(json_data, dict):
                            # Single JSON object - convert to single-row DataFrame
                            df = pl.DataFrame([json_data])
                        else:
                            raise ValueError(f"Unsupported JSON structure: {type(json_data)}")
                        
                        return df.lazy()
                    except Exception as json_error:
                        logger.error(f"Failed to parse both NDJSON and JSON formats: NDJSON error: {ndjson_error}, JSON error: {json_error}")
                        raise ndjson_error  # Re-raise original NDJSON error
            
            else:
                raise ValueError(f"Unsupported file format: {source_info.format}")
                
        except Exception as e:
            # Clean up temp file on error
            try:
                os.unlink(temp_file_path)
            except:
                pass
            raise e
        finally:
            # Clean up temp file after use
            try:
                os.unlink(temp_file_path)
            except:
                pass
    
    def _read_s3_source_eager_sample(self, 
                                   source_info: S3DataSourceInfo, 
                                   dataset_name: Optional[str] = None,
                                   n_rows: Optional[int] = None) -> pl.DataFrame:
        """
        Read a sample from S3 source as eager DataFrame for analysis.
        
        Args:
            source_info: Information about the S3 data source
            dataset_name: For Excel files, the sheet name to read
            n_rows: Number of rows to read (for sampling)
            
        Returns:
            Polars DataFrame with sample data
        """
        with tempfile.NamedTemporaryFile(suffix=f'.{source_info.format}', delete=False) as temp_file:
            temp_file_path = temp_file.name
            
        try:
            self.bucket_service.base_s3_service.s3_client.download_file(
                source_info.bucket_name, 
                source_info.object_key, 
                temp_file_path
            )
            
            if source_info.format == 'csv':
                return pl.read_csv(
                    temp_file_path, 
                    separator=';',  # Use semicolon as default like import_metadata.py
                    n_rows=n_rows,
                    ignore_errors=True  # Handle malformed rows gracefully
                )
            
            elif source_info.format == 'parquet':
                df = pl.read_parquet(temp_file_path)
                return df.head(n_rows) if n_rows else df
            
            elif source_info.format == 'excel':
                sheet_name = dataset_name if dataset_name else 0
                df = pl.read_excel(temp_file_path, sheet_name=sheet_name)
                return df.head(n_rows) if n_rows else df
            
            elif source_info.format in ['json', 'jsonl']:
                # Determine if this is NDJSON or regular JSON
                try:
                    # Try reading as NDJSON first (more common for data files)
                    df = pl.read_ndjson(temp_file_path)
                    return df.head(n_rows) if n_rows else df
                except Exception as ndjson_error:
                    # If NDJSON fails, try reading as regular JSON
                    try:
                        import json
                        with open(temp_file_path, 'r') as f:
                            json_data = json.load(f)
                        
                        # Convert JSON to DataFrame format
                        if isinstance(json_data, list):
                            # JSON array of objects
                            df = pl.DataFrame(json_data)
                        elif isinstance(json_data, dict):
                            # Single JSON object - convert to single-row DataFrame
                            df = pl.DataFrame([json_data])
                        else:
                            raise ValueError(f"Unsupported JSON structure: {type(json_data)}")
                        
                        return df.head(n_rows) if n_rows else df
                    except Exception as json_error:
                        logger.error(f"Failed to parse both NDJSON and JSON formats: NDJSON error: {ndjson_error}, JSON error: {json_error}")
                        raise ndjson_error  # Re-raise original NDJSON error
            
            else:
                raise ValueError(f"Unsupported file format: {source_info.format}")
                
        finally:
            # Clean up temp file
            try:
                os.unlink(temp_file_path)
            except:
                pass
    
    def _get_total_row_count_safe(self, 
                                 source_info: S3DataSourceInfo,
                                 dataset_name: Optional[str] = None) -> int:
        """
        Safely get total row count using temporary file with proper cleanup.
        Only used for very large datasets where sampling isn't sufficient.
        """
        with tempfile.NamedTemporaryFile(suffix=f'.{source_info.format}', delete=False) as temp_file:
            temp_file_path = temp_file.name
            
        try:
            # Download the file from S3
            self.bucket_service.base_s3_service.s3_client.download_file(
                source_info.bucket_name, 
                source_info.object_key, 
                temp_file_path
            )
            
            if source_info.format == 'csv':
                # Create lazy frame and immediately collect the count
                lazy_df = pl.scan_csv(
                    temp_file_path, 
                    separator=';',
                    ignore_errors=True
                )
                return lazy_df.select(pl.count()).collect().item()
            
            elif source_info.format == 'parquet':
                lazy_df = pl.scan_parquet(temp_file_path)
                return lazy_df.select(pl.count()).collect().item()
            
            elif source_info.format == 'excel':
                sheet_name = dataset_name if dataset_name else 0
                df = pl.read_excel(temp_file_path, sheet_name=sheet_name)
                return len(df)
            
            elif source_info.format in ['json', 'jsonl']:
                # Determine if this is NDJSON or regular JSON
                try:
                    # Try reading as NDJSON first (more common for data files)
                    lazy_df = pl.scan_ndjson(temp_file_path)
                    return lazy_df.select(pl.count()).collect().item()
                except Exception as ndjson_error:
                    # If NDJSON fails, try reading as regular JSON
                    try:
                        import json
                        with open(temp_file_path, 'r') as f:
                            json_data = json.load(f)
                        
                        # Convert JSON to DataFrame format
                        if isinstance(json_data, list):
                            # JSON array of objects
                            return len(json_data)
                        elif isinstance(json_data, dict):
                            # Single JSON object - one row
                            return 1
                        else:
                            raise ValueError(f"Unsupported JSON structure: {type(json_data)}")
                    except Exception as json_error:
                        logger.error(f"Failed to parse both NDJSON and JSON formats: NDJSON error: {ndjson_error}, JSON error: {json_error}")
                        raise ndjson_error  # Re-raise original NDJSON error
            
            else:
                raise ValueError(f"Unsupported file format: {source_info.format}")
                
        finally:
            # Always clean up temp file
            try:
                os.unlink(temp_file_path)
            except:
                pass
    
    def get_s3_table_preview(self, 
                           source_info: S3DataSourceInfo,
                           dataset_name: Optional[str] = None,
                           offset: int = 0,
                           limit: Optional[int] = None,
                           skip_analysis: bool = False) -> S3TablePreview:
        """
        Get a preview of table data from S3 without loading the entire dataset.
        
        Args:
            source_info: Information about the S3 data source
            dataset_name: For multi-dataset sources (Excel sheets)
            offset: Number of rows to skip
            limit: Maximum number of rows to return
            skip_analysis: If True, skip expensive multi-value analysis (for lazy loading)
            
        Returns:
            S3TablePreview with requested data slice
        """
        if limit is None:
            limit = self.default_preview_rows
        
        try:
            # Read a larger sample to get accurate total row count and schema
            # Use a larger sample size that's likely to capture the full dataset
            large_sample_size = max(10000, limit + offset + 1000)  # Read more to get accurate count
            sample_df = self._read_s3_source_eager_sample(source_info, dataset_name, n_rows=large_sample_size)
            
            # If we got fewer rows than requested, we have the full dataset
            if len(sample_df) < large_sample_size:
                total_rows = len(sample_df)  # This is the actual total
            else:
                # For very large datasets, fall back to lazy count with proper temp file handling
                total_rows = self._get_total_row_count_safe(source_info, dataset_name)
            
            column_headers = list(sample_df.columns)
            column_types = {col: str(dtype) for col, dtype in sample_df.schema.items()}
            
            # Apply offset and limit to the sample we already read
            preview_df = sample_df.slice(offset, limit)
            
            # Convert to list of lists for template compatibility (avoiding pandas dependency)
            # Ensure we're returning lists, not tuples (which Polars might return)
            data_rows = [list(row) for row in preview_df.fill_null("").rows()]
            
            # Conditionally analyze multi-value columns (skip for lazy loading)
            if not skip_analysis:
                # Take a smaller subset for analysis if needed
                analysis_sample_df = sample_df.head(self.sample_size_for_analysis)
                sample_data = analysis_sample_df.to_dicts()
                # Multi-value analysis integrated into S3DirectDataAnalyzer
                multi_value_analysis = self._analyze_multi_values_simple(analysis_sample_df)
            else:
                # Skip expensive analysis for lazy loading
                sample_data = []
                multi_value_analysis = {}
            
            return S3TablePreview(
                column_headers=column_headers,
                data_rows=data_rows,
                total_rows=total_rows,
                showing_rows=len(data_rows),
                offset=offset,
                has_more=(offset + len(data_rows)) < total_rows,
                column_types=column_types,
                sample_size=len(sample_data),
                multi_value_columns=multi_value_analysis
            )
            
        except Exception as e:
            logger.error(f"Error getting S3 table preview for {source_info.object_key}: {e}")
            raise
    
    def analyze_s3_dataset_completely(self, 
                                    source_info: S3DataSourceInfo,
                                    dataset_name: Optional[str] = None,
                                    include_relationships: bool = True) -> S3DatasetAnalysis:
        """
        Perform complete analysis of a dataset from S3 including relationships.
        
        Args:
            source_info: Information about the S3 data source
            dataset_name: For multi-dataset sources
            include_relationships: Whether to analyze relationships (expensive)
            
        Returns:
            Complete S3DatasetAnalysis
        """
        try:
            # Get basic statistics using eager reading (like CSV mapping editor)
            sample_df = self._read_s3_source_eager_sample(
                source_info, dataset_name, n_rows=self.sample_size_for_analysis
            )
            
            # For large files, get accurate total count safely
            if len(sample_df) >= self.sample_size_for_analysis:
                total_rows = self._get_total_row_count_safe(source_info, dataset_name)
            else:
                total_rows = len(sample_df)
            
            schema = sample_df.schema
            column_count = len(schema)
            column_types = {col: str(dtype) for col, dtype in schema.items()}
            
            # Get preview data using the sample we already have
            column_headers = list(sample_df.columns)
            preview_rows = min(self.default_preview_rows, len(sample_df))
            preview_df = sample_df.head(preview_rows)
            data_rows = [list(row) for row in preview_df.fill_null("").rows()]
            
            # Create preview object
            preview = S3TablePreview(
                column_headers=column_headers,
                data_rows=data_rows,
                total_rows=total_rows,
                showing_rows=len(data_rows),
                offset=0,
                has_more=preview_rows < total_rows,
                column_types=column_types,
                sample_size=len(sample_df),
                multi_value_columns={}  # Will be filled below
            )
            
            # Use the sample we already have for detailed analysis
            sample_data = sample_df.to_dicts()
            
            # Multi-value analysis
            multi_value_analysis = self._analyze_multi_values_simple(sample_df)
            
            # Update preview with multi-value analysis
            preview.multi_value_columns = multi_value_analysis
            
            # Data quality metrics
            quality_metrics = self._calculate_data_quality_metrics(sample_df)
            
            # Import strategy suggestion
            suggested_strategy = self._suggest_import_strategy(
                total_rows, multi_value_analysis, quality_metrics
            )
            
            # Relationship analysis (optional, expensive)
            relationship_analysis = None
            if include_relationships and total_rows <= 10000:  # Only for reasonably sized datasets
                try:
                    # Convert to format expected by relationship service
                    temp_files = self._create_temp_csv_for_analysis(sample_data, dataset_name or source_info.name)
                    relationship_analysis = self.relationship_service.compare_datasets_relationships(temp_files)
                    
                    # Clean up temp files
                    for temp_file in temp_files:
                        try:
                            os.unlink(temp_file)
                        except:
                            pass
                            
                except Exception as e:
                    logger.warning(f"Could not analyze relationships for {dataset_name}: {e}")
            
            return S3DatasetAnalysis(
                source_info=source_info,
                row_count=total_rows,
                column_count=column_count,
                column_types=column_types,
                preview=preview,
                multi_value_analysis=multi_value_analysis,
                data_quality_metrics=quality_metrics,
                suggested_import_strategy=suggested_strategy,
                relationship_analysis=relationship_analysis
            )
            
        except Exception as e:
            logger.error(f"Error analyzing S3 dataset {dataset_name}: {e}")
            raise
    
    def _calculate_data_quality_metrics(self, df: pl.DataFrame) -> Dict[str, Any]:
        """Calculate data quality metrics for a dataset."""
        metrics = {
            'total_cells': df.shape[0] * df.shape[1],
            'empty_cells': 0,
            'null_cells': 0,
            'duplicate_rows': 0,
            'columns_with_all_nulls': [],
            'columns_with_mixed_types': [],
            'completeness_percentage': 0.0
        }
        
        try:
            # Calculate null counts per column
            null_counts = df.null_count()
            total_rows = df.shape[0]
            
            for column in df.columns:
                null_count = null_counts[column][0]
                metrics['null_cells'] += null_count
                
                if null_count == total_rows:
                    metrics['columns_with_all_nulls'].append(column)
            
            # Calculate completeness
            if metrics['total_cells'] > 0:
                metrics['completeness_percentage'] = (
                    (metrics['total_cells'] - metrics['null_cells']) / metrics['total_cells'] * 100
                )
            
            # Count duplicate rows
            metrics['duplicate_rows'] = total_rows - df.unique().shape[0]
            
        except Exception as e:
            logger.warning(f"Error calculating data quality metrics: {e}")
        
        return metrics
    
    def _suggest_import_strategy(self, 
                               total_rows: int,
                               multi_value_analysis: Dict[str, Any],
                               quality_metrics: Dict[str, Any]) -> str:
        """Suggest an import strategy based on analysis."""
        
        # Check for multi-value columns
        has_multi_value = any(
            analysis.get('is_multi_value', False) 
            for analysis in multi_value_analysis.values()
        )
        
        # Check data quality
        completeness = quality_metrics.get('completeness_percentage', 100)
        
        if total_rows > 100000:
            return "BATCH_IMPORT"  # Large dataset, use batch processing
        elif has_multi_value:
            return "MULTI_VALUE_PROCESSING"  # Handle multi-value columns specially
        elif completeness < 80:
            return "QUALITY_CHECK_FIRST"  # Poor quality, recommend checking first
        elif total_rows < 1000:
            return "DIRECT_IMPORT"  # Small dataset, direct import
        else:
            return "STANDARD_IMPORT"  # Normal processing
    
    def _create_temp_csv_for_analysis(self, 
                                    sample_data: List[Dict[str, Any]], 
                                    dataset_name: str) -> List[str]:
        """Create temporary CSV files for relationship analysis."""
        temp_files = []
        
        try:
            # Create temporary file
            temp_fd, temp_path = tempfile.mkstemp(suffix='.csv', prefix=f'{dataset_name}_')
            
            with os.fdopen(temp_fd, 'w', newline='', encoding='utf-8') as temp_file:
                if sample_data:
                    import csv
                    writer = csv.DictWriter(temp_file, fieldnames=sample_data[0].keys())
                    writer.writeheader()
                    writer.writerows(sample_data)
            
            temp_files.append(temp_path)
            
        except Exception as e:
            logger.error(f"Error creating temp CSV for analysis: {e}")
        
        return temp_files
    
    def get_s3_source_summary(self, organization_id: str, source_name: str) -> Dict[str, Any]:
        """
        Get a summary of all datasets in an S3 source.
        
        Args:
            organization_id: Organization ID for S3 bucket access
            source_name: Name of the source to analyze
            
        Returns:
            Summary information about the source and its datasets
        """
        sources = self.discover_s3_data_sources(organization_id)
        source_info = next((s for s in sources if s.name == source_name), None)
        
        if not source_info:
            raise ValueError(f"Source '{source_name}' not found in organization {organization_id}")
        
        # For single files (CSV, Excel, etc.), the dataset name is often just the source name
        # For Excel files, we might have multiple sheets, so we get those
        dataset_names = self.get_dataset_names_from_s3_source(source_info)
        datasets_summary = []
        
        # Handle single-file sources (CSV, JSON, etc.)
        if len(dataset_names) == 1 and dataset_names[0] == source_info.name:
            # This is a single dataset file
            try:
                preview = self.get_s3_table_preview(source_info, dataset_names[0], limit=5)
                datasets_summary.append({
                    'name': dataset_names[0],
                    'row_count': preview.total_rows,
                    'column_count': len(preview.column_headers),
                    'columns': preview.column_headers,
                    'sample_data': preview.data_rows,
                    'multi_value_columns': list(preview.multi_value_columns.keys())
                })
            except Exception as e:
                logger.error(f"Could not analyze single dataset {dataset_names[0]}: {e}")
                datasets_summary.append({
                    'name': dataset_names[0],
                    'error': str(e)
                })
        else:
            # This is a multi-dataset source (e.g., Excel with multiple sheets)
            for dataset_name in dataset_names:
                try:
                    preview = self.get_s3_table_preview(source_info, dataset_name, limit=5)
                    datasets_summary.append({
                        'name': dataset_name,
                        'row_count': preview.total_rows,
                        'column_count': len(preview.column_headers),
                        'columns': preview.column_headers,
                        'sample_data': preview.data_rows,
                        'multi_value_columns': list(preview.multi_value_columns.keys())
                    })
                except Exception as e:
                    logger.warning(f"Could not analyze dataset {dataset_name}: {e}")
                    datasets_summary.append({
                        'name': dataset_name,
                        'error': str(e)
                    })
        
        return {
            'source_info': source_info,
            'datasets': datasets_summary,
            'total_datasets': len(dataset_names)
        }
    
    def get_single_dataset_summary(self, organization_id: str, dataset_name: str, source_name: str) -> Dict[str, Any]:
        """
        Get summary for a single dataset WITHOUT scanning all files in S3.
        
        This is an optimized method that directly accesses the specific file
        without discovering all sources first.
        
        Args:
            organization_id: Organization ID for S3 bucket access
            dataset_name: Name of the dataset
            source_name: Name of the source file
            
        Returns:
            Dataset summary with columns and preview
        """
        try:
            # Determine the S3 path directly without full scan
            bucket_name = self.bucket_service.get_organization_bucket(organization_id)
            
            # Try common file extensions
            possible_extensions = ['.csv', '.xlsx', '.xls', '.json', '.parquet']
            source_info = None
            
            for ext in possible_extensions:
                object_key = f"metadata/{source_name}{ext}"
                try:
                    # Check if file exists by trying to get its metadata
                    result = self._safe_head_object(bucket_name, object_key)
                    if not result:
                        raise ClientError({'Error': {'Code': 'NoSuchKey'}}, 'head_object')
                    # File exists, create source info
                    source_info = S3DataSourceInfo(
                        bucket_name=bucket_name,
                        object_key=object_key,
                        name=source_name,
                        format=ext[1:]  # Remove dot
                    )
                    break
                except:
                    continue
            
            if not source_info:
                # Fallback: check without extension (source_name might already include it)
                object_key = f"metadata/{source_name}"
                try:
                    result = self._safe_head_object(bucket_name, object_key)
                    if not result:
                        raise ClientError({'Error': {'Code': 'NoSuchKey'}}, 'head_object')
                    # Determine format from filename
                    name, ext = os.path.splitext(source_name)
                    if ext.lower() in ['.csv', '.xlsx', '.xls', '.json', '.parquet']:
                        source_info = S3DataSourceInfo(
                            bucket_name=bucket_name,
                            object_key=object_key,
                            name=name,
                            format=ext[1:].lower()
                        )
                except:
                    pass
            
            if not source_info:
                raise ValueError(f"Source file '{source_name}' not found in S3")
            
            # Get preview for the specific dataset
            preview = self.get_s3_table_preview(source_info, dataset_name, limit=5)
            
            return {
                'name': dataset_name,
                'source': source_name,
                'row_count': preview.total_rows,
                'column_count': len(preview.column_headers),
                'columns': preview.column_headers,
                'sample_data': preview.data_rows,
                'multi_value_columns': list(preview.multi_value_columns.keys()),
                'preview': {
                    'colHeaders': preview.column_headers,
                    'dataRows': preview.data_rows
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting single dataset summary for {dataset_name}: {e}")
            return {
                'name': dataset_name,
                'source': source_name,
                'error': str(e),
                'columns': [],
                'preview': {
                    'colHeaders': [],
                    'dataRows': []
                }
            }

    def get_s3_import_preview(self, 
                            organization_id: str,
                            source_name: str, 
                            dataset_name: str) -> Dict[str, Any]:
        """
        Get a preview of what would happen if we imported this S3 dataset.
        Uses SmartBulkUpdater's analysis capabilities.
        
        Args:
            organization_id: Organization ID for S3 bucket access
            source_name: Name of the source file
            dataset_name: Name of the dataset within the source
            
        Returns:
            Import preview with change analysis
        """
        # Find the source
        sources = self.discover_s3_data_sources(organization_id)
        source_info = next((s for s in sources if s.name == source_name), None)
        
        if not source_info:
            raise ValueError(f"Source '{source_name}' not found in organization {organization_id}")
        
        # Get sample data for import analysis
        sample_preview = self.get_s3_table_preview(source_info, dataset_name, limit=1000)
        
        # Convert to format expected by SmartBulkUpdater
        csv_data = []
        for i, row in enumerate(sample_preview.data_rows):
            row_dict = {col: val for col, val in zip(sample_preview.column_headers, row)}
            row_dict['id'] = i  # Add row ID
            csv_data.append(row_dict)
        
        # Analyze what would change
        # Convert list of dicts to DataFrame for the new analyzer
        import polars as pl
        df = pl.DataFrame(csv_data)
        # Changes analysis integrated into S3DirectDataAnalyzer
        changes_analysis = self._analyze_dataset_changes_simple(
            dataset_name=dataset_name,
            df=df,
            organization_id=organization_id
        )
        
        return {
            'dataset_name': dataset_name,
            'import_preview': changes_analysis,
            'sample_size': len(csv_data),
            'total_rows': sample_preview.total_rows,
            's3_info': {
                'bucket': source_info.bucket_name,
                'object_key': source_info.object_key,
                'size_bytes': source_info.size_bytes
            }
        }

    def get_full_dataset_data(self, organization_id: str, dataset_name: str, 
                             source_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Load complete CSV dataset data (not just preview) for processing.
        
        This method loads the entire dataset into memory for processing by 
        SmartBulkUpdaterPolars or other components that need full data access.
        
        Args:
            organization_id: Organization ID to determine S3 bucket
            dataset_name: Name of the dataset to load
            source_name: Optional source name to narrow search
            
        Returns:
            List of dictionaries representing all rows in the dataset
            
        Raises:
            ValueError: If dataset is not found or cannot be loaded
        """
        logger.info(f"Loading full dataset data: {dataset_name} for org: {organization_id}")
        
        try:
            # Discover available data sources
            available_sources = self.discover_s3_data_sources(organization_id)
            
            # Find the source containing the requested dataset
            target_source = None
            for source in available_sources:
                if source_name and source.name != source_name:
                    continue  # Skip if source name specified and doesn't match
                
                try:
                    datasets = self.get_dataset_names_from_s3_source(source)
                    if dataset_name in datasets:
                        target_source = source
                        break
                except Exception as e:
                    logger.warning(f"Could not check datasets in source {source.name}: {e}")
                    continue
            
            if not target_source:
                available_datasets = []
                for source in available_sources:
                    try:
                        datasets = self.get_dataset_names_from_s3_source(source)
                        available_datasets.extend(datasets)
                    except:
                        pass
                
                raise ValueError(
                    f"Dataset '{dataset_name}' not found in organization '{organization_id}'. "
                    f"Available datasets: {available_datasets}"
                )
            
            # Load the complete dataset using eager reading
            logger.info(f"Loading complete dataset from source: {target_source.name}")
            df = self._read_s3_source_eager_sample(
                target_source, 
                dataset_name, 
                n_rows=None  # Load all rows - no limit
            )
            
            # Convert to list of dictionaries
            dataset_rows = df.to_dicts()
            
            logger.info(f"Successfully loaded {len(dataset_rows)} rows from dataset: {dataset_name}")
            logger.info(f"Dataset columns: {df.columns}")
            
            return dataset_rows
            
        except Exception as e:
            logger.error(f"Error loading full dataset {dataset_name}: {e}", exc_info=True)
            raise ValueError(f"Failed to load dataset '{dataset_name}': {str(e)}")

    def get_multiple_datasets_data(self, organization_id: str, 
                                  dataset_names: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Load multiple complete datasets efficiently.
        
        Args:
            organization_id: Organization ID
            dataset_names: List of dataset names to load
            
        Returns:
            Dictionary mapping dataset names to their data
        """
        logger.info(f"Loading {len(dataset_names)} datasets for org: {organization_id}")
        
        datasets_data = {}
        errors = {}
        
        for dataset_name in dataset_names:
            try:
                dataset_data = self.get_full_dataset_data(organization_id, dataset_name)
                datasets_data[dataset_name] = dataset_data
                logger.info(f"Loaded dataset '{dataset_name}': {len(dataset_data)} rows")
            except Exception as e:
                logger.error(f"Failed to load dataset '{dataset_name}': {e}")
                errors[dataset_name] = str(e)
        
        if errors and not datasets_data:
            # All datasets failed
            raise ValueError(f"Failed to load any datasets. Errors: {errors}")
        elif errors:
            # Some datasets failed - log warnings but continue
            logger.warning(f"Some datasets failed to load: {errors}")
        
        logger.info(f"Successfully loaded {len(datasets_data)} out of {len(dataset_names)} datasets")
        return datasets_data
    
    def _analyze_multi_values_simple(self, df) -> Dict[str, Any]:
        """
        Simple multi-value analysis to replace BulkDataAnalyzer functionality.
        
        Args:
            df: Polars DataFrame to analyze
            
        Returns:
            Dictionary with multi-value analysis results
        """
        multi_value_columns = {}
        
        try:
            for column in df.columns:
                # Simple heuristic: check if any values contain common separators
                sample_values = df[column].drop_nulls().head(100).to_list()
                separators_found = set()
                
                for value in sample_values:
                    if isinstance(value, str):
                        if ',' in value:
                            separators_found.add(',')
                        if ';' in value:
                            separators_found.add(';')
                        if '|' in value:
                            separators_found.add('|')
                
                if separators_found:
                    multi_value_columns[column] = {
                        'likely_multi_value': True,
                        'detected_separators': list(separators_found),
                        'recommended_separator': ',' if ',' in separators_found else list(separators_found)[0]
                    }
                else:
                    multi_value_columns[column] = {
                        'likely_multi_value': False,
                        'detected_separators': [],
                        'recommended_separator': None
                    }
        except Exception as e:
            logger.warning(f"Error in multi-value analysis: {e}")
        
        return multi_value_columns
    
    def _analyze_dataset_changes_simple(self, dataset_name: str, df, organization_id: str) -> Dict[str, Any]:
        """
        Simple dataset changes analysis to replace BulkDataAnalyzer functionality.
        
        Args:
            dataset_name: Name of the dataset
            df: Polars DataFrame with the data
            organization_id: Organization ID
            
        Returns:
            Dictionary with changes analysis results
        """
        try:
            row_count = df.height
            column_count = len(df.columns)
            
            # Simple analysis - estimate resources that would be created
            estimated_resources = row_count * column_count
            estimated_triples = estimated_resources * 2  # Rough estimate
            
            return {
                'dataset_name': dataset_name,
                'organization_id': organization_id,
                'estimated_changes': {
                    'rows_to_process': row_count,
                    'columns_to_process': column_count,
                    'estimated_resources': estimated_resources,
                    'estimated_triples': estimated_triples
                },
                'analysis_status': 'completed_simple'
            }
        except Exception as e:
            logger.error(f"Error in dataset changes analysis: {e}")
            return {
                'dataset_name': dataset_name,
                'organization_id': organization_id,
                'estimated_changes': {
                    'rows_to_process': 0,
                    'columns_to_process': 0,
                    'estimated_resources': 0,
                    'estimated_triples': 0
                },
                'analysis_status': 'error',
                'error': str(e)
            } 