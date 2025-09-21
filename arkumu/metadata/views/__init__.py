# Metadata Views Package
# This package contains all view modules for the metadata application

# Dashboard views
from .dashboard_views import metadata_dashboard, all_upload_sessions, all_ingest_sessions

# Resource views  
from .resource_views import resource_list, resource_detail, resource_graph

# Triple views
from .triple_views import triple_search, triple_list

# Graph views
from .graph_views import full_graph_view, graph_data_view


# Data discovery views
from .data_discovery_views import DataDiscoveryView, search_resources, link_file_to_resource, batch_link_files, unlink_file, auto_link_all

# Split table/graph views
from .split_views import split_table_graph_view, get_graph_data

# Direct data views
from .direct_data_views import direct_split_table_graph_view
from .metadata_entry_views import (
    MetadataEntryDashboardView,
    MetadataEntrySectionView,
    MetadataEntrySubmitView,
)

__all__ = [
    # Dashboard
    'metadata_dashboard',
    
    # Resources
    'resource_list', 
    'resource_detail', 
    'resource_graph',
    
    # Triples
    'triple_search', 
    'triple_list',
    
    # Graph visualization
    'full_graph_view', 
    'graph_data_view',
    


    # Data discovery
    'DataDiscoveryView',
    'search_resources',
    'link_file_to_resource',
    'batch_link_files',
    'unlink_file',
    'auto_link_all',
    
    # Split table/graph views
    'split_table_graph_view',
    'get_table_data',
    'get_graph_data', 
    'create_connection',
    
    # Direct data views
    'direct_split_table_graph_view',

    # Metadata entry
    'MetadataEntryDashboardView',
    'MetadataEntrySectionView',
    'MetadataEntrySubmitView',
] 
