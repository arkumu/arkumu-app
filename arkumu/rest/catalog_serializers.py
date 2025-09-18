"""
Serializers for catalog REST API endpoints.
"""

from rest_framework import serializers


class KeywordSerializer(serializers.Serializer):
    """Serializer for popular keyword items."""
    id = serializers.CharField(
        help_text="Canonical identifier (resource URI slug)"
    )
    label = serializers.CharField(
        help_text="Human-readable label for the keyword"
    )
    count = serializers.IntegerField(
        help_text="Number of projects using this keyword"
    )


class ActorSerializer(serializers.Serializer):
    """Serializer for actors in project previews."""
    name = serializers.CharField(
        help_text="Name of the actor"
    )
    roles = serializers.ListField(
        child=serializers.CharField(),
        help_text="List of roles for this actor"
    )


class ProjectPreviewSerializer(serializers.Serializer):
    """Serializer for project preview cards."""
    id = serializers.CharField(
        help_text="Project identifier (resource URI slug)"
    )
    year = serializers.IntegerField(
        allow_null=True,
        help_text="Year from event start date"
    )
    university = serializers.CharField(
        help_text="University/institution name"
    )
    title = serializers.CharField(
        help_text="Project title"
    )
    project_type = serializers.CharField(
        allow_null=True,
        help_text="Type of project"
    )
    actors = ActorSerializer(
        many=True,
        help_text="List of actors with their roles"
    )
    categories = serializers.ListField(
        child=serializers.CharField(),
        help_text="List of project categories"
    )
    preview_image_url = serializers.CharField(
        allow_null=True,
        help_text="URL to project preview image"
    )
    detail_url = serializers.CharField(
        help_text="URL to project detail page"
    )


class PopularKeywordsQuerySerializer(serializers.Serializer):
    """Query parameters for popular keywords endpoint."""
    limit = serializers.IntegerField(
        required=False,
        default=100,
        min_value=1,
        max_value=200,
        help_text="Maximum number of keywords to return (default 100, max 200)"
    )


class RandomProjectsQuerySerializer(serializers.Serializer):
    """Query parameters for random projects endpoint."""
    limit = serializers.IntegerField(
        required=False,
        default=10,
        min_value=1,
        max_value=50,
        help_text="Maximum number of projects to return (default 10, max 50)"
    )
    keyword_id = serializers.CharField(
        required=False,
        allow_blank=False,
        help_text="Filter by keyword/category ID"
    )
    category = serializers.CharField(
        required=False,
        allow_blank=False,
        help_text="Filter by category name"
    )
    university = serializers.CharField(
        required=False,
        allow_blank=False,
        help_text="Filter by university"
    )
    year = serializers.IntegerField(
        required=False,
        min_value=1900,
        max_value=2100,
        help_text="Filter by year"
    )