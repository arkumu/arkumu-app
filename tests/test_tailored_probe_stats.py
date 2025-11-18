import base64
import json

from arkumu.oaipmh import tailored_probe
from arkumu.oaipmh.tailored_probe import TailoredProbeOptions, collect_probe_stats


def _wrap_oai(body: str) -> bytes:
    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<oai:OAI-PMH xmlns:oai='http://www.openarchives.org/OAI/2.0/'>"
        f"{body}"  # noqa: E231 - intentional adjacency
        "</oai:OAI-PMH>"
    ).encode("utf-8")


def _list_identifiers_xml(headers: int, token: str | None) -> bytes:
    header_xml = "".join(
        f"<oai:header><oai:identifier>id{i}</oai:identifier></oai:header>" for i in range(headers)
    )
    token_xml = f"<oai:resumptionToken>{token}</oai:resumptionToken>" if token else ""
    return _wrap_oai(f"<oai:ListIdentifiers>{header_xml}{token_xml}</oai:ListIdentifiers>")


def _error_xml(code: str, message: str) -> bytes:
    return _wrap_oai(f"<oai:error code='{code}'>{message}</oai:error>")


def _build_token(payload: dict[str, object]) -> str:
    encoded = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    return f"{encoded}:signature"


def test_collect_probe_stats_handles_full_flow(monkeypatch):
    token = _build_token({"cursor": 0, "profile": "demo"})
    responses = [
        _list_identifiers_xml(headers=2, token=token),
        _list_identifiers_xml(headers=1, token=None),
        _error_xml("badResumptionToken", "tailored token rejected"),
        _error_xml("badResumptionToken", "snapshot rejected"),
    ]

    def fake_http_get(url, params, headers):
        assert responses, "unexpected request count"
        return responses.pop(0)

    monkeypatch.setattr(tailored_probe, "_http_get", fake_http_get)

    options = TailoredProbeOptions(base_url="https://example.com")
    stats = collect_probe_stats(options)

    assert stats.first_page.headers_count == 2
    assert stats.first_page.resumption_token == token
    assert stats.first_page.token_payload == {"cursor": 0, "profile": "demo"}
    assert stats.resume and stats.resume.succeeded is True and not stats.resume.has_additional_pages
    assert stats.db_replay and stats.db_replay.rejected is True
    assert stats.snapshot_replay and stats.snapshot_replay.rejected is True
    assert not responses, "all mocked responses should be consumed"


def test_collect_probe_stats_when_no_resumption_token(monkeypatch):
    responses = [_list_identifiers_xml(headers=1, token=None)]

    def fake_http_get(url, params, headers):
        return responses.pop(0)

    monkeypatch.setattr(tailored_probe, "_http_get", fake_http_get)

    options = TailoredProbeOptions(base_url="https://example.org")
    stats = collect_probe_stats(options)

    assert stats.first_page.headers_count == 1
    assert stats.first_page.resumption_token is None
    assert stats.resume is None
    assert stats.db_replay is None
    assert stats.snapshot_replay is None
