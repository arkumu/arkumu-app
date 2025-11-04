from django.urls import path
from arkumu.metadata.views import dashboard_views, resource_views, triple_views, bulk_editor_views, data_discovery_views, data_explorer_views, direct_data_views, model_graph_views, resource_relationship_views, mapping_visualizer_graphviz, database_structure_visualizer, blueprint_visualizer_graphviz, simplified_resource_views
from arkumu.metadata.views import controlled_vocabulary_views
from arkumu.metadata.views import metadata_entry_views
# Temporarily disabled bulk arkumu mapping views
# from arkumu.metadata.views.bulk_arkumu_mapping_views import (
#     BulkArkumuMappingView,
#     BulkArkumuMappingPreviewView, 
#     BulkArkumuMappingExecutionDetailView,
#     BulkArkumuMappingSortView,
#     BulkArkumuMappingRemoveView,
#     BulkArkumuMappingDeleteView
# )
from arkumu.metadata.views.resource_graph_visualizer import ResourceGraphView, ResourceGraphExpandView
from arkumu.metadata.views.rdf_preview_visualizer import rdf_preview_visualizer, rdf_preview_property_mappings_sorted

# Use optimized views for better performance
from arkumu.metadata.views.data_explorer_optimized import (
    OptimizedDataExplorerView as DataExplorerView,
    OptimizedResourceDetailView as ResourceDetailView,  # Now fixed!
    DataExplorerResultsView,
    SemanticStatsView,
    ResourceTripleCountsView,
    BatchTripleCountsView
)
from arkumu.metadata.views.csv_mapping import saved_mappings_api
from arkumu.metadata.views.csv_mapping.views import mapping_validation_views, mapping_save_views, mapping_load_views, mapping_delete_views
from arkumu.metadata.views.csv_mapping.views import core_editor_views, dataset_views, column_views, utility_views, relationship_views, ontology_views
from arkumu.metadata.views.csv_mapping.views.execution_views import (
    ExecuteGUIMappingView,
    GetMappingExecutionStatusView, 
    ValidateMappingExecutionView
)
from arkumu.metadata.views.csv_mapping.views import mapping_analysis_views
from arkumu.metadata.views import entity_creation_views

app_name = 'metadata'

urlpatterns = [
    # Dashboard
    path('dashboard/', dashboard_views.metadata_dashboard, name='metadata_dashboard'),
    path('dashboard/publish-projects/', dashboard_views.publish_projects_visibility, name='metadata_dashboard_publish_projects'),
    path('dashboard/cache-refresh/', dashboard_views.trigger_cache_refresh, name='metadata_dashboard_cache_refresh'),
    path('dashboard/checksum-refresh/', dashboard_views.trigger_checksum_refresh, name='metadata_dashboard_checksum_refresh'),
    path('dashboard/mark-missing/', dashboard_views.trigger_mark_missing, name='metadata_dashboard_mark_missing'),
    path('dashboard/deduplicate/', dashboard_views.trigger_deduplicate, name='metadata_dashboard_deduplicate'),
    path('dashboard/link-events/', dashboard_views.trigger_link_events, name='metadata_dashboard_link_events'),
    path('dashboard/link-digital-objects/', dashboard_views.trigger_link_digital_objects, name='metadata_dashboard_link_digital_objects'),
    path('dashboard/snapshot-stats/', dashboard_views.project_snapshot_stats, name='metadata_dashboard_snapshot_stats'),
    path('dashboard/all-uploads/', dashboard_views.all_upload_sessions, name='all_upload_sessions'),
    path('dashboard/all-ingests/', dashboard_views.all_ingest_sessions, name='all_ingest_sessions'),
    path('dashboard/ingest-stats/<uuid:session_id>/', dashboard_views.ingest_session_stats, name='ingest_session_stats'),
    path('dashboard/upload-stats/<uuid:session_id>/', dashboard_views.upload_session_stats, name='upload_session_stats'),
    path('dashboard/upload-session/<uuid:session_id>/verify/', dashboard_views.trigger_upload_verification, name='upload_session_verify'),
    path('dashboard/oai/', dashboard_views.oai_proxy, name='oai_proxy'),
    path('dashboard/oai-widget/', dashboard_views.oai_widget, name='metadata_dashboard_oai_widget'),

    # Controlled vocabularies
    path('controlled-vocabularies/', controlled_vocabulary_views.ControlledVocabularyOverviewView.as_view(), name='controlled_vocab_overview'),
    path('controlled-vocabularies/<str:vocab_key>/', controlled_vocabulary_views.ControlledVocabularyEntryListView.as_view(), name='controlled_vocab_list'),
    path('controlled-vocabularies/<str:vocab_key>/new/', controlled_vocabulary_views.ControlledVocabularyEntryManageView.as_view(), name='controlled_vocab_create'),
    path('controlled-vocabularies/<str:vocab_key>/<uuid:resource_id>/edit/', controlled_vocabulary_views.ControlledVocabularyEntryManageView.as_view(), name='controlled_vocab_edit'),

    # Data Explorer (unified resource and triple browsing)
    path('data-explorer/', DataExplorerView.as_view(), name='data_explorer'),
    path('data-explorer/results/', DataExplorerResultsView.as_view(), name='data_explorer_results'),
    path('data-explorer/stats/', SemanticStatsView.as_view(), name='semantic_stats'),  # For async stats loading
    path('data-explorer/triple-counts/<uuid:resource_id>/', ResourceTripleCountsView.as_view(), name='resource_triple_counts'),  # HTMX triple counts
    path('data-explorer/batch-counts/', BatchTripleCountsView.as_view(), name='batch_triple_counts'),  # Batch triple counts
    path('data-explorer/export/json/', data_explorer_views.export_data_as_json, name='export_data_json'),  # JSON export
    
    # Resource details (optimized views)
    path('resources/<uuid:resource_id>/', ResourceDetailView.as_view(pk_url_kwarg='resource_id'), name='resource_detail'),
    path('resources/<uuid:resource_id>/graph-legacy/', resource_views.resource_graph, name='resource_graph_legacy'),
    path('resource-detail/<uuid:pk>/', ResourceDetailView.as_view(), name='resource_detail_modal'),
    
    # Resource Relationship Explorer (HTMX-based)
    path('resources/<uuid:resource_id>/relationships/', resource_relationship_views.ResourceRelationshipExplorerView.as_view(), name='resource_relationships'),
    
    # Resource Graph Visualizer (GraphViz-based)
    path('resources/<uuid:resource_id>/graph/', ResourceGraphView.as_view(), name='resource_graph'),
    path('resources/<uuid:resource_id>/graph/expand/', ResourceGraphExpandView.as_view(), name='resource_graph_expand'),
    path('resources/<uuid:resource_id>/related/', resource_relationship_views.RelatedResourcesHTMXView.as_view(), name='related_resources_htmx'),
    path('resources/<uuid:resource_id>/chain/<uuid:target_id>/', resource_relationship_views.RelationshipChainHTMXView.as_view(), name='relationship_chain_htmx'),
    path('mappings/<uuid:mapping_id>/relationships/', resource_relationship_views.MappingRelationshipsHTMXView.as_view(), name='mapping_relationships_htmx'),
    path('organizations/<str:org_code>/relationship-types/', resource_relationship_views.OrganizationRelationshipTypesHTMXView.as_view(), name='org_relationship_types_htmx'),
    
    # Bulk editor - Core functionality

    path('bulk-editor/list-s3-csv/', bulk_editor_views.list_s3_csv_files, name='list_s3_csv_files'),
    path('bulk-editor/auto-analyze/', bulk_editor_views.auto_analyze_csv, name='auto_analyze_csv'),
    path('bulk-editor/find-matching/', bulk_editor_views.find_matching_resources, name='find_matching_resources'),
    path('bulk-editor/add-mapping/', bulk_editor_views.add_mapping_rule, name='add_mapping_rule'),

    # Bulk editor - Dataset transformation
    path('bulk-editor/list-datasets/', bulk_editor_views.list_datasets, name='list_datasets'),
    path('bulk-editor/preview-transformation/', bulk_editor_views.preview_dataset_transformation, name='preview_transformation'),
    path('bulk-editor/execute-transformation/', bulk_editor_views.execute_dataset_transformation, name='execute_transformation'),
    
    # Bulk editor - Service-powered enhancements
    path('bulk-editor/smart-suggestions/', bulk_editor_views.smart_mapping_suggestions, name='smart_mapping_suggestions'),
    path('bulk-editor/apply-suggestions/', bulk_editor_views.apply_smart_suggestions, name='apply_smart_suggestions'),
    path('bulk-editor/enhanced-preview/', bulk_editor_views.enhanced_dataset_preview, name='enhanced_dataset_preview'),
    path('bulk-editor/service-execution/', bulk_editor_views.service_powered_execution, name='service_powered_execution'),
    path('bulk-editor/enhanced-validation/', bulk_editor_views.enhanced_validation_preview, name='enhanced_validation_preview'),
    path('bulk-editor/cross-dataset-resolution/', bulk_editor_views.cross_dataset_resolution, name='cross_dataset_resolution'),
    
    # Semantic Graph Editor
    path('graph-editor/', bulk_editor_views.semantic_graph_editor, name='semantic_graph_editor'),
    path('graph-editor/table-data/', bulk_editor_views.graph_table_data, name='graph_table_data'),
    
    # Graph Connections Viewer
    path('graph-connections/', bulk_editor_views.graph_connections_view, name='graph_connections'),
    path('htmx/datasets/', bulk_editor_views.get_datasets_htmx, name='get_datasets_htmx'),
    path('htmx/dataset/<uuid:dataset_id>/columns/', bulk_editor_views.get_dataset_columns_htmx, name='get_dataset_columns_htmx'),
    path('htmx/column/<str:column_id>/cells/', bulk_editor_views.get_column_cells_htmx, name='get_column_cells_htmx'),
    path('htmx/cell/<uuid:cell_id>/connections/', bulk_editor_views.get_cell_connections_htmx, name='get_cell_connections_htmx'),
    
    # Data Discovery
    path('data-discovery/', data_discovery_views.DataDiscoveryView.as_view(), name='data_discovery'),
    path('data-discovery/search-resources/', data_discovery_views.search_resources, name='search_resources'),
    path('data-discovery/link-file/', data_discovery_views.link_file_to_resource, name='link_file_to_resource'),
    path('data-discovery/batch-link/', data_discovery_views.batch_link_files, name='batch_link_files'),
    path('data-discovery/batch-unlink/', data_discovery_views.batch_unlink_files, name='batch_unlink_files'),
    path('data-discovery/unlink-file/', data_discovery_views.unlink_file, name='unlink_file'),
    path('data-discovery/auto-link-all/', data_discovery_views.auto_link_all, name='auto_link_all'),
    path('data-discovery/rescan-s3/', data_discovery_views.rescan_s3_files, name='rescan_s3_files'),
    path('data-discovery/toggle-select-all/', data_discovery_views.toggle_select_all, name='toggle_select_all'),
    
    # Direct Data Analysis (File-based, faster)
    path('direct-analysis/', direct_data_views.direct_split_table_graph_view, name='direct_split_table_graph'),
    path('direct-analysis/load-source-data/', direct_data_views.direct_load_source_data, name='direct_load_source_data'),
    path('direct-analysis/load-all-datasets/', direct_data_views.direct_load_all_datasets, name='direct_load_all_datasets'),
    path('direct-analysis/dataset-card/', direct_data_views.direct_get_dataset_card, name='direct_dataset_card'),
    path('direct-analysis/toggle-dataset-card/', direct_data_views.toggle_dataset_card, name='toggle_dataset_card'),
    path('direct-analysis/load-more-rows/', direct_data_views.direct_load_more_dataset_rows, name='direct_load_more_dataset_rows'),
    path('direct-analysis/analyze-relationships/', direct_data_views.direct_analyze_dataset_relationships, name='direct_analyze_dataset_relationships'),
    path('direct-analysis/import-preview/', direct_data_views.direct_get_import_preview, name='direct_import_preview'),
    path('direct-analysis/analyze-column/', direct_data_views.direct_analyze_column, name='direct_analyze_column'),
    
    # Cross-Dataset Relationship Discovery
    path('direct-analysis/relationship-discovery/', direct_data_views.direct_relationship_discovery_view, name='direct_relationship_discovery'),
    path('direct-analysis/dataset-linking/', direct_data_views.direct_dataset_linking_view, name='direct_dataset_linking'),

    # Canonical metadata entry (HTMX)
    path('metadata-entry/', metadata_entry_views.MetadataEntryDashboardView.as_view(), name='metadata_entry'),
    path('metadata-entry/section/', metadata_entry_views.MetadataEntrySectionView.as_view(), name='metadata_entry_section'),
    path('metadata-entry/submit/', metadata_entry_views.MetadataEntrySubmitView.as_view(), name='metadata_entry_submit'),
    path('metadata-entry/latest/', metadata_entry_views.MetadataEntryLatestProjectsView.as_view(), name='metadata_entry_latest'),

    # Manual Relationship Builder
    path('add-column-to-workspace/', direct_data_views.add_column_to_workspace, name='add_column_to_workspace'),
    path('remove-column-from-workspace/', direct_data_views.remove_column_from_workspace, name='remove_column_from_workspace'),
    path('toggle-all-columns/', direct_data_views.toggle_all_columns, name='toggle_all_columns'),
    path('create-mapping/', direct_data_views.create_mapping, name='create_mapping'),
    path('preview-mapping/', direct_data_views.preview_mapping, name='preview_mapping'),
    path('mapping-config/', direct_data_views.mapping_config, name='mapping_config'),
    path('clear-workspace/', direct_data_views.clear_workspace, name='clear_workspace'),
    path('clear-all-datasets/', direct_data_views.clear_all_datasets, name='clear_all_datasets'),
    path('deselect-all-columns/', direct_data_views.deselect_all_columns, name='deselect_all_columns'),
    path('set-anchor-column/', direct_data_views.set_anchor_column, name='set_anchor_column'),
    path('toggle-multi-value-column/', direct_data_views.toggle_multi_value_column, name='toggle_multi_value_column'),
    path('toggle-fk-column/', direct_data_views.toggle_fk_column, name='toggle_fk_column'),
    path('configure-fk/', direct_data_views.configure_fk, name='configure_fk'),
    path('update-fk-targets/', direct_data_views.update_fk_targets, name='update_fk_targets'),
    path('update-fk-columns/', direct_data_views.update_fk_columns, name='update_fk_columns'),
    path('save-fk-config/', direct_data_views.save_fk_config, name='save_fk_config'),
    path('remove-fk-config/', direct_data_views.remove_fk_config, name='remove_fk_config'),
    path('close-fk-modal/', direct_data_views.close_fk_modal, name='close_fk_modal'),
    
    # Inline FK Configuration (replacement for modal approach)
    path('toggle-fk-form/', direct_data_views.toggle_fk_form, name='toggle_fk_form'),
    path('hide-fk-form/', direct_data_views.hide_fk_form, name='hide_fk_form'),
    path('update-fk-target-columns/', direct_data_views.update_fk_target_columns, name='update_fk_target_columns'),
    path('save-inline-fk-config/', direct_data_views.save_inline_fk_config, name='save_inline_fk_config'),
    
    path('export-mappings/', direct_data_views.export_mappings, name='export_mappings'),
    path('filter-workspace/', direct_data_views.filter_workspace, name='filter_workspace'),
    path('expand-dataset/', direct_data_views.expand_dataset, name='expand_dataset'),
    
    # Dataset column selection helpers
    path('select-all-dataset-columns/', direct_data_views.select_all_dataset_columns, name='select_all_dataset_columns'),
    path('deselect-all-dataset-columns/', direct_data_views.deselect_all_dataset_columns, name='deselect_all_dataset_columns'),
    
    # Tooltip helpers for HTMX
    path('tooltip/', direct_data_views.tooltip_view, name='tooltip'),
    
    # ==============================================================================
    # CSV Mapping Editor (Step-by-step extraction from direct_data_views)
    # ==============================================================================
    
    # Main CSV Mapping Editor
    path('csv-mapping-editor/', core_editor_views.csv_mapping_editor_view, name='csv_mapping_editor'),
    path('mapping-graph-data/', core_editor_views.mapping_graph_data_view, name='mapping_graph_data'),
    path('mapping-overview-data/', core_editor_views.mapping_overview_data_view, name='mapping_overview_data'),
    
    # Step 2: Dataset card views (implemented with coordinator)
    path('csv-dataset-card/', dataset_views.CSVDatasetCardView.as_view(), name='csv_dataset_card'),
    path('toggle-csv-dataset/', dataset_views.ToggleDatasetSelectionView.as_view(), name='csv_toggle_dataset_card'),
    path('csv-get-dataset-badges/', dataset_views.GetDatasetBadgesView.as_view(), name='csv_get_dataset_badges'),
    path('csv-load-more-rows/', dataset_views.LoadMoreDatasetRowsView.as_view(), name='csv_load_more_dataset_rows'),
    path('csv-dataset-preview/', dataset_views.LazyDatasetPreviewView.as_view(), name='csv_dataset_preview'),
    
    # Step 3: Column workspace management URLs (implemented with coordinator)
    path('csv-add-column/', column_views.AddColumnToWorkspaceView.as_view(), name='csv_add_column_to_workspace'),
    path('csv-remove-column/', column_views.RemoveColumnFromWorkspaceView.as_view(), name='csv_remove_column_from_workspace'),
    path('csv-select-all-dataset-columns/', column_views.SelectAllDatasetColumnsView.as_view(), name='csv_select_all_dataset_columns'),
    path('csv-deselect-all-dataset-columns/', column_views.DeselectAllDatasetColumnsView.as_view(), name='csv_deselect_all_dataset_columns'),
    
    # Pure Selection Interface URLs (separated from workspace operations)
    path('csv-toggle-column-selection/', column_views.ToggleColumnSelectionView.as_view(), name='csv_toggle_column_selection'),
    path('csv-select-all-columns/', column_views.SelectAllColumnsView.as_view(), name='csv_select_all_columns'),
    path('csv-deselect-all-columns/', column_views.DeselectAllColumnsView.as_view(), name='csv_deselect_all_columns'),
    path('csv-add-selected-to-workspace/', column_views.AddSelectedColumnsToWorkspaceView.as_view(), name='csv_add_selected_columns_to_workspace'),
    
    # Step 4: FK configuration URLs (placeholder for now)
    path('csv-configure-fk/', relationship_views.ConfigureFKRelationshipView.as_view(), name='configure_fk_relationship'),
    
    # Clear operation URLs (separated by responsibility)
    path('csv-clear-selected-datasets/', utility_views.ClearSelectedDatasetsView.as_view(), name='csv_clear_selected_datasets'),
    path('csv-clear-workspace-columns/', utility_views.ClearWorkspaceColumnsView.as_view(), name='csv_clear_workspace_columns'),
    path('csv-clear-all-mapping-state/', utility_views.ClearAllMappingStateView.as_view(), name='csv_clear_all_mapping_state'),
    
    # Legacy clear URL (now delegates to ClearSelectedDatasetsView for backward compatibility)
    path('csv-clear-all-datasets/', utility_views.ClearAllDatasetsView.as_view(), name='csv_clear_all_datasets'),
    
    # Mapping persistence endpoints (JSON API)
    path('csv-save-mapping/', saved_mappings_api.SaveMappingView.as_view(), name='csv_save_mapping'),
    path('csv-update-mapping/', saved_mappings_api.UpdateMappingView.as_view(), name='csv_update_mapping'),
    path('csv-load-mapping/', saved_mappings_api.LoadMappingView.as_view(), name='csv_load_mapping'),
    path('csv-list-mappings/', saved_mappings_api.ListMappingsView.as_view(), name='csv_list_mappings'),
    path('csv-delete-mapping/', saved_mappings_api.DeleteMappingView.as_view(), name='csv_delete_mapping'),
    
    # Mapping persistence endpoints (HTMX UI)
    path('csv-validate-mapping-name/', mapping_validation_views.ValidateMappingNameView.as_view(), name='csv_validate_mapping_name'),
    path('csv-update-button-state/', mapping_validation_views.UpdateButtonStateView.as_view(), name='csv_update_button_state'),
    path('csv-save-mapping-htmx/', mapping_save_views.SaveMappingHTMXView.as_view(), name='csv_save_mapping_htmx'),
    path('csv-load-mapping-htmx/', mapping_load_views.LoadMappingHTMXView.as_view(), name='csv_load_mapping_htmx'),
    path('csv-delete-mapping-htmx/', mapping_delete_views.DeleteMappingHTMXView.as_view(), name='csv_delete_mapping_htmx'),
    
    # Step 4: FK Configuration URLs (now using proper CSV mapping views with coordinator mixins)
    path('csv-toggle-fk-form/', relationship_views.ToggleFKFormView.as_view(), name='csv_toggle_fk_form'),
    path('csv-hide-fk-form/', relationship_views.HideFKFormView.as_view(), name='csv_hide_fk_form'),
    path('csv-update-fk-target-columns/', relationship_views.UpdateFKTargetColumnsView.as_view(), name='csv_update_fk_target_columns'),
    path('csv-save-inline-fk-config/', relationship_views.SaveInlineFKConfigView.as_view(), name='csv_save_inline_fk_config'),
    path('csv-remove-fk-config/', relationship_views.RemoveFKConfigView.as_view(), name='remove_fk_config'),
    
    # Column configuration URLs (anchor and multi-value using coordinator mixins)
    path('csv-set-anchor-column/', column_views.SetAnchorColumnView.as_view(), name='csv_set_anchor_column'),
    path('csv-toggle-multi-value-column/', column_views.ToggleMultiValueColumnView.as_view(), name='csv_toggle_multi_value_column'),
    
    # Step 5: Relationship Context Configuration URLs (junction tables with attributes)
    path('csv-toggle-relationship-context-form/', relationship_views.ToggleRelationshipContextFormView.as_view(), name='csv_toggle_relationship_context_form'),
    path('csv-hide-relationship-context-form/', relationship_views.HideRelationshipContextFormView.as_view(), name='csv_hide_relationship_context_form'),
    path('csv-update-relationship-context-columns/', relationship_views.UpdateRelationshipContextColumnsView.as_view(), name='csv_update_relationship_context_columns'),
    path('csv-save-relationship-context/', relationship_views.SaveInlineRelationshipContextView.as_view(), name='csv_save_relationship_context'),
    path('csv-remove-relationship-context/', relationship_views.RemoveRelationshipContextView.as_view(), name='csv_remove_relationship_context'),
    
    # JSON Export URL (single export button with target="_blank")
    path('csv-mapping/export-json/', utility_views.ExportMappingJSONView.as_view(), name='csv_export_mapping_json'),
    
    # Mapping Visualizer
    path('mappings/<uuid:mapping_id>/mapping-visualizer/', mapping_visualizer_graphviz.mapping_visualizer_graphviz, name='mapping_visualizer_graphviz'),
    
    # Blueprint/Schema Visualizer
    path('mappings/<uuid:mapping_id>/blueprint-visualizer/', blueprint_visualizer_graphviz.blueprint_visualizer_graphviz, name='blueprint_visualizer_graphviz'),
    
    # RDF Preview Visualizer
    path('mappings/<uuid:mapping_id>/rdf-preview/', rdf_preview_visualizer, name='rdf_preview_visualizer'),
    path('mappings/<uuid:mapping_id>/rdf-preview/property-mappings-sorted/', rdf_preview_property_mappings_sorted, name='rdf_preview_property_mappings_sorted'),
    
    # Database Structure Visualizer
    path('ingest/<uuid:session_id>/structure/', database_structure_visualizer.database_structure_visualizer, name='database_structure_visualizer'),
    
    # External Ontology Views
    path('csv-toggle-external-ontology-form/', ontology_views.ToggleExternalOntologyFormView.as_view(), name='csv_toggle_external_ontology_form'),
    path('csv-hide-external-ontology-form/', ontology_views.HideExternalOntologyFormView.as_view(), name='csv_hide_external_ontology_form'),
    path('csv-save-external-ontology/', ontology_views.SaveInlineExternalOntologyView.as_view(), name='csv_save_external_ontology'),
    path('csv-remove-external-ontology/', ontology_views.RemoveExternalOntologyView.as_view(), name='csv_remove_external_ontology'),
    path('csv-remove-individual-external-ontology/', ontology_views.RemoveIndividualExternalOntologyView.as_view(), name='csv_remove_individual_external_ontology'),
    path('csv-validate-external-ontology-identifier/', ontology_views.ValidateExternalOntologyIdentifierView.as_view(), name='csv_validate_external_ontology_identifier'),
    
    # CSV Mapping Execution URLs
    path('csv-mapping/execute/', ExecuteGUIMappingView.as_view(), name='execute_gui_mapping'),
    path('csv-mapping/execution-status/', GetMappingExecutionStatusView.as_view(), name='mapping_execution_status'),
    path('csv-mapping/validate-execution/', ValidateMappingExecutionView.as_view(), name='validate_mapping_execution'),
    
    # Mapping Analysis URLs
    path('csv-mapping/analysis/<str:organization_id>/', mapping_analysis_views.mapping_analysis_dashboard, name='mapping_analysis_dashboard'),
    path('csv-mapping/analysis/<str:organization_id>/<uuid:mapping_id>/api/', mapping_analysis_views.mapping_analysis_api, name='mapping_analysis_api'),
    
    
    # Model Graph Visualization URLs
    path('model-graph/', model_graph_views.model_graph_main, name='model_graph'),
    path('model-graph/mapping-details/', model_graph_views.model_graph_mapping_details, name='model_graph_mapping_details'),
    path('model-graph/field/<str:field_type>/', model_graph_views.model_graph_field_details, name='model_graph_field_details'),
    path('model-graph/workflow/<str:workflow_type>/', model_graph_views.model_graph_workflow_details, name='model_graph_workflow_details'),
    path('model-graph/relation/<str:relation_type>/', model_graph_views.model_graph_relation_details, name='model_graph_relation_details'),
    
    # Simplified Resource Management URLs
    path('resource-management/', simplified_resource_views.ResourceDashboardView.as_view(), name='resource_management'),
    path('resource-management/create/', simplified_resource_views.UnifiedResourceView.as_view(), name='unified_resource_create'),
    path('resource-management/search/', simplified_resource_views.SearchResourcesView.as_view(), name='search_resources_htmx'),
    path('resource-management/link/', simplified_resource_views.QuickLinkResourcesView.as_view(), name='quick_link_resources'),
    path('resource-management/link-form/<uuid:resource_id>/', simplified_resource_views.ResourceLinkFormView.as_view(), name='resource_link_form'),
    path('resource-management/predicates/', simplified_resource_views.GetPredicatesView.as_view(), name='get_predicates_htmx'),
    path('resource-management/triple/<uuid:triple_id>/delete/', simplified_resource_views.DeleteTripleView.as_view(), name='delete_triple'),
    path('ontology-linking-modal/', simplified_resource_views.OntologyLinkingModalView.as_view(), name='ontology_linking_modal'),
    
    # Harmonization URLs (Temporarily disabled)
    # path('harmonization/', harmonization_views.HarmonizationListView.as_view(), name='harmonization_list'),
    # path('harmonization/start/', harmonization_views.HarmonizationStartView.as_view(), name='harmonization_start'),
    # path('harmonization/executions/<uuid:pk>/', harmonization_views.HarmonizationExecutionDetailView.as_view(), name='harmonization_execution_detail'),
    # path('harmonization/rules/', harmonization_views.HarmonizationRuleListView.as_view(), name='harmonization_rules_list'),
    # path('harmonization/rules/create/', harmonization_views.HarmonizationRuleCreateView.as_view(), name='harmonization_rule_create'),
    # path('harmonization/rules/<uuid:pk>/edit/', harmonization_views.HarmonizationRuleUpdateView.as_view(), name='harmonization_rule_update'),
    # path('harmonization/conflicts/', harmonization_views.HarmonizationConflictListView.as_view(), name='harmonization_conflicts'),
    # path('harmonization/executions/', harmonization_views.HarmonizationListView.as_view(), name='harmonization_executions_list'),
    
    # Bulk Arkumu Mapping URLs (Temporarily disabled)
    # path('bulk-arkumu-mapping/', BulkArkumuMappingView.as_view(), name='bulk_arkumu_mapping'),
    # path('bulk-arkumu-mapping/preview/', BulkArkumuMappingPreviewView.as_view(), name='bulk_arkumu_mapping_preview'),
    # path('bulk-arkumu-mapping/execution/<uuid:pk>/', BulkArkumuMappingExecutionDetailView.as_view(), name='bulk_arkumu_mapping_execution'),
    # path('bulk-arkumu-mapping/sort/', BulkArkumuMappingSortView.as_view(), name='bulk_arkumu_mapping_sort'),
    # path('bulk-arkumu-mapping/remove/', BulkArkumuMappingRemoveView.as_view(), name='bulk_arkumu_mapping_remove'),
    # path('bulk-arkumu-mapping/delete/<uuid:pk>/', BulkArkumuMappingDeleteView.as_view(), name='bulk_arkumu_mapping_delete'),
    

    # Entity creation endpoints
    path('create/project/', entity_creation_views.create_project, name='create_project'),
    path('project/details/', entity_creation_views.get_project_details, name='project_details'),
    path('create/event/', entity_creation_views.create_event, name='create_event'),
    path('create/actor/', entity_creation_views.create_actor, name='create_actor'),
    path('actor/details/', entity_creation_views.get_actor_details, name='actor_details'),
    path('create/role/', entity_creation_views.create_role, name='create_role'),
    path('role/details/', entity_creation_views.get_role_details, name='role_details'),
    path('create/digital-object/', entity_creation_views.create_digital_object, name='create_digital_object'),
    path('create/institution/', entity_creation_views.create_institution, name='create_institution'),
    path('create/project-category/', entity_creation_views.create_project_category, name='create_project_category'),
    path('create/project-type/', entity_creation_views.create_project_type, name='create_project_type'),
    path('create/alternate-title/', entity_creation_views.create_alternate_title, name='create_alternate_title'),
    path('create/description/', entity_creation_views.create_description, name='create_description'),
    path('create/catchphrase/', entity_creation_views.create_catchphrase, name='create_catchphrase'),

    ]
