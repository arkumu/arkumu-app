#!/usr/bin/env python3
"""Test OAI-PMH resumption tokens for KHM harvesting."""

import sys
import time
import requests
from xml.etree import ElementTree as ET

BASE_URL = "http://localhost:8000/metadata/dashboard/oai-tailored/"
OAI_NS = "{http://www.openarchives.org/OAI/2.0/}"

# Create session with authentication
session = requests.Session()

def login():
    """Login to get session cookie."""
    # Get CSRF token
    login_url = "http://localhost:8000/accounts/login/"
    resp = session.get(login_url)

    # Extract CSRF token from cookies or form
    csrf_token = session.cookies.get("csrftoken")
    if not csrf_token:
        import re
        match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', resp.text)
        if match:
            csrf_token = match.group(1)

    if not csrf_token:
        print("Could not get CSRF token")
        return False

    # Login
    resp = session.post(
        login_url,
        data={
            "csrfmiddlewaretoken": csrf_token,
            "login": "test",
            "password": "test",
        },
        headers={"Referer": login_url},
        allow_redirects=False,
    )

    if resp.status_code in (302, 200):
        print("Logged in successfully")
        return True
    else:
        print(f"Login failed: {resp.status_code}")
        return False


def parse_response(xml_text):
    """Parse OAI-PMH response and extract key info."""
    root = ET.fromstring(xml_text)

    error = root.find(f".//{OAI_NS}error")
    if error is not None:
        return {
            "error": error.get("code"),
            "message": error.text,
        }

    # ListIdentifiers
    list_ids = root.find(f".//{OAI_NS}ListIdentifiers")
    if list_ids is not None:
        headers = list_ids.findall(f"{OAI_NS}header")
        token_elem = list_ids.find(f"{OAI_NS}resumptionToken")
        all_ids = [h.find(f"{OAI_NS}identifier").text for h in headers]
        return {
            "verb": "ListIdentifiers",
            "count": len(headers),
            "identifiers": all_ids,
            "display_ids": all_ids[:3],  # For display only
            "resumptionToken": token_elem.text if token_elem is not None else None,
        }

    # ListRecords
    list_recs = root.find(f".//{OAI_NS}ListRecords")
    if list_recs is not None:
        records = list_recs.findall(f"{OAI_NS}record")
        token_elem = list_recs.find(f"{OAI_NS}resumptionToken")
        all_ids = [r.find(f".//{OAI_NS}identifier").text for r in records]
        return {
            "verb": "ListRecords",
            "count": len(records),
            "identifiers": all_ids,
            "display_ids": all_ids[:3],  # For display only
            "resumptionToken": token_elem.text if token_elem is not None else None,
        }

    return {"error": "unknown", "message": "Could not parse response"}


def test_harvesting(set_spec, verb="ListIdentifiers", max_pages=5):
    """Test harvesting with resumption tokens."""
    print(f"\n{'='*60}")
    print(f"Testing {verb} for set={set_spec}")
    print(f"{'='*60}")

    params = {
        "verb": verb,
        "metadataPrefix": "mets",
        "set": set_spec,
    }

    all_identifiers = []
    page = 0
    token = None

    while page < max_pages:
        page += 1

        if token:
            # Use resumption token (replaces all other params)
            req_params = {"verb": verb, "resumptionToken": token}
        else:
            req_params = params

        print(f"\nPage {page}: ", end="")
        start = time.time()

        try:
            resp = session.get(BASE_URL, params=req_params, timeout=120)
            elapsed = time.time() - start
            print(f"{elapsed:.2f}s")

            if resp.status_code != 200:
                print(f"  ERROR: HTTP {resp.status_code}")
                print(f"  {resp.text[:500]}")
                break

            result = parse_response(resp.text)

            if "error" in result:
                print(f"  OAI Error: {result['error']} - {result.get('message', '')}")
                break

            print(f"  Records: {result['count']}")
            print(f"  First IDs: {result.get('display_ids', result['identifiers'][:3])}")

            all_identifiers.extend(result.get("identifiers", []))

            token = result.get("resumptionToken")
            if token:
                print(f"  Token: {token[:50]}...")
            else:
                print("  No more pages (no resumption token)")
                break

        except requests.exceptions.Timeout:
            print("  TIMEOUT!")
            break
        except Exception as e:
            print(f"  Exception: {e}")
            break

    print(f"\n{'='*60}")
    print(f"Summary for {set_spec}:")
    print(f"  Pages fetched: {page}")
    print(f"  Total identifiers: {len(all_identifiers)}")
    print(f"  Unique identifiers: {len(set(all_identifiers))}")

    # Check for duplicates
    if len(all_identifiers) != len(set(all_identifiers)):
        print("  WARNING: Duplicate identifiers found!")
        from collections import Counter
        counts = Counter(all_identifiers)
        dups = [(k, v) for k, v in counts.items() if v > 1]
        print(f"  Duplicates: {dups[:5]}")

    return all_identifiers


def main():
    if not login():
        print("Failed to login, exiting")
        sys.exit(1)

    sets_to_test = ["khm", "hmt"]

    if len(sys.argv) > 1:
        sets_to_test = sys.argv[1:]

    for set_spec in sets_to_test:
        # Test ListIdentifiers with more pages
        test_harvesting(set_spec, verb="ListIdentifiers", max_pages=10)

        # Test ListRecords (2 pages to verify token works)
        print(f"\n--- Testing ListRecords for {set_spec} (2 pages) ---")
        test_harvesting(set_spec, verb="ListRecords", max_pages=2)


if __name__ == "__main__":
    main()
