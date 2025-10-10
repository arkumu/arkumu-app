import os
import time
import logging
from collections import defaultdict
from functools import wraps
from dataclasses import dataclass
from typing import Dict, Optional, Callable, Tuple

from django.core.exceptions import ValidationError
from django.db import transaction

from arkumu.storage.services.bucket_service import BucketService
from arkumu.storage.models import S3FileObject, UploadSession
from arkumu.metadata.models import Resource, ResourceType
from arkumu.metadata.services.resource_traversal_service import ResourceTraversalService

logger = logging.getLogger(__name__)

@dataclass
class MatchingConfig:
    """Configuration for file-resource matching operations."""
    batch_size: int = 1000
    case_sensitive: bool = False
    max_retries: int = 3
    timeout_seconds: int = 300
    log_progress_every: int = 100

class FileMatchingError(Exception):
    """Custom exception for file matching operations."""
    pass

class S3SyncError(Exception):
    """Custom exception for S3 synchronization operations."""
    pass

def retry_on_failure(max_retries: int = 3, delay: float = 1.0):
    """Decorator to retry operations on failure."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        logger.warning(f"Attempt {attempt + 1} failed for {func.__name__}: {e}. Retrying in {delay}s...")
                        time.sleep(delay * (2 ** attempt))  # Exponential backoff
                    else:
                        logger.error(f"All {max_retries} attempts failed for {func.__name__}")
            raise last_exception
        return wrapper
    return decorator

class FileResourceMatcherService:
    def __init__(self, logger_func: Optional[Callable] = None, config: Optional[MatchingConfig] = None):
        self.logger_func = logger_func or self._default_logger
        self.config = config or MatchingConfig()
        self.bucket_service = BucketService()
        self.traversal_service = ResourceTraversalService()

    def _default_logger(self, message: str, level: str = "info"):
        """Default logging implementation."""
        getattr(logger, level)(message)

    def _log(self, message: str, level: str = "info"):
        """Unified logging method."""
        if callable(self.logger_func):
            self.logger_func(message)
        getattr(logger, level)(message)

    def _validate_bucket_params(self, bucket_name: str, prefix: str = ""):
        """Validate S3 bucket parameters."""
        if not bucket_name or not isinstance(bucket_name, str):
            raise ValidationError("bucket_name must be a non-empty string")
        if not isinstance(prefix, str):
            raise ValidationError("prefix must be a string")

    def _record_metrics(self, operation: str, **metrics):
        """Record operation metrics for monitoring."""
        metrics_str = ", ".join([f"{k}={v}" for k, v in metrics.items()])
        self._log(f"METRICS [{operation}]: {metrics_str}", "info")

    @transaction.atomic
    def match_and_link_by_filename_to_resource_value(
        self,
        s3_file_queryset=None,
        *,
        link_target: str = "project",
    ) -> Tuple[int, int, int, int]:
        """
        Matches S3FileObjects to Resources by comparing the S3FileObject's file_name
        (stripping the extension) to the Resource's value.
        Considers only S3FileObjects where related_resource is null.

        Returns: (processed_count, linked_count, ambiguous_count, error_count)
        """
        if link_target not in {"project", "event", "digital_object"}:
            raise ValueError("link_target must be either 'project', 'event', or 'digital_object'")

        start_time = time.time()
        
        if s3_file_queryset is None:
            files_to_process = S3FileObject.objects.filter(related_resource__isnull=True)
        else:
            files_to_process = s3_file_queryset.filter(related_resource__isnull=True)

        total_files = files_to_process.count()
        processed_count = 0
        linked_count = 0
        ambiguous_count = 0
        error_count = 0

        self._log(f"Starting matching process. Found {total_files} S3 files to process for linking.")

        # Process files in batches for better performance
        batch_size = self.config.batch_size
        files_to_update = []
        
        # Pre-fetch all resources for better performance
        all_resources = defaultdict(list)
        for resource in Resource.objects.all():
            # Skip resources with null/empty values
            if not resource.value:
                continue

            raw_value = resource.value if self.config.case_sensitive else resource.value.lower()
            all_resources[raw_value].append(resource)

            base_value, _ = os.path.splitext(resource.value)
            if base_value and base_value != resource.value:
                normalized_base = base_value if self.config.case_sensitive else base_value.lower()
                all_resources[normalized_base].append(resource)

        # Use iterator with chunk_size for better memory efficiency and to avoid slicing issues
        for s3_file in files_to_process.iterator(chunk_size=batch_size):
            processed_count += 1
            
            try:
                file_name_without_extension, _ = os.path.splitext(s3_file.file_name)
                
                if not file_name_without_extension:
                    self._log(f"Skipping S3FileObject ID {s3_file.id} ('{s3_file.s3_key}') - empty filename after stripping extension.")
                    continue

                candidate_names = [file_name_without_extension, s3_file.file_name]
                matching_resources = []

                for name in candidate_names:
                    if not name:
                        continue
                    search_key = name if self.config.case_sensitive else name.lower()
                    hits = all_resources.get(search_key)
                    if hits:
                        matching_resources.extend(hits)

                # Deduplicate while preserving order
                seen_ids = set()
                matching_resources = [
                    res for res in matching_resources
                    if (res.id not in seen_ids and not seen_ids.add(res.id))
                ]

                match_count = len(matching_resources)

                if match_count == 1:
                    matched_resource = matching_resources[0]

                    if link_target == "event":
                        target_entity = self.traversal_service.get_event_entity_for_resource(matched_resource)
                    elif link_target == "project":
                        target_entity = self.traversal_service.get_project_entity_for_resource(matched_resource)
                        if not target_entity and matched_resource.resource_type != ResourceType.LITERAL:
                            target_entity = matched_resource
                    else:
                        target_entity = self.traversal_service.get_digital_object_entity_for_resource(matched_resource)
                        if not target_entity and matched_resource.resource_type != ResourceType.LITERAL:
                            target_entity = matched_resource

                    if target_entity:
                        s3_file.related_resource = target_entity
                        files_to_update.append(s3_file)
                        linked_count += 1

                        if link_target == "event":
                            entity_label = "Event"
                        elif link_target == "project":
                            entity_label = "Project"
                        else:
                            entity_label = "Digital object"
                        if target_entity.id != matched_resource.id:
                            self._log(
                                f"Linked S3FileObject ID {s3_file.id} ({s3_file.s3_key}) to {entity_label} Entity ID {target_entity.id} ('{target_entity.uri}') "
                                f"via matched resource ID {matched_resource.id} ('{matched_resource.value}')."
                            )
                        else:
                            self._log(
                                f"Linked S3FileObject ID {s3_file.id} ({s3_file.s3_key}) to {entity_label} Entity ID {target_entity.id} ('{target_entity.uri}')."
                            )
                    else:
                        self._log(
                            f"No {link_target} entity found for matched resource ID {matched_resource.id} ('{matched_resource.value}') "
                            f"for S3FileObject ID {s3_file.id} ({s3_file.s3_key}). Skipping link."
                        )
                elif match_count > 1:
                    target_entities = []
                    for res in matching_resources:
                        if link_target == "event":
                            entity = self.traversal_service.get_event_entity_for_resource(res)
                        elif link_target == "project":
                            entity = self.traversal_service.get_project_entity_for_resource(res)
                            if not entity and res.resource_type != ResourceType.LITERAL:
                                entity = res
                        else:
                            entity = self.traversal_service.get_digital_object_entity_for_resource(res)
                            if not entity and res.resource_type != ResourceType.LITERAL:
                                entity = res

                        if entity:
                            target_entities.append(entity)

                    target_entities = [entity for entity in target_entities if entity]
                    unique_targets = list({entity.id: entity for entity in target_entities}.values())

                    if len(unique_targets) == 1:
                        target_entity = unique_targets[0]
                        s3_file.related_resource = target_entity
                        files_to_update.append(s3_file)
                        linked_count += 1
                        self._log(
                            f"Resolved ambiguous match for S3FileObject ID {s3_file.id} ({s3_file.s3_key}): "
                            f"Found {match_count} matching resources but all point to same {link_target} {target_entity.uri}. Linked successfully."
                        )
                    else:
                        ambiguous_count += 1
                        resource_ids = [r.id for r in matching_resources]
                        target_ids = [t.id for t in unique_targets] if unique_targets else []
                        self._log(
                            f"Ambiguous match for S3FileObject ID {s3_file.id} ({s3_file.s3_key}): "
                            f"Found {match_count} Resources (IDs: {resource_ids}) leading to {len(unique_targets)} different {link_target}s (IDs: {target_ids}). No link made."
                        )
                else:
                    self._log(f"No Resource found with value '{file_name_without_extension}' for S3FileObject ID {s3_file.id} ({s3_file.s3_key}).")

            except Exception as e:
                error_count += 1
                self._log(f"Error matching S3FileObject ID {s3_file.id} ('{s3_file.s3_key}'): {e}", "error")

            # Log progress periodically
            if processed_count % self.config.log_progress_every == 0:
                self._log(f"Progress: {processed_count}/{total_files} files processed ({linked_count} linked so far)")

            # Bulk update when batch is full
            if len(files_to_update) >= batch_size:
                try:
                    S3FileObject.objects.bulk_update(
                        files_to_update, 
                        ['related_resource', 'updated_at'],
                        batch_size=self.config.batch_size
                    )
                    files_to_update.clear()
                except Exception as e:
                    self._log(f"Error during bulk update: {e}", "error")
                    error_count += len(files_to_update)
                    files_to_update.clear()

        # Final bulk update for remaining files
        if files_to_update:
            try:
                S3FileObject.objects.bulk_update(
                    files_to_update, 
                    ['related_resource', 'updated_at'],
                    batch_size=self.config.batch_size
                )
            except Exception as e:
                self._log(f"Error during final bulk update: {e}", "error")
                error_count += len(files_to_update)

        execution_time = time.time() - start_time
        self._log(f"Matching process finished in {execution_time:.2f}s. Processed: {processed_count}, Linked: {linked_count}, Ambiguous: {ambiguous_count}, Errors: {error_count}.")
        
        self._record_metrics("file_matching", 
                           processed=processed_count,
                           linked=linked_count, 
                           ambiguous=ambiguous_count,
                           errors=error_count,
                           execution_time=execution_time)
        
        return processed_count, linked_count, ambiguous_count, error_count

    def _get_or_create_system_session(self) -> 'UploadSession':
        """Get or create a system upload session for discovered files."""
        from django.contrib.auth import get_user_model
        from arkumu.storage.models import UploadSession
        
        User = get_user_model()
        
        # Get or create system user
        system_user, created = User.objects.get_or_create(
            username='system_s3_discovery',
            defaults={
                'email': 'system@arkumu.org',
                'name': 'System S3Discovery',
                'is_active': True,
            }
        )
        
        # Get or create system session
        system_session, created = UploadSession.objects.get_or_create(
            user=system_user,
            folder_name='s3_discovery_system',
            import_type='file_upload',
            defaults={
                'status': 'in_progress',
                'institution': 'SYSTEM',
                'base_uri': 'http://arkumu.org/system',
            }
        )
        
        return system_session

    @retry_on_failure(max_retries=3)
    @transaction.atomic
    def discover_and_sync_s3_files(self, bucket_name: str, prefix: str = "") -> Tuple[int, int, int, int]:
        """
        Discovers files in S3 bucket and syncs them to database.
        
        Returns: (synced_count, created_count, skipped_count, error_count)
        """
        start_time = time.time()
        
        # Validate inputs
        self._validate_bucket_params(bucket_name, prefix)
        
        self._log(f"Starting S3 discovery and sync for bucket: '{bucket_name}', prefix: '{prefix or '(root)'}'")
        
        try:
            s3_object_list = self.bucket_service.list_bucket_contents(bucket_name=bucket_name, prefix=prefix)
        except Exception as e:
            error_msg = f"Error calling BucketService.list_bucket_contents for {bucket_name}/{prefix}: {e}"
            self._log(error_msg, "error")
            raise S3SyncError(error_msg) from e

        # Get system session for discovered files
        system_session = self._get_or_create_system_session()

        synced_count = 0
        created_count = 0
        skipped_count = 0
        error_count = 0

        # Optimize: Fetch existing keys in batches
        existing_db_keys = set(S3FileObject.objects.values_list('s3_key', flat=True))
        
        files_to_create = []
        total_objects = len(s3_object_list)
        
        self._log(f"Found {total_objects} objects in S3. Processing...")

        for idx, s3_item in enumerate(s3_object_list):
            try:
                s3_key = s3_item.get('Key')
                
                # Skip folders and invalid objects
                if not s3_key or s3_key.endswith('/'):
                    skipped_count += 1
                    continue

                if s3_key not in existing_db_keys:
                    file_name = os.path.basename(s3_key)
                    file_size = s3_item.get('Size', 0)
                    
                    # Prepare object for bulk creation with system session
                    s3_file_obj = S3FileObject(
                        session=system_session,
                        file_name=file_name,
                        original_path=s3_key,
                        s3_key=s3_key,
                        file_size_bytes=file_size,
                        content_type=s3_item.get('ContentType', 'application/octet-stream'),
                        status='verified'
                    )
                    files_to_create.append(s3_file_obj)
                    
                    # Bulk create when batch is full
                    if len(files_to_create) >= self.config.batch_size:
                        try:
                            S3FileObject.objects.bulk_create(files_to_create, ignore_conflicts=True)
                            created_count += len(files_to_create)
                            self._log(f"Bulk created {len(files_to_create)} S3FileObjects")
                            files_to_create.clear()
                        except Exception as e:
                            self._log(f"Error during bulk create: {e}", "error")
                            error_count += len(files_to_create)
                            files_to_create.clear()
                else:
                    synced_count += 1

                # Log progress
                if (idx + 1) % self.config.log_progress_every == 0:
                    self._log(f"Progress: {idx + 1}/{total_objects} objects processed")

            except Exception as e:
                error_count += 1
                self._log(f"Error processing S3 object {s3_item}: {e}", "error")

        # Create remaining files
        if files_to_create:
            try:
                S3FileObject.objects.bulk_create(files_to_create, ignore_conflicts=True)
                created_count += len(files_to_create)
                self._log(f"Final bulk created {len(files_to_create)} S3FileObjects")
            except Exception as e:
                self._log(f"Error during final bulk create: {e}", "error")
                error_count += len(files_to_create)

        execution_time = time.time() - start_time
        self._log(f"S3 discovery and sync finished for {bucket_name}/{prefix} in {execution_time:.2f}s. "
                  f"Synced: {synced_count}, Created: {created_count}, "
                  f"Skipped: {skipped_count}, Errors: {error_count}.")
        
        self._record_metrics("s3_sync",
                           synced=synced_count,
                           created=created_count,
                           skipped=skipped_count,
                           errors=error_count,
                           execution_time=execution_time)
        
        return synced_count, created_count, skipped_count, error_count

    def get_unlinked_files_count(self) -> int:
        """Get count of S3 files not linked to any resource."""
        return S3FileObject.objects.filter(related_resource__isnull=True).count()

    def get_matching_statistics(self) -> dict:
        """Get statistics about file-resource matching."""
        total_files = S3FileObject.objects.count()
        linked_files = S3FileObject.objects.filter(related_resource__isnull=False).count()
        unlinked_files = total_files - linked_files
        
        return {
            'total_files': total_files,
            'linked_files': linked_files,
            'unlinked_files': unlinked_files,
            'link_percentage': round((linked_files / total_files * 100) if total_files > 0 else 0, 2)
        }
