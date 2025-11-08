from typing import Optional, Union

from django.db import models
from django.conf import settings
from arkumu.metadata.models.base import UUIDModel


class MappingSelectionAudit(UUIDModel):
    """Audit trail for mapping selections (superuser only feature)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='mapping_selection_audits'
    )
    organization_id = models.CharField(max_length=255, db_index=True)
    mapping = models.ForeignKey(
        'Mapping',
        on_delete=models.SET_NULL,
        null=True,
        related_name='selection_audits'
    )
    mapping_name = models.CharField(max_length=255)
    action = models.CharField(
        max_length=20,
        choices=[
            ('set', 'Set Active'),
            ('cleared', 'Cleared')
        ]
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['organization_id', '-timestamp']),
            models.Index(fields=['user', '-timestamp']),
            models.Index(fields=['-timestamp']),
        ]
        verbose_name = 'Mapping Selection Audit'
        verbose_name_plural = 'Mapping Selection Audits'

    def __str__(self):
        username = self.user.username if self.user else 'Unknown'
        return f"{username} {self.action} mapping for {self.organization_id} at {self.timestamp}"


class Mapping(UUIDModel):
    """Flexible mapping configurations for CSV data transformation"""
    
    # Basic mapping info
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, help_text="Optional description of what this mapping does")
    
    # Organization context
    organization_id = models.CharField(max_length=255, db_index=True)
    
    # Source information (for traceability) - TRANSITIONING to computed property
    # This field will be deprecated once migration is complete
    source_datasets = models.JSONField(default=list, help_text="DEPRECATED: List of datasets - now computed from mapping_config")
    
    # Flexible mapping configuration - GUI interprets structure
    mapping_config = models.JSONField(default=dict, help_text="Flexible mapping configuration interpreted by GUI")
    
    # Provenance and validation
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, models.SET_NULL, related_name='created_mappings', null=True, blank=True)
    validation_status = models.CharField(max_length=20, default='draft', 
                                       choices=[('draft', 'Draft'), ('validated', 'Validated'), ('active', 'Active')])
    
    # Execution tracking
    last_executed = models.DateTimeField(null=True, blank=True)
    execution_stats = models.JSONField(default=dict, help_text="Statistics from last execution")

    # Active mapping flag (only one per organization)
    is_active = models.BooleanField(default=False, help_text="Whether this is the active mapping for this organization")

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization_id', 'validation_status']),
            models.Index(fields=['created_by', 'validation_status']),
            models.Index(fields=['organization_id', 'is_active']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['organization_id'],
                condition=models.Q(is_active=True),
                name='unique_active_mapping_per_org'
            )
        ]
    
    def __str__(self):
        return f"{self.name} - {self.organization_id}"
    
    def get_source_datasets(self):
        """Get list of datasets this mapping applies to - computed from mapping_config"""
        return self.mapping_config.get('workspace_datasets', [])

    def get_dataset_count(self):
        """Get number of datasets in this mapping - uses workspace_datasets from mapping_config"""
        return len(self.get_source_datasets())
    
    def get_column_count(self):
        """Get total number of columns in workspace (selected columns only)"""
        workspace_columns = self.mapping_config.get('workspace_columns', {})
        return len(workspace_columns)
    
    def get_relationship_count(self):
        """Get number of FK relationships configured"""
        return len(self.mapping_config.get('fk_relationships', {}))
    
    def is_ready_for_execution(self):
        """Check if mapping has sufficient configuration to execute"""
        return (self.validation_status in ['validated', 'active'] and 
                self.mapping_config and 
                self.source_datasets) 

    # ------------------------------------------------------------------ #
    # Selection helpers
    # ------------------------------------------------------------------ #
    @classmethod
    def get_active_for_organization(
        cls,
        organization: Union[str, "Organization"],
    ) -> Optional["Mapping"]:
        """
        Return the active mapping for an organization, falling back to the
        newest mapping when no active record exists.
        """
        org_code = organization
        if organization is None:
            return None
        if not isinstance(organization, str):
            org_code = getattr(organization, "code", None)
        if not org_code:
            return None

        org_code = str(org_code).lower()
        queryset = cls.objects.filter(organization_id=org_code).order_by("-created_at")
        return queryset.filter(is_active=True).first() or queryset.first()
