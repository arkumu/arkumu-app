"""Tests for the tailored OAI project builder."""

from arkumu.oaipmh.oai_project import CuratedMediaSelection
from arkumu.oaipmh.oai_project_tailored import OAIProjectBuilderTailored
from arkumu.projects import ProjectDigitalObject, ProjectInstitution, ProjectRecord
from arkumu.oaipmh import oai_project as base_builder_module
from arkumu.oaipmh.services import dcp_index


def test_tailored_builder_path_resolver_passthrough():
    builder = OAIProjectBuilderTailored()
    resolver = builder._path_resolver  # noqa: SLF001 - intentional introspection for test

    result = resolver(
        "khm",
        path="/Volumes/Archivplatte/media/digital_archive_vault/2013/example/file.jpg",
        file_name="file.jpg",
    )

    assert result == ["/Volumes/Archivplatte/media/digital_archive_vault/2013/example/file.jpg"]


def test_tailored_builder_expands_dcp_folder_from_record(monkeypatch):
    """
    Tailored builder should expand a DCP bundle by scanning record digital_objects (DB-only).
    """

    class DummyNormalized:
        def __init__(self, obj):
            self.source = "rosetta"
            self.storage_key = obj.storage_key or obj.path
            self.rosetta_path = obj.path
            self.storage_status = getattr(obj, "storage_status", "completed")
            self.preferred_location = self.storage_key
            self.resource_id = getattr(obj, "resource_id", None)
            self.uri = getattr(obj, "uri", None)
            self.file_name = getattr(obj, "file_name", None)

    monkeypatch.setattr(
        OAIProjectBuilderTailored,
        "_normalize_object",
        lambda self, obj, institution_code: DummyNormalized(obj),
    )
    monkeypatch.setattr(
        OAIProjectBuilderTailored,
        "_is_harvestable",
        lambda self, obj: True,
    )

    builder = OAIProjectBuilderTailored()
    folder = "/rosetta/khm/sandbox/input/arkumu/daten/2265_auf_der_strecke_dcp"
    record = ProjectRecord(
        subject_id="proj-2265",
        uri="http://arkumu.org/data/khm/entities/00-projekte/2265",
        title="Tailored DCP project",
        institution=ProjectInstitution(code="khm", label="KHM"),
        digital_objects=[
            ProjectDigitalObject(
                path=f"{folder}/CPL_abc.xml",
                storage_key=f"{folder}/CPL_abc.xml",
                file_name="CPL_abc.xml",
                resource_id="cpl-1",
            ),
            ProjectDigitalObject(
                path=f"{folder}/asset.mxf",
                storage_key=f"{folder}/asset.mxf",
                file_name="asset.mxf",
                resource_id="asset-1",
            ),
        ],
    )

    project = builder.from_project_record(record, use_curated_media_links=False)

    assert len(project.digital_objects) == 2
    assert {obj.preferred_location for obj in project.digital_objects} == {
        f"{folder}/CPL_abc.xml",
        f"{folder}/asset.mxf",
    }


def test_tailored_builder_expands_curated_dcp_when_record_lacks_objects(monkeypatch):
    """
    When curated selection filters would exclude siblings, DCP bundle still expands.
    """

    from arkumu.oaipmh.oai_project import CuratedMediaSelection

    def fake_curated_selection(record):
        return CuratedMediaSelection(
            ordered_resource_ids=("cpl-1",),
            ordered_object_uris=(),
            resource_uri_pairs=(("cpl-1", None),),
            label_overrides_by_id={},
            label_overrides_by_uri={},
            curated_missing_uris=(),
            graph_only_uris=(),
            warnings=(),
        )

    class DummyNormalized:
        def __init__(self, obj):
            self.source = "rosetta"
            self.storage_key = obj.storage_key or obj.path
            self.rosetta_path = obj.path
            self.storage_status = getattr(obj, "storage_status", "completed")
            self.preferred_location = self.storage_key
            self.resource_id = getattr(obj, "resource_id", None)
            self.uri = getattr(obj, "uri", None)
            self.file_name = getattr(obj, "file_name", None)

    monkeypatch.setattr(OAIProjectBuilderTailored, "_resolve_curated_selection", lambda self, record: fake_curated_selection(record))
    monkeypatch.setattr(
        OAIProjectBuilderTailored,
        "_normalize_object",
        lambda self, obj, institution_code: DummyNormalized(obj),
    )
    monkeypatch.setattr(
        OAIProjectBuilderTailored,
        "_is_harvestable",
        lambda self, obj: True,
    )

    builder = OAIProjectBuilderTailored()
    folder = "/rosetta/khm/sandbox/input/arkumu/daten/2265_auf_der_strecke_dcp"
    record = ProjectRecord(
        subject_id="proj-2265",
        uri="http://arkumu.org/data/khm/entities/00-projekte/2265",
        title="Tailored curated DCP project",
        institution=ProjectInstitution(code="khm", label="KHM"),
        digital_objects=[
            ProjectDigitalObject(
                path=f"{folder}/CPL_abc.xml",
                storage_key=f"{folder}/CPL_abc.xml",
                file_name="CPL_abc.xml",
                resource_id="cpl-1",
            ),
            ProjectDigitalObject(
                path=f"{folder}/asset.mxf",
                storage_key=f"{folder}/asset.mxf",
                file_name="asset.mxf",
                resource_id="asset-1",
            ),
        ],
    )

    project = builder.from_project_record(record, use_curated_media_links=True)

    assert len(project.digital_objects) == 2
    assert {obj.preferred_location for obj in project.digital_objects} == {
        f"{folder}/CPL_abc.xml",
        f"{folder}/asset.mxf",
    }


def test_tailored_builder_expands_dcp_via_folder_triple(monkeypatch):
    """
    Tailored builder should expand a DCP bundle based on the folder triple, even without CPL/PKL filenames.
    """

    class DummyNormalized:
        def __init__(self, obj):
            self.source = "rosetta"
            self.storage_key = obj.storage_key or obj.path
            self.rosetta_path = obj.path
            self.storage_status = getattr(obj, "storage_status", "completed")
            self.preferred_location = self.storage_key
            self.resource_id = getattr(obj, "resource_id", None)
            self.uri = getattr(obj, "uri", None)
            self.file_name = getattr(obj, "file_name", None)

    folder = "/rosetta/khm/sandbox/input/arkumu/daten/9999_bundle_dcp"

    def fake_get_bundle_members(org_code, folder_name, folder_path=None):
        assert org_code == "khm"
        assert folder_name.endswith("_dcp")
        return dcp_index.BundleLookupResult(
            org_code="khm",
            folder_name=folder_name,
            relative_file_paths=(
                "9999_bundle_dcp/feature.mxf",
                "9999_bundle_dcp/audio.wav",
            ),
        )

    monkeypatch.setattr(
        dcp_index,
        "get_bundle_members",
        fake_get_bundle_members,
    )
    monkeypatch.setattr(
        OAIProjectBuilderTailored,
        "_normalize_object",
        lambda self, obj, institution_code: DummyNormalized(obj),
    )
    monkeypatch.setattr(
        OAIProjectBuilderTailored,
        "_is_harvestable",
        lambda self, obj: True,
    )

    builder = OAIProjectBuilderTailored()
    record = ProjectRecord(
        subject_id="proj-9999",
        uri="http://arkumu.org/data/khm/entities/00-projekte/9999",
        title="Tailored DCP via triple",
        institution=ProjectInstitution(code="khm", label="KHM"),
        digital_objects=[
            ProjectDigitalObject(
                path=f"{folder}/feature.mxf",
                storage_key=f"{folder}/feature.mxf",
                file_name="feature.mxf",
                resource_id="res-1",
            ),
            ProjectDigitalObject(
                path=f"{folder}/audio.wav",
                storage_key=f"{folder}/audio.wav",
                file_name="audio.wav",
                resource_id="res-2",
            ),
        ],
    )

    project = builder.from_project_record(record, use_curated_media_links=False)

    assert len(project.digital_objects) == 2
    assert {obj.preferred_location for obj in project.digital_objects} == {
        f"{folder}/feature.mxf",
        f"{folder}/audio.wav",
    }


def test_tailored_builder_dcp_triple_bypasses_curated_filter(monkeypatch):
    """
    Curated selections should not drop DCP siblings when the folder triple is present.
    """

    def fake_curated_selection(record):
        return CuratedMediaSelection(
            ordered_resource_ids=("res-1",),
            ordered_object_uris=(),
            resource_uri_pairs=(("res-1", None),),
            label_overrides_by_id={},
            label_overrides_by_uri={},
            curated_missing_uris=(),
            graph_only_uris=(),
            warnings=(),
        )

    class DummyNormalized:
        def __init__(self, obj):
            self.source = "rosetta"
            self.storage_key = obj.storage_key or obj.path
            self.rosetta_path = obj.path
            self.storage_status = getattr(obj, "storage_status", "completed")
            self.preferred_location = self.storage_key
            self.resource_id = getattr(obj, "resource_id", None)
            self.uri = getattr(obj, "uri", None)
            self.file_name = getattr(obj, "file_name", None)

    folder = "/rosetta/khm/sandbox/input/arkumu/daten/8888_bundle_dcp"

    monkeypatch.setattr(
        OAIProjectBuilderTailored,
        "_dcp_folder_from_triple",
        lambda self, obj: folder,
    )
    monkeypatch.setattr(
        OAIProjectBuilderTailored,
        "_resolve_curated_selection",
        lambda self, record: fake_curated_selection(record),
    )
    monkeypatch.setattr(
        OAIProjectBuilderTailored,
        "_normalize_object",
        lambda self, obj, institution_code: DummyNormalized(obj),
    )
    monkeypatch.setattr(
        OAIProjectBuilderTailored,
        "_is_harvestable",
        lambda self, obj: True,
    )

    builder = OAIProjectBuilderTailored()
    record = ProjectRecord(
        subject_id="proj-8888",
        uri="http://arkumu.org/data/khm/entities/00-projekte/8888",
        title="Tailored curated DCP via triple",
        institution=ProjectInstitution(code="khm", label="KHM"),
        digital_objects=[
            ProjectDigitalObject(
                path=f"{folder}/main.mxf",
                storage_key=f"{folder}/main.mxf",
                file_name="main.mxf",
                resource_id="res-1",
            ),
            ProjectDigitalObject(
                path=f"{folder}/subs.xml",
                storage_key=f"{folder}/subs.xml",
                file_name="subs.xml",
                resource_id="res-2",
            ),
        ],
    )

    project = builder.from_project_record(record, use_curated_media_links=True)

    assert len(project.digital_objects) == 2
    assert {obj.preferred_location for obj in project.digital_objects} == {
        f"{folder}/main.mxf",
        f"{folder}/subs.xml",
    }
