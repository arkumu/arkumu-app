from django.urls import path
from .views import (
    oai_endpoint,
    oai_db_endpoint,
    oai_tailored_endpoint,
    oai_schema_download,
)
from . import dashboard_views

app_name = "oai"

urlpatterns = [
    path("", oai_endpoint, name="endpoint"),
    path("db/", oai_db_endpoint, name="db-endpoint"),
    path("tailored/", oai_tailored_endpoint, name="tailored-endpoint"),
    path("schemas/<slug:snapshot>/<slug:variant>.<slug:ext>", oai_schema_download, name="schema_download"),

    # Dashboard and proxy views
    path("proxy/", dashboard_views.oai_proxy, name="oai_proxy"),
    path("proxy/db/", dashboard_views.oai_db_proxy, name="oai_db_proxy"),
    path("widget/", dashboard_views.oai_widget, name="oai_widget"),
    path("dashboard/snapshot/", dashboard_views.oai_snapshot_dashboard, name="oai_snapshot_dashboard"),
    path("dashboard/db/", dashboard_views.oai_db_dashboard, name="oai_db_dashboard"),
    path("dashboard/endpoints/", dashboard_views.oai_endpoints_info, name="oai_endpoints_info"),

    # Media links management
    path("media-links/", dashboard_views.oai_media_links_dashboard, name="oai_media_links_dashboard"),
    path("media-links/panel/", dashboard_views.oai_media_links_panel, name="oai_media_links_panel"),
    path("media-links/link/<int:link_id>/update/", dashboard_views.oai_media_link_update, name="oai_media_link_update"),
    path("media-links/link/<int:link_id>/delete/", dashboard_views.oai_media_link_delete, name="oai_media_link_delete"),
    path("media-links/link/add/", dashboard_views.oai_media_link_add, name="oai_media_link_add"),
    path("media-links/seed/preview/", dashboard_views.oai_media_link_seed_preview, name="oai_media_link_seed_preview"),
    path("media-links/seed/run/", dashboard_views.oai_media_link_seed_execute, name="oai_media_link_seed_execute"),
    path("media-links/project/<uuid:resource_id>/status/", dashboard_views.oai_project_status_update, name="oai_project_status_update"),
]
