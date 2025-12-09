"""Detailed XSD validation tests for Rosetta METS schema (rosettaMets.xsd + dnx_sip.xsd).

Tests validate against the actual Rosetta METS XSD 1.1 schema to ensure
our METS output is fully compliant with Rosetta requirements.
"""

from __future__ import annotations

import pytest
from lxml import etree as ET

from arkumu.oaipmh.validation.mets_validator import RosettaMETSValidator
from arkumu.oaipmh.constants import ROSETTA_METS_NS, DNX_NS, XLINK_NS


# Rosetta METS namespace map
ROSETTA_NSMAP = {
    "mets": ROSETTA_METS_NS,
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "xlink": XLINK_NS,
    None: DNX_NS,
}


@pytest.fixture(scope="module")
def validator() -> RosettaMETSValidator:
    """Shared validator instance."""
    return RosettaMETSValidator()


def _build_minimal_valid_mets() -> str:
    """Build a minimal valid Rosetta METS document."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<mets:mets xmlns:mets="{ROSETTA_METS_NS}"
           xmlns:dc="http://purl.org/dc/elements/1.1/"
           xmlns:dcterms="http://purl.org/dc/terms/"
           xmlns:xlink="{XLINK_NS}"
           xmlns="{DNX_NS}">
  <mets:dmdSec ID="ie-dmd">
    <mets:mdWrap MDTYPE="DC">
      <mets:xmlData>
        <dc:record>
          <dc:title>Test Title</dc:title>
          <dc:identifier>test-123</dc:identifier>
        </dc:record>
      </mets:xmlData>
    </mets:mdWrap>
  </mets:dmdSec>
  <mets:amdSec ID="ie-amd">
    <mets:techMD ID="ie-amd-tech">
      <mets:mdWrap MDTYPE="OTHER" OTHERMDTYPE="dnx">
        <mets:xmlData>
          <dnx/>
        </mets:xmlData>
      </mets:mdWrap>
    </mets:techMD>
  </mets:amdSec>
  <mets:amdSec ID="rep1-amd">
    <mets:techMD ID="rep1-amd-tech">
      <mets:mdWrap MDTYPE="OTHER" OTHERMDTYPE="dnx">
        <mets:xmlData>
          <dnx>
            <section id="generalRepCharacteristics">
              <record>
                <key id="preservationType">PRESERVATION_MASTER</key>
                <key id="usageType">VIEW</key>
              </record>
            </section>
          </dnx>
        </mets:xmlData>
      </mets:mdWrap>
    </mets:techMD>
  </mets:amdSec>
  <mets:amdSec ID="fid1-1-amd">
    <mets:techMD ID="fid1-1-amd-tech">
      <mets:mdWrap MDTYPE="OTHER" OTHERMDTYPE="dnx">
        <mets:xmlData>
          <dnx/>
        </mets:xmlData>
      </mets:mdWrap>
    </mets:techMD>
  </mets:amdSec>
  <mets:fileSec>
    <mets:fileGrp USE="VIEW" ID="rep1" ADMID="rep1-amd">
      <mets:file ID="fid1-1" ADMID="fid1-1-amd">
        <mets:FLocat LOCTYPE="URL" xlink:href="content/streams/test.pdf"/>
      </mets:file>
    </mets:fileGrp>
  </mets:fileSec>
  <mets:structMap ID="rep1-1" TYPE="LOGICAL">
    <mets:div>
      <mets:div TYPE="FILE" LABEL="Test File">
        <mets:fptr FILEID="fid1-1"/>
      </mets:div>
    </mets:div>
  </mets:structMap>
</mets:mets>"""


class TestRosettaMetsXsdValidation:
    """Tests for validate_rosetta_mets_xml() against rosettaMets.xsd."""

    def test_minimal_valid_mets_passes(self, validator: RosettaMETSValidator):
        """A minimal valid Rosetta METS document should pass validation."""
        mets_xml = _build_minimal_valid_mets()
        result = validator.validate_rosetta_mets_xml(mets_xml)
        assert result.is_valid, f"Valid METS should pass: {result.issues}"

    def test_empty_payload_fails(self, validator: RosettaMETSValidator):
        """Empty payload should fail validation."""
        result = validator.validate_rosetta_mets_xml("")
        assert not result.is_valid
        assert any("Empty" in issue.message for issue in result.issues)

    def test_invalid_xml_fails(self, validator: RosettaMETSValidator):
        """Malformed XML should fail validation."""
        result = validator.validate_rosetta_mets_xml("<mets:mets><broken></mets:mets>")
        assert not result.is_valid
        assert any("Invalid XML" in issue.message for issue in result.issues)

    def test_objid_attribute_not_allowed(self, validator: RosettaMETSValidator):
        """OBJID attribute on mets:mets root is not allowed in Rosetta schema."""
        mets_xml = _build_minimal_valid_mets().replace(
            '<mets:mets xmlns:mets=',
            '<mets:mets OBJID="http://example.org/test" xmlns:mets='
        )
        result = validator.validate_rosetta_mets_xml(mets_xml)
        assert not result.is_valid
        assert any("OBJID" in issue.message for issue in result.issues)

    def test_size_attribute_not_allowed_on_file(self, validator: RosettaMETSValidator):
        """SIZE attribute on mets:file is not allowed in Rosetta schema."""
        mets_xml = _build_minimal_valid_mets().replace(
            '<mets:file ID="fid1-1" ADMID="fid1-1-amd">',
            '<mets:file ID="fid1-1" ADMID="fid1-1-amd" SIZE="12345">'
        )
        result = validator.validate_rosetta_mets_xml(mets_xml)
        assert not result.is_valid
        assert any("SIZE" in issue.message for issue in result.issues)

    def test_invalid_div_type_fails(self, validator: RosettaMETSValidator):
        """div TYPE must be 'FILE' in Rosetta schema, not arbitrary values."""
        mets_xml = _build_minimal_valid_mets().replace(
            'TYPE="FILE"',
            'TYPE="project"'
        )
        result = validator.validate_rosetta_mets_xml(mets_xml)
        assert not result.is_valid
        assert any("FILE" in issue.message or "TYPE" in issue.message for issue in result.issues)

    def test_missing_dmdsec_allowed(self, validator: RosettaMETSValidator):
        """Missing dmdSec is allowed in Rosetta schema (optional element)."""
        mets_xml = _build_minimal_valid_mets()
        root = ET.fromstring(mets_xml.encode("utf-8"))
        dmd_sec = root.find(f".//{{{ROSETTA_METS_NS}}}dmdSec")
        if dmd_sec is not None:
            root.remove(dmd_sec)
        modified_xml = ET.tostring(root, encoding="unicode")
        result = validator.validate_rosetta_mets_xml(modified_xml)
        # dmdSec is optional in Rosetta schema
        assert result.is_valid, f"dmdSec should be optional: {result.issues}"

    def test_missing_filesec_allowed(self, validator: RosettaMETSValidator):
        """Missing fileSec is allowed per Rosetta 7.2 (structural IE)."""
        mets_xml = _build_minimal_valid_mets()
        root = ET.fromstring(mets_xml.encode("utf-8"))
        file_sec = root.find(f".//{{{ROSETTA_METS_NS}}}fileSec")
        if file_sec is not None:
            root.remove(file_sec)
        # Also remove structMap since it references files
        struct_map = root.find(f".//{{{ROSETTA_METS_NS}}}structMap")
        if struct_map is not None:
            root.remove(struct_map)
        modified_xml = ET.tostring(root, encoding="unicode")
        result = validator.validate_rosetta_mets_xml(modified_xml)
        # This should pass - fileSec is optional since Rosetta 7.2
        assert result.is_valid, f"Missing fileSec should be allowed: {result.issues}"

    def test_flocat_with_href_valid(self, validator: RosettaMETSValidator):
        """FLocat with xlink:href should be valid."""
        mets_xml = _build_minimal_valid_mets()
        assert 'xlink:href="content/streams/test.pdf"' in mets_xml
        result = validator.validate_rosetta_mets_xml(mets_xml)
        assert result.is_valid

    def test_flocat_invalid_loctype_fails(self, validator: RosettaMETSValidator):
        """FLocat with invalid LOCTYPE should fail."""
        mets_xml = _build_minimal_valid_mets().replace(
            'LOCTYPE="URL"',
            'LOCTYPE="INVALID"'
        )
        result = validator.validate_rosetta_mets_xml(mets_xml)
        assert not result.is_valid


class TestDnxXsdValidation:
    """Tests for DNX schema validation (dnx_sip.xsd)."""

    def test_valid_dnx_passes(self, validator: RosettaMETSValidator):
        """Valid DNX sections should pass."""
        mets_xml = _build_minimal_valid_mets()
        result = validator.validate_rosetta_mets_xml(mets_xml)
        assert result.is_valid

    def test_dnx_with_general_rep_characteristics(self, validator: RosettaMETSValidator):
        """DNX with generalRepCharacteristics section should be valid."""
        mets_xml = _build_minimal_valid_mets()
        assert "generalRepCharacteristics" in mets_xml
        result = validator.validate_rosetta_mets_xml(mets_xml)
        assert result.is_valid

    def test_dnx_invalid_section_id_fails(self, validator: RosettaMETSValidator):
        """DNX with invalid section id should fail."""
        mets_xml = _build_minimal_valid_mets().replace(
            'section id="generalRepCharacteristics"',
            'section id="invalidSectionName"'
        )
        result = validator.validate_rosetta_mets_xml(mets_xml)
        assert not result.is_valid

    def test_dnx_invalid_key_id_fails(self, validator: RosettaMETSValidator):
        """DNX with invalid key id should fail."""
        mets_xml = _build_minimal_valid_mets().replace(
            'key id="preservationType"',
            'key id="invalidKeyName"'
        )
        result = validator.validate_rosetta_mets_xml(mets_xml)
        assert not result.is_valid


class TestNamespaceValidation:
    """Tests for namespace handling in Rosetta METS."""

    def test_correct_rosetta_namespace(self, validator: RosettaMETSValidator):
        """Rosetta METS must use the correct namespace."""
        mets_xml = _build_minimal_valid_mets()
        assert ROSETTA_METS_NS in mets_xml
        result = validator.validate_rosetta_mets_xml(mets_xml)
        assert result.is_valid

    def test_wrong_mets_namespace_fails(self, validator: RosettaMETSValidator):
        """Using LOC METS namespace instead of Rosetta should fail."""
        mets_xml = _build_minimal_valid_mets().replace(
            ROSETTA_METS_NS,
            "http://www.loc.gov/METS/"
        )
        result = validator.validate_rosetta_mets_xml(mets_xml)
        assert not result.is_valid

    def test_dnx_namespace_required(self, validator: RosettaMETSValidator):
        """DNX elements must use the correct namespace."""
        mets_xml = _build_minimal_valid_mets()
        assert DNX_NS in mets_xml
        result = validator.validate_rosetta_mets_xml(mets_xml)
        assert result.is_valid


class TestStructMapValidation:
    """Tests for structMap validation in Rosetta METS."""

    def test_logical_structmap_type_allowed(self, validator: RosettaMETSValidator):
        """LOGICAL structMap TYPE is allowed."""
        mets_xml = _build_minimal_valid_mets()
        assert 'TYPE="LOGICAL"' in mets_xml
        result = validator.validate_rosetta_mets_xml(mets_xml)
        assert result.is_valid

    def test_physical_structmap_type_allowed(self, validator: RosettaMETSValidator):
        """PHYSICAL structMap TYPE is allowed."""
        mets_xml = _build_minimal_valid_mets().replace(
            'TYPE="LOGICAL"',
            'TYPE="PHYSICAL"'
        )
        result = validator.validate_rosetta_mets_xml(mets_xml)
        assert result.is_valid

    def test_fptr_references_valid_file(self, validator: RosettaMETSValidator):
        """fptr FILEID must reference a valid file ID."""
        mets_xml = _build_minimal_valid_mets()
        assert 'FILEID="fid1-1"' in mets_xml
        assert 'ID="fid1-1"' in mets_xml
        result = validator.validate_rosetta_mets_xml(mets_xml)
        assert result.is_valid
