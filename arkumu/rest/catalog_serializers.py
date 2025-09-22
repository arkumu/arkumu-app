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
    organization = serializers.CharField(
        allow_blank=True,
        help_text="Archive or institution name"
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
    organization = serializers.CharField(
        required=False,
        allow_blank=False,
        help_text="Filter by archive code (fuk, hmt, khm, rsh, det) or institution name"
    )
    year = serializers.IntegerField(
        required=False,
        min_value=1900,
        max_value=2100,
        help_text="Filter by year"
    )


class ProjectPreviewSearchQuerySerializer(serializers.Serializer):
    """Query parameters for project preview search endpoint."""

    query = serializers.CharField(
        required=True,
        allow_blank=False,
        help_text="Free-text query to filter projects"
    )
    limit = serializers.IntegerField(
        required=False,
        default=25,
        min_value=1,
        max_value=50,
        help_text="Maximum number of results to return (default 25, max 50)"
    )


class ProjectListQuerySerializer(serializers.Serializer):
    """Query parameters for project snapshot listing endpoint."""

    limit = serializers.IntegerField(
        required=False,
        default=25,
        min_value=1,
        max_value=200,
        help_text="Maximum number of projects to return (default 25, max 200)"
    )
    offset = serializers.IntegerField(
        required=False,
        default=0,
        min_value=0,
        help_text="Number of projects to skip before returning results"
    )
    institution = serializers.CharField(
        required=False,
        allow_blank=False,
        help_text="Filter by institution code or label substring"
    )
    category = serializers.CharField(
        required=False,
        allow_blank=False,
        help_text="Filter by category slug or label substring"
    )
    year = serializers.IntegerField(
        required=False,
        min_value=1400,
        max_value=2100,
        help_text="Filter by derived project year"
    )
    search = serializers.CharField(
        required=False,
        allow_blank=False,
        help_text="Case-insensitive substring search across title, subtitle and description"
    )


class ProjectEventActorSerializer(serializers.Serializer):
    """Serializer for actors attached to a project event."""

    name = serializers.CharField()
    roles = serializers.ListField(
        child=serializers.CharField(),
        help_text="Roles performed by the actor within the event"
    )


class ProjectEventSerializer(serializers.Serializer):
    """Serializer for project event metadata."""

    id = serializers.CharField(allow_null=True)
    uri = serializers.CharField(allow_null=True)
    name = serializers.CharField(allow_null=True)
    description = serializers.CharField(allow_null=True)
    location = serializers.CharField(allow_null=True)
    location_id = serializers.CharField(allow_null=True)
    country = serializers.CharField(allow_null=True)
    type = serializers.CharField(allow_null=True)
    start = serializers.CharField(allow_null=True)
    end = serializers.CharField(allow_null=True)
    latitude = serializers.FloatField(allow_null=True)
    longitude = serializers.FloatField(allow_null=True)
    actors = ProjectEventActorSerializer(many=True)


class ProjectRecordSerializer(serializers.Serializer):
    """Serializer for full project snapshot records."""

    uri = serializers.CharField()
    slug = serializers.CharField()
    title = serializers.CharField(allow_null=True)
    subtitle = serializers.CharField(allow_null=True)
    alternative_title = serializers.CharField(allow_null=True)
    descriptions = serializers.ListField(
        child=serializers.CharField(),
        help_text="Project description paragraphs"
    )
    image = serializers.CharField(allow_null=True)
    institution = serializers.CharField(allow_null=True)
    institution_codes = serializers.ListField(
        child=serializers.CharField(),
        help_text="Institution codes associated with the project"
    )
    project_type = serializers.CharField(allow_null=True)
    year_range = serializers.CharField(allow_null=True)
    categories = serializers.ListField(child=serializers.CharField())
    category_slugs = serializers.ListField(child=serializers.CharField())
    actors = ActorSerializer(many=True)
    catchphrases = serializers.ListField(child=serializers.CharField())
    digital_objects = serializers.ListField(child=serializers.CharField())
    events = ProjectEventSerializer(many=True)
