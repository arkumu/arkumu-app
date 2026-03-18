from django.db import models
from django.db.models import Q
from django.core.exceptions import ValidationError
from arkumu.metadata.models.base import UUIDModel
from arkumu.metadata.models.resource import Resource, ResourceType


class TripleManager(models.Manager):
    """Custom manager for organization-aware triple filtering."""
    
    def for_user(self, user):
        """Return triples accessible by the given user."""
        if not user.is_authenticated:
            # Anonymous users can only see derived triples
            return self.filter(is_derived=True)
        
        # System admins see everything
        if hasattr(user, 'role') and user.role == 'system_admin':
            return self.all()
        
        # Authenticated users see:
        # 1. Their organization's data
        # 2. Derived triples (system-generated)
        q = Q(is_derived=True)  # Always show derived triples
        
        # Add organization data
        if user.organization:
            q |= Q(source=user.organization)
        
        return self.filter(q)
    
    def for_organization(self, organization):
        """Return triples for a specific organization."""
        return self.filter(source=organization)
    
    def archival_only(self):
        """Return only original archival triples (not derived)."""
        return self.filter(is_derived=False)
    
    def derived_only(self):
        """Return only derived/integrated triples."""
        return self.filter(is_derived=True)
    
    def from_archive(self, archive_code):
        """Return triples from a specific archive."""
        return self.filter(source__code=archive_code)


class Triple(UUIDModel):
    subject = models.ForeignKey(Resource, related_name='subject_triples', on_delete=models.CASCADE)
    predicate = models.ForeignKey(Resource, related_name='predicate_triples', on_delete=models.CASCADE)
    object = models.ForeignKey(Resource, related_name='object_triples', on_delete=models.CASCADE)
    
    # NEW: Source tracking
    source = models.ForeignKey(
        'users.Organization',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Organization that owns this triple. Null for derived triples."
    )
    
    # NEW: Triple type flag
    is_derived = models.BooleanField(
        default=False,
        db_index=True,
        help_text="True if system-generated, not from source archive"
    )
    
    # Add the custom manager
    objects = TripleManager()
    
    class Meta:
        indexes = [
            models.Index(fields=['subject', 'predicate']),
            models.Index(fields=['object']),
            models.Index(fields=['object', 'predicate']),  # For reverse lookup
            models.Index(fields=['predicate']),  # For relationship type filtering
            # Supports dataset membership paging on isPartOf without an extra sort on subject.
            models.Index(fields=['predicate', 'object', 'subject'], name='metadata_tr_pred_obj_subj_idx'),
            models.Index(fields=['source']),  # For filtering by source
            models.Index(fields=['is_derived']),  # For filtering original vs derived
        ]
        constraints = [
            # Allow same triple from different sources
            models.UniqueConstraint(
                fields=['subject', 'predicate', 'object', 'source'],
                name='unique_archival_triple'
            ),
            # Derived triples must be unique
            models.UniqueConstraint(
                fields=['subject', 'predicate', 'object'],
                condition=models.Q(source__isnull=True),
                name='unique_derived_triple'
            )
        ]
    
    def clean(self):
        """Validate the triple based on resource types."""
        # Subject cannot be a literal
        if self.subject.resource_type == ResourceType.LITERAL:
            raise ValidationError("Subject cannot be a literal resource")
        
        # Predicate must be a property
        if self.predicate.resource_type != ResourceType.PROPERTY:
            raise ValidationError("Predicate must be a property resource")
            
    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
        
    def __str__(self):
        return f"{self.subject} —{self.predicate}→ {self.object}"
