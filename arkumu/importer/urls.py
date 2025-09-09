from django.urls import path
from .views import import_views, ingest_views, progress_views, mock_views, progress, import_analysis_views

app_name = "importer"

urlpatterns = [
    # New ingest data interface
    path("ingest/", ingest_views.ingest_data, name="ingest_data"),
    path("ingest/get-files/", ingest_views.get_organization_files_for_ingest, name="get_organization_files"),
    path("ingest/toggle-file-selection/", ingest_views.toggle_file_selection, name="toggle_file_selection"),
    path("ingest/select-all-files/", ingest_views.select_all_files, name="select_all_files"),
    path("ingest/deselect-all-files/", ingest_views.deselect_all_files, name="deselect_all_files"),
    path("ingest/toggle-folder/", ingest_views.toggle_folder, name="toggle_folder"),
    path("ingest/list-mappings-dropdown/", ingest_views.list_mappings_dropdown, name="list_mappings_dropdown"),
    path("ingest/navbar-controls/", ingest_views.navbar_controls, name="navbar_controls"),
    path("ingest/execution-status/", ingest_views.execution_status, name="execution_status"),
    path("ingest/analyze-mapping/", ingest_views.analyze_mapping, name="analyze_mapping"),
    path("ingest/correlation-analysis/", ingest_views.correlation_analysis, name="correlation_analysis"),
    path("ingest/start-import/", ingest_views.start_import, name="start_import"),
    path("ingest/start-import/<uuid:session_pk>/", ingest_views.start_import_session, name="start_import_session"),
    path("ingest/run-validation/", ingest_views.run_pre_execution_validation, name="run_validation"),
    path("ingest/validation-results/", ingest_views.validation_results_display, name="validation_results"),
    # Mapping import endpoints
    path("mappings/list-importable/", ingest_views.list_importable_mappings, name="list_importable_mappings"),
    path("mappings/import/", ingest_views.import_selected_mappings, name="import_selected_mappings"),
    path("mappings/close-modal/", ingest_views.close_import_modal, name="close_import_modal"),
    # Organization changes now handled in main ingest_data view
    
    # Import Results Analysis URLs  
    path("results-analysis/", import_analysis_views.import_results_dashboard, name="import_results_dashboard"),
    path("results-analysis/<uuid:session_id>/", import_analysis_views.import_results_detail, name="import_results_detail"),
    path("results-analysis/<uuid:session_id>/api/", import_analysis_views.import_results_api, name="import_results_api"),
    
    # CSV ingest endpoint (existing)
    path("ingest-file/", import_views.ingest_file, name="ingest_file"),
    
    # Directory import endpoint
    path("start-directory-import/", import_views.start_directory_import, name="start_directory_import"),
    
    # Task status polling endpoint  
    path("task-status/<str:task_id>/", import_views.task_status_view, name="task_status"),
    
    # Progress polling endpoint for HTMX
    path("progress/<uuid:session_pk>/", progress_views.import_progress_view, name="import_progress"),
    
    # Task monitoring and cancellation
    path("task-monitor/<str:task_id>/", progress.progress_monitor_view, name="task_monitor"),
    path("task-monitor-status/<str:task_id>/", progress.task_status_api, name="task_status_api"),
    path("task-cancel/<str:task_id>/", progress.cancel_task_api, name="cancel_task_api"),
    
    # Mock testing endpoints for development
    path("mock/test-interface/", mock_views.mock_test_interface, name="mock_test_interface"),
    path("mock/start-import/", mock_views.start_mock_import, name="start_mock_import"),
    path("mock/progress/<uuid:session_pk>/", mock_views.mock_import_progress, name="mock_import_progress"),
    
    # Database management endpoints (development utilities)
    path("reset-database/", import_views.reset_database, name="reset_database"),
    path("clear-upload-sessions/", import_views.clear_upload_sessions, name="clear_upload_sessions"),
    path("clear-ingest-sessions/", import_views.clear_ingest_sessions, name="clear_ingest_sessions"),
] 