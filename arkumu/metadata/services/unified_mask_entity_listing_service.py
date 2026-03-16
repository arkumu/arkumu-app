"""Entity listing service for the unified mask workspace."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Dict, List, Optional, Sequence
from urllib.parse import urlencode

from django.db.models import Q
from django.urls import reverse

from arkumu.common.uri_utils import DEFAULT_INSTITUTION_BASE_URI, mint_uri, slugify_uri_part
from arkumu.catalog.services.project_views import CardURIs, ProjectURIs
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.services.canonical_graph_service import RDF_TYPE_URI
from arkumu.metadata.services.mapping_set_resolver import MappingSetResolver
from arkumu.metadata.services.mask_schema import (
    ACTOR_ENGLISH_NAME_URI,
    COLLECTION_NAME_DE_URI,
    COLLECTION_NAME_EN_URI,
    COLLECTION_TYPE_URI,
    INFORMATION_CARRIER_LABEL_URI,
    INFORMATION_CARRIER_NAME_DE_URI,
    INFORMATION_CARRIER_NAME_EN_URI,
    INFORMATION_CARRIER_TYPE_URI,
    KEYWORD_LABEL_DE_URI,
    KEYWORD_TYPE_URI,
    PLACE_NAME_URI,
    PLACE_TYPE_URI,
)


@dataclass(frozen=True)
class UnifiedMaskEntityListItem:
    uri: str
    label: str
    edit_url: Optional[str]
    visibility: str
    updated_at: object
    summary: List[str]
    source_dataset: Optional[str] = None
    workspace_url: Optional[str] = None


@dataclass(frozen=True)
class UnifiedMaskEntityListPage:
    items: List[UnifiedMaskEntityListItem]
    page: int
    per_page: int
    total_count: int

    @property
    def total_pages(self) -> int:
        if self.total_count <= 0:
            return 1
        return max(1, ceil(self.total_count / self.per_page))

    @property
    def has_previous(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages

    @property
    def previous_page(self) -> Optional[int]:
        return self.page - 1 if self.has_previous else None

    @property
    def next_page(self) -> Optional[int]:
        return self.page + 1 if self.has_next else None


@dataclass(frozen=True)
class EntityListingConfig:
    canonical_type_uri: str
    label_predicate_uris: Sequence[str]
    summary_predicate_uris: Sequence[str]
    edit_url_name: Optional[str]


ENTITY_LISTING_CONFIG: Dict[str, EntityListingConfig] = {
    "project": EntityListingConfig(
        canonical_type_uri=CardURIs.PROJECT_TYPE,
        label_predicate_uris=(CardURIs.TITLE, CardURIs.SUBTITLE),
        summary_predicate_uris=(CardURIs.INSTITUTION, ProjectURIs.PROJECT_TYPE_FIELD, CardURIs.SUBTITLE),
        edit_url_name="metadata:edit_project",
    ),
    "event": EntityListingConfig(
        canonical_type_uri=CardURIs.EVENT_TYPE,
        label_predicate_uris=(ProjectURIs.EVENT_NAME,),
        summary_predicate_uris=(ProjectURIs.EVENT_TYPE, CardURIs.EVENT_START, CardURIs.EVENT_END),
        edit_url_name="metadata:edit_ereignis",
    ),
    "actor": EntityListingConfig(
        canonical_type_uri=CardURIs.ACTOR_TYPE,
        label_predicate_uris=(CardURIs.ACTOR_GERMAN_NAME, ACTOR_ENGLISH_NAME_URI),
        summary_predicate_uris=(ACTOR_ENGLISH_NAME_URI,),
        edit_url_name="metadata:edit_akteur",
    ),
    "place": EntityListingConfig(
        canonical_type_uri=PLACE_TYPE_URI,
        label_predicate_uris=(PLACE_NAME_URI,),
        summary_predicate_uris=(),
        edit_url_name="metadata:edit_ort",
    ),
    "collection": EntityListingConfig(
        canonical_type_uri=COLLECTION_TYPE_URI,
        label_predicate_uris=(COLLECTION_NAME_DE_URI, COLLECTION_NAME_EN_URI),
        summary_predicate_uris=(),
        edit_url_name=None,
    ),
    "information_carrier": EntityListingConfig(
        canonical_type_uri=INFORMATION_CARRIER_TYPE_URI,
        label_predicate_uris=(
            INFORMATION_CARRIER_NAME_DE_URI,
            INFORMATION_CARRIER_NAME_EN_URI,
            INFORMATION_CARRIER_LABEL_URI,
        ),
        summary_predicate_uris=(INFORMATION_CARRIER_LABEL_URI,),
        edit_url_name=None,
    ),
    "keyword": EntityListingConfig(
        canonical_type_uri=KEYWORD_TYPE_URI,
        label_predicate_uris=(KEYWORD_LABEL_DE_URI,),
        summary_predicate_uris=(),
        edit_url_name=None,
    ),
    "digital_object": EntityListingConfig(
        canonical_type_uri=CardURIs.DIGITAL_OBJECT_TYPE,
        label_predicate_uris=(CardURIs.DIGITAL_OBJECT_PATH,),
        summary_predicate_uris=(),
        edit_url_name="metadata:edit_digitales_objekt",
    ),
}


class UnifiedMaskEntityListingService:
    """List existing resources for the unified mask workspace."""

    def __init__(self, *, mapping_set_resolver: Optional[MappingSetResolver] = None) -> None:
        self.mapping_set_resolver = mapping_set_resolver or MappingSetResolver()

    def list_entities(
        self,
        *,
        organization_code: Optional[str],
        entity_type: str,
        page: int = 1,
        per_page: int = 24,
        search_query: Optional[str] = None,
    ) -> UnifiedMaskEntityListPage:
        config = ENTITY_LISTING_CONFIG.get(entity_type)
        if config is None or not organization_code:
            return UnifiedMaskEntityListPage(items=[], page=1, per_page=per_page, total_count=0)

        normalized_page = max(1, page)
        normalized_per_page = max(1, min(per_page, 100))
        offset = (normalized_page - 1) * normalized_per_page

        normalized_search = (search_query or "").strip()
        dataset_bindings = self.mapping_set_resolver.list_datasets_for_entity(
            organization_code=organization_code,
            entity_type=entity_type,
        )
        resources, dataset_by_uri, total_count = self._list_resources_for_dataset_bindings(
            organization_code=organization_code,
            dataset_bindings=dataset_bindings,
            offset=offset,
            limit=normalized_per_page,
            config=config,
            search_query=normalized_search,
        )
        if not resources:
            resources, total_count = self._list_resources_for_canonical_type(
                organization_code=organization_code,
                canonical_type_uri=config.canonical_type_uri,
                offset=offset,
                limit=normalized_per_page,
                config=config,
                search_query=normalized_search,
            )
            dataset_by_uri = {}

        items = [
            UnifiedMaskEntityListItem(
                uri=resource.uri or "",
                label=self._resolve_label(resource, config.label_predicate_uris),
                edit_url=self._build_edit_url(config.edit_url_name, resource.uri or ""),
                visibility=resource.public_access_level,
                updated_at=resource.updated_at,
                summary=self._resolve_summary(resource, config.summary_predicate_uris),
                source_dataset=dataset_by_uri.get(resource.uri or ""),
            )
            for resource in resources
            if resource.uri
        ]
        return UnifiedMaskEntityListPage(
            items=items,
            page=normalized_page,
            per_page=normalized_per_page,
            total_count=total_count,
        )

    def _list_resources_for_dataset_bindings(
        self,
        *,
        organization_code: str,
        dataset_bindings,
        offset: int,
        limit: int,
        config: EntityListingConfig,
        search_query: str,
    ) -> tuple[List[Resource], Dict[str, str], int]:
        if not dataset_bindings:
            return [], {}, 0

        org_slug = slugify_uri_part(str(organization_code))
        dataset_uri_to_name: Dict[str, str] = {}
        for binding in dataset_bindings:
            dataset_uri = mint_uri(
                DEFAULT_INSTITUTION_BASE_URI,
                org_slug,
                "datasets",
                binding.dataset_name,
            )
            dataset_uri_to_name[dataset_uri] = binding.dataset_name

        queryset = (
            Resource.objects.filter(
                resource_type=ResourceType.ENTITY,
                organization__code=organization_code,
                subject_triples__predicate__uri="http://purl.org/dc/terms/isPartOf",
                subject_triples__object__uri__in=list(dataset_uri_to_name.keys()),
            )
            .select_related("organization")
            .distinct()
            .order_by("-updated_at")
        )
        queryset = self._apply_search(
            queryset=queryset,
            config=config,
            search_query=search_query,
        )
        total_count = queryset.count()
        resources = queryset[offset : offset + limit]

        dataset_by_uri: Dict[str, str] = {}
        if resources:
            triples = (
                Triple.objects.filter(
                    subject__in=resources,
                    predicate__uri="http://purl.org/dc/terms/isPartOf",
                    object__uri__in=list(dataset_uri_to_name.keys()),
                )
                .select_related("subject", "object")
            )
            for triple in triples:
                if triple.subject.uri and triple.object.uri and triple.subject.uri not in dataset_by_uri:
                    dataset_by_uri[triple.subject.uri] = dataset_uri_to_name.get(triple.object.uri, "")

        return list(resources), dataset_by_uri, total_count

    def _list_resources_for_canonical_type(
        self,
        *,
        organization_code: str,
        canonical_type_uri: str,
        offset: int,
        limit: int,
        config: EntityListingConfig,
        search_query: str,
    ) -> tuple[List[Resource], int]:
        queryset = (
            Resource.objects.filter(
                resource_type=ResourceType.ENTITY,
                organization__code=organization_code,
                subject_triples__predicate__uri=RDF_TYPE_URI,
            )
            .filter(
                Q(subject_triples__object__canonical_uri=canonical_type_uri)
                | Q(subject_triples__object__uri=canonical_type_uri)
            )
            .select_related("organization")
            .distinct()
        )
        queryset = self._apply_search(
            queryset=queryset,
            config=config,
            search_query=search_query,
        )
        total_count = queryset.count()
        return list(queryset.order_by("-updated_at")[offset : offset + limit]), total_count

    def _resolve_label(self, resource: Resource, label_predicate_uris: Sequence[str]) -> str:
        for predicate_uri in label_predicate_uris:
            triple = (
                Triple.objects.filter(
                    subject=resource,
                    object__resource_type=ResourceType.LITERAL,
                )
                .filter(Q(predicate__canonical_uri=predicate_uri) | Q(predicate__uri=predicate_uri))
                .select_related("object")
                .first()
            )
            if triple and triple.object and triple.object.value:
                return triple.object.value
        if resource.name:
            return resource.name
        return resource.uri.rstrip("/").split("/")[-1]

    def _build_edit_url(self, url_name: Optional[str], resource_uri: str) -> Optional[str]:
        if not url_name or not resource_uri:
            return None
        return f"{reverse(url_name)}?{urlencode({'uri': resource_uri})}"

    def _resolve_summary(self, resource: Resource, predicate_uris: Sequence[str]) -> List[str]:
        summary: List[str] = []
        seen = set()
        for predicate_uri in predicate_uris:
            triples = (
                Triple.objects.filter(subject=resource)
                .filter(Q(predicate__canonical_uri=predicate_uri) | Q(predicate__uri=predicate_uri))
                .select_related("object")[:3]
            )
            for triple in triples:
                value = self._render_object(triple.object)
                if not value or value == resource.uri or value in seen or value == self._resolve_label(resource, (predicate_uri,)):
                    continue
                seen.add(value)
                summary.append(value)
                if len(summary) >= 3:
                    return summary
        return summary

    def _render_object(self, resource: Resource) -> str:
        if resource.resource_type == ResourceType.LITERAL:
            return resource.value or ""
        if resource.name:
            return resource.name
        if resource.value:
            return resource.value
        if resource.uri:
            return resource.uri.rstrip("/").split("/")[-1]
        return ""

    def _apply_search(self, *, queryset, config: EntityListingConfig, search_query: str):
        if not search_query:
            return queryset

        predicate_uris = tuple(dict.fromkeys(config.label_predicate_uris + config.summary_predicate_uris))
        search_filter = Q(uri__icontains=search_query) | Q(name__icontains=search_query)
        if predicate_uris:
            search_filter |= (
                (
                    Q(subject_triples__object__value__icontains=search_query)
                    | Q(subject_triples__object__name__icontains=search_query)
                    | Q(subject_triples__object__uri__icontains=search_query)
                )
                & (
                    Q(subject_triples__predicate__canonical_uri__in=predicate_uris)
                    | Q(subject_triples__predicate__uri__in=predicate_uris)
                )
            )
        return queryset.filter(search_filter).distinct()
