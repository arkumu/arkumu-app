"""OAI-PMH Public URLs - Harvesting endpoints (IP-restricted by nginx)."""
from django.urls import path
from .views.router import oai_endpoint, oai_db_endpoint, oai_tailored_endpoint, oai_tailored_stats

app_name = "oai"

urlpatterns = [
    # Public OAI-PMH tailored endpoint (IP-restricted by nginx for external harvesters)
    path("", oai_endpoint, name="endpoint"),
    # Authenticated DB-backed endpoints used by internal tools/tests
    path("db/", oai_db_endpoint, name="db-endpoint"),
    # Authenticated tailored endpoint (explicit access with login)
    path("tailored/", oai_tailored_endpoint, name="tailored-endpoint"),
    path("tailored/stats/", oai_tailored_stats, name="tailored-stats"),
]
