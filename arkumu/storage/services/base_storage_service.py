import logging
import os
from typing import Any, Dict
import threading
import boto3
from botocore.exceptions import ClientError
from botocore.config import Config
from django.conf import settings
import time # Keep time for potential delays if needed
import urllib3

logger = logging.getLogger(__name__)

class BaseStorageService:
    """
    Base service for interacting with S3/MinIO storage.
    This service is a singleton and handles the core S3 client setup,
    initialization of ingest/production buckets, and CORS configuration once.
    Other services should obtain this singleton instance to access the S3 client and config.
    """
    _instance = None
    _lock = threading.Lock()  # Lock for thread-safe singleton creation and initialization
    _global_buckets_checked = False # Moved here, will be set in __init__

    def __new__(cls, *args, **kwargs):
        # This __new__ makes BaseStorageService a singleton.
        # It ensures only one instance of BaseStorageService itself is ever created.
        if not cls._instance: # Check first without lock for performance
            with cls._lock:
                if not cls._instance: # Double-check lock
                    logger.info("-----> BaseStorageService.__new__: Creating new (and only) instance of BaseStorageService.")
                    cls._instance = super().__new__(cls)
                    # __init__ will be called automatically by Python after __new__ returns this instance.
                    # We will put an initialization guard in __init__.
                else:
                    logger.info("-----> BaseStorageService.__new__: Instance already existed (another thread created it).")
        else:
            logger.info("-----> BaseStorageService.__new__: Instance already existed.")
        return cls._instance

    def __init__(self):
        # This __init__ should only perform its expensive setup once.
        # The __new__ method ensures only one instance, but __init__ is called
        # every time BaseStorageService() is invoked if the instance already exists.
        
        # Check if our one-time initialization has already run for this instance.
        # Use an instance attribute for the flag.
        if hasattr(self, '_base_initialized_flag') and self._base_initialized_flag:
            logger.info("===> BaseStorageService.__init__: Already fully initialized. Skipping one-time setup.")
            return
            
        init_start_time = time.time()
        logger.info(f"===> BaseStorageService.__init__: Starting ONE-TIME actual S3 setup at {init_start_time:.3f}")
        logger.info(f"⏱️ TIMING: BaseStorageService initialization beginning...")
        
        # Disable SSL warnings for self-signed certificates
        if self._is_minio_environment() or os.environ.get('AWS_S3_ENDPOINT_URL'):
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            logger.info("===> SSL warnings disabled for custom S3 endpoint")
        
        # Class-level flag for ensuring buckets are checked only once across all calls to this specific init method.
        # This is somewhat redundant if __init__ itself only runs its core logic once due to _base_initialized_flag,
        # but kept for clarity on the original intent.
        # Consider if BaseStorageService._buckets_checked (class attr) is still needed or if an instance attr is better.
        # For now, let's stick to the logic of ensuring buckets only once globally for the process.
        if not hasattr(BaseStorageService, '_global_buckets_checked') :
            BaseStorageService._global_buckets_checked = False

        self.is_minio = self._is_minio_environment()
        self.endpoint_url = self._get_endpoint_url()
        self.access_key = self._get_access_key()
        self.secret_key = self._get_secret_key()
        self.region = self._get_region()
        self.in_container = self._is_running_in_container()
        self.ingest_bucket = self._get_ingest_bucket_name()
        self.production_bucket = self._get_production_bucket_name()
        
        logger.info(f"===> BaseStorageService: Attempting to create S3 client. Endpoint: {self.endpoint_url}, Region: {self.region}")
        logger.info("===> BaseStorageService: S3 credentials configured")
        # _create_s3_client will set self.s3_client and potentially self.presigned_client
        self._create_s3_client() 
        logger.info("===> BaseStorageService: S3 client(s) created.")
        
        logger.info(f"BaseStorageService core configured with {'MinIO' if self.is_minio else 'S3'}. Ingest: {self.ingest_bucket}, Prod: {self.production_bucket}")
        
        # Ensure essential buckets (ingest, production) exist. This should run only once.
        # The skip_bucket_check parameter is removed from __init__ as this init runs its core only once.
        with BaseStorageService._lock: # Use the same lock to protect _global_buckets_checked
            if not BaseStorageService._global_buckets_checked:
                logger.info("===> BaseStorageService: Ensuring system buckets exist (GLOBAL first time check)...")
                
                # Ingest bucket creation removed - buckets should be created manually or on-demand
                # logger.info(f"===> BaseStorageService: Checking ingest bucket: {self.ingest_bucket}")
                # ingest_bucket_exists = self.ensure_bucket_exists(self.ingest_bucket)
                # logger.info(f"===> BaseStorageService: Ingest bucket '{self.ingest_bucket}' exists result: {ingest_bucket_exists}")
                ingest_bucket_exists = False
                
                # Production bucket creation removed - buckets should be created manually or on-demand
                # logger.info(f"===> BaseStorageService: Checking production bucket: {self.production_bucket}")
                # production_bucket_exists = self.ensure_bucket_exists(self.production_bucket)
                # logger.info(f"===> BaseStorageService: Production bucket '{self.production_bucket}' exists result: {production_bucket_exists}")
                production_bucket_exists = False
                
                BaseStorageService._global_buckets_checked = True
                logger.info("===> BaseStorageService: System buckets GLOBAL check complete. _global_buckets_checked set to True.")
                
                # CORS configuration for ingest bucket removed since bucket is not auto-created
                # if ingest_bucket_exists:
                #     logger.info(f"===> BaseStorageService: Ensuring CORS for ingest bucket: {self.ingest_bucket}")
                #     cors_result = self.ensure_cors_enabled(self.ingest_bucket)
                #     logger.info(f"===> BaseStorageService: CORS configuration for '{self.ingest_bucket}' result: {cors_result.get('success')}")
                # else:
                #     logger.warning(f"===> BaseStorageService: Skipping CORS for ingest bucket '{self.ingest_bucket}' as it does not exist or failed to be ensured.")
                logger.info(f"===> BaseStorageService: Ingest bucket '{self.ingest_bucket}' creation disabled - create manually if needed")
            else:
                logger.info("===> BaseStorageService: System buckets GLOBAL check already performed.")
        
        self._base_initialized_flag = True # Mark this specific instance as having completed its one-time setup.
        init_end_time = time.time()
        init_duration = init_end_time - init_start_time
        logger.info(f"===> BaseStorageService.__init__: ONE-TIME actual S3 setup COMPLETED at {init_end_time:.3f}")
        logger.info(f"⏱️ TIMING: BaseStorageService initialization took {init_duration:.3f} seconds")
    
    # Methods like _is_minio_environment, _get_endpoint_url, _create_s3_client, 
    # ensure_bucket_exists, ensure_cors_enabled etc. remain largely the same, 
    # but _create_s3_client should assign to self.s3_client and self.presigned_client directly.

    def _create_s3_client(self):
        """
        Create an S3 client configured for the current environment.
        Assigns to self.s3_client and self.presigned_client.
        """
        logger.info(f"⏱️ S3 CLIENT CREATION: Starting at {time.strftime('%H:%M:%S', time.localtime())}.{int((time.time() % 1) * 1000):03d}")
        
        # Get max pool connections from environment, with sensible defaults
        max_pool_connections = int(os.environ.get('AWS_MAX_POOL_CONNECTIONS', '10'))
        
        optimized_config = Config(
            retries={'max_attempts': 2, 'mode': 'standard'},
            connect_timeout=5,
            read_timeout=10,
            max_pool_connections=max_pool_connections
        )
        
        client_kwargs = {
            'service_name': 's3',
            'aws_access_key_id': self.access_key,
            'aws_secret_access_key': self.secret_key,
            'config': optimized_config,
        }
        
        if self.region:
            client_kwargs['region_name'] = self.region
        
        if self.endpoint_url:
            client_kwargs['endpoint_url'] = self.endpoint_url
            # Dell EMC ECS configuration based on official samples
            if 'https://' in self.endpoint_url:
                # Use SSL with verification disabled for self-signed certificates
                client_kwargs['use_ssl'] = True
                client_kwargs['verify'] = False
            else:
                # Use plaintext HTTP
                client_kwargs['use_ssl'] = False
            
            # Dell EMC ECS compatible configuration with checksum validation disabled
            custom_s3_config = Config(
                s3={'addressing_style': 'path'},
                retries={'max_attempts': 1, 'mode': 'standard'},
                connect_timeout=60,
                read_timeout=120,
                max_pool_connections=max_pool_connections,  # Use environment variable
                # Disable strict checksum validation for Dell EMC ViPR compatibility
                request_checksum_calculation='when_required',
                response_checksum_validation='when_required'
            )
            client_kwargs['config'] = custom_s3_config
            
            if self.is_minio:
                
                browser_endpoint = os.environ.get('AWS_S3_BROWSER_ENDPOINT_URL', None)
                if browser_endpoint:
                    logger.info(f"Using browser endpoint URL for presigned client from environment: {browser_endpoint}")
                elif 'minio:9000' in self.endpoint_url:
                    browser_endpoint = self.endpoint_url.replace('minio:9000', 'localhost:9000')
                    logger.info(f"MinIO detected at {self.endpoint_url}, presigned client will use {browser_endpoint}")
                else:
                    browser_endpoint = self.endpoint_url
                    logger.info(f"Using server endpoint for presigned client: {browser_endpoint}")
                
                presigned_kwargs = {
                    'service_name': 's3',
                    'aws_access_key_id': self.access_key,
                    'aws_secret_access_key': self.secret_key,
                    'region_name': self.region if self.region else None,
                    'endpoint_url': browser_endpoint,
                    'config': Config(
                        s3={'addressing_style': 'path'},
                        retries={'max_attempts': 2, 'mode': 'standard'},
                        connect_timeout=5,
                        read_timeout=10,
                        max_pool_connections=max_pool_connections,  # Use environment variable
                        # Disable strict checksum validation for Dell EMC ViPR compatibility
                        request_checksum_calculation='when_required',
                        response_checksum_validation='when_required'
                    )
                }
                
                if 'https://' in browser_endpoint:
                    presigned_kwargs['use_ssl'] = True
                    presigned_kwargs['verify'] = False
                else:
                    presigned_kwargs['use_ssl'] = False
                
                self.presigned_client = boto3.client(**presigned_kwargs)
                logger.info(f"Created separate presigned client with endpoint: {browser_endpoint}")
            else: # Not MinIO but has endpoint_url (e.g. Dell EMC ViPR, other S3 compatible)
                 # Ensure presigned_client exists, can be same as s3_client if no special browser URL needed
                if not hasattr(self, 'presigned_client'):
                    self.presigned_client = boto3.client(**client_kwargs)
                    logger.info("Created presigned client (same as main client for Dell EMC/S3-compatible endpoint).")

        s3_create_start = time.time()
        self.s3_client = boto3.client(**client_kwargs)
        s3_create_end = time.time()
        logger.info(f"⏱️ S3 CLIENT CREATED: boto3.client() took {s3_create_end - s3_create_start:.3f}s")
        
        # Test S3 connection and log results
        test_start = time.time()
        self._test_s3_connection()
        test_end = time.time()
        logger.info(f"⏱️ S3 CONNECTION TEST: Took {test_end - test_start:.3f}s")
        
        # If not using a specific endpoint_url (i.e., targeting AWS S3 directly) 
        # and presigned_client wasn't created, make it the same as s3_client.
        if not self.endpoint_url and not hasattr(self, 'presigned_client'):
            logger.info("Using main S3 client for presigned URLs (AWS S3 default endpoint).")
            self.presigned_client = self.s3_client
        elif self.endpoint_url and not self.is_minio and not hasattr(self, 'presigned_client'):
             # Fallback for non-MinIO with endpoint_url if presigned_client still not set
            self.presigned_client = self.s3_client 
            logger.info("Fallback: presigned client set to main client for custom S3 endpoint.")

    def _test_s3_connection(self):
        """
        Test S3 connection and log detailed results for debugging.
        """
        logger.info("===> Testing S3 connection...")
        logger.info(f"===> Endpoint: {self.endpoint_url}")
        logger.info(f"===> Region: {self.region}")
        logger.info("===> S3 credentials validated")
        
        try:
            # Test basic connection by listing buckets
            logger.info("===> Attempting to list buckets...")
            list_start = time.time()
            response = self.s3_client.list_buckets()
            list_end = time.time()
            logger.info(f"⏱️ S3 LIST BUCKETS: Took {list_end - list_start:.3f}s")
            buckets = [bucket['Name'] for bucket in response.get('Buckets', [])]
            logger.info(f"✅ S3 connection successful! Found {len(buckets)} buckets: {buckets}")
            
            # Test specific organization buckets
            from arkumu.storage.services.bucket_service import PREDEFINED_ORGANIZATIONS
            for org_id in PREDEFINED_ORGANIZATIONS:
                try:
                    self.s3_client.head_bucket(Bucket=org_id)
                    logger.info(f"✅ Organization bucket '{org_id}' exists and is accessible")
                except ClientError as e:
                    error_code = e.response.get('Error', {}).get('Code', 'Unknown')
                    if error_code in ['404', 'NoSuchBucket']:
                        logger.warning(f"⚠️ Organization bucket '{org_id}' does not exist")
                    elif error_code in ['403', 'Forbidden']:
                        logger.error(f"❌ Organization bucket '{org_id}' exists but access denied")
                    else:
                        logger.error(f"❌ Error checking bucket '{org_id}': {error_code}")
                
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_message = e.response.get('Error', {}).get('Message', str(e))
            logger.error(f"❌ S3 connection failed with ClientError: {error_code} - {error_message}")
            logger.error(f"❌ Full error response: {e.response}")
        except Exception as e:
            logger.error(f"❌ S3 connection failed with unexpected error: {type(e).__name__}: {str(e)}")
            import traceback
            logger.error(f"❌ Full traceback: {traceback.format_exc()}")

    # ... other helper methods (_is_minio_environment, _get_access_key, etc.) ...
    # ... ensure_bucket_exists, ensure_cors_enabled, delete_object etc. ...
    # The set_client_and_buckets method is no longer needed as sub-services will get the BaseStorageService instance.

# Make sure all previous helper methods from BaseStorageService are still here and are instance methods.
# The following is a placeholder for brevity - ensure all methods from the previous version of
# BaseStorageService (like _get_ingest_bucket_name, _format_size, get_file_content, etc.) are present.

    def _is_minio_environment(self) -> bool:
        use_minio = getattr(settings, 'USE_MINIO', None)
        if use_minio is not None: return use_minio
        use_minio_env = os.environ.get('USE_MINIO', '').lower()
        if use_minio_env in ('true', 'yes', '1'): return True
        if use_minio_env in ('false', 'no', '0'): return False
        return getattr(settings, 'DEBUG', False)

    def _get_endpoint_url(self) -> str:
        endpoint_url = getattr(settings, 'AWS_S3_ENDPOINT_URL', None)
        if endpoint_url: return endpoint_url
        endpoint_url_env = os.environ.get('AWS_S3_ENDPOINT_URL', '')
        if endpoint_url_env: return endpoint_url_env
        if self._is_minio_environment(): return 'http://minio:9000'
        return None

    def _get_access_key(self) -> str:
        access_key = getattr(settings, 'AWS_ACCESS_KEY_ID', None)
        if access_key: return access_key
        access_key_env = os.environ.get('AWS_ACCESS_KEY_ID', '')
        if access_key_env: return access_key_env
        if self._is_minio_environment(): return 'minioadmin'
        logger.warning("No AWS_ACCESS_KEY_ID found")
        return ''

    def _get_secret_key(self) -> str:
        secret_key = getattr(settings, 'AWS_SECRET_ACCESS_KEY', None)
        if secret_key: return secret_key
        secret_key_env = os.environ.get('AWS_SECRET_ACCESS_KEY', '')
        if secret_key_env: return secret_key_env
        if self._is_minio_environment(): return 'minioadmin'
        logger.warning("No AWS_SECRET_ACCESS_KEY found")
        return ''

    def _get_region(self) -> str:
        region = getattr(settings, 'AWS_S3_REGION_NAME', None)
        if region: return region
        region_env = os.environ.get('AWS_S3_REGION_NAME', '')
        if region_env: return region_env
        return 'us-east-1'

    def _get_ingest_bucket_name(self) -> str:
        bucket_name = getattr(settings, 'AWS_INGEST_BUCKET_NAME', None)
        if bucket_name: return bucket_name
        bucket_name_env = os.environ.get('AWS_INGEST_BUCKET_NAME', '')
        if bucket_name_env: return bucket_name_env
        storage_bucket = getattr(settings, 'AWS_STORAGE_BUCKET_NAME', None)
        if storage_bucket: return storage_bucket
        storage_bucket_env = os.environ.get('AWS_STORAGE_BUCKET_NAME', '')
        if storage_bucket_env: return storage_bucket_env
        if self._is_minio_environment(): return 'arkumu-ingest'
        logger.warning("No AWS_INGEST_BUCKET_NAME found")
        return 'arkumu-ingest' # Default

    def _get_production_bucket_name(self) -> str:
        bucket_name = getattr(settings, 'AWS_PRODUCTION_BUCKET_NAME', None)
        if bucket_name: return bucket_name
        bucket_name_env = os.environ.get('AWS_PRODUCTION_BUCKET_NAME', '')
        if bucket_name_env: return bucket_name_env
        if self._is_minio_environment(): return 'arkumu-production'
        logger.warning("No AWS_PRODUCTION_BUCKET_NAME found")
        return 'arkumu-production' # Default

    def _is_running_in_container(self):
        if os.environ.get('RUNNING_IN_CONTAINER'): return True
        if os.path.exists('/.dockerenv'): return True
        try:
            with open('/proc/1/cgroup', 'r') as f:
                return 'docker' in f.read() or 'kubepods' in f.read()
        except: pass
        return False

    def ensure_bucket_exists(self, bucket_name: str) -> bool:
        logger.info(f"Checking if bucket '{bucket_name}' exists (within ensure_bucket_exists)...")
        try:
            self.s3_client.head_bucket(Bucket=bucket_name)
            logger.info(f"✅ Bucket '{bucket_name}' already exists (from head_bucket)")
            return True
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            logger.info(f"Bucket '{bucket_name}' head_bucket result: {error_code}")
            if error_code == '404' or error_code == 'NoSuchBucket':
                try:
                    logger.info(f"🔄 Creating bucket '{bucket_name}' in region '{self.region if self.region else 'default'}'...")
                    create_kwargs = {'Bucket': bucket_name}
                    if self.region and self.region != 'us-east-1':
                        create_kwargs['CreateBucketConfiguration'] = {'LocationConstraint': self.region}
                    elif not self.region and not self.is_minio:
                         pass 
                    self.s3_client.create_bucket(**create_kwargs)
                    logger.info(f"✅ Bucket '{bucket_name}' created successfully.")
                    time.sleep(0.5) 
                    return True
                except Exception as create_error:
                    logger.error(f"❌ Error creating bucket '{bucket_name}': {str(create_error)}")
                    if hasattr(create_error, 'response'): 
                        logger.error(f"Error details: {create_error.response.get('Error', {})}")
                    return False
            else:
                logger.error(f"❌ Error checking bucket '{bucket_name}' (non-404): {e.response.get('Error', {})}")
                return False

    def ensure_cors_enabled(self, bucket_name: str = None) -> Dict[str, Any]:
        if bucket_name is None: bucket_name = self.ingest_bucket
        if self.is_minio or self.endpoint_url:
            logger.info("⚠️ CORS: Skipping for MinIO/non-AWS S3.")
            return {"success": True, "message": "CORS skipped for MinIO/non-AWS S3", "updated": False}
        logger.info(f"CORS: Checking for bucket: {bucket_name}")
        required_rule = {
            'AllowedHeaders': ['*'], 'AllowedMethods': ['POST'],
            'AllowedOrigins': ['*'], 'ExposeHeaders': []
        }
        try:
            cors_config = self.s3_client.get_bucket_cors(Bucket=bucket_name)
            current_rules = cors_config.get('CORSRules', [])
            logger.info(f"CORS: Found {len(current_rules)} existing rules.")
            rule_exists = any(
                set(r.get('AllowedHeaders', [])) >= set(required_rule['AllowedHeaders']) and
                set(r.get('AllowedMethods', [])) >= set(required_rule['AllowedMethods']) and
                set(r.get('AllowedOrigins', [])) >= set(required_rule['AllowedOrigins'])
                for r in current_rules
            )
            if not rule_exists:
                logger.info("CORS: Required rule not found, updating...")
                new_rules = current_rules + [required_rule]
                self.s3_client.put_bucket_cors(Bucket=bucket_name, CORSConfiguration={'CORSRules': new_rules})
                logger.info("CORS: Configuration updated.")
                return {"success": True, "message": "CORS updated", "updated": True}
            logger.info("CORS: Already configured.")
            return {"success": True, "message": "CORS already configured", "updated": False}
        except ClientError as e:
            if e.response.get('Error', {}).get('Code') == 'NoSuchCORSConfiguration':
                logger.info("CORS: No existing config, creating new...")
                self.s3_client.put_bucket_cors(Bucket=bucket_name, CORSConfiguration={'CORSRules': [required_rule]})
                logger.info("CORS: Configuration created.")
                return {"success": True, "message": "CORS created", "updated": True}
            logger.error(f"CORS: Error getting/setting config: {e.response.get('Error', {})}")
            return {"success": False, "error": str(e.response.get('Error', {}))}
        except Exception as e:
            logger.error(f"CORS: Unexpected error: {str(e)}")
            return {"success": False, "error": str(e)}

    def get_file_content(self, bucket_name: str, file_path: str) -> Dict[str, Any]:
        try:
            response = self.s3_client.get_object(Bucket=bucket_name, Key=file_path)
            return {
                "content": response["Body"].read(),
                "metadata": {
                    "content_type": response.get("ContentType", "application/octet-stream"),
                    "content_length": response.get("ContentLength", 0),
                    "last_modified": response.get("LastModified", None),
                },
                "success": True
            }
        except ClientError as e:
            logger.error(f"Error getting file content for {file_path} in {bucket_name}: {e.response.get('Error', {})}")
            return {"success": False, "error": str(e.response.get('Error', {}))}

    def delete_object(self, bucket_name: str, object_path: str, is_directory: bool = False) -> Dict[str, Any]:
        try:
            if is_directory:
                paginator = self.s3_client.get_paginator("list_objects_v2")
                objects_to_delete = [{"Key": obj["Key"]} for page in paginator.paginate(Bucket=bucket_name, Prefix=object_path) for obj in page.get("Contents", [])]
                if objects_to_delete:
                    deleted_count = 0
                    for obj_key in objects_to_delete:
                        self.s3_client.delete_object(Bucket=bucket_name, Key=obj_key["Key"])
                        deleted_count +=1
                    logger.info(f"Deleted {deleted_count} objects from directory {object_path} in {bucket_name}")
                    return {"success": True, "deleted_count": deleted_count}
                return {"success": True, "deleted_count": 0, "message": "Directory empty."}
            else:
                self.s3_client.delete_object(Bucket=bucket_name, Key=object_path)
                logger.info(f"Deleted object {object_path} from {bucket_name}")
                return {"success": True, "deleted_count": 1}
        except ClientError as e:
            logger.error(f"Error deleting {object_path} from {bucket_name}: {e.response.get('Error', {})}")
            return {"success": False, "error": str(e.response.get('Error', {}))}

    def _format_size(self, size_bytes: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0: return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} PB"
    
    def get_encryption_settings(self) -> Dict[str, str]:
        """
        Get standardized encryption settings for S3 uploads.
        Returns encryption configuration for ExtraArgs.
        """
        # For AWS S3, use AES256 server-side encryption
        # For MinIO/other S3-compatible, encryption might not be supported
        if self.is_minio:
            logger.debug("🔒 ENCRYPTION: MinIO detected - encryption may not be supported")
            return {}
        
        logger.debug("🔒 ENCRYPTION: Using AES256 server-side encryption")
        return {
            'ServerSideEncryption': 'AES256'
        }
    
    def upload_fileobj_encrypted(self, fileobj, bucket_name: str, s3_key: str, 
                                content_type: str = None, metadata: Dict[str, str] = None) -> Dict[str, Any]:
        """
        Upload file object with encryption enabled.
        Wrapper around upload_fileobj with standardized encryption settings.
        """
        extra_args = {
            'ContentType': content_type or 'application/octet-stream',
            'Metadata': metadata or {}
        }
        
        # Add encryption settings
        encryption_settings = self.get_encryption_settings()
        extra_args.update(encryption_settings)
        
        # Add encryption flag to metadata
        if encryption_settings:
            extra_args['Metadata']['encrypted'] = 'true'
            extra_args['Metadata']['encryption_type'] = 'AES256'
        else:
            extra_args['Metadata']['encrypted'] = 'false'
        
        try:
            s3_start = time.time()
            self.s3_client.upload_fileobj(
                Fileobj=fileobj,
                Bucket=bucket_name,
                Key=s3_key,
                ExtraArgs=extra_args
            )
            s3_end = time.time()
            s3_duration = s3_end - s3_start
            
            # Log encryption with timing at debug level
            logger.debug(f"🔒 ENCRYPTED UPLOAD: {s3_key} -> s3://{bucket_name} (AES256: {bool(encryption_settings)}) took {s3_duration:.3f}s")
            return {
                'success': True,
                'encrypted': bool(encryption_settings),
                'encryption_type': 'AES256' if encryption_settings else None
            }
            
        except Exception as e:
            logger.error(f"❌ ENCRYPTED UPLOAD FAILED: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }