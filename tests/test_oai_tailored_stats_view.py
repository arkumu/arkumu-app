import base64
from datetime import datetime, timezone

import pytest
from django.urls import reverse

from arkumu.oaipmh.tailored_probe import (
    FirstPageResult,
    ReplayProbeResult,
    ResumeProbeResult,
    TailoredProbeOptions,
    TailoredProbeStats,
    TailoredProbeError,
)


def _sample_stats() -> TailoredProbeStats:
    return TailoredProbeStats(
        base_url="http://testserver",
        verb="ListIdentifiers",
        metadata_prefix="oai_dc",
        collected_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        first_page=FirstPageResult(
            headers_count=2,
            resumption_token="token",
            token_payload={"cursor": 0},
        ),
        resume=ResumeProbeResult(succeeded=True, error=None, has_additional_pages=False),
        db_replay=ReplayProbeResult(rejected=True, error="badResumptionToken: expected"),
        snapshot_replay=None,
    )


@pytest.mark.django_db
def test_tailored_stats_view_returns_payload(client, monkeypatch, settings):
    settings.OAI_BASIC_AUTH_ENABLED = False
    stats = _sample_stats()
    captured: dict[str, TailoredProbeOptions] = {}

    def fake_collect(options: TailoredProbeOptions) -> TailoredProbeStats:
        captured["options"] = options
        return stats

    monkeypatch.setattr("arkumu.oaipmh.views.router.collect_probe_stats", fake_collect)

    url = reverse("oai:tailored-stats")
    auth = base64.b64encode(b"alice:secret").decode("ascii")
    response = client.get(
        url,
        {
            "verb": "ListRecords",
            "metadataPrefix": "mets",
            "set": "fuk",
            "from": "2023-01-01",
            "until": "2023-12-31",
            "skip_tailored_resume": "1",
            "skip_db": "true",
            "skip_snapshot": "true",
            "pause_for_dataset_change": "1",
        },
        HTTP_AUTHORIZATION=f"Basic {auth}",
        HTTP_X_INTERNAL_OAI_BYPASS="1",
    )

    assert response.status_code == 200
    assert response.json() == stats.to_dict()

    options = captured["options"]
    assert options.base_url == "http://testserver"
    assert options.verb == "ListRecords"
    assert options.metadata_prefix == "mets"
    assert options.set_spec == "fuk"
    assert options.from_date == "2023-01-01"
    assert options.until_date == "2023-12-31"
    assert options.run_tailored_resume is False
    assert options.run_db_check is False
    assert options.run_snapshot_check is False
    assert options.pause_for_dataset_change is True
    assert options.basic_auth == "alice:secret"
    assert options.internal_bypass is True


@pytest.mark.django_db
def test_tailored_stats_view_handles_probe_error(client, monkeypatch, settings):
    settings.OAI_BASIC_AUTH_ENABLED = False

    def fake_collect(options: TailoredProbeOptions) -> TailoredProbeStats:
        raise TailoredProbeError("probe failed")

    monkeypatch.setattr("arkumu.oaipmh.views.router.collect_probe_stats", fake_collect)

    response = client.get(reverse("oai:tailored-stats"))
    assert response.status_code == 502
    assert response.json()["error"] == "probe failed"


@pytest.mark.django_db
def test_tailored_stats_view_handles_unexpected_error(client, monkeypatch, settings):
    settings.OAI_BASIC_AUTH_ENABLED = False

    def fake_collect(options: TailoredProbeOptions) -> TailoredProbeStats:  # pragma: no cover - test stub
        raise RuntimeError("boom")

    monkeypatch.setattr("arkumu.oaipmh.views.router.collect_probe_stats", fake_collect)

    response = client.get(reverse("oai:tailored-stats"))
    assert response.status_code == 500
    assert response.json()["error"] == "internal server error"
