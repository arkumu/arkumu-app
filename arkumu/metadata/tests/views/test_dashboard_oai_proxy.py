import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_oai_proxy_requires_authentication(client):
    url = reverse("metadata:oai_proxy")
    response = client.get(url, {"verb": "Identify"})

    assert response.status_code == 403


@pytest.mark.django_db
def test_oai_proxy_returns_oai_response_for_logged_in_user(client, django_user_model):
    user = django_user_model.objects.create_user(
        username="staff",
        password="secret",
        role="manager",
    )
    client.force_login(user)

    url = reverse("metadata:oai_proxy")
    response = client.get(url, {"verb": "Identify"})

    assert response.status_code == 200
    assert b"<OAI-PMH" in response.content
