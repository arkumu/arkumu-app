"""Tests for the tailored OAI project builder."""

from arkumu.oaipmh.oai_project_tailored import OAIProjectBuilderTailored
from arkumu.projects import ProjectDigitalObject, ProjectInstitution, ProjectRecord
from arkumu.oaipmh import oai_project as base_builder_module


def test_tailored_builder_path_resolver_passthrough():
    builder = OAIProjectBuilderTailored()
    resolver = builder._path_resolver  # noqa: SLF001 - intentional introspection for test

    result = resolver(
        "khm",
        path="/Volumes/Archivplatte/media/digital_archive_vault/2013/example/file.jpg",
        file_name="file.jpg",
    )

    assert result == ["/Volumes/Archivplatte/media/digital_archive_vault/2013/example/file.jpg"]


def test_tailored_builder_skips_dcp_path_index(monkeypatch):
    """
    Tailored builder must not consult the base DCP expansion that reads external path indexes.
    """

    def explode(*args, **kwargs):
        raise AssertionError("Base DCP expansion must not run in tailored profile")

    monkeypatch.setattr(
        base_builder_module.OAIProjectBuilder,
        "_expand_dcp_folder_if_needed",
        explode,
    )

    builder = OAIProjectBuilderTailored()
    record = ProjectRecord(
        subject_id="proj-2265",
        uri="http://arkumu.org/data/khm/entities/00-projekte/2265",
        title="Tailored DCP project",
        institution=ProjectInstitution(code="khm", label="KHM"),
        digital_objects=[
            ProjectDigitalObject(
                path="/rosetta/khm/sandbox/input/arkumu/daten/2265_auf_der_strecke_dcp",
                storage_key="/rosetta/khm/sandbox/input/arkumu/daten/2265_auf_der_strecke_dcp",
                file_name="2265_auf_der_strecke_dcp",
            )
        ],
    )

    project = builder.from_project_record(record, use_curated_media_links=False)

    assert len(project.digital_objects) == 1
    assert project.digital_objects[0].original_path.endswith("2265_auf_der_strecke_dcp")
