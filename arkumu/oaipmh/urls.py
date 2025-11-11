from django.urls import path
from .views import oai_endpoint, oai_db_endpoint

app_name = "oai"

urlpatterns = [
    path("", oai_endpoint, name="endpoint"),
    path("db/", oai_db_endpoint, name="db-endpoint"),
]
