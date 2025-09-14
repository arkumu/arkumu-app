from django.urls import path
from .views import oai_endpoint

app_name = "oai"

urlpatterns = [
    path("", oai_endpoint, name="endpoint"),
]

