from datetime import datetime, timezone

import pytest
from django.conf import settings
from django.http import HttpResponse
from rest_framework.test import APIClient

from arkumu.oaipmh.tailored_probe import (
    FirstPageResult,
    ReplayProbeResult,
    ResumeProbeResult,
    TailoredProbeOptions,
    TailoredProbeStats,
)


def _sample_stats() -> TailoredProbeStats:
    return TailoredProbeStats(
        base_url="http://testserver",
        verb="ListIdentifiers",
        metadata_prefix="oai_dc",
        collected_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        first_page=FirstPageResult(headers_count=1, resumption_token=None, token_payload=None),
        resume=None,
        db_replay=ReplayProbeResult(rejected=True, error="badResumptionToken: expected"),
        snapshot_replay=None,
    )


@pytest.mark.django_db
def test_tailored_probe_viewset_requires_auth():
    client = APIClient()
    response = client.post("/api/oai-tailored-probe/", {}, format="json")
    assert response.status_code == 403


@pytest.mark.django_db
def test_tailored_probe_viewset_runs_internal_probe(django_user_model, monkeypatch):
    user = django_user_model.objects.create_user(username="apiuser", password="secret")
    client = APIClient()
    client.force_authenticate(user=user)

    stats = _sample_stats()
    captured = {}

    def fake_collect(options: TailoredProbeOptions, http_get=None):
        captured["options"] = options
        captured["http_get"] = http_get
        return stats

    monkeypatch.setattr("arkumu.rest.views.oai_viewsets.collect_probe_stats", fake_collect)

    response = client.post(
        "/api/oai-tailored-probe/",
        {"metadata_prefix": "mets", "skip_db": True},
        format="json",
    )

    assert response.status_code == 200
    assert response.json() == stats.to_dict()

    assert captured["options"].metadata_prefix == "mets"
    assert captured["options"].run_db_check is False
    assert callable(captured["http_get"])


@pytest.mark.django_db
def test_tailored_probe_viewset_uses_remote_base(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="apiuser", password="secret")
    client = APIClient()
    client.force_authenticate(user=user)

    stats = _sample_stats()
    captured = {}

    def fake_collect(options: TailoredProbeOptions, http_get=None):
        captured["options"] = options
        captured["http_get"] = http_get
        return stats

    monkeypatch.setattr("arkumu.rest.views.oai_viewsets.collect_probe_stats", fake_collect)

    response = client.post(
        "/api/oai-tailored-probe/",
        {
            "base_url": "https://remote.example",
            "basic_auth_username": "probe",
            "basic_auth_password": "pass",
            "skip_tailored_resume": True,
        },
        format="json",
    )

    assert response.status_code == 200
    assert captured["options"].base_url == "https://remote.example"
    assert captured["options"].basic_auth == "probe:pass"
    assert captured["options"].run_tailored_resume is False
    assert captured["http_get"] is None


@pytest.mark.django_db
def test_internal_http_get_omits_none_params(monkeypatch, django_user_model):
    from arkumu.rest.views import oai_viewsets

    user = django_user_model.objects.create_user(username="apiuser", password="secret")
    extractor = {}

    def fake_view(request):
        extractor["params"] = request.GET.dict()
        return HttpResponse(
            "<?xml version='1.0' encoding='UTF-8'?><oai:OAI-PMH xmlns:oai='http://www.openarchives.org/OAI/2.0/'><oai:ListIdentifiers /></oai:OAI-PMH>",
            content_type="text/xml",
        )

    monkeypatch.setitem(oai_viewsets._INTERNAL_VIEW_MAP, "/oai/tailored/", (fake_view, True))
    monkeypatch.setattr(settings, "ALLOWED_HOSTS", list(settings.ALLOWED_HOSTS) + ["localhost"])

    http_get = oai_viewsets._build_internal_http_get(user, "localhost:8000")
    http_get("http://localhost:8000/oai/tailored/", {"from": None, "verb": "ListIdentifiers"}, {})

    assert "from" not in extractor["params"]


@pytest.mark.django_db
def test_internal_http_get_sets_host(monkeypatch, django_user_model):
    from arkumu.rest.views import oai_viewsets

    user = django_user_model.objects.create_user(username="apiuser", password="secret")
    captured = {}

    def fake_view(request):
        captured["host"] = request.get_host()
        return HttpResponse(
            "<?xml version='1.0' encoding='UTF-8'?><oai:OAI-PMH xmlns:oai='http://www.openarchives.org/OAI/2.0/'><oai:ListIdentifiers /></oai:OAI-PMH>",
            content_type="text/xml",
        )

    monkeypatch.setitem(oai_viewsets._INTERNAL_VIEW_MAP, "/oai/tailored/", (fake_view, True))
    monkeypatch.setattr(settings, "ALLOWED_HOSTS", list(settings.ALLOWED_HOSTS) + ["localhost"])

    http_get = oai_viewsets._build_internal_http_get(user, "localhost:8000")
    http_get("http://localhost:8000/oai/tailored/", {"verb": "ListIdentifiers"}, {})

    assert captured["host"] == "localhost:8000"
