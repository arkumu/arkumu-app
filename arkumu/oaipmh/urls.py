from django.urls import path
from .views import oai_endpoint, oai_db_endpoint, oai_tailored_endpoint

app_name = "oai"

urlpatterns = [
    path("", oai_endpoint, name="endpoint"),
    path("db/", oai_db_endpoint, name="db-endpoint"),
    path("tailored/", oai_tailored_endpoint, name="tailored-endpoint"),
]
