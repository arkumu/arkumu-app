"""
Shared fixtures for staged production integration tests.

These fixtures are extracted from the main integration test to be shared
across individual stage tests, ensuring consistent test data and setup.
"""
import pytest
import io
import csv
import json
import logging
from typing import Dict, List, Any

from arkumu.storage.services.bucket_service import BucketService
from arkumu.importer.services.mapping_consumer.mapping_adapter import MappingAdapter
from arkumu.importer.services.execution.statistics import ExecutionStatistics
from arkumu.metadata.models.mappings import Mapping
from arkumu.users.models import Organization

logger = logging.getLogger(__name__)


@pytest.fixture
def fuk_mapping_from_s3(db):
    """Load the folkwang-mapping.json from S3 bucket"""
    bucket_service = BucketService()
    bucket_name = 'fuk'
    file_path = 'metadata/folkwang-mapping.json'
    
    logger.info(f"Loading mapping configuration from S3: {bucket_name}/{file_path}")
    
    try:
        # Get the mapping JSON file from S3
        result = bucket_service.get_file_content(bucket_name, file_path)
        
        if isinstance(result, dict) and 'content' in result:
            content = result['content']
            if isinstance(content, bytes):
                content = content.decode('utf-8')
            
            # Parse the JSON content
            mapping_data = json.loads(content)
            logger.info(f"Successfully loaded mapping data from S3")
            return mapping_data
        else:
            raise Exception(f"Unexpected result format from get_file_content: {result}")
            
    except Exception as e:
        logger.error(f"Failed to load folkwang-mapping.json from S3: {e}")
        # Fallback to a minimal test mapping if S3 file not available
        logger.warning("Using fallback minimal mapping configuration")
        return {
            'name': 'fuk-test',
            'organization_id': 'fuk',
            'source_datasets': ['Ort', 'Rolle', 'AkteurIn', 'Ereignis', 'Projekt'],
            'mapping_config': {
                'version': '1.1',
                'workspace_columns': {
                    'Ort': {
                        'ID': {'arkumu_type': 'ID'},
                        'Name': {'arkumu_type': 'Name'}
                    },
                    'Rolle': {
                        'ID': {'arkumu_type': 'ID'},
                        'Name': {'arkumu_type': 'Name'}
                    }
                }
            }
        }


@pytest.fixture 
def production_test_mapping(db, fuk_mapping_from_s3):
    """Create the fuk-test mapping in the test database using data from S3"""
    # Create FUK organization if it doesn't exist
    organization, _ = Organization.objects.get_or_create(
        code='fuk',
        defaults={
            'name': 'Folkwang Universität der Künste',
            'domain': 'folkwang-uni.de'
        }
    )
    
    # The mapping JSON from S3 is already in the correct format
    # Just store it directly in the database - the system will handle the rest
    
    # Extract basic metadata
    metadata = fuk_mapping_from_s3.get('metadata', {})
    mapping_name = metadata.get('name', 'fuk-test') if isinstance(metadata, dict) else 'fuk-test'
    
    # Extract source datasets for the model field
    workspace_datasets = fuk_mapping_from_s3.get('workspace_datasets', [])
    
    # Create or update the mapping in the test database
    # Store the entire S3 JSON as the mapping_config - the system knows how to handle it
    mapping, created = Mapping.objects.update_or_create(
        name=mapping_name,
        organization_id=organization.code,
        defaults={
            'source_datasets': workspace_datasets,  # List of dataset names
            'mapping_config': fuk_mapping_from_s3,  # Store the entire S3 JSON
            'validation_status': 'validated',  # Mark as validated for testing
            'description': 'Test mapping loaded from S3 fuk_mapping.json'
        }
    )
    
    if created:
        logger.info(f"Created new mapping '{mapping_name}' in test database")
    else:
        logger.info(f"Updated existing mapping '{mapping_name}' in test database")
    
    # Store mapping without validation - let the pipeline handle validation
    # This eliminates redundant validation since translate_to_execution_config() validates during processing
    
    return mapping


@pytest.fixture
def real_csv_data(db):
    """Get REAL CSV data from the organization's MinIO bucket"""
    # Changed from session scope to function scope to ensure proper test database usage
    
    bucket_service = BucketService()
    bucket_name = 'fuk'  # Direct bucket name - we know it exists
    
    logger.info(f"Loading REAL CSV data from MinIO bucket: {bucket_name}")
    
    # List files in metadata/ directory
    files = bucket_service.list_bucket_contents(
        bucket_name=bucket_name,
        prefix='metadata/'
    )
    
    # Filter for CSV files only
    csv_files = []
    for file in files:
        if file['type'] == 'file' and file['name'].lower().endswith('.csv'):
            csv_files.append({
                'key': file['path'],
                'name': file['name'],
                'size': file.get('size', 0),
                'path': file['path']
            })
    
    if not csv_files:
        raise AssertionError("No CSV files found in production metadata bucket")
    
    logger.info(f"Found {len(csv_files)} CSV files in S3 bucket {bucket_name}")
    
    # Load CSV data using BucketService
    csv_data = {}
    for csv_file in csv_files:
        file_path = csv_file['path']
        file_name = csv_file['name']
        dataset_name = file_name.replace('.csv', '')
        
        try:
            # Get file content using BucketService
            result = bucket_service.get_file_content(bucket_name, file_path)
            
            if isinstance(result, dict) and 'content' in result:
                content = result['content']
                if isinstance(content, bytes):
                    content = content.decode('utf-8')
            else:
                raise Exception(f"Unexpected result format from get_file_content: {result}")
            
            # Parse CSV with semicolon delimiter (FUK standard)
            csv_reader = csv.DictReader(io.StringIO(content), delimiter=';')
            rows = list(csv_reader)
            
            csv_data[dataset_name] = {
                'headers': csv_reader.fieldnames,
                'rows': rows,
                'row_count': len(rows)
            }
            
            logger.info(f"Loaded REAL data from {file_name}: {len(rows)} rows")
            
        except Exception as e:
            logger.warning(f"Failed to load {file_name}: {e}")
            continue
    
    if not csv_data:
        raise AssertionError("No CSV data could be loaded from S3")
        
    logger.info(f"Successfully loaded {len(csv_data)} datasets from S3")
    return csv_data


@pytest.fixture
def bucket_service():
    """Shared BucketService instance for tests"""
    return BucketService()


@pytest.fixture
def mapping_adapter():
    """Shared MappingAdapter instance for tests"""
    return MappingAdapter()


@pytest.fixture
def execution_statistics():
    """Shared ExecutionStatistics instance for tests"""
    return ExecutionStatistics()


# Expected CSV files in fuk/metadata/
EXPECTED_FUK_CSV_FILES = [
    'AkteurIn.csv', 'AkteurIn_AkteurIn_Kreuztabelle.csv', 'AkteurIn_Ereignis_Kreuztabelle.csv',
    'Alternativer_Titel.csv', 'Beschreibung.csv', 'Bestehender_Lizenzvertrag.csv',
    'Digitales-Objekt-Lizenz.csv', 'Digitales_Objekt.csv', 'Einliefernde_Hochschule.csv',
    'Equipment_und_Software.csv', 'Equipmentart.csv', 'Ereignis.csv',
    'Ereignis_Ereignis_Kreuztabelle.csv', 'Ereignisbeschreibung.csv', 'Ereignistyp.csv',
    'Informationsträger.csv', 'Informationsträger_Kreuztabelle.csv',
    'Informationsträgereigenschaft.csv', 'Informationsträgertyp.csv', 'Materialschlagwort.csv',
    'Nummernart.csv', 'Organisationseinheit.csv', 'Ort.csv', 'Physisches_Objekt.csv',
    'ProduktID_Kreuztabelle.csv', 'Projekt.csv', 'Projekt_Projekt_Kreuztabelle.csv',
    'Projektart.csv', 'Projekteigenschaft.csv', 'Projekteigenschaft_Kreuztabelle.csv',
    'Projektkategorie.csv', 'Rolle.csv', 'Sammlung.csv', 'Schlagwort.csv', 'Sprache.csv'
]