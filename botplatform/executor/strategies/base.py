"""Base strategy interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class Candidate:
    """A trading candidate (market opportunity)."""

    slug: str
    question: str
    yes_token_id: str
    no_token_id: str
    yes_price: float
    no_price: float
    end_date: datetime | None
    avg_spread: float
    rel_spread: float


@dataclass
class OrderPayload:
    """Order to be placed."""

    token_id: str
    side: str  # "buy" or "sell"
    price: float
    size: float


@dataclass
class SizingDecision:
    """Position sizing decision."""

    size: float
    notional_usd: float
    method: str
    no_win_prob: float | None = None
    full_kelly: float | None = None
    applied_fraction: float | None = None


@dataclass
class ExecutionContext:
    """Context provided to strategy during execution."""

    bot_id: str
    wallet_id: str
    bankroll_usd: float
    config: dict[str, Any]
    existing_positions: list[str]  # List of market slugs with open positions


class BaseExecutorStrategy(ABC):
    """Base class for executor strategies.

    Strategies are responsible for:
    1. Scanning for market opportunities
    2. Deciding on position sizing
    3. Generating order payloads

    They do NOT handle order signing or submission - that's handled by the executor.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    @abstractmethod
    async def scan_candidates(
        self,
        context: ExecutionContext,
    ) -> list[Candidate]:
        """Scan for trading candidates.

        Returns a list of candidates sorted by priority (best first).
        """
        pass

    @abstractmethod
    async def compute_order(
        self,
        candidate: Candidate,
        context: ExecutionContext,
    ) -> tuple[OrderPayload, SizingDecision] | None:
        """Compute the order for a candidate.

        Returns (OrderPayload, SizingDecision) or None if no order should be placed.
        """
        pass

    async def on_order_placed(
        self,
        candidate: Candidate,
        order: OrderPayload,
        order_id: str,
        context: ExecutionContext,
    ) -> None:
        """Called when an order is successfully placed.

        Override to perform any post-order actions (logging, state updates, etc.)
        """
        pass

    async def on_order_failed(
        self,
        candidate: Candidate,
        order: OrderPayload,
        error: str,
        context: ExecutionContext,
    ) -> None:
        """Called when an order fails.

        Override to handle order failures.
        """
        pass
