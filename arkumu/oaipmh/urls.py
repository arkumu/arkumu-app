"""OAI-PMH Public URLs - Harvesting endpoints (IP-restricted by nginx)."""
from django.urls import path
from .views.router import oai_endpoint, oai_tailored_endpoint, oai_tailored_stats
from .views.snapshot import oai_snapshot_handler

app_name = "oai"

urlpatterns = [
    # Public OAI-PMH endpoint (IP-restricted by nginx for external harvesters)
    path("", oai_endpoint, name="endpoint"),
    # Authenticated tailored endpoint (explicit access with login)
    path("tailored/", oai_tailored_endpoint, name="tailored-endpoint"),
    path("tailored/stats/", oai_tailored_stats, name="tailored-stats"),
    # Pre-serialized snapshot endpoint (fast, uses OAISnapshotRecord table)
    path("snapshot/", oai_snapshot_handler, name="snapshot-endpoint"),
]
