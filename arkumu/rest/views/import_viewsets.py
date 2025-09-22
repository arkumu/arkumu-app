import os
import json
import logging
import tempfile
import zipfile
import shutil
from django.conf import settings
from arkumu.users.mixins import GeneralLoginRequiredMixin
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import AllowAny
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample

from arkumu.importer.services.orchestrator.import_orchestrator import ImportOrchestrator
from arkumu.importer.services.file_upload.s3_upload_service import S3UploadService
from arkumu.storage.models import UploadSession, S3FileObject
from arkumu.rest.serializers import DirectoryImportSerializer

logger = logging.getLogger(__name__)


@extend_schema(tags=['import'])
class ImportViewSet(GeneralLoginRequiredMixin, viewsets.GenericViewSet):
    """
    API endpoint for importing CSV data from directories.
    """
    # This base name will be used in the URL
    basename = 'import'
    
    # Define the serializer class for schema generation
    serializer_class = DirectoryImportSerializer
    
    # Define the queryset (even though we don't use it)
    queryset = None
    
    # Allow any access
    permission_classes = [AllowAny]
    
    @extend_schema(
        operation_id='import_directory',
        description='Import all CSV files from a directory or ZIP file with automatic foreign key detection and placeholder-based reference resolution. No manual configuration required.',
        request=DirectoryImportSerializer,
        responses={200: dict},
        parameters=[
            OpenApiParameter(
                name='zip_file',
                description='ZIP file containing CSV files to import. Use this for browser-based uploads.',
                required=False,
                type='binary'
            ),
        ],
        examples=[
            OpenApiExample(
                'Example Request with Directory Path',
                value={
                    'directory_path': '/path/to/csv_files',
                    'institution': 'DEFAULT',
                    'delimiter': ';',
                    'has_quoted_fields': False,
                    'file_columns': {
                        'table1': ['image_path', 'document_path'],
                        'table2': ['attachment_path']
                    }
                },
                request_only=True,
            ),
            OpenApiExample(
                'Example Request with ZIP File',
                value={
                    'institution': 'DEFAULT',
                    'delimiter': ';',
                    'has_quoted_fields': False,
                    'file_columns': {
                        'table1': ['image_path', 'document_path'],
                        'table2': ['attachment_path']
                    }
                    # ZIP file is uploaded separately
                },
                request_only=True,
            ),
        ]
    )
    @action(
        detail=False,
        methods=['post'],
        url_path='',
        parser_classes=[MultiPartParser, FormParser, JSONParser]
    )
    def import_directory(self, request):
        """
        Import all CSV files from a directory or ZIP file with automatic reference detection.
        
        This endpoint supports two ways to provide CSV files:
        1. Directory path: Provide a server-side path to a directory containing CSV files
        2. ZIP file: Upload a ZIP file containing CSV files directly through the browser
        
        The ZIP file should contain CSV files in the root or in subdirectories. The endpoint will:
        1. Extract the ZIP file to a temporary directory
        2. Process all CSV files with automatic foreign key detection
        3. Create placeholders for missing references
        4. Resolve placeholders when referenced entities are imported
        5. Handle file uploads if S3 config is provided
        6. Clean up the temporary directory after processing
        
        To use the ZIP file upload in Swagger UI:
        - Click "Try it out"
        - Click "Choose File" next to the zip_file parameter
        - Select your ZIP file containing CSV files
        - Fill in other parameters as needed
        - Click "Execute"
        """
        serializer = DirectoryImportSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        # Get parameters from validated data
        validated_data = serializer.validated_data
        directory_path = validated_data.get('directory_path')
        zip_file = validated_data.get('zip_file')
        temp_dir = None
        upload_session = None
            
        try:
            # Get other parameters with defaults
            institution = validated_data.get('institution', 'DEFAULT')
            base_uri = validated_data.get('base_uri', 'http://arkumu.org/data')
            delimiter = validated_data.get('delimiter', ';')
            has_quoted_fields = validated_data.get('has_quoted_fields', False)
            file_columns = validated_data.get('file_columns', {})
            files_base_directory = validated_data.get('files_base_directory')
            
            # Handle ZIP file upload if provided
            if zip_file and not directory_path:
                temp_dir = tempfile.mkdtemp(prefix="arkumu_import_")
                logger.info(f"Created temporary directory for ZIP extraction: {temp_dir}")
                
                # Extract ZIP file to temporary directory
                with zipfile.ZipFile(zip_file, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)
                
                directory_path = temp_dir
                files_base_directory = files_base_directory or temp_dir
                logger.info(f"Extracted ZIP file to {directory_path}")
            
            if not directory_path or not os.path.isdir(directory_path):
                return Response(
                    {"error": f"Directory not found or invalid: {directory_path}"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Determine folder name for the upload session
            if zip_file:
                folder_name = getattr(zip_file, 'name', 'uploaded_zip_file')
            else:
                folder_name = os.path.basename(directory_path.rstrip('/'))
            
            # Initialize S3 upload service if S3 config is provided
            upload_service = None
            s3_config = validated_data.get('s3_config')
            s3_bucket = None
            s3_base_path = None
            
            if s3_config:
                # Get S3 configuration with defaults
                aws_access_key_id = s3_config.get('aws_access_key_id')
                aws_secret_access_key = s3_config.get('aws_secret_access_key')
                region_name = s3_config.get('region_name', 'us-east-1')
                bucket_name = s3_config.get('bucket_name', 'arkumu-files')
                base_url = s3_config.get('base_url', f'https://s3.amazonaws.com/{bucket_name}')
                
                # Use environment variables if keys not provided
                if not aws_access_key_id:
                    aws_access_key_id = os.environ.get('AWS_ACCESS_KEY_ID')
                if not aws_secret_access_key:
                    aws_secret_access_key = os.environ.get('AWS_SECRET_ACCESS_KEY')
                
                # Initialize S3 upload service
                upload_service = S3UploadService(
                    aws_access_key_id=aws_access_key_id,
                    aws_secret_access_key=aws_secret_access_key,
                    region_name=region_name,
                    bucket_name=bucket_name,
                    base_url=base_url
                )
                s3_bucket = bucket_name
                s3_base_path = s3_config.get('base_path', 'imports/')
                logger.info("Initialized S3 upload service")
            
            # Create upload session to track this import
            import_type = 'zip_import' if zip_file else 'csv_import'
            upload_session = UploadSession.create_from_import(
                user=request.user,
                folder_name=folder_name,
                import_type=import_type,
                institution=institution,
                base_uri=base_uri,
                s3_bucket=s3_bucket,
                s3_base_path=s3_base_path
            )
            
            logger.info(f"Created upload session {upload_session.id} for user {request.user.username}")
            
            # Set the files_base_directory default here after we have directory_path
            if not files_base_directory:
                files_base_directory = directory_path
            
            # Run the import
            try:
                stats = ImportWorkflowService.import_csv_directory(
                    directory_path=directory_path,
                    institution=institution,
                    base_uri=base_uri,
                    delimiter=delimiter,
                    has_quoted_fields=has_quoted_fields,
                    file_columns=file_columns,
                    files_base_directory=files_base_directory,
                    upload_service=upload_service,
                    upload_session=upload_session  # Pass the session to track files
                )
                
                # Mark session as completed with stats
                upload_session.mark_completed(stats)
                
                # Add session info to response
                stats['upload_session_id'] = str(upload_session.id)
                stats['upload_session_status'] = upload_session.status
                
                return Response(stats, status=status.HTTP_200_OK)
                
            except Exception as e:
                logger.error(f"Error during CSV import: {str(e)}")
                if upload_session:
                    upload_session.mark_failed(str(e))
                return Response(
                    {"error": f"Import failed: {str(e)}"}, 
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        finally:
            # Clean up temporary directory if it was created
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                    logger.info(f"Cleaned up temporary directory: {temp_dir}")
                except Exception as e:
                    logger.warning(f"Failed to clean up temporary directory {temp_dir}: {str(e)}")
