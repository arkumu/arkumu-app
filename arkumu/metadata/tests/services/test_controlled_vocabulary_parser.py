from pathlib import Path

import json
import pytest

from arkumu.metadata.services.controlled_vocabulary_parser import (
    ControlledVocabularyMarkdownParser,
    ControlledVocabularyExportService,
)


@pytest.fixture
def markdown_path(settings) -> Path:
    path = Path(settings.BASE_DIR) / "202509221948 arkumu controlled vocabularies.md"
    if not path.exists():
        pytest.skip("Controlled vocabularies markdown file missing")
    return path


def test_parser_reads_value_lists(markdown_path):
    parser = ControlledVocabularyMarkdownParser()
    document = parser.parse_file(markdown_path)

    assert document.sections, "Expected sections to be parsed"
    value_lists = next((sec for sec in document.sections if "Value Lists" in sec.title), None)
    assert value_lists is not None, "Value Lists section should exist"
    assert any(entry.slug == "event-types" for entry in value_lists.entries)


def test_export_service_serializes_json(markdown_path):
    service = ControlledVocabularyExportService()
    payload = service.build_document(markdown_path)

    assert "sections" in payload
    serialized = service.export_json(markdown_path, indent=None)
    loaded = json.loads(serialized)

    assert loaded == payload

