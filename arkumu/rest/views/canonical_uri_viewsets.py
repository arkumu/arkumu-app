"""
Canonical URI Mapping REST API ViewSets

REST API endpoints for processing canonical URI mappings from CSV files.
Maps organization-specific resource names to Arkumu canonical URIs.
"""

import json
import logging
import tempfile
import csv
from typing import Dict, Any

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample

from arkumu.metadata.services.integration import CanonicalUriMappingService
from arkumu.metadata.models import Resource, ResourceType

logger = logging.getLogger(__name__)


@extend_schema(tags=['canonical-uri'])
class CanonicalUriMappingViewSet(viewsets.GenericViewSet):
    """
    API endpoints for canonical URI mapping operations.
    
    Provides endpoints to process CSV files that map organization-specific
    resource names to Arkumu canonical URIs.
    """
    
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    
    @extend_schema(
        operation_id='canonical_uri_process',
        description='Process canonical URI mappings from uploaded CSV file',
        parameters=[
            OpenApiParameter(
                name='organization_code',
                description='Organization code (e.g., hmt, rsh)',
                required=True,
                type=str
            ),
            OpenApiParameter(
                name='dry_run',
                description='Preview changes without applying them',
                required=False,
                type=bool,
                default=False
            ),
        ],
        request={
            'multipart/form-data': {
                'type': 'object',
                'properties': {
                    'csv_file': {'type': 'string', 'format': 'binary'},
                    'organization_code': {'type': 'string'},
                    'dry_run': {'type': 'boolean', 'default': False}
                }
            }
        },
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean'},
                    'stats': {
                        'type': 'object',
                        'properties': {
                            'updated': {'type': 'integer'},
                            'not_found': {'type': 'array', 'items': {'type': 'string'}},
                            'skipped': {'type': 'integer'},
                            'errors': {'type': 'integer'}
                        }
                    },
                    'organization': {'type': 'string'},
                    'dry_run': {'type': 'boolean'}
                }
            },
            400: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            500: {'type': 'object', 'properties': {'error': {'type': 'string'}}}
        },
        examples=[
            OpenApiExample(
                'Success Response',
                value={
                    'success': True,
                    'stats': {
                        'updated': 10,
                        'not_found': ['Class: NonExistent'],
                        'skipped': 0,
                        'errors': 0
                    },
                    'organization': 'HMT',
                    'dry_run': False
                }
            )
        ]
    )
    @action(detail=False, methods=['post'], url_path='process')
    def process_mappings(self, request):
        """Process canonical URI mappings from uploaded CSV file."""
        try:
            # Get parameters
            organization_code = request.data.get('organization_code')
            dry_run = str(request.data.get('dry_run', 'false')).lower() == 'true'
            csv_file = request.FILES.get('csv_file')
            
            # Validate inputs
            if not organization_code:
                return Response({
                    'success': False,
                    'error': 'Organization code is required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            if not csv_file:
                return Response({
                    'success': False,
                    'error': 'CSV file is required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Initialize service
            try:
                service = CanonicalUriMappingService(organization_code)
            except ValueError as e:
                return Response({
                    'success': False,
                    'error': str(e)
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Save uploaded file temporarily
            with tempfile.NamedTemporaryFile(mode='w+', suffix='.csv', delete=False) as tmp_file:
                # Write CSV content
                csv_content = csv_file.read().decode('utf-8')
                tmp_file.write(csv_content)
                tmp_file.flush()
                
                # Process the CSV
                stats = service.process_canonical_mappings(tmp_file.name, dry_run=dry_run)
            
            return Response({
                'success': True,
                'stats': {
                    'updated': stats['updated'],
                    'not_found': stats['not_found'],
                    'skipped': stats['skipped'],
                    'errors': stats['errors']
                },
                'organization': service.organization.name,
                'organization_code': organization_code,
                'dry_run': dry_run
            })
            
        except Exception as e:
            logger.error(f"Error processing canonical URI mappings: {e}")
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @extend_schema(
        operation_id='canonical_uri_validate',
        description='Validate canonical URI mapping CSV format',
        parameters=[
            OpenApiParameter(
                name='organization_code',
                description='Organization code',
                required=True,
                type=str
            ),
        ],
        request={
            'multipart/form-data': {
                'type': 'object',
                'properties': {
                    'csv_file': {'type': 'string', 'format': 'binary'},
                    'organization_code': {'type': 'string'}
                }
            }
        },
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean'},
                    'is_valid': {'type': 'boolean'},
                    'errors': {'type': 'array', 'items': {'type': 'string'}},
                    'sample_rows': {'type': 'array', 'items': {'type': 'object'}}
                }
            }
        }
    )
    @action(detail=False, methods=['post'], url_path='validate')
    def validate_csv(self, request):
        """Validate CSV file format."""
        try:
            organization_code = request.data.get('organization_code')
            csv_file = request.FILES.get('csv_file')
            
            if not organization_code or not csv_file:
                return Response({
                    'success': False,
                    'error': 'Organization code and CSV file are required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Initialize service
            try:
                service = CanonicalUriMappingService(organization_code)
            except ValueError as e:
                return Response({
                    'success': False,
                    'error': str(e)
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Save and validate file
            with tempfile.NamedTemporaryFile(mode='w+', suffix='.csv', delete=False) as tmp_file:
                csv_content = csv_file.read().decode('utf-8')
                tmp_file.write(csv_content)
                tmp_file.flush()
                
                is_valid, errors = service.validate_mapping_csv(tmp_file.name)
                
                # Get sample rows for preview
                tmp_file.seek(0)
                reader = csv.DictReader(tmp_file)
                sample_rows = []
                for i, row in enumerate(reader):
                    if i >= 5:  # Only first 5 rows
                        break
                    sample_rows.append(row)
            
            return Response({
                'success': True,
                'is_valid': is_valid,
                'errors': errors,
                'sample_rows': sample_rows
            })
            
        except Exception as e:
            logger.error(f"Error validating canonical URI mapping: {e}")
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @extend_schema(
        operation_id='canonical_uri_unmapped',
        description='Get resources without canonical URIs for an organization',
        parameters=[
            OpenApiParameter(
                name='organization_code',
                description='Organization code',
                required=True,
                type=str
            ),
            OpenApiParameter(
                name='resource_type',
                description='Filter by resource type',
                required=False,
                type=str,
                enum=['class', 'property']
            ),
            OpenApiParameter(
                name='limit',
                description='Maximum results to return',
                required=False,
                type=int,
                default=100
            ),
        ],
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean'},
                    'unmapped_resources': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'id': {'type': 'string'},
                                'uri': {'type': 'string'},
                                'name': {'type': 'string'},
                                'resource_type': {'type': 'string'}
                            }
                        }
                    },
                    'total_count': {'type': 'integer'},
                    'organization': {'type': 'string'}
                }
            }
        }
    )
    @action(detail=False, methods=['get'], url_path='unmapped')
    def get_unmapped_resources(self, request):
        """Get resources without canonical URIs."""
        try:
            organization_code = request.query_params.get('organization_code')
            resource_type_str = request.query_params.get('resource_type', '').lower()
            limit = int(request.query_params.get('limit', 100))
            
            if not organization_code:
                return Response({
                    'success': False,
                    'error': 'Organization code is required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Initialize service
            try:
                service = CanonicalUriMappingService(organization_code)
            except ValueError as e:
                return Response({
                    'success': False,
                    'error': str(e)
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Parse resource type filter
            resource_type = None
            if resource_type_str == 'class':
                resource_type = ResourceType.CLASS
            elif resource_type_str == 'property':
                resource_type = ResourceType.PROPERTY
            
            # Get unmapped resources
            unmapped = service.get_unmapped_resources(resource_type)
            total_count = len(unmapped)
            
            # Apply limit
            unmapped = unmapped[:limit]
            
            # Serialize resources
            resources_data = [
                {
                    'id': str(resource.id),
                    'uri': resource.uri,
                    'name': resource.name,
                    'resource_type': resource.resource_type
                }
                for resource in unmapped
            ]
            
            return Response({
                'success': True,
                'unmapped_resources': resources_data,
                'total_count': total_count,
                'organization': service.organization.name,
                'organization_code': organization_code
            })
            
        except Exception as e:
            logger.error(f"Error getting unmapped resources: {e}")
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @extend_schema(
        operation_id='canonical_uri_batch_update',
        description='Batch update canonical URIs for specific resources',
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'organization_code': {'type': 'string'},
                    'updates': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'resource_name': {'type': 'string'},
                                'resource_type': {'type': 'string', 'enum': ['class', 'property']},
                                'canonical_uri': {'type': 'string'}
                            }
                        }
                    },
                    'dry_run': {'type': 'boolean', 'default': False}
                }
            }
        },
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean'},
                    'updated': {'type': 'integer'},
                    'not_found': {'type': 'array', 'items': {'type': 'string'}},
                    'errors': {'type': 'array', 'items': {'type': 'string'}},
                    'dry_run': {'type': 'boolean'}
                }
            }
        }
    )
    @action(detail=False, methods=['post'], url_path='batch-update')
    def batch_update(self, request):
        """Batch update canonical URIs."""
        try:
            organization_code = request.data.get('organization_code')
            updates = request.data.get('updates', [])
            dry_run = request.data.get('dry_run', False)
            
            if not organization_code:
                return Response({
                    'success': False,
                    'error': 'Organization code is required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            if not updates:
                return Response({
                    'success': False,
                    'error': 'No updates provided'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Initialize service
            try:
                service = CanonicalUriMappingService(organization_code)
            except ValueError as e:
                return Response({
                    'success': False,
                    'error': str(e)
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Process updates
            updated_count = 0
            not_found = []
            errors = []
            
            for update in updates:
                try:
                    resource_name = update.get('resource_name')
                    resource_type_str = update.get('resource_type', '').lower()
                    canonical_uri = update.get('canonical_uri')
                    
                    if not all([resource_name, resource_type_str, canonical_uri]):
                        errors.append(f"Invalid update data: {update}")
                        continue
                    
                    # Parse resource type
                    resource_type = service._parse_resource_type(resource_type_str)
                    if not resource_type:
                        errors.append(f"Invalid resource type: {resource_type_str}")
                        continue
                    
                    # Find and update resources
                    resources = Resource.objects.filter(
                        organization=service.organization,
                        name=resource_name,
                        resource_type=resource_type,
                        is_placeholder=False
                    )
                    
                    if resources.exists():
                        if not dry_run:
                            resources.update(canonical_uri=canonical_uri)
                        updated_count += resources.count()
                    else:
                        not_found.append(f"{resource_type_str}: {resource_name}")
                        
                except Exception as e:
                    errors.append(f"Error processing {resource_name}: {str(e)}")
            
            return Response({
                'success': True,
                'updated': updated_count,
                'not_found': not_found,
                'errors': errors,
                'dry_run': dry_run
            })
            
        except Exception as e:
            logger.error(f"Error in batch update: {e}")
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)