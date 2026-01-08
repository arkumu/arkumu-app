"""
Tests for OAI-PMH security audit signals (publication and snapshot record deletion logging).
"""
import pytest
from django.utils import timezone

from arkumu.users.models import Organization
from arkumu.oaipmh.models import OAIProjectPublication, OAISnapshotRecord
from arkumu.metadata.models.resource import Resource


@pytest.fixture
def test_organization(db):
    """Create a test organization for OAI models."""
    return Organization.objects.create(
        name="Security Test Org",
        code="sec_test",
        domain="security.test.org",
        is_active=True,
    )


@pytest.fixture
def test_resource(db, test_organization):
    """Create a test Resource for OAI publication tests."""
    return Resource.objects.create(
        uri="http://arkumu.org/entities/projekt/delete_test_1",
        resource_type="ENTITY",
        organization=test_organization,
    )


@pytest.mark.django_db
class TestPublicationDeletionLogging:
    """Tests for OAI publication deletion security logging."""

    def test_publication_deletion_logs_warning(self, caplog, test_organization, test_resource):
        """Test that publication deletion is logged as warning."""
        publication = OAIProjectPublication.objects.create(
            project=test_resource,
            is_approved=True,
        )
        publication_pk = publication.pk

        with caplog.at_level("WARNING", logger="arkumu.security"):
            publication.delete()

        assert "PUBLICATION_DELETED" in caplog.text
        assert "delete_test_1" in caplog.text
        assert test_organization.code in caplog.text
        assert f"pk={publication_pk}" in caplog.text

    def test_publication_deletion_logs_institution(self, caplog, test_organization):
        """Test that institution code is included in deletion log."""
        special_org = Organization.objects.create(
            name="Special Inst",
            code="special_inst",
            domain="special.test.org",
            is_active=True,
        )
        resource = Resource.objects.create(
            uri="http://arkumu.org/entities/projekt/inst_test",
            resource_type="ENTITY",
            organization=special_org,
        )
        publication = OAIProjectPublication.objects.create(
            project=resource,
            is_approved=True,
        )

        with caplog.at_level("WARNING", logger="arkumu.security"):
            publication.delete()

        assert "PUBLICATION_DELETED" in caplog.text
        assert "institution=special_inst" in caplog.text

    def test_bulk_publication_deletion_logs_each(self, caplog, test_organization):
        """Test that bulk deletion logs each publication separately."""
        publications = []
        for i in range(3):
            resource = Resource.objects.create(
                uri=f"http://arkumu.org/entities/projekt/bulk_{i}",
                resource_type="ENTITY",
                organization=test_organization,
            )
            pub = OAIProjectPublication.objects.create(
                project=resource,
                is_approved=True,
            )
            publications.append(pub)

        with caplog.at_level("WARNING", logger="arkumu.security"):
            for pub in publications:
                pub.delete()

        # Each deletion should be logged
        assert caplog.text.count("PUBLICATION_DELETED") == 3


@pytest.mark.django_db
class TestSnapshotRecordDeletionLogging:
    """Tests for OAI snapshot record deletion security logging."""

    def test_snapshot_record_deletion_logs_warning(self, caplog, test_organization):
        """Test that snapshot record deletion is logged as warning."""
        record = OAISnapshotRecord.objects.create(
            position=1,
            uri="http://arkumu.org/entities/projekt/snapshot_test_1",
            datestamp=timezone.now(),
            organization=test_organization,
            header_xml="<header/>",
            metadata_dc_xml="<dc/>",
            metadata_mets_xml="<mets/>",
        )
        record_pk = record.pk

        with caplog.at_level("WARNING", logger="arkumu.security"):
            record.delete()

        assert "SNAPSHOT_RECORD_DELETED" in caplog.text
        assert "snapshot_test_1" in caplog.text
        assert test_organization.code in caplog.text
        assert f"pk={record_pk}" in caplog.text

    def test_snapshot_record_deletion_logs_institution(self, caplog, test_organization):
        """Test that institution code is included in snapshot record deletion log."""
        snapshot_org = Organization.objects.create(
            name="Snapshot Inst",
            code="snapshot_inst",
            domain="snapshot.test.org",
            is_active=True,
        )
        record = OAISnapshotRecord.objects.create(
            position=1,
            uri="http://arkumu.org/entities/projekt/snap_inst_test",
            datestamp=timezone.now(),
            organization=snapshot_org,
            header_xml="<header/>",
            metadata_dc_xml="<dc/>",
            metadata_mets_xml="<mets/>",
        )

        with caplog.at_level("WARNING", logger="arkumu.security"):
            record.delete()

        assert "SNAPSHOT_RECORD_DELETED" in caplog.text
        assert "institution=snapshot_inst" in caplog.text
