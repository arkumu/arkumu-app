#!/usr/bin/env python
"""
Simple OAI-PMH compliance test script.

This script tests the basic functionality of the OAI-PMH implementation
by making requests to all mandatory verbs and validating responses.
"""

import sys
import requests
from urllib.parse import urljoin
import xml.etree.ElementTree as ET


def test_oai_pmh_endpoint(base_url="http://localhost:8000/oai/"):
    """Test all OAI-PMH verbs for basic compliance."""

    print(f"Testing OAI-PMH endpoint: {base_url}")
    print("=" * 60)

    results = {}

    # Test 1: Identify
    print("\n1. Testing Identify verb...")
    try:
        response = requests.get(base_url, params={"verb": "Identify"}, timeout=30)
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            if root.find(".//{http://www.openarchives.org/OAI/2.0/}Identify") is not None:
                print("✅ Identify: SUCCESS")
                results["Identify"] = "PASS"
            else:
                print("❌ Identify: Missing Identify element")
                results["Identify"] = "FAIL"
        else:
            print(f"❌ Identify: HTTP {response.status_code}")
            results["Identify"] = "FAIL"
    except Exception as e:
        print(f"❌ Identify: Exception - {e}")
        results["Identify"] = "FAIL"

    # Test 2: ListMetadataFormats
    print("\n2. Testing ListMetadataFormats verb...")
    try:
        response = requests.get(base_url, params={"verb": "ListMetadataFormats"}, timeout=30)
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            formats = root.findall(".//{http://www.openarchives.org/OAI/2.0/}metadataFormat")
            if len(formats) > 0:
                print(f"✅ ListMetadataFormats: SUCCESS ({len(formats)} formats found)")
                for fmt in formats:
                    prefix = fmt.find(".//{http://www.openarchives.org/OAI/2.0/}metadataPrefix")
                    if prefix is not None:
                        print(f"   - {prefix.text}")
                results["ListMetadataFormats"] = "PASS"
            else:
                print("❌ ListMetadataFormats: No formats found")
                results["ListMetadataFormats"] = "FAIL"
        else:
            print(f"❌ ListMetadataFormats: HTTP {response.status_code}")
            results["ListMetadataFormats"] = "FAIL"
    except Exception as e:
        print(f"❌ ListMetadataFormats: Exception - {e}")
        results["ListMetadataFormats"] = "FAIL"

    # Test 3: ListSets
    print("\n3. Testing ListSets verb...")
    try:
        response = requests.get(base_url, params={"verb": "ListSets"}, timeout=30)
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            sets = root.findall(".//{http://www.openarchives.org/OAI/2.0/}set")
            print(f"✅ ListSets: SUCCESS ({len(sets)} sets found)")
            for s in sets[:3]:  # Show first 3 sets
                spec = s.find(".//{http://www.openarchives.org/OAI/2.0/}setSpec")
                name = s.find(".//{http://www.openarchives.org/OAI/2.0/}setName")
                if spec is not None and name is not None:
                    print(f"   - {spec.text}: {name.text}")
            results["ListSets"] = "PASS"
        else:
            print(f"❌ ListSets: HTTP {response.status_code}")
            results["ListSets"] = "FAIL"
    except Exception as e:
        print(f"❌ ListSets: Exception - {e}")
        results["ListSets"] = "FAIL"

    # Test 4: ListIdentifiers (requires records to exist)
    print("\n4. Testing ListIdentifiers verb...")
    try:
        response = requests.get(base_url, params={"verb": "ListIdentifiers", "metadataPrefix": "oai_dc"}, timeout=30)
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            error = root.find(".//{http://www.openarchives.org/OAI/2.0/}error")
            if error is not None and error.get("code") == "noRecordsMatch":
                print("✅ ListIdentifiers: SUCCESS (no records available, but proper error response)")
                results["ListIdentifiers"] = "PASS"
            else:
                headers = root.findall(".//{http://www.openarchives.org/OAI/2.0/}header")
                if len(headers) > 0:
                    print(f"✅ ListIdentifiers: SUCCESS ({len(headers)} identifiers found)")
                    results["ListIdentifiers"] = "PASS"
                else:
                    print("❌ ListIdentifiers: No headers or proper error found")
                    results["ListIdentifiers"] = "FAIL"
        else:
            print(f"❌ ListIdentifiers: HTTP {response.status_code}")
            results["ListIdentifiers"] = "FAIL"
    except Exception as e:
        print(f"❌ ListIdentifiers: Exception - {e}")
        results["ListIdentifiers"] = "FAIL"

    # Test 5: ListRecords (requires records to exist)
    print("\n5. Testing ListRecords verb...")
    try:
        response = requests.get(base_url, params={"verb": "ListRecords", "metadataPrefix": "oai_dc"}, timeout=30)
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            error = root.find(".//{http://www.openarchives.org/OAI/2.0/}error")
            if error is not None and error.get("code") == "noRecordsMatch":
                print("✅ ListRecords: SUCCESS (no records available, but proper error response)")
                results["ListRecords"] = "PASS"
            else:
                records = root.findall(".//{http://www.openarchives.org/OAI/2.0/}record")
                if len(records) > 0:
                    print(f"✅ ListRecords: SUCCESS ({len(records)} records found)")
                    results["ListRecords"] = "PASS"
                else:
                    print("❌ ListRecords: No records or proper error found")
                    results["ListRecords"] = "FAIL"
        else:
            print(f"❌ ListRecords: HTTP {response.status_code}")
            results["ListRecords"] = "FAIL"
    except Exception as e:
        print(f"❌ ListRecords: Exception - {e}")
        results["ListRecords"] = "FAIL"

    # Test 6: Error handling
    print("\n6. Testing error handling...")
    try:
        response = requests.get(base_url, params={"verb": "InvalidVerb"}, timeout=30)
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            error = root.find(".//{http://www.openarchives.org/OAI/2.0/}error")
            if error is not None and error.get("code") == "badVerb":
                print("✅ Error handling: SUCCESS (proper badVerb error)")
                results["ErrorHandling"] = "PASS"
            else:
                print("❌ Error handling: Missing or incorrect error response")
                results["ErrorHandling"] = "FAIL"
        else:
            print(f"❌ Error handling: HTTP {response.status_code}")
            results["ErrorHandling"] = "FAIL"
    except Exception as e:
        print(f"❌ Error handling: Exception - {e}")
        results["ErrorHandling"] = "FAIL"

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY:")
    passed = sum(1 for result in results.values() if result == "PASS")
    total = len(results)
    print(f"Tests passed: {passed}/{total}")

    for test, result in results.items():
        status = "✅" if result == "PASS" else "❌"
        print(f"{status} {test}")

    if passed == total:
        print("\n🎉 All tests passed! OAI-PMH implementation appears to be working correctly.")
        return True
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Check the implementation.")
        return False


if __name__ == "__main__":
    # Default to localhost, but allow override via command line
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000/oai/"
    success = test_oai_pmh_endpoint(base_url)
    sys.exit(0 if success else 1)