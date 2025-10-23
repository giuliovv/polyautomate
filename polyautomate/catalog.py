"""
Client for Polymarket's public catalogue (Gamma) that exposes market metadata
and CLOB token identifiers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import json

import requests

from .exceptions import PolymarketAPIError

CATALOG_BASE_URL = "https://gamma-api.polymarket.com"


@dataclass(slots=True)
class CatalogMarket:
    """Normalized view of a catalogue market entry."""

    id: str
    question: str
    slug: str
    condition_id: str
    enable_order_book: bool
    clob_token_ids: List[str]
    raw: Dict[str, Any]


@dataclass(slots=True)
class CatalogEvent:
    """Normalized view of an event, including its markets."""

    id: str
    slug: str
    title: str
    markets: List[CatalogMarket]
    raw: Dict[str, Any]


class MarketCatalog:
    """High-level wrapper around the Gamma catalogue endpoints."""

    def __init__(self, *, base_url: str = CATALOG_BASE_URL, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "polyautomate/0.1"})

    def _request(self, path: str, *, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base_url}{path}"
        response = self.session.get(url, params=params, timeout=self.timeout)
        if response.status_code >= 400:
            raise PolymarketAPIError(response.status_code, response.text or response.reason)
        if not response.content:
            return None
        return response.json()

    def search_markets(
        self,
        *,
        query: Optional[str] = None,
        tag: Optional[str] = None,
        closed: Optional[bool] = None,
        limit: Optional[int] = None,
    ) -> List[CatalogMarket]:
        """
        Retrieve markets from the catalogue.

        The server currently ignores `tag`, so the filter is applied client-side.
        """
        params: Dict[str, Any] = {}
        if closed is not None:
            params["closed"] = json.dumps(closed)
        if limit is not None:
            params["limit"] = limit
        payload = self._request("/markets", params=params or None) or []
        markets = [_to_catalog_market(item) for item in payload]
        if query:
            lowered = query.lower()
            markets = [
                m
                for m in markets
                if lowered in m.question.lower() or lowered in (m.slug.lower() if m.slug else "")
            ]
        if tag:
            tag_lower = tag.lower()
            markets = [
                m
                for m in markets
                if _has_tag(m.raw, tag_lower)
            ]
        return markets

    def get_event(self, slug: str) -> CatalogEvent:
        payload = self._request("/events", params={"slug": slug})
        if not payload:
            raise ValueError(f"No event found for slug '{slug}'")
        event_payload = payload[0]
        markets_payload = event_payload.get("markets") or []
        markets = [_to_catalog_market(item) for item in markets_payload]
        return CatalogEvent(
            id=str(event_payload.get("id", "")),
            slug=event_payload.get("slug", ""),
            title=event_payload.get("title", ""),
            markets=markets,
            raw=event_payload,
        )


def _to_catalog_market(payload: Dict[str, Any]) -> CatalogMarket:
    ids_raw = payload.get("clobTokenIds") or "[]"
    if isinstance(ids_raw, str):
        try:
            clob_ids = json.loads(ids_raw)
        except json.JSONDecodeError:
            clob_ids = []
    elif isinstance(ids_raw, list):
        clob_ids = ids_raw
    else:
        clob_ids = []
    return CatalogMarket(
        id=str(payload.get("id", "")),
        question=payload.get("question", ""),
        slug=payload.get("slug", ""),
        condition_id=payload.get("conditionId", ""),
        enable_order_book=bool(payload.get("enableOrderBook")),
        clob_token_ids=[str(token) for token in clob_ids],
        raw=payload,
    )


def _has_tag(raw: Dict[str, Any], tag_lower: str) -> bool:
    if not raw:
        return False
    tags_value = raw.get("tags")
    single_tag = raw.get("tag")
    candidates: List[str] = []
    if isinstance(tags_value, list):
        candidates.extend(str(item) for item in tags_value)
    elif isinstance(tags_value, str):
        candidates.append(tags_value)
    if isinstance(single_tag, list):
        candidates.extend(str(item) for item in single_tag)
    elif isinstance(single_tag, str):
        candidates.append(single_tag)
    return any(tag_lower == candidate.lower() for candidate in candidates)
