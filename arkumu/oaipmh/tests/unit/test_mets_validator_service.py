"""Unit tests for the Rosetta METS validator."""

from __future__ import annotations

from pathlib import Path

import pytest
from django.conf import settings
from lxml import etree as LET

from arkumu.oaipmh.validation import RosettaMETSValidator
from arkumu.oaipmh.constants import METS_NS, XLINK_NS


@pytest.fixture(scope="module")
def validator() -> RosettaMETSValidator:
    return RosettaMETSValidator()


@pytest.fixture(scope="module")
def example_metadata_element() -> LET._Element:
    example_path = Path(settings.BASE_DIR) / "arkumu/oaipmh/schema/arkumu_mets_example.xml"
    xml_text = example_path.read_text(encoding="utf-8")
    record = LET.fromstring(xml_text.encode("utf-8"))
    metadata_elem = record.find(".//metadata")
    assert metadata_elem is not None, "Example METS record missing <metadata> wrapper"
    return metadata_elem


def test_example_record_validates(validator: RosettaMETSValidator, example_metadata_element: LET._Element):
    result = validator.validate_metadata_element(example_metadata_element)
    assert result.is_valid, "Bundled Rosetta example should validate successfully"


def test_missing_dc_namespace_fails(validator: RosettaMETSValidator, example_metadata_element: LET._Element):
    metadata_copy = LET.fromstring(LET.tostring(example_metadata_element))
    mets_elem = metadata_copy[0]
    nsmap = {prefix: uri for prefix, uri in mets_elem.nsmap.items() if prefix != "dc"}
    rebuilt_mets = LET.Element(LET.QName(mets_elem.nsmap["mets"], "mets"), nsmap=nsmap)
    for attr, value in mets_elem.attrib.items():
        rebuilt_mets.set(attr, value)
    for child in mets_elem:
        rebuilt_mets.append(child)

    metadata_copy.clear()
    metadata_copy.append(rebuilt_mets)

    result = validator.validate_metadata_element(metadata_copy)
    assert not result.is_valid, "Missing dc namespace should trigger validation failure"


def test_missing_flocat_fails(validator: RosettaMETSValidator, example_metadata_element: LET._Element):
    metadata_copy = LET.fromstring(LET.tostring(example_metadata_element))
    for flocat in metadata_copy.findall(f'.//{{{METS_NS}}}FLocat'):
        parent = flocat.getparent()
        if parent is not None:
            parent.remove(flocat)

    result = validator.validate_metadata_element(metadata_copy)
    assert not result.is_valid, "METS payload without FLocat should fail semantic validation"


def test_validate_metadata_xml_handles_parse_errors(validator: RosettaMETSValidator):
    result = validator.validate_metadata_xml("<metadata><broken></metadata>")
    assert not result.is_valid


def test_invalid_href_detected(validator: RosettaMETSValidator, example_metadata_element: LET._Element):
    metadata_copy = LET.fromstring(LET.tostring(example_metadata_element))
    first_flocat = metadata_copy.find(f'.//{{{METS_NS}}}FLocat')
    assert first_flocat is not None
    first_flocat.set(f'{{{XLINK_NS}}}href', '   ')

    result = validator.validate_metadata_element(metadata_copy)
    assert not result.is_valid, "Empty xlink:href values should fail validation"
