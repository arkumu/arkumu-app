"""
Harmonization Service

Main service class that orchestrates the harmonization process.
Creates a semantic alignment layer on top of archive-specific data.
"""

import logging
from typing import List, Optional, Dict, Any
from django.db import transaction
from django.utils import timezone
from django.contrib.auth import get_user_model

from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.harmonization import (
    HarmonizationRule,
    HarmonizationExecution,
    HarmonizationConflict
)
from .catalog_uri_generator import CatalogUriGenerator
from .alignment_generator import AlignmentGenerator
from .mapping_rules import RuleMatcher
from .bulk_processor import HarmonizationBulkProcessor, ProcessingStats
from .conflict_resolver import ConflictResolver

User = get_user_model()
logger = logging.getLogger(__name__)


class HarmonizationService:
    """
    Main service for harmonizing metadata across different archives.
    
    This service creates semantic alignments between archive-specific properties
    and catalog-level properties while preserving original data integrity.
    """
    
    def __init__(self):
        """Initialize the harmonization service with all required components."""
        self.catalog_uri_generator = CatalogUriGenerator()
        self.alignment_generator = AlignmentGenerator(self.catalog_uri_generator)
        self.rule_matcher = RuleMatcher()
        self.bulk_processor = HarmonizationBulkProcessor(
            self.rule_matcher,
            self.alignment_generator,
            self.catalog_uri_generator
        )
        self.conflict_resolver = ConflictResolver()
    
    def harmonize_organization(self, 
                             organization,
                             user: User = None,
                             execution_mode: str = 'manual',
                             cleanup_existing: bool = True,
                             resource_types: List[ResourceType] = None) -> HarmonizationExecution:
        """
        Harmonize all resources from an organization.
        
        Args:
            organization: Organization to harmonize
            user: User executing the harmonization
            execution_mode: Mode of execution ('manual', 'scheduled', 'triggered')
            cleanup_existing: Whether to remove existing alignments first
            resource_types: Optional list of resource types to process
            
        Returns:
            HarmonizationExecution instance with results
        """
        logger.info(f"Starting harmonization for organization: {organization.name}")
        
        # Create execution record
        execution = HarmonizationExecution.objects.create(
            created_by=user,
            execution_mode=execution_mode,
            status='running'
        )
        execution.organizations.add(organization)
        
        try:
            with transaction.atomic():
                # Cleanup existing alignments if requested
                if cleanup_existing:
                    removed_count = self.bulk_processor.cleanup_existing_alignments(organization)
                    logger.info(f"Removed {removed_count} existing alignments")
                
                # Process organization resources
                stats = self.bulk_processor.process_organization(
                    organization, 
                    execution,
                    resource_types
                )
                
                # Update execution with final results
                execution.status = 'completed'
                execution.completed_at = timezone.now()
                execution.resources_processed = stats.resources_processed
                execution.triples_created = stats.triples_created
                execution.conflicts_resolved = stats.conflicts_resolved
                execution.errors = stats.errors
                execution.calculate_duration()
                execution.save()
                
                logger.info(f"Harmonization completed for {organization.name}: "
                           f"{stats.resources_processed} resources processed, "
                           f"{stats.triples_created} triples created")
        
        except Exception as e:
            execution.status = 'failed'
            execution.completed_at = timezone.now()
            execution.errors.append({
                'message': f"Harmonization failed: {str(e)}",
                'timestamp': timezone.now().isoformat()
            })
            execution.save()
            
            logger.exception(f"Harmonization failed for {organization.name}")
            raise
        
        return execution
    
    def harmonize_resources(self, 
                          resources: List[Resource],
                          user: User = None,
                          execution_mode: str = 'manual') -> HarmonizationExecution:
        """
        Harmonize a specific list of resources.
        
        Args:
            resources: List of resources to harmonize
            user: User executing the harmonization
            execution_mode: Mode of execution
            
        Returns:
            HarmonizationExecution instance with results
        """
        logger.info(f"Starting harmonization for {len(resources)} resources")
        
        # Create execution record
        execution = HarmonizationExecution.objects.create(
            created_by=user,
            execution_mode=execution_mode,
            status='running'
        )
        
        # Add organizations from resources
        organizations = set(r.source for r in resources if r.source)
        execution.organizations.add(*organizations)
        
        try:
            # Process resources
            stats = self.bulk_processor.process_resources(resources, execution)
            
            # Update execution
            execution.status = 'completed'
            execution.completed_at = timezone.now()
            execution.resources_processed = stats.resources_processed
            execution.triples_created = stats.triples_created
            execution.conflicts_resolved = stats.conflicts_resolved
            execution.errors = stats.errors
            execution.calculate_duration()
            execution.save()
            
            logger.info(f"Resource harmonization completed: "
                       f"{stats.resources_processed} resources processed, "
                       f"{stats.triples_created} triples created")
        
        except Exception as e:
            execution.status = 'failed'
            execution.completed_at = timezone.now()
            execution.errors.append({
                'message': f"Resource harmonization failed: {str(e)}",
                'timestamp': timezone.now().isoformat()
            })
            execution.save()
            
            logger.exception("Resource harmonization failed")
            raise
        
        return execution
    
    def create_harmonization_rule(self,
                                source_organization,
                                source_property_pattern: str,
                                catalog_property_name: str,
                                mapping_type: str = 'exact',
                                priority: int = 0,
                                user: User = None,
                                notes: str = '') -> HarmonizationRule:
        """
        Create a new harmonization rule.
        
        Args:
            source_organization: Source organization for the rule
            source_property_pattern: Pattern to match source properties
            catalog_property_name: Name of the catalog property
            mapping_type: Type of mapping (exact, close, broad, narrow)
            priority: Rule priority (higher wins in conflicts)
            user: User creating the rule
            notes: Optional notes about the rule
            
        Returns:
            Created HarmonizationRule instance
        """
        # Generate catalog property URI
        catalog_property_uri = self.catalog_uri_generator.generate_property_uri(
            catalog_property_name
        )
        
        # Validate pattern
        is_valid, validation_message = self.rule_matcher.validate_rule_pattern(
            source_property_pattern
        )
        
        if not is_valid:
            raise ValueError(f"Invalid pattern: {validation_message}")
        
        # Create rule
        rule = HarmonizationRule.objects.create(
            source_organization=source_organization,
            source_property_pattern=source_property_pattern,
            catalog_property_uri=catalog_property_uri,
            catalog_property_label=catalog_property_name,
            mapping_type=mapping_type,
            priority=priority,
            created_by=user,
            notes=notes + (f"\nPattern validation: {validation_message}" if validation_message else "")
        )
        
        logger.info(f"Created harmonization rule: {rule}")
        return rule
    
    def validate_organization_rules(self, organization) -> Dict[str, Any]:
        """
        Validate all rules for an organization.
        
        Args:
            organization: Organization to validate rules for
            
        Returns:
            Dictionary with validation results
        """
        return self.bulk_processor.validate_rules_for_organization(organization)
    
    def resolve_conflicts(self, 
                        organization = None,
                        execution: HarmonizationExecution = None,
                        strategy: str = 'priority',
                        user: User = None) -> Dict[str, int]:
        """
        Resolve pending conflicts for an organization or execution.
        
        Args:
            organization: Optional organization to resolve conflicts for
            execution: Optional execution to resolve conflicts for
            strategy: Resolution strategy to use
            user: User resolving conflicts (for manual resolution)
            
        Returns:
            Dictionary with resolution statistics
        """
        conflicts = self.conflict_resolver.get_pending_conflicts(organization, execution)
        
        if not conflicts:
            return {'resolved': 0, 'failed': 0, 'skipped': 0}
        
        logger.info(f"Resolving {len(conflicts)} conflicts using {strategy} strategy")
        
        stats = self.conflict_resolver.resolve_conflicts_bulk(conflicts, strategy)
        
        logger.info(f"Conflict resolution completed: {stats}")
        return stats
    
    def get_harmonization_status(self, organization) -> Dict[str, Any]:
        """
        Get harmonization status for an organization.
        
        Args:
            organization: Organization to get status for
            
        Returns:
            Dictionary with harmonization status information
        """
        # Get basic counts
        total_resources = Resource.objects.filter(
            source=organization,
            resource_type__in=[ResourceType.PROPERTY, ResourceType.CLASS]
        ).count()
        
        # Get alignments
        alignments = self.alignment_generator.get_catalog_alignments_for_organization(organization)
        aligned_resources = len(set(alignment.subject.id for alignment in alignments))
        
        # Get active rules
        active_rules = HarmonizationRule.objects.filter(
            source_organization=organization,
            is_active=True
        ).count()
        
        # Get recent executions
        recent_executions = HarmonizationExecution.objects.filter(
            organizations=organization
        ).order_by('-started_at')[:5]
        
        # Get pending conflicts
        pending_conflicts = self.conflict_resolver.get_pending_conflicts(organization)
        
        return {
            'organization': organization.name,
            'total_resources': total_resources,
            'aligned_resources': aligned_resources,
            'alignment_percentage': (aligned_resources / total_resources * 100) if total_resources > 0 else 0,
            'active_rules': active_rules,
            'pending_conflicts': len(pending_conflicts),
            'recent_executions': [
                {
                    'id': str(exec.id),
                    'status': exec.status,
                    'started_at': exec.started_at,
                    'resources_processed': exec.resources_processed,
                    'triples_created': exec.triples_created
                }
                for exec in recent_executions
            ]
        }
    
    def preview_harmonization(self, 
                            organization,
                            resource_types: List[ResourceType] = None,
                            limit: int = 100) -> Dict[str, Any]:
        """
        Preview what would happen during harmonization without making changes.
        
        Args:
            organization: Organization to preview
            resource_types: Optional resource types to include
            limit: Maximum number of resources to preview
            
        Returns:
            Dictionary with preview information
        """
        # Get sample resources
        resources_query = Resource.objects.filter(source=organization)
        
        if resource_types:
            resources_query = resources_query.filter(resource_type__in=resource_types)
        else:
            resources_query = resources_query.filter(
                resource_type__in=[ResourceType.PROPERTY, ResourceType.CLASS]
            )
        
        resources = list(resources_query[:limit])
        
        # Find matching rules without creating alignments
        match_results = self.rule_matcher.find_matching_rules_bulk(resources)
        
        # Analyze results
        total_resources = len(resources)
        resources_with_matches = len([r for r in match_results.values() if r.matching_rules])
        resources_with_conflicts = len([r for r in match_results.values() if r.has_conflicts])
        
        # Generate catalog properties that would be created
        catalog_properties = set()
        for result in match_results.values():
            for rule in result.matching_rules:
                catalog_properties.add(rule.catalog_property_label)
        
        return {
            'total_resources_analyzed': total_resources,
            'resources_with_matches': resources_with_matches,
            'resources_with_conflicts': resources_with_conflicts,
            'estimated_triples': resources_with_matches - resources_with_conflicts,
            'catalog_properties_to_create': len(catalog_properties),
            'conflicts_to_resolve': resources_with_conflicts,
            'sample_matches': [
                {
                    'resource_uri': result.resource.uri,
                    'resource_name': result.resource.name,
                    'matching_rules': len(result.matching_rules),
                    'has_conflict': result.has_conflicts,
                    'catalog_properties': [rule.catalog_property_label for rule in result.matching_rules]
                }
                for result in list(match_results.values())[:10]
                if result.matching_rules
            ]
        }