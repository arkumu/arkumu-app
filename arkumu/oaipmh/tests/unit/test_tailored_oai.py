from datetime import datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace

import pytest

from django.utils import timezone

from arkumu.catalog.services.project_views import ProjectURIs
from arkumu.metadata.models.resource import Resource, ResourceType, PublicAccessLevel
from arkumu.metadata.models.triples import Triple
from arkumu.oaipmh import views
from arkumu.oaipmh.models import OAIProjectMediaLink, OAIProjectPublication
from arkumu.oaipmh.oai_project_tailored import OAIProjectBuilderTailored
from arkumu.oaipmh.views import projects as project_views
from arkumu.projects import ProjectDigitalObject, ProjectInstitution, ProjectRecord
from arkumu.projects.services.snapshot_service import ProjectSnapshotService
from arkumu.storage.models.s3_file_objects import S3FileObject
from arkumu.users.models import Organization


@pytest.mark.django_db
def test_tailored_queryset_requires_curated_and_approved(monkeypatch):
    org = Organization.objects.create(code="fuk", name="FUK", is_active=True)
    now = timezone.now()

    monkeypatch.setattr(views, "_project_type_filter", lambda: None)

    project = Resource.objects.create(
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
    OAIProjectMediaLink.objects.create(project=project, digital_object=digital)
    pub = OAIProjectPublication.objects.create(project=project, is_approved=True)
    # Force publication timestamp to be newer than resource update
    OAIProjectPublication.objects.filter(pk=pub.pk).update(updated_at=now - timedelta(days=1))

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

    qs = views._tailored_resources_queryset()
    uris = list(qs.values_list("uri", flat=True))

    assert project.uri in uris
    assert project_unapproved.uri not in uris

    annotated = qs.get(uri=project.uri)
    assert hasattr(annotated, "effective_datestamp")
    assert annotated.effective_datestamp >= annotated.updated_at


@pytest.mark.django_db
def test_tailored_harvestable_page_uses_effective_datestamp(monkeypatch):
    org = Organization.objects.create(code="fuk", name="FUK", is_active=True)
    base = datetime(2024, 1, 1, tzinfo=dt_timezone.utc)

    monkeypatch.setattr(views, "_project_type_filter", lambda: None)

    def make_project(idx: int, updated: datetime) -> Resource:
        return Resource.objects.create(
            uri=f"https://arkumu.org/entities/projekt/{idx}",
            organization=org,
            resource_type=ResourceType.ENTITY,
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True,
            updated_at=updated,
        )

    proj_a = make_project(1, base)
    proj_b = make_project(2, base + timedelta(days=1))

    dig_a = Resource.objects.create(
        uri="https://arkumu.org/entities/digitales-objekt/a",
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )
    dig_b = Resource.objects.create(
        uri="https://arkumu.org/entities/digitales-objekt/b",
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )

    link_a = OAIProjectMediaLink.objects.create(project=proj_a, digital_object=dig_a)
    link_b = OAIProjectMediaLink.objects.create(project=proj_b, digital_object=dig_b)
    pub_a = OAIProjectPublication.objects.create(project=proj_a, is_approved=True)
    pub_b = OAIProjectPublication.objects.create(project=proj_b, is_approved=True)

    # Make effective datestamp ordering explicit:
    # proj_b should appear first due to earlier link/publication timestamps.
    OAIProjectMediaLink.objects.filter(pk=link_a.pk).update(updated_at=base + timedelta(days=5))
    OAIProjectMediaLink.objects.filter(pk=link_b.pk).update(updated_at=base + timedelta(days=2))
    OAIProjectPublication.objects.filter(pk=pub_a.pk).update(updated_at=base + timedelta(days=4))
    OAIProjectPublication.objects.filter(pk=pub_b.pk).update(updated_at=base + timedelta(days=1))

    monkeypatch.setattr(
        views,
        "_build_tailored_project_hint_from_resource",
        lambda resource: SimpleNamespace(harvestable=True, uri=resource.uri),
    )

    qs = views._tailored_resources_queryset()

    first_page = views._tailored_harvestable_page(
        qs,
        cursor_position=None,
        page_size=1,
        include_hints=True,
    )
    assert first_page.resources

    second_page = views._tailored_harvestable_page(
        qs,
        cursor_position=first_page.cursor_position,
        page_size=1,
        include_hints=True,
    )
    assert second_page.resources
    first_resource = first_page.resources[0]
    second_resource = second_page.resources[0]
    assert first_resource.effective_datestamp <= second_resource.effective_datestamp


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
        status=OAIProjectMediaLink.STATUS_APPROVED,
        order_index=1,
    )
    OAIProjectMediaLink.objects.create(
        project=project,
        digital_object=digital_a,
        status=OAIProjectMediaLink.STATUS_APPROVED,
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
            status=OAIProjectMediaLink.STATUS_APPROVED,
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
        status=OAIProjectMediaLink.STATUS_APPROVED,
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
        status=OAIProjectMediaLink.STATUS_APPROVED,
        order_index=1,
        label_override="Second Pending",
    )
    OAIProjectMediaLink.objects.create(
        project=project,
        digital_object=digital_one,
        status=OAIProjectMediaLink.STATUS_PENDING,
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
