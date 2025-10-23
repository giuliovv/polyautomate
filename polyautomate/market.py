"""
Helpers for working with market payloads returned by Polymarket's API.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional


@dataclass(slots=True)
class MarketToken:
    """Represents a ticket/outcome token within a market."""

    token_id: str
    name: str
    raw: Dict[str, object]


def _extract_token_dicts(market: Dict[str, object]) -> Iterable[Dict[str, object]]:
    tokens = market.get("tokens")
    if isinstance(tokens, list):
        return tokens
    outcomes = market.get("outcomes")
    if isinstance(outcomes, list):
        return outcomes
    return []


def parse_market_tokens(market: Dict[str, object]) -> List[MarketToken]:
    """
    Convert the raw token/outcome entries into normalized MarketToken objects.
    Handles field naming differences (`token_id` vs `tokenId`, etc).
    """
    parsed: List[MarketToken] = []
    for entry in _extract_token_dicts(market):
        if not isinstance(entry, dict):
            continue
        token_id = entry.get("token_id") or entry.get("tokenId")
        if not isinstance(token_id, str):
            continue
        name = entry.get("outcome") or entry.get("name") or entry.get("title") or ""
        parsed.append(MarketToken(token_id=token_id, name=str(name), raw=entry))
    return parsed


def resolve_token_id(
    market: Dict[str, object],
    *,
    outcome_name: Optional[str] = None,
) -> Optional[str]:
    """
    Return a token id from the market, optionally filtering by the outcome name.
    """
    tokens = parse_market_tokens(market)
    if not tokens:
        return None
    if outcome_name:
        lowered = outcome_name.strip().lower()
        for token in tokens:
            if token.name.lower() == lowered:
                return token.token_id
        return None
    return tokens[0].token_id


def resolve_market_id(market: Dict[str, object]) -> Optional[str]:
    """
    Determine the identifier accepted by the candlesticks endpoint.

    Preference order:
    1. `id`
    2. `market_id`
    3. `condition_id`
    4. `question_id`
    5. `market_slug`
    6. `slug`
    """
    candidates = [
        market.get("id"),
        market.get("market_id"),
        market.get("condition_id"),
        market.get("question_id"),
        market.get("market_slug"),
        market.get("slug"),
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            return candidate
    return None
