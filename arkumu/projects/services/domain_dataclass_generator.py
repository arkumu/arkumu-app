"""Generate Python dataclasses from the Arkumu domain markdown model."""

from __future__ import annotations

import re
from urllib.parse import urlparse
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from arkumu.metadata.services.controlled_vocabulary_detail_parser import (
    ControlledVocabularyDetailParser,
)
from arkumu.common.uri_utils import slugify_uri_part
from arkumu.metadata.services.domain_schema_parser import ArkumuModelExportService
from arkumu.metadata.services.property_markdown_parser import (
    PropertyMarkdownParser,
    PropertyDefinition,
)


@dataclass
class GeneratedField:
    """Definition of a dataclass field."""

    name: str
    label_en: str
    label_de: Optional[str]
    source_name_en: str
    source_name_de: Optional[str]
    predicate_uri: Optional[str] = None
    graph_representation: Optional[str] = None
    property_slug: Optional[str] = None
    cardinality: str = "repeatable"
    value_type: Optional[str] = None
    vocabulary_slug: Optional[str] = None

    def render(self, indent: str = "    ") -> str:
        metadata_parts = [
            f"'source_en_name': '{self.source_name_en}'",
            f"'label_en': '{self.label_en}'",
        ]
        if self.source_name_de:
            metadata_parts.append(f"'source_de_name': '{self.source_name_de}'")
        if self.label_de:
            metadata_parts.append(f"'label_de': '{self.label_de}'")
        if self.predicate_uri:
            metadata_parts.append(f"'predicate_uri': '{self.predicate_uri}'")
        if self.graph_representation:
            metadata_parts.append(f"'graph_id': '{self.graph_representation}'")
        if self.property_slug:
            metadata_parts.append(f"'property_slug': '{self.property_slug}'")
        if self.cardinality:
            metadata_parts.append(f"'cardinality': '{self.cardinality}'")
        if self.value_type:
            metadata_parts.append(f"'value_type': '{self.value_type}'")
        if self.vocabulary_slug:
            metadata_parts.append(f"'vocabulary': '{self.vocabulary_slug}'")
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

    def __init__(
        self,
        export_service: Optional[ArkumuModelExportService] = None,
        property_parser: Optional[PropertyMarkdownParser] = None,
        vocabulary_parser: Optional[ControlledVocabularyDetailParser] = None,
    ) -> None:
        self.export_service = export_service or ArkumuModelExportService()
        self.property_parser = property_parser or PropertyMarkdownParser()
        self._property_map: Dict[str, PropertyDefinition] = {}
        self.vocabulary_parser = vocabulary_parser or ControlledVocabularyDetailParser()
        self._vocabulary_map: Dict[str, Dict[str, str]] = {}
        self._vocabulary_by_entity: Dict[str, list[str]] = {}

    def build_module(self, markdown_path: Path | str) -> str:
        payload = self.export_service.build_schema(markdown_path)
        property_definitions = self.property_parser.parse_file(markdown_path)
        self._property_map = {
            definition.normalized_key: definition for definition in property_definitions
        }
        vocab_dir = Path(markdown_path).parent
        self._vocabulary_map = self._load_vocabulary_map(vocab_dir)
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
            prop_def = self._property_map.get(normalized_key)
            fields.append(
                GeneratedField(
                    name=snake_name,
                    label_en=label_en,
                    label_de=str(de_entry.get("label")) if de_entry else None,
                    source_name_en=name_en_raw,
                    source_name_de=str(de_entry.get("name")) if de_entry else None,
                    predicate_uri=prop_def.uri if prop_def else None,
                    graph_representation=prop_def.graph_representation if prop_def else None,
                    property_slug=prop_def.slug if prop_def else None,
                    cardinality=(prop_def.cardinality or "repeatable") if prop_def else "repeatable",
                    value_type=prop_def.value_type if prop_def else None,
                    vocabulary_slug=self._match_vocabulary(english_name, label_en),
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

    def _load_vocabulary_map(self, vocab_dir: Path) -> Dict[str, Dict[str, str]]:
        mapping: Dict[str, Dict[str, str]] = {}
        for file_path in vocab_dir.glob("*controlled vocabulary*.md"):
            try:
                document = self.vocabulary_parser.parse_file(file_path)
            except Exception:
                continue
            entity_key = self._normalize_vocab_key(document.entity or "")
            if not entity_key:
                continue
            store = mapping.setdefault(entity_key, {})
            vocab_slug = self._infer_vocabulary_slug(document, file_path)
            labels = [vocab_slug.replace('-', ' ')] if vocab_slug else []
            if labels and vocab_slug:
                self._register_vocab_labels(store, vocab_slug, labels)
        return mapping

    def _register_vocab_labels(self, store: Dict[str, str], slug: str, labels: Iterable[str]) -> None:
        for label in labels:
            key = self._normalize_vocab_key(label)
            if not key:
                continue
            store.setdefault(key, slug)
            if key.endswith('s'):
                store.setdefault(key[:-1], slug)
            if key.endswith('ies'):
                store.setdefault(key[:-3] + 'y', slug)

    def _match_vocabulary(self, class_english_name: str, field_label: str) -> Optional[str]:
        entity_key = self._normalize_vocab_key(class_english_name)
        vocab_entries = self._vocabulary_map.get(entity_key)
        if not vocab_entries:
            return None

        label_key = self._normalize_vocab_key(field_label)
        if label_key in vocab_entries:
            return vocab_entries[label_key]

        # attempt plural variations
        plural_key = self._normalize_vocab_key(field_label + 's')
        if plural_key in vocab_entries:
            return vocab_entries[plural_key]

        plural_es_key = self._normalize_vocab_key(field_label + 'es')
        if plural_es_key in vocab_entries:
            return vocab_entries[plural_es_key]

        return None

    def _normalize_vocab_key(self, value: str) -> str:
        value = value or ""
        return re.sub(r"[^a-z0-9]", "", value.lower())

    def _infer_vocabulary_slug(self, document, file_path: Path) -> Optional[str]:
        for entry in document.entries:
            if entry.uri:
                parsed = urlparse(entry.uri)
                segment = parsed.path.rstrip('/').split('/')[-1]
                if segment:
                    return segment
        stem = file_path.stem
        if 'controlled vocabulary - ' in stem:
            slug_source = stem.split('controlled vocabulary - ', 1)[1]
            slug_source = slug_source.split('(')[0].strip()
            return slugify_uri_part(slug_source)
        return None
