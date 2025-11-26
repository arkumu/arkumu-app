from rest_framework import serializers

class S3ConfigSerializer(serializers.Serializer):
    aws_access_key_id = serializers.CharField(required=False, allow_null=True)
    aws_secret_access_key = serializers.CharField(required=False, allow_null=True)
    region_name = serializers.CharField(required=False, default='us-east-1')
    bucket_name = serializers.CharField(required=False, default='arkumu-files')
    base_url = serializers.CharField(required=False)

class DirectoryImportSerializer(serializers.Serializer):
    """Serializer for importing CSV files either from a directory path or from an uploaded ZIP file."""
    directory_path = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Path to directory containing CSV files to import (server-side path)"
    )
    zip_file = serializers.FileField(
        required=False,
        allow_null=True,
        help_text="ZIP file containing CSV files to import"
    )
    institution = serializers.CharField(
        required=False,
        default="DEFAULT",
        help_text="Institution code for the import"
    )
    base_uri = serializers.CharField(
        required=False,
        default="http://arkumu.org/data",
        help_text="Base URI for generated resources"
    )
    delimiter = serializers.CharField(
        required=False,
        default=";",
        help_text="CSV column delimiter"
    )
    has_quoted_fields = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Whether CSV fields are quoted"
    )
    file_columns = serializers.DictField(
        required=False,
        allow_null=True,
        help_text="Dictionary mapping dataset names to lists of file column names"
    )
    files_base_directory = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Base directory for resolving file paths (defaults to directory_path)"
    )
    s3_config = S3ConfigSerializer(required=False, allow_null=True)
    
    def validate(self, data):
        """Validate that either directory_path or zip_file is provided."""
        if not data.get('directory_path') and not data.get('zip_file'):
            raise serializers.ValidationError("Either directory_path or zip_file must be provided")
        return data


class TailoredProbeRequestSerializer(serializers.Serializer):
    base_url = serializers.CharField(required=False, allow_blank=True)
    verb = serializers.ChoiceField(
        choices=["ListIdentifiers", "ListRecords"],
        default="ListIdentifiers",
    )
    metadata_prefix = serializers.CharField(default="oai_dc")
    set_spec = serializers.CharField(required=False, allow_blank=True)
    from_date = serializers.CharField(required=False, allow_blank=True)
    until_date = serializers.CharField(required=False, allow_blank=True)
    skip_tailored_resume = serializers.BooleanField(required=False, default=False)
    skip_db = serializers.BooleanField(required=False, default=False)
    skip_snapshot = serializers.BooleanField(required=False, default=False)
    pause_for_dataset_change = serializers.BooleanField(required=False, default=False)
    internal_bypass = serializers.BooleanField(required=False, default=False)
    basic_auth_username = serializers.CharField(required=False, allow_blank=True)
    basic_auth_password = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        username = attrs.get("basic_auth_username")
        password = attrs.get("basic_auth_password")
        if bool(username) ^ bool(password):
            raise serializers.ValidationError("basic_auth_username and basic_auth_password must be provided together")
        return attrs
