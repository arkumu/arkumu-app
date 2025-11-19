"""Tests for the tailored OAI project builder."""

from arkumu.oaipmh.oai_project_tailored import OAIProjectBuilderTailored


def test_tailored_builder_path_resolver_passthrough():
    builder = OAIProjectBuilderTailored()
    resolver = builder._path_resolver  # noqa: SLF001 - intentional introspection for test

    result = resolver(
        "khm",
        path="/Volumes/Archivplatte/media/digital_archive_vault/2013/example/file.jpg",
        file_name="file.jpg",
    )

    assert result == ["/Volumes/Archivplatte/media/digital_archive_vault/2013/example/file.jpg"]
