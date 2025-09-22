"""Generate Python dataclasses from the Arkumu domain markdown model."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from arkumu.metadata.services.domain_schema_parser import ArkumuModelExportService


@dataclass
class GeneratedField:
    """Definition of a dataclass field."""

    name: str
    label_en: str
    label_de: Optional[str]
    source_name_en: str
    source_name_de: Optional[str]

    def render(self, indent: str = "    ") -> str:
        metadata_parts = [
            f"'source_en_name': '{self.source_name_en}'",
            f"'label_en': '{self.label_en}'",
        ]
        if self.source_name_de:
            metadata_parts.append(f"'source_de_name': '{self.source_name_de}'")
        if self.label_de:
            metadata_parts.append(f"'label_de': '{self.label_de}'")
        metadata = ', '.join(metadata_parts)
        return (
            f"{indent}{self.name}: list[str] = field(\n"
            f"{indent}    default_factory=list,\n"
            f"{indent}    metadata={{ {metadata} }},\n"
            f"{indent})"
        )


@dataclass
class GeneratedClass:
    """Definition of a generated dataclass."""

    name: str
    docstring: str
    fields: List[GeneratedField]

    def render(self) -> str:
        body_lines = [f"@dataclass", f"class {self.name}(ArkumuEntity):", f"    \"\"\"{self.docstring}\"\"\""]
        if not self.fields:
            body_lines.append("    pass")
        else:
            for field_def in self.fields:
                body_lines.append(field_def.render())
        return "\n".join(body_lines)


class DomainDataclassGenerator:
    """Generate dataclass module strings from the Arkumu domain markdown."""

    def __init__(self, export_service: Optional[ArkumuModelExportService] = None) -> None:
        self.export_service = export_service or ArkumuModelExportService()

    def build_module(self, markdown_path: Path | str) -> str:
        payload = self.export_service.build_schema(markdown_path)
        classes = [
            self._build_class_definition(class_payload)
            for class_payload in payload.get("classes", [])
        ]
        header = self._module_header()
        body = "\n\n".join(cls.render() for cls in classes if cls)
        return f"{header}\n\n{body}\n"

    def write_module(self, markdown_path: Path | str, output_path: Path | str) -> None:
        content = self.build_module(markdown_path)
        Path(output_path).write_text(content, encoding="utf-8")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _module_header(self) -> str:
        return "\n".join(
            [
                '"""Auto-generated dataclasses from Arkumu domain model."""',
                "from __future__ import annotations",
                "",
                "from dataclasses import dataclass, field",
                "",
                "",
                "@dataclass",
                "class ArkumuEntity:",
                "    uri: str | None = None",
                "    identifiers: list[str] = field(default_factory=list)",
            ]
        )

    def _build_class_definition(self, payload: Dict[str, object]) -> GeneratedClass:
        english_name = str(payload["names"]["en"])  # type: ignore[index]
        class_name = self._to_pascal_case(english_name)
        description_en = str(payload.get("descriptions", {}).get("en", ""))
        description_de = str(payload.get("descriptions", {}).get("de", ""))
        docstring = f"EN: {description_en}\nDE: {description_de}".strip()

        properties_en = payload.get("properties", {}).get("en", [])  # type: ignore[index]
        properties_de = payload.get("properties", {}).get("de", [])  # type: ignore[index]
        german_map = {
            self._normalize_property_name(prop.get("name", "")): prop
            for prop in properties_de
        }

        fields: List[GeneratedField] = []
        seen_names: set[str] = set()
        for prop in properties_en:
            name_en_raw = str(prop.get("name", ""))
            label_en = str(prop.get("label", name_en_raw))
            snake_name = self._make_unique(self._to_snake_case(label_en), seen_names)
            seen_names.add(snake_name)

            normalized_key = self._normalize_property_name(name_en_raw)
            de_entry = german_map.get(normalized_key)
            fields.append(
                GeneratedField(
                    name=snake_name,
                    label_en=label_en,
                    label_de=str(de_entry.get("label")) if de_entry else None,
                    source_name_en=name_en_raw,
                    source_name_de=str(de_entry.get("name")) if de_entry else None,
                )
            )

        return GeneratedClass(name=class_name, docstring=docstring, fields=fields)

    def _to_pascal_case(self, value: str) -> str:
        tokens = re.findall(r"[A-Za-z0-9]+", value)
        if not tokens:
            return "GeneratedClass"
        pascal = "".join(token.capitalize() for token in tokens)
        if pascal[0].isdigit():
            pascal = f"C{pascal}"
        return pascal

    def _to_snake_case(self, value: str) -> str:
        tokens = re.findall(r"[A-Za-z0-9]+", value)
        if not tokens:
            return "value"
        snake = "_".join(token.lower() for token in tokens)
        if snake[0].isdigit():
            snake = f"value_{snake}"
        return snake

    def _normalize_property_name(self, value: str) -> str:
        return re.sub(r"\s+", " ", value.strip().lower())

    def _make_unique(self, candidate: str, existing: Iterable[str]) -> str:
        if candidate not in existing:
            return candidate
        suffix = 2
        while f"{candidate}_{suffix}" in existing:
            suffix += 1
        return f"{candidate}_{suffix}"
