from datetime import datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace

import pytest

from django.utils import timezone

from arkumu.catalog.services.project_views import ProjectURIs
from arkumu.metadata.models.resource import Resource, ResourceType, PublicAccessLevel
from arkumu.metadata.models.triples import Triple
from arkumu.oaipmh.models import OAIProjectMediaLink, OAIProjectPublication
from arkumu.oaipmh.oai_project_tailored import OAIProjectBuilderTailored
from arkumu.oaipmh.views import tailored
from arkumu.oaipmh.views import projects as project_views
from arkumu.projects import ProjectDigitalObject, ProjectInstitution, ProjectRecord
from arkumu.projects.services.snapshot_service import ProjectSnapshotService
from arkumu.storage.models.s3_file_objects import S3FileObject
from arkumu.users.models import Organization


@pytest.mark.django_db
def test_approved_publications_queryset_filters_by_approval():
    """Test that _approved_publications_queryset only returns approved publications."""
    org = Organization.objects.create(code="fuk", name="FUK", is_active=True)
    now = timezone.now()

    # Create approved project with publication
    project_approved = Resource.objects.create(
        uri="https://arkumu.org/entities/projekt/1",
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
        updated_at=now - timedelta(days=2),
    )
    digital = Resource.objects.create(
        uri="https://arkumu.org/entities/digitales-objekt/1",
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )
    OAIProjectMediaLink.objects.create(project=project_approved, digital_object=digital)
    pub_approved = OAIProjectPublication.objects.create(project=project_approved, is_approved=True)
    OAIProjectPublication.objects.filter(pk=pub_approved.pk).update(updated_at=now - timedelta(days=1))

    # Create unapproved project
    project_unapproved = Resource.objects.create(
        uri="https://arkumu.org/entities/projekt/2",
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
        updated_at=now,
    )
    digital_two = Resource.objects.create(
        uri="https://arkumu.org/entities/digitales-objekt/2",
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )
    OAIProjectMediaLink.objects.create(project=project_unapproved, digital_object=digital_two)
    OAIProjectPublication.objects.create(project=project_unapproved, is_approved=False)

    qs = tailored._approved_publications_queryset()
    project_uris = [pub.project.uri for pub in qs]

    assert project_approved.uri in project_uris
    assert project_unapproved.uri not in project_uris


@pytest.mark.django_db
def test_approved_publications_queryset_uses_publication_updated_at():
    """Test that publication's updated_at is used for ordering."""
    org = Organization.objects.create(code="fuk", name="FUK", is_active=True)
    now = timezone.now()

    project = Resource.objects.create(
        uri="https://arkumu.org/entities/projekt/1",
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
        updated_at=now - timedelta(days=10),
    )
    digital = Resource.objects.create(
        uri="https://arkumu.org/entities/digitales-objekt/1",
        organization=org,
        resource_type=ResourceType.ENTITY,
    )
    OAIProjectMediaLink.objects.create(project=project, digital_object=digital)
    pub = OAIProjectPublication.objects.create(project=project, is_approved=True)

    # Set publication updated_at to a specific time
    publication_time = now - timedelta(days=1)
    OAIProjectPublication.objects.filter(pk=pub.pk).update(updated_at=publication_time)

    qs = tailored._approved_publications_queryset()
    result = qs.first()

    assert result is not None
    assert result.updated_at == publication_time


@pytest.mark.django_db
def test_fetch_publication_page_pagination():
    """Test cursor-based pagination through publications."""
    org = Organization.objects.create(code="fuk", name="FUK", is_active=True)
    base = datetime(2024, 1, 1, tzinfo=dt_timezone.utc)

    # Create multiple approved projects
    projects = []
    for i in range(3):
        project = Resource.objects.create(
            uri=f"https://arkumu.org/entities/projekt/{i+1}",
            organization=org,
            resource_type=ResourceType.ENTITY,
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True,
        )
        digital = Resource.objects.create(
            uri=f"https://arkumu.org/entities/digitales-objekt/{i+1}",
            organization=org,
            resource_type=ResourceType.ENTITY,
        )
        OAIProjectMediaLink.objects.create(project=project, digital_object=digital)
        pub = OAIProjectPublication.objects.create(project=project, is_approved=True)
        OAIProjectPublication.objects.filter(pk=pub.pk).update(
            updated_at=base + timedelta(days=i)
        )
        projects.append(project)

    qs = tailored._approved_publications_queryset()

    # First page
    first_page = tailored._fetch_publication_page(
        qs,
        cursor_position=None,
        page_size=2,
    )
    assert len(first_page.publications) == 2
    assert first_page.has_more is True
    assert first_page.cursor_position is not None

    # Second page
    second_page = tailored._fetch_publication_page(
        qs,
        cursor_position=first_page.cursor_position,
        page_size=2,
    )
    assert len(second_page.publications) == 1
    assert second_page.has_more is False


@pytest.mark.django_db
def test_fetch_publication_page_ordering():
    """Test that publications are ordered by updated_at."""
    org = Organization.objects.create(code="fuk", name="FUK", is_active=True)
    base = datetime(2024, 1, 1, tzinfo=dt_timezone.utc)

    # Create projects with different publication timestamps
    proj_a = Resource.objects.create(
        uri="https://arkumu.org/entities/projekt/a",
        organization=org,
        resource_type=ResourceType.ENTITY,
    )
    proj_b = Resource.objects.create(
        uri="https://arkumu.org/entities/projekt/b",
        organization=org,
        resource_type=ResourceType.ENTITY,
    )

    for proj in [proj_a, proj_b]:
        digital = Resource.objects.create(
            uri=f"{proj.uri}/digital",
            organization=org,
            resource_type=ResourceType.ENTITY,
        )
        OAIProjectMediaLink.objects.create(project=proj, digital_object=digital)

    pub_a = OAIProjectPublication.objects.create(project=proj_a, is_approved=True)
    pub_b = OAIProjectPublication.objects.create(project=proj_b, is_approved=True)

    # proj_b has earlier timestamp, should come first
    OAIProjectPublication.objects.filter(pk=pub_a.pk).update(updated_at=base + timedelta(days=5))
    OAIProjectPublication.objects.filter(pk=pub_b.pk).update(updated_at=base + timedelta(days=1))

    qs = tailored._approved_publications_queryset()
    page = tailored._fetch_publication_page(qs, cursor_position=None, page_size=10)

    assert len(page.publications) == 2
    assert page.publications[0].project.uri == proj_b.uri  # Earlier timestamp first
    assert page.publications[1].project.uri == proj_a.uri


@pytest.mark.django_db
def test_project_hint_uses_curated_links_only_when_tailored(monkeypatch):
    org = Organization.objects.create(code="khm", name="KHM", is_active=True)
    project = Resource.objects.create(
        uri="https://arkumu.org/entities/projekt/curated",
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )
    digital_a = Resource.objects.create(
        uri="https://arkumu.org/entities/digital/a",
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )
    digital_b = Resource.objects.create(
        uri="https://arkumu.org/entities/digital/b",
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )

    record = ProjectRecord(
        subject_id=str(project.id),
        uri=project.uri,
        title="Curated Project",
        institution=ProjectInstitution(label=org.name, code=org.code),
        digital_objects=[
            ProjectDigitalObject(
                path="s3://bucket/a.tif",
                storage_key="s3://bucket/a.tif",
                file_name="a.tif",
                content_type="image/tiff",
                storage_status="completed",
                resource_id=str(digital_a.id),
                uri=digital_a.uri,
            ),
            ProjectDigitalObject(
                path="s3://bucket/b.tif",
                storage_key="s3://bucket/b.tif",
                file_name="b.tif",
                content_type="image/tiff",
                storage_status="completed",
                resource_id=str(digital_b.id),
                uri=digital_b.uri,
            ),
        ],
    )

    OAIProjectMediaLink.objects.create(
        project=project,
        digital_object=digital_b,
        order_index=1,
    )
    OAIProjectMediaLink.objects.create(
        project=project,
        digital_object=digital_a,
        order_index=2,
    )

    monkeypatch.setattr(project_views, "_assemble_record_from_db", lambda resource: record)
    monkeypatch.setattr(
        project_views,
        "snapshot_service",
        SimpleNamespace(get_record_by_uri=lambda uri: None),
    )
    monkeypatch.setattr(project_views.project_builder, "_s3_orgs", set())
    monkeypatch.setattr(project_views.project_builder, "_rosetta_orgs", set())
    monkeypatch.setattr(project_views.project_builder, "_path_resolver", lambda *args, **kwargs: ["s3://bucket/a.tif"])
    monkeypatch.setattr(project_views._tailored_project_builder, "_s3_orgs", set())
    monkeypatch.setattr(project_views._tailored_project_builder, "_rosetta_orgs", set())
    monkeypatch.setattr(project_views._tailored_project_builder, "_path_resolver", lambda *args, **kwargs: ["s3://bucket/a.tif"])

    base_hint = project_views._build_project_hint_from_resource(project)
    assert [obj.resource_id for obj in base_hint.digital_objects] == [
        str(digital_a.id),
        str(digital_b.id),
    ]

    curated_hint = project_views._build_tailored_project_hint_from_resource(project)

    assert [obj.resource_id for obj in curated_hint.digital_objects] == [
        str(digital_b.id),
        str(digital_a.id),
    ]


@pytest.mark.django_db
def test_tailored_builder_rehydrates_missing_curated_media(monkeypatch):
    org = Organization.objects.create(code="fuk", name="FUK", is_active=True)
    project = Resource.objects.create(
        uri="https://arkumu.org/entities/projekt/s3",
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )

    def _digital(slug: str) -> Resource:
        return Resource.objects.create(
            uri=f"https://arkumu.org/entities/digital/{slug}",
            organization=org,
            resource_type=ResourceType.ENTITY,
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True,
        )

    digital_extra = _digital("extra")
    digital_first = _digital("first")
    digital_second = _digital("second")
    digital_third = _digital("third")

    for resource in (digital_first, digital_second, digital_third):
        S3FileObject.objects.create(
            related_resource=resource,
            file_name=f"{resource.uri.rsplit('/', 1)[-1]}.tif",
            s3_key=f"s3://bucket/{resource.uri.rsplit('/', 1)[-1]}.tif",
            content_type="image/tiff",
            status="completed",
            file_size_bytes=1024,
        )

    record = ProjectRecord(
        subject_id=str(project.id),
        uri=project.uri,
        title="S3 curated project",
        institution=ProjectInstitution(label=org.name, code=org.code),
        digital_objects=[
            ProjectDigitalObject(
                path="s3://bucket/extra.tif",
                storage_key="s3://bucket/extra.tif",
                file_name="extra.tif",
                content_type="image/tiff",
                storage_status="completed",
                resource_id=str(digital_extra.id),
                uri=digital_extra.uri,
            )
        ],
    )

    for order, resource in enumerate([digital_third, digital_first, digital_second], start=1):
        OAIProjectMediaLink.objects.create(
            project=project,
            digital_object=resource,
            order_index=order,
        )

    builder = OAIProjectBuilderTailored(
        s3_orgs=[org.code],
        rosetta_orgs=[],
        path_resolver=lambda *args, **kwargs: [],
    )

    def _fake_find_fixity(org_code, candidates):
        for candidate in candidates:
            if candidate:
                return SimpleNamespace(
                    storage_key=candidate,
                    checksum_or_etag="sha256:d34db33f",
                    status="completed",
                )
        return None

    monkeypatch.setattr(
        "arkumu.projects.services.dump_fixity_index.find_fixity",
        _fake_find_fixity,
    )

    curated_project = builder.from_project_record(record, use_curated_media_links=True)

    curated_ids = [obj.resource_id for obj in curated_project.digital_objects]
    assert curated_ids == [
        str(digital_third.id),
        str(digital_first.id),
        str(digital_second.id),
    ]

    curated_keys = [obj.storage_key for obj in curated_project.digital_objects]
    assert curated_keys == [
        "s3://bucket/third.tif",
        "s3://bucket/first.tif",
        "s3://bucket/second.tif",
    ]


@pytest.mark.django_db
def test_tailored_builder_hydrates_graph_only_curated_media():
    org = Organization.objects.create(code="khm", name="KHM", is_active=True)
    project = Resource.objects.create(
        uri="https://arkumu.org/entities/projekt/graph",
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )
    digital = Resource.objects.create(
        uri="https://arkumu.org/entities/digital/graph-only",
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )

    path_predicate = Resource.objects.create(
        uri=ProjectURIs.DIGITAL_OBJECT_PATH,
        canonical_uri=ProjectURIs.DIGITAL_OBJECT_PATH,
        resource_type=ResourceType.PROPERTY,
    )
    link_predicate = Resource.objects.create(
        uri=ProjectURIs.DIGITAL_OBJECT_LINK,
        canonical_uri=ProjectURIs.DIGITAL_OBJECT_LINK,
        resource_type=ResourceType.PROPERTY,
    )
    literal = Resource.objects.create(
        value="/graph/curated-object.jpg",
        resource_type=ResourceType.LITERAL,
    )
    Triple.objects.create(subject=digital, predicate=path_predicate, object=literal)

    checksum_predicate_uri = ProjectSnapshotService.ROSETTA_CHECKSUM_PREDICATES["khm"]
    checksum_predicate = Resource.objects.create(
        uri=checksum_predicate_uri,
        canonical_uri=checksum_predicate_uri,
        resource_type=ResourceType.PROPERTY,
    )
    checksum_literal = Resource.objects.create(
        value="sha256:feedface",
        resource_type=ResourceType.LITERAL,
    )
    Triple.objects.create(subject=digital, predicate=checksum_predicate, object=checksum_literal)

    event = Resource.objects.create(
        uri="https://arkumu.org/entities/ereignis/1",
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )
    Triple.objects.create(subject=event, predicate=link_predicate, object=digital)

    OAIProjectMediaLink.objects.create(
        project=project,
        digital_object=digital,
        order_index=1,
    )

    record = ProjectRecord(
        subject_id=str(project.id),
        uri=project.uri,
        title="Graph curated project",
        institution=ProjectInstitution(label=org.name, code=org.code),
        digital_objects=[],
    )

    builder = OAIProjectBuilderTailored(
        s3_orgs=[],
        rosetta_orgs=[],
        path_resolver=lambda *args, **kwargs: [],
    )

    curated_project = builder.from_project_record(record, use_curated_media_links=True)

    assert [obj.resource_id for obj in curated_project.digital_objects] == [str(digital.id)]
    assert curated_project.digital_objects[0].storage_key == "/graph/curated-object.jpg"
    assert curated_project.digital_objects[0].uri == digital.uri
    assert curated_project.digital_objects[0].checksum == "feedface"


@pytest.mark.django_db
def test_tailored_builder_uses_pending_curated_links():
    org = Organization.objects.create(code="det", name="DET", is_active=True)
    project = Resource.objects.create(
        uri="https://arkumu.org/entities/projekt/pending",
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )
    digital_one = Resource.objects.create(
        uri="https://arkumu.org/entities/digital/pending-1",
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )
    digital_two = Resource.objects.create(
        uri="https://arkumu.org/entities/digital/pending-2",
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )

    record = ProjectRecord(
        subject_id=str(project.id),
        uri=project.uri,
        title="Pending curated project",
        institution=ProjectInstitution(label=org.name, code=org.code),
        digital_objects=[
            ProjectDigitalObject(
                path="a.tif",
                storage_key="a.tif",
                file_name="a.tif",
                content_type="image/tiff",
                storage_status="completed",
                resource_id=str(digital_one.id),
                uri=digital_one.uri,
            ),
            ProjectDigitalObject(
                path="b.tif",
                storage_key="b.tif",
                file_name="b.tif",
                content_type="image/tiff",
                storage_status="completed",
                resource_id=str(digital_two.id),
                uri=digital_two.uri,
            ),
        ],
    )

    OAIProjectMediaLink.objects.create(
        project=project,
        digital_object=digital_two,
        order_index=1,
        label_override="Second Pending",
    )
    OAIProjectMediaLink.objects.create(
        project=project,
        digital_object=digital_one,
        order_index=2,
    )

    builder = OAIProjectBuilderTailored(
        s3_orgs=[],
        rosetta_orgs=[],
        path_resolver=lambda *args, **kwargs: [],
    )

    project_view = builder.from_project_record(record, use_curated_media_links=True)

    assert [obj.resource_id for obj in project_view.digital_objects] == [
        str(digital_two.id),
        str(digital_one.id),
    ]
    assert project_view.digital_objects[0].label_override == "Second Pending"


@pytest.mark.django_db
def test_publication_dataset_marker_returns_latest_timestamp():
    """Test that dataset marker returns the latest publication timestamp."""
    org = Organization.objects.create(code="test", name="Test", is_active=True)
    base = datetime(2024, 6, 1, tzinfo=dt_timezone.utc)

    for i in range(3):
        project = Resource.objects.create(
            uri=f"https://arkumu.org/entities/projekt/{i}",
            organization=org,
            resource_type=ResourceType.ENTITY,
        )
        digital = Resource.objects.create(
            uri=f"https://arkumu.org/entities/digital/{i}",
            organization=org,
            resource_type=ResourceType.ENTITY,
        )
        OAIProjectMediaLink.objects.create(project=project, digital_object=digital)
        pub = OAIProjectPublication.objects.create(project=project, is_approved=True)
        OAIProjectPublication.objects.filter(pk=pub.pk).update(
            updated_at=base + timedelta(days=i)
        )

    qs = tailored._approved_publications_queryset()
    marker = tailored._publication_dataset_marker(qs)

    # Should be the latest timestamp (day 2)
    expected = (base + timedelta(days=2)).isoformat()
    assert marker == expected


@pytest.mark.django_db
def test_approved_publications_queryset_filters_inactive_orgs():
    """Test that inactive organizations are excluded."""
    active_org = Organization.objects.create(code="active", name="Active", is_active=True)
    inactive_org = Organization.objects.create(code="inactive", name="Inactive", is_active=False)

    for org in [active_org, inactive_org]:
        project = Resource.objects.create(
            uri=f"https://arkumu.org/entities/projekt/{org.code}",
            organization=org,
            resource_type=ResourceType.ENTITY,
        )
        digital = Resource.objects.create(
            uri=f"https://arkumu.org/entities/digital/{org.code}",
            organization=org,
            resource_type=ResourceType.ENTITY,
        )
        OAIProjectMediaLink.objects.create(project=project, digital_object=digital)
        OAIProjectPublication.objects.create(project=project, is_approved=True)

    qs = tailored._approved_publications_queryset()
    org_codes = [pub.project.organization.code for pub in qs]

    assert "active" in org_codes
    assert "inactive" not in org_codes
