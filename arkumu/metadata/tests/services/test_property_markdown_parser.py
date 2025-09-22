from pathlib import Path

import pytest

from arkumu.metadata.services.property_markdown_parser import PropertyMarkdownParser


@pytest.fixture
def markdown_path(settings) -> Path:
    path = Path(settings.BASE_DIR) / "202509221749 arkumu model.md"
    if not path.exists():
        pytest.skip("Domain markdown missing")
    return path


def test_property_parser_extracts_graph_representation(markdown_path):
    parser = PropertyMarkdownParser()
    properties = parser.parse_file(markdown_path)

    assert properties
    lookup = {prop.normalized_key: prop for prop in properties}
    has_german_name = lookup.get("has german name")
    assert has_german_name is not None
    assert has_german_name.graph_representation == "arkumu:hasGermanName"
    assert has_german_name.uri.endswith("#has-german-name")

