from django.db import models
from django.utils.translation import gettext_lazy as _
from django.contrib.postgres.indexes import GinIndex
from arkumu.metadata.models.base import UUIDModel
from arkumu.common.uri_utils import normalize_string_nfc
from arkumu.common.hash_utils import generate_value_hash


class ResourceType(models.TextChoices):
        IRI = 'IRI', _('IRI Identified Resource')
        ENTITY = 'ENTITY', _('Entity')
        CLASS = 'CLASS', _('Class')
        PROPERTY = 'PROPERTY', _('Property')
        LITERAL = 'LITERAL', _('Literal')
        # Potentially BLANK_NODE = 'BLANK', _('Blank Node') if you plan to mint them


class PublicAccessLevel(models.TextChoices):
    PRIVATE = 'private', _('Private - Organization only')
    RESTRICTED = 'restricted', _('Restricted - Authenticated users only')
    PUBLIC = 'public', _('Public - Catalog display allowed')


class ResourceManager(models.Manager):
    """Custom manager for organization-aware resource filtering."""
    
    def for_user(self, user):
        """Return resources accessible by the given user."""
        if not user.is_authenticated:
            # Anonymous users can only see public, approved resources
            return self.filter(
                public_access_level=PublicAccessLevel.PUBLIC,
                is_public_approved=True
            )
        
        # System admins see everything
        if user.role == 'system_admin':
            return self.all()
        
        # Authenticated users see:
        # 1. Their organization's data
        # 2. Public approved resources
        # 3. Restricted resources (if authenticated)
        queryset = self.none()
        
        # Add organization data
        if user.organization:
            queryset = queryset.union(
                self.filter(organization=user.organization)
            )
        
        # Add public resources
        queryset = queryset.union(
            self.filter(
                public_access_level__in=[
                    PublicAccessLevel.PUBLIC,
                    PublicAccessLevel.RESTRICTED
                ],
                is_public_approved=True
            )
        )
        
        return queryset
    
    def for_organization(self, organization):
        """Return resources for a specific organization."""
        return self.filter(organization=organization)


class Resource(UUIDModel):

    uri = models.URLField(
        max_length=512,
        unique=True,  # Unique for non-literals
        null=True,    # Literals don't have URIs
        blank=True,
        help_text="Uniform Resource Identifier for this resource"
    )
    resource_type = models.CharField(
        max_length=10,
        choices=ResourceType.choices,
        default=ResourceType.IRI,
        help_text="Type of the resource (IRI, Class, Property, or Literal)"
    )
    
    # Organization for permissions (links to the User organization model)
    organization = models.ForeignKey(
        'users.Organization',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="Organization this resource belongs to (for permissions)"
    )
    
    # Public access control
    public_access_level = models.CharField(
        max_length=20,
        choices=PublicAccessLevel.choices,
        default=PublicAccessLevel.RESTRICTED,
        help_text="Level of public access for this resource"
    )
    
    # Flag to indicate if this resource has been approved for public display
    is_public_approved = models.BooleanField(
        default=False,
        help_text="Has this resource been approved for public catalog display?"
    )
    
    # Timestamps for public access tracking
    public_approved_at = models.DateTimeField(
        null=True, 
        blank=True,
        help_text="When this resource was approved for public access"
    )
    public_approved_by = models.ForeignKey(
        'users.User',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='public_approved_resources',
        help_text="User who approved this resource for public access"
    )

    # Track public visibility across organizations
    is_public = models.BooleanField(
        default=False,
        help_text="Whether this resource is visible to users from other organizations"
    )
    
    # Track external linkage (for deletion rules)
    is_externally_linked = models.BooleanField(
        default=False,
        help_text="Whether this resource is referenced by users from other organizations"
    )

    # Explicit column tracking fields for better querying
    name = models.TextField(
        max_length=255, 
        null=True, 
        blank=True,
        help_text="Name of the column, property, or context this resource represents"
    )
    
    
    value = models.TextField(
        null=True, 
        blank=True,
        help_text="Value of this resource (literal value or descriptive value for IRIs)"
    )
    
    value_hash = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        db_index=True,
        help_text="SHA-256 hash of the value field for efficient uniqueness checking"
    )
    
    is_placeholder = models.BooleanField(
        default=False,
        help_text="Indicates if this is a placeholder resource created during cross-reference that hasn't been fully imported yet"
    )
    
    # Harmonization field for unified catalog
    canonical_uri = models.URLField(
        max_length=512,
        null=True,
        blank=True,
        db_index=True,
        help_text="Unified catalog URI this resource maps to for cross-archive harmonization"
    )

    datatype = models.CharField(
        max_length=255, blank=True, null=True,
        help_text="Datatype URI for literal values (e.g., xsd:string, xsd:integer)"
    )
    language = models.CharField(
        max_length=10, blank=True, null=True,
        help_text="Language tag for language-tagged string literals (e.g., 'en', 'fr')"
    )

    # Add the custom manager
    objects = ResourceManager()

    class Meta:
        # Ensure consistency between resource_type and required fields
        constraints = [
            models.CheckConstraint(
                check=(
                    (models.Q(resource_type='LITERAL') & models.Q(value__isnull=False)) |
                    (~models.Q(resource_type='LITERAL') & models.Q(uri__isnull=False))
                ),
                name='resource_type_consistency'
            ),
            # Add uniqueness constraint for literal values using hash
            # Note: 'source' removed to allow literal deduplication across archives
            # Hash used to prevent PostgreSQL btree index size limitations
            # Provenance is maintained through the subject URIs in triples
            # Name field excluded as it's just truncated display version
            models.UniqueConstraint(
                fields=['value_hash', 'language', 'datatype'],
                condition=models.Q(resource_type='LITERAL'),
                name='unique_literal_value_hash'
            )
        ]
        
        # Add indexes for common queries
        indexes = [
            models.Index(fields=['name'], name='name_idx'),
            # Removed value_idx - using value_hash index instead to avoid PostgreSQL btree size limits
            models.Index(fields=['uri'], name='uri_pattern_idx', opclasses=['varchar_pattern_ops']),
            models.Index(fields=['organization']),
            # New indexes for public access queries
            models.Index(fields=['public_access_level', 'is_public_approved']),
            # Trigram GIN index for fast text search on literal values
            GinIndex(
                fields=['value'],
                name='resource_value_search_idx',
                condition=models.Q(resource_type='LITERAL'),
                opclasses=['gin_trgm_ops']
            ),
        ]
        
        # Add object-level permissions for django-guardian
        # Note: view_resource, change_resource, delete_resource, add_resource are auto-created by Django
        permissions = [
            ('share_resource', 'Can share resource with others'),
            ('can_approve_public_access', 'Can approve resources for public access'),
            # Note: Public catalog access is automatic for all authenticated users
            # Anonymous users get PUBLIC resources, authenticated users get PUBLIC + RESTRICTED
        ]

    def can_be_deleted_by(self, user):
        """Check if user can delete this resource based on usage rules."""
        from guardian.shortcuts import get_users_with_perms
        
        # System admins can delete anything
        if user.role == 'system_admin':
            return True
        
        # Resource cannot be deleted if externally linked
        if self.is_externally_linked:
            return False
        
        # Check if resource is being used by others
        users_with_perms = get_users_with_perms(self, only_with_perms=['change_resource'])
        if users_with_perms.exclude(pk=user.pk).exists():
            return False
        
        return True
    
    def get_collaboration_users(self):
        """Get users who have been granted collaborative access."""
        from guardian.shortcuts import get_users_with_perms
        return get_users_with_perms(self, only_with_perms=['change_resource'])
    
    def share_with_user(self, user, permission_level='view'):
        """Share this resource with another user."""
        from guardian.shortcuts import assign_perm
        
        perms_to_assign = ['view_resource']
        if permission_level in ['edit', 'change']:
            perms_to_assign.append('change_resource')
        
        for perm in perms_to_assign:
            assign_perm(perm, user, self)
    
    # Alternative field names for compatibility
    @property
    def literal_value(self):
        """Alias for value field."""
        return self.value
    
    @literal_value.setter
    def literal_value(self, value):
        self.value = value
    
    @property
    def literal_datatype(self):
        """Alias for datatype field."""
        return self.datatype
    
    @literal_datatype.setter
    def literal_datatype(self, value):
        self.datatype = value
    
    def save(self, *args, **kwargs):
        """Normalize text and generate hash if needed. Bulk operations handle this manually."""
        # Normalize text fields for consistent storage
        if self.value:
            self.value = normalize_string_nfc(self.value)
            
        if self.name:
            self.name = normalize_string_nfc(self.name)
            
        # Generate hash for literals if not already set (fallback for individual saves)
        if self.resource_type == ResourceType.LITERAL and self.value and not self.value_hash:
            self.value_hash = generate_value_hash(self.value)
            
        super().save(*args, **kwargs)
    
    @property
    def literal_language(self):
        """Alias for language field."""
        return self.language
    
    @literal_language.setter
    def literal_language(self, value):
        self.language = value
    
    def __init__(self, *args, **kwargs):
        # Handle alternative field names
        if 'literal_value' in kwargs:
            kwargs['value'] = kwargs.pop('literal_value')
        if 'literal_datatype' in kwargs:
            kwargs['datatype'] = kwargs.pop('literal_datatype')
        if 'literal_language' in kwargs:
            kwargs['language'] = kwargs.pop('literal_language')
        
        super().__init__(*args, **kwargs)

    def __str__(self):
        if self.resource_type == ResourceType.LITERAL:
            result = f'"{self.value}"'
            if self.datatype:
                result += f"^^{self.datatype}"
            if self.language:
                result += f"@{self.language}"
            return result
        return self.uri or f"_{self.id}" # Fallback for blank node or uninitialized

    @property
    def is_publicly_accessible(self):
        """Check if this resource can be displayed in public catalog."""
        return (
            self.public_access_level == PublicAccessLevel.PUBLIC and 
            self.is_public_approved
        )

    def can_user_view(self, user):
        """
        Check if a user can view this resource.
        Integrates Guardian object-level permissions with role-based and public access logic.
        """
        # Public access - anyone can view
        if self.is_publicly_accessible:
            return True
            
        # If user is not authenticated, only public resources are accessible
        if not user or not user.is_authenticated:
            return False
        
        # Check Guardian object-level permissions first
        if user.has_perm('view_resource', self):
            return True
        
        # Cross-university public viewing (new requirement from specification)
        if (self.public_access_level == PublicAccessLevel.PUBLIC and 
            user.has_role_permission('can_view_cross_university_public')):
            return True
            
        # Restricted access - any authenticated user can view
        if self.public_access_level == PublicAccessLevel.RESTRICTED:
            return True
            
        return False

    def can_user_edit(self, user):
        """
        Check if a user can edit this resource.
        Integrates Guardian permissions with role-based restrictions.
        """
        if not user or not user.is_authenticated:
            return False
        
        # Cannot edit if externally linked (from specification)
        if self.is_externally_linked:
            return False
            
        # Check Guardian object-level permissions
        return user.has_perm('change_resource', self)
    
    def can_user_delete(self, user):
        """
        Check if a user can delete this resource.
        Integrates Guardian permissions with specification restrictions.
        """
        if not user or not user.is_authenticated:
            return False
            
        # Cannot delete if externally linked (from specification)
        if self.is_externally_linked:
            return False
            
        # Check Guardian object-level permissions
        return user.has_perm('delete_resource', self)
    
    def can_user_link_with(self, user, target_resource):
        """Check if user can link this resource with another resource."""
        if not user or not user.is_authenticated:
            return False
            
        # System admins can link anything
        if user.role == 'system_admin':
            return True
            
        # Users can link with public resources from other universities
        if (target_resource.public_access_level == PublicAccessLevel.PUBLIC and
            target_resource.is_publicly_accessible and
            user.has_role_permission('can_link_cross_university')):
            return True
            
        # Users can link within their own organization
        if (self.organization == user.organization and
            target_resource.organization == user.organization):
            return True
            
        return False
