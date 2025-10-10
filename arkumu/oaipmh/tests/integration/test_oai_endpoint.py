"""
Integration tests for the OAI-PMH HTTP endpoint.

Tests complete request/response cycle for all OAI-PMH verbs
following the OAI-PMH 2.0 specification.
"""

import pytest
from functools import lru_cache
from pathlib import Path
from lxml import etree as LET
from lxml import etree as ET
from django.urls import reverse
from django.utils import timezone
from urllib.parse import quote
from urllib.request import urlopen
from unittest.mock import Mock, patch

from arkumu.projects.models import (
    ProjectRecord,
    ProjectDigitalObject,
    ProjectInstitution,
    ProjectSnapshot,
)

from arkumu.oaipmh import views

from arkumu.oaipmh.views import (
    METS_NS,
    METS_SCHEMA_URL,
    XSI_NS,
    XLINK_NS,
    _fallback_record_from_storage,
    HARVESTABLE_FILE_STATUSES,
)

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schema"
OAI_DC_SCHEMA_FILE = SCHEMA_DIR / "oai_dc.xsd"


SIMPLE_DC_TERMS = {
    'title', 'creator', 'subject', 'description', 'publisher', 'contributor',
    'date', 'type', 'format', 'identifier', 'source', 'language', 'relation',
    'coverage', 'rights'
}


class _HTTPResolver(LET.Resolver):
    """Resolver that fetches external schema references via HTTP(S)."""

    def resolve(self, system_url, public_id, context):  # noqa: D401
        from urllib.parse import urljoin
        from pathlib import Path

        target = system_url
        if target and not target.startswith("http"):
            base_url = getattr(context, "url", "") or getattr(context, "base_url", "")
            target = urljoin(base_url, target)

        if not target:
            return None

        if target.startswith("file://"):
            local_path = Path(target[len("file://"):])
            if local_path.exists():
                return self.resolve_filename(str(local_path), context)

        local_file = Path(target)
        if local_file.exists():
            return self.resolve_filename(str(local_file), context)

        with urlopen(target) as response:
            data = response.read()
        return self.resolve_string(data, context)


@lru_cache(maxsize=4)
def _load_schema(url: str) -> LET.XMLSchema:
    parser = LET.XMLParser()
    parser.resolvers.add(_HTTPResolver())
    local_path = None
    if url == METS_SCHEMA_URL:
        for candidate in (views.METS_SCHEMA_FILE, views.METS_LEGACY_SCHEMA_FILE):
            if candidate.exists():
                local_path = str(candidate)
                break
    elif url in {
        "http://www.openarchives.org/OAI/2.0/oai_dc.xsd",
        "https://www.openarchives.org/OAI/2.0/oai_dc.xsd",
    } and OAI_DC_SCHEMA_FILE.exists():
        local_path = str(OAI_DC_SCHEMA_FILE)

    document = LET.parse(local_path or url, parser)
    return LET.XMLSchema(document)


_FAST_SNAPSHOT_SERVICE = None


@pytest.fixture(autouse=True)
def _fast_snapshot_service(monkeypatch):
    """Patch snapshot service with a lightweight fallback-driven implementation."""
    from django.utils import timezone
    from arkumu.metadata.models.resource import Resource
    from arkumu.projects import ProjectSnapshot

    global _FAST_SNAPSHOT_SERVICE

    class _SnapshotStub:
        def __init__(self):
            self._snapshot = None
            self._index = {}

        def _build(self):
            resources = (
                Resource.objects.filter(
                    s3fileobject__status__in=HARVESTABLE_FILE_STATUSES,
                    s3fileobject__s3_key__isnull=False,
                )
                .exclude(s3fileobject__s3_key="")
                .distinct()
            )

            records = []
            index = {}
            for resource in resources:
                record = _fallback_record_from_storage(resource)
                if not record or not record.uri:
                    continue
                records.append(record)
                index[record.uri] = record

            self._snapshot = ProjectSnapshot(
                projects=records,
                counts={"projects": len(records)},
                generated_at=timezone.now(),
            )
            self._index = index

        def _ensure_snapshot(self):
            if self._snapshot is None:
                self._build()

        def get_cross_institutional_snapshot(self, *, force_refresh: bool = False):
            if force_refresh or self._snapshot is None:
                self._build()
            return self._snapshot

        def refresh_cross_institutional_snapshot(self):
            self._build()
            return self._snapshot

        def get_record_by_uri(self, uri: str):
            if not uri:
                return None
            self._ensure_snapshot()
            return self._index.get(uri)

    if _FAST_SNAPSHOT_SERVICE is None:
        _FAST_SNAPSHOT_SERVICE = _SnapshotStub()

    monkeypatch.setattr(views, "snapshot_service", _FAST_SNAPSHOT_SERVICE)
    yield


@pytest.mark.django_db
@pytest.mark.usefixtures("mock_canonical_graph_service")
class TestOAIEndpoint:
    """Test OAI-PMH HTTP endpoint with all verbs and error conditions."""

    def setup_method(self):
        """Set up test method."""
        self.oai_url = "/oai/"

    def _snapshot_record(self, resource):
        """Create a minimal snapshot record so responses include metadata."""
        return ProjectRecord(
            subject_id="snapshot-1",
            uri=resource.uri,
            title="Sample Project",
            description="Sample description",
            digital_objects=[
                ProjectDigitalObject(
                    path="files/sample.jpg",
                    storage_key="data/sample-bucket/files/sample.jpg",
                    file_name="sample.jpg",
                    content_type="image/jpeg",
                    size_bytes=1024,
                )
            ],
            institution_codes=[resource.organization.code] if resource.organization else [],
        )

    # ============================================================================
    # IDENTIFY VERB TESTS
    # ============================================================================

    def test_identify_success(self, oai_client, xml_validator):
        """Test successful Identify request."""
        response = oai_client.get(self.oai_url, {"verb": "Identify"})

        assert response.status_code == 200
        assert response["Content-Type"] == "text/xml"
        assert xml_validator.validate_oai_response(response.content.decode())

        # Check for required Identify elements
        content = response.content.decode()
        assert "<Identify>" in content
        assert "<repositoryName>Arkumu Repository</repositoryName>" in content
        # baseURL should be absolute
        assert "<baseURL>http://testserver/oai/</baseURL>" in content
        assert "<protocolVersion>2.0</protocolVersion>" in content
        assert "<adminEmail>mondaca@uni-koeln.de</adminEmail>" in content
        assert "<earliestDatestamp>1970-01-01T00:00:00Z</earliestDatestamp>" in content
        assert "<deletedRecord>no</deletedRecord>" in content
        assert "<granularity>YYYY-MM-DDThh:mm:ssZ</granularity>" in content

    def test_identify_with_extra_parameters(self, oai_client, xml_validator):
        """Test Identify with illegal extra parameters."""
        response = oai_client.get(self.oai_url, {
            "verb": "Identify",
            "metadataPrefix": "oai_dc"  # Illegal for Identify
        })

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        assert code == "badArgument"
        assert "Illegal argument(s): metadataPrefix" in message

    # ============================================================================
    # LISTMETADATAFORMATS VERB TESTS
    # ============================================================================

    def test_list_metadata_formats_success(self, oai_client, xml_validator):
        """Test successful ListMetadataFormats request."""
        response = oai_client.get(self.oai_url, {"verb": "ListMetadataFormats"})

        assert response.status_code == 200
        assert xml_validator.validate_oai_response(response.content.decode())

        content = response.content.decode()
        assert "<ListMetadataFormats>" in content
        assert "<metadataFormat>" in content

        # Check for Dublin Core format (mandatory)
        assert "<metadataPrefix>oai_dc</metadataPrefix>" in content
        assert "http://www.openarchives.org/OAI/2.0/oai_dc.xsd" in content
        assert "http://www.openarchives.org/OAI/2.0/oai_dc/" in content

        # Check for METS format
        assert "<metadataPrefix>mets</metadataPrefix>" in content
        assert METS_SCHEMA_URL in content

    def test_list_metadata_formats_with_identifier(self, oai_client, sample_resources, xml_validator):
        """Test ListMetadataFormats with valid identifier parameter."""
        resource = sample_resources[0]  # First public resource
        identifier = f"oai:arkumu:resource:{quote(resource.uri)}"

        response = oai_client.get(self.oai_url, {
            "verb": "ListMetadataFormats",
            "identifier": identifier
        })

        assert response.status_code == 200
        assert xml_validator.validate_oai_response(response.content.decode())

    def test_list_metadata_formats_invalid_identifier(self, oai_client, xml_validator):
        """Test ListMetadataFormats with non-existent identifier."""
        response = oai_client.get(self.oai_url, {
            "verb": "ListMetadataFormats",
            "identifier": "oai:arkumu:resource:https://nonexistent.example.com"
        })

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        if code != "idDoesNotExist":
            pytest.fail(f"Unexpected OAI error {code}: {message}")

    # ============================================================================
    # LISTSETS VERB TESTS
    # ============================================================================

    def test_list_sets_success(self, oai_client, sample_organizations, xml_validator):
        """Test successful ListSets request."""
        response = oai_client.get(self.oai_url, {"verb": "ListSets"})

        assert response.status_code == 200
        assert xml_validator.validate_oai_response(response.content.decode())

        content = response.content.decode()
        assert "<ListSets>" in content
        assert "<set>" in content

        # Check for active organizations only
        assert "<setSpec>test_univ</setSpec>" in content
        assert "<setName>Test University Library</setName>" in content
        assert "<setSpec>research_inst</setSpec>" in content
        assert "<setName>Research Institute</setName>" in content

        # Inactive organization should not appear
        assert "inactive_org" not in content

    def test_list_sets_with_illegal_arguments(self, oai_client, xml_validator):
        """Test ListSets with illegal arguments."""
        response = oai_client.get(self.oai_url, {
            "verb": "ListSets",
            "metadataPrefix": "oai_dc"  # Illegal for ListSets
        })

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        assert code == "badArgument"

    # ============================================================================
    # LISTIDENTIFIERS VERB TESTS
    # ============================================================================

    def test_list_identifiers_success(self, oai_client, sample_resources, xml_validator, mock_canonical_graph_service):
        """Test successful ListIdentifiers request."""
        response = oai_client.get(self.oai_url, {
            "verb": "ListIdentifiers",
            "metadataPrefix": "oai_dc"
        })

        assert response.status_code == 200
        assert xml_validator.validate_oai_response(response.content.decode())

        content = response.content.decode()
        assert "<ListIdentifiers>" in content
        assert "<header>" in content
        assert "<identifier>" in content
        assert "<datestamp>" in content

        # Should only include public approved resources
        record_count = xml_validator.count_records(response.content.decode())
        assert record_count == 6  # 5 from test_univ + 1 from research_inst

    def test_list_identifiers_missing_metadata_prefix(self, oai_client, xml_validator):
        """Test ListIdentifiers without required metadataPrefix."""
        response = oai_client.get(self.oai_url, {"verb": "ListIdentifiers"})

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        assert code == "badArgument"
        assert "metadataPrefix is required" in message

    def test_list_identifiers_invalid_metadata_prefix(self, oai_client, xml_validator):
        """Test ListIdentifiers with unsupported metadataPrefix."""
        response = oai_client.get(self.oai_url, {
            "verb": "ListIdentifiers",
            "metadataPrefix": "unsupported_format"
        })

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        assert code == "cannotDisseminateFormat"

    def test_list_identifiers_with_set_filter(self, oai_client, sample_resources, xml_validator, mock_canonical_graph_service):
        """Test ListIdentifiers with set parameter."""
        response = oai_client.get(self.oai_url, {
            "verb": "ListIdentifiers",
            "metadataPrefix": "oai_dc",
            "set": "test_univ"
        })

        assert response.status_code == 200
        assert xml_validator.validate_oai_response(response.content.decode())

        # Should only include resources from test_univ organization
        record_count = xml_validator.count_records(response.content.decode())
        assert record_count == 5

    def test_list_identifiers_with_date_filter(self, oai_client, sample_resources, xml_validator, mock_canonical_graph_service):
        """Test ListIdentifiers with from/until date parameters."""
        response = oai_client.get(self.oai_url, {
            "verb": "ListIdentifiers",
            "metadataPrefix": "oai_dc",
            "from": "2023-01-02",
            "until": "2023-01-04"
        })

        assert response.status_code == 200
        assert xml_validator.validate_oai_response(response.content.decode())

    def test_list_identifiers_invalid_date_format(self, oai_client, xml_validator):
        """Test ListIdentifiers with invalid date format."""
        response = oai_client.get(self.oai_url, {
            "verb": "ListIdentifiers",
            "metadataPrefix": "oai_dc",
            "from": "invalid-date"
        })

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        assert code == "badArgument"
        assert "Invalid 'from' parameter" in message

    def test_list_identifiers_from_after_until(self, oai_client, xml_validator):
        """Test ListIdentifiers with from date after until date."""
        response = oai_client.get(self.oai_url, {
            "verb": "ListIdentifiers",
            "metadataPrefix": "oai_dc",
            "from": "2023-01-10",
            "until": "2023-01-01"
        })

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        assert code == "badArgument"
        assert "from' date must be earlier than 'until' date" in message

    def test_list_identifiers_no_records_match(self, oai_client, xml_validator):
        """Test ListIdentifiers when no records match criteria."""
        response = oai_client.get(self.oai_url, {
            "verb": "ListIdentifiers",
            "metadataPrefix": "oai_dc",
            "from": "2050-01-01"  # Future date
        })

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        assert code == "noRecordsMatch"

    def test_list_identifiers_with_resumption_token(self, oai_client, large_dataset, xml_validator, mock_canonical_graph_service):
        """Test ListIdentifiers with resumption token."""
        # First request to get resumption token
        response = oai_client.get(self.oai_url, {
            "verb": "ListIdentifiers",
            "metadataPrefix": "oai_dc"
        })

        assert response.status_code == 200
        token = xml_validator.get_resumption_token(response.content.decode())

        if token:  # If pagination occurred
            # Request next page with token
            response2 = oai_client.get(self.oai_url, {
                "verb": "ListIdentifiers",
                "resumptionToken": token
            })

            assert response2.status_code == 200
            assert xml_validator.validate_oai_response(response2.content.decode())

    def test_list_identifiers_resumption_token_exclusive(self, oai_client, xml_validator):
        """Test that resumptionToken cannot be combined with other arguments."""
        response = oai_client.get(self.oai_url, {
            "verb": "ListIdentifiers",
            "resumptionToken": "dummy_token",
            "metadataPrefix": "oai_dc"
        })

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        assert code == "badArgument"
        assert "resumptionToken cannot be combined with other arguments" in message

    def test_list_identifiers_invalid_resumption_token(self, oai_client, xml_validator):
        """Test ListIdentifiers with invalid resumption token."""
        response = oai_client.get(self.oai_url, {
            "verb": "ListIdentifiers",
            "resumptionToken": "invalid_token"
        })

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        assert code == "badResumptionToken"

    # ============================================================================
    # LISTRECORDS VERB TESTS
    # ============================================================================

    def test_list_records_success(self, oai_client, sample_resources, xml_validator, mock_canonical_graph_service):
        """Test successful ListRecords request."""
        response = oai_client.get(self.oai_url, {
            "verb": "ListRecords",
            "metadataPrefix": "oai_dc"
        })

        assert response.status_code == 200
        assert xml_validator.validate_oai_response(response.content.decode())

        content = response.content.decode()
        assert "<ListRecords>" in content
        assert "<record>" in content
        assert "<header>" in content
        assert "<metadata" in content

        # Check Dublin Core metadata structure
        assert 'xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/"' in content
        assert 'xmlns:dc="http://purl.org/dc/elements/1.1/"' in content

    def test_list_records_mets_format(self, oai_client, sample_resources, xml_validator, mock_canonical_graph_service):
        """Test ListRecords with METS metadata format."""
        response = oai_client.get(self.oai_url, {
            "verb": "ListRecords",
            "metadataPrefix": "mets"
        })

        assert response.status_code == 200
        assert xml_validator.validate_oai_response(response.content.decode())

        content = response.content.decode()
        assert "<ListRecords>" in content
        # Note: METS XML structure would be checked in format-specific tests

    def test_list_records_missing_metadata_prefix(self, oai_client, xml_validator):
        """Test ListRecords without required metadataPrefix."""
        response = oai_client.get(self.oai_url, {"verb": "ListRecords"})

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        assert code == "badArgument"
        assert "metadataPrefix is required" in message

    def test_list_records_inclusive_datestamp_range(self, oai_client, sample_resources, xml_validator, mock_canonical_graph_service):
        """Ensure from/until datestamps include records within the same second."""
        resource = sample_resources[0]
        target_ts = timezone.now().replace(microsecond=654321)
        resource.__class__.objects.filter(pk=resource.pk).update(updated_at=target_ts)

        datestamp = target_ts.strftime("%Y-%m-%dT%H:%M:%SZ")
        identifier = f"oai:arkumu:resource:{quote(resource.uri)}"

        response = oai_client.get(self.oai_url, {
            "verb": "ListRecords",
            "metadataPrefix": "oai_dc",
            "from": datestamp,
            "until": datestamp
        })

        assert response.status_code == 200
        content = response.content.decode()
        assert '<error code="noRecordsMatch"' not in content
        assert identifier in content
        assert xml_validator.validate_oai_response(content)

    # ============================================================================
    # GETRECORD VERB TESTS
    # ============================================================================

    def test_get_record_success(self, oai_client, sample_resources, xml_validator, mock_canonical_graph_service):
        """Test successful GetRecord request."""
        resource = sample_resources[0]  # First public resource
        identifier = f"oai:arkumu:resource:{quote(resource.uri)}"

        snapshot = self._snapshot_record(resource)
        with patch('arkumu.oaipmh.views._get_snapshot_record', return_value=snapshot):
            response = oai_client.get(self.oai_url, {
                "verb": "GetRecord",
                "identifier": identifier,
                "metadataPrefix": "oai_dc"
            })

        assert response.status_code == 200

        content = response.content.decode()
        assert "<GetRecord>" in content
        assert "<record>" in content
        assert "<header>" in content
        assert "<metadata" in content
        assert identifier in content
        assert 'ns0:' not in content

        parser = LET.XMLParser(ns_clean=True)
        root = LET.fromstring(response.content, parser=parser)
        metadata_elem = root.find('.//{http://www.openarchives.org/OAI/2.0/}metadata')
        assert metadata_elem is not None
        dc_container = metadata_elem.find('.//{http://www.openarchives.org/OAI/2.0/oai_dc/}dc')
        assert dc_container is not None
        assert dc_container.prefix == 'oai_dc'
        assert all(child.prefix in {None, 'dc', 'dcterms'} for child in dc_container.iterchildren())

        oai_dc_schema = _load_schema("http://www.openarchives.org/OAI/2.0/oai_dc.xsd")
        dc_subset = LET.Element(dc_container.tag, nsmap=dc_container.nsmap)
        for child in dc_container:
            qname = LET.QName(child.tag)
            if qname.namespace == 'http://purl.org/dc/elements/1.1/' and qname.localname in SIMPLE_DC_TERMS:
                clone = LET.SubElement(dc_subset, child.tag, child.attrib)
                clone.text = child.text
        # Validate the Dublin Core subset against the official schema
        oai_dc_schema.assertValid(LET.ElementTree(dc_subset))

    def test_get_record_mets_format(self, oai_client, sample_resources, xml_validator, mock_canonical_graph_service):
        """Test GetRecord with METS format."""
        resource = sample_resources[0]
        identifier = f"oai:arkumu:resource:{quote(resource.uri)}"

        snapshot = self._snapshot_record(resource)
        with patch('arkumu.oaipmh.views._get_snapshot_record', return_value=snapshot):
            response = oai_client.get(self.oai_url, {
                "verb": "GetRecord",
                "identifier": identifier,
                "metadataPrefix": "mets"
            })

        assert response.status_code == 200
        assert 'ns0:' not in response.content.decode()

        parser = LET.XMLParser(ns_clean=True)
        root = LET.fromstring(response.content, parser=parser)
        metadata_elem = root.find('.//{http://www.openarchives.org/OAI/2.0/}metadata')
        assert metadata_elem is not None
        mets_root = metadata_elem.find(f'.//{{{METS_NS}}}mets')
        assert mets_root is not None
        assert mets_root.prefix == 'mets'
        schema_location = mets_root.get(f'{{{XSI_NS}}}schemaLocation')
        assert schema_location == f"{METS_NS} {METS_SCHEMA_URL}"

        mets_schema = _load_schema(METS_SCHEMA_URL)
        ordered_mets = LET.Element(mets_root.tag, mets_root.attrib, nsmap=mets_root.nsmap)
        buckets = {name: [] for name in ('metsHdr', 'dmdSec', 'amdSec', 'fileSec', 'structMap', 'structLink', 'behaviorSec')}
        others = []
        for child in mets_root:
            local = LET.QName(child.tag).localname
            clone = LET.fromstring(LET.tostring(child))
            if local in buckets:
                buckets[local].append(clone)
            else:
                others.append(clone)

        for name in ('metsHdr', 'dmdSec', 'amdSec', 'fileSec', 'structMap', 'structLink', 'behaviorSec'):
            for element in buckets[name]:
                ordered_mets.append(element)
        for element in others:
            ordered_mets.append(element)

        mets_schema.assertValid(LET.ElementTree(ordered_mets))

    def test_post_identify_supported(self, oai_client):
        """The endpoint should accept POST Identify requests without CSRF errors."""
        response = oai_client.post(self.oai_url, {"verb": "Identify"})

        assert response.status_code == 200
        assert "<Identify>" in response.content.decode()

    def test_post_get_record_supported(self, oai_client, sample_resources, xml_validator, mock_canonical_graph_service):
        """POST requests should work for GetRecord as well."""
        resource = sample_resources[0]
        identifier = f"oai:arkumu:resource:{quote(resource.uri)}"

        response = oai_client.post(self.oai_url, {
            "verb": "GetRecord",
            "identifier": identifier,
            "metadataPrefix": "oai_dc"
        })

        assert response.status_code == 200
        assert xml_validator.validate_oai_response(response.content.decode())
        assert identifier in response.content.decode()

    def test_get_record_missing_identifier(self, oai_client, xml_validator):
        """Test GetRecord without required identifier."""
        response = oai_client.get(self.oai_url, {
            "verb": "GetRecord",
            "metadataPrefix": "oai_dc"
        })

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        assert code == "badArgument"
        assert "identifier and metadataPrefix are required" in message

    def test_get_record_missing_metadata_prefix(self, oai_client, xml_validator):
        """Test GetRecord without required metadataPrefix."""
        response = oai_client.get(self.oai_url, {
            "verb": "GetRecord",
            "identifier": "oai:arkumu:resource:https://test.example.com"
        })

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        assert code == "badArgument"
        assert "identifier and metadataPrefix are required" in message

    def test_get_record_invalid_identifier(self, oai_client, xml_validator):
        """Test GetRecord with non-existent identifier."""
        response = oai_client.get(self.oai_url, {
            "verb": "GetRecord",
            "identifier": "oai:arkumu:resource:https://nonexistent.example.com",
            "metadataPrefix": "oai_dc"
        })

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        assert code == "idDoesNotExist"

    def test_get_record_private_resource(self, oai_client, sample_resources, xml_validator):
        """Test GetRecord with private resource (should not be accessible)."""
        # Private resource is at index 6 in sample_resources
        private_resource_uri = "https://test.example.com/private/1"
        identifier = f"oai:arkumu:resource:{quote(private_resource_uri)}"

        response = oai_client.get(self.oai_url, {
            "verb": "GetRecord",
            "identifier": identifier,
            "metadataPrefix": "oai_dc"
        })

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        assert code == "idDoesNotExist"

    @pytest.mark.django_db
    def test_get_record_dc_excludes_file_paths(self, oai_client, sample_resources, mock_canonical_graph_service):
        """GetRecord oai_dc should not list per-file identifiers/relations."""
        from arkumu.storage.models.s3_file_objects import S3FileObject
        from unittest.mock import patch, Mock
        resource = sample_resources[0]
        # Create related file
        S3FileObject.objects.create(
            file_name="test1.txt",
            s3_key="org/test1.txt",
            file_size_bytes=123,
            content_type="text/plain",
            related_resource=resource,
            s3_url="https://s3.example/org/test1.txt",
            status='completed'
        )

        # Patch export service used in views
        with patch('arkumu.storage.services.rosetta_export_service.RosettaExportService') as mock_export_cls, \
             patch('arkumu.oaipmh.views.snapshot_service') as mock_snapshot_service, \
             patch('arkumu.oaipmh.views.oai_cache') as mock_oai_cache:
            mock_export = Mock()
            mock_export.prepare_file_for_harvest.return_value = {
                'access_method': 'presigned_url',
                'url': 'https://download.example/test1.txt'
            }
            mock_export_cls.return_value = mock_export

            mock_oai_cache.get_cached_record.return_value = None
            mock_oai_cache.get_cached_page.return_value = None

            mock_record = ProjectRecord(
                subject_id=resource.uri,
                uri=resource.uri,
                digital_objects=[
                    ProjectDigitalObject(
                        path='org/test1.txt',
                        access_url='https://download.example/test1.txt',
                        storage_key='org/test1.txt',
                        content_type='text/plain',
                    )
                ],
            )

            mock_snapshot_service.get_record_by_uri.return_value = mock_record
            mock_snapshot_service.get_cross_institutional_snapshot.return_value = Mock(
                projects=[mock_record],
                generated_at=timezone.now(),
            )

            identifier = f"oai:arkumu:resource:{quote(resource.uri)}"
            response = oai_client.get(
                "/oai/",
                {"verb": "GetRecord", "identifier": identifier, "metadataPrefix": "oai_dc"},
            )

        assert response.status_code == 200
        content = response.content.decode()
        assert 'https://download.example/test1.txt' not in content
        assert 'org/test1.txt' not in content
        assert '<dc:format>text/plain</dc:format>' in content

    @pytest.mark.django_db
    def test_get_record_mets_includes_flocat_urls(self, oai_client, sample_resources):
        """GetRecord mets should include FLocat xlink:href for content files when present."""
        from arkumu.storage.models.s3_file_objects import S3FileObject
        from unittest.mock import patch, Mock
        from lxml import etree as ET

        resource = sample_resources[0]
        # Create related file
        S3FileObject.objects.create(
            file_name="test1.txt",
            s3_key="org/test1.txt",
            file_size_bytes=1024,
            content_type="text/plain",
            related_resource=resource,
            s3_url="https://s3.example/org/test1.txt",
            status='completed'
        )

        # Patch export service used in METSSerializer
        with patch('arkumu.storage.services.rosetta_export_service.RosettaExportService') as mock_export_cls, \
             patch('arkumu.oaipmh.views.snapshot_service') as mock_snapshot_service, \
             patch('arkumu.oaipmh.views.oai_cache') as mock_oai_cache:
            mock_export = Mock()
            mock_export.prepare_file_for_harvest.return_value = {
                'access_method': 'presigned_url',
                'url': 'https://download.example/test1.txt'
            }
            mock_export_cls.return_value = mock_export

            mock_oai_cache.get_cached_record.return_value = None
            mock_oai_cache.get_cached_page.return_value = None

            mock_record = ProjectRecord(
                subject_id=resource.uri,
                uri=resource.uri,
                digital_objects=[
                    ProjectDigitalObject(
                        path='org/test1.txt',
                        access_url='https://download.example/test1.txt',
                        storage_key='org/test1.txt',
                        content_type='text/plain',
                    )
                ],
            )

            mock_snapshot_service.get_record_by_uri.return_value = mock_record
            mock_snapshot_service.get_cross_institutional_snapshot.return_value = Mock(
                projects=[mock_record],
                generated_at=timezone.now(),
            )

            identifier = f"oai:arkumu:resource:{quote(resource.uri)}"
            response = oai_client.get(
                "/oai/",
                {"verb": "GetRecord", "identifier": identifier, "metadataPrefix": "mets"},
            )

        assert response.status_code == 200
        # Parse and check for FLocat xlink:href
        root = ET.fromstring(response.content)
        # Find FLocat
        flocats = root.findall(f'.//{{{views.METS_NS}}}FLocat')
        expected_href = 'org/test1.txt'
        assert any(
            f.get('{http://www.w3.org/1999/xlink}href') == expected_href
            for f in flocats
        )

    @pytest.mark.django_db
    def test_get_record_mets_only_includes_preservation_master_files(self, oai_client, sample_resources):
        """Ensure METS payload exposes only preservation master representations."""

        resource = sample_resources[0]

        with patch('arkumu.oaipmh.views.snapshot_service') as mock_snapshot_service, \
             patch('arkumu.oaipmh.views.oai_cache') as mock_oai_cache:
            mock_oai_cache.get_cached_record.return_value = None
            mock_oai_cache.get_cached_page.return_value = None

            mock_record = ProjectRecord(
                subject_id=resource.uri,
                uri=resource.uri,
                digital_objects=[
                    ProjectDigitalObject(
                        path='objects/preservation/master.tif',
                        storage_key='org/preservation/master.tif',
                        file_name='master.tif',
                        content_type='image/tiff',
                    ),
                    ProjectDigitalObject(
                        path='objects/preview/preview.jpg',
                        storage_key='org/preview/preview.jpg',
                        file_name='preview.jpg',
                        content_type='image/jpeg',
                    ),
                ],
            )

            mock_snapshot_service.get_record_by_uri.return_value = mock_record
            mock_snapshot_service.get_cross_institutional_snapshot.return_value = Mock(
                projects=[mock_record],
                generated_at=timezone.now(),
            )

            identifier = f"oai:arkumu:resource:{quote(resource.uri)}"
            response = oai_client.get(
                "/oai/",
                {"verb": "GetRecord", "identifier": identifier, "metadataPrefix": "mets"},
            )

        assert response.status_code == 200
        root = ET.fromstring(response.content)
        file_groups = root.findall(f'.//{{{views.METS_NS}}}fileGrp')
        assert len(file_groups) == 1
        assert file_groups[0].get('USE') == 'VIEW'

        flocat_hrefs = {
            flocat.get('{http://www.w3.org/1999/xlink}href')
            for flocat in root.findall(f'.//{{{views.METS_NS}}}FLocat')
        }
        assert 'org/preservation/master.tif' in flocat_hrefs
        assert all('preview' not in (href or '') for href in flocat_hrefs)

    @pytest.mark.django_db
    def test_get_record_mets_returns_error_when_validation_fails(self, oai_client, sample_resources, xml_validator, mock_canonical_graph_service):
        """When DNX validation fails the METS record is not disseminated."""

        resource = sample_resources[0]

        with patch('arkumu.oaipmh.validation.mets_validator.rosetta_mets_validator.validate_metadata_element', return_value=Mock(is_valid=False)) as mock_validate, \
             patch('arkumu.oaipmh.views._fallback_record_from_storage', return_value=None), \
             patch('arkumu.oaipmh.views.snapshot_service') as mock_snapshot_service, \
             patch('arkumu.oaipmh.views.oai_cache') as mock_oai_cache:
            mock_oai_cache.get_cached_record.return_value = None
            mock_oai_cache.get_cached_page.return_value = None

            mock_record = ProjectRecord(
                subject_id=resource.uri,
                uri=resource.uri,
                digital_objects=[
                    ProjectDigitalObject(
                        path='objects/preservation/master.tif',
                        storage_key='org/preservation/master.tif',
                        file_name='master.tif',
                        content_type='image/tiff',
                    ),
                ],
            )

            mock_snapshot_service.get_record_by_uri.return_value = mock_record
            mock_snapshot_service.get_cross_institutional_snapshot.return_value = Mock(
                projects=[mock_record],
                generated_at=timezone.now(),
            )

            identifier = f"oai:arkumu:resource:{quote(resource.uri)}"
            response = oai_client.get(
                "/oai/",
                {"verb": "GetRecord", "identifier": identifier, "metadataPrefix": "mets"},
            )

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        if code != "idDoesNotExist":
            pytest.fail(f"Unexpected OAI error {code}: {message}")
        assert "METS dissemination" in message
        mock_validate.assert_called()

    @pytest.mark.django_db
    def _setup_rosetta_project(
        self,
        *,
        org_code: str,
        rosetta_path: str,
        resource_uri: str,
        title: str,
        settings,
        tmp_path,
    ):
        from arkumu.metadata.models.resource import Resource, PublicAccessLevel
        from arkumu.users.models import Organization
        from arkumu.oaipmh import path_mapping

        org = Organization.objects.create(
            name=org_code.upper(),
            code=org_code,
            domain=f"{org_code}.example",
            is_active=True,
        )
        resource = Resource.objects.create(
            uri=resource_uri,
            organization=org,
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True,
            updated_at=timezone.now(),
        )

        import hashlib
        checksum_value = hashlib.sha256(rosetta_path.encode("utf-8")).hexdigest()

        mapping_file = tmp_path / f"{org_code}_paths.txt"
        mapping_file.write_text(f"{rosetta_path}\n", encoding="utf-8")

        files_config = dict(getattr(settings, 'OAI_EXTERNAL_PATH_FILES', {}))
        files_config[org_code] = str(mapping_file)
        settings.OAI_EXTERNAL_PATH_FILES = files_config

        roots_config = dict(getattr(settings, 'OAI_EXTERNAL_ROSETTA_ROOTS', {}))
        if org_code == 'khm':
            roots_config['khm'] = '/rosetta/khm/sandbox/input/arkumu/daten'
        if org_code == 'hmt':
            roots_config['hmt'] = '/rosetta/hfmt/sandbox/input/arkumu'
        settings.OAI_EXTERNAL_ROSETTA_ROOTS = roots_config

        prefixes_config = dict(getattr(settings, 'OAI_EXTERNAL_PATH_PREFIXES', {}))
        prefixes_config.setdefault('hmt', ['/Volumes/18TB1'])
        settings.OAI_EXTERNAL_PATH_PREFIXES = prefixes_config

        path_mapping._load_index.cache_clear()

        record = ProjectRecord(
            subject_id=f"snapshot-{org_code}-1",
            uri=resource_uri,
            title=title,
            institution=ProjectInstitution(label=org_code.upper(), code=org_code),
            digital_objects=[
                ProjectDigitalObject(
                    path=rosetta_path,
                    file_name=rosetta_path.split('/')[-1],
                    content_type='image/tiff',
                    checksum=checksum_value,
                    checksum_algorithm='sha256',
                    checksum_provenance='metadata',
                )
            ],
        )

        return resource, record, checksum_value

    @pytest.mark.django_db
    def test_list_records_khm_uses_rosetta_paths(
        self,
        oai_client,
        mock_canonical_graph_service,
        settings,
        tmp_path,
    ):
        settings.OAI_ROSETTA_HARVESTABLE_ORGS = ('khm',)
        settings.OAI_S3_HARVESTABLE_ORGS = ('fuk', 'det', 'rsh')

        rosetta_path = "/rosetta/khm/sandbox/input/arkumu/daten/object_master.tif"
        resource, record, checksum = self._setup_rosetta_project(
            org_code='khm',
            rosetta_path=rosetta_path,
            resource_uri="https://arkumu.org/entities/projekt/9001",
            title="KHM Rosetta Project",
            settings=settings,
            tmp_path=tmp_path,
        )
        snapshot = ProjectSnapshot(projects=[record])

        with patch('arkumu.oaipmh.views.snapshot_service') as mock_snapshot_service, \
             patch('arkumu.oaipmh.views.oai_cache') as mock_oai_cache:
            mock_oai_cache.get_cached_record.return_value = None
            mock_oai_cache.get_cached_page.return_value = None
            mock_oai_cache.cache_page.return_value = None
            mock_oai_cache.cache_record.return_value = None

            mock_snapshot_service.get_cross_institutional_snapshot.return_value = snapshot
            mock_snapshot_service.get_record_by_uri.side_effect = lambda uri: record if uri == resource.uri else None
            mock_snapshot_service.refresh_cross_institutional_snapshot.return_value = snapshot

            response = oai_client.get(
                self.oai_url,
                {"verb": "ListRecords", "metadataPrefix": "mets", "set": "khm"},
            )

        assert response.status_code == 200
        root = ET.fromstring(response.content)
        ns = {"mets": METS_NS, "xlink": XLINK_NS}
        hrefs = {
            flocat.get(f"{{{XLINK_NS}}}href")
            for flocat in root.findall('.//mets:FLocat', ns)
        }
        assert rosetta_path in hrefs, hrefs

        target_file = None
        for mets_file in root.findall('.//mets:file', ns):
            flocat = mets_file.find('mets:FLocat', ns)
            if flocat is None:
                continue
            href = flocat.get(f"{{{XLINK_NS}}}href")
            if href == rosetta_path:
                target_file = mets_file
                break

        assert target_file is not None
        assert target_file.get('CHECKSUMTYPE') is None
        assert target_file.get('CHECKSUM') is None

        dnx_ns = {"dnx": "http://www.exlibrisgroup.com/dps/dnx"}
        amd_id = target_file.get('ID')
        amd_sec = root.find(f".//mets:amdSec[@ID='{amd_id}-amd']", ns)
        assert amd_sec is not None
        fixity_value = amd_sec.find(".//dnx:key[@id='fixityValue']", {**ns, **dnx_ns})
        assert fixity_value is not None
        assert fixity_value.text == checksum
        set_specs = {header.text for header in root.findall('.//{http://www.openarchives.org/OAI/2.0/}setSpec')}
        assert set_specs == {'khm'}

    @pytest.mark.django_db
    def test_list_records_hmt_uses_rosetta_paths(
        self,
        oai_client,
        mock_canonical_graph_service,
        settings,
        tmp_path,
    ):
        settings.OAI_ROSETTA_HARVESTABLE_ORGS = ('hmt',)
        settings.OAI_S3_HARVESTABLE_ORGS = ('fuk', 'det', 'rsh')

        rosetta_path = "/rosetta/hfmt/sandbox/input/arkumu/object_master.wav"
        resource, record, checksum = self._setup_rosetta_project(
            org_code='hmt',
            rosetta_path=rosetta_path,
            resource_uri="https://arkumu.org/entities/projekt/9002",
            title="HMT Audio Project",
            settings=settings,
            tmp_path=tmp_path,
        )
        snapshot = ProjectSnapshot(projects=[record])

        with patch('arkumu.oaipmh.views.snapshot_service') as mock_snapshot_service, \
             patch('arkumu.oaipmh.views.oai_cache') as mock_oai_cache:
            mock_oai_cache.get_cached_record.return_value = None
            mock_oai_cache.get_cached_page.return_value = None
            mock_oai_cache.cache_page.return_value = None
            mock_oai_cache.cache_record.return_value = None

            mock_snapshot_service.get_cross_institutional_snapshot.return_value = snapshot
            mock_snapshot_service.get_record_by_uri.side_effect = lambda uri: record if uri == resource.uri else None
            mock_snapshot_service.refresh_cross_institutional_snapshot.return_value = snapshot

            response = oai_client.get(
                self.oai_url,
                {"verb": "ListRecords", "metadataPrefix": "mets", "set": "hmt"},
            )

        assert response.status_code == 200
        root = ET.fromstring(response.content)
        ns = {"mets": METS_NS, "xlink": XLINK_NS}
        hrefs = {
            flocat.get(f"{{{XLINK_NS}}}href")
            for flocat in root.findall('.//mets:FLocat', ns)
        }
        assert rosetta_path in hrefs, hrefs
        set_specs = {header.text for header in root.findall('.//{http://www.openarchives.org/OAI/2.0/}setSpec')}
        assert set_specs == {'hmt'}

    @pytest.mark.django_db
    def test_list_records_set_without_matching_resources_returns_empty(
        self,
        oai_client,
        mock_canonical_graph_service,
        settings,
        tmp_path,
    ):
        settings.OAI_ROSETTA_HARVESTABLE_ORGS = ('khm',)
        settings.OAI_S3_HARVESTABLE_ORGS = ('fuk',)

        rosetta_path = "/rosetta/khm/sandbox/input/arkumu/daten/object_master.tif"
        _, khm_record, _ = self._setup_rosetta_project(
            org_code='khm',
            rosetta_path=rosetta_path,
            resource_uri="https://arkumu.org/entities/projekt/9001",
            title="KHM Rosetta Project",
            settings=settings,
            tmp_path=tmp_path,
        )

        fuk_resource, fuk_record, _ = self._setup_rosetta_project(
            org_code='fuk',
            rosetta_path='s3://fuk/object_master.tif',
            resource_uri="https://arkumu.org/entities/projekt/1001",
            title="FUK Project",
            settings=settings,
            tmp_path=tmp_path,
        )

        # KHM resource removed from DB to simulate missing metadata entry
        from arkumu.metadata.models.resource import Resource
        Resource.objects.filter(uri=khm_record.uri).delete()

        snapshot = ProjectSnapshot(projects=[khm_record, fuk_record])

        with patch('arkumu.oaipmh.views.snapshot_service') as mock_snapshot_service, \
             patch('arkumu.oaipmh.views.oai_cache') as mock_oai_cache:
            mock_oai_cache.get_cached_record.return_value = None
            mock_oai_cache.get_cached_page.return_value = None

            mock_snapshot_service.get_cross_institutional_snapshot.return_value = snapshot
            mock_snapshot_service.get_record_by_uri.side_effect = lambda uri: (
                khm_record if uri == khm_record.uri else fuk_record if uri == fuk_record.uri else None
            )
            mock_snapshot_service.refresh_cross_institutional_snapshot.return_value = snapshot

            response = oai_client.get(
                self.oai_url,
                {"verb": "ListRecords", "metadataPrefix": "mets", "set": "khm"},
            )

        assert response.status_code == 200
        root = ET.fromstring(response.content)
        error = root.find('{http://www.openarchives.org/OAI/2.0/}error')
        assert error is not None
        assert error.get('code') == 'noRecordsMatch'

    # ============================================================================
    # GENERAL ERROR TESTS
    # ============================================================================

    def test_missing_verb(self, oai_client, xml_validator):
        """Test request without verb parameter."""
        response = oai_client.get(self.oai_url)

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        assert code == "badVerb"
        assert "Missing verb" in message

    def test_invalid_verb(self, oai_client, xml_validator):
        """Test request with invalid verb."""
        response = oai_client.get(self.oai_url, {"verb": "InvalidVerb"})

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        assert code == "badVerb"
        assert "Illegal verb: InvalidVerb" in message

    def test_response_date_present(self, oai_client):
        """Test that all responses include responseDate element."""
        response = oai_client.get(self.oai_url, {"verb": "Identify"})

        assert response.status_code == 200
        content = response.content.decode()
        assert "<responseDate>" in content
        # Date should be in ISO format
        import re
        date_pattern = r'<responseDate>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z</responseDate>'
        assert re.search(date_pattern, content)

    def test_request_element_present(self, oai_client):
        """Test that all responses include request element with correct URL."""
        response = oai_client.get(self.oai_url, {"verb": "Identify"})

        assert response.status_code == 200
        content = response.content.decode()
        root = ET.fromstring(response.content)
        ns = {"oai": "http://www.openarchives.org/OAI/2.0/"}
        request_elem = root.find("oai:request", ns)
        assert request_elem is not None
        assert request_elem.text == f"http://testserver{self.oai_url}"
        assert request_elem.get("verb") == "Identify"

    def test_xml_declaration_and_content_type(self, oai_client):
        """Test proper XML declaration and Content-Type header."""
        response = oai_client.get(self.oai_url, {"verb": "Identify"})

        assert response.status_code == 200
        assert response["Content-Type"] == "text/xml"

        content = response.content.decode()
        # ElementTree uses single quotes in XML declaration
        assert content.startswith("<?xml version='1.0' encoding='utf-8'?>")

    def test_oai_pmh_namespace(self, oai_client):
        """Test that OAI-PMH namespace is correctly declared."""
        response = oai_client.get(self.oai_url, {"verb": "Identify"})

        assert response.status_code == 200
        content = response.content.decode()
        assert 'xmlns="http://www.openarchives.org/OAI/2.0/"' in content
        assert 'xsi:schemaLocation' in content
        assert 'http://www.openarchives.org/OAI/2.0/OAI-PMH.xsd' in content
