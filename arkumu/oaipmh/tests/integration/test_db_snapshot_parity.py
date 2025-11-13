"""
Parity tests for snapshot-backed `/oai/` and DB-backed `/oai/db/` endpoints.

Implements the comparison checklist from docs/db_vs_snapshot_comparison.md:
  * Pagination span + resumption token semantics
  * ListRecords/METS payload equality
  * GetRecord payload parity for both metadata formats
  * Matching error handling for tampered tokens + missing harvestables
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple
from urllib.parse import quote

import pytest
from lxml import etree as ET

from arkumu.oaipmh import views

OAI_NS = "http://www.openarchives.org/OAI/2.0/"
OAI = f"{{{OAI_NS}}}"


@dataclass
class HarvestPage:
    identifiers: List[str]
    resumption_tokens: List[str]


def _parse_response(content: bytes) -> ET._Element:
    return ET.fromstring(content)


def _header_identifiers(root: ET._Element) -> List[str]:
    path = f".//{OAI}header/{OAI}identifier"
    return [elem.text for elem in root.findall(path) if elem.text]


def _record_map(root: ET._Element) -> Dict[str, bytes]:
    records = {}
    for record in root.findall(f".//{OAI}record"):
        identifier = record.find(f"./{OAI}header/{OAI}identifier")
        if identifier is None or not identifier.text:
            continue
        records[identifier.text] = ET.tostring(record, encoding="utf-8")
    return records


def _resumption_token(root: ET._Element) -> str | None:
    token = root.find(f".//{OAI}resumptionToken")
    text = token.text if token is not None else None
    return text or None


def _collect_identifiers(client, path: str, base_params: Dict[str, str]) -> HarvestPage:
    params = dict(base_params)
    identifiers: List[str] = []
    tokens: List[str] = []

    while True:
        response = client.get(path, params)
        assert response.status_code == 200
        root = _parse_response(response.content)

        identifiers.extend(_header_identifiers(root))
        token = _resumption_token(root)
        if not token:
            break
        tokens.append(token)
        params = {"verb": base_params["verb"], "resumptionToken": token}

    return HarvestPage(identifiers=identifiers, resumption_tokens=tokens)


def _collect_records(client, path: str, base_params: Dict[str, str]) -> Tuple[Dict[str, bytes], List[str]]:
    params = dict(base_params)
    records: Dict[str, bytes] = {}
    tokens: List[str] = []

    while True:
        response = client.get(path, params)
        assert response.status_code == 200
        root = _parse_response(response.content)

        records.update(_record_map(root))
        token = _resumption_token(root)
        if not token:
            break
        tokens.append(token)
        params = {"verb": base_params["verb"], "resumptionToken": token}

    return records, tokens


def _decode_token(token: str) -> Dict[str, str]:
    valid, payload, error = views.resumption_service.parse_token(token)
    assert valid, error
    assert payload is not None
    return payload


def _oai_identifier(uri: str) -> str:
    return f"oai:arkumu:resource:{quote(uri, safe='')}"


def _extract_error(root: ET._Element) -> Tuple[str, str]:
    error_elem = root.find(f".//{OAI}error")
    if error_elem is None:
        return "", ""
    return error_elem.get("code", ""), (error_elem.text or "").strip()


@pytest.mark.django_db
@pytest.mark.usefixtures("mock_canonical_graph_service")
def test_list_identifiers_pagination_parity(oai_client, parity_dataset):
    """Ensure ListIdentifiers has identical spans while tokens encode expected markers."""
    for org_code in parity_dataset["org_codes"]:
        base_params = {
            "verb": "ListIdentifiers",
            "metadataPrefix": "oai_dc",
            "set": org_code,
            "from": "2020-01-01",
        }

        snapshot_pages = _collect_identifiers(oai_client, "/oai/", base_params)
        db_pages = _collect_identifiers(oai_client, "/oai/db/", base_params)

        assert snapshot_pages.identifiers == db_pages.identifiers
        assert len(snapshot_pages.identifiers) == len(parity_dataset["orgs"][org_code]["uris"])

        assert bool(snapshot_pages.resumption_tokens) == bool(db_pages.resumption_tokens)
        if snapshot_pages.resumption_tokens:
            snapshot_token = snapshot_pages.resumption_tokens[0]
            db_token = db_pages.resumption_tokens[0]

            snapshot_payload = _decode_token(snapshot_token)
            db_payload = _decode_token(db_token)

            assert "snapshot" in snapshot_payload
            assert "cursor" not in snapshot_payload

            assert "cursor" in db_payload
            assert "cursor_position" in db_payload


@pytest.mark.django_db
@pytest.mark.usefixtures("mock_canonical_graph_service")
def test_list_records_mets_payload_parity(oai_client, parity_dataset):
    """ListRecords with METS should return identical record payloads and pagination."""
    for org_code in parity_dataset["org_codes"]:
        base_params = {
            "verb": "ListRecords",
            "metadataPrefix": "mets",
            "set": org_code,
            "from": "2020-01-01",
        }

        snapshot_records, snapshot_tokens = _collect_records(oai_client, "/oai/", base_params)
        db_records, db_tokens = _collect_records(oai_client, "/oai/db/", base_params)

        assert snapshot_records.keys() == db_records.keys()
        for identifier, snapshot_xml in snapshot_records.items():
            assert snapshot_xml == db_records[identifier]

        assert bool(snapshot_tokens) == bool(db_tokens)


@pytest.mark.django_db
@pytest.mark.usefixtures("mock_canonical_graph_service")
def test_get_record_payload_parity(oai_client, parity_dataset):
    """GetRecord must emit byte-for-byte identical headers + metadata for both formats."""
    for uri in parity_dataset["sample_project_uris"]:
        identifier = _oai_identifier(uri)
        for metadata_prefix in ("oai_dc", "mets"):
            params = {
                "verb": "GetRecord",
                "identifier": identifier,
                "metadataPrefix": metadata_prefix,
            }

            snapshot = oai_client.get("/oai/", params)
            db_response = oai_client.get("/oai/db/", params)

            assert snapshot.status_code == 200
            assert db_response.status_code == 200

            snapshot_root = _parse_response(snapshot.content)
            db_root = _parse_response(db_response.content)

            snapshot_record = snapshot_root.find(f".//{OAI}record")
            db_record = db_root.find(f".//{OAI}record")
            assert snapshot_record is not None
            assert db_record is not None

            snapshot_header = snapshot_record.find(f"./{OAI}header")
            db_header = db_record.find(f"./{OAI}header")
            assert ET.tostring(snapshot_header, encoding="utf-8") == ET.tostring(db_header, encoding="utf-8")

            snapshot_metadata = snapshot_record.find(f"./{OAI}metadata")
            db_metadata = db_record.find(f"./{OAI}metadata")
            assert snapshot_metadata is not None
            assert db_metadata is not None
            assert ET.tostring(snapshot_metadata, encoding="utf-8") == ET.tostring(db_metadata, encoding="utf-8")


@pytest.mark.django_db
@pytest.mark.usefixtures("mock_canonical_graph_service")
def test_error_semantics_align(oai_client, parity_dataset):
    """Both endpoints must reply with identical error codes for tampered tokens and missing files."""
    org_code = parity_dataset["org_codes"][0]
    pages = _collect_identifiers(
        oai_client,
        "/oai/",
        {
            "verb": "ListIdentifiers",
            "metadataPrefix": "oai_dc",
            "set": org_code,
        },
    )
    db_pages = _collect_identifiers(
        oai_client,
        "/oai/db/",
        {
            "verb": "ListIdentifiers",
            "metadataPrefix": "oai_dc",
            "set": org_code,
        },
    )

    assert pages.resumption_tokens
    assert db_pages.resumption_tokens

    def _tamper(token: str) -> str:
        return f"{token}A"

    snapshot_error = oai_client.get("/oai/", {
        "verb": "ListIdentifiers",
        "resumptionToken": _tamper(pages.resumption_tokens[0]),
    })
    db_error = oai_client.get("/oai/db/", {
        "verb": "ListIdentifiers",
        "resumptionToken": _tamper(db_pages.resumption_tokens[0]),
    })

    for response in (snapshot_error, db_error):
        assert response.status_code == 200

    snapshot_error_code, _ = _extract_error(_parse_response(snapshot_error.content))
    db_error_code, _ = _extract_error(_parse_response(db_error.content))
    assert snapshot_error_code == db_error_code == "badResumptionToken"

    missing_identifier = _oai_identifier(parity_dataset["non_harvestable_uri"])
    params = {
        "verb": "GetRecord",
        "identifier": missing_identifier,
        "metadataPrefix": "mets",
    }

    snapshot_missing = oai_client.get("/oai/", params)
    db_missing = oai_client.get("/oai/db/", params)
    for response in (snapshot_missing, db_missing):
        assert response.status_code == 200

    snapshot_missing_code, _ = _extract_error(_parse_response(snapshot_missing.content))
    db_missing_code, _ = _extract_error(_parse_response(db_missing.content))
    assert snapshot_missing_code == db_missing_code == "idDoesNotExist"

