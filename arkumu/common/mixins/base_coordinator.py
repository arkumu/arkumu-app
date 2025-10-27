"""
Base Coordinator Mixin

Provides shared functionality for all coordinator mixins including:
- Organization management and session handling
- Standardized session key generation
- Common state management patterns
- Advanced session key management (patterns, bulk operations, validation)

This base class eliminates code duplication between CSV mapping and ingest coordinators
while maintaining clean separation of their specific responsibilities.
"""

import logging
import json
from copy import deepcopy
from arkumu.users.models import Organization
from django.middleware.csrf import get_token
from django.utils import timezone

logger = logging.getLogger(__name__)


class BaseCoordinatorMixin:
    """
    Base coordinator mixin for shared session and organization management.
    
    This mixin provides:
    - Centralized organization state management
    - Standardized session key generation with prefixes
    - Base organization change handling
    - Common template context preparation
    - Advanced session key management (patterns, bulk operations, migration, validation)
    
    Subclasses should implement their own specific state management
    while leveraging these shared utilities.
    """
    
    # NOTE: SESSION_PREFIX removed to implement single source of truth session keys
    # All coordinators now use shared keys without prefixes
    
    # Shared session keys (no prefix, used across all coordinators)
    SHARED_CURRENT_ORGANIZATION_KEY = 'current_organization'
    SHARED_CURRENT_MAPPING_KEY = 'current_mapping'
    
    def get_session_key(self, base_key, organization_id=None):
        """
        Generate standardized session key with organization ID.
        
        This ensures consistent session key patterns across all coordinators:
        - With org: 'workspace_columns_123'
        - Without org: 'current_mapping'
        
        Single source of truth session keys enable true coordination between coordinators.
        
        Args:
            base_key (str): Base key name (e.g., 'workspace_columns', 'selected_files')
            organization_id (int, optional): Organization numeric ID to append
            
        Returns:
            str: Standardized session key without prefixes
        """
        key = base_key
        
        if organization_id:
            # Always use numeric ID for consistency
            key = f"{key}_{organization_id}"
            
        return key
    
    def _get_shared_session_key(self, base_key):
        """
        Generate shared session key (no prefix) for cross-coordinator state.
        
        Args:
            base_key (str): Base key name
            
        Returns:
            str: Shared session key
        """
        return base_key
    
    def get_current_organization(self, request):
        """
        Get the currently selected organization from session.
        
        Args:
            request: Django request object
            
        Returns:
            dict: Organization data with keys: id, code, name
            None: If no organization is selected
        """
        session_key = self._get_shared_session_key(self.SHARED_CURRENT_ORGANIZATION_KEY)
        return request.session.get(session_key)
    
    def set_current_organization(self, request, organization_identifier):
        """
        Set the current organization in session.
        
        Args:
            request: Django request object
            organization_identifier: Organization ID (numeric) or code (string)
            
        Returns:
            dict: Organization data that was set
            None: If organization not found
        """
        # Get current organization before changing
        old_org = self.get_current_organization(request)
        
        try:
            # Try to parse as numeric ID first
            if str(organization_identifier).isdigit():
                organization = Organization.objects.get(id=int(organization_identifier))
            else:
                # Treat as organization code
                organization = Organization.objects.get(code=organization_identifier)
            
            org_data = {
                'id': organization.id,
                'code': organization.code,
                'name': organization.name
            }
            
            # Check if organization is actually changing
            if old_org and old_org['id'] != org_data['id']:
                logger.info(f"BASE_COORDINATOR: Organization changing from {old_org['name']} to {org_data['name']}")
                
                # Clear current mapping if it exists (it belongs to the old organization)
                current_mapping = self.get_current_mapping(request)
                if current_mapping:
                    logger.info(f"BASE_COORDINATOR: Clearing current mapping '{current_mapping.get('name')}' due to organization change")
                    self.clear_current_mapping(request)
                
                # Clear organization-specific state
                logger.info(f"BASE_COORDINATOR: Clearing organization-specific state for old org {old_org['code']} (ID: {old_org['id']})")
                self._clear_organization_state_variants(request, old_org)
            
            session_key = self._get_shared_session_key(self.SHARED_CURRENT_ORGANIZATION_KEY)
            request.session[session_key] = org_data
            request.session.modified = True
            
            logger.info(f"BASE_COORDINATOR: Set current organization to {org_data['name']} (code: {org_data['code']}, id: {org_data['id']}) with key: {session_key}")
            return org_data
            
        except (Organization.DoesNotExist, ValueError) as e:
            logger.warning(f"BASE_COORDINATOR: Organization '{organization_identifier}' not found: {e}")
            return None
    
    def clear_current_organization(self, request):
        """
        Clear the current organization from session.
        
        Args:
            request: Django request object
        """
        session_key = self._get_shared_session_key(self.SHARED_CURRENT_ORGANIZATION_KEY)
        if session_key in request.session:
            del request.session[session_key]
            request.session.modified = True
            logger.info(f"BASE_COORDINATOR: Cleared current organization from key: {session_key}")
    
    def get_current_mapping(self, request):
        """
        Get the currently selected mapping from session (shared across all coordinators).
        
        Args:
            request: Django request object
            
        Returns:
            dict: Mapping data with keys: id, name, organization_id, loaded_at
            None: If no mapping is selected
        """
        session_key = self._get_shared_session_key(self.SHARED_CURRENT_MAPPING_KEY)
        return request.session.get(session_key)
    
    def set_current_mapping(self, request, mapping_id, mapping_name=None, organization_id=None):
        """
        Set the current mapping in session (shared across all coordinators).
        
        Args:
            request: Django request object
            mapping_id: Mapping ID
            mapping_name: Mapping name (optional)
            organization_id: Organization ID (optional, uses current if not provided)
            
        Returns:
            dict: Mapping data that was set
        """
        if not organization_id:
            current_org = self.get_current_organization(request)
            if not current_org:
                logger.warning("BASE_COORDINATOR: Cannot set mapping without organization")
                return None
            organization_id = current_org['id']
        
        mapping_data = {
            'id': mapping_id,
            'name': mapping_name or f"Mapping {mapping_id}",
            'organization_id': organization_id,
            'loaded_at': timezone.now().isoformat()
        }
        
        session_key = self._get_shared_session_key(self.SHARED_CURRENT_MAPPING_KEY)
        request.session[session_key] = mapping_data
        request.session.modified = True
        
        logger.info(f"BASE_COORDINATOR: Set current mapping to '{mapping_data['name']}' (id: {mapping_id}) for org ID {organization_id}")
        return mapping_data
    
    def clear_current_mapping(self, request):
        """
        Clear the current mapping from session.
        
        Args:
            request: Django request object
            
        Returns:
            dict: The mapping data that was cleared, or None
        """
        session_key = self._get_shared_session_key(self.SHARED_CURRENT_MAPPING_KEY)
        if session_key in request.session:
            mapping_data = request.session[session_key]
            del request.session[session_key]
            request.session.modified = True
            logger.info(f"BASE_COORDINATOR: Cleared current mapping '{mapping_data.get('name', 'unknown')}' (id: {mapping_data.get('id', 'unknown')})")
            return mapping_data
        return None
    
    def get_organization_context(self, request):
        """
        Get organization context for templates.
        
        This provides a standardized organization context that all coordinators
        can use for template rendering, ensuring consistency across interfaces.
        
        Args:
            request: Django request object
            
        Returns:
            dict: Context with organization_id, organization_code, etc.
        """
        current_org = self.get_current_organization(request)
        if current_org:
            return {
                'organization_id': current_org['code'],  # Use code for mapping compatibility
                'organization_code': current_org['code'],
                'organization_name': current_org['name'],
                'organization_numeric_id': current_org['id'],
                'has_organization': True
            }
        else:
            return {
                'organization_id': None,
                'organization_code': None,
                'organization_name': None,
                'organization_numeric_id': None,
                'has_organization': False
            }

    def _clear_organization_state_variants(self, request, organization_info):
        """
        Clear organization-specific session state using multiple identifier variants.

        Some coordinators store session data using the organization code while others
        use the numeric database ID. When switching organizations we clear state for
        every known identifier to avoid leaking session data between organizations.

        Args:
            request: Django request object
            organization_info (dict | int | str): Organization metadata or direct identifier
        """
        if not organization_info:
            return

        def _add_variant(variant, collected, seen):
            if variant in (None, ''):
                return
            if variant not in seen:
                collected.append(variant)
                seen.add(variant)

        variants = []
        seen = set()

        if isinstance(organization_info, dict):
            org_id = organization_info.get('id')
            org_code = organization_info.get('code')

            _add_variant(org_id, variants, seen)
            if org_id is not None:
                _add_variant(str(org_id), variants, seen)
            _add_variant(org_code, variants, seen)
        else:
            _add_variant(organization_info, variants, seen)
            if isinstance(organization_info, int):
                _add_variant(str(organization_info), variants, seen)

        for identifier in variants:
            try:
                logger.debug(
                    "BASE_COORDINATOR: Clearing organization-specific state for identifier %r (type=%s)",
                    identifier,
                    type(identifier).__name__,
                )
                self.clear_organization_specific_state(request, identifier)
            except Exception as exc:
                logger.exception(
                    "BASE_COORDINATOR: Error clearing state for organization identifier %r: %s",
                    identifier,
                    exc,
                )
    
    def handle_organization_change(self, request, new_organization_identifier):
        """
        Handle organization change with proper state cleanup.
        
        SAFER IMPLEMENTATION: Sets new organization first, then clears old state.
        This prevents data loss if setting the new organization fails.
        
        Args:
            request: Django request object
            new_organization_identifier: New organization ID or code
            
        Returns:
            tuple: (org_data, old_org_data) - New organization data and old organization data
        """
        logger.info(f"BASE_COORDINATOR: Handling organization change to {new_organization_identifier}")
        
        # Get current organization for cleanup
        old_org = self.get_current_organization(request)
        
        # Set new organization FIRST (safer - prevents data loss on failure)
        new_org_data = self.set_current_organization(request, new_organization_identifier)
        
        if not new_org_data:
            logger.error(f"BASE_COORDINATOR: Failed to set new organization {new_organization_identifier}")
            return None, old_org
        
        # Only clear old state AFTER successfully setting new organization
        if old_org and old_org['id'] != new_org_data['id']:
            logger.info(f"BASE_COORDINATOR: Clearing old organization state for {old_org['code']} (ID: {old_org['id']})")
            self._clear_organization_state_variants(request, old_org)
            
            # Only clear the current mapping if it belongs to the old organization
            current_mapping = self.get_current_mapping(request)
            if current_mapping and current_mapping.get('organization_id') == old_org['id']:
                logger.info(f"BASE_COORDINATOR: Clearing mapping '{current_mapping.get('name')}' that belongs to old organization")
                self.clear_current_mapping(request)
            else:
                logger.info(f"BASE_COORDINATOR: Preserving mapping - it doesn't belong to old organization or no mapping exists")
        
        # Also store this organization for cross-view persistence (if OrganizationMixin is available)
        if hasattr(self, 'set_last_selected_organization'):
            self.set_last_selected_organization(request, new_organization_identifier)
        
        return new_org_data, old_org
    
    def get_base_template_context(self, request, additional_context=None):
        """
        Get base template context that all coordinators can use.
        
        This provides common context items like organization info, mapping info,
        CSRF token, and any additional context passed in.
        
        Args:
            request: Django request object
            additional_context (dict, optional): Additional context to merge
            
        Returns:
            dict: Base template context
        """
        context = {
            **self.get_organization_context(request),
            'current_mapping': self.get_current_mapping(request),
            'csrf_token': get_token(request),
        }
        
        if additional_context:
            context.update(additional_context)
            
        return context
    
    def validate_organization_required(self, request):
        """
        Validate that an organization is currently selected.
        
        Args:
            request: Django request object
            
        Returns:
            tuple: (is_valid, error_message, organization_data)
        """
        organization = self.get_current_organization(request)
        if not organization:
            return False, "No organization selected", None
        
        return True, None, organization
    
    def clear_organization_specific_state(self, request, organization_id):
        """
        Clear all session state specific to an organization.
        
        IMPORTANT: Subclasses MUST implement this method to clear their
        specific organization-related session data.
        
        Args:
            request: Django request object
            organization_id (int | str): Organization identifier used by session keys
        """
        logger.info(f"BASE_COORDINATOR: Clearing organization-specific state for org identifier {organization_id}")
        # Subclasses should implement specific state clearing
        # This is intentionally a no-op in the base class
    
    def clear_all_coordinator_state(self, request):
        """
        Clear ALL coordinator-related session data for the current user.
        
        This is a "nuclear option" that clears:
        1. Current organization selection
        2. All coordinator-prefixed session keys
        3. Organization-specific state for all coordinators
        
        Use this for logout, session reset, or debugging.
        
        Args:
            request: Django request object
            
        Returns:
            dict: Summary of what was cleared
        """
        logger.info("BASE_COORDINATOR: GLOBAL COORDINATOR STATE RESET")
        
        # Get current organization and mapping before clearing
        current_org = self.get_current_organization(request)
        current_mapping = self.get_current_mapping(request)
        
        # Clear current organization and mapping selection
        self.clear_current_organization(request)
        self.clear_current_mapping(request)
        
        # Find all coordinator-related session keys
        coordinator_keys = []
        for key in list(request.session.keys()):
            if ('_mapping' in key or '_ingest' in key or '_base' in key or 
                key.startswith('csv_') or key.startswith('ingest_') or key.startswith('base_')):
                coordinator_keys.append(key)
        
        # Remove all coordinator session keys
        for key in coordinator_keys:
            del request.session[key]
            logger.info(f"BASE_COORDINATOR: Cleared session key: {key}")
        
        request.session.modified = True
        
        summary = {
            'organization_cleared': current_org is not None,
            'organization_name': current_org['name'] if current_org else None,
            'session_keys_cleared': len(coordinator_keys),
            'cleared_keys': coordinator_keys
        }
        
        logger.info(f"BASE_COORDINATOR: GLOBAL RESET COMPLETE - {summary}")
        return summary
    
    def get_session_key_with_pattern(self, pattern, organization_id=None):
        """
        Enhanced session key generation for complex patterns.
        
        This method supports advanced pattern-based session key generation
        with placeholders for dynamic values like organization IDs, timestamps,
        and custom identifiers.
        
        Pattern examples:
        - 'workspace_{action}_{timestamp}' -> 'csv_mapping_workspace_load_1234567890_123'
        - 'file_{file_id}_{status}' -> 'csv_mapping_file_456_processed_123'
        - 'batch_{batch_id}' -> 'csv_mapping_batch_789_123'
        
        Args:
            pattern (str): Pattern string with placeholders
            organization_id (int, optional): Organization numeric ID to append
            
        Returns:
            str: Enhanced session key with pattern applied
        """
        # Apply the pattern without prefix (single source of truth)
        enhanced_key = pattern
        
        # Add organization ID if provided
        if organization_id:
            enhanced_key = f"{enhanced_key}_{organization_id}"
        
        logger.debug(f"BASE_COORDINATOR: Generated session key with pattern '{pattern}' -> '{enhanced_key}'")
        return enhanced_key
    
    def bulk_clear_session_keys(self, request, patterns, organization_id=None):
        """
        Clear multiple session keys matching patterns.
        
        This method efficiently clears multiple session keys that match
        specified patterns, useful for cleanup operations when transitioning
        between states or organizations.
        
        Args:
            request: Django request object
            patterns (list): List of pattern strings to match against session keys
            organization_id (int, optional): Organization ID to filter keys
            
        Returns:
            dict: Summary of cleared keys with counts and details
        """
        logger.info(f"BASE_COORDINATOR: Bulk clearing session keys for patterns: {patterns}, org_id: {organization_id}")
        
        cleared_keys = []
        pattern_matches = {pattern: [] for pattern in patterns}
        
        # Get all session keys
        all_keys = list(request.session.keys())
        
        # Process each pattern
        for pattern in patterns:
            # Generate the full session key pattern
            if organization_id:
                full_pattern = f"{pattern}_{organization_id}"
            else:
                full_pattern = pattern
            
            # Find matching keys (supports partial matching)
            matching_keys = [key for key in all_keys if full_pattern in key]
            
            for key in matching_keys:
                if key in request.session:
                    del request.session[key]
                    cleared_keys.append(key)
                    pattern_matches[pattern].append(key)
                    logger.debug(f"BASE_COORDINATOR: Cleared session key: {key}")
        
        # Mark session as modified if any keys were cleared
        if cleared_keys:
            request.session.modified = True
        
        summary = {
            'total_cleared': len(cleared_keys),
            'cleared_keys': cleared_keys,
            'pattern_matches': pattern_matches,
            'organization_id': organization_id
        }
        
        logger.info(f"BASE_COORDINATOR: Bulk clear complete - {summary['total_cleared']} keys cleared")
        return summary
    
    def get_coordinator_session_keys(self, request, organization_id=None):
        """
        Get all session keys for this coordinator.
        
        This method returns all session keys that belong to the current
        coordinator, optionally filtered by organization ID.
        
        Args:
            request: Django request object
            organization_id (int, optional): Organization ID to filter keys
            
        Returns:
            dict: Dictionary containing session keys and their values
        """
        logger.debug(f"BASE_COORDINATOR: Getting coordinator session keys for org_id: {organization_id}")
        
        # With single source of truth, we don't filter by prefix
        coordinator_keys = {}
        
        for key, value in request.session.items():
            # Include organization-scoped keys and shared keys
            if organization_id and key.endswith(f"_{organization_id}"):
                coordinator_keys[key] = value
            elif key in [self.SHARED_CURRENT_ORGANIZATION_KEY, self.SHARED_CURRENT_MAPPING_KEY]:
                coordinator_keys[key] = value
            elif not organization_id:
                # Include non-organization-scoped keys when no org_id specified
                coordinator_keys[key] = value
        
        logger.debug(f"BASE_COORDINATOR: Found {len(coordinator_keys)} coordinator session keys")
        return coordinator_keys
    
    def migrate_session_key(self, request, old_key, new_key):
        """
        Migrate data from old session key to new one.
        
        This method safely transfers data from an old session key to a new one,
        handling the case where the old key might not exist or the new key
        already exists.
        
        Args:
            request: Django request object
            old_key (str): Source session key (can be full key or base key)
            new_key (str): Target session key (can be full key or base key)
            
        Returns:
            dict: Migration status and details
        """
        logger.info(f"BASE_COORDINATOR: Migrating session key from '{old_key}' to '{new_key}'")
        
        # Handle both full keys and base keys
        # With single source of truth, keys don't need prefix validation
        # old_key and new_key remain as provided
        
        migration_status = {
            'old_key': old_key,
            'new_key': new_key,
            'migrated': False,
            'old_key_existed': False,
            'new_key_existed': False,
            'data_migrated': None
        }
        
        # Check if old key exists
        if old_key in request.session:
            migration_status['old_key_existed'] = True
            old_data = request.session[old_key]
            
            # Check if new key already exists
            if new_key in request.session:
                migration_status['new_key_existed'] = True
                logger.warning(f"BASE_COORDINATOR: New key '{new_key}' already exists, will overwrite")
            
            # Migrate the data
            request.session[new_key] = old_data
            migration_status['data_migrated'] = old_data
            
            # Remove old key
            del request.session[old_key]
            request.session.modified = True
            
            migration_status['migrated'] = True
            logger.info(f"BASE_COORDINATOR: Successfully migrated session data from '{old_key}' to '{new_key}'")
        else:
            logger.warning(f"BASE_COORDINATOR: Old key '{old_key}' does not exist, migration skipped")
        
        return migration_status
    
    def validate_session_key_consistency(self, request, organization_id):
        """
        Validate session key consistency for an organization.
        
        This method checks that all session keys for the specified organization
        are consistent and valid, identifying any orphaned or malformed keys.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID to validate
            
        Returns:
            dict: Validation results with consistency status and issues found
        """
        logger.info(f"BASE_COORDINATOR: Validating session key consistency for org_id: {organization_id}")
        
        validation_results = {
            'organization_id': organization_id,
            'is_consistent': True,
            'issues': [],
            'valid_keys': [],
            'invalid_keys': [],
            'orphaned_keys': [],
            'total_keys_checked': 0
        }
        
        # Get current organization to validate against
        current_org = self.get_current_organization(request)
        
        # Get all coordinator session keys
        coordinator_keys = self.get_coordinator_session_keys(request, organization_id)
        validation_results['total_keys_checked'] = len(coordinator_keys)
        
        for key, value in coordinator_keys.items():
            key_issues = []
            
            # With single source of truth, no prefix validation needed
            # Keys can be shared across coordinators
            
            # Check if key ends with organization ID
            if not key.endswith(f"_{organization_id}"):
                key_issues.append(f"Key doesn't end with organization ID '{organization_id}'")
            
            # Check if the organization ID in the key matches current organization
            if current_org and current_org['id'] != organization_id:
                key_issues.append(f"Key organization ID '{organization_id}' doesn't match current organization '{current_org['id']}'")
            
            # Check if value is not None or empty
            if value is None:
                key_issues.append("Key has None value")
            
            # Categorize the key
            if key_issues:
                validation_results['invalid_keys'].append({
                    'key': key,
                    'issues': key_issues,
                    'value': value
                })
                validation_results['is_consistent'] = False
            else:
                validation_results['valid_keys'].append(key)
        
        # Check for orphaned keys (keys that don't belong to any organization)
        all_coordinator_keys = self.get_coordinator_session_keys(request)
        for key in all_coordinator_keys:
            # Keys that don't end with an organization ID might be orphaned
            if not any(key.endswith(f"_{org_id}") for org_id in [organization_id]):
                parts = key.split('_')
                if len(parts) < 3 or not parts[-1].isdigit():
                    validation_results['orphaned_keys'].append(key)
                    validation_results['is_consistent'] = False
        
        # Compile issues summary
        if validation_results['invalid_keys']:
            validation_results['issues'].append(f"Found {len(validation_results['invalid_keys'])} invalid keys")
        
        if validation_results['orphaned_keys']:
            validation_results['issues'].append(f"Found {len(validation_results['orphaned_keys'])} potentially orphaned keys")
        
        if validation_results['is_consistent']:
            logger.info(f"BASE_COORDINATOR: Session key consistency validation passed for org_id: {organization_id}")
        else:
            logger.warning(f"BASE_COORDINATOR: Session key consistency validation failed for org_id: {organization_id} - Issues: {validation_results['issues']}")
        
        return validation_results

    def get_coordinator_debug_info(self, request):
        """
        Get debug information about the current coordinator state.
        
        Useful for troubleshooting session issues and state management.
        
        Args:
            request: Django request object
            
        Returns:
            dict: Debug information about current state
        """
        current_org = self.get_current_organization(request)
        
        # Get all session keys (no prefix filtering for single source of truth)
        coordinator_sessions = {
            key: value for key, value in request.session.items()
        }
        
        # Get all shared keys
        shared_sessions = {
            key: value for key, value in request.session.items()
            if key in [self.SHARED_CURRENT_ORGANIZATION_KEY]
        }
        
        return {
            'coordinator_type': self.__class__.__name__,
            'session_prefix': None,  # No prefix for single source of truth
            'current_organization': current_org,
            'coordinator_sessions': coordinator_sessions,
            'shared_sessions': shared_sessions,
            'total_session_keys': len(request.session.keys()),
            'coordinator_session_count': len(coordinator_sessions)
        }

    # ==========================================================================
    # Generic Dataset Selection Management Methods
    # ==========================================================================

    def get_selected_datasets(self, request, organization_id, selection_type='datasets'):
        """
        Generic dataset selection retrieval with support for different selection types.
        
        This method provides a unified interface for retrieving selected datasets
        or other types of selections (files, sources, etc.) from the session.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            selection_type (str): Type of selection to retrieve (default: 'datasets')
            
        Returns:
            list: List of selected items
        """
        logger.debug(f"BASE_COORDINATOR: Getting selected {selection_type} for org {organization_id}")
        
        # Generate session key using enhanced key management
        session_key = self.get_session_key(f'selected_{selection_type}', organization_id)
        selected_items = request.session.get(session_key, [])
        
        # Validate that we have a list
        if not isinstance(selected_items, list):
            logger.warning(f"BASE_COORDINATOR: Invalid {selection_type} selection format (not a list), resetting to empty list")
            selected_items = []
            request.session[session_key] = selected_items
            request.session.modified = True
        
        logger.debug(f"BASE_COORDINATOR: Retrieved {len(selected_items)} selected {selection_type} for org {organization_id}")
        return selected_items

    def set_selected_datasets(self, request, organization_id, dataset_list, selection_type='datasets'):
        """
        Set dataset selection with proper validation and session management.
        
        This method provides a unified interface for setting selected datasets
        or other types of selections with proper error handling and logging.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            dataset_list (list): List of items to set as selected
            selection_type (str): Type of selection to set (default: 'datasets')
            
        Returns:
            tuple: (success, final_selection_list, error_message)
        """
        logger.info(f"BASE_COORDINATOR: Setting selected {selection_type} for org {organization_id}")
        
        # Validate input
        if not isinstance(dataset_list, list):
            error_msg = f"Invalid {selection_type} list: must be a list, got {type(dataset_list)}"
            logger.error(f"BASE_COORDINATOR: {error_msg}")
            return False, [], error_msg
        
        # Remove duplicates while preserving order
        unique_items = []
        seen = set()
        for item in dataset_list:
            if item not in seen:
                unique_items.append(item)
                seen.add(item)
        
        # Generate session key
        session_key = self.get_session_key(f'selected_{selection_type}', organization_id)
        
        # Store in session
        request.session[session_key] = unique_items
        request.session.modified = True
        
        # Force session save for reliability
        request.session.save()
        
        logger.info(f"BASE_COORDINATOR: Set {len(unique_items)} selected {selection_type} for org {organization_id}")
        logger.debug(f"BASE_COORDINATOR: Session key: {session_key}")
        
        return True, unique_items, None

    def add_selected_dataset(self, request, organization_id, dataset_name, selection_type='datasets'):
        """
        Add a dataset to the selection with proper validation and duplicate prevention.
        
        This method provides a unified interface for adding items to a selection
        with proper uniqueness checking and position management.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            dataset_name (str): Name of the dataset to add
            selection_type (str): Type of selection to modify (default: 'datasets')
            
        Returns:
            tuple: (success, updated_selection, was_duplicate, error_message)
        """
        logger.info(f"BASE_COORDINATOR: Adding {dataset_name} to selected {selection_type} for org {organization_id}")
        
        # Validate input
        if not dataset_name or not isinstance(dataset_name, str):
            error_msg = f"Invalid dataset name: must be a non-empty string, got {type(dataset_name)}"
            logger.error(f"BASE_COORDINATOR: {error_msg}")
            return False, [], False, error_msg
        
        # Get current selection
        current_selection = self.get_selected_datasets(request, organization_id, selection_type)
        
        # Check for duplicates
        was_duplicate = dataset_name in current_selection
        
        if was_duplicate:
            # Remove existing instance and add to front for recency
            current_selection.remove(dataset_name)
            logger.info(f"BASE_COORDINATOR: Removed duplicate {dataset_name} from {selection_type} selection")
        
        # Add to front for most recent
        updated_selection = [dataset_name] + current_selection
        
        # Update session
        success, final_selection, error_msg = self.set_selected_datasets(
            request, organization_id, updated_selection, selection_type
        )
        
        if success:
            logger.info(f"BASE_COORDINATOR: Successfully added {dataset_name} to {selection_type} selection (duplicate: {was_duplicate})")
        else:
            logger.error(f"BASE_COORDINATOR: Failed to add {dataset_name}: {error_msg}")
        
        return success, final_selection, was_duplicate, error_msg

    def remove_selected_dataset(self, request, organization_id, dataset_name, selection_type='datasets'):
        """
        Remove a dataset from the selection with proper validation.
        
        This method provides a unified interface for removing items from a selection
        with proper error handling and logging.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            dataset_name (str): Name of the dataset to remove
            selection_type (str): Type of selection to modify (default: 'datasets')
            
        Returns:
            tuple: (success, updated_selection, was_present, error_message)
        """
        logger.info(f"BASE_COORDINATOR: Removing {dataset_name} from selected {selection_type} for org {organization_id}")
        
        # Validate input
        if not dataset_name or not isinstance(dataset_name, str):
            error_msg = f"Invalid dataset name: must be a non-empty string, got {type(dataset_name)}"
            logger.error(f"BASE_COORDINATOR: {error_msg}")
            return False, [], False, error_msg
        
        # Get current selection
        current_selection = self.get_selected_datasets(request, organization_id, selection_type)
        
        # Check if item exists
        was_present = dataset_name in current_selection
        
        if not was_present:
            logger.info(f"BASE_COORDINATOR: {dataset_name} not in {selection_type} selection, nothing to remove")
            return True, current_selection, False, None
        
        # Remove the item
        updated_selection = [item for item in current_selection if item != dataset_name]
        
        # Update session
        success, final_selection, error_msg = self.set_selected_datasets(
            request, organization_id, updated_selection, selection_type
        )
        
        if success:
            logger.info(f"BASE_COORDINATOR: Successfully removed {dataset_name} from {selection_type} selection")
        else:
            logger.error(f"BASE_COORDINATOR: Failed to remove {dataset_name}: {error_msg}")
        
        return success, final_selection, was_present, error_msg

    def toggle_dataset_selection(self, request, organization_id, dataset_name, selection_type='datasets'):
        """
        Toggle dataset selection state with proper validation and logging.
        
        This method provides a unified interface for toggling items in a selection
        with automatic add/remove logic and detailed operation results.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            dataset_name (str): Name of the dataset to toggle
            selection_type (str): Type of selection to modify (default: 'datasets')
            
        Returns:
            tuple: (success, updated_selection, was_added, error_message)
        """
        logger.info(f"BASE_COORDINATOR: Toggling {dataset_name} in selected {selection_type} for org {organization_id}")
        
        # Validate input
        if not dataset_name or not isinstance(dataset_name, str):
            error_msg = f"Invalid dataset name: must be a non-empty string, got {type(dataset_name)}"
            logger.error(f"BASE_COORDINATOR: {error_msg}")
            return False, [], False, error_msg
        
        # Get current selection
        current_selection = self.get_selected_datasets(request, organization_id, selection_type)
        
        # Determine operation
        if dataset_name in current_selection:
            # Remove from selection
            success, final_selection, was_present, error_msg = self.remove_selected_dataset(
                request, organization_id, dataset_name, selection_type
            )
            was_added = False
            logger.info(f"BASE_COORDINATOR: Toggled {dataset_name} OFF in {selection_type} selection")
        else:
            # Add to selection
            success, final_selection, was_duplicate, error_msg = self.add_selected_dataset(
                request, organization_id, dataset_name, selection_type
            )
            was_added = True
            logger.info(f"BASE_COORDINATOR: Toggled {dataset_name} ON in {selection_type} selection")
        
        return success, final_selection, was_added, error_msg

    def clear_selected_datasets(self, request, organization_id, selection_type='datasets'):
        """
        Clear all selected datasets with proper logging and validation.
        
        This method provides a unified interface for clearing all selections
        with detailed operation results and error handling.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            selection_type (str): Type of selection to clear (default: 'datasets')
            
        Returns:
            tuple: (success, items_cleared_count, error_message)
        """
        logger.info(f"BASE_COORDINATOR: Clearing all selected {selection_type} for org {organization_id}")
        
        # Get current selection count
        current_selection = self.get_selected_datasets(request, organization_id, selection_type)
        items_cleared = len(current_selection)
        
        # Clear selection
        success, final_selection, error_msg = self.set_selected_datasets(
            request, organization_id, [], selection_type
        )
        
        if success:
            logger.info(f"BASE_COORDINATOR: Successfully cleared {items_cleared} {selection_type} selections")
        else:
            logger.error(f"BASE_COORDINATOR: Failed to clear {selection_type} selections: {error_msg}")
        
        return success, items_cleared, error_msg

    def validate_dataset_selection_consistency(self, request, organization_id, selection_type='datasets'):
        """
        Validate selection consistency and detect data integrity issues.
        
        This method provides comprehensive validation of selection state
        with automatic issue detection and detailed reporting.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            selection_type (str): Type of selection to validate (default: 'datasets')
            
        Returns:
            tuple: (is_consistent, issues_found, validation_results)
        """
        logger.info(f"BASE_COORDINATOR: Validating {selection_type} selection consistency for org {organization_id}")
        
        validation_results = {
            'organization_id': organization_id,
            'selection_type': selection_type,
            'is_consistent': True,
            'issues': [],
            'warnings': [],
            'total_items': 0,
            'duplicate_items': [],
            'invalid_items': [],
            'session_info': {},
            'validation_timestamp': timezone.now().isoformat()
        }
        
        try:
            # Get current selection
            current_selection = self.get_selected_datasets(request, organization_id, selection_type)
            validation_results['total_items'] = len(current_selection)
            
            # Check for duplicates
            seen_items = set()
            duplicate_items = []
            
            for item in current_selection:
                if item in seen_items:
                    duplicate_items.append(item)
                    validation_results['is_consistent'] = False
                else:
                    seen_items.add(item)
            
            validation_results['duplicate_items'] = duplicate_items
            
            # Check for invalid items (empty, None, wrong type)
            invalid_items = []
            for item in current_selection:
                if not item or not isinstance(item, str):
                    invalid_items.append(item)
                    validation_results['is_consistent'] = False
            
            validation_results['invalid_items'] = invalid_items
            
            # Check session consistency
            session_key = self.get_session_key(f'selected_{selection_type}', organization_id)
            session_value = request.session.get(session_key)
            
            validation_results['session_info'] = {
                'session_key': session_key,
                'session_key_exists': session_key in request.session,
                'session_value_type': type(session_value).__name__,
                'session_value_is_list': isinstance(session_value, list)
            }
            
            # Generate issues and warnings
            if duplicate_items:
                validation_results['issues'].append(f"Found {len(duplicate_items)} duplicate items: {duplicate_items}")
            
            if invalid_items:
                validation_results['issues'].append(f"Found {len(invalid_items)} invalid items: {invalid_items}")
            
            if not isinstance(session_value, list):
                validation_results['issues'].append(f"Session value is not a list: {type(session_value)}")
                validation_results['is_consistent'] = False
            
            # Auto-fix issues if found
            if not validation_results['is_consistent']:
                logger.warning(f"BASE_COORDINATOR: Inconsistencies found in {selection_type} selection, attempting auto-fix")
                
                # Clean up the selection
                clean_selection = []
                seen_clean = set()
                
                for item in current_selection:
                    if item and isinstance(item, str) and item not in seen_clean:
                        clean_selection.append(item)
                        seen_clean.add(item)
                
                # Update session with cleaned selection
                success, final_selection, error_msg = self.set_selected_datasets(
                    request, organization_id, clean_selection, selection_type
                )
                
                if success:
                    validation_results['warnings'].append(f"Auto-fixed selection: cleaned {len(current_selection) - len(clean_selection)} problematic items")
                    logger.info(f"BASE_COORDINATOR: Auto-fixed {selection_type} selection for org {organization_id}")
                else:
                    validation_results['issues'].append(f"Failed to auto-fix selection: {error_msg}")
            
        except Exception as e:
            logger.error(f"BASE_COORDINATOR: Error validating {selection_type} selection: {e}", exc_info=True)
            validation_results['is_consistent'] = False
            validation_results['issues'].append(f"Validation error: {str(e)}")
        
        # Log validation results
        if validation_results['is_consistent']:
            logger.info(f"BASE_COORDINATOR: {selection_type} selection validation PASSED for org {organization_id}")
        else:
            logger.warning(f"BASE_COORDINATOR: {selection_type} selection validation FAILED for org {organization_id} - Issues: {validation_results['issues']}")
        
        return validation_results['is_consistent'], validation_results['issues'], validation_results

    # ==========================================================================
    # Generic Workspace Management Methods
    # ==========================================================================

    def get_workspace_items(self, request, organization_id, item_type='columns'):
        """
        Get workspace items from session (generic workspace item retrieval).
        
        This method provides a unified interface for retrieving workspace items
        of any type (columns, files, datasets, etc.) from the session.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            item_type (str): Type of workspace items to retrieve (default: 'columns')
            
        Returns:
            list: List of workspace items
        """
        # Generate session key using enhanced key management
        session_key = self.get_session_key(f'workspace_{item_type}', organization_id)
        items = request.session.get(session_key, [])
        
        logger.debug(f"BASE_COORDINATOR: Retrieved {len(items)} workspace {item_type} for org {organization_id}")
        return items

    def add_workspace_item(self, request, organization_id, item_data, item_type='columns'):
        """
        Add an item to workspace with proper validation and uniqueness checking.
        
        This method provides a unified interface for adding workspace items
        with proper duplicate checking and session management.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            item_data (dict): Item data to add to workspace
            item_type (str): Type of workspace item (default: 'columns')
            
        Returns:
            tuple: (success, item_added, total_items, error_message)
        """
        logger.info(f"BASE_COORDINATOR: Adding {item_type} item to workspace for org {organization_id}")
        
        # Validate item_data
        if not isinstance(item_data, dict):
            error_msg = f"Invalid item_data: must be a dictionary, got {type(item_data)}"
            logger.error(f"BASE_COORDINATOR: {error_msg}")
            return False, None, 0, error_msg
        
        # Ensure item has required fields
        if 'id' not in item_data:
            error_msg = f"Item data missing required 'id' field"
            logger.error(f"BASE_COORDINATOR: {error_msg}")
            return False, None, 0, error_msg
        
        # Get current workspace items
        existing_items = self.get_workspace_items(request, organization_id, item_type)
        
        # Check for duplicates
        item_id = item_data['id']
        if any(item.get('id') == item_id for item in existing_items):
            error_msg = f"Item with id '{item_id}' already exists in workspace"
            logger.warning(f"BASE_COORDINATOR: {error_msg}")
            existing_item = next((item for item in existing_items if item.get('id') == item_id), None)
            return False, existing_item, len(existing_items), error_msg
        
        # Add timestamp if not present
        if 'added_at' not in item_data:
            item_data['added_at'] = timezone.now().isoformat()
        
        # Add item to workspace
        updated_items = existing_items + [item_data]
        self.update_workspace_items(request, organization_id, updated_items, item_type)
        
        logger.info(f"BASE_COORDINATOR: Successfully added {item_type} item '{item_id}' to workspace")
        return True, item_data, len(updated_items), None

    def update_workspace_items(self, request, organization_id, items, item_type='columns'):
        """
        Update workspace items in session with proper validation.
        
        This method provides a unified interface for updating workspace items
        with proper session management and validation.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            items (list): List of workspace items to store
            item_type (str): Type of workspace items (default: 'columns')
        """
        logger.info(f"BASE_COORDINATOR: Updating workspace {item_type} for org {organization_id}")
        
        # Validate items is a list
        if not isinstance(items, list):
            logger.error(f"BASE_COORDINATOR: Invalid items: must be a list, got {type(items)}")
            raise ValueError(f"Items must be a list, got {type(items)}")
        
        # Generate session key
        session_key = self.get_session_key(f'workspace_{item_type}', organization_id)
        
        # Store items in session
        request.session[session_key] = items
        request.session.modified = True
        
        # Force session save for reliability
        request.session.save()
        
        logger.info(f"BASE_COORDINATOR: Updated workspace with {len(items)} {item_type} items")
        logger.debug(f"BASE_COORDINATOR: Session key: {session_key}")

    def clear_workspace_items(self, request, organization_id, item_type='columns'):
        """
        Clear workspace items for a specific item type.
        
        This method provides a unified interface for clearing workspace items
        of a specific type while preserving other workspace data.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            item_type (str): Type of workspace items to clear (default: 'columns')
            
        Returns:
            int: Number of items cleared
        """
        logger.info(f"BASE_COORDINATOR: Clearing workspace {item_type} for org {organization_id}")
        
        # Get current items to count them
        current_items = self.get_workspace_items(request, organization_id, item_type)
        items_count = len(current_items)
        
        # Clear items by setting empty list
        self.update_workspace_items(request, organization_id, [], item_type)
        
        logger.info(f"BASE_COORDINATOR: Cleared {items_count} {item_type} items from workspace")
        return items_count

    def get_workspace_statistics(self, request, organization_id, item_type='columns'):
        """
        Get comprehensive statistics about workspace items.
        
        This method provides unified workspace statistics with support for
        different item types and extensible statistical analysis.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            item_type (str): Type of workspace items to analyze (default: 'columns')
            
        Returns:
            dict: Comprehensive workspace statistics
        """
        logger.debug(f"BASE_COORDINATOR: Getting workspace statistics for {item_type} in org {organization_id}")
        
        items = self.get_workspace_items(request, organization_id, item_type)
        
        # Base statistics
        stats = {
            'total_items': len(items),
            'item_type': item_type,
            'organization_id': organization_id,
            'has_items': len(items) > 0,
            'last_updated': timezone.now().isoformat()
        }
        
        if not items:
            return stats
        
        # Analyze item properties based on type
        if item_type == 'columns':
            # Column-specific statistics
            stats.update({
                'anchor_items': len([item for item in items if item.get('is_anchor', False)]),
                'fk_items': len([item for item in items if item.get('is_fk', False)]),
                'multi_value_items': len([item for item in items if item.get('is_multi_value', False)]),
                'datasets_represented': len(set(item.get('dataset') for item in items if item.get('dataset'))),
                'sources_represented': len(set(item.get('source') for item in items if item.get('source')))
            })
        else:
            # Generic item statistics
            stats.update({
                'unique_types': len(set(item.get('type') for item in items if item.get('type'))),
                'items_with_metadata': len([item for item in items if len(item.keys()) > 2])  # More than id and name
            })
        
        # Temporal statistics
        items_with_timestamps = [item for item in items if item.get('added_at')]
        if items_with_timestamps:
            timestamps = [item['added_at'] for item in items_with_timestamps]
            stats.update({
                'oldest_item': min(timestamps),
                'newest_item': max(timestamps),
                'items_with_timestamps': len(items_with_timestamps)
            })
        
        logger.debug(f"BASE_COORDINATOR: Generated statistics for {len(items)} {item_type} items")
        return stats

    def validate_workspace_uniqueness(self, request, organization_id, item_type='columns'):
        """
        Validate workspace item uniqueness and detect duplicates.
        
        This method provides unified validation for workspace items
        with automatic duplicate detection and cleanup capabilities.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            item_type (str): Type of workspace items to validate (default: 'columns')
            
        Returns:
            tuple: (is_unique, duplicates_found, cleaned_items)
        """
        logger.info(f"BASE_COORDINATOR: Validating workspace {item_type} uniqueness for org {organization_id}")
        
        items = self.get_workspace_items(request, organization_id, item_type)
        
        seen_ids = set()
        duplicates = []
        cleaned_items = []
        
        for item in items:
            if not isinstance(item, dict):
                logger.warning(f"BASE_COORDINATOR: Non-dict item found in workspace: {item}")
                continue
                
            item_id = item.get('id')
            if not item_id:
                logger.warning(f"BASE_COORDINATOR: Item without ID found: {item}")
                continue
                
            if item_id in seen_ids:
                duplicates.append(item_id)
                logger.warning(f"BASE_COORDINATOR: Duplicate {item_type} item detected: '{item_id}'")
            else:
                seen_ids.add(item_id)
                cleaned_items.append(item)
        
        is_unique = len(duplicates) == 0
        
        # Auto-clean if duplicates found
        if not is_unique:
            logger.info(f"BASE_COORDINATOR: Auto-cleaning {len(duplicates)} duplicate {item_type} items")
            self.update_workspace_items(request, organization_id, cleaned_items, item_type)
        
        logger.info(f"BASE_COORDINATOR: Validation complete - Unique: {is_unique}, Duplicates: {len(duplicates)}")
        return is_unique, duplicates, cleaned_items

    def get_workspace_summary(self, request, organization_id, item_type='columns'):
        """
        Get comprehensive workspace summary with statistics and metadata.
        
        This method provides a unified interface for getting complete workspace
        information including statistics, validation status, and item details.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            item_type (str): Type of workspace items to analyze (default: 'columns')
            
        Returns:
            dict: Comprehensive workspace summary
        """
        logger.info(f"BASE_COORDINATOR: Getting workspace summary for {item_type} in org {organization_id}")
        
        # Get basic statistics
        stats = self.get_workspace_statistics(request, organization_id, item_type)
        
        # Get validation status
        is_unique, duplicates, cleaned_items = self.validate_workspace_uniqueness(request, organization_id, item_type)
        
        # Get current items (post-validation)
        current_items = self.get_workspace_items(request, organization_id, item_type)
        
        # Build comprehensive summary
        summary = {
            **stats,
            'validation': {
                'is_unique': is_unique,
                'duplicates_found': len(duplicates),
                'duplicate_ids': duplicates,
                'validation_passed': is_unique
            },
            'session_info': {
                'session_key': self.get_session_key(f'workspace_{item_type}', organization_id),
                'coordinator_prefix': None,  # No prefix for single source of truth
                'items_in_session': len(current_items)
            },
            'metadata': {
                'summary_generated_at': timezone.now().isoformat(),
                'summary_type': 'workspace_summary',
                'coordinator_class': self.__class__.__name__
            }
        }
        
        # Add item-specific analysis
        if item_type == 'columns' and current_items:
            # Group by dataset for column-specific analysis
            by_dataset = {}
            for item in current_items:
                dataset = item.get('dataset', 'unknown')
                if dataset not in by_dataset:
                    by_dataset[dataset] = []
                by_dataset[dataset].append(item)
            
            summary['analysis'] = {
                'items_by_dataset': {dataset: len(items) for dataset, items in by_dataset.items()},
                'datasets_with_items': len(by_dataset),
                'average_items_per_dataset': len(current_items) / len(by_dataset) if by_dataset else 0
            }
        
        logger.info(f"BASE_COORDINATOR: Generated comprehensive summary for {len(current_items)} {item_type} items")
        return summary

    # ==========================================================================
    # Generic State Serialization and Persistence Methods
    # ==========================================================================

    def serialize_coordinator_state(self, request, organization_id, state_config=None):
        """
        Generic state serialization for coordinator data.
        
        This method provides a unified interface for serializing coordinator state
        with support for different state configurations and custom serialization logic.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            state_config (dict, optional): State configuration with serialization options
                {
                    'include_keys': ['workspace_columns', 'selected_datasets'],  # Keys to include
                    'exclude_keys': ['temp_data', 'cache'],  # Keys to exclude
                    'custom_serializers': {'custom_key': custom_serializer_func},  # Custom serializers
                    'metadata': {'version': '1.0', 'description': 'Test state'},  # Additional metadata
                    'compression': False,  # Enable compression for large states
                    'validation': True  # Enable state validation
                }
                
        Returns:
            dict: Serialized state data with metadata
                {
                    'coordinator_type': 'CSVMappingCoordinator',
                    'organization_id': 123,
                    'state_version': '1.0',
                    'serialized_at': '2024-01-01T12:00:00Z',
                    'session_data': {...},
                    'metadata': {...},
                    'validation_hash': 'abc123',
                    'success': True,
                    'error_message': None
                }
        """
        logger.info(f"BASE_COORDINATOR: Serializing state for org {organization_id}")
        
        # Initialize state configuration with defaults
        config = state_config or {}
        include_keys = config.get('include_keys', [])
        exclude_keys = config.get('exclude_keys', [])
        custom_serializers = config.get('custom_serializers', {})
        metadata = config.get('metadata', {})
        compression = config.get('compression', False)
        validation = config.get('validation', True)
        
        try:
            # Get all coordinator session keys
            all_coordinator_keys = self.get_coordinator_session_keys(request, organization_id)
            
            # Filter keys based on configuration
            filtered_keys = {}
            for key, value in all_coordinator_keys.items():
                # Extract base key name (remove prefix and org ID)
                base_key = key.replace(f"_{organization_id}", "")
                
                # Apply include/exclude filters
                if include_keys and base_key not in include_keys:
                    continue
                if exclude_keys and base_key in exclude_keys:
                    continue
                    
                # Apply custom serializers if available
                if base_key in custom_serializers:
                    try:
                        serialized_value = custom_serializers[base_key](value)
                        filtered_keys[base_key] = serialized_value
                    except Exception as e:
                        logger.warning(f"BASE_COORDINATOR: Custom serializer failed for key '{base_key}': {e}")
                        filtered_keys[base_key] = value
                else:
                    # Use default serialization (deep copy for safety)
                    filtered_keys[base_key] = deepcopy(value)
            
            # Include shared state if relevant
            shared_state = {}
            current_org = self.get_current_organization(request)
            if current_org and current_org['id'] == organization_id:
                shared_state['current_organization'] = current_org
                
            current_mapping = self.get_current_mapping(request)
            if current_mapping and current_mapping.get('organization_id') == organization_id:
                shared_state['current_mapping'] = current_mapping
            
            # Generate validation hash if requested
            validation_hash = None
            if validation:
                try:
                    state_json = json.dumps(filtered_keys, sort_keys=True)
                    validation_hash = str(hash(state_json))
                except Exception as e:
                    logger.warning(f"BASE_COORDINATOR: Failed to generate validation hash: {e}")
            
            # Build serialized state
            serialized_state = {
                'coordinator_type': self.__class__.__name__,
                'session_prefix': None,  # No prefix for single source of truth
                'organization_id': organization_id,
                'state_version': '1.0',
                'serialized_at': timezone.now().isoformat(),
                'session_data': filtered_keys,
                'shared_state': shared_state,
                'metadata': {
                    'total_keys': len(filtered_keys),
                    'compression_enabled': compression,
                    'validation_enabled': validation,
                    **metadata
                },
                'validation_hash': validation_hash,
                'success': True,
                'error_message': None
            }
            
            logger.info(f"BASE_COORDINATOR: Successfully serialized {len(filtered_keys)} keys for org {organization_id}")
            return serialized_state
            
        except Exception as e:
            logger.error(f"BASE_COORDINATOR: State serialization failed for org {organization_id}: {e}", exc_info=True)
            return {
                'coordinator_type': self.__class__.__name__,
                'organization_id': organization_id,
                'serialized_at': timezone.now().isoformat(),
                'success': False,
                'error_message': str(e),
                'session_data': {},
                'shared_state': {},
                'metadata': {}
            }

    def deserialize_coordinator_state(self, request, organization_id, state_data, state_config=None):
        """
        Generic state deserialization for coordinator data.
        
        This method provides a unified interface for deserializing coordinator state
        with support for different state configurations and custom deserialization logic.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            state_data (dict): Serialized state data to deserialize
            state_config (dict, optional): State configuration with deserialization options
                {
                    'merge_strategy': 'replace',  # 'replace', 'merge', 'preserve_existing'
                    'custom_deserializers': {'custom_key': custom_deserializer_func},
                    'validation': True,  # Enable state validation
                    'restore_shared_state': True,  # Restore shared state (org/mapping)
                    'skip_keys': ['temp_data'],  # Keys to skip during deserialization
                    'force_migration': False  # Force migration if version mismatch
                }
                
        Returns:
            dict: Deserialization results with status and details
                {
                    'success': True,
                    'keys_restored': 15,
                    'keys_skipped': 2,
                    'validation_passed': True,
                    'version_compatible': True,
                    'shared_state_restored': True,
                    'error_message': None,
                    'restored_keys': [...],
                    'skipped_keys': [...],
                    'warnings': [...]
                }
        """
        logger.info(f"BASE_COORDINATOR: Deserializing state for org {organization_id}")
        
        # Initialize result structure
        result = {
            'success': False,
            'keys_restored': 0,
            'keys_skipped': 0,
            'validation_passed': False,
            'version_compatible': False,
            'shared_state_restored': False,
            'error_message': None,
            'restored_keys': [],
            'skipped_keys': [],
            'warnings': []
        }
        
        try:
            # Validate state data structure
            if not isinstance(state_data, dict):
                result['error_message'] = f"Invalid state data: expected dict, got {type(state_data)}"
                logger.error(f"BASE_COORDINATOR: {result['error_message']}")
                return result
            
            if not state_data.get('success', False):
                result['error_message'] = f"State data indicates serialization failure: {state_data.get('error_message', 'Unknown error')}"
                logger.error(f"BASE_COORDINATOR: {result['error_message']}")
                return result
            
            # Initialize configuration
            config = state_config or {}
            merge_strategy = config.get('merge_strategy', 'replace')
            custom_deserializers = config.get('custom_deserializers', {})
            validation = config.get('validation', True)
            restore_shared_state = config.get('restore_shared_state', True)
            skip_keys = config.get('skip_keys', [])
            force_migration = config.get('force_migration', False)
            
            # Validate version compatibility
            state_version = state_data.get('state_version', '1.0')
            if state_version != '1.0' and not force_migration:
                result['error_message'] = f"Incompatible state version: {state_version} (expected: 1.0)"
                logger.error(f"BASE_COORDINATOR: {result['error_message']}")
                return result
            
            result['version_compatible'] = True
            
            # Validate coordinator type compatibility
            state_coordinator_type = state_data.get('coordinator_type')
            if state_coordinator_type != self.__class__.__name__:
                warning_msg = f"State from different coordinator type: {state_coordinator_type} (current: {self.__class__.__name__})"
                result['warnings'].append(warning_msg)
                logger.warning(f"BASE_COORDINATOR: {warning_msg}")
            
            # Validate organization ID
            state_org_id = state_data.get('organization_id')
            if state_org_id != organization_id:
                result['error_message'] = f"Organization ID mismatch: state has {state_org_id}, expected {organization_id}"
                logger.error(f"BASE_COORDINATOR: {result['error_message']}")
                return result
            
            # Validate hash if present
            if validation and state_data.get('validation_hash'):
                try:
                    session_data = state_data.get('session_data', {})
                    state_json = json.dumps(session_data, sort_keys=True)
                    computed_hash = str(hash(state_json))
                    
                    if computed_hash != state_data['validation_hash']:
                        result['error_message'] = f"State validation hash mismatch: computed {computed_hash}, expected {state_data['validation_hash']}"
                        logger.error(f"BASE_COORDINATOR: {result['error_message']}")
                        return result
                    
                    result['validation_passed'] = True
                except Exception as e:
                    warning_msg = f"Failed to validate state hash: {e}"
                    result['warnings'].append(warning_msg)
                    logger.warning(f"BASE_COORDINATOR: {warning_msg}")
            else:
                result['validation_passed'] = True
            
            # Restore session data
            session_data = state_data.get('session_data', {})
            
            for base_key, value in session_data.items():
                # Skip keys if configured
                if base_key in skip_keys:
                    result['skipped_keys'].append(base_key)
                    result['keys_skipped'] += 1
                    continue
                
                # Generate full session key
                session_key = self.get_session_key(base_key, organization_id)
                
                # Apply merge strategy
                if merge_strategy == 'preserve_existing' and session_key in request.session:
                    result['skipped_keys'].append(base_key)
                    result['keys_skipped'] += 1
                    continue
                
                # Apply custom deserializers if available
                if base_key in custom_deserializers:
                    try:
                        deserialized_value = custom_deserializers[base_key](value)
                        final_value = deserialized_value
                    except Exception as e:
                        warning_msg = f"Custom deserializer failed for key '{base_key}': {e}"
                        result['warnings'].append(warning_msg)
                        logger.warning(f"BASE_COORDINATOR: {warning_msg}")
                        final_value = value
                else:
                    final_value = deepcopy(value)
                
                # Apply merge strategy for existing keys
                if merge_strategy == 'merge' and session_key in request.session:
                    existing_value = request.session[session_key]
                    if isinstance(existing_value, dict) and isinstance(final_value, dict):
                        final_value = {**existing_value, **final_value}
                    elif isinstance(existing_value, list) and isinstance(final_value, list):
                        final_value = existing_value + final_value
                
                # Store in session
                request.session[session_key] = final_value
                result['restored_keys'].append(base_key)
                result['keys_restored'] += 1
            
            # Restore shared state if requested
            if restore_shared_state:
                shared_state = state_data.get('shared_state', {})
                
                # Restore current organization
                if 'current_organization' in shared_state:
                    org_data = shared_state['current_organization']
                    if org_data.get('id') == organization_id:
                        self.set_current_organization(request, organization_id)
                        result['shared_state_restored'] = True
                        logger.info(f"BASE_COORDINATOR: Restored current organization: {org_data['name']}")
                
                # Restore current mapping
                if 'current_mapping' in shared_state:
                    mapping_data = shared_state['current_mapping']
                    if mapping_data.get('organization_id') == organization_id:
                        self.set_current_mapping(
                            request, 
                            mapping_data['id'], 
                            mapping_data.get('name'),
                            organization_id
                        )
                        logger.info(f"BASE_COORDINATOR: Restored current mapping: {mapping_data['name']}")
            
            # Mark session as modified and save
            request.session.modified = True
            request.session.save()
            
            result['success'] = True
            logger.info(f"BASE_COORDINATOR: Successfully deserialized state - {result['keys_restored']} keys restored, {result['keys_skipped']} skipped")
            
        except Exception as e:
            result['error_message'] = str(e)
            logger.error(f"BASE_COORDINATOR: State deserialization failed: {e}", exc_info=True)
        
        return result

    def validate_state_compatibility(self, request, organization_id, state_data, state_config=None):
        """
        Validate state compatibility without applying changes.
        
        This method provides comprehensive validation of state data to ensure
        compatibility with the current coordinator and organization context.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            state_data (dict): Serialized state data to validate
            state_config (dict, optional): Validation configuration
                {
                    'strict_version': True,  # Require exact version match
                    'strict_coordinator': True,  # Require exact coordinator type match
                    'validate_hash': True,  # Validate state hash
                    'check_organization': True,  # Validate organization exists
                    'validate_session_keys': True  # Validate session key format
                }
                
        Returns:
            dict: Validation results with detailed compatibility analysis
                {
                    'is_compatible': True,
                    'version_compatible': True,
                    'coordinator_compatible': True,
                    'organization_compatible': True,
                    'hash_valid': True,
                    'issues': [],
                    'warnings': [],
                    'recommendations': [],
                    'state_info': {...},
                    'validation_timestamp': '2024-01-01T12:00:00Z'
                }
        """
        logger.info(f"BASE_COORDINATOR: Validating state compatibility for org {organization_id}")
        
        # Initialize validation results
        validation_results = {
            'is_compatible': True,
            'version_compatible': True,
            'coordinator_compatible': True,
            'organization_compatible': True,
            'hash_valid': True,
            'issues': [],
            'warnings': [],
            'recommendations': [],
            'state_info': {},
            'validation_timestamp': timezone.now().isoformat()
        }
        
        try:
            # Initialize configuration
            config = state_config or {}
            strict_version = config.get('strict_version', True)
            strict_coordinator = config.get('strict_coordinator', True)
            validate_hash = config.get('validate_hash', True)
            check_organization = config.get('check_organization', True)
            validate_session_keys = config.get('validate_session_keys', True)
            
            # Validate state data structure
            if not isinstance(state_data, dict):
                validation_results['is_compatible'] = False
                validation_results['issues'].append(f"Invalid state data type: expected dict, got {type(state_data)}")
                return validation_results
            
            if not state_data.get('success', False):
                validation_results['is_compatible'] = False
                validation_results['issues'].append(f"State data indicates serialization failure: {state_data.get('error_message', 'Unknown error')}")
                return validation_results
            
            # Extract state information
            state_info = {
                'coordinator_type': state_data.get('coordinator_type'),
                'session_prefix': state_data.get('session_prefix'),
                'organization_id': state_data.get('organization_id'),
                'state_version': state_data.get('state_version', '1.0'),
                'serialized_at': state_data.get('serialized_at'),
                'total_keys': state_data.get('metadata', {}).get('total_keys', 0),
                'has_validation_hash': bool(state_data.get('validation_hash')),
                'has_shared_state': bool(state_data.get('shared_state'))
            }
            validation_results['state_info'] = state_info
            
            # Validate version compatibility
            state_version = state_data.get('state_version', '1.0')
            if strict_version and state_version != '1.0':
                validation_results['version_compatible'] = False
                validation_results['is_compatible'] = False
                validation_results['issues'].append(f"Incompatible state version: {state_version} (expected: 1.0)")
            elif state_version != '1.0':
                validation_results['warnings'].append(f"State version mismatch: {state_version} (current: 1.0)")
                validation_results['recommendations'].append("Consider enabling force_migration for deserialization")
            
            # Validate coordinator type compatibility
            state_coordinator_type = state_data.get('coordinator_type')
            if strict_coordinator and state_coordinator_type != self.__class__.__name__:
                validation_results['coordinator_compatible'] = False
                validation_results['is_compatible'] = False
                validation_results['issues'].append(f"Incompatible coordinator type: {state_coordinator_type} (expected: {self.__class__.__name__})")
            elif state_coordinator_type != self.__class__.__name__:
                validation_results['warnings'].append(f"Coordinator type mismatch: {state_coordinator_type} (current: {self.__class__.__name__})")
                validation_results['recommendations'].append("Verify state data is compatible with current coordinator")
            
            # Validate organization compatibility
            state_org_id = state_data.get('organization_id')
            if state_org_id != organization_id:
                validation_results['organization_compatible'] = False
                validation_results['is_compatible'] = False
                validation_results['issues'].append(f"Organization ID mismatch: state has {state_org_id}, expected {organization_id}")
            
            # Check if organization exists
            if check_organization:
                try:
                    Organization.objects.get(id=organization_id)
                except Organization.DoesNotExist:
                    validation_results['organization_compatible'] = False
                    validation_results['is_compatible'] = False
                    validation_results['issues'].append(f"Organization {organization_id} does not exist")
            
            # Validate hash if present
            if validate_hash and state_data.get('validation_hash'):
                try:
                    session_data = state_data.get('session_data', {})
                    state_json = json.dumps(session_data, sort_keys=True)
                    computed_hash = str(hash(state_json))
                    
                    if computed_hash != state_data['validation_hash']:
                        validation_results['hash_valid'] = False
                        validation_results['is_compatible'] = False
                        validation_results['issues'].append(f"State validation hash mismatch: computed {computed_hash}, expected {state_data['validation_hash']}")
                        validation_results['recommendations'].append("State data may be corrupted or modified")
                    
                except Exception as e:
                    validation_results['warnings'].append(f"Failed to validate state hash: {e}")
            
            # Validate session keys format
            if validate_session_keys:
                session_data = state_data.get('session_data', {})
                invalid_keys = []
                
                for base_key in session_data.keys():
                    # Check if key would generate valid session key
                    try:
                        session_key = self.get_session_key(base_key, organization_id)
                        if not session_key or len(session_key) < 3:
                            invalid_keys.append(base_key)
                    except Exception:
                        invalid_keys.append(base_key)
                
                if invalid_keys:
                    validation_results['warnings'].append(f"Found {len(invalid_keys)} keys with invalid format: {invalid_keys}")
            
            # Generate recommendations based on findings
            if validation_results['warnings']:
                validation_results['recommendations'].append("Review warnings before deserializing state")
            
            if not validation_results['is_compatible']:
                validation_results['recommendations'].append("State is not compatible - deserialization will fail")
            
            # Log validation results
            if validation_results['is_compatible']:
                logger.info(f"BASE_COORDINATOR: State compatibility validation PASSED for org {organization_id}")
            else:
                logger.warning(f"BASE_COORDINATOR: State compatibility validation FAILED for org {organization_id} - Issues: {validation_results['issues']}")
            
        except Exception as e:
            validation_results['is_compatible'] = False
            validation_results['issues'].append(f"Validation error: {str(e)}")
            logger.error(f"BASE_COORDINATOR: State compatibility validation error: {e}", exc_info=True)
        
        return validation_results

    def save_coordinator_state(self, request, organization_id, state_name, state_config=None):
        """
        Save coordinator state with metadata to session storage.
        
        This method provides a unified interface for saving named coordinator states
        with metadata for later retrieval and management.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            state_name (str): Name to save the state under
            state_config (dict, optional): State configuration for serialization
                {
                    'description': 'State description',
                    'tags': ['backup', 'checkpoint'],
                    'auto_expire': 3600,  # Auto-expire after seconds
                    'overwrite_existing': True,  # Allow overwriting existing states
                    'include_metadata': True,  # Include additional metadata
                    'compress': False  # Compress state data
                }
                
        Returns:
            dict: Save operation results with status and metadata
                {
                    'success': True,
                    'state_name': 'backup_state',
                    'state_key': 'saved_states_backup_state_123',
                    'serialized_keys': 15,
                    'state_size': 1024,
                    'overwritten': False,
                    'expires_at': '2024-01-01T13:00:00Z',
                    'error_message': None,
                    'metadata': {...}
                }
        """
        logger.info(f"BASE_COORDINATOR: Saving coordinator state '{state_name}' for org {organization_id}")
        
        # Initialize result structure
        result = {
            'success': False,
            'state_name': state_name,
            'state_key': None,
            'serialized_keys': 0,
            'state_size': 0,
            'overwritten': False,
            'expires_at': None,
            'error_message': None,
            'metadata': {}
        }
        
        try:
            # Validate state name
            if not state_name or not isinstance(state_name, str):
                result['error_message'] = f"Invalid state name: must be a non-empty string, got {type(state_name)}"
                logger.error(f"BASE_COORDINATOR: {result['error_message']}")
                return result
            
            # Sanitize state name
            sanitized_name = state_name.replace(' ', '_').replace('/', '_').replace('\\', '_')
            if sanitized_name != state_name:
                logger.info(f"BASE_COORDINATOR: Sanitized state name from '{state_name}' to '{sanitized_name}'")
            
            # Initialize configuration
            config = state_config or {}
            description = config.get('description', f"Saved state: {sanitized_name}")
            tags = config.get('tags', [])
            auto_expire = config.get('auto_expire')
            overwrite_existing = config.get('overwrite_existing', True)
            include_metadata = config.get('include_metadata', True)
            compress = config.get('compress', False)
            
            # Generate state key
            state_key = self.get_session_key(f'saved_states_{sanitized_name}', organization_id)
            result['state_key'] = state_key
            
            # Check if state already exists
            if state_key in request.session:
                if not overwrite_existing:
                    result['error_message'] = f"State '{sanitized_name}' already exists and overwrite_existing is False"
                    logger.error(f"BASE_COORDINATOR: {result['error_message']}")
                    return result
                result['overwritten'] = True
                logger.info(f"BASE_COORDINATOR: Overwriting existing state '{sanitized_name}'")
            
            # Serialize current state
            serialized_state = self.serialize_coordinator_state(request, organization_id, config)
            
            if not serialized_state.get('success'):
                result['error_message'] = f"Failed to serialize state: {serialized_state.get('error_message', 'Unknown error')}"
                logger.error(f"BASE_COORDINATOR: {result['error_message']}")
                return result
            
            result['serialized_keys'] = len(serialized_state.get('session_data', {}))
            
            # Calculate expiration time
            expires_at = None
            if auto_expire:
                expires_at = timezone.now() + timezone.timedelta(seconds=auto_expire)
                result['expires_at'] = expires_at.isoformat()
            
            # Build saved state metadata
            saved_state = {
                'state_data': serialized_state,
                'metadata': {
                    'name': sanitized_name,
                    'description': description,
                    'tags': tags,
                    'saved_at': timezone.now().isoformat(),
                    'saved_by': getattr(request.user, 'username', 'anonymous') if hasattr(request, 'user') else 'system',
                    'organization_id': organization_id,
                    'coordinator_type': self.__class__.__name__,
                    'expires_at': expires_at.isoformat() if expires_at else None,
                    'compressed': compress,
                    'auto_expire': auto_expire
                }
            }
            
            # Add additional metadata if requested
            if include_metadata:
                saved_state['metadata'].update({
                    'session_info': {
                        'session_key': request.session.session_key,
                        'session_modified': request.session.modified
                    },
                    'organization_info': self.get_current_organization(request),
                    'mapping_info': self.get_current_mapping(request)
                })
            
            # Calculate state size
            try:
                state_json = json.dumps(saved_state)
                result['state_size'] = len(state_json.encode('utf-8'))
            except Exception as e:
                logger.warning(f"BASE_COORDINATOR: Failed to calculate state size: {e}")
            
            # Save state to session
            request.session[state_key] = saved_state
            request.session.modified = True
            request.session.save()
            
            # Update state registry
            self._update_state_registry(request, organization_id, sanitized_name, 'saved')
            
            result['success'] = True
            result['metadata'] = saved_state['metadata']
            
            logger.info(f"BASE_COORDINATOR: Successfully saved state '{sanitized_name}' with {result['serialized_keys']} keys ({result['state_size']} bytes)")
            
        except Exception as e:
            result['error_message'] = str(e)
            logger.error(f"BASE_COORDINATOR: Failed to save state '{state_name}': {e}", exc_info=True)
        
        return result

    def load_coordinator_state(self, request, organization_id, state_name, state_config=None):
        """
        Load saved coordinator state from session storage.
        
        This method provides a unified interface for loading named coordinator states
        with automatic validation and deserialization.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            state_name (str): Name of the state to load
            state_config (dict, optional): State configuration for deserialization
                {
                    'merge_strategy': 'replace',  # How to merge with existing state
                    'validate_expiration': True,  # Check if state is expired
                    'auto_cleanup_expired': True,  # Remove expired states
                    'restore_shared_state': True,  # Restore shared state
                    'validate_compatibility': True,  # Validate before loading
                    'backup_current': True  # Backup current state before loading
                }
                
        Returns:
            dict: Load operation results with status and details
                {
                    'success': True,
                    'state_name': 'backup_state',
                    'state_found': True,
                    'state_valid': True,
                    'state_expired': False,
                    'keys_restored': 15,
                    'backup_created': True,
                    'loaded_at': '2024-01-01T12:00:00Z',
                    'error_message': None,
                    'metadata': {...},
                    'deserialization_results': {...}
                }
        """
        logger.info(f"BASE_COORDINATOR: Loading coordinator state '{state_name}' for org {organization_id}")
        
        # Initialize result structure
        result = {
            'success': False,
            'state_name': state_name,
            'state_found': False,
            'state_valid': False,
            'state_expired': False,
            'keys_restored': 0,
            'backup_created': False,
            'loaded_at': None,
            'error_message': None,
            'metadata': {},
            'deserialization_results': {}
        }
        
        try:
            # Validate state name
            if not state_name or not isinstance(state_name, str):
                result['error_message'] = f"Invalid state name: must be a non-empty string, got {type(state_name)}"
                logger.error(f"BASE_COORDINATOR: {result['error_message']}")
                return result
            
            # Sanitize state name
            sanitized_name = state_name.replace(' ', '_').replace('/', '_').replace('\\', '_')
            
            # Initialize configuration
            config = state_config or {}
            merge_strategy = config.get('merge_strategy', 'replace')
            validate_expiration = config.get('validate_expiration', True)
            auto_cleanup_expired = config.get('auto_cleanup_expired', True)
            restore_shared_state = config.get('restore_shared_state', True)
            validate_compatibility = config.get('validate_compatibility', True)
            backup_current = config.get('backup_current', True)
            
            # Generate state key
            state_key = self.get_session_key(f'saved_states_{sanitized_name}', organization_id)
            
            # Check if state exists
            if state_key not in request.session:
                result['error_message'] = f"State '{sanitized_name}' not found"
                logger.error(f"BASE_COORDINATOR: {result['error_message']}")
                return result
            
            result['state_found'] = True
            saved_state = request.session[state_key]
            
            # Validate saved state structure
            if not isinstance(saved_state, dict) or 'state_data' not in saved_state:
                result['error_message'] = f"Invalid saved state structure for '{sanitized_name}'"
                logger.error(f"BASE_COORDINATOR: {result['error_message']}")
                return result
            
            # Extract metadata
            metadata = saved_state.get('metadata', {})
            result['metadata'] = metadata
            
            # Check expiration
            if validate_expiration and metadata.get('expires_at'):
                try:
                    expires_at = timezone.datetime.fromisoformat(metadata['expires_at'].replace('Z', '+00:00'))
                    if timezone.now() > expires_at:
                        result['state_expired'] = True
                        if auto_cleanup_expired:
                            del request.session[state_key]
                            request.session.modified = True
                            self._update_state_registry(request, organization_id, sanitized_name, 'expired')
                            logger.info(f"BASE_COORDINATOR: Auto-cleaned expired state '{sanitized_name}'")
                        
                        result['error_message'] = f"State '{sanitized_name}' expired at {metadata['expires_at']}"
                        logger.error(f"BASE_COORDINATOR: {result['error_message']}")
                        return result
                except Exception as e:
                    logger.warning(f"BASE_COORDINATOR: Failed to check expiration for state '{sanitized_name}': {e}")
            
            # Validate compatibility
            state_data = saved_state['state_data']
            if validate_compatibility:
                compatibility_results = self.validate_state_compatibility(request, organization_id, state_data)
                if not compatibility_results['is_compatible']:
                    result['error_message'] = f"State '{sanitized_name}' is not compatible: {compatibility_results['issues']}"
                    logger.error(f"BASE_COORDINATOR: {result['error_message']}")
                    return result
            
            result['state_valid'] = True
            
            # Backup current state if requested
            if backup_current:
                try:
                    backup_name = f"auto_backup_{sanitized_name}_{int(timezone.now().timestamp())}"
                    backup_result = self.save_coordinator_state(
                        request, organization_id, backup_name, 
                        {'description': f'Auto-backup before loading {sanitized_name}', 'tags': ['auto-backup']}
                    )
                    result['backup_created'] = backup_result['success']
                    if backup_result['success']:
                        logger.info(f"BASE_COORDINATOR: Created backup '{backup_name}' before loading state")
                except Exception as e:
                    logger.warning(f"BASE_COORDINATOR: Failed to create backup: {e}")
            
            # Deserialize state
            deserialize_config = {
                'merge_strategy': merge_strategy,
                'restore_shared_state': restore_shared_state,
                'validation': validate_compatibility
            }
            
            deserialization_results = self.deserialize_coordinator_state(
                request, organization_id, state_data, deserialize_config
            )
            
            result['deserialization_results'] = deserialization_results
            
            if not deserialization_results['success']:
                result['error_message'] = f"Failed to deserialize state: {deserialization_results.get('error_message', 'Unknown error')}"
                logger.error(f"BASE_COORDINATOR: {result['error_message']}")
                return result
            
            result['keys_restored'] = deserialization_results['keys_restored']
            result['loaded_at'] = timezone.now().isoformat()
            result['success'] = True
            
            # Update state registry
            self._update_state_registry(request, organization_id, sanitized_name, 'loaded')
            
            logger.info(f"BASE_COORDINATOR: Successfully loaded state '{sanitized_name}' with {result['keys_restored']} keys")
            
        except Exception as e:
            result['error_message'] = str(e)
            logger.error(f"BASE_COORDINATOR: Failed to load state '{state_name}': {e}", exc_info=True)
        
        return result

    def clear_coordinator_state(self, request, organization_id, state_config=None):
        """
        Clear coordinator state with configurable options.
        
        This method provides a unified interface for clearing coordinator state
        with support for selective clearing and backup creation.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            state_config (dict, optional): State clearing configuration
                {
                    'clear_saved_states': True,  # Clear saved states
                    'clear_workspace': True,  # Clear workspace items
                    'clear_selections': True,  # Clear selections
                    'clear_shared_state': False,  # Clear shared state (org/mapping)
                    'backup_before_clear': True,  # Create backup before clearing
                    'exclude_keys': ['important_data'],  # Keys to preserve
                    'clear_expired_only': False  # Only clear expired saved states
                }
                
        Returns:
            dict: Clear operation results with status and details
                {
                    'success': True,
                    'keys_cleared': 25,
                    'saved_states_cleared': 5,
                    'workspace_items_cleared': 15,
                    'selections_cleared': 3,
                    'shared_state_cleared': False,
                    'backup_created': True,
                    'excluded_keys': ['important_data'],
                    'cleared_at': '2024-01-01T12:00:00Z',
                    'error_message': None,
                    'details': {...}
                }
        """
        logger.info(f"BASE_COORDINATOR: Clearing coordinator state for org {organization_id}")
        
        # Initialize result structure
        result = {
            'success': False,
            'keys_cleared': 0,
            'saved_states_cleared': 0,
            'workspace_items_cleared': 0,
            'selections_cleared': 0,
            'shared_state_cleared': False,
            'backup_created': False,
            'excluded_keys': [],
            'cleared_at': None,
            'error_message': None,
            'details': {}
        }
        
        try:
            # Initialize configuration
            config = state_config or {}
            clear_saved_states = config.get('clear_saved_states', True)
            clear_workspace = config.get('clear_workspace', True)
            clear_selections = config.get('clear_selections', True)
            clear_shared_state = config.get('clear_shared_state', False)
            backup_before_clear = config.get('backup_before_clear', True)
            exclude_keys = config.get('exclude_keys', [])
            clear_expired_only = config.get('clear_expired_only', False)
            
            result['excluded_keys'] = exclude_keys
            
            # Create backup if requested
            if backup_before_clear:
                try:
                    backup_name = f"auto_backup_clear_{int(timezone.now().timestamp())}"
                    backup_result = self.save_coordinator_state(
                        request, organization_id, backup_name,
                        {'description': 'Auto-backup before clearing state', 'tags': ['auto-backup', 'clear']}
                    )
                    result['backup_created'] = backup_result['success']
                    if backup_result['success']:
                        logger.info(f"BASE_COORDINATOR: Created backup '{backup_name}' before clearing")
                except Exception as e:
                    logger.warning(f"BASE_COORDINATOR: Failed to create backup: {e}")
            
            # Get all coordinator session keys
            all_keys = self.get_coordinator_session_keys(request, organization_id)
            
            # Process each key
            for key, value in all_keys.items():
                # Extract base key
                base_key = key.replace(f"_{organization_id}", "")
                
                # Check exclusions
                if base_key in exclude_keys:
                    continue
                
                # Categorize and clear based on configuration
                cleared = False
                
                if clear_saved_states and base_key.startswith('saved_states_'):
                    if clear_expired_only:
                        # Only clear expired states
                        if isinstance(value, dict) and 'metadata' in value:
                            expires_at = value['metadata'].get('expires_at')
                            if expires_at:
                                try:
                                    expires_time = timezone.datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                                    if timezone.now() > expires_time:
                                        del request.session[key]
                                        result['saved_states_cleared'] += 1
                                        cleared = True
                                except Exception:
                                    pass
                    else:
                        del request.session[key]
                        result['saved_states_cleared'] += 1
                        cleared = True
                
                elif clear_workspace and base_key.startswith('workspace_'):
                    del request.session[key]
                    # Count workspace items
                    if isinstance(value, list):
                        result['workspace_items_cleared'] += len(value)
                    cleared = True
                
                elif clear_selections and base_key.startswith('selected_'):
                    del request.session[key]
                    # Count selections
                    if isinstance(value, list):
                        result['selections_cleared'] += len(value)
                    cleared = True
                
                elif not any(base_key.startswith(prefix) for prefix in ['saved_states_', 'workspace_', 'selected_']):
                    # Clear other coordinator keys
                    del request.session[key]
                    cleared = True
                
                if cleared:
                    result['keys_cleared'] += 1
            
            # Clear shared state if requested
            if clear_shared_state:
                self.clear_current_organization(request)
                self.clear_current_mapping(request)
                result['shared_state_cleared'] = True
            
            # Mark session as modified
            request.session.modified = True
            request.session.save()
            
            result['cleared_at'] = timezone.now().isoformat()
            result['success'] = True
            
            # Build details
            result['details'] = {
                'configuration': config,
                'total_keys_processed': len(all_keys),
                'organization_id': organization_id,
                'coordinator_type': self.__class__.__name__
            }
            
            logger.info(f"BASE_COORDINATOR: Successfully cleared coordinator state - {result['keys_cleared']} keys, {result['saved_states_cleared']} saved states")
            
        except Exception as e:
            result['error_message'] = str(e)
            logger.error(f"BASE_COORDINATOR: Failed to clear coordinator state: {e}", exc_info=True)
        
        return result

    def get_state_metadata(self, request, organization_id, state_config=None):
        """
        Get comprehensive metadata about coordinator state.
        
        This method provides detailed information about the current coordinator state
        including statistics, saved states, and debugging information.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            state_config (dict, optional): Metadata configuration
                {
                    'include_session_data': False,  # Include actual session data
                    'include_saved_states': True,  # Include saved states info
                    'include_statistics': True,  # Include detailed statistics
                    'include_debug_info': True,  # Include debug information
                    'validate_states': True,  # Validate saved states
                    'analyze_usage': True  # Analyze session usage patterns
                }
                
        Returns:
            dict: Comprehensive state metadata
                {
                    'organization_id': 123,
                    'coordinator_type': 'CSVMappingCoordinator',
                    'session_prefix': 'csv_mapping',
                    'current_state': {...},
                    'saved_states': {...},
                    'statistics': {...},
                    'debug_info': {...},
                    'validation_results': {...},
                    'usage_analysis': {...},
                    'metadata_generated_at': '2024-01-01T12:00:00Z'
                }
        """
        logger.info(f"BASE_COORDINATOR: Getting state metadata for org {organization_id}")
        
        try:
            # Initialize configuration
            config = state_config or {}
            include_session_data = config.get('include_session_data', False)
            include_saved_states = config.get('include_saved_states', True)
            include_statistics = config.get('include_statistics', True)
            include_debug_info = config.get('include_debug_info', True)
            validate_states = config.get('validate_states', True)
            analyze_usage = config.get('analyze_usage', True)
            
            # Base metadata
            metadata = {
                'organization_id': organization_id,
                'coordinator_type': self.__class__.__name__,
                'session_prefix': None,  # No prefix for single source of truth
                'metadata_generated_at': timezone.now().isoformat()
            }
            
            # Get all coordinator session keys
            all_keys = self.get_coordinator_session_keys(request, organization_id)
            
            # Current state information
            current_state = {
                'total_keys': len(all_keys),
                'key_categories': {
                    'saved_states': len([k for k in all_keys.keys() if 'saved_states_' in k]),
                    'workspace': len([k for k in all_keys.keys() if 'workspace_' in k]),
                    'selections': len([k for k in all_keys.keys() if 'selected_' in k]),
                    'other': len([k for k in all_keys.keys() if not any(prefix in k for prefix in ['saved_states_', 'workspace_', 'selected_'])])
                },
                'shared_state': {
                    'current_organization': self.get_current_organization(request),
                    'current_mapping': self.get_current_mapping(request)
                }
            }
            
            if include_session_data:
                current_state['session_data'] = all_keys
            
            metadata['current_state'] = current_state
            
            # Saved states information
            if include_saved_states:
                saved_states_info = {
                    'total_saved_states': 0,
                    'states_by_name': {},
                    'expired_states': [],
                    'total_state_size': 0
                }
                
                for key, value in all_keys.items():
                    if 'saved_states_' in key and isinstance(value, dict):
                        saved_states_info['total_saved_states'] += 1
                        
                        # Extract state name
                        state_name = key.replace(f"saved_states_", "").replace(f"_{organization_id}", "")
                        
                        state_metadata = value.get('metadata', {})
                        state_info = {
                            'saved_at': state_metadata.get('saved_at'),
                            'description': state_metadata.get('description'),
                            'tags': state_metadata.get('tags', []),
                            'expires_at': state_metadata.get('expires_at'),
                            'coordinator_type': state_metadata.get('coordinator_type')
                        }
                        
                        # Check if expired
                        if state_metadata.get('expires_at'):
                            try:
                                expires_time = timezone.datetime.fromisoformat(state_metadata['expires_at'].replace('Z', '+00:00'))
                                if timezone.now() > expires_time:
                                    saved_states_info['expired_states'].append(state_name)
                                    state_info['is_expired'] = True
                            except Exception:
                                pass
                        
                        # Calculate size
                        try:
                            state_size = len(json.dumps(value).encode('utf-8'))
                            saved_states_info['total_state_size'] += state_size
                            state_info['size_bytes'] = state_size
                        except Exception:
                            pass
                        
                        # Validate state if requested
                        if validate_states:
                            validation_results = self.validate_state_compatibility(
                                request, organization_id, value.get('state_data', {})
                            )
                            state_info['validation'] = {
                                'is_compatible': validation_results['is_compatible'],
                                'issues': validation_results['issues'],
                                'warnings': validation_results['warnings']
                            }
                        
                        saved_states_info['states_by_name'][state_name] = state_info
                
                metadata['saved_states'] = saved_states_info
            
            # Statistics
            if include_statistics:
                statistics = {
                    'session_statistics': {
                        'session_key': request.session.session_key,
                        'session_modified': request.session.modified,
                        'total_session_keys': len(request.session.keys()),
                        'coordinator_session_keys': len(all_keys)
                    },
                    'organization_statistics': {
                        'organization_id': organization_id,
                        'organization_data': self.get_current_organization(request)
                    }
                }
                
                # Add workspace statistics if available
                workspace_stats = self.get_workspace_statistics(request, organization_id)
                if workspace_stats['total_items'] > 0:
                    statistics['workspace_statistics'] = workspace_stats
                
                metadata['statistics'] = statistics
            
            # Debug information
            if include_debug_info:
                debug_info = self.get_coordinator_debug_info(request)
                debug_info['organization_specific'] = {
                    'organization_id': organization_id,
                    'session_key_pattern': f"*_{organization_id}",
                    'key_validation': self.validate_session_key_consistency(request, organization_id)
                }
                metadata['debug_info'] = debug_info
            
            # Usage analysis
            if analyze_usage:
                usage_analysis = {
                    'key_usage_patterns': {},
                    'data_size_distribution': {},
                    'temporal_patterns': {}
                }
                
                # Analyze key usage patterns
                for key in all_keys.keys():
                    base_key = key.replace(f"_{organization_id}", "")
                    category = 'other'
                    
                    if base_key.startswith('saved_states_'):
                        category = 'saved_states'
                    elif base_key.startswith('workspace_'):
                        category = 'workspace'
                    elif base_key.startswith('selected_'):
                        category = 'selections'
                    
                    if category not in usage_analysis['key_usage_patterns']:
                        usage_analysis['key_usage_patterns'][category] = 0
                    usage_analysis['key_usage_patterns'][category] += 1
                
                metadata['usage_analysis'] = usage_analysis
            
            logger.info(f"BASE_COORDINATOR: Generated comprehensive state metadata for org {organization_id}")
            return metadata
            
        except Exception as e:
            logger.error(f"BASE_COORDINATOR: Failed to get state metadata: {e}", exc_info=True)
            return {
                'organization_id': organization_id,
                'coordinator_type': self.__class__.__name__,
                'error_message': str(e),
                'metadata_generated_at': timezone.now().isoformat()
            }

    def _update_state_registry(self, request, organization_id, state_name, action):
        """
        Update the state registry with state operation tracking.
        
        This internal method maintains a registry of state operations for auditing
        and debugging purposes.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            state_name (str): Name of the state
            action (str): Action performed ('saved', 'loaded', 'expired', 'deleted')
        """
        try:
            registry_key = self.get_session_key('state_registry', organization_id)
            registry = request.session.get(registry_key, {})
            
            if state_name not in registry:
                registry[state_name] = []
            
            registry[state_name].append({
                'action': action,
                'timestamp': timezone.now().isoformat(),
                'user': getattr(request.user, 'username', 'anonymous') if hasattr(request, 'user') else 'system'
            })
            
            # Keep only last 10 entries per state
            registry[state_name] = registry[state_name][-10:]
            
            request.session[registry_key] = registry
            request.session.modified = True
            
            logger.debug(f"BASE_COORDINATOR: Updated state registry - {state_name}: {action}")
            
        except Exception as e:
            logger.warning(f"BASE_COORDINATOR: Failed to update state registry: {e}")

    # ==========================================================================
    # Generic Validation and Consistency Check Methods
    # ==========================================================================

    def validate_coordinator_consistency(self, request, organization_id, validation_config=None):
        """
        Comprehensive coordinator consistency validation.
        
        This method performs a complete consistency check across all coordinator
        components including session state, workspace items, selections, and
        cross-component relationships.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            validation_config (dict, optional): Configuration for validation behavior
                - 'auto_fix' (bool): Automatically fix detected issues (default: True)
                - 'strict_mode' (bool): Fail on warnings (default: False)
                - 'include_components' (list): Components to validate (default: all)
                - 'skip_components' (list): Components to skip (default: none)
                
        Returns:
            dict: Comprehensive validation results with detailed findings
        """
        logger.info(f"BASE_COORDINATOR: Starting comprehensive consistency validation for org {organization_id}")
        
        # Default validation configuration
        config = {
            'auto_fix': True,
            'strict_mode': False,
            'include_components': ['session_keys', 'workspace', 'selections', 'state_integrity'],
            'skip_components': []
        }
        if validation_config:
            config.update(validation_config)
        
        validation_results = {
            'organization_id': organization_id,
            'is_consistent': True,
            'overall_status': 'PASS',
            'component_results': {},
            'issues': [],
            'warnings': [],
            'fixes_applied': [],
            'validation_timestamp': timezone.now().isoformat(),
            'validation_config': config
        }
        
        try:
            # Component 1: Session Key Consistency
            if 'session_keys' in config['include_components'] and 'session_keys' not in config['skip_components']:
                logger.debug(f"BASE_COORDINATOR: Validating session key consistency")
                session_validation = self.validate_session_key_consistency(request, organization_id)
                validation_results['component_results']['session_keys'] = session_validation
                
                if not session_validation['is_consistent']:
                    validation_results['is_consistent'] = False
                    validation_results['issues'].extend([f"Session keys: {issue}" for issue in session_validation['issues']])
            
            # Component 2: Workspace Item Consistency
            if 'workspace' in config['include_components'] and 'workspace' not in config['skip_components']:
                logger.debug(f"BASE_COORDINATOR: Validating workspace consistency")
                workspace_validation = self.validate_workspace_uniqueness(request, organization_id, 'columns')
                validation_results['component_results']['workspace'] = {
                    'is_unique': workspace_validation[0],
                    'duplicates_found': workspace_validation[1],
                    'cleaned_items_count': len(workspace_validation[2])
                }
                
                if not workspace_validation[0]:
                    validation_results['is_consistent'] = False
                    validation_results['issues'].append(f"Workspace: Found {len(workspace_validation[1])} duplicate items")
                    if config['auto_fix']:
                        validation_results['fixes_applied'].append(f"Auto-cleaned {len(workspace_validation[1])} duplicate workspace items")
            
            # Component 3: Selection Consistency
            if 'selections' in config['include_components'] and 'selections' not in config['skip_components']:
                logger.debug(f"BASE_COORDINATOR: Validating selection consistency")
                selection_validation = self.validate_dataset_selection_consistency(request, organization_id, 'datasets')
                validation_results['component_results']['selections'] = selection_validation[2]
                
                if not selection_validation[0]:
                    validation_results['is_consistent'] = False
                    validation_results['issues'].extend([f"Selections: {issue}" for issue in selection_validation[1]])
            
            # Component 4: Selection-Workspace Cross-Validation
            if 'cross_validation' in config['include_components'] and 'cross_validation' not in config['skip_components']:
                logger.debug(f"BASE_COORDINATOR: Validating selection-workspace consistency")
                cross_validation = self.validate_selection_workspace_consistency(request, organization_id)
                validation_results['component_results']['cross_validation'] = cross_validation
                
                if not cross_validation['is_consistent']:
                    validation_results['is_consistent'] = False
                    validation_results['issues'].extend([f"Cross-validation: {issue}" for issue in cross_validation['issues']])
            
            # Component 5: State Integrity
            if 'state_integrity' in config['include_components'] and 'state_integrity' not in config['skip_components']:
                logger.debug(f"BASE_COORDINATOR: Validating state integrity")
                state_validation = self.validate_state_integrity(request, organization_id)
                validation_results['component_results']['state_integrity'] = state_validation
                
                if not state_validation['is_consistent']:
                    validation_results['is_consistent'] = False
                    validation_results['issues'].extend([f"State integrity: {issue}" for issue in state_validation['issues']])
            
            # Determine overall status
            if validation_results['is_consistent']:
                validation_results['overall_status'] = 'PASS'
            elif config['strict_mode'] and validation_results['warnings']:
                validation_results['overall_status'] = 'FAIL'
                validation_results['is_consistent'] = False
            else:
                validation_results['overall_status'] = 'FAIL' if not validation_results['is_consistent'] else 'WARN'
            
            # Auto-fix remaining issues if enabled
            if config['auto_fix'] and not validation_results['is_consistent']:
                logger.info(f"BASE_COORDINATOR: Attempting auto-fix for detected issues")
                fix_results = self.auto_fix_consistency_issues(request, organization_id, {
                    'fix_duplicates': True,
                    'fix_orphaned_keys': True,
                    'fix_invalid_selections': True
                })
                validation_results['fixes_applied'].extend(fix_results['fixes_applied'])
                
                if fix_results['fixes_successful']:
                    validation_results['warnings'].append("Auto-fix applied successfully")
                else:
                    validation_results['issues'].append("Auto-fix failed for some issues")
            
        except Exception as e:
            logger.error(f"BASE_COORDINATOR: Error during consistency validation: {e}", exc_info=True)
            validation_results['is_consistent'] = False
            validation_results['overall_status'] = 'ERROR'
            validation_results['issues'].append(f"Validation error: {str(e)}")
        
        # Log final results
        status_msg = f"Consistency validation {validation_results['overall_status']} for org {organization_id}"
        if validation_results['is_consistent']:
            logger.info(f"BASE_COORDINATOR: {status_msg}")
        else:
            logger.warning(f"BASE_COORDINATOR: {status_msg} - Issues: {len(validation_results['issues'])}, Warnings: {len(validation_results['warnings'])}")
        
        return validation_results

    def validate_item_uniqueness(self, request, organization_id, item_type='columns', validation_config=None):
        """
        Generic item uniqueness validation for any item type.
        
        This method provides comprehensive uniqueness validation with configurable
        criteria and automatic cleanup capabilities.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            item_type (str): Type of items to validate (default: 'columns')
            validation_config (dict, optional): Configuration for validation behavior
                - 'uniqueness_key' (str): Key to use for uniqueness check (default: 'id')
                - 'auto_clean' (bool): Automatically remove duplicates (default: True)
                - 'strict_validation' (bool): Strict type checking (default: False)
                - 'custom_validator' (callable): Custom validation function
                
        Returns:
            dict: Detailed validation results with uniqueness status and actions taken
        """
        logger.info(f"BASE_COORDINATOR: Validating {item_type} uniqueness for org {organization_id}")
        
        # Default validation configuration
        config = {
            'uniqueness_key': 'id',
            'auto_clean': True,
            'strict_validation': False,
            'custom_validator': None
        }
        if validation_config:
            config.update(validation_config)
        
        validation_results = {
            'organization_id': organization_id,
            'item_type': item_type,
            'is_unique': True,
            'total_items': 0,
            'unique_items': 0,
            'duplicate_items': [],
            'invalid_items': [],
            'cleaned_items': [],
            'issues': [],
            'warnings': [],
            'actions_taken': [],
            'validation_timestamp': timezone.now().isoformat(),
            'validation_config': config
        }
        
        try:
            # Get items from workspace
            items = self.get_workspace_items(request, organization_id, item_type)
            validation_results['total_items'] = len(items)
            
            seen_keys = set()
            valid_items = []
            duplicate_items = []
            invalid_items = []
            
            for item in items:
                # Basic type validation
                if not isinstance(item, dict):
                    invalid_items.append({
                        'item': item,
                        'reason': 'Not a dictionary object'
                    })
                    continue
                
                # Get uniqueness key
                uniqueness_value = item.get(config['uniqueness_key'])
                
                # Validate uniqueness key exists
                if uniqueness_value is None:
                    invalid_items.append({
                        'item': item,
                        'reason': f"Missing uniqueness key: {config['uniqueness_key']}"
                    })
                    continue
                
                # Strict validation if enabled
                if config['strict_validation']:
                    if not isinstance(uniqueness_value, (str, int)):
                        invalid_items.append({
                            'item': item,
                            'reason': f"Invalid type for uniqueness key: {type(uniqueness_value)}"
                        })
                        continue
                
                # Custom validation if provided
                if config['custom_validator']:
                    try:
                        if not config['custom_validator'](item):
                            invalid_items.append({
                                'item': item,
                                'reason': 'Failed custom validation'
                            })
                            continue
                    except Exception as e:
                        invalid_items.append({
                            'item': item,
                            'reason': f'Custom validator error: {str(e)}'
                        })
                        continue
                
                # Check for duplicates
                if uniqueness_value in seen_keys:
                    duplicate_items.append({
                        'item': item,
                        'duplicate_key': uniqueness_value
                    })
                else:
                    seen_keys.add(uniqueness_value)
                    valid_items.append(item)
            
            # Update validation results
            validation_results['unique_items'] = len(valid_items)
            validation_results['duplicate_items'] = duplicate_items
            validation_results['invalid_items'] = invalid_items
            validation_results['cleaned_items'] = valid_items
            
            # Determine if collection is unique
            validation_results['is_unique'] = len(duplicate_items) == 0 and len(invalid_items) == 0
            
            # Generate issues and warnings
            if duplicate_items:
                validation_results['issues'].append(f"Found {len(duplicate_items)} duplicate {item_type}")
                validation_results['warnings'].append(f"Duplicate keys: {[item['duplicate_key'] for item in duplicate_items]}")
            
            if invalid_items:
                validation_results['issues'].append(f"Found {len(invalid_items)} invalid {item_type}")
                validation_results['warnings'].append(f"Invalid items: {[item['reason'] for item in invalid_items]}")
            
            # Auto-clean if enabled and issues found
            if config['auto_clean'] and not validation_results['is_unique']:
                logger.info(f"BASE_COORDINATOR: Auto-cleaning {len(duplicate_items) + len(invalid_items)} problematic {item_type}")
                
                # Update workspace with cleaned items
                self.update_workspace_items(request, organization_id, valid_items, item_type)
                
                validation_results['actions_taken'].append(f"Removed {len(duplicate_items)} duplicates and {len(invalid_items)} invalid items")
                validation_results['warnings'].append(f"Auto-cleaned workspace: {len(valid_items)} items remain")
            
        except Exception as e:
            logger.error(f"BASE_COORDINATOR: Error validating {item_type} uniqueness: {e}", exc_info=True)
            validation_results['is_unique'] = False
            validation_results['issues'].append(f"Validation error: {str(e)}")
        
        # Log results
        if validation_results['is_unique']:
            logger.info(f"BASE_COORDINATOR: {item_type} uniqueness validation PASSED for org {organization_id}")
        else:
            logger.warning(f"BASE_COORDINATOR: {item_type} uniqueness validation FAILED for org {organization_id} - Issues: {len(validation_results['issues'])}")
        
        return validation_results

    def cleanup_orphaned_items(self, request, organization_id, item_type='columns', cleanup_config=None):
        """
        Remove orphaned items from coordinator state.
        
        This method identifies and removes items that are no longer valid or
        referenced, helping maintain clean state across coordinator components.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            item_type (str): Type of items to clean up (default: 'columns')
            cleanup_config (dict, optional): Configuration for cleanup behavior
                - 'dry_run' (bool): Only identify orphans without removing (default: False)
                - 'orphan_criteria' (list): List of criteria for identifying orphans
                - 'preserve_patterns' (list): Patterns to preserve during cleanup
                - 'batch_size' (int): Number of items to process at once (default: 100)
                
        Returns:
            dict: Cleanup results with items removed and actions taken
        """
        logger.info(f"BASE_COORDINATOR: Cleaning up orphaned {item_type} for org {organization_id}")
        
        # Default cleanup configuration
        config = {
            'dry_run': False,
            'orphan_criteria': ['missing_references', 'invalid_structure', 'expired_items'],
            'preserve_patterns': [],
            'batch_size': 100
        }
        if cleanup_config:
            config.update(cleanup_config)
        
        cleanup_results = {
            'organization_id': organization_id,
            'item_type': item_type,
            'items_processed': 0,
            'orphans_found': 0,
            'orphans_removed': 0,
            'items_preserved': 0,
            'orphaned_items': [],
            'preserved_items': [],
            'actions_taken': [],
            'issues': [],
            'warnings': [],
            'cleanup_timestamp': timezone.now().isoformat(),
            'cleanup_config': config
        }
        
        try:
            # Get current workspace items
            current_items = self.get_workspace_items(request, organization_id, item_type)
            cleanup_results['items_processed'] = len(current_items)
            
            # Get related data for reference validation
            selected_datasets = self.get_selected_datasets(request, organization_id, 'datasets')
            
            valid_items = []
            orphaned_items = []
            
            for item in current_items:
                is_orphan = False
                orphan_reasons = []
                
                # Check orphan criteria
                if 'missing_references' in config['orphan_criteria']:
                    # Check if item references non-existent datasets
                    if isinstance(item, dict) and 'dataset' in item:
                        if item['dataset'] not in selected_datasets:
                            is_orphan = True
                            orphan_reasons.append(f"References non-existent dataset: {item['dataset']}")
                
                if 'invalid_structure' in config['orphan_criteria']:
                    # Check if item has valid structure
                    if not isinstance(item, dict):
                        is_orphan = True
                        orphan_reasons.append("Invalid item structure (not a dictionary)")
                    elif isinstance(item, dict) and not item.get('id'):
                        is_orphan = True
                        orphan_reasons.append("Missing required 'id' field")
                
                if 'expired_items' in config['orphan_criteria']:
                    # Check if item has expired timestamp
                    if isinstance(item, dict) and 'timestamp' in item:
                        try:
                            item_time = timezone.datetime.fromisoformat(item['timestamp'].replace('Z', '+00:00'))
                            if (timezone.now() - item_time).days > 30:  # 30 days old
                                is_orphan = True
                                orphan_reasons.append("Item is older than 30 days")
                        except (ValueError, TypeError):
                            pass
                
                # Check preservation patterns
                should_preserve = False
                if isinstance(item, dict) and 'id' in item:
                    for pattern in config['preserve_patterns']:
                        if pattern in str(item['id']):
                            should_preserve = True
                            break
                
                # Categorize item
                if is_orphan and not should_preserve:
                    orphaned_items.append({
                        'item': item,
                        'reasons': orphan_reasons
                    })
                else:
                    valid_items.append(item)
                    if should_preserve:
                        cleanup_results['preserved_items'].append(item)
            
            # Update results
            cleanup_results['orphans_found'] = len(orphaned_items)
            cleanup_results['items_preserved'] = len(cleanup_results['preserved_items'])
            cleanup_results['orphaned_items'] = orphaned_items
            
            # Perform cleanup if not dry run
            if not config['dry_run'] and orphaned_items:
                logger.info(f"BASE_COORDINATOR: Removing {len(orphaned_items)} orphaned {item_type}")
                
                # Process in batches if needed
                batch_size = config['batch_size']
                if len(valid_items) > batch_size:
                    logger.info(f"BASE_COORDINATOR: Processing {len(valid_items)} items in batches of {batch_size}")
                
                # Update workspace with cleaned items
                self.update_workspace_items(request, organization_id, valid_items, item_type)
                
                cleanup_results['orphans_removed'] = len(orphaned_items)
                cleanup_results['actions_taken'].append(f"Removed {len(orphaned_items)} orphaned {item_type}")
                
                # Clean up related session keys
                orphaned_keys = []
                for item in orphaned_items:
                    if isinstance(item['item'], dict) and 'id' in item['item']:
                        item_key = self.get_session_key(f"{item_type}_{item['item']['id']}", organization_id)
                        if item_key in request.session:
                            del request.session[item_key]
                            orphaned_keys.append(item_key)
                
                if orphaned_keys:
                    cleanup_results['actions_taken'].append(f"Cleaned up {len(orphaned_keys)} orphaned session keys")
                    request.session.modified = True
            
            elif config['dry_run'] and orphaned_items:
                cleanup_results['actions_taken'].append(f"DRY RUN: Would remove {len(orphaned_items)} orphaned {item_type}")
                cleanup_results['warnings'].append("Dry run mode - no actual cleanup performed")
            
        except Exception as e:
            logger.error(f"BASE_COORDINATOR: Error during orphan cleanup: {e}", exc_info=True)
            cleanup_results['issues'].append(f"Cleanup error: {str(e)}")
        
        # Log results
        if cleanup_results['orphans_found'] > 0:
            logger.info(f"BASE_COORDINATOR: Orphan cleanup completed - Found: {cleanup_results['orphans_found']}, Removed: {cleanup_results['orphans_removed']}")
        else:
            logger.info(f"BASE_COORDINATOR: No orphaned {item_type} found for org {organization_id}")
        
        return cleanup_results

    def validate_selection_workspace_consistency(self, request, organization_id, validation_config=None):
        """
        Validate consistency between selections and workspace items.
        
        This method ensures that workspace items are consistent with current
        selections and identifies any mismatches or orphaned relationships.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            validation_config (dict, optional): Configuration for validation behavior
                - 'require_selection_match' (bool): Require workspace items to match selections (default: True)
                - 'auto_sync' (bool): Automatically sync inconsistencies (default: False)
                - 'sync_direction' (str): Direction to sync ('selection_to_workspace' or 'workspace_to_selection')
                
        Returns:
            dict: Validation results with consistency status and recommendations
        """
        logger.info(f"BASE_COORDINATOR: Validating selection-workspace consistency for org {organization_id}")
        
        # Default validation configuration
        config = {
            'require_selection_match': True,
            'auto_sync': False,
            'sync_direction': 'selection_to_workspace'
        }
        if validation_config:
            config.update(validation_config)
        
        validation_results = {
            'organization_id': organization_id,
            'is_consistent': True,
            'selected_datasets': [],
            'workspace_datasets': [],
            'missing_in_workspace': [],
            'missing_in_selection': [],
            'orphaned_workspace_items': [],
            'consistency_score': 0.0,
            'issues': [],
            'warnings': [],
            'recommendations': [],
            'actions_taken': [],
            'validation_timestamp': timezone.now().isoformat(),
            'validation_config': config
        }
        
        try:
            # Get current selections and workspace items
            selected_datasets = self.get_selected_datasets(request, organization_id, 'datasets')
            workspace_items = self.get_workspace_items(request, organization_id, 'columns')
            
            validation_results['selected_datasets'] = selected_datasets
            
            # Extract unique datasets from workspace items
            workspace_datasets = set()
            for item in workspace_items:
                if isinstance(item, dict) and 'dataset' in item:
                    workspace_datasets.add(item['dataset'])
            
            validation_results['workspace_datasets'] = list(workspace_datasets)
            
            # Find inconsistencies
            selected_set = set(selected_datasets)
            workspace_set = set(workspace_datasets)
            
            missing_in_workspace = selected_set - workspace_set
            missing_in_selection = workspace_set - selected_set
            
            validation_results['missing_in_workspace'] = list(missing_in_workspace)
            validation_results['missing_in_selection'] = list(missing_in_selection)
            
            # Find orphaned workspace items
            orphaned_items = []
            for item in workspace_items:
                if isinstance(item, dict) and 'dataset' in item:
                    if item['dataset'] not in selected_datasets:
                        orphaned_items.append(item)
            
            validation_results['orphaned_workspace_items'] = orphaned_items
            
            # Calculate consistency score
            total_datasets = len(selected_set | workspace_set)
            consistent_datasets = len(selected_set & workspace_set)
            validation_results['consistency_score'] = (consistent_datasets / total_datasets) if total_datasets > 0 else 1.0
            
            # Determine consistency status
            validation_results['is_consistent'] = (
                len(missing_in_workspace) == 0 and
                len(missing_in_selection) == 0 and
                len(orphaned_items) == 0
            )
            
            # Generate issues and recommendations
            if missing_in_workspace:
                validation_results['issues'].append(f"Selected datasets missing from workspace: {list(missing_in_workspace)}")
                validation_results['recommendations'].append(f"Add workspace columns for datasets: {list(missing_in_workspace)}")
            
            if missing_in_selection:
                if config['require_selection_match']:
                    validation_results['issues'].append(f"Workspace datasets not in selection: {list(missing_in_selection)}")
                    validation_results['recommendations'].append(f"Either select datasets or remove workspace items: {list(missing_in_selection)}")
                else:
                    validation_results['warnings'].append(f"Workspace datasets not in selection: {list(missing_in_selection)}")
            
            if orphaned_items:
                validation_results['issues'].append(f"Found {len(orphaned_items)} orphaned workspace items")
                validation_results['recommendations'].append("Remove orphaned workspace items or add corresponding dataset selections")
            
            # Auto-sync if enabled
            if config['auto_sync'] and not validation_results['is_consistent']:
                logger.info(f"BASE_COORDINATOR: Auto-syncing selection-workspace inconsistencies")
                
                if config['sync_direction'] == 'selection_to_workspace':
                    # Remove orphaned workspace items
                    if orphaned_items:
                        cleaned_items = [item for item in workspace_items if item not in orphaned_items]
                        self.update_workspace_items(request, organization_id, cleaned_items, 'columns')
                        validation_results['actions_taken'].append(f"Removed {len(orphaned_items)} orphaned workspace items")
                
                elif config['sync_direction'] == 'workspace_to_selection':
                    # Add missing datasets to selection
                    if missing_in_selection:
                        updated_selection = selected_datasets + list(missing_in_selection)
                        self.set_selected_datasets(request, organization_id, updated_selection, 'datasets')
                        validation_results['actions_taken'].append(f"Added {len(missing_in_selection)} datasets to selection")
            
        except Exception as e:
            logger.error(f"BASE_COORDINATOR: Error validating selection-workspace consistency: {e}", exc_info=True)
            validation_results['is_consistent'] = False
            validation_results['issues'].append(f"Validation error: {str(e)}")
        
        # Log results
        if validation_results['is_consistent']:
            logger.info(f"BASE_COORDINATOR: Selection-workspace consistency validation PASSED for org {organization_id}")
        else:
            logger.warning(f"BASE_COORDINATOR: Selection-workspace consistency validation FAILED for org {organization_id} - Score: {validation_results['consistency_score']:.2f}")
        
        return validation_results

    def get_consistency_report(self, request, organization_id, report_config=None):
        """
        Generate comprehensive consistency report.
        
        This method creates a detailed report of all coordinator state components
        with consistency analysis, issue identification, and recommended actions.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            report_config (dict, optional): Configuration for report generation
                - 'include_raw_data' (bool): Include raw session data (default: False)
                - 'include_statistics' (bool): Include detailed statistics (default: True)
                - 'include_recommendations' (bool): Include action recommendations (default: True)
                - 'format' (str): Report format ('dict' or 'json') (default: 'dict')
                
        Returns:
            dict: Comprehensive consistency report with all findings and recommendations
        """
        logger.info(f"BASE_COORDINATOR: Generating consistency report for org {organization_id}")
        
        # Default report configuration
        config = {
            'include_raw_data': False,
            'include_statistics': True,
            'include_recommendations': True,
            'format': 'dict'
        }
        if report_config:
            config.update(report_config)
        
        report = {
            'organization_id': organization_id,
            'report_timestamp': timezone.now().isoformat(),
            'report_config': config,
            'overall_status': 'UNKNOWN',
            'overall_score': 0.0,
            'components': {},
            'summary': {
                'total_issues': 0,
                'total_warnings': 0,
                'critical_issues': 0,
                'recommendations': []
            },
            'raw_data': {} if config['include_raw_data'] else None,
            'statistics': {} if config['include_statistics'] else None
        }
        
        try:
            # Component 1: Coordinator Consistency
            logger.debug("BASE_COORDINATOR: Running coordinator consistency check")
            coordinator_validation = self.validate_coordinator_consistency(request, organization_id)
            report['components']['coordinator_consistency'] = coordinator_validation
            
            # Component 2: Item Uniqueness
            logger.debug("BASE_COORDINATOR: Running item uniqueness check")
            uniqueness_validation = self.validate_item_uniqueness(request, organization_id, 'columns')
            report['components']['item_uniqueness'] = uniqueness_validation
            
            # Component 3: Selection-Workspace Consistency
            logger.debug("BASE_COORDINATOR: Running selection-workspace consistency check")
            selection_workspace_validation = self.validate_selection_workspace_consistency(request, organization_id)
            report['components']['selection_workspace_consistency'] = selection_workspace_validation
            
            # Component 4: State Integrity
            logger.debug("BASE_COORDINATOR: Running state integrity check")
            state_validation = self.validate_state_integrity(request, organization_id)
            report['components']['state_integrity'] = state_validation
            
            # Calculate overall metrics
            component_scores = []
            total_issues = 0
            total_warnings = 0
            critical_issues = 0
            all_recommendations = []
            
            for component_name, component_data in report['components'].items():
                # Extract score based on component type
                if component_name == 'coordinator_consistency':
                    score = 1.0 if component_data['is_consistent'] else 0.0
                elif component_name == 'item_uniqueness':
                    score = 1.0 if component_data['is_unique'] else 0.0
                elif component_name == 'selection_workspace_consistency':
                    score = component_data['consistency_score']
                elif component_name == 'state_integrity':
                    score = 1.0 if component_data['is_consistent'] else 0.0
                else:
                    score = 0.5  # Default for unknown components
                
                component_scores.append(score)
                
                # Count issues and warnings
                if 'issues' in component_data:
                    issues_count = len(component_data['issues'])
                    total_issues += issues_count
                    if issues_count > 0:
                        critical_issues += 1
                
                if 'warnings' in component_data:
                    total_warnings += len(component_data['warnings'])
                
                # Collect recommendations
                if 'recommendations' in component_data:
                    all_recommendations.extend(component_data['recommendations'])
            
            # Calculate overall score
            report['overall_score'] = sum(component_scores) / len(component_scores) if component_scores else 0.0
            
            # Determine overall status
            if report['overall_score'] >= 0.9:
                report['overall_status'] = 'EXCELLENT'
            elif report['overall_score'] >= 0.7:
                report['overall_status'] = 'GOOD'
            elif report['overall_score'] >= 0.5:
                report['overall_status'] = 'NEEDS_ATTENTION'
            else:
                report['overall_status'] = 'CRITICAL'
            
            # Update summary
            report['summary']['total_issues'] = total_issues
            report['summary']['total_warnings'] = total_warnings
            report['summary']['critical_issues'] = critical_issues
            report['summary']['recommendations'] = all_recommendations
            
            # Add statistics if requested
            if config['include_statistics']:
                report['statistics'] = {
                    'session_key_count': len(self.get_coordinator_session_keys(request, organization_id)),
                    'workspace_item_count': len(self.get_workspace_items(request, organization_id, 'columns')),
                    'selected_dataset_count': len(self.get_selected_datasets(request, organization_id, 'datasets')),
                    'component_scores': dict(zip(report['components'].keys(), component_scores))
                }
            
            # Add raw data if requested
            if config['include_raw_data']:
                report['raw_data'] = {
                    'session_keys': self.get_coordinator_session_keys(request, organization_id),
                    'workspace_items': self.get_workspace_items(request, organization_id, 'columns'),
                    'selected_datasets': self.get_selected_datasets(request, organization_id, 'datasets')
                }
            
        except Exception as e:
            logger.error(f"BASE_COORDINATOR: Error generating consistency report: {e}", exc_info=True)
            report['overall_status'] = 'ERROR'
            report['summary']['total_issues'] += 1
            report['summary']['recommendations'].append(f"Fix report generation error: {str(e)}")
        
        # Log report summary
        logger.info(f"BASE_COORDINATOR: Consistency report generated - Status: {report['overall_status']}, Score: {report['overall_score']:.2f}, Issues: {report['summary']['total_issues']}")
        
        # Return in requested format
        if config['format'] == 'json':
            return json.dumps(report, indent=2)
        else:
            return report

    def auto_fix_consistency_issues(self, request, organization_id, fix_config=None):
        """
        Auto-fix common consistency issues.
        
        This method automatically resolves common consistency problems found
        during validation, with configurable fix strategies and rollback support.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            fix_config (dict, optional): Configuration for fix behavior
                - 'fix_duplicates' (bool): Fix duplicate items (default: True)
                - 'fix_orphaned_keys' (bool): Remove orphaned session keys (default: True)
                - 'fix_invalid_selections' (bool): Clean invalid selections (default: True)
                - 'fix_workspace_issues' (bool): Fix workspace inconsistencies (default: True)
                - 'create_backup' (bool): Create state backup before fixing (default: True)
                - 'rollback_on_error' (bool): Rollback changes on error (default: True)
                
        Returns:
            dict: Fix results with actions taken and success status
        """
        logger.info(f"BASE_COORDINATOR: Auto-fixing consistency issues for org {organization_id}")
        
        # Default fix configuration
        config = {
            'fix_duplicates': True,
            'fix_orphaned_keys': True,
            'fix_invalid_selections': True,
            'fix_workspace_issues': True,
            'create_backup': True,
            'rollback_on_error': True
        }
        if fix_config:
            config.update(fix_config)
        
        fix_results = {
            'organization_id': organization_id,
            'fixes_successful': True,
            'fixes_applied': [],
            'fixes_failed': [],
            'issues_resolved': 0,
            'backup_created': False,
            'rollback_performed': False,
            'fix_timestamp': timezone.now().isoformat(),
            'fix_config': config
        }
        
        backup_data = None
        
        try:
            # Create backup if requested
            if config['create_backup']:
                logger.debug("BASE_COORDINATOR: Creating state backup before fixes")
                backup_data = self.serialize_coordinator_state(request, organization_id)
                fix_results['backup_created'] = True
                fix_results['fixes_applied'].append("Created state backup")
            
            # Fix 1: Remove duplicate workspace items
            if config['fix_duplicates']:
                logger.debug("BASE_COORDINATOR: Fixing duplicate workspace items")
                uniqueness_result = self.validate_item_uniqueness(request, organization_id, 'columns', {
                    'auto_clean': True
                })
                
                if not uniqueness_result['is_unique']:
                    duplicates_removed = len(uniqueness_result['duplicate_items'])
                    fix_results['fixes_applied'].append(f"Removed {duplicates_removed} duplicate workspace items")
                    fix_results['issues_resolved'] += duplicates_removed
            
            # Fix 2: Clean up orphaned session keys
            if config['fix_orphaned_keys']:
                logger.debug("BASE_COORDINATOR: Cleaning up orphaned session keys")
                orphaned_keys = []
                
                # Get all session keys and check for orphans
                all_keys = list(request.session.keys())
                for key in all_keys:
                    # With single source of truth, no prefix filtering needed
                    if True:  # Include all keys
                        # Check if key has valid organization ID
                        parts = key.split('_')
                        if len(parts) >= 3 and parts[-1].isdigit():
                            key_org_id = int(parts[-1])
                            if key_org_id != organization_id:
                                # This is an orphaned key for a different organization
                                orphaned_keys.append(key)
                        elif not parts[-1].isdigit():
                            # Key doesn't end with organization ID - might be orphaned
                            orphaned_keys.append(key)
                
                # Remove orphaned keys
                for key in orphaned_keys:
                    if key in request.session:
                        del request.session[key]
                
                if orphaned_keys:
                    request.session.modified = True
                    fix_results['fixes_applied'].append(f"Removed {len(orphaned_keys)} orphaned session keys")
                    fix_results['issues_resolved'] += len(orphaned_keys)
            
            # Fix 3: Clean invalid selections
            if config['fix_invalid_selections']:
                logger.debug("BASE_COORDINATOR: Cleaning invalid selections")
                selection_validation = self.validate_dataset_selection_consistency(request, organization_id, 'datasets')
                
                if not selection_validation[0]:
                    fix_results['fixes_applied'].append("Cleaned invalid dataset selections")
                    fix_results['issues_resolved'] += len(selection_validation[1])
            
            # Fix 4: Fix workspace issues
            if config['fix_workspace_issues']:
                logger.debug("BASE_COORDINATOR: Fixing workspace issues")
                cleanup_result = self.cleanup_orphaned_items(request, organization_id, 'columns', {
                    'dry_run': False
                })
                
                if cleanup_result['orphans_removed'] > 0:
                    fix_results['fixes_applied'].append(f"Removed {cleanup_result['orphans_removed']} orphaned workspace items")
                    fix_results['issues_resolved'] += cleanup_result['orphans_removed']
            
            # Verify fixes were successful
            if fix_results['issues_resolved'] > 0:
                logger.info(f"BASE_COORDINATOR: Successfully resolved {fix_results['issues_resolved']} consistency issues")
                
                # Run final validation to confirm fixes
                final_validation = self.validate_coordinator_consistency(request, organization_id, {
                    'auto_fix': False
                })
                
                if not final_validation['is_consistent']:
                    fix_results['fixes_failed'].append("Some issues remain after auto-fix")
                    fix_results['fixes_successful'] = False
            
        except Exception as e:
            logger.error(f"BASE_COORDINATOR: Error during auto-fix: {e}", exc_info=True)
            fix_results['fixes_successful'] = False
            fix_results['fixes_failed'].append(f"Auto-fix error: {str(e)}")
            
            # Rollback if requested and backup exists
            if config['rollback_on_error'] and backup_data:
                logger.info("BASE_COORDINATOR: Rolling back changes due to error")
                try:
                    self.deserialize_coordinator_state(request, organization_id, backup_data)
                    fix_results['rollback_performed'] = True
                    fix_results['fixes_applied'].append("Rolled back changes due to error")
                except Exception as rollback_error:
                    logger.error(f"BASE_COORDINATOR: Rollback failed: {rollback_error}")
                    fix_results['fixes_failed'].append(f"Rollback failed: {str(rollback_error)}")
        
        # Log final results
        if fix_results['fixes_successful']:
            logger.info(f"BASE_COORDINATOR: Auto-fix completed successfully - {fix_results['issues_resolved']} issues resolved")
        else:
            logger.warning(f"BASE_COORDINATOR: Auto-fix completed with errors - {len(fix_results['fixes_failed'])} failures")
        
        return fix_results

    def validate_state_integrity(self, request, organization_id, validation_config=None):
        """
        Validate overall state integrity.
        
        This method performs comprehensive validation of the coordinator's internal
        state to ensure data integrity and consistency across all components.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            validation_config (dict, optional): Configuration for validation behavior
                - 'check_data_types' (bool): Validate data types (default: True)
                - 'check_references' (bool): Validate cross-references (default: True)
                - 'check_timestamps' (bool): Validate timestamps (default: True)
                - 'check_constraints' (bool): Validate business constraints (default: True)
                
        Returns:
            dict: State integrity validation results with detailed findings
        """
        logger.info(f"BASE_COORDINATOR: Validating state integrity for org {organization_id}")
        
        # Default validation configuration
        config = {
            'check_data_types': True,
            'check_references': True,
            'check_timestamps': True,
            'check_constraints': True
        }
        if validation_config:
            config.update(validation_config)
        
        validation_results = {
            'organization_id': organization_id,
            'is_consistent': True,
            'integrity_score': 0.0,
            'checks_performed': [],
            'issues': [],
            'warnings': [],
            'data_type_issues': [],
            'reference_issues': [],
            'timestamp_issues': [],
            'constraint_violations': [],
            'recommendations': [],
            'validation_timestamp': timezone.now().isoformat(),
            'validation_config': config
        }
        
        try:
            total_checks = 0
            passed_checks = 0
            
            # Check 1: Data Type Validation
            if config['check_data_types']:
                logger.debug("BASE_COORDINATOR: Checking data types")
                validation_results['checks_performed'].append('data_types')
                total_checks += 1
                
                # Check workspace items data types
                workspace_items = self.get_workspace_items(request, organization_id, 'columns')
                for i, item in enumerate(workspace_items):
                    if not isinstance(item, dict):
                        validation_results['data_type_issues'].append(f"Workspace item {i} is not a dictionary: {type(item)}")
                        validation_results['is_consistent'] = False
                    elif isinstance(item, dict):
                        # Check required fields
                        if 'id' not in item:
                            validation_results['data_type_issues'].append(f"Workspace item {i} missing 'id' field")
                            validation_results['is_consistent'] = False
                        elif not isinstance(item['id'], str):
                            validation_results['data_type_issues'].append(f"Workspace item {i} 'id' is not a string: {type(item['id'])}")
                            validation_results['is_consistent'] = False
                
                # Check selected datasets data types
                selected_datasets = self.get_selected_datasets(request, organization_id, 'datasets')
                if not isinstance(selected_datasets, list):
                    validation_results['data_type_issues'].append(f"Selected datasets is not a list: {type(selected_datasets)}")
                    validation_results['is_consistent'] = False
                else:
                    for i, dataset in enumerate(selected_datasets):
                        if not isinstance(dataset, str):
                            validation_results['data_type_issues'].append(f"Selected dataset {i} is not a string: {type(dataset)}")
                            validation_results['is_consistent'] = False
                
                if not validation_results['data_type_issues']:
                    passed_checks += 1
            
            # Check 2: Cross-Reference Validation
            if config['check_references']:
                logger.debug("BASE_COORDINATOR: Checking cross-references")
                validation_results['checks_performed'].append('references')
                total_checks += 1
                
                # Check workspace-selection consistency
                workspace_items = self.get_workspace_items(request, organization_id, 'columns')
                selected_datasets = self.get_selected_datasets(request, organization_id, 'datasets')
                
                workspace_datasets = set()
                for item in workspace_items:
                    if isinstance(item, dict) and 'dataset' in item:
                        workspace_datasets.add(item['dataset'])
                
                # Check for references to non-selected datasets
                for dataset in workspace_datasets:
                    if dataset not in selected_datasets:
                        validation_results['reference_issues'].append(f"Workspace references unselected dataset: {dataset}")
                        validation_results['is_consistent'] = False
                
                # Check for missing workspace items for selected datasets
                for dataset in selected_datasets:
                    if dataset not in workspace_datasets:
                        validation_results['warnings'].append(f"Selected dataset has no workspace items: {dataset}")
                
                if not validation_results['reference_issues']:
                    passed_checks += 1
            
            # Check 3: Timestamp Validation
            if config['check_timestamps']:
                logger.debug("BASE_COORDINATOR: Checking timestamps")
                validation_results['checks_performed'].append('timestamps')
                total_checks += 1
                
                # Check workspace item timestamps
                workspace_items = self.get_workspace_items(request, organization_id, 'columns')
                for i, item in enumerate(workspace_items):
                    if isinstance(item, dict) and 'timestamp' in item:
                        try:
                            timestamp = item['timestamp']
                            if isinstance(timestamp, str):
                                parsed_time = timezone.datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                                if parsed_time > timezone.now():
                                    validation_results['timestamp_issues'].append(f"Workspace item {i} has future timestamp: {timestamp}")
                                    validation_results['is_consistent'] = False
                        except (ValueError, TypeError) as e:
                            validation_results['timestamp_issues'].append(f"Workspace item {i} has invalid timestamp: {timestamp} - {str(e)}")
                            validation_results['is_consistent'] = False
                
                if not validation_results['timestamp_issues']:
                    passed_checks += 1
            
            # Check 4: Business Constraint Validation
            if config['check_constraints']:
                logger.debug("BASE_COORDINATOR: Checking business constraints")
                validation_results['checks_performed'].append('constraints')
                total_checks += 1
                
                # Check maximum limits
                workspace_items = self.get_workspace_items(request, organization_id, 'columns')
                selected_datasets = self.get_selected_datasets(request, organization_id, 'datasets')
                
                # Max workspace items constraint
                if len(workspace_items) > 1000:
                    validation_results['constraint_violations'].append(f"Too many workspace items: {len(workspace_items)} > 1000")
                    validation_results['is_consistent'] = False
                
                # Max selected datasets constraint
                if len(selected_datasets) > 100:
                    validation_results['constraint_violations'].append(f"Too many selected datasets: {len(selected_datasets)} > 100")
                    validation_results['is_consistent'] = False
                
                # Check for required fields in workspace items
                for i, item in enumerate(workspace_items):
                    if isinstance(item, dict):
                        required_fields = ['id', 'dataset']
                        for field in required_fields:
                            if field not in item:
                                validation_results['constraint_violations'].append(f"Workspace item {i} missing required field: {field}")
                                validation_results['is_consistent'] = False
                
                if not validation_results['constraint_violations']:
                    passed_checks += 1
            
            # Calculate integrity score
            validation_results['integrity_score'] = (passed_checks / total_checks) if total_checks > 0 else 1.0
            
            # Generate recommendations
            if validation_results['data_type_issues']:
                validation_results['recommendations'].append("Fix data type issues in workspace items and selections")
            
            if validation_results['reference_issues']:
                validation_results['recommendations'].append("Resolve cross-reference inconsistencies between workspace and selections")
            
            if validation_results['timestamp_issues']:
                validation_results['recommendations'].append("Correct invalid timestamps in workspace items")
            
            if validation_results['constraint_violations']:
                validation_results['recommendations'].append("Address business constraint violations")
            
        except Exception as e:
            logger.error(f"BASE_COORDINATOR: Error validating state integrity: {e}", exc_info=True)
            validation_results['is_consistent'] = False
            validation_results['issues'].append(f"State integrity validation error: {str(e)}")
        
        # Log results
        if validation_results['is_consistent']:
            logger.info(f"BASE_COORDINATOR: State integrity validation PASSED for org {organization_id} - Score: {validation_results['integrity_score']:.2f}")
        else:
            logger.warning(f"BASE_COORDINATOR: State integrity validation FAILED for org {organization_id} - Score: {validation_results['integrity_score']:.2f}")
        
        return validation_results
