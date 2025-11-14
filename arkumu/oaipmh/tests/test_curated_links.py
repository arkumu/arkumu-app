"""Tests covering curated media link integration."""

from __future__ import annotations

import pytest

from arkumu.metadata.models.resource import PublicAccessLevel, Resource, ResourceType
from arkumu.oaipmh.models import OAIProjectMediaLink
from arkumu.oaipmh.oai_project import OAIProjectBuilder
from arkumu.projects import ProjectDigitalObject, ProjectInstitution, ProjectRecord
from arkumu.users.models import Organization


def _make_org(code: str = "fuk") -> Organization:
    return Organization.objects.create(
        name=f"Org {code.upper()}",
        code=code,
        domain=f"{code}.arkumu",
        is_active=True,
    )


def _make_resource(org: Organization, uri: str) -> Resource:
    return Resource.objects.create(
        uri=uri,
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
        name=uri.rsplit("/", 1)[-1],
    )


def _record_for_project(project: Resource, *digital_objects: ProjectDigitalObject) -> ProjectRecord:
    institution = project.organization
    return ProjectRecord(
        subject_id=str(project.id),
        uri=project.uri,
        title=project.name,
        institution=ProjectInstitution(
            label=institution.name if institution else None,
            code=institution.code if institution else None,
        ),
        digital_objects=list(digital_objects),
    )


def _digital_object(resource: Resource, storage_key: str) -> ProjectDigitalObject:
    return ProjectDigitalObject(
        path=storage_key,
        storage_key=storage_key,
        file_name=storage_key.rsplit("/", 1)[-1],
        content_type="image/tiff",
        storage_status="completed",
        resource_id=str(resource.id),
        uri=resource.uri,
    )


@pytest.mark.django_db
def test_builder_prefers_curated_links_when_available(settings):
    settings.OAI_S3_HARVESTABLE_ORGS = ()
    settings.OAI_ROSETTA_HARVESTABLE_ORGS = ()

    org = _make_org()
    project = _make_resource(org, "https://arkumu.test/entities/projekt/100")
    digital_a = _make_resource(org, "https://arkumu.test/entities/digital/1")
    digital_b = _make_resource(org, "https://arkumu.test/entities/digital/2")

    record = _record_for_project(
        project,
        _digital_object(digital_a, "s3://bucket/a.tif"),
        _digital_object(digital_b, "s3://bucket/b.tif"),
    )

    OAIProjectMediaLink.objects.create(
        project=project,
        digital_object=digital_b,
        status=OAIProjectMediaLink.STATUS_APPROVED,
        order_index=1,
        label_override="Curated B",
    )
    OAIProjectMediaLink.objects.create(
        project=project,
        digital_object=digital_a,
        status=OAIProjectMediaLink.STATUS_APPROVED,
        order_index=2,
    )

    builder = OAIProjectBuilder()
    curated_project = builder.from_project_record(record, use_curated_media_links=True)

    assert [obj.resource_id for obj in curated_project.digital_objects] == [
        str(digital_b.id),
        str(digital_a.id),
    ]
    assert curated_project.digital_objects[0].display_label == "Curated B"
    assert curated_project.curated_selection is not None
    assert curated_project.curated_selection.ordered_resource_ids[0] == str(digital_b.id)


@pytest.mark.django_db
def test_builder_reports_conflicts_when_curated_missing_and_graph_only(settings):
    settings.OAI_S3_HARVESTABLE_ORGS = ()
    settings.OAI_ROSETTA_HARVESTABLE_ORGS = ()

    org = _make_org("det")
    project = _make_resource(org, "https://arkumu.test/entities/projekt/200")
    curated_resource = _make_resource(org, "https://arkumu.test/entities/digital/curated")
    graph_resource = _make_resource(org, "https://arkumu.test/entities/digital/graph")

    record = _record_for_project(
        project,
        _digital_object(graph_resource, "s3://bucket/graph.tif"),
    )

    OAIProjectMediaLink.objects.create(
        project=project,
        digital_object=curated_resource,
        status=OAIProjectMediaLink.STATUS_APPROVED,
        order_index=1,
    )

    builder = OAIProjectBuilder()
    curated_project = builder.from_project_record(record, use_curated_media_links=True)

    assert curated_project.digital_objects == ()
    assert curated_project.curated_selection is not None
    selection = curated_project.curated_selection
    assert curated_resource.uri in selection.curated_missing_uris
    assert graph_resource.uri in selection.graph_only_uris
    warning_codes = {warning.code for warning in selection.warnings}
    assert "curated_missing_in_graph" in warning_codes
    assert "graph_objects_uncurated" in warning_codes


@pytest.mark.django_db
def test_builder_flags_duplicate_curated_assignments(settings):
    settings.OAI_S3_HARVESTABLE_ORGS = ()
    settings.OAI_ROSETTA_HARVESTABLE_ORGS = ()

    org = _make_org("rsh")
    project_a = _make_resource(org, "https://arkumu.test/entities/projekt/300")
    project_b = _make_resource(org, "https://arkumu.test/entities/projekt/301")
    shared_resource = _make_resource(org, "https://arkumu.test/entities/digital/shared")

    record = _record_for_project(
        project_a,
        _digital_object(shared_resource, "s3://bucket/shared.tif"),
    )

    OAIProjectMediaLink.objects.create(
        project=project_a,
        digital_object=shared_resource,
        status=OAIProjectMediaLink.STATUS_APPROVED,
        order_index=1,
    )
    OAIProjectMediaLink.objects.create(
        project=project_b,
        digital_object=shared_resource,
        status=OAIProjectMediaLink.STATUS_APPROVED,
        order_index=1,
    )

    builder = OAIProjectBuilder()
    curated_project = builder.from_project_record(record, use_curated_media_links=True)

    assert curated_project.digital_objects and curated_project.digital_objects[0].resource_id == str(shared_resource.id)
    assert curated_project.curated_selection is not None
    assert any(
        warning.code == "digital_object_multi_project"
        for warning in curated_project.curated_selection.warnings
    )

