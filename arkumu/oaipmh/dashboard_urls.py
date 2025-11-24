"""OAI-PMH Dashboard URLs - Admin interface bypassing nginx IP restrictions."""
from django.urls import path
from . import dashboard_views, media_link_views, tailored_dashboard_views
from .views import oai_db_endpoint, oai_tailored_endpoint, oai_schema_download

app_name = "oai_admin"

urlpatterns = [
    # OAI endpoints (login-required, bypass nginx)
    path("db/", oai_db_endpoint, name="db-endpoint"),
    path("tailored/", oai_tailored_endpoint, name="tailored-endpoint"),
    path("schemas/<slug:snapshot>/<slug:variant>.<slug:ext>", oai_schema_download, name="schema_download"),

    # Dashboard views
    path("widget/", dashboard_views.oai_widget, name="oai_widget"),
    path("dashboard/snapshot/", dashboard_views.oai_snapshot_dashboard, name="oai_snapshot_dashboard"),
    path("dashboard/db/", dashboard_views.oai_db_dashboard, name="oai_db_dashboard"),
    path("dashboard/tailored/", tailored_dashboard_views.oai_tailored_dashboard, name="oai_tailored_dashboard"),
    path("dashboard/endpoints/", dashboard_views.oai_endpoints_info, name="oai_endpoints_info"),

    # Media links management
    path("media-links/", media_link_views.oai_media_links_dashboard, name="oai_media_links_dashboard"),
    path("media-links/panel/", media_link_views.oai_media_links_panel, name="oai_media_links_panel"),
    path("media-links/digital-view/", media_link_views.oai_media_links_digital_view, name="oai_media_links_digital_view"),
    path("media-links/link/<int:link_id>/update/", media_link_views.oai_media_link_update, name="oai_media_link_update"),
    path("media-links/link/<int:link_id>/delete/", media_link_views.oai_media_link_delete, name="oai_media_link_delete"),
    path("media-links/link/add/", media_link_views.oai_media_link_add, name="oai_media_link_add"),
    path("media-links/seed/preview/", media_link_views.oai_media_link_seed_preview, name="oai_media_link_seed_preview"),
    path("media-links/seed/run/", media_link_views.oai_media_link_seed_execute, name="oai_media_link_seed_execute"),
    path("media-links/clear/", media_link_views.oai_media_link_clear_data, name="oai_media_link_clear_data"),
    path("media-links/seed-sync/", media_link_views.oai_media_link_seed_and_sync, name="oai_media_link_seed_and_sync"),
    path("media-links/sync-status/", media_link_views.oai_media_sync_status, name="oai_media_sync_status"),
    path("media-links/project/<uuid:resource_id>/status/", media_link_views.oai_project_status_update, name="oai_project_status_update"),
    path("media-links/oai-sync/", media_link_views.oai_publication_sync, name="oai_publication_sync"),
]
