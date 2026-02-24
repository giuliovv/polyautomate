"""
Client for the polymarketdata.co REST API.

Provides high-granularity historical order book, price, and liquidity data
for Polymarket prediction markets.

All requests require an API key passed via the ``X-API-Key`` header.

Example::

    from polyautomate.api.polymarketdata import PMDClient

    client = PMDClient(api_key="pk_live_...")

    # List markets matching a search term
    markets = list(client.list_markets(search="election", limit=20))

    # Fetch 1-hour price history for a market
    prices = client.get_prices(
        "presidential-election-winner-2024",
        start_ts="2024-10-01T00:00:00Z",
        end_ts="2024-11-06T00:00:00Z",
        resolution="1h",
    )
    # prices is a dict: {token_label: [{ts, price}, ...]}

    # Fetch order book snapshots
    books = client.get_books(
        "presidential-election-winner-2024",
        start_ts="2024-10-01T00:00:00Z",
        end_ts="2024-11-06T00:00:00Z",
        resolution="1h",
    )
    # books is a dict: {token_label: [{ts, bids, asks}, ...]}
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Iterator

import requests

logger = logging.getLogger(__name__)


class PMDError(Exception):
    """Raised when the polymarketdata.co API returns an error response."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}: {detail}")


class PMDClient:
    """
    REST client for polymarketdata.co.

    Parameters
    ----------
    api_key:
        Your ``pk_live_...`` API key from polymarketdata.co.
    timeout:
        Request timeout in seconds. Defaults to 30.
    retry_on_rate_limit:
        When True (default), automatically wait and retry once on HTTP 429.
        The client respects the ``Retry-After`` header when present, otherwise
        waits 61 seconds (just past the 1-minute window on the free plan).
    """

    BASE_URL = "https://api.polymarketdata.co"

    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = 30.0,
        retry_on_rate_limit: bool = True,
    ) -> None:
        self.api_key = api_key
        self._timeout = timeout
        self._retry_on_rate_limit = retry_on_rate_limit
        self._session = requests.Session()
        self._session.headers.update(
            {
                "X-API-Key": api_key,
                "Accept": "application/json",
            }
        )

    # ------------------------------------------------------------------
    # Low-level transport
    # ------------------------------------------------------------------

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.BASE_URL}{path}"
        for attempt in range(2):
            resp = self._session.get(url, params=params, timeout=self._timeout)
            if resp.status_code == 429 and self._retry_on_rate_limit and attempt == 0:
                wait = int(resp.headers.get("Retry-After", 61))
                logger.warning("Rate limited; waiting %ds before retry…", wait)
                time.sleep(wait)
                continue
            if not resp.ok:
                try:
                    detail = resp.json().get("detail", resp.text)
                except Exception:
                    detail = resp.text
                raise PMDError(resp.status_code, str(detail))
            return resp.json()
        # Should not be reached, but satisfy type checker
        raise PMDError(429, "Rate limit retry exhausted")

    def _paginate(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        max_items: int | None = None,
    ) -> Iterator[dict]:
        """
        Yield items from a cursor-paginated list endpoint.

        Parameters
        ----------
        max_items:
            Stop after yielding this many items total.  ``None`` means
            fetch all pages until the server returns no next_cursor.
        """
        params = dict(params or {})
        yielded = 0
        while True:
            resp = self._get(path, params)
            for item in resp.get("data", []):
                yield item
                yielded += 1
                if max_items is not None and yielded >= max_items:
                    return
            cursor = resp.get("metadata", {}).get("next_cursor")
            if not cursor:
                break
            params["cursor"] = cursor

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def health(self) -> dict:
        """Check API liveness. Returns ``{status, timestamp}``."""
        return self._get("/v1/health")

    def usage(self) -> dict:
        """
        Return current usage for the API key.

        Returns a dict with ``plan``, ``organization``, ``limits``,
        and ``reset_at`` fields.
        """
        return self._get("/v1/usage")

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def list_tags(self) -> list[str]:
        """Return all available market tags."""
        return self._get("/v1/tags").get("data", [])

    # Default page size used for list endpoints (separate from the user-facing limit).
    _PAGE_SIZE = 100

    def list_markets(
        self,
        *,
        search: str | None = None,
        tags: list[str] | None = None,
        tags_match: str = "any",
        start_date_min: str | None = None,
        end_date_max: str | None = None,
        sort: str = "updated_at",
        order: str = "desc",
        limit: int = 100,
    ) -> Iterator[dict]:
        """
        Iterate over markets matching the given filters.

        Parameters
        ----------
        search:
            Free-text search across market titles/descriptions.
        tags:
            Filter by one or more tags.
        tags_match:
            ``"any"`` (default) returns markets matching at least one tag;
            ``"all"`` requires all tags to match.
        limit:
            Maximum total number of markets to yield.  Pagination is handled
            automatically; pass a large number (or ``None`` not yet supported)
            to retrieve all matching markets.
        """
        params: dict[str, Any] = {
            "sort": sort,
            "order": order,
            "limit": min(limit, self._PAGE_SIZE),  # per-page; API max is 1000
        }
        if search is not None:
            params["search"] = search
        if tags is not None:
            params["tags"] = tags
            params["tags_match"] = tags_match
        if start_date_min is not None:
            params["start_date_min"] = start_date_min
        if end_date_max is not None:
            params["end_date_max"] = end_date_max
        yield from self._paginate("/v1/markets", params, max_items=limit)

    def list_events(
        self,
        *,
        search: str | None = None,
        tags: list[str] | None = None,
        limit: int = 100,
    ) -> Iterator[dict]:
        """Iterate over events (groups of related markets)."""
        params: dict[str, Any] = {"limit": min(limit, self._PAGE_SIZE)}
        if search is not None:
            params["search"] = search
        if tags is not None:
            params["tags"] = tags
        yield from self._paginate("/v1/events", params, max_items=limit)

    def list_series(
        self,
        *,
        search: str | None = None,
        tags: list[str] | None = None,
        limit: int = 100,
    ) -> Iterator[dict]:
        """Iterate over series (recurring event collections)."""
        params: dict[str, Any] = {"limit": min(limit, self._PAGE_SIZE)}
        if search is not None:
            params["search"] = search
        if tags is not None:
            params["tags"] = tags
        yield from self._paginate("/v1/series", params, max_items=limit)

    def get_market(self, id_or_slug: str) -> dict:
        """
        Fetch details for a single market.

        Parameters
        ----------
        id_or_slug:
            The market's UUID or URL slug.

        Returns a dict with ``id``, ``slug``, ``question``, ``description``,
        ``status``, dates, and a ``tokens`` list.
        """
        return self._get(f"/v1/markets/{id_or_slug}")

    # ------------------------------------------------------------------
    # History helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ts(value: datetime | int | str) -> str:
        """Normalise a timestamp argument to an ISO-8601 string."""
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.isoformat()
        return str(value)

    def get_prices(
        self,
        id_or_slug: str,
        start_ts: datetime | int | str,
        end_ts: datetime | int | str,
        resolution: str = "1h",
        *,
        limit: int = 200,
    ) -> dict[str, list[dict]]:
        """
        Fetch token price history for all outcomes of a market.

        Parameters
        ----------
        id_or_slug:
            Market UUID or URL slug.
        start_ts, end_ts:
            Time range. Accepts a :class:`datetime`, a Unix timestamp (int),
            or an ISO-8601 string.
        resolution:
            Candle interval: ``"1m"``, ``"10m"``, ``"1h"``, ``"6h"``, ``"1d"``.
        limit:
            Page size (max 200).

        Returns
        -------
        dict
            ``{token_label: [{ts: int, price: float}, ...]}``
            Prices are probabilities in ``[0.0, 1.0]``.
        """
        params: dict[str, Any] = {
            "start_ts": self._ts(start_ts),
            "end_ts": self._ts(end_ts),
            "resolution": resolution,
            "limit": limit,
        }
        result: dict[str, list] = {}
        cursor: str | None = None
        while True:
            if cursor:
                params["cursor"] = cursor
            resp = self._get(f"/v1/markets/{id_or_slug}/prices", params)
            for label, points in resp.get("data", {}).items():
                result.setdefault(label, []).extend(points)
            cursor = resp.get("metadata", {}).get("next_cursor")
            if not cursor:
                break
        return result

    def get_token_prices(
        self,
        token_id: str,
        start_ts: datetime | int | str,
        end_ts: datetime | int | str,
        resolution: str = "1h",
        *,
        limit: int = 200,
    ) -> list[dict]:
        """
        Fetch price history for a single token.

        Returns
        -------
        list
            ``[{ts: int, price: float}, ...]``
        """
        params: dict[str, Any] = {
            "start_ts": self._ts(start_ts),
            "end_ts": self._ts(end_ts),
            "resolution": resolution,
            "limit": limit,
        }
        result: list[dict] = []
        cursor: str | None = None
        while True:
            if cursor:
                params["cursor"] = cursor
            resp = self._get(f"/v1/tokens/{token_id}/prices", params)
            result.extend(resp.get("data", []))
            cursor = resp.get("metadata", {}).get("next_cursor")
            if not cursor:
                break
        return result

    def get_metrics(
        self,
        id_or_slug: str,
        start_ts: datetime | int | str,
        end_ts: datetime | int | str,
        resolution: str = "1h",
        *,
        limit: int = 200,
    ) -> list[dict]:
        """
        Fetch market metrics over a time range.

        Each data point contains ``ts``, ``volume``, ``liquidity``, and
        ``spread`` fields.
        """
        params: dict[str, Any] = {
            "start_ts": self._ts(start_ts),
            "end_ts": self._ts(end_ts),
            "resolution": resolution,
            "limit": limit,
        }
        result: list[dict] = []
        cursor: str | None = None
        while True:
            if cursor:
                params["cursor"] = cursor
            resp = self._get(f"/v1/markets/{id_or_slug}/metrics", params)
            result.extend(resp.get("data", []))
            cursor = resp.get("metadata", {}).get("next_cursor")
            if not cursor:
                break
        return result

    def get_books(
        self,
        id_or_slug: str,
        start_ts: datetime | int | str,
        end_ts: datetime | int | str,
        resolution: str = "1h",
        *,
        limit: int = 200,
    ) -> dict[str, list[dict]]:
        """
        Fetch order book snapshots for all tokens of a market.

        Each snapshot has the form::

            {
              "ts": 1700000000,
              "bids": [[price, size], ...],   # sorted best-to-worst
              "asks": [[price, size], ...]
            }

        Returns
        -------
        dict
            ``{token_label: [snapshot, ...]}``
        """
        params: dict[str, Any] = {
            "start_ts": self._ts(start_ts),
            "end_ts": self._ts(end_ts),
            "resolution": resolution,
            "limit": limit,
        }
        result: dict[str, list] = {}
        cursor: str | None = None
        while True:
            if cursor:
                params["cursor"] = cursor
            resp = self._get(f"/v1/markets/{id_or_slug}/books", params)
            for label, snapshots in resp.get("data", {}).items():
                result.setdefault(label, []).extend(snapshots)
            cursor = resp.get("metadata", {}).get("next_cursor")
            if not cursor:
                break
        return result

    def get_token_books(
        self,
        token_id: str,
        start_ts: datetime | int | str,
        end_ts: datetime | int | str,
        resolution: str = "1h",
        *,
        limit: int = 200,
    ) -> list[dict]:
        """
        Fetch order book snapshots for a single token.

        Returns
        -------
        list
            ``[{ts, bids, asks}, ...]``
        """
        params: dict[str, Any] = {
            "start_ts": self._ts(start_ts),
            "end_ts": self._ts(end_ts),
            "resolution": resolution,
            "limit": limit,
        }
        result: list[dict] = []
        cursor: str | None = None
        while True:
            if cursor:
                params["cursor"] = cursor
            resp = self._get(f"/v1/tokens/{token_id}/books", params)
            result.extend(resp.get("data", []))
            cursor = resp.get("metadata", {}).get("next_cursor")
            if not cursor:
                break
        return result
