"""HTMX views for searching storage-backed resources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from arkumu.storage.models import S3FileObject
from arkumu.common.mixins.base_coordinator import BaseCoordinatorMixin


class _Coordinator(BaseCoordinatorMixin):
    """Lightweight helper to access shared coordinator session state."""


_coordinator = _Coordinator()


@dataclass(slots=True)
class _SearchFilters:
    query: str
    input_id: str
    selected_value: str
    organization: str


def _resolve_filters(request: HttpRequest) -> _SearchFilters:
    query = request.GET.get("q", "").strip()
    input_id = request.GET.get("input_id", "").strip()
    selected = request.GET.get("selected", "").strip()
    organization = request.GET.get("organization", "").strip()
    return _SearchFilters(query=query, input_id=input_id, selected_value=selected, organization=organization)


def _filter_verified_files(
    *,
    organization_code: str | None,
    query: str,
) -> Iterable[S3FileObject]:
    base_queryset = S3FileObject.objects.filter(status="verified").order_by(
        "-updated_at",
        "-created_at",
    )

    if organization_code:
        base_queryset = base_queryset.filter(
            Q(organization__iexact=organization_code)
            | Q(related_resource__organization__code__iexact=organization_code)
        )

    if query:
        base_queryset = base_queryset.filter(
            s3_key__icontains=query,
        )

    return base_queryset[:20]


@login_required
def verified_file_search(request: HttpRequest) -> HttpResponse:
    """Return an HTMX-friendly list of verified storage files."""

    filters = _resolve_filters(request)
    organization = getattr(request.user, "organization", None)
    user_organization_code = getattr(organization, "code", "") or ""
    session_org = _coordinator.get_current_organization(request) or {}
    session_org_code = session_org.get("code", "")
    organization_code = (filters.organization or session_org_code or user_organization_code).strip()

    if not organization_code:
        return render(
            request,
            "storage/partials/verified_file_search_results.html",
            {
                "files": [],
                "input_id": filters.input_id,
                "selected_value": filters.selected_value,
                "query": filters.query,
                "error": "Keine Organisation zugeordnet. Bitte wende dich an das ArkUmu-Team.",
                "organization": organization_code,
            },
            status=200,
        )

    files = _filter_verified_files(
        organization_code=organization_code,
        query=filters.query,
    )

    return render(
        request,
        "storage/partials/verified_file_search_results.html",
        {
            "files": files,
            "input_id": filters.input_id,
            "selected_value": filters.selected_value,
            "query": filters.query,
            "error": "",
            "organization": organization_code,
        },
    )
