from pathlib import Path

import pytest

from arkumu.metadata.services.controlled_vocabulary_detail_parser import (
    ControlledVocabularyDetailParser,
)


@pytest.fixture
def event_vocab_path(settings) -> Path:
    path = Path(settings.BASE_DIR) / "202509222017 arkumu controlled vocabulary - event types (event).md"
    if not path.exists():
        pytest.skip("Event vocabulary markdown missing")
    return path


def test_detail_parser_extracts_entries(event_vocab_path):
    parser = ControlledVocabularyDetailParser()
    document = parser.parse_file(event_vocab_path)

    assert document.entity.lower() == "event"
    assert document.entries
    first = document.entries[0]
    assert first.english_name
    assert first.slug
    assert first.attributes["id"]
