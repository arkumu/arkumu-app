"""Load field values for unified mask workspaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from django.db.models import Q

from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.services.mask_runtime_service import ResolvedMaskField


@dataclass(frozen=True)
class LoadedMaskFieldValue:
    field_name: str
    values: List[str]
    source_label: str


class MaskValueLoaderService:
    """Load current values for mask fields from mapped or canonical predicates."""

    def load_field_values(
        self,
        *,
        organization_code: Optional[str],
        resource_uri: Optional[str],
        fields: Iterable[ResolvedMaskField],
    ) -> Dict[str, LoadedMaskFieldValue]:
        org_code = (organization_code or "").strip().lower()
        uri = (resource_uri or "").strip()
        if not org_code or not uri:
            return {}

        resource = Resource.objects.filter(
            resource_type=ResourceType.ENTITY,
            organization__code=org_code,
            uri=uri,
        ).first()
        if resource is None:
            return {}

        return {
            field.field.name: self._load_single_field_value(resource=resource, field=field)
            for field in fields
        }

    def _load_single_field_value(
        self,
        *,
        resource: Resource,
        field: ResolvedMaskField,
    ) -> LoadedMaskFieldValue:
        mapped_predicates = [binding.property_uri for binding in field.bindings if binding.property_uri]
        canonical_predicate = field.field.semantic_slot.canonical_property_uri

        triples = self._load_triples(
            resource=resource,
            mapped_predicates=mapped_predicates,
            canonical_predicate=canonical_predicate,
        )
        values = self._serialize_triples(triples)

        if values and mapped_predicates and any(triple.predicate.uri in mapped_predicates for triple in triples):
            source_label = "Gemappt"
        elif values and canonical_predicate:
            source_label = "Canonical"
        else:
            source_label = "Leer"

        return LoadedMaskFieldValue(
            field_name=field.field.name,
            values=values,
            source_label=source_label,
        )

    def _load_triples(
        self,
        *,
        resource: Resource,
        mapped_predicates: List[str],
        canonical_predicate: Optional[str],
    ) -> List[Triple]:
        predicate_query = Q()
        if mapped_predicates:
            predicate_query |= Q(predicate__uri__in=mapped_predicates)
        if canonical_predicate:
            predicate_query |= Q(predicate__uri=canonical_predicate) | Q(
                predicate__canonical_uri=canonical_predicate
            )
        if not predicate_query:
            return []

        triples = list(
            Triple.objects.filter(subject=resource)
            .filter(predicate_query)
            .select_related("predicate", "object")
        )

        order = {uri: index for index, uri in enumerate(mapped_predicates)}
        return sorted(
            triples,
            key=lambda triple: (
                0 if triple.predicate.uri in order else 1,
                order.get(triple.predicate.uri or "", 9999),
                triple.id,
            ),
        )

    def _serialize_triples(self, triples: List[Triple]) -> List[str]:
        values: List[str] = []
        seen = set()
        for triple in triples:
            rendered = self._render_object(triple.object)
            if rendered in seen:
                continue
            seen.add(rendered)
            values.append(rendered)
        return values

    def _render_object(self, resource: Resource) -> str:
        if resource.resource_type == ResourceType.LITERAL:
            return resource.value or ""
        if resource.name:
            return resource.name
        if resource.value:
            return resource.value
        if resource.uri:
            return resource.uri
        return ""
