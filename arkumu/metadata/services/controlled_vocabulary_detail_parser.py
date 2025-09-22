"""Parse detailed controlled vocabulary markdown files."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from arkumu.common.uri_utils import slugify_uri_part


LABEL_NORMALIZATIONS = {
    "englisch name": "english name",
    "englisch synonyms": "english synonyms",
}


@dataclass
class VocabularyEntryDetail:
    identifier: Optional[str]
    english_name: str
    german_name: Optional[str]
    english_synonyms: List[str]
    german_synonyms: List[str]
    uri: Optional[str]
    attributes: Dict[str, str] = field(default_factory=dict)

    @property
    def slug(self) -> str:
        return slugify_uri_part(self.english_name)


@dataclass
class VocabularyDocumentDetail:
    entity: str
    entries: List[VocabularyEntryDetail]


class ControlledVocabularyDetailParser:
    """Parse individual controlled vocabulary markdown files."""

    TABLE_ROW_PATTERN = re.compile(r"^\|.*\|$")

    def parse_file(self, path: Path | str) -> VocabularyDocumentDetail:
        content = Path(path).read_text(encoding="utf-8")
        return self.parse_text(content)

    def parse_text(self, content: str) -> VocabularyDocumentDetail:
        lines = content.splitlines()
        entity = self._extract_entity(lines)
        entries: List[VocabularyEntryDetail] = []
        heading: Optional[str] = None
        table_buffer: List[str] = []

        def flush() -> None:
            nonlocal heading, table_buffer
            if not table_buffer:
                return
            entry = self._parse_table(heading, table_buffer)
            if entry:
                entries.append(entry)
            table_buffer = []

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("## "):
                flush()
                heading = stripped[3:].strip()
                continue
            if self.TABLE_ROW_PATTERN.match(stripped):
                table_buffer.append(stripped)
                continue
            if stripped == "---":
                flush()
                heading = None
                continue
            if not stripped:
                flush()
                continue

        flush()

        return VocabularyDocumentDetail(entity=entity or "", entries=entries)

    def _extract_entity(self, lines: Iterable[str]) -> Optional[str]:
        for line in lines:
            stripped = line.strip().lower()
            if stripped.startswith("used in:"):
                return line.split(":", 1)[1].strip()
        return None

    def _parse_table(self, heading: Optional[str], rows: List[str]) -> Optional[VocabularyEntryDetail]:
        if len(rows) <= 2:
            return None
        data: Dict[str, str] = {}
        for row in rows[2:]:
            parts = [col.strip() for col in row.strip("|").split("|")]
            if len(parts) < 2:
                continue
            label_raw, value_raw = parts[0], parts[1]
            label = self._normalize_label(label_raw)
            value = self._clean_value(value_raw)
            data[label] = value

        english_name = data.get("english name") or (heading.strip() if heading else "")
        if not english_name:
            return None

        english_synonyms = self._split_synonyms(data.get("english synonyms", ""))
        german_synonyms = self._split_synonyms(data.get("german synonyms", ""))

        return VocabularyEntryDetail(
            identifier=data.get("id"),
            english_name=english_name,
            german_name=data.get("german name"),
            english_synonyms=english_synonyms,
            german_synonyms=german_synonyms,
            uri=data.get("uri"),
            attributes=data,
        )

    def _normalize_label(self, label: str) -> str:
        cleaned = self._clean_value(label).lower()
        cleaned = LABEL_NORMALIZATIONS.get(cleaned, cleaned)
        return cleaned

    def _clean_value(self, value: str) -> str:
        text = value.strip()
        if text.startswith("**") and text.endswith("**"):
            text = text[2:-2]
        if text.startswith("<") and text.endswith(">"):
            text = text[1:-1]
        text = text.replace(" ", " ")
        return re.sub(r"\s+", " ", text)

    def _split_synonyms(self, value: str) -> List[str]:
        if not value:
            return []
        parts = [part.strip() for part in value.split(",")]
        return [part for part in parts if part]

