"""OAI-PMH Public URLs - Harvesting endpoints (IP-restricted by nginx)."""
from django.urls import path
from .views import (
    oai_endpoint,
    oai_db_endpoint,
    oai_tailored_endpoint,
    oai_schema_download,
)

app_name = "oai"

urlpatterns = [
    # Public OAI-PMH harvesting endpoints
    path("", oai_endpoint, name="endpoint"),
    path("db/", oai_db_endpoint, name="db-endpoint"),
    path("tailored/", oai_tailored_endpoint, name="tailored-endpoint"),
    path("schemas/<slug:snapshot>/<slug:variant>.<slug:ext>", oai_schema_download, name="schema_download"),
]
