"""
Service helpers for creating and editing controlled vocabularies.

These functions encapsulate the logic required to map form data to RDF
resources and triples so views/templates remain thin.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple

from django.db import transaction
from django.db.models import Q

from arkumu.metadata.controlled_vocabularies.registry import (
    ColumnConfig,
    VocabularyConfig,
    column_to_field_name,
    get_vocabulary_config,
    XSD_BOOLEAN_URI,
)
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.services.canonical_graph_service import RDF_TYPE_URI


@dataclass(frozen=True)
class VocabularyEntrySummary:
    resource: Resource
    label: str
    slug: str
    synonyms: List[str]
    synonyms_by_language: Dict[str, List[str]]
    field_values: List[Tuple[str, List[str]]]


@dataclass
class VocabularySaveStats:
    triples_created: int = 0
    triples_deleted: int = 0


@dataclass
class VocabularySaveResult:
    resource: Resource
    stats: VocabularySaveStats


class ControlledVocabularyService:
    def __init__(self, vocab_key: str):
        self.vocab_key = vocab_key
        self.config = get_vocabulary_config(vocab_key)
        self.field_to_column = {
            column_to_field_name(column): column
            for column in self.config.columns.keys()
        }
        self.predicate_map = {
            column: column_config.predicate_uri
            for column, column_config in self.config.columns.items()
        }
        self.synonym_predicates = {
            column_config.predicate_uri: column_config
            for column_config in self.config.columns.values()
            if column_config.split
        }

    # ------------------------------------------------------------------
    # Listing & retrieval helpers
    # ------------------------------------------------------------------

    def list_entries(self, search: Optional[str] = None) -> List[VocabularyEntrySummary]:
        type_triples = (
            Triple.objects.filter(
                predicate__uri=RDF_TYPE_URI,
                object__uri=self.config.class_uri,
                source__isnull=True,
            )
            .select_related("subject")
        )
        if search:
            type_triples = type_triples.filter(
                Q(subject__name__icontains=search) | Q(subject__uri__icontains=search)
            )

        entries: List[VocabularyEntrySummary] = []
        for triple in type_triples:
            resource = triple.subject
            label = resource.name or self._derive_label_from_triples(resource)
            slug = self.extract_slug(resource.uri or "")
            synonyms_map = self._collect_synonyms(resource)
            field_values = self._collect_field_values(resource)
            synonyms = [value for values in synonyms_map.values() for value in values]
            entries.append(
                VocabularyEntrySummary(
                    resource=resource,
                    label=label,
                    slug=slug,
                    synonyms=synonyms,
                    synonyms_by_language=synonyms_map,
                    field_values=field_values,
                )
            )
        entries.sort(key=lambda item: item.label.lower())
        return entries

    def get_reference_choices(self, exclude: Optional[Resource] = None) -> List[Tuple[str, str]]:
        resources = (
            Resource.objects.filter(
                subject_triples__predicate__uri=RDF_TYPE_URI,
                subject_triples__object__uri=self.config.class_uri,
                subject_triples__source__isnull=True,
            )
            .distinct()
        )
        options: List[Tuple[str, str]] = []
        for resource in resources:
            if exclude and resource.id == exclude.id:
                continue
            label = resource.name or self.extract_slug(resource.uri or "") or str(resource.uri)
            options.append((str(resource.id), label))
        options.sort(key=lambda item: item[1].lower())
        return options

    def get_initial(self, resource: Resource) -> Dict[str, object]:
        initial: Dict[str, object] = {}
        initial["slug"] = self.extract_slug(resource.uri or "")
        predicate_values = self._collect_predicate_map(resource)

        for column, column_config in self.config.columns.items():
            field_name = column_to_field_name(column)
            objects = predicate_values.get(column_config.predicate_uri, [])

            if column_config.value_type == "reference":
                initial[field_name] = str(objects[0].id) if objects else ""
            elif column_config.value_type == "boolean":
                if objects:
                    value = (objects[0].value or "").strip().lower()
                    initial[field_name] = value == "true"
                else:
                    initial[field_name] = False
            elif column_config.value_type == "iri":
                initial[field_name] = objects[0].uri if objects else ""
            elif column_config.split:
                values = [self._object_to_value(obj) for obj in objects]
                initial[field_name] = "\n".join(values)
            else:
                initial[field_name] = self._object_to_value(objects[0]) if objects else ""

        return initial

    # ------------------------------------------------------------------
    # Save workflow
    # ------------------------------------------------------------------

    @transaction.atomic
    def save(
        self,
        cleaned_data: Dict[str, object],
        resource: Optional[Resource] = None,
        *,
        with_stats: bool = False,
    ) -> Resource | VocabularySaveResult:
        slug = (cleaned_data.get("slug") or "").strip()
        if not slug:
            raise ValueError("Missing slug for controlled vocabulary entry.")
        canonical_uri = self.build_canonical_uri(slug)

        if resource is None:
            if Resource.objects.filter(uri=canonical_uri).exists():
                raise ValueError("An entry with this canonical URI already exists.")
            resource = Resource(
                uri=canonical_uri,
                canonical_uri=canonical_uri,
                resource_type=ResourceType.ENTITY,
            )
        else:
            if Resource.objects.filter(uri=canonical_uri).exclude(pk=resource.pk).exists():
                raise ValueError("Another entry already uses this canonical URI.")
            resource.uri = canonical_uri
            resource.canonical_uri = canonical_uri
            resource.resource_type = ResourceType.ENTITY

        stats = VocabularySaveStats()

        label = self._label_from_cleaned_data(cleaned_data)
        if label:
            resource.name = label
        resource.save()

        predicate_cache: Dict[str, Resource] = {}
        touched_predicates: Dict[Resource, Set[int]] = {}

        Triple.objects.filter(
            subject=resource,
            source=None,
            is_derived=True,
        ).delete()

        rdf_type_predicate = self._ensure_resource(RDF_TYPE_URI, ResourceType.PROPERTY)
        class_resource = self._ensure_resource(self.config.class_uri, ResourceType.CLASS)
        if self._ensure_triple(resource, rdf_type_predicate, class_resource):
            stats.triples_created += 1
        touched_predicates[rdf_type_predicate] = {class_resource.id}

        for column, column_config in self.config.columns.items():
            field_name = column_to_field_name(column)
            value = cleaned_data.get(field_name)
            predicate_resource = predicate_cache.get(column_config.predicate_uri)
            if not predicate_resource:
                predicate_resource = self._ensure_resource(
                    column_config.predicate_uri,
                    ResourceType.PROPERTY,
                )
                predicate_cache[column_config.predicate_uri] = predicate_resource

            if value in (None, "", []):
                touched_predicates[predicate_resource] = set()
                continue

            result = self._apply_form_value(resource, predicate_resource, column_config, value)
            touched_predicates[predicate_resource] = result["object_ids"]
            stats.triples_created += result.get("triples_created", 0)

        stats.triples_deleted += self._cleanup_outdated_triples(resource, touched_predicates)

        if with_stats:
            return VocabularySaveResult(resource=resource, stats=stats)
        return resource

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def build_canonical_uri(self, slug: str) -> str:
        base = self.config.class_uri.rstrip("/")
        return f"{base}/{slug}"

    def extract_slug(self, uri: str) -> str:
        if not uri:
            return ""
        base = self.config.class_uri.rstrip("/") + "/"
        if uri.startswith(base):
            return uri[len(base):]
        return uri.rsplit("/", 1)[-1]

    def _label_from_cleaned_data(self, cleaned_data: Dict[str, object]) -> str:
        for column in self.config.label_priority:
            field_name = column_to_field_name(column)
            value = cleaned_data.get(field_name)
            if isinstance(value, bool):
                continue
            if value:
                if isinstance(value, str):
                    candidate = value.strip()
                else:
                    candidate = str(value).strip()
                if candidate:
                    if "\n" in candidate:
                        return candidate.splitlines()[0].strip()
                    return candidate
        return ""

    def _collect_predicate_map(self, resource: Resource) -> Dict[str, List[Resource]]:
        predicate_uris = {config.predicate_uri for config in self.config.columns.values()}
        triples = (
            Triple.objects.filter(
                subject=resource,
                predicate__uri__in=predicate_uris,
                source__isnull=True,
            )
            .select_related("object", "predicate")
        )
        mapping: Dict[str, List[Resource]] = {}
        for triple in triples:
            mapping.setdefault(triple.predicate.uri, []).append(triple.object)
        return mapping

    def _collect_synonyms(self, resource: Resource) -> Dict[str, List[str]]:
        if not self.synonym_predicates:
            return {}

        triples = Triple.objects.filter(
            subject=resource,
            predicate__uri__in=self.synonym_predicates.keys(),
            source__isnull=True,
        ).select_related("object", "predicate")

        synonyms: Dict[str, List[str]] = {}
        for triple in triples:
            config = self.synonym_predicates.get(triple.predicate.uri)
            if not config:
                continue
            language_key = config.language or "other"
            value = self._object_to_value(triple.object)
            if not value:
                continue
            synonyms.setdefault(language_key, []).append(value)

        for values in synonyms.values():
            values.sort(key=lambda item: item.lower())
        return synonyms

    def _collect_field_values(self, resource: Resource) -> List[Tuple[str, List[str]]]:
        predicate_map = self._collect_predicate_map(resource)
        field_values: List[Tuple[str, List[str]]] = []
        for column, config in self.config.columns.items():
            objects = predicate_map.get(config.predicate_uri, [])
            formatted = self._format_objects(config, objects)
            if formatted:
                label = (config.label or column).strip()
                field_values.append((label, formatted))
        return field_values

    def _derive_label_from_triples(self, resource: Resource) -> str:
        predicate_map = self._collect_predicate_map(resource)
        for column in self.config.label_priority:
            if column in self.config.columns:
                predicate_uri = self.config.columns[column].predicate_uri
                if predicate_uri in predicate_map and predicate_map[predicate_uri]:
                    value = self._object_to_value(predicate_map[predicate_uri][0])
                    if value:
                        return value
        return resource.uri or str(resource.id)

    def _apply_form_value(
        self,
        subject: Resource,
        predicate: Resource,
        config: ColumnConfig,
        raw_value: object,
    ) -> Dict[str, object]:
        object_ids: Set[int] = set()
        values: Iterable[str]
        triples_created = 0

        if config.value_type == "reference":
            if not raw_value:
                return {"object_ids": set(), "triples_created": 0}
            target = self._resolve_reference(str(raw_value))
            if self._ensure_triple(subject, predicate, target):
                triples_created += 1
            object_ids.add(target.id)
            return {"object_ids": object_ids, "triples_created": triples_created}

        if config.value_type == "boolean":
            bool_value = bool(raw_value)
            literal = self._ensure_literal("true" if bool_value else "false", None, XSD_BOOLEAN_URI)
            if self._ensure_triple(subject, predicate, literal):
                triples_created += 1
            object_ids.add(literal.id)
            return {"object_ids": object_ids, "triples_created": triples_created}

        if config.value_type == "iri":
            iri_value = str(raw_value).strip()
            if not iri_value:
                return {"object_ids": set(), "triples_created": 0}
            iri_resource = self._ensure_resource(iri_value, ResourceType.IRI)
            if self._ensure_triple(subject, predicate, iri_resource):
                triples_created += 1
            object_ids.add(iri_resource.id)
            return {"object_ids": object_ids, "triples_created": triples_created}

        if isinstance(raw_value, str):
            values = self._split_form_values(raw_value, config) if config.split else [raw_value]
        else:
            values = [str(raw_value)]

        for value in values:
            cleaned = value.strip()
            if not cleaned:
                continue
            literal = self._ensure_literal(
                cleaned,
                config.language,
                config.datatype,
            )
            if self._ensure_triple(subject, predicate, literal):
                triples_created += 1
            object_ids.add(literal.id)

        return {"object_ids": object_ids, "triples_created": triples_created}

    def _split_form_values(self, raw_value: str, config: ColumnConfig) -> List[str]:
        if not raw_value:
            return []
        tokens: List[str] = []
        for fragment in raw_value.replace("\r", "\n").split("\n"):
            fragment = fragment.strip()
            if not fragment:
                continue
            if config.split_delimiter and config.split_delimiter in fragment:
                tokens.extend(item.strip() for item in fragment.split(config.split_delimiter) if item.strip())
            else:
                tokens.append(fragment)
        if not tokens and config.split_delimiter:
            tokens.extend(item.strip() for item in raw_value.split(config.split_delimiter) if item.strip())
        return [val for val in tokens if val]

    def _format_objects(self, config: ColumnConfig, objects: List[Resource]) -> List[str]:
        if not objects:
            return []

        formatted: List[str] = []
        for obj in objects:
            if config.value_type == "boolean":
                value = (obj.value or "").strip().lower()
                formatted.append("Yes" if value == "true" else "No")
            elif config.value_type == "reference":
                label = obj.name or self.extract_slug(obj.uri or "")
                formatted.append(label or obj.uri or str(obj.id))
            elif config.value_type == "iri":
                formatted.append(obj.uri or "")
            else:
                value = self._object_to_value(obj)
                if value:
                    formatted.append(value)

        return [value for value in formatted if value]

    def _ensure_triple(self, subject: Resource, predicate: Resource, obj: Resource) -> bool:
        _triple, created = Triple.objects.update_or_create(
            subject=subject,
            predicate=predicate,
            object=obj,
            source=None,
            defaults={"is_derived": True},
        )
        return created

    def _cleanup_outdated_triples(
        self,
        subject: Resource,
        predicate_objects: Dict[Resource, Set[int]],
    ) -> int:
        deleted = 0
        for predicate, valid_object_ids in predicate_objects.items():
            qs = Triple.objects.filter(
                subject=subject,
                predicate=predicate,
                source=None,
                is_derived=True,
            )
            if valid_object_ids:
                qs = qs.exclude(object_id__in=valid_object_ids)
            count, _ = qs.delete()
            deleted += count
        return deleted

    def _resolve_reference(self, resource_id: str) -> Resource:
        return Resource.objects.get(pk=resource_id)

    def _ensure_resource(self, uri: str, resource_type: ResourceType) -> Resource:
        resource, created = Resource.objects.get_or_create(
            uri=uri,
            defaults={"resource_type": resource_type},
        )
        update_fields = []
        if not created and resource.resource_type != resource_type:
            resource.resource_type = resource_type
            update_fields.append("resource_type")

        # Set self-canonical for shared predicates
        if resource.canonical_uri is None and uri.startswith("http://arkumu.org/data/properties/"):
            resource.canonical_uri = uri
            update_fields.append("canonical_uri")

        if update_fields:
            resource.save(update_fields=update_fields)
        return resource

    def _ensure_literal(self, value: str, language: Optional[str], datatype: Optional[str]) -> Resource:
        literal = Resource.objects.filter(
            resource_type=ResourceType.LITERAL,
            value=value,
            language=language or None,
            datatype=datatype or None,
        ).first()
        if literal:
            return literal
        return Resource.objects.create(
            resource_type=ResourceType.LITERAL,
            value=value,
            language=language or None,
            datatype=datatype or None,
        )

    def _object_to_value(self, obj: Resource) -> str:
        if obj.resource_type == ResourceType.LITERAL:
            return obj.value or ""
        return obj.uri or obj.name or str(obj.id)
