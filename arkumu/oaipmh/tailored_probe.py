"""Utilities for probing tailored OAI endpoints and tokens."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Dict, Optional
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


def run_probe(options: TailoredProbeOptions) -> None:
    base = options.base_url.rstrip("/")
    endpoints = {
        "tailored": f"{base}/oai/tailored/",
        "db": f"{base}/oai/db/",
        "snapshot": f"{base}/oai/",
    }

    headers: Dict[str, str] = {}
    if options.basic_auth:
        auth_bytes = options.basic_auth.encode("utf-8")
        headers["Authorization"] = "Basic " + base64.b64encode(auth_bytes).decode("ascii")
    if options.internal_bypass:
        headers["X-INTERNAL-OAI-BYPASS"] = "1"

    verb_params = {
        "verb": options.verb,
        "metadataPrefix": options.metadata_prefix,
        "set": options.set_spec,
        "from": options.from_date,
        "until": options.until_date,
    }

    print("--> Requesting first page from /oai/tailored/ ...")
    page1 = _http_get(endpoints["tailored"], verb_params, headers)
    headers_count = len(ET.fromstring(page1).findall(".//oai:header", OAI_NS))
    token = _extract_resumption_token(page1)
    print(f"{headers_count} headers returned; token={'present' if token else 'missing'}")
    if token:
        decoded = _decode_token(token)
        print("Decoded token payload:\n" + json.dumps(decoded, indent=2))

    if not token:
        return

    if options.run_tailored_resume:
        print("--> Fetching next page via resumptionToken ...")
        page2 = _http_get(endpoints["tailored"], {"verb": options.verb, "resumptionToken": token}, headers)
        err = _extract_error(page2)
        if err:
            print("Received error on resume:", err)
        else:
            resumed = _extract_resumption_token(page2)
            print("Resume succeeded; more pages?", bool(resumed))

    if options.run_db_check:
        print("--> Calling /oai/db/ with tailored token (expect rejection)...")
        db_resp = _http_get(endpoints["db"], {"verb": options.verb, "resumptionToken": token}, headers)
        print("DB endpoint response:", _extract_error(db_resp) or "no error element present")

    if options.run_snapshot_check:
        print("--> Calling /oai/ snapshot endpoint with tailored token (expect rejection)...")
        snap_resp = _http_get(endpoints["snapshot"], {"verb": options.verb, "resumptionToken": token}, headers)
        print("Snapshot endpoint response:", _extract_error(snap_resp) or "no error element present")

    if options.pause_for_dataset_change:
        input("\n*** Make a dataset change (e.g., approve/unapprove a project), then press Enter to retry token...\n")
        stale_resp = _http_get(endpoints["tailored"], {"verb": options.verb, "resumptionToken": token}, headers)
        print("Tailored endpoint after dataset change:", _extract_error(stale_resp) or "no error element present")
