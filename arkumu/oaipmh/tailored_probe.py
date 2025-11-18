"""Utilities for probing tailored OAI endpoints and tokens."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
from typing import Callable, Dict, Optional
from urllib import parse, request
from xml.etree import ElementTree as ET

OAI_NS = {"oai": "http://www.openarchives.org/OAI/2.0/"}


@dataclass
class TailoredProbeOptions:
    base_url: str
    verb: str = "ListIdentifiers"
    metadata_prefix: str = "oai_dc"
    set_spec: Optional[str] = None
    from_date: Optional[str] = None
    until_date: Optional[str] = None
    basic_auth: Optional[str] = None
    internal_bypass: bool = False
    pause_for_dataset_change: bool = False
    run_tailored_resume: bool = True
    run_db_check: bool = True
    run_snapshot_check: bool = True


class TailoredProbeError(Exception):
    """Raised when probing the tailored endpoint fails."""


@dataclass
class FirstPageResult:
    headers_count: int
    resumption_token: Optional[str]
    token_payload: Optional[Dict[str, object]]

    def to_dict(self) -> Dict[str, object]:
        return {
            "headers": self.headers_count,
            "resumption_token": self.resumption_token,
            "decoded_payload": self.token_payload,
        }


@dataclass
class ResumeProbeResult:
    succeeded: bool
    error: Optional[str]
    has_additional_pages: Optional[bool]

    def to_dict(self) -> Dict[str, object]:
        return {
            "succeeded": self.succeeded,
            "error": self.error,
            "has_additional_pages": self.has_additional_pages,
        }


@dataclass
class ReplayProbeResult:
    rejected: bool
    error: Optional[str]

    def to_dict(self) -> Dict[str, object]:
        return {
            "rejected": self.rejected,
            "error": self.error,
        }


@dataclass
class TailoredProbeStats:
    base_url: str
    verb: str
    metadata_prefix: str
    collected_at: datetime
    first_page: FirstPageResult
    resume: Optional[ResumeProbeResult] = None
    db_replay: Optional[ReplayProbeResult] = None
    snapshot_replay: Optional[ReplayProbeResult] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "base_url": self.base_url,
            "verb": self.verb,
            "metadata_prefix": self.metadata_prefix,
            "collected_at": self.collected_at.isoformat().replace("+00:00", "Z"),
            "first_page": self.first_page.to_dict(),
            "resume": self.resume.to_dict() if self.resume else None,
            "db_replay": self.db_replay.to_dict() if self.db_replay else None,
            "snapshot_replay": self.snapshot_replay.to_dict() if self.snapshot_replay else None,
        }


HttpFetcher = Callable[[str, Dict[str, Optional[str]], Dict[str, str]], bytes]


def _http_get(url: str, params: Dict[str, Optional[str]], headers: Dict[str, str]) -> bytes:
    query = parse.urlencode({k: v for k, v in params.items() if v is not None})
    full_url = f"{url}?{query}" if query else url
    req = request.Request(full_url, headers=headers)
    with request.urlopen(req) as resp:
        return resp.read()


def _extract_resumption_token(xml_payload: bytes) -> Optional[str]:
    root = ET.fromstring(xml_payload)
    token_elem = root.find(".//oai:resumptionToken", OAI_NS)
    return token_elem.text.strip() if token_elem is not None and token_elem.text else None


def _extract_error(xml_payload: bytes) -> Optional[str]:
    root = ET.fromstring(xml_payload)
    error_elem = root.find(".//oai:error", OAI_NS)
    if error_elem is None:
        return None
    code = error_elem.attrib.get("code", "unknown")
    text = (error_elem.text or "").strip()
    return f"{code}: {text}".strip()


def _decode_token(token: str) -> Dict[str, object]:
    unquoted = parse.unquote(token)
    token_part, _signature = unquoted.rsplit(":", 1)
    payload = base64.b64decode(token_part.encode("ascii"))
    return json.loads(payload.decode("utf-8"))


def _build_endpoints(base_url: str) -> Dict[str, str]:
    base = base_url.rstrip("/")
    return {
        "tailored": f"{base}/oai/tailored/",
        "db": f"{base}/oai/db/",
        "snapshot": f"{base}/oai/",
    }


def _build_headers(options: TailoredProbeOptions) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    if options.basic_auth:
        auth_bytes = options.basic_auth.encode("utf-8")
        headers["Authorization"] = "Basic " + base64.b64encode(auth_bytes).decode("ascii")
    if options.internal_bypass:
        headers["X-INTERNAL-OAI-BYPASS"] = "1"
    return headers


def _perform_request(
    label: str,
    url: str,
    params: Dict[str, Optional[str]],
    headers: Dict[str, str],
    http_get: HttpFetcher,
) -> bytes:
    try:
        return http_get(url, params, headers)
    except Exception as exc:  # pragma: no cover - transport errors
        raise TailoredProbeError(f"Failed request to {label}: {exc}") from exc


def collect_probe_stats(
    options: TailoredProbeOptions,
    http_get: Optional[HttpFetcher] = None,
) -> TailoredProbeStats:
    http_get = http_get or _http_get
    endpoints = _build_endpoints(options.base_url)
    headers = _build_headers(options)
    verb_params = {
        "verb": options.verb,
        "metadataPrefix": options.metadata_prefix,
        "set": options.set_spec,
        "from": options.from_date,
        "until": options.until_date,
    }

    page1 = _perform_request("/oai/tailored/", endpoints["tailored"], verb_params, headers, http_get)
    headers_count = len(ET.fromstring(page1).findall(".//oai:header", OAI_NS))
    token = _extract_resumption_token(page1)
    decoded = None
    if token:
        try:
            decoded = _decode_token(token)
        except Exception as exc:  # pragma: no cover - invalid token payloads
            raise TailoredProbeError(f"Failed to decode resumption token: {exc}") from exc

    stats = TailoredProbeStats(
        base_url=options.base_url,
        verb=options.verb,
        metadata_prefix=options.metadata_prefix,
        collected_at=datetime.now(dt_timezone.utc),
        first_page=FirstPageResult(headers_count=headers_count, resumption_token=token, token_payload=decoded),
    )

    if not token:
        return stats

    if options.run_tailored_resume:
        page2 = _perform_request(
            "tailored resume",
            endpoints["tailored"],
            {"verb": options.verb, "resumptionToken": token},
            headers,
            http_get,
        )
        err = _extract_error(page2)
        next_token = None if err else _extract_resumption_token(page2)
        stats.resume = ResumeProbeResult(succeeded=err is None, error=err, has_additional_pages=bool(next_token))

    if options.run_db_check:
        db_resp = _perform_request(
            "/oai/db/",
            endpoints["db"],
            {"verb": options.verb, "resumptionToken": token},
            headers,
            http_get,
        )
        db_error = _extract_error(db_resp)
        stats.db_replay = ReplayProbeResult(rejected=bool(db_error), error=db_error)

    if options.run_snapshot_check:
        snap_resp = _perform_request(
            "/oai/",
            endpoints["snapshot"],
            {"verb": options.verb, "resumptionToken": token},
            headers,
            http_get,
        )
        snap_error = _extract_error(snap_resp)
        stats.snapshot_replay = ReplayProbeResult(rejected=bool(snap_error), error=snap_error)

    return stats


def run_probe(options: TailoredProbeOptions) -> TailoredProbeStats:
    print("--> Requesting first page from /oai/tailored/ ...")
    http_get = _http_get
    stats = collect_probe_stats(options, http_get=http_get)
    page = stats.first_page
    print(f"{page.headers_count} headers returned; token={'present' if page.resumption_token else 'missing'}")
    if page.token_payload is not None:
        print("Decoded token payload:\n" + json.dumps(page.token_payload, indent=2))

    token = page.resumption_token
    if not token:
        return stats

    if stats.resume:
        print("--> Fetching next page via resumptionToken ...")
        if stats.resume.succeeded:
            print("Resume succeeded; more pages?", bool(stats.resume.has_additional_pages))
        else:
            print("Received error on resume:", stats.resume.error)

    if stats.db_replay is not None:
        print("--> Calling /oai/db/ with tailored token (expect rejection)...")
        message = stats.db_replay.error or "no error element present"
        print("DB endpoint response:", message)

    if stats.snapshot_replay is not None:
        print("--> Calling /oai/ snapshot endpoint with tailored token (expect rejection)...")
        message = stats.snapshot_replay.error or "no error element present"
        print("Snapshot endpoint response:", message)

    if options.pause_for_dataset_change:
        endpoints = _build_endpoints(options.base_url)
        headers = _build_headers(options)
        input("\n*** Make a dataset change (e.g., approve/unapprove a project), then press Enter to retry token...\n")
        stale_resp = _perform_request(
            "tailored resume",
            endpoints["tailored"],
            {"verb": options.verb, "resumptionToken": token},
            headers,
            http_get,
        )
        print("Tailored endpoint after dataset change:", _extract_error(stale_resp) or "no error element present")

    return stats
