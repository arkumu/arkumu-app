from django.urls import path

from . import views
from .views import direct_upload_views, streaming_upload_views, file_operations_views, dashboard_views, upload_status_view, resumable_upload_views, simple_multipart_upload, file_browser_oob_views

app_name = "storage"

urlpatterns = [
    # Main storage dashboard
    path("", dashboard_views.storage_dashboard, name="storage_dashboard"),
    
    # Upload endpoints
    path("upload/", views.upload_form, name="upload_form"),
    path("upload/process/", views.process_upload, name="process_upload"),
    # path('mark-uploads-complete/', views.mark_uploads_complete, name='mark_uploads_complete'), # Removed - incorrect view name
    path("upload/direct/", views.direct_upload, name="direct_upload"),
    path("upload/success/", views.upload_success, name="upload_success"),
    path('upload/complete/', direct_upload_views.upload_complete, name='upload_complete'),
    
    # New streaming upload endpoints
    path("upload/streaming/", streaming_upload_views.streaming_upload_form, name="streaming_upload_form"),
    path("upload/streaming/api/", streaming_upload_views.streaming_upload_api, name="streaming_upload_api"),
    path("upload/streaming/single/", streaming_upload_views.streaming_upload_single, name="streaming_upload_single"),
    path("upload/status/<uuid:session_id>/", upload_status_view.upload_status, name="upload_status"),
    path("upload/dismiss-banner/", upload_status_view.dismiss_upload_banner, name="dismiss_upload_banner"),
    path("file/info/", streaming_upload_views.file_info, name="file_info"),
    
    # Simple multipart upload endpoint
    path("upload/simple/", simple_multipart_upload.simple_multipart_form, name="simple_multipart_form"),
    path("upload/multipart/", simple_multipart_upload.SimpleMultipartUploadViewSet.as_view({'post': 'upload'}), name="simple_multipart_upload"),
    
    # Resumable upload endpoints (keeping for backward compatibility)
    path("upload/resumable/init/", resumable_upload_views.resumable_upload_init, name="resumable_upload_init"),
    path("upload/resumable/chunk/", resumable_upload_views.resumable_upload_chunk, name="resumable_upload_chunk"),
    path("upload/resumable/status/<uuid:upload_id>/", resumable_upload_views.resumable_upload_status, name="resumable_upload_status"),
    path("upload/resumable/resume/<uuid:upload_id>/", resumable_upload_views.resumable_upload_resume, name="resumable_upload_resume"),
    
    # Organization-specific views
    path("organizations/", file_operations_views.organization_dashboard, name="organization_dashboard"),
    # Handle organization selection via parameter (for HTMX) - MUST come before the generic pattern
    path("organizations/browse/", file_operations_views.organization_contents, name="organization_contents_browse"),
    path("organizations/<str:organization>/", file_operations_views.organization_contents, name="organization_contents"),

    
    # Archivist dashboard
    path("dashboard/", dashboard_views.archivist_dashboard, name="archivist_dashboard"),
    path("dashboard/upload-mode/", dashboard_views.upload_mode_toggle, name="upload_mode_toggle"),
    path("dashboard/folder-contents/<str:bucket_type>/<path:folder_path>/", views.load_folder_contents, name="load_folder_contents"),
    path("dismiss-message/", dashboard_views.dismiss_message, name="dismiss_message"),
    
    # File operations
    path("file-content/<str:bucket_type>/<path:file_path>/", file_operations_views.file_content, name="file_content"),
    path("csv-preview/<str:bucket_type>/<path:file_path>/", file_operations_views.csv_preview, name="csv_preview"),
    path("delete/<str:bucket_type>/<str:object_type>/<path:object_path>/", file_operations_views.delete_object, name="delete_object"),
    path("debug/presigned-url/", direct_upload_views.debug_presigned_url, name="debug_presigned_url"),
    path("upload/debug-error/", direct_upload_views.debug_upload_error, name="debug_upload_error"),

    # Add new route for dashboard content partials
    path("dashboard-content/<str:bucket_type>/", views.dashboard_content, name="dashboard_content"),
    
    # Organization bucket viewing with auto-creation
    path("view-organization-bucket/", dashboard_views.view_organization_bucket, name="view_organization_bucket"),
    
    # File browser OOB updates
    path("oob/file-browser-refresh/<str:organization>/", file_browser_oob_views.file_browser_refresh, name="file_browser_refresh"),
    
    # Simple test endpoint for debugging OOB updates
    path("test/oob-refresh/<str:organization>/", file_browser_oob_views.test_oob_refresh, name="test_oob_refresh"),
] 