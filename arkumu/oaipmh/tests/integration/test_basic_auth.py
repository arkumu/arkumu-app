import base64

import pytest
from django.test import override_settings
from django.urls import reverse


def _basic_auth_header(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("utf-8")
    return {"HTTP_AUTHORIZATION": f"Basic {token}"}


@pytest.mark.django_db
@override_settings(OAI_BASIC_AUTH_ALLOWED_USERS=[])
def test_oai_endpoint_allows_requests_without_credentials_configured(client):
    url = reverse("oai:endpoint")
    response = client.get(url, {"verb": "Identify"})

    assert response.status_code == 200


@pytest.mark.django_db
@override_settings(OAI_BASIC_AUTH_ALLOWED_USERS=["hbz-dev"])
def test_oai_endpoint_requires_basic_auth_when_configured(client, django_user_model):
    django_user_model.objects.create_user(username="hbz-dev", password="secret")

    url = reverse("oai:endpoint")
    response = client.get(url, {"verb": "Identify"})

    assert response.status_code == 401
    assert response["WWW-Authenticate"].startswith("Basic")


@pytest.mark.django_db
@override_settings(OAI_BASIC_AUTH_ALLOWED_USERS=["hbz-dev"])
def test_oai_endpoint_accepts_valid_basic_auth_credentials(client, django_user_model):
    django_user_model.objects.create_user(username="hbz-dev", password="secret")

    url = reverse("oai:endpoint")
    headers = _basic_auth_header("hbz-dev", "secret")
    response = client.get(url, {"verb": "Identify"}, **headers)

    assert response.status_code == 200


@pytest.mark.django_db
@override_settings(OAI_BASIC_AUTH_ALLOWED_USERS=["hbz-dev"])
def test_oai_endpoint_rejects_invalid_basic_auth_credentials(client, django_user_model):
    django_user_model.objects.create_user(username="hbz-dev", password="secret")

    url = reverse("oai:endpoint")
    headers = _basic_auth_header("hbz-dev", "wrong")
    response = client.get(url, {"verb": "Identify"}, **headers)

    assert response.status_code == 401


@pytest.mark.django_db
@override_settings(OAI_BASIC_AUTH_ALLOWED_USERS=["hbz-dev"])
def test_oai_endpoint_rejects_user_not_in_allow_list(client, django_user_model):
    django_user_model.objects.create_user(username="other", password="secret")

    url = reverse("oai:endpoint")
    headers = _basic_auth_header("other", "secret")
    response = client.get(url, {"verb": "Identify"}, **headers)

    assert response.status_code == 401
