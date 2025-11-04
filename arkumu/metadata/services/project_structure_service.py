"""Generate hierarchical manifests from project snapshot dataclasses."""

from __future__ import annotations

import sys
from dataclasses import MISSING, dataclass, fields, is_dataclass
from types import NoneType
from typing import Any, Iterable, List, Optional, Tuple, Type, get_args, get_origin, get_type_hints

from arkumu.projects import (
    ProjectActor,
    ProjectAlternateTitle,
    ProjectCatchphrase,
    ProjectDigitalObject,
    ProjectEvent,
    ProjectEventActor,
    ProjectInstitution,
    ProjectRecord,
    ProjectType,
)


@dataclass
class StructureField:
    """Leaf field description for display."""

    name: str
    label: str
    type_label: str
    required: bool
    repeatable: bool = False


@dataclass
class StructureNode:
    """Recursive manifest node for dataclass inspection."""

    name: str
    label: str
    description: Optional[str]
    repeatable: bool
    fields: List[StructureField]
    children: List["StructureNode"]


class ProjectStructureService:
    """Derive structured manifests from `ProjectRecord` dataclasses."""

    NODE_LABELS = {
        "ProjectRecord": "Projekt",
        "ProjectInstitution": "Institution",
        "ProjectType": "Projektart",
        "ProjectEvent": "Ereignis",
        "ProjectEventActor": "Ereignis-Akteur*in",
        "ProjectActor": "Akteur*in",
        "ProjectDigitalObject": "Digitales Objekt",
        "ProjectAlternateTitle": "Alternativtitel",
        "ProjectCatchphrase": "Schlagwort",
    }

    NODE_DESCRIPTIONS = {
        "ProjectRecord": "Zentrale Angaben und Relationen eines Projekts.",
        "ProjectInstitution": "Verknüpfte Institution, inklusive Codes.",
        "ProjectEvent": "Veranstaltungen, Orte und Zeiträume.",
        "ProjectActor": "Projektbeteiligte und deren Rollen.",
        "ProjectDigitalObject": "Verknüpfte Mediendateien.",
    }

    FIELD_LABELS = {
        ("ProjectRecord", "title"): "Titel",
        ("ProjectRecord", "subtitle"): "Untertitel",
        ("ProjectRecord", "description"): "Beschreibung",
        ("ProjectRecord", "year_range"): "Zeitraum",
        ("ProjectRecord", "categories"): "Kategorien",
        ("ProjectRecord", "catchphrases"): "Schlagworte",
        ("ProjectRecord", "institution_codes"): "Institutionscodes",
        ("ProjectRecord", "category_slugs"): "Kategorie-Slugs",
        ("ProjectInstitution", "label"): "Name",
        ("ProjectInstitution", "code"): "Code",
        ("ProjectInstitution", "uri"): "URI",
        ("ProjectType", "label"): "Bezeichnung",
        ("ProjectEvent", "name"): "Name",
        ("ProjectEvent", "description"): "Beschreibung",
        ("ProjectEvent", "location"): "Ort",
        ("ProjectEvent", "start"): "Beginn",
        ("ProjectEvent", "end"): "Ende",
        ("ProjectEvent", "type"): "Typ",
        ("ProjectEvent", "country"): "Land",
        ("ProjectEvent", "latitude"): "Breitengrad",
        ("ProjectEvent", "longitude"): "Längengrad",
        ("ProjectEventActor", "name"): "Name",
        ("ProjectEventActor", "roles"): "Rollen",
        ("ProjectActor", "name"): "Name",
        ("ProjectActor", "roles"): "Rollen",
        ("ProjectDigitalObject", "path"): "Dateipfad",
        ("ProjectDigitalObject", "uri"): "URI",
        ("ProjectAlternateTitle", "value"): "Titel",
        ("ProjectCatchphrase", "label"): "Label",
    }

    SIMPLE_TYPE_LABELS = {
        str: "Text",
        int: "Zahl",
        float: "Zahl",
        bool: "Bool",
    }

    def get_project_structure(self) -> StructureNode:
        """Return the hierarchical structure rooted at `ProjectRecord`."""

        return self._build_node(ProjectRecord, repeatable=False)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_node(self, dataclass_type: Type[Any], repeatable: bool) -> StructureNode:
        node_name = dataclass_type.__name__
        label = self.NODE_LABELS.get(node_name, self._humanize(node_name))
        description = self.NODE_DESCRIPTIONS.get(node_name)

        type_hints = self._type_hints(dataclass_type)

        node_fields: List[StructureField] = []
        children: List[StructureNode] = []

        for field in fields(dataclass_type):
            annotation = type_hints.get(field.name, field.type)
            resolved_annotation, optional = self._unwrap_optional(annotation)
            child_dataclass, is_collection = self._resolve_child_dataclass(resolved_annotation)

            if child_dataclass:
                child_node = self._build_node(child_dataclass, repeatable=is_collection)
                child_node.label = self.FIELD_LABELS.get(
                    (node_name, field.name),
                    child_node.label,
                )
                children.append(child_node)
                continue

            type_label = self._label_for_annotation(resolved_annotation)
            if is_collection:
                type_label = f"Liste · {type_label}"
            field_label = self.FIELD_LABELS.get((node_name, field.name), self._humanize(field.name))
            required = (
                not optional
                and field.default is MISSING
                and getattr(field, "default_factory", MISSING) is MISSING
            )

            node_fields.append(
                StructureField(
                    name=field.name,
                    label=field_label,
                    type_label=type_label,
                    required=required,
                    repeatable=is_collection,
                )
            )

        return StructureNode(
            name=node_name,
            label=label,
            description=description,
            repeatable=repeatable,
            fields=node_fields,
            children=children,
        )

    def _type_hints(self, dataclass_type: Type[Any]) -> dict:
        module_globals = sys.modules[dataclass_type.__module__].__dict__
        return get_type_hints(dataclass_type, globalns=module_globals)

    def _unwrap_optional(self, annotation: Any) -> Tuple[Any, bool]:
        origin = get_origin(annotation)
        if origin is None:
            return annotation, False

        args = get_args(annotation)
        if not args:
            return annotation, False

        # `Optional[T]` is represented as `Union[T, NoneType]`.
        non_none_args = [arg for arg in args if arg is not NoneType and arg is not type(None)]
        if len(non_none_args) == 1 and len(non_none_args) != len(args):
            return non_none_args[0], True

        return annotation, False

    def _resolve_child_dataclass(self, annotation: Any) -> Tuple[Optional[Type[Any]], bool]:
        origin = get_origin(annotation)
        if origin in (list, List, Iterable, tuple, set):
            args = get_args(annotation)
            inner = args[0] if args else Any
            inner_type, _ = self._unwrap_optional(inner)
            if self._is_dataclass_type(inner_type):
                return inner_type, True
            return None, True
        if self._is_dataclass_type(annotation):
            return annotation, False
        return None, False

    def _is_dataclass_type(self, candidate: Any) -> bool:
        return isinstance(candidate, type) and is_dataclass(candidate)

    def _label_for_annotation(self, annotation: Any) -> str:
        if isinstance(annotation, type) and annotation in self.SIMPLE_TYPE_LABELS:
            return self.SIMPLE_TYPE_LABELS[annotation]
        if getattr(annotation, "__name__", None):
            return self.NODE_LABELS.get(annotation.__name__, self._humanize(annotation.__name__))
        return self._humanize(str(annotation))

    def _humanize(self, raw: str) -> str:
        cleaned = raw.replace("_", " ")
        result: List[str] = []
        last_index = 0
        for index, char in enumerate(cleaned):
            if char.isupper() and index != 0 and not cleaned[index - 1].isupper():
                result.append(cleaned[last_index:index])
                last_index = index
        result.append(cleaned[last_index:])
        return " ".join(part.capitalize() for part in result if part)
