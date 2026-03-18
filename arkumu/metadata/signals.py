from django.db.models.signals import post_save
from django.dispatch import receiver
import logging

logger = logging.getLogger(__name__)


@receiver(post_save, sender='metadata.Mapping')
def create_mapping_blueprint(sender, instance, created, **kwargs):
    """
    Create blueprint structure when a mapping is saved.
    
    This ensures all dataset URIs exist for navigation even before data is imported.
    """
    # Only create blueprint for validated or active mappings
    if instance.validation_status not in ['validated', 'active']:
        logger.debug(f"Skipping blueprint creation for mapping '{instance.name}' - status: {instance.validation_status}")
        return
    
    # Only process if mapping has configuration
    if not instance.mapping_config:
        logger.debug(f"Skipping blueprint creation for mapping '{instance.name}' - no mapping config")
        return
    
    try:
        logger.info(f"Creating blueprint structure for mapping '{instance.name}' (organization: {instance.organization_id})")
        
        # Load and translate the mapping to get all datasets
        from arkumu.importer.services.mapping_consumer.mapping_adapter import MappingAdapter
        from arkumu.importer.services.execution.resource_manager import ResourceManager
        from arkumu.importer.services.execution.statistics import ExecutionStatistics
        
        mapping_adapter = MappingAdapter()
        execution_config = mapping_adapter.translate_to_execution_config(instance.id)
        
        # Initialize resource manager
        statistics = ExecutionStatistics()
        # Get the organization object instead of just the code
        from arkumu.users.models import Organization
        organization = Organization.objects.get(code=instance.organization_id.upper())
        
        resource_manager = ResourceManager(
            organization=organization,
            base_uri="http://arkumu.org/data",
            statistics=statistics
        )
        
        # Create dataset URIs for ALL datasets in the mapping
        created_count = 0
        for dataset_config in execution_config.datasets:
            try:
                dataset_resource = resource_manager.create_dataset_resource(dataset_config.dataset_name)
                if dataset_resource:
                    created_count += 1
                    logger.debug(f"Created/verified dataset URI for '{dataset_config.dataset_name}'")
            except Exception as e:
                logger.warning(f"Failed to create dataset URI for '{dataset_config.dataset_name}': {e}")
        
        logger.info(f"Blueprint creation complete for mapping '{instance.name}': {created_count}/{len(execution_config.datasets)} dataset URIs created/verified")
        
    except Exception as e:
        logger.error(f"Failed to create blueprint for mapping '{instance.name}': {e}")
        # Don't raise the exception to avoid disrupting the mapping save operation 