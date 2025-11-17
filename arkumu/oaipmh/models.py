"""Database models for OAI-specific features."""

from django.conf import settings
from django.db import models
from django.db.models import F

from arkumu.metadata.models.resource import Resource
from arkumu.users.models import Organization


class OAIProjectMediaLinkQuerySet(models.QuerySet):
    """Custom queryset helpers for curated media links."""

    def ordered(self):
        order_expr = F("order_index").asc(nulls_last=True)
        return self.order_by(order_expr, "created_at", "id")

    def approved(self):
        return self.filter(status=OAIProjectMediaLink.STATUS_APPROVED)

    def for_project(self, project: Resource | str | None):
        if project is None:
            return self.none()
        project_id = getattr(project, "pk", project)
        return self.filter(project_id=project_id)

    def approved_for_project(self, project: Resource | str | None):
        return self.for_project(project).approved().ordered()


class OAIProjectMediaLink(models.Model):
    """Curated link between a project and one of its digital objects."""

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"

    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    )

    SOURCE_PROJECT = "project"
    SOURCE_EVENT = "event"
    SOURCE_MANUAL = "manual"
    SOURCE_UNKNOWN = "unknown"

    SOURCE_CHOICES = (
        (SOURCE_PROJECT, "Project"),
        (SOURCE_EVENT, "Event"),
        (SOURCE_MANUAL, "Manual"),
        (SOURCE_UNKNOWN, "Unknown"),
    )

    project = models.ForeignKey(
        Resource,
        on_delete=models.CASCADE,
        related_name="oai_media_links",
    )
    digital_object = models.ForeignKey(
        Resource,
        on_delete=models.CASCADE,
        related_name="oai_media_references",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    source = models.CharField(
        max_length=20,
        choices=SOURCE_CHOICES,
        default=SOURCE_UNKNOWN,
    )
    order_index = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Explicit ordering applied when emitting METS structMap/fileSec entries.",
    )
    label_override = models.CharField(
        max_length=255,
        blank=True,
        help_text="Curator-provided display label for the digital object.",
    )
    notes = models.TextField(
        blank=True,
        help_text="Free-form curator notes.",
    )
    is_stale = models.BooleanField(
        default=False,
        help_text="Flagged when the canonical graph no longer references this digital object.",
    )
    last_reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="oai_media_links_reviewed",
    )
    last_reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("project", "digital_object"),
                name="uniq_oai_media_link_project_object",
            ),
        ]
        indexes = [
            models.Index(fields=("project",), name="oai_media_project_idx"),
            models.Index(fields=("digital_object",), name="oai_media_object_idx"),
            models.Index(fields=("status",), name="oai_media_status_idx"),
            models.Index(fields=("is_stale",), name="oai_media_stale_idx"),
        ]
        verbose_name = "OAI Project Media Link"
        verbose_name_plural = "OAI Project Media Links"

    objects = OAIProjectMediaLinkQuerySet.as_manager()

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"{self.project_id} → {self.digital_object_id} ({self.status})"

    @property
    def is_approved(self) -> bool:
        return self.status == self.STATUS_APPROVED


class OAIProjectPublicationQuerySet(models.QuerySet):
    """Helpers for project-level OAI publication approvals."""

    def approved(self):
        return self.filter(is_approved=True)


class OAIProjectPublication(models.Model):
    """Per-project OAI publication approval state and audit metadata."""

    project = models.OneToOneField(
        Resource,
        on_delete=models.CASCADE,
        related_name="oai_publication",
        help_text="Project resource this OAI publication state applies to.",
    )
    is_approved = models.BooleanField(
        default=False,
        help_text="Whether this project is approved for OAI harvesting.",
    )
    approved_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When OAI publication was last approved.",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="oai_project_publications",
        help_text="User who last approved OAI publication for this project.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = OAIProjectPublicationQuerySet.as_manager()

    class Meta:
        verbose_name = "OAI Project Publication"
        verbose_name_plural = "OAI Project Publications"
        indexes = [
            models.Index(fields=("project",), name="oai_project_pub_project_idx"),
            models.Index(fields=("is_approved",), name="oai_project_pub_approved_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug helper
        state = "approved" if self.is_approved else "pending"
        return f"{self.project_id} ({state})"


class OAIMediaSyncState(models.Model):
    """Per-organization sync watermarks for tailored/canonical profiles."""

    PROFILE_CANONICAL = "canonical"
    PROFILE_TAILORED = "tailored"

    PROFILE_CHOICES = (
        (PROFILE_CANONICAL, "Canonical"),
        (PROFILE_TAILORED, "Tailored"),
    )

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="oai_media_sync_states",
    )
    profile = models.CharField(max_length=20, choices=PROFILE_CHOICES, default=PROFILE_TAILORED)
    last_seed_at = models.DateTimeField(null=True, blank=True)
    last_publication_sync_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "OAI Media Sync State"
        verbose_name_plural = "OAI Media Sync States"
        unique_together = ("organization", "profile")

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"{self.organization_id}:{self.profile}"
