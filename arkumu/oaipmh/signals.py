"""
Signal handlers for OAI-PMH security audit logging.

Logs critical model deletions for security audit purposes.
"""
import logging
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import OAIProjectPublication, OAISnapshotRecord

logger = logging.getLogger("arkumu.security")


@receiver(post_delete, sender=OAIProjectPublication)
def log_publication_deletion(sender, instance, **kwargs):
    """Log OAI publication deletion."""
    # Get project URI from the related Resource
    project_uri = getattr(instance.project, "uri", None) if instance.project_id else None
    # Get organization code from the related Resource's organization
    org_code = None
    if instance.project_id and hasattr(instance.project, "organization") and instance.project.organization:
        org_code = instance.project.organization.code
    logger.warning(
        f"PUBLICATION_DELETED: project_uri={project_uri} "
        f"institution={org_code} pk={instance.pk}"
    )


@receiver(post_delete, sender=OAISnapshotRecord)
def log_snapshot_record_deletion(sender, instance, **kwargs):
    """Log OAI snapshot record deletion."""
    org_code = instance.organization.code if instance.organization_id else None
    logger.warning(
        f"SNAPSHOT_RECORD_DELETED: uri={instance.uri} "
        f"institution={org_code} pk={instance.pk}"
    )
