from __future__ import annotations

from typing import Dict, Optional
from urllib.parse import urlsplit

from django.contrib.auth.models import AnonymousUser
from django.test.client import RequestFactory
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from arkumu.oaipmh.tailored_probe import (
    TailoredProbeError,
    TailoredProbeOptions,
    TailoredProbeStats,
    collect_probe_stats,
)
from arkumu.oaipmh.views.legacy import oai_endpoint
from arkumu.oaipmh.views.router import oai_db_endpoint, oai_tailored_endpoint

from ..serializers import TailoredProbeRequestSerializer

_REQUEST_FACTORY = RequestFactory()
_INTERNAL_VIEW_MAP = {
    "/oai/tailored/": (oai_tailored_endpoint, True),
    "/oai/db/": (oai_db_endpoint, True),
    "/oai/": (oai_endpoint, False),
}


def _build_internal_http_get(user, host: str):
    def _http_get(url: str, params: Dict[str, Optional[str]], headers: Dict[str, str]) -> bytes:
        path = urlsplit(url).path or "/"
        view_entry = _INTERNAL_VIEW_MAP.get(path)
        if not view_entry:
            raise TailoredProbeError(f"Unsupported internal endpoint: {path}")
        view_func, requires_auth = view_entry
        filtered_params = {k: v for k, v in params.items() if v is not None}
        req = _REQUEST_FACTORY.get(path, data=filtered_params, HTTP_HOST=host)
        req.user = user if requires_auth else AnonymousUser()
        req.session = {}
        req._dont_enforce_csrf_checks = True
        response = view_func(req)
        if response.status_code != 200:
            raise TailoredProbeError(f"Internal request to {path} failed (status {response.status_code})")
        return response.content

    return _http_get


def _build_basic_auth(attrs: dict) -> Optional[str]:
    username = attrs.get("basic_auth_username")
    password = attrs.get("basic_auth_password")
    if username and password:
        return f"{username}:{password}"
    return None


class TailoredProbeViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def create(self, request):
        serializer = TailoredProbeRequestSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        base_url = data.get("base_url")
        if base_url:
            base_url = base_url.rstrip("/")
        else:
            base_url = request.build_absolute_uri("/").rstrip("/")
        base_host = urlsplit(base_url).netloc or "localhost"

        options = TailoredProbeOptions(
            base_url=base_url,
            verb=data["verb"],
            metadata_prefix=data["metadata_prefix"],
            set_spec=data.get("set_spec"),
            from_date=data.get("from_date"),
            until_date=data.get("until_date"),
            basic_auth=_build_basic_auth(data),
            internal_bypass=data.get("internal_bypass", False),
            pause_for_dataset_change=data.get("pause_for_dataset_change", False),
            run_tailored_resume=not data.get("skip_tailored_resume", False),
            run_db_check=not data.get("skip_db", False),
            run_snapshot_check=not data.get("skip_snapshot", False),
        )

        http_get = None if data.get("base_url") else _build_internal_http_get(request.user, base_host)

        try:
            stats: TailoredProbeStats = collect_probe_stats(options, http_get=http_get)
        except TailoredProbeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        except Exception as exc:  # pragma: no cover - defensive guardrail
            return Response({"detail": "internal server error"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(stats.to_dict())
