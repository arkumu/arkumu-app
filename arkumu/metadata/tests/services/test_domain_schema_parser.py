import json
from pathlib import Path

import pytest

from arkumu.metadata.services.domain_schema_parser import (
    ArkumuModelExportService,
    ArkumuModelMarkdownParser,
)


@pytest.fixture
def markdown_path(settings) -> Path:
    base_dir = Path(settings.BASE_DIR)
    path = base_dir / "202509221749 arkumu model.md"
    if not path.exists():
        pytest.skip("Domain model markdown file missing")
    return path


def test_parser_extracts_actor_class(markdown_path):
    parser = ArkumuModelMarkdownParser()
    classes = parser.parse_file(markdown_path)

    assert classes, "Expected at least one class definition"

    actor = next((cls for cls in classes if cls.identifier == "actor"), None)
    assert actor is not None, "Actor class should be parsed"
    assert actor.english_name == "Actor"
    assert actor.german_name == "Akteur:in"
    assert actor.properties["en"], "English property list should not be empty"
    assert any(prop["name"] == "has german name" for prop in actor.properties["en"])


def test_export_service_produces_serialized_json(markdown_path):
    service = ArkumuModelExportService()
    payload = service.build_schema(markdown_path)

    assert "generated_at" in payload
    assert payload["classes"], "Classes should be present in export payload"

    serialized = service.export_json(markdown_path, indent=None, payload=payload)
    data = json.loads(serialized)

    assert data["classes"] == payload["classes"]
    assert data["generated_at"] == payload["generated_at"]
