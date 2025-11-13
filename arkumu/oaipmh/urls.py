"""OAI-PMH Public URLs - Harvesting endpoints (IP-restricted by nginx)."""
from django.urls import path
from .views import oai_endpoint

app_name = "oai"

urlpatterns = [
    # Public OAI-PMH snapshot endpoint (IP-restricted by nginx for external harvesters)
    path("", oai_endpoint, name="endpoint"),
]
