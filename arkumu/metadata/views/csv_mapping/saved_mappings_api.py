"""
CSV Mapping Persistence Views

This module contains views for saving, loading, listing, and deleting 
CSV mapping configurations using the Mapping model.

These views are separated from the main CSV mapping editor views to 
keep the codebase organized and maintainable.
"""

import logging
import unicodedata
from django.http import JsonResponse, HttpResponse
from django.views import View
from arkumu.users.mixins import GeneralLoginRequiredMixin
from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.views.csv_mapping.mixins.coordinator import CSVMappingCoordinatorMixin

logger = logging.getLogger(__name__)


def _normalize_dataset_name(value):
    """Normalize dataset identifiers to NFC for consistent matching."""
    if not isinstance(value, str):
        return value
    return unicodedata.normalize("NFC", value)


class SaveMappingView(GeneralLoginRequiredMixin, CSVMappingCoordinatorMixin, View):
    """Save current mapping state to database"""
    
    def validate_mapping_before_save(self, request, organization_id, mapping_config):
        """
        Validate mapping configuration before saving to database.
        
        This ensures the mapping state is consistent and all referenced
        datasets and columns actually exist in the current context.
        
        Args:
            request: Django request object
            organization_id (str): Organization ID
            mapping_config (dict): Serialized mapping configuration
            
        Returns:
            dict: Validation result with is_valid, errors, warnings
        """
        logger.info(f"VALIDATE_MAPPING: Starting pre-save validation for organization {organization_id}")
        
        validation_result = {
            'is_valid': True,
            'errors': [],
            'warnings': []
        }
        
        try:
            # 1. Check that mapping_config has required structure
            required_keys = ['workspace_columns', 'fk_relationships', 'metadata']
            for key in required_keys:
                if key not in mapping_config:
                    validation_result['errors'].append(f"Missing required configuration key: {key}")
                    validation_result['is_valid'] = False
            
            # Check that at least one datasets key exists (backward compatibility)
            if 'selected_datasets' not in mapping_config and 'workspace_datasets' not in mapping_config:
                validation_result['errors'].append("Missing datasets configuration: need either 'selected_datasets' or 'workspace_datasets'")
                validation_result['is_valid'] = False
            
            # 2. Validate datasets exist (support both old and new format)
            selected_datasets_raw = mapping_config.get('workspace_datasets', mapping_config.get('selected_datasets', []))
            selected_datasets = [_normalize_dataset_name(ds) for ds in selected_datasets_raw if ds]
            selected_dataset_set = set(selected_datasets)
            if not selected_datasets:
                validation_result['warnings'].append("No datasets selected - mapping will be empty")
            else:
                try:
                    available_datasets = self.get_csv_datasets_for_organization(organization_id)
                    available_names = {_normalize_dataset_name(ds.get('name')) for ds in available_datasets if ds.get('name')}
                    
                    for dataset_name in selected_datasets_raw:
                        normalized = _normalize_dataset_name(dataset_name)
                        if normalized not in available_names:
                            validation_result['errors'].append(f"Dataset '{dataset_name}' is no longer available")
                            validation_result['is_valid'] = False
                except Exception as e:
                    validation_result['warnings'].append(f"Could not verify dataset availability: {str(e)}")
            
            # 3. Validate workspace columns consistency
            workspace_columns = mapping_config.get('workspace_columns', {})
            if not workspace_columns:
                validation_result['warnings'].append("No columns in workspace - mapping will be empty")
            else:
                # Check that workspace columns reference valid datasets
                for column_id, column_data in workspace_columns.items():
                    try:
                        # Parse column ID: "source::dataset::column_name"
                        parts = column_id.split('::', 2)
                        if len(parts) != 3:
                            validation_result['errors'].append(f"Invalid column ID format: {column_id}")
                            validation_result['is_valid'] = False
                            continue
                        
                        source, dataset_name, column_name = parts
                        normalized_dataset = _normalize_dataset_name(dataset_name)
                        
                        # Check dataset is selected
                        if normalized_dataset not in selected_dataset_set:
                            validation_result['errors'].append(f"Column '{column_id}' references unselected dataset '{dataset_name}'")
                            validation_result['is_valid'] = False
                        
                        # Validate column data structure
                        if not isinstance(column_data, dict):
                            validation_result['errors'].append(f"Invalid column data for '{column_id}' - must be dictionary")
                            validation_result['is_valid'] = False
                            
                    except Exception as e:
                        validation_result['errors'].append(f"Error validating column '{column_id}': {str(e)}")
                        validation_result['is_valid'] = False
            
            # 4. Validate FK relationships
            fk_relationships = mapping_config.get('fk_relationships', {})
            for fk_id, fk_config in fk_relationships.items():
                if not isinstance(fk_config, dict):
                    validation_result['errors'].append(f"Invalid FK relationship config for '{fk_id}'")
                    validation_result['is_valid'] = False
                    continue
                
                # Check required FK fields
                required_fk_fields = ['target_dataset', 'target_column']
                for field in required_fk_fields:
                    if field not in fk_config:
                        validation_result['errors'].append(f"FK relationship '{fk_id}' missing required field: {field}")
                        validation_result['is_valid'] = False
                
                # Check that FK references valid datasets (allow missing references as warnings)
                target_dataset = fk_config.get('target_dataset')
                normalized_target = _normalize_dataset_name(target_dataset) if target_dataset else None
                if normalized_target and normalized_target not in selected_dataset_set:
                    validation_result['warnings'].append(f"FK relationship '{fk_id}' references unselected dataset '{target_dataset}' - relationship will be preserved for future use")
            
            # 4.5. Validate relationship contexts (new feature)
            relationship_contexts = mapping_config.get('relationship_contexts', {})
            for context_id, context_config in relationship_contexts.items():
                if not isinstance(context_config, dict):
                    validation_result['errors'].append(f"Invalid relationship context config for '{context_id}'")
                    validation_result['is_valid'] = False
                    continue
                
                # Check required context fields
                required_context_fields = ['context_type']
                for field in required_context_fields:
                    if field not in context_config:
                        validation_result['errors'].append(f"Relationship context '{context_id}' missing required field: {field}")
                        validation_result['is_valid'] = False
                
                # Check that referenced FK columns exist in workspace
                primary_fk = context_config.get('primary_fk')
                secondary_fk = context_config.get('secondary_fk')
                
                if primary_fk and primary_fk not in workspace_columns:
                    validation_result['warnings'].append(f"Relationship context '{context_id}' references missing primary FK: {primary_fk}")
                
                if secondary_fk and secondary_fk not in workspace_columns:
                    validation_result['warnings'].append(f"Relationship context '{context_id}' references missing secondary FK: {secondary_fk}")
            
            # 5. Validate metadata consistency
            metadata = mapping_config.get('metadata', {})
            reported_datasets = metadata.get('total_datasets', 0)
            reported_columns = metadata.get('total_columns', 0)
            reported_fks = metadata.get('total_fk_relationships', 0)
            reported_contexts = metadata.get('total_relationship_contexts', 0)
            
            actual_datasets = len(selected_dataset_set)
            actual_columns = len(workspace_columns)
            actual_fks = len(fk_relationships)
            actual_contexts = len(relationship_contexts)
            
            if reported_datasets != actual_datasets:
                validation_result['warnings'].append(f"Metadata mismatch: reported {reported_datasets} datasets, found {actual_datasets}")
            
            if reported_columns != actual_columns:
                validation_result['warnings'].append(f"Metadata mismatch: reported {reported_columns} columns, found {actual_columns}")
            
            if reported_fks != actual_fks:
                validation_result['warnings'].append(f"Metadata mismatch: reported {reported_fks} FK relationships, found {actual_fks}")
            
            if reported_contexts != actual_contexts:
                validation_result['warnings'].append(f"Metadata mismatch: reported {reported_contexts} relationship contexts, found {actual_contexts}")
            
        except Exception as e:
            validation_result['errors'].append(f"Validation error: {str(e)}")
            validation_result['is_valid'] = False
        
        logger.info(f"VALIDATE_MAPPING: Validation complete - Valid: {validation_result['is_valid']}, Errors: {len(validation_result['errors'])}, Warnings: {len(validation_result['warnings'])}")
        return validation_result
    
    def post(self, request):
        """Save current mapping configuration to Mapping model"""
        logger.info("SAVE_MAPPING: Starting save operation")
        
        try:
            # Get organization and mapping details from form
            organization_id = request.POST.get('organization')
            mapping_name = request.POST.get('mapping_name', '').strip()
            
            if not organization_id:
                return JsonResponse({'error': 'Organization ID is required'}, status=400)
            
            if not mapping_name:
                return JsonResponse({'error': 'Mapping name is required'}, status=400)
            
            # Check for duplicate names BEFORE proceeding
            if Mapping.objects.filter(name=mapping_name, organization_id=organization_id).exists():
                logger.warning(f"SAVE_MAPPING: Attempted to save duplicate mapping name '{mapping_name}' for organization {organization_id}")
                return JsonResponse({
                    'error': f'Mapping "{mapping_name}" already exists for this organization'
                }, status=400)
            
            # Serialize current state
            mapping_config = self.serialize_current_mapping_state(
                request, organization_id, mapping_name
            )
            
            # Determine source datasets from config
            selected_datasets = mapping_config.get('selected_datasets', [])
            
            # Validate mapping before saving
            validation_result = self.validate_mapping_before_save(request, organization_id, mapping_config)
            
            if not validation_result['is_valid']:
                return JsonResponse({
                    'error': 'Mapping is not valid',
                    'validation_errors': validation_result['errors'],
                    'validation_warnings': validation_result['warnings']
                }, status=400)
            
            # Create new mapping record (no longer using get_or_create to avoid updates)
            mapping = Mapping.objects.create(
                name=mapping_name,
                organization_id=organization_id,
                source_datasets=selected_datasets,
                mapping_config=mapping_config,
                created_by=request.user if request.user.is_authenticated else None,
                validation_status='draft'
            )
            
            logger.info(f"SAVE_MAPPING: Successfully created mapping '{mapping_name}' with ID {mapping.id}")
            
            return JsonResponse({
                'success': True,
                'mapping_id': str(mapping.id),
                'mapping_name': mapping_name,
                'created': True,  # Always true now since we only create
                'updated_at': mapping.updated_at.isoformat(),
                'validation_status': mapping.validation_status,
                'message': f'Mapping "{mapping_name}" created successfully'
            })
            
        except Exception as e:
            logger.error(f"SAVE_MAPPING: Error saving mapping: {str(e)}")
            return JsonResponse({
                'error': f'Failed to save mapping: {str(e)}'
            }, status=500)
    
    def _determine_mapping_type(self, mapping_config):
        """Legacy method - no longer needed with flexible mapping model"""
        # With the simplified model, we don't need type determination
        # The GUI interprets the mapping_config structure directly
        return None


class UpdateMappingView(GeneralLoginRequiredMixin, CSVMappingCoordinatorMixin, View):
    """Update existing mapping with current state"""
    
    def validate_mapping_for_update(self, request, organization_id, mapping_config):
        """
        More flexible validation for mapping updates that allows workspace changes.
        
        Unlike the strict validation used for new mappings, this allows:
        - Adding new datasets to the workspace
        - Adding new columns from existing or new datasets
        - Modifying FK relationships
        
        Only validates that:
        - Required config structure exists
        - Referenced datasets are actually available
        - Column IDs have valid format
        - FK relationships reference valid datasets
        """
        logger.info(f"VALIDATE_UPDATE: Starting flexible validation for organization {organization_id}")
        
        validation_result = {
            'is_valid': True,
            'errors': [],
            'warnings': []
        }
        
        try:
            # 1. Check basic required structure
            required_keys = ['workspace_columns', 'fk_relationships', 'metadata']
            for key in required_keys:
                if key not in mapping_config:
                    validation_result['errors'].append(f"Missing required configuration key: {key}")
                    validation_result['is_valid'] = False
            
            # Check that at least one datasets key exists (backward compatibility)
            if 'selected_datasets' not in mapping_config and 'workspace_datasets' not in mapping_config:
                validation_result['errors'].append("Missing datasets configuration: need either 'selected_datasets' or 'workspace_datasets'")
                validation_result['is_valid'] = False
            
            # 2. Get all datasets referenced in workspace (more flexible approach)
            workspace_columns = mapping_config.get('workspace_columns', {})
            datasets_in_workspace = set()
            
            for column_id in workspace_columns.keys():
                try:
                    parts = column_id.split('::', 2)
                    if len(parts) == 3:
                        source, dataset_name, column_name = parts
                        datasets_in_workspace.add(_normalize_dataset_name(dataset_name))
                    else:
                        validation_result['warnings'].append(f"Column ID has unusual format: {column_id}")
                except Exception:
                    validation_result['warnings'].append(f"Could not parse column ID: {column_id}")
            
            # 3. Update workspace_datasets to match what's actually in workspace (new format)
            if datasets_in_workspace:
                mapping_config['workspace_datasets'] = list(datasets_in_workspace)
                # Keep selected_datasets for backward compatibility if it exists
                if 'selected_datasets' in mapping_config:
                    mapping_config['selected_datasets'] = list(datasets_in_workspace)
                logger.info(f"VALIDATE_UPDATE: Updated workspace_datasets to match workspace: {datasets_in_workspace}")
            
            # 4. Verify all referenced datasets are available
            try:
                available_datasets = self.get_csv_datasets_for_organization(organization_id)
                available_names = {_normalize_dataset_name(ds.get('name')) for ds in available_datasets if ds.get('name')}
                
                missing_datasets = datasets_in_workspace - available_names
                if missing_datasets:
                    validation_result['errors'].extend([
                        f"Dataset '{ds}' is no longer available" for ds in missing_datasets
                    ])
                    validation_result['is_valid'] = False
            except Exception as e:
                validation_result['warnings'].append(f"Could not verify dataset availability: {str(e)}")
            
            # 5. Validate FK relationships (but allow missing references)
            fk_relationships = mapping_config.get('fk_relationships', {})
            for fk_id, fk_config in fk_relationships.items():
                if not isinstance(fk_config, dict):
                    validation_result['warnings'].append(f"Invalid FK relationship config for '{fk_id}' - will be skipped")
                    continue
                
                target_dataset = fk_config.get('target_dataset')
                normalized_target = _normalize_dataset_name(target_dataset) if target_dataset else None
                if normalized_target and normalized_target not in datasets_in_workspace:
                    validation_result['warnings'].append(f"FK relationship '{fk_id}' references dataset '{target_dataset}' not in workspace")
            
            # 6. Update metadata to reflect current state
            metadata = mapping_config.get('metadata', {})
            metadata.update({
                'total_datasets': len(datasets_in_workspace),
                'total_columns': len(workspace_columns),
                'total_fk_relationships': len(fk_relationships),
                'last_validated': 'updated',
            })
            mapping_config['metadata'] = metadata
            logger.info(f"VALIDATE_UPDATE: Updated metadata")
            
        except Exception as e:
            validation_result['errors'].append(f"Validation error: {str(e)}")
            validation_result['is_valid'] = False
        
        logger.info(f"VALIDATE_UPDATE: Validation complete - Valid: {validation_result['is_valid']}, Errors: {len(validation_result['errors'])}, Warnings: {len(validation_result['warnings'])}")
        return validation_result
    
    def post(self, request):
        """Update existing mapping configuration"""
        logger.info("UPDATE_MAPPING: Starting update operation")
        
        try:
            # Get required parameters
            organization_id = request.POST.get('organization')
            mapping_id = request.POST.get('mapping_id')
            mapping_name = request.POST.get('mapping_name', '').strip()
            
            if not organization_id:
                return JsonResponse({'error': 'Organization ID is required'}, status=400)
            
            if not mapping_id:
                return JsonResponse({'error': 'Mapping ID is required'}, status=400)
            
            if not mapping_name:
                return JsonResponse({'error': 'Mapping name is required'}, status=400)
            
            # Get existing mapping
            try:
                mapping = Mapping.objects.get(
                    id=mapping_id,
                    organization_id=organization_id
                )
            except Mapping.DoesNotExist:
                return JsonResponse({
                    'error': f'Mapping with ID {mapping_id} not found for organization {organization_id}'
                }, status=404)
            
            # Check if name change would create duplicate (only if name is changing)
            if mapping.name != mapping_name:
                if Mapping.objects.filter(name=mapping_name, organization_id=organization_id).exists():
                    return JsonResponse({
                        'error': f'Mapping "{mapping_name}" already exists for this organization'
                    }, status=400)
            
            # Serialize current state
            mapping_config = self.serialize_current_mapping_state(
                request, organization_id, mapping_name
            )
            
            # Use more flexible validation for updates that allows workspace changes
            validation_result = self.validate_mapping_for_update(request, organization_id, mapping_config)
            
            if not validation_result['is_valid']:
                return JsonResponse({
                    'error': 'Mapping is not valid',
                    'validation_errors': validation_result['errors'],
                    'validation_warnings': validation_result['warnings']
                }, status=400)
            
            # Update mapping fields
            mapping.name = mapping_name
            mapping.source_datasets = mapping_config.get('workspace_datasets', mapping_config.get('selected_datasets', []))
            mapping.mapping_config = mapping_config
            mapping.validation_status = 'draft'  # Reset to draft on update
            mapping.save()
            
            logger.info(f"UPDATE_MAPPING: Successfully updated mapping '{mapping_name}' with ID {mapping.id}")
            
            return JsonResponse({
                'success': True,
                'mapping_id': str(mapping.id),
                'mapping_name': mapping_name,
                'updated': True,
                'updated_at': mapping.updated_at.isoformat(),
                'validation_status': mapping.validation_status,
                'message': f'Mapping "{mapping_name}" updated successfully'
            })
            
        except Exception as e:
            logger.error(f"UPDATE_MAPPING: Error updating mapping: {str(e)}")
            return JsonResponse({
                'error': f'Failed to update mapping: {str(e)}'
            }, status=500)


class LoadMappingView(GeneralLoginRequiredMixin, CSVMappingCoordinatorMixin, View):
    """Load existing mapping from database"""
    
    def post(self, request):
        """Load and restore mapping configuration from Mapping model"""
        organization_id = request.POST.get('organization')
        mapping_id = request.POST.get('mapping_id')
        
        logger.info(f"🟡 LOAD_MAPPING_API: Starting load operation - org={organization_id}, mapping_id={mapping_id}")
        
        try:
            # Get parameters
            if not organization_id:
                logger.error(f"🔴 LOAD_MAPPING_API: Missing organization_id")
                return JsonResponse({'error': 'Organization ID is required'}, status=400)
                
            if not mapping_id:
                logger.error(f"🔴 LOAD_MAPPING_API: Missing mapping_id")
                return JsonResponse({'error': 'Mapping ID is required'}, status=400)
            
            logger.info(f"🟡 LOAD_MAPPING_API: Querying database for mapping...")
            
            # Get mapping record
            try:
                mapping = Mapping.objects.get(
                    id=mapping_id,
                    organization_id=organization_id
                )
                logger.info(f"🟡 LOAD_MAPPING_API: Found mapping '{mapping.name}' in database")
            except Mapping.DoesNotExist:
                logger.error(f"🔴 LOAD_MAPPING_API: Mapping not found in database")
                return JsonResponse({
                    'error': f'Mapping with ID {mapping_id} not found for organization {organization_id}'
                }, status=404)
            
            logger.info(f"🟡 LOAD_MAPPING_API: Validating mapping using execution engine validator...")
            
            # Use the same validation that the execution engine uses
            from arkumu.importer.services.mapping_validation.validator import MappingValidator
            
            try:
                # Add organization_id to mapping config for validation (it's not stored in the config itself)
                mapping_config_for_validation = mapping.mapping_config.copy()
                mapping_config_for_validation['organization_id'] = organization_id
                
                # Validate mapping completeness (basic structure)
                completeness_result = MappingValidator.validate_mapping_completeness(mapping_config_for_validation)
                
                if not completeness_result['is_complete']:
                    logger.error(f"🔴 LOAD_MAPPING_API: Mapping structure validation failed")
                    return JsonResponse({
                        'error': 'Mapping structure is invalid',
                        'validation_errors': [issue['message'] for issue in completeness_result['issues'] 
                                            if issue.get('severity') in ['ERROR', 'CRITICAL']],
                        'missing_components': completeness_result['missing_components']
                    }, status=400)
                
                # Log any structure warnings but continue
                structure_warnings = [issue['message'] for issue in completeness_result['issues'] 
                                    if issue.get('severity') in ['WARNING', 'INFO']]
                if structure_warnings:
                    logger.warning(f"🟡 LOAD_MAPPING_API: Structure warnings: {structure_warnings}")
                
                logger.info(f"🟡 LOAD_MAPPING_API: Mapping structure validation passed - proceeding with load")
                
            except Exception as e:
                logger.warning(f"🟡 LOAD_MAPPING_API: Structure validation failed, but proceeding with load: {str(e)}")
                # Don't fail the load for validation errors - just warn and continue
            
            logger.info(f"🟡 LOAD_MAPPING_API: Deserializing mapping state...")
            
            # Restore mapping state
            summary = self.deserialize_mapping_state(
                request, organization_id, mapping.mapping_config, 
                mapping_id=str(mapping.id), mapping_name=mapping.name
            )
            
            logger.info(f"🟢 LOAD_MAPPING_API: Successfully loaded mapping '{mapping.name}' with ID {mapping.id}")
            logger.info(f"🟢 LOAD_MAPPING_API: Summary: {summary}")
            
            # Also save mapping in ingest coordinator session for cross-interface compatibility
            try:
                from arkumu.importer.mixins.ingest_coordinator import IngestCoordinatorMixin
                
                # Create a temporary instance of IngestCoordinatorMixin to access its methods
                class TempIngestCoordinator(IngestCoordinatorMixin):
                    pass
                
                ingest_coordinator = TempIngestCoordinator()
                
                # Set the current organization in ingest coordinator if not already set
                current_org = ingest_coordinator.get_current_organization(request)
                if not current_org or current_org.get('code') != organization_id:
                    ingest_coordinator.set_current_organization(request, organization_id)
                
                # Set the selected mapping in ingest coordinator
                ingest_result = ingest_coordinator.set_current_mapping(
                    request, 
                    mapping_id=str(mapping.id), 
                    mapping_name=mapping.name
                )
                
                if ingest_result:
                    logger.info(f"🟢 LOAD_MAPPING_API: Also saved mapping in ingest coordinator session")
                else:
                    logger.warning(f"🟡 LOAD_MAPPING_API: Could not save mapping in ingest coordinator session")
                    
            except Exception as e:
                logger.warning(f"🟡 LOAD_MAPPING_API: Error saving to ingest coordinator session: {e}")
                # Don't fail the entire operation if ingest coordinator update fails
            
            # Return success response that triggers UI refresh
            response_data = {
                'success': True,
                'mapping_id': str(mapping.id),
                'mapping_name': mapping.name,
                'summary': summary,
                'message': f'Mapping "{mapping.name}" loaded successfully'
            }
            
            # Add structure warnings if any
            if 'structure_warnings' in locals() and structure_warnings:
                response_data['warnings'] = structure_warnings
                logger.info(f"🟡 LOAD_MAPPING_API: Added {len(structure_warnings)} structure warnings to response")
            
            logger.info(f"🟢 LOAD_MAPPING_API: Returning success response")
            return JsonResponse(response_data)
            
        except Exception as e:
            logger.error(f"🔴 LOAD_MAPPING_API: Error loading mapping: {str(e)}", exc_info=True)
            return JsonResponse({
                'error': f'Failed to load mapping: {str(e)}'
            }, status=500)


class ListMappingsView(GeneralLoginRequiredMixin, CSVMappingCoordinatorMixin, View):
    """List available mappings for organization"""
    
    def get(self, request):
        """Get list of mappings for organization"""
        logger.info("LIST_MAPPINGS: Starting list operation")
        
        try:
            organization_param = request.GET.get('organization')
            
            if not organization_param:
                return JsonResponse({'error': 'Organization ID is required'}, status=400)
            
            # Handle organization codes vs IDs
            from arkumu.users.models import Organization
            organization = None
            organization_code = None
            
            try:
                # First try as numeric ID  
                organization_id = int(organization_param)
                logger.info(f"LIST_MAPPINGS: Looking up organization by ID: {organization_id}")
                
                # Look up organization by ID to get its code
                organization = Organization.objects.get(id=organization_id)
                organization_code = organization.code
                logger.info(f"LIST_MAPPINGS: Found organization '{organization.name}' (id: {organization_id}, code: {organization_code})")
                
            except ValueError:
                # Handle organization codes like 'fuk', 'rsh', etc.
                organization_code = organization_param
                logger.info(f"LIST_MAPPINGS: Using organization code directly: {organization_code}")
                
                try:
                    organization = Organization.objects.get(code=organization_code)
                    logger.info(f"LIST_MAPPINGS: Found organization '{organization.name}' (code: {organization_code}, id: {organization.id})")
                except Organization.DoesNotExist:
                    logger.warning(f"LIST_MAPPINGS: Organization with code '{organization_code}' not found in database")
                    
            except Organization.DoesNotExist:
                logger.warning(f"LIST_MAPPINGS: Organization with ID '{organization_param}' not found in database")
                organization_code = None
            
            # Try to get mappings using the organization code (how they're stored)
            if organization_code:
                logger.info(f"LIST_MAPPINGS: Searching for mappings with organization_id='{organization_code}'")
                mappings = Mapping.objects.filter(
                    organization_id=organization_code
                ).order_by('-created_at')
                logger.info(f"LIST_MAPPINGS: Found {mappings.count()} mappings for organization code '{organization_code}'")
            else:
                logger.warning(f"LIST_MAPPINGS: No valid organization code found for parameter '{organization_param}'")
                mappings = Mapping.objects.none()
                
            # Return empty state if no organization found or no mappings
            if not organization_code or mappings.count() == 0:
                if request.headers.get('HX-Request'):
                    # Return HTML options for select dropdown with empty state
                    options_html = '<option value="">No mappings available for this organization</option>'
                    return HttpResponse(options_html)
                else:
                    # Return JSON for API calls
                    return JsonResponse({
                        'success': True,
                        'mappings': [],
                        'total_count': 0,
                        'message': f'No mappings found for organization {organization_param}'
                    })
            
            # Serialize mapping list
            mapping_list = []
            for mapping in mappings:
                metadata = mapping.mapping_config.get('metadata', {})
                relationship_contexts = mapping.mapping_config.get('relationship_contexts', {})
                
                # Get actual workspace data from mapping_config instead of computed values
                workspace_datasets = mapping.mapping_config.get('workspace_datasets', mapping.mapping_config.get('selected_datasets', []))
                workspace_columns = mapping.mapping_config.get('workspace_columns', {})
                fk_relationships = mapping.mapping_config.get('fk_relationships', {})
                
                mapping_list.append({
                    'id': str(mapping.id),
                    'name': mapping.name,
                    'description': getattr(mapping, 'description', f'Mapping configuration for {mapping.name}'),
                    'validation_status': mapping.get_validation_status_display(),
                    'created_at': mapping.created_at.isoformat(),
                    'created_by': mapping.created_by.username if mapping.created_by else 'Unknown',
                    'source_datasets': workspace_datasets,  # Use actual workspace datasets
                    'total_datasets': len(workspace_datasets),  # Count actual workspace datasets
                    'total_columns': len(workspace_columns),  # Count actual workspace columns
                    'total_fk_relationships': len(fk_relationships),  # Count actual FK relationships
                    'total_relationship_contexts': len(relationship_contexts),
                    'mapping_version': mapping.mapping_config.get('version', '1.0'),
                    'last_executed': mapping.last_executed.isoformat() if mapping.last_executed else None
                })
            
            logger.info(f"LIST_MAPPINGS: Found {len(mapping_list)} mappings for organization {organization_code}")
            
            # Check if this is an HTMX request for populating select dropdown
            if request.headers.get('HX-Request'):
                # Return HTML options for select dropdown
                options_html = '<option value="">Select a mapping...</option>'
                for mapping in mapping_list:
                    created_date = mapping['created_at'][:10] if mapping['created_at'] else 'Unknown'
                    
                    # Enhanced dataset info with FK and context counts
                    extra_info = []
                    if mapping.get('total_fk_relationships', 0) > 0:
                        extra_info.append(f"{mapping['total_fk_relationships']} FKs")
                    if mapping.get('total_relationship_contexts', 0) > 0:
                        extra_info.append(f"{mapping['total_relationship_contexts']} contexts")
                    
                    datasets_info = f"{mapping['total_datasets']} datasets, {mapping['total_columns']} columns"
                    if extra_info:
                        datasets_info += f", {', '.join(extra_info)}"
                    
                    options_html += f'''<option value="{mapping['id']}" 
                                               data-name="{mapping['name']}"
                                               data-description="{mapping['description']}"
                                               data-datasets="{mapping['total_datasets']}"
                                               data-columns="{mapping['total_columns']}"
                                               data-fks="{mapping.get('total_fk_relationships', 0)}"
                                               data-contexts="{mapping.get('total_relationship_contexts', 0)}"
                                               data-version="{mapping.get('mapping_version', '1.0')}"
                                               data-created="{created_date}">
                        {mapping['name']} ({datasets_info}) - {created_date}
                    </option>'''
                
                return HttpResponse(options_html)
            else:
                # Return JSON for API calls
                return JsonResponse({
                    'success': True,
                    'mappings': mapping_list,
                    'total_count': len(mapping_list)
                })
            
        except Exception as e:
            logger.error(f"LIST_MAPPINGS: Error listing mappings: {str(e)}")
            return JsonResponse({
                'error': f'Failed to list mappings: {str(e)}'
            }, status=500)


class DeleteMappingView(GeneralLoginRequiredMixin, CSVMappingCoordinatorMixin, View):
    """Delete existing mapping"""
    
    def post(self, request):
        """Delete mapping from database"""
        logger.info("DELETE_MAPPING: Starting delete operation")
        
        try:
            organization_id = request.POST.get('organization')
            mapping_id = request.POST.get('mapping_id')
            
            if not organization_id:
                return JsonResponse({'error': 'Organization ID is required'}, status=400)
                
            if not mapping_id:
                return JsonResponse({'error': 'Mapping ID is required'}, status=400)
            
            # Get and delete mapping
            try:
                mapping = Mapping.objects.get(
                    id=mapping_id,
                    organization_id=organization_id
                )
                mapping_name = mapping.name
                mapping.delete()
                
                logger.info(f"DELETE_MAPPING: Successfully deleted mapping '{mapping_name}' with ID {mapping_id}")
                
                return JsonResponse({
                    'success': True,
                    'message': f'Mapping "{mapping_name}" deleted successfully'
                })
                
            except Mapping.DoesNotExist:
                return JsonResponse({
                    'error': f'Mapping with ID {mapping_id} not found'
                }, status=404)
            
        except Exception as e:
            logger.error(f"DELETE_MAPPING: Error deleting mapping: {str(e)}")
            return JsonResponse({
                'error': f'Failed to delete mapping: {str(e)}'
            }, status=500) 
