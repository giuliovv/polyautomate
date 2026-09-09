from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Iterator

import requests

from ..exceptions import PolymarketAPIError

LOGGER = logging.getLogger(__name__)


class GammaLiveDataAdapter:
    """Live market-data adapter backed by Polymarket's public Gamma API.

    It intentionally exposes the small PMD-like surface the longshot executor
    needs, so strategy/order logic stays unchanged while we remove the PMD
    subscription from the live path.
    """

    def __init__(
        self,
        *,
        gamma_base_url: str = "https://gamma-api.polymarket.com",
        timeout: float = 10.0,
        session: requests.Session | None = None,
    ) -> None:
        self.gamma_base_url = gamma_base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "polyautomate/0.1"})

    def _request(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        response = self.session.get(
            f"{self.gamma_base_url}{path}",
            params=params,
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise PolymarketAPIError(response.status_code, response.text or response.reason)
        if not response.content:
            return None
        return response.json()

    def list_markets(
        self,
        *,
        search: str | None = None,
        tags: list[str] | None = None,
        tags_match: str = "any",
        start_date_min: str | None = None,
        end_date_min: str | None = None,
        end_date_max: str | None = None,
        sort: str = "updated_at",
        order: str = "desc",
        limit: int = 100,
    ) -> Iterator[dict]:
        del start_date_min, end_date_min, end_date_max, tags_match
        params: dict[str, Any] = {
            "closed": "false",
            "limit": min(max(limit, 1), 500),
        }
        if search:
            params["q"] = search
        if sort in {"updated_at", "updatedAt"}:
            params["order"] = "updatedAt"
            params["ascending"] = "true" if order.lower() == "asc" else "false"
        if tags:
            # Gamma's public /markets endpoint has inconsistent tag support;
            # retain a best-effort parameter and apply filtering upstream later
            # if the strategy starts relying on tags.
            params["tag"] = tags[0]

        payload = self._request("/markets", params=params) or []
        if isinstance(payload, dict):
            rows = payload.get("markets") or payload.get("data") or []
        else:
            rows = payload
        emitted = 0
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            normalized = self._normalize_market(raw)
            if not normalized:
                continue
            yield normalized
            emitted += 1
            if emitted >= limit:
                break

    def get_market(self, id_or_slug: str) -> dict:
        try:
            payload = self._request(f"/markets/{id_or_slug}")
        except PolymarketAPIError:
            payload = self._request("/markets", params={"slug": id_or_slug, "closed": "false", "limit": 1})
            if isinstance(payload, list) and payload:
                payload = payload[0]
            elif isinstance(payload, dict):
                rows = payload.get("markets") or payload.get("data") or []
                payload = rows[0] if rows else None
        if not isinstance(payload, dict):
            raise PolymarketAPIError(404, f"Market not found: {id_or_slug}")
        normalized = self._normalize_market(payload)
        if not normalized:
            raise PolymarketAPIError(422, f"Market missing live token metadata: {id_or_slug}")
        return normalized

    def get_prices(
        self,
        id_or_slug: str,
        start_ts: datetime | int | str,
        end_ts: datetime | int | str,
        resolution: str = "1h",
        *,
        limit: int = 200,
    ) -> dict[str, list[dict]]:
        del start_ts, end_ts, resolution, limit
        market = self.get_market(id_or_slug)
        result: dict[str, list[dict]] = {}
        for token in market.get("tokens", []) or []:
            label = str(token.get("outcome") or token.get("label") or token.get("name") or "")
            price = token.get("price") or token.get("last_price") or token.get("lastPrice")
            if not label or price is None:
                continue
            try:
                result.setdefault(label, []).append({"ts": int(datetime.now().timestamp()), "price": float(price)})
            except (TypeError, ValueError):
                continue
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
        del start_ts, end_ts, resolution, limit
        market = self.get_market(id_or_slug)
        spread = market.get("spread")
        try:
            return [{"spread": float(spread)}]
        except (TypeError, ValueError):
            return []

    def _normalize_market(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        slug = str(raw.get("slug") or raw.get("id") or "")
        question = str(raw.get("question") or raw.get("title") or "")
        token_ids = _json_list(raw.get("clobTokenIds"))
        outcomes = _json_list(raw.get("outcomes"))
        prices = _json_list(raw.get("outcomePrices"))

        tokens: list[dict[str, Any]] = []
        for idx, token_id in enumerate(token_ids):
            label = str(outcomes[idx] if idx < len(outcomes) else ("Yes" if idx == 0 else "No"))
            price = prices[idx] if idx < len(prices) else None
            tokens.append({"token_id": str(token_id), "outcome": label, "price": price})

        if len(tokens) < 2:
            LOGGER.debug("gamma_market_skipped_missing_tokens slug=%s", slug)
            return None

        closed = bool(raw.get("closed")) or not bool(raw.get("active", True))
        status = "closed" if closed else "active"
        end_date = raw.get("endDate") or raw.get("endDateIso") or raw.get("end_date")
        spread = raw.get("spread")
        if spread is None:
            spread = _spread_from_best_quotes(raw)

        return {
            "id": str(raw.get("id") or ""),
            "slug": slug,
            "question": question,
            "status": status,
            "end_date": end_date,
            "endDate": end_date,
            "tokens": tokens,
            "spread": spread,
            "raw": raw,
        }


def _json_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _spread_from_best_quotes(raw: dict[str, Any]) -> float | None:
    try:
        bid = float(raw.get("bestBid"))
        ask = float(raw.get("bestAsk"))
    except (TypeError, ValueError):
        return None
    if ask < bid:
        return None
    return ask - bid
