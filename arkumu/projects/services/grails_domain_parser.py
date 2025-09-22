"""Parse Grails domain classes and emit Python dataclass metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional


@dataclass
class GrailsField:
    name: str
    grails_type: str
    is_collection: bool = False

    def python_type(self, type_map: Dict[str, str]) -> str:
        base = self.grails_type
        optional = False
        if base.endswith("?"):
            base = base[:-1]
            optional = True
        python = type_map.get(base, "str")
        if self.is_collection:
            python = f"list[{python}]"
        elif optional:
            python = f"Optional[{python}]"
        return python


@dataclass
class GrailsDomainClass:
    package: str
    name: str
    fields: List[GrailsField] = field(default_factory=list)
    has_many: Dict[str, str] = field(default_factory=dict)
    belongs_to: List[str] = field(default_factory=list)


class GrailsDomainParser:
    """Lightweight Groovy domain parser tailored to Digikunst-style classes."""

    CLASS_RE = re.compile(r"class\s+(\w+)\b")
    PACKAGE_RE = re.compile(r"package\s+([\w\.]+)")
    FIELD_RE = re.compile(r"^\s*(?:def\s+)?([A-Za-z0-9_<>,]+)\s+([A-Za-z0-9_]+)\s*(?:=.*)?$")
    STATIC_ASSIGN_RE = re.compile(r"^\s*static\s+(\w+)\s*=\s*(.+)")

    def parse_file(self, path: Path | str) -> GrailsDomainClass:
        content = Path(path).read_text(encoding="utf-8")
        return self.parse_text(content)

    def parse_text(self, content: str) -> GrailsDomainClass:
        package = ""
        name = ""
        fields: List[GrailsField] = []
        has_many: Dict[str, str] = {}
        belongs_to: List[str] = []

        in_field_section = True
        lines = content.splitlines()
        total = len(lines)
        i = 0
        while i < total:
            raw_line = lines[i]
            line = raw_line.rstrip()
            if not package:
                pkg = self.PACKAGE_RE.match(line)
                if pkg:
                    package = pkg.group(1)
                    i += 1
                    continue
            cls = self.CLASS_RE.search(line)
            if cls:
                name = cls.group(1)
                i += 1
                continue
            if line.strip().startswith("static"):
                assign = self.STATIC_ASSIGN_RE.match(line)
                if assign:
                    key = assign.group(1)
                    value = assign.group(2)
                    if key in {"hasMany", "belongsTo"} and value.strip().endswith('[') and not value.strip().endswith(']'):
                        block = [value]
                        i += 1
                        depth = 1
                        while i < total and depth > 0:
                            block_line = lines[i].rstrip()
                            block.append(block_line)
                            depth += block_line.count('[')
                            depth -= block_line.count(']')
                            i += 1
                        value = "\n".join(block)
                    else:
                        i += 1
                    if key == "hasMany":
                        has_many.update(self._parse_map_literal(value))
                    elif key == "belongsTo":
                        belongs_to.extend(self._parse_belongs_to(value))
                in_field_section = False
                continue
            if in_field_section:
                match = self.FIELD_RE.match(line)
                if match and not line.strip().startswith("import"):
                    grails_type, field_name = match.groups()
                    if field_name in {"constraints", "mapping"}:
                        continue
                    fields.append(self._build_field(grails_type, field_name))
            i += 1

        return GrailsDomainClass(
            package=package,
            name=name,
            fields=fields,
            has_many=has_many,
            belongs_to=belongs_to,
        )

    def _build_field(self, grails_type: str, name: str) -> GrailsField:
        is_collection = False
        base_type = grails_type
        if base_type.startswith("List<") and base_type.endswith(">"):
            inner = base_type[5:-1].strip()
            base_type = inner
            is_collection = True
        elif base_type.lower() == "list":
            base_type = "String"
            is_collection = True
        return GrailsField(name=name, grails_type=base_type, is_collection=is_collection)

    def _parse_map_literal(self, literal: str) -> Dict[str, str]:
        body = literal.strip()
        if body.startswith('['):
            body = body[1:]
        if body.endswith(']'):
            body = body[:-1]
        pattern = re.compile(r"([A-Za-z0-9_]+)\s*:\s*([A-Za-z0-9_.<>]+)")
        return {key: value for key, value in pattern.findall(body)}

    def _parse_belongs_to(self, literal: str) -> List[str]:
        literal = literal.strip()
        if literal.startswith('[') and literal.endswith(']'):
            inner = literal[1:-1]
            return [item.strip() for item in inner.split(',') if item.strip()]
        return [literal]


class GrailsDataclassGenerator:
    """Render Python dataclasses from Grails domain metadata."""

    TYPE_MAP = {
        "String": "str",
        "Integer": "int",
        "Long": "int",
        "BigInteger": "int",
        "BigDecimal": "Decimal",
        "Boolean": "bool",
        "Date": "datetime",
        "LocalDateTime": "datetime",
        "LocalDate": "date",
        "Double": "float",
        "Float": "float",
    }

    def build_module(self, domains: Iterable[GrailsDomainClass]) -> str:
        header = self._header()
        body = "\n\n".join(self._render_class(domain) for domain in domains)
        return f"{header}\n\n{body}\n"

    def _header(self) -> str:
        return "\n".join(
            [
                '"""Auto-generated from Grails domain definitions."""',
                "from __future__ import annotations",
                "",
                "from dataclasses import dataclass, field",
                "from datetime import date, datetime",
                "from decimal import Decimal",
                "from typing import Optional",
            ]
        )

    def _render_class(self, domain: GrailsDomainClass) -> str:
        lines = [f"@dataclass", f"class {domain.name}:", f"    \"\"\"Generated from {domain.package}.{domain.name}\"\"\""]
        if not domain.fields:
            lines.append("    pass")
            return "\n".join(lines)
        for field_meta in domain.fields:
            py_type = field_meta.python_type(self.TYPE_MAP)
            default = "field(default_factory=list)" if field_meta.is_collection else "None"
            assignment = f"field(default_factory=list)" if field_meta.is_collection else "None"
            if field_meta.is_collection:
                lines.append(
                    f"    {field_meta.name}: {py_type} = field(default_factory=list)"
                )
            else:
                lines.append(f"    {field_meta.name}: Optional[{py_type}] = None")
        if domain.has_many:
            lines.append("    # hasMany")
            for key, value in domain.has_many.items():
                lines.append(f"    # {key} -> {value}")
        if domain.belongs_to:
            lines.append("    # belongsTo")
            for parent in domain.belongs_to:
                lines.append(f"    # {parent}")
        return "\n".join(lines)
