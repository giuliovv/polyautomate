from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests

from ..exceptions import PolymarketAPIError

DEFAULT_BASE_URL = "https://clob.polymarket.com"


def _normalize_path(path: str) -> str:
    if not path.startswith("/"):
        return f"/{path}"
    return path


def _json_dumps(data: Dict[str, Any] | None) -> str:
    if not data:
        return ""
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


@dataclass(slots=True)
class RequestContext:
    method: str
    path: str
    body: Dict[str, Any] | None
    params: Dict[str, Any] | None


class BaseAPIClient:
    """Shared HTTP plumbing for Polymarket API clients."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        session: Optional[requests.Session] = None,
        timeout: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.timeout = timeout

    def _request(
        self,
        ctx: RequestContext,
        *,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        url = f"{self.base_url}{ctx.path}"
        response = self.session.request(
            ctx.method,
            url,
            params=ctx.params,
            json=ctx.body,
            headers=headers,
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise PolymarketAPIError(
                response.status_code, response.text or response.reason, payload=_safe_json(response)
            )
        if not response.content:
            return None
        return response.json()


def _safe_json(response: requests.Response) -> Dict[str, Any]:
    try:
        return response.json()  # type: ignore[return-value]
    except ValueError:
        return {}


def _coerce_timestamp(value) -> int:
    from datetime import datetime

    if isinstance(value, datetime):
        return int(value.timestamp())
    if isinstance(value, (int, float)):
        return int(value)
    raise TypeError(f"Unsupported timestamp type: {type(value)!r}")
