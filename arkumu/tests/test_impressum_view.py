import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_impressum_view_renders_content(client):
    response = client.get(reverse("impressum"))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Hochschule für Musik Detmold" in content
    assert "<h1>Impressum</h1>" in content
