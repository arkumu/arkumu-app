"""Parse property definitions from the Arkumu domain markdown."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from arkumu.common.uri_utils import slugify_uri_part


@dataclass
class PropertyDefinition:
    heading: str
    english_name: str
    german_name: str
    uri: Optional[str]
    graph_representation: Optional[str]
    metadata: Dict[str, str]
    vocabulary_slug: Optional[str] = None

    @property
    def slug(self) -> str:
        source = self.english_name or self.heading
        return slugify_uri_part(source)

    @property
    def normalized_key(self) -> str:
        return self.english_name.strip().lower()

    @property
    def cardinality(self) -> Optional[str]:
        return self.metadata.get('cardinality')

    @property
    def value_type(self) -> Optional[str]:
        return self.metadata.get('value type')


class PropertyMarkdownParser:
    """Scan markdown for property blocks and extract key columns."""

    HEADER_PREFIX = "### "
    TABLE_ROW_PATTERN = re.compile(r"^\|.*\|$")

    def parse_file(self, markdown_path: Path | str) -> List[PropertyDefinition]:
        content = Path(markdown_path).read_text(encoding="utf-8")
        return self.parse_text(content)

    def parse_text(self, content: str) -> List[PropertyDefinition]:
        definitions: List[PropertyDefinition] = []
        current_heading: Optional[str] = None
        table_rows: List[str] = []

        for raw_line in content.splitlines():
            line = raw_line.rstrip()
            if line.startswith(self.HEADER_PREFIX):
                if current_heading and table_rows:
                    definition = self._build_definition(current_heading, table_rows)
                    if definition:
                        definitions.append(definition)
                    table_rows = []
                current_heading = line[len(self.HEADER_PREFIX) :].strip()
                continue

            if current_heading and self.TABLE_ROW_PATTERN.match(line):
                table_rows.append(line)
                continue

            if table_rows and line.strip() == "":
                if current_heading:
                    definition = self._build_definition(current_heading, table_rows)
                    if definition:
                        definitions.append(definition)
                table_rows = []
                current_heading = None

        if current_heading and table_rows:
            definition = self._build_definition(current_heading, table_rows)
            if definition:
                definitions.append(definition)

        return definitions

    def _build_definition(self, heading: str, rows: List[str]) -> Optional[PropertyDefinition]:
        if len(rows) <= 2:
            return None

        metadata: Dict[str, str] = {}
        # Skip header & separator
        for row in rows[2:]:
            cells = [cell.strip() for cell in row.strip("|").split("|")]
            if len(cells) < 2:
                continue
            label, value = cells[0], cells[1]
            cleaned_label = self._clean(label)
            cleaned_value = self._clean(value)
            metadata[cleaned_label.lower()] = cleaned_value

        english = metadata.get("english name of property")
        german = metadata.get("german name of property")
        uri = metadata.get("uri")
        graph = metadata.get("graph representation")

        if not english:
            return None

        return PropertyDefinition(
            heading=heading,
            english_name=english,
            german_name=german or "",
            uri=uri,
            graph_representation=graph,
            metadata=metadata,
        )

    def _clean(self, value: str) -> str:
        text = value.strip()
        if text.startswith("**") and text.endswith("**"):
            text = text[2:-2]
        if text.startswith("<") and text.endswith(">"):
            text = text[1:-1]
        return re.sub(r"\s+", " ", text)
