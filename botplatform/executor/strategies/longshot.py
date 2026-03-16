"""Longshot strategy adapted from polyautomate.runtime.longshot_executor."""

import logging
from datetime import datetime, timezone
from typing import Any

from executor.strategies.base import (
    BaseExecutorStrategy,
    Candidate,
    OrderPayload,
    SizingDecision,
    ExecutionContext,
)

LOGGER = logging.getLogger("executor.strategies.longshot")

_SPORTS_KEYWORDS = (
    "map 1", "map 2", "map 3", "game 1", "game 2", "game 3",
    "first blood", "total kills", "game handicap", "map handicap",
    "games total", "win on ", " vs. ", " vs ", "up or down", "o/u ",
    "both teams to score", "spread:",
)


def _is_sports_market(question: str) -> bool:
    """Check if market question indicates a sports/esports market."""
    q = question.lower()
    return any(kw in q for kw in _SPORTS_KEYWORDS)


def _parse_dt(raw: object) -> datetime | None:
    """Parse ISO datetime string."""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _extract_token_price(market: dict, outcome: str) -> float | None:
    """Extract price for a specific outcome from market data."""
    for token in market.get("tokens", []) or []:
        if not isinstance(token, dict):
            continue
        label = str(token.get("outcome") or token.get("label") or token.get("name") or "").strip().lower()
        if label != outcome.lower():
            continue
        price = token.get("price")
        if price is not None:
            return float(price)
    return None


def _extract_token_id(market: dict, outcome: str) -> str | None:
    """Extract token ID for a specific outcome."""
    for token in market.get("tokens", []) or []:
        if not isinstance(token, dict):
            continue
        label = str(token.get("outcome") or token.get("label") or token.get("name") or "").strip().lower()
        if label != outcome.lower():
            continue
        return str(token.get("token_id", ""))
    return None


class LongshotStrategy(BaseExecutorStrategy):
    """Strategy that buys NO on low-probability YES outcomes.

    The idea is that when YES price is very low (e.g., 0.05), the NO side
    offers good value if the probability estimate is wrong.

    Configuration:
        threshold: Maximum YES price to consider (default: 0.40)
        max_spread: Maximum spread to accept (default: 0.03)
        min_time_to_end_hours: Minimum hours until market end (default: 24)
        max_time_to_end_days: Maximum days until market end (default: 30)
        exclude_sports: Whether to exclude sports markets (default: True)
        kelly_fraction: Fraction of Kelly bet to use (default: 0.25)
        max_bankroll_fraction: Max % of bankroll per trade (default: 0.03)
        min_notional_usd: Minimum trade size (default: 2.0)
        max_notional_usd: Maximum trade size (default: 25.0)
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.threshold = config.get("threshold", 0.40)
        self.max_spread = config.get("max_spread", 0.03)
        self.min_time_to_end_hours = config.get("min_time_to_end_hours", 24)
        self.max_time_to_end_days = config.get("max_time_to_end_days", 30)
        self.exclude_sports = config.get("exclude_sports", True)
        self.kelly_fraction = config.get("kelly_fraction", 0.25)
        self.max_bankroll_fraction = config.get("max_bankroll_fraction", 0.03)
        self.min_notional_usd = config.get("min_notional_usd", 2.0)
        self.max_notional_usd = config.get("max_notional_usd", 25.0)

    async def scan_candidates(self, context: ExecutionContext) -> list[Candidate]:
        """Scan for longshot candidates using polymarketdata API.

        Note: In the full implementation, this would use PMDClient to fetch markets.
        For now, this is a skeleton that shows the filtering logic.
        """
        # TODO: Integrate PMDClient for market scanning
        # For now, return empty list - this will be filled in when connected to PMD API
        candidates: list[Candidate] = []

        # The actual implementation would:
        # 1. Fetch markets from polymarketdata.co
        # 2. Filter by: resolved, threshold, spread, time-to-resolution, sports
        # 3. Exclude markets with existing positions
        # 4. Sort by YES price (ascending)

        return candidates

    async def compute_order(
        self,
        candidate: Candidate,
        context: ExecutionContext,
    ) -> tuple[OrderPayload, SizingDecision] | None:
        """Compute order for a longshot candidate.

        Uses Kelly criterion for position sizing.
        """
        # Skip if already have position
        if candidate.slug in context.existing_positions:
            return None

        yes_price = candidate.yes_price
        no_price = candidate.no_price

        # Skip if above threshold
        if yes_price > self.threshold:
            return None

        # Estimate NO win probability (heuristic: assume YES is slightly overpriced)
        # This is simplified - the real executor has more sophisticated calibration
        no_win_prob = 1.0 - yes_price * 0.9  # Assume YES is ~10% overpriced

        # Compute Kelly bet size
        # f* = (p * b - q) / b where p = prob, b = odds, q = 1-p
        if no_price <= 0 or no_price >= 1:
            return None

        odds = (1.0 / no_price) - 1.0  # Decimal odds - 1
        if odds <= 0:
            return None

        full_kelly = (no_win_prob * odds - (1.0 - no_win_prob)) / odds
        if full_kelly <= 0:
            return None

        # Apply fractional Kelly
        kelly_bet = full_kelly * self.kelly_fraction

        # Compute notional size
        notional_usd = min(
            kelly_bet * context.bankroll_usd,
            self.max_bankroll_fraction * context.bankroll_usd,
            self.max_notional_usd,
        )
        notional_usd = max(notional_usd, self.min_notional_usd)

        # Convert to shares
        size = notional_usd / no_price

        order = OrderPayload(
            token_id=candidate.no_token_id,
            side="buy",
            price=no_price,
            size=size,
        )

        sizing = SizingDecision(
            size=size,
            notional_usd=notional_usd,
            method="kelly",
            no_win_prob=no_win_prob,
            full_kelly=full_kelly,
            applied_fraction=self.kelly_fraction,
        )

        return order, sizing

    async def on_order_placed(
        self,
        candidate: Candidate,
        order: OrderPayload,
        order_id: str,
        context: ExecutionContext,
    ) -> None:
        """Log successful order placement."""
        LOGGER.info(
            "order_placed slug=%s order_id=%s size=%.2f price=%.4f notional=%.2f",
            candidate.slug,
            order_id,
            order.size,
            order.price,
            order.size * order.price,
        )

    async def on_order_failed(
        self,
        candidate: Candidate,
        order: OrderPayload,
        error: str,
        context: ExecutionContext,
    ) -> None:
        """Log failed order."""
        LOGGER.error(
            "order_failed slug=%s error=%s",
            candidate.slug,
            error,
        )
