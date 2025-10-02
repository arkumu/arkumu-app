from django.urls import path

from django.views.generic import TemplateView

from django.contrib.auth.decorators import login_required

from .views import (
    file_operations_views,
    dashboard_views,
    upload_status_view,
    file_browser_oob_views,
    upload_views,
)

app_name = "storage"

urlpatterns = [
    # Main storage dashboard
    path("", dashboard_views.storage_dashboard, name="storage_dashboard"),
    
    # Upload endpoints (presigned flows only)
    # Presigned URL Upload endpoints  
    path("upload/presigned/", upload_views.upload_form, name="presigned_upload_form"),
    path("upload/presigned/url/", upload_views.get_presigned_url, name="get_presigned_url"),
    path("upload/presigned/success/", upload_views.upload_success, name="presigned_upload_success"),
    path("upload/presigned/cancel/", upload_views.cancel_upload, name="cancel_presigned_upload"),
    path("upload/presigned/multipart/complete/", upload_views.complete_multipart_upload, name="multipart_complete"),
    path("upload/presigned/multipart/abort/", upload_views.abort_multipart_upload, name="multipart_abort"),
    path("upload/presigned/multipart/init/", upload_views.presigned_multipart_init, name="presigned_multipart_init"),
    path("upload/presigned/multipart/parts/", upload_views.presigned_multipart_part_urls, name="presigned_multipart_part_urls"),
    path("upload/presigned/batch/", upload_views.batch_presigned_urls, name="batch_presigned_urls"),
    
    # Upload session status + dismiss banner
    path("upload/status/<uuid:session_id>/", upload_status_view.upload_status, name="upload_status"),
    path("upload/dismiss-banner/", upload_status_view.dismiss_upload_banner, name="dismiss_upload_banner"),
    
    # Organization-specific views
    path("organizations/", file_operations_views.organization_dashboard, name="organization_dashboard"),
    # Handle organization selection via parameter (for HTMX) - MUST come before the generic pattern
    path("organizations/browse/", file_operations_views.organization_contents, name="organization_contents_browse"),
    path("organizations/<str:organization>/", file_operations_views.organization_contents, name="organization_contents"),

    
    # Archivist dashboard
    path("dashboard/", dashboard_views.archivist_dashboard, name="archivist_dashboard"),
    path("dashboard/upload-mode/", dashboard_views.upload_mode_toggle, name="upload_mode_toggle"),
    path("dashboard/refresh/<str:organization>/", dashboard_views.refresh_file_browser, name="refresh_file_browser"),
    path("dashboard/bucket-size/<str:organization>/", dashboard_views.bucket_size_info, name="bucket_size_info"),
    path("dashboard/export-imports/<str:organization>/", dashboard_views.export_successful_imports_csv, name="export_successful_imports_csv"),
    path("dashboard/folder-contents/<str:bucket_type>/<path:folder_path>/", dashboard_views.load_folder_contents, name="load_folder_contents"),
    path("dismiss-message/", dashboard_views.dismiss_message, name="dismiss_message"),
    
    # File operations
    path("file-content/<str:bucket_type>/<path:file_path>/", file_operations_views.file_content, name="file_content"),
    path("csv-preview/<str:bucket_type>/<path:file_path>/", file_operations_views.csv_preview, name="csv_preview"),
    path("file-viewer/<str:bucket_type>/<path:file_path>/", file_operations_views.file_viewer, name="file_viewer"),
    path("stream/<str:bucket_type>/<path:file_path>/", file_operations_views.stream_file, name="stream_file"),
    path("delete/<str:bucket_type>/<str:object_type>/<path:object_path>/", file_operations_views.delete_object, name="delete_object"),

    # Dashboard content partials
    path("dashboard-content/<str:bucket_type>/", dashboard_views.dashboard_content, name="dashboard_content"),
    
    # Organization bucket viewing with auto-creation
    path("view-organization-bucket/", dashboard_views.view_organization_bucket, name="view_organization_bucket"),
    
    # File browser OOB updates
    path("oob/file-browser-refresh/<str:organization>/", file_browser_oob_views.file_browser_refresh, name="file_browser_refresh"),
    
    # Upload completion OOB refresh
    path("upload/oob-refresh/<str:organization>/", upload_views.upload_complete_oob_refresh, name="upload_complete_oob_refresh"),
    
    # Mark file as uploaded
    path("upload/mark-uploaded/<str:file_id>/", upload_views.mark_file_uploaded, name="mark_file_uploaded"),
    
    # Simple test endpoint for debugging OOB updates
    path("test/oob-refresh/<str:organization>/", file_browser_oob_views.test_oob_refresh, name="test_oob_refresh"),

] 
