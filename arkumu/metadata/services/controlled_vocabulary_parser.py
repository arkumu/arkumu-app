"""Parse controlled vocabulary markdown into dataclasses."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from arkumu.common.uri_utils import slugify_uri_part

MARKDOWN_LINK_RE = re.compile(r"\[(?P<label>[^\]]+)\]\((?P<url>[^\)]*)\)")
TABLE_ROW_RE = re.compile(r"^\|.*\|$")


@dataclass
class ControlledVocabularyReference:
    label: str
    url: Optional[str]


@dataclass
class ControlledVocabularyEntry:
    """Single controlled vocabulary definition."""

    english_name: str
    german_name: str
    entity: str
    wiki_url: Optional[str]
    english_path: Optional[str]
    german_path: Optional[str]
    slug: Optional[str]


@dataclass
class ControlledVocabularySection:
    """Grouping of vocabulary entries (e.g. Value Lists, Taxonomies)."""

    title: str
    entries: List[ControlledVocabularyEntry] = field(default_factory=list)
    references: List[ControlledVocabularyReference] = field(default_factory=list)


@dataclass
class ControlledVocabularyDocument:
    sections: List[ControlledVocabularySection]

    def to_dict(self) -> Dict[str, object]:
        return {
            "sections": [
                {
                    "title": section.title,
                    "entries": [asdict(entry) for entry in section.entries],
                    "references": [asdict(ref) for ref in section.references],
                }
                for section in self.sections
            ]
        }


class ControlledVocabularyMarkdownParser:
    """Parse markdown tables describing Arkumu controlled vocabularies."""

    def parse_file(self, markdown_path: Path | str) -> ControlledVocabularyDocument:
        content = Path(markdown_path).read_text(encoding="utf-8")
        return self.parse_text(content)

    def parse_text(self, content: str) -> ControlledVocabularyDocument:
        sections: List[ControlledVocabularySection] = []
        current_section: Optional[ControlledVocabularySection] = None
        table_buffer: List[str] = []

        for raw_line in content.splitlines():
            line = raw_line.rstrip()
            header_match = self._section_header(line)
            if header_match:
                if current_section and table_buffer:
                    current_section.entries.extend(self._parse_table(table_buffer))
                    table_buffer.clear()
                current_section = ControlledVocabularySection(title=header_match)
                sections.append(current_section)
                continue

            if not current_section:
                continue

            if TABLE_ROW_RE.match(line):
                table_buffer.append(line)
                continue

            if table_buffer:
                current_section.entries.extend(self._parse_table(table_buffer))
                table_buffer.clear()

            reference = self._parse_reference(line)
            if reference:
                current_section.references.append(reference)

        if current_section and table_buffer:
            current_section.entries.extend(self._parse_table(table_buffer))

        return ControlledVocabularyDocument(sections=sections)

    def _section_header(self, line: str) -> Optional[str]:
        if line.startswith("## "):
            return line.lstrip('#').strip()
        return None

    def _parse_reference(self, line: str) -> Optional[ControlledVocabularyReference]:
        stripped = line.strip()
        if not stripped.startswith("* "):
            return None
        match = MARKDOWN_LINK_RE.search(stripped)
        if match:
            return ControlledVocabularyReference(
                label=match.group("label"),
                url=match.group("url") or None,
            )
        return ControlledVocabularyReference(label=stripped.lstrip("* "), url=None)

    def _parse_table(self, rows: List[str]) -> List[ControlledVocabularyEntry]:
        if len(rows) <= 2:
            return []
        data_rows = rows[2:]  # skip header + separator
        entries: List[ControlledVocabularyEntry] = []
        for row in data_rows:
            columns = [col.strip() for col in row.strip('|').split('|')]
            if len(columns) < 4:
                continue
            english_name, german_name, entity, link = columns[:4]
            english_label, english_path = self._strip_markdown_link(english_name)
            german_label, german_path = self._strip_markdown_link(german_name)
            entity_label, _ = self._strip_markdown_link(entity)
            _, wiki_url = self._strip_markdown_link(link)
            slug_source = english_path.rsplit('/', 1)[-1] if english_path and '/' in english_path else english_path or english_label
            slug = slugify_uri_part(slug_source)
            entries.append(
                ControlledVocabularyEntry(
                    english_name=english_label,
                    german_name=german_label,
                    entity=entity_label,
                    wiki_url=wiki_url,
                    english_path=english_path,
                    german_path=german_path,
                    slug=slug,
                )
            )
        return entries

    def _strip_markdown_link(self, value: str) -> tuple[str, Optional[str]]:
        match = MARKDOWN_LINK_RE.search(value)
        if match:
            return match.group("label").strip(), (match.group("url") or None)
        return value.strip(), None


class ControlledVocabularyExportService:
    """Serialize the vocabulary document to JSON."""

    def __init__(self, parser: Optional[ControlledVocabularyMarkdownParser] = None) -> None:
        self.parser = parser or ControlledVocabularyMarkdownParser()

    def build_document(self, markdown_path: Path | str) -> Dict[str, object]:
        return self.parser.parse_file(markdown_path).to_dict()

    def export_json(self, markdown_path: Path | str, *, indent: Optional[int] = 2) -> str:
        document = self.build_document(markdown_path)
        return json.dumps(document, indent=indent, ensure_ascii=False)
