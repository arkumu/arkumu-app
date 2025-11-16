"""OAI-PMH Public URLs - Harvesting endpoints (IP-restricted by nginx)."""
from django.urls import path
from .views.legacy import oai_endpoint
from .views.router import oai_db_endpoint, oai_tailored_endpoint

app_name = "oai"

urlpatterns = [
    # Public OAI-PMH snapshot endpoint (IP-restricted by nginx for external harvesters)
    path("", oai_endpoint, name="endpoint"),
    # Authenticated DB-backed endpoints used by internal tools/tests
    path("db/", oai_db_endpoint, name="db-endpoint"),
    path("tailored/", oai_tailored_endpoint, name="tailored-endpoint"),
]
