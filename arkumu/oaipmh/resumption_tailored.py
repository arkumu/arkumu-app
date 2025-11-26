"""Tailored resumption token service specialized for curated OAI feeds."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote

from arkumu.oaipmh.resumption import ResumptionTokenService


class TailoredResumptionTokenService(ResumptionTokenService):
    """Resumption service that embeds tailored-only metadata into each token."""

    PROFILE_NAME = "tailored"
    DEFAULT_VERSION = 1

    def __init__(
        self,
        secret_key: Optional[str] = None,
        page_size: int = 100,
        *,
        profile: Optional[str] = None,
        rt_version: Optional[int] = None,
        accept_legacy_tokens: bool = True,
    ) -> None:
        super().__init__(secret_key=secret_key, page_size=page_size)
        self.profile = profile or self.PROFILE_NAME
        self.rt_version = rt_version or self.DEFAULT_VERSION
        self.accept_legacy_tokens = accept_legacy_tokens

    def create_token(
        self,
        offset: int,
        verb: str,
        metadata_prefix: str = "oai_dc",
        set_spec: Optional[str] = None,
        from_date: Optional[str] = None,
        until_date: Optional[str] = None,
        total_count: Optional[int] = None,
        snapshot_marker: Optional[str] = None,
        cursor_marker: Optional[str] = None,
        cursor_position: Optional[str] = None,
        *,
        profile: Optional[str] = None,
        rt_version: Optional[int] = None,
    ) -> str:
        """Create a tailored resumption token with profile + version metadata."""

        dataset_marker = cursor_marker or snapshot_marker
        if not dataset_marker:
            raise ValueError("Tailored resumption tokens require a cursor marker")

        token_data = {
            "offset": offset,
            "verb": verb,
            "metadata_prefix": metadata_prefix,
            "page_size": self.page_size,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "profile": profile or self.profile,
            "rt_version": rt_version or self.rt_version,
        }

        if set_spec:
            token_data["set"] = set_spec
        if from_date:
            token_data["from"] = from_date
        if until_date:
            token_data["until"] = until_date
        if total_count is not None:
            token_data["total_count"] = total_count
        if snapshot_marker:
            token_data["snapshot"] = snapshot_marker
        token_data["cursor"] = dataset_marker
        if cursor_position:
            token_data["cursor_position"] = cursor_position

        token_json = json.dumps(token_data, sort_keys=True)
        token_bytes = token_json.encode("utf-8")

        signature = hmac.new(
            self.secret_key.encode("utf-8"),
            token_bytes,
            hashlib.sha256,
        ).hexdigest()

        signed_token = f"{base64.b64encode(token_bytes).decode('ascii')}:{signature}"
        return quote(signed_token)

    def parse_token(self, token: str) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """Parse tailored tokens while enforcing profile/version/cursor requirements."""

        is_valid, token_data, error = super().parse_token(token)
        if not is_valid or token_data is None:
            return is_valid, token_data, error

        token_profile = token_data.get("profile")
        dataset_marker = token_data.get("cursor") or token_data.get("snapshot")

        if not dataset_marker:
            return False, None, "Tailored token missing cursor marker"

        if token_profile is None:
            if not self.accept_legacy_tokens:
                return False, None, "Tailored resumption token missing profile"
            return True, token_data, None

        if token_profile != self.profile:
            return False, None, "Token profile does not match endpoint"

        token_version = token_data.get("rt_version")
        if token_version != self.rt_version:
            return False, None, "Unsupported tailored resumption token version"

        return True, token_data, None
