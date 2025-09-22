"""Utilities for parsing Arkumu domain model Markdown into structured schemas."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from django.utils import timezone

from arkumu.common.uri_utils import slugify_uri_part

FIELD_MAP: Dict[str, str] = {
    "English Name of Class": "english_name",
    "German Name of Class": "german_name",
    "URI": "uri",
    "English Description": "english_description",
    "German Description": "german_description",
    "Properties (English Naming)": "properties_en",
    "Properties (German Naming)": "properties_de",
}

MARKDOWN_LINK_PATTERN = re.compile(r"\[(?P<label>[^\]]+)\]\([^\)]+\)")
PROPERTY_PATTERN = re.compile(
    r"\[(?P<name>[^\]]+)\]\([^\)]+\)\s*⇒\s*\[(?P<label>[^\]]+)\]"
)


@dataclass
class ClassSchema:
    """Represents a single class extracted from the Markdown source."""

    identifier: str
    english_name: str
    german_name: str
    uri: str
    descriptions: Dict[str, str]
    properties: Dict[str, List[Dict[str, str]]]

    def to_dict(self) -> Dict[str, object]:
        return {
            "id": self.identifier,
            "uri": self.uri,
            "names": {
                "en": self.english_name,
                "de": self.german_name,
            },
            "descriptions": self.descriptions,
            "properties": self.properties,
        }


class ArkumuModelMarkdownParser:
    """Parse Arkumu Markdown definitions into structured class schemas."""

    def parse_file(self, markdown_path: Path | str) -> List[ClassSchema]:
        path = Path(markdown_path)
        content = path.read_text(encoding="utf-8")
        return self.parse_text(content)

    def parse_text(self, content: str) -> List[ClassSchema]:
        classes: List[ClassSchema] = []
        current: Optional[Dict[str, object]] = None

        for line in content.splitlines():
            header = line.strip()
            if header.startswith("### "):
                if current:
                    schema = self._build_schema(current)
                    if schema:
                        classes.append(schema)
                current = {"title": header[4:].strip(), "rows": []}
                continue

            if not current:
                continue

            if not header or header.startswith("---"):
                continue

            if header.startswith("|||") or header.startswith("|---"):
                continue

            if header.startswith("|") and header.endswith("|"):
                cells = [cell.strip() for cell in header.strip("|").split("|")]
                if len(cells) >= 2:
                    current.setdefault("rows", []).append((cells[0], cells[1]))

        if current:
            schema = self._build_schema(current)
            if schema:
                classes.append(schema)

        return classes

    def _build_schema(self, raw: Dict[str, object]) -> Optional[ClassSchema]:
        rows: Iterable[tuple[str, str]] = raw.get("rows", [])  # type: ignore[assignment]
        data: Dict[str, object] = {}
        for header, value in rows:
            key = self._normalize_header(header)
            mapped = FIELD_MAP.get(key)
            if not mapped:
                continue
            cleaned_value = self._clean_cell(value)
            if mapped in {"properties_en", "properties_de"}:
                data[mapped] = self._parse_properties(value)
            else:
                data[mapped] = cleaned_value

        english_name = data.get("english_name")
        german_name = data.get("german_name")
        uri = data.get("uri")
        if not (english_name and german_name and uri):
            return None

        identifier = slugify_uri_part(str(english_name))
        descriptions = {
            "en": str(data.get("english_description", "")),
            "de": str(data.get("german_description", "")),
        }
        properties = {
            "en": data.get("properties_en", []),
            "de": data.get("properties_de", []),
        }

        return ClassSchema(
            identifier=identifier,
            english_name=str(english_name),
            german_name=str(german_name),
            uri=str(uri),
            descriptions=descriptions,
            properties=properties,
        )

    def _normalize_header(self, cell: str) -> str:
        text = self._clean_cell(cell)
        return text.strip()

    def _clean_cell(self, cell: str) -> str:
        text = cell.strip()
        text = text.replace("**", "")
        text = text.replace("<br/>", " ")
        text = MARKDOWN_LINK_PATTERN.sub(lambda m: m.group("label"), text)
        text = text.replace("⇒", "⇒")
        text = text.strip()
        if text.startswith("<") and text.endswith(">"):
            text = text[1:-1]
        return re.sub(r"\s+", " ", text)

    def _parse_properties(self, cell: str) -> List[Dict[str, str]]:
        raw = cell.replace("<br/>", "\n")
        entries: List[Dict[str, str]] = []
        for line in raw.split("\n"):
            line = line.strip()
            if not line:
                continue
            match = PROPERTY_PATTERN.search(line)
            if match:
                entries.append(
                    {
                        "name": match.group("name").strip(),
                        "label": match.group("label").strip(),
                    }
                )
                continue
            parts = [piece.strip() for piece in line.split("⇒")]
            if len(parts) == 2:
                entries.append({"name": parts[0], "label": parts[1]})
            else:
                entries.append({"name": line, "label": line})
        return entries


class ArkumuModelExportService:
    """High-level service that exposes the Markdown parsing as a JSON export."""

    def __init__(self, parser: Optional[ArkumuModelMarkdownParser] = None) -> None:
        self.parser = parser or ArkumuModelMarkdownParser()

    def build_schema(self, markdown_path: Path | str) -> Dict[str, object]:
        classes = [schema.to_dict() for schema in self.parser.parse_file(markdown_path)]
        return {
            "generated_at": timezone.now().isoformat(),
            "classes": classes,
        }

    def export_json(
        self,
        markdown_path: Path | str,
        *,
        indent: Optional[int] = 2,
        payload: Optional[Dict[str, object]] = None,
    ) -> str:
        if payload is None:
            payload = self.build_schema(markdown_path)
        return json.dumps(payload, indent=indent, ensure_ascii=False)
