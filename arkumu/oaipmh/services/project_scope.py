"""Shared helpers for deriving the canonical OAI project scope."""

from __future__ import annotations

from typing import List

from django.conf import settings
from django.db.models import Exists, OuterRef, Q

from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.users.models import Organization

PROJECT_LINK_PREDICATES: tuple[str, ...] = tuple(
    uri.strip()
    for uri in getattr(
        settings,
        "OAI_PROJECT_LINK_PREDICATES",
        ("http://arkumu.org/data/properties/projekt",),
    )
    if uri and uri.strip()
)
PROJECT_TYPE_URIS: tuple[str, ...] = tuple(
    uri.strip()
    for uri in getattr(settings, "OAI_PROJECT_TYPE_URIS", ())
    if uri and uri.strip()
)
RDF_TYPE_URI = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
# Orgs that bypass the link predicate gate (event-based or indirect media links)
_DEFAULT_LINK_PREDICATE_BYPASS_ORGS = (
    "fuk",
    "det",
    "rsh",
)
PROJECT_LINK_PREDICATE_BYPASS_ORGS: set[str] = {
    code.strip().lower()
    for code in getattr(
        settings,
        "OAI_PROJECT_LINK_SCOPE_DISABLED_ORGS",
        _DEFAULT_LINK_PREDICATE_BYPASS_ORGS,
    )
    if code and code.strip()
}


def project_queryset_for_org(org: Organization):
    """Return the canonical queryset covering all OAI projects for an organization."""

    queryset = Resource.objects.filter(
        organization=org,
        resource_type=ResourceType.ENTITY,
    )

    scope_clauses: List[Q] = []

    if PROJECT_TYPE_URIS:
        type_predicate_filter = (
            Q(predicate__uri=RDF_TYPE_URI)
            | Q(predicate__canonical_uri=RDF_TYPE_URI)
        )
        type_object_filter = (
            Q(object__uri__in=PROJECT_TYPE_URIS)
            | Q(object__canonical_uri__in=PROJECT_TYPE_URIS)
        )
        type_subquery = Triple.objects.filter(
            subject_id=OuterRef("pk"),
        ).filter(type_predicate_filter & type_object_filter)
        queryset = queryset.annotate(has_project_type=Exists(type_subquery))
        scope_clauses.append(Q(has_project_type=True))

    org_code = (getattr(org, "code", "") or "").strip().lower()

    if PROJECT_LINK_PREDICATES and org_code not in PROJECT_LINK_PREDICATE_BYPASS_ORGS:
        link_subquery = Triple.objects.filter(
            object_id=OuterRef("pk"),
        ).filter(
            Q(predicate__uri__in=PROJECT_LINK_PREDICATES)
            | Q(predicate__canonical_uri__in=PROJECT_LINK_PREDICATES)
        )
        queryset = queryset.annotate(has_project_link=Exists(link_subquery))
        scope_clauses.append(Q(has_project_link=True))

    if not scope_clauses and org_code in PROJECT_LINK_PREDICATE_BYPASS_ORGS:
        # Allow bypass orgs (event-based media linkage) to include all entity resources.
        scope_clauses.append(Q())

    if not scope_clauses:
        return queryset.none()

    project_scope = Q()
    for clause in scope_clauses:
        project_scope &= clause

    return queryset.filter(project_scope).order_by("updated_at", "id")


__all__ = ["project_queryset_for_org"]
