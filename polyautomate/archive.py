"""
Helpers for building local archives of Polymarket market history.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from .catalog import CatalogEvent, CatalogMarket, MarketCatalog
from .history import PriceHistoryService


@dataclass(slots=True)
class ExportResult:
    """Tracks the output files produced for a market token."""

    market: CatalogMarket
    token_id: str
    interval: str
    path: Path
    rows: int


@dataclass(slots=True)
class ExportSummary:
    """Aggregate information about an export run."""

    successes: List[ExportResult]
    failed: int = 0
    failed_markets: List[CatalogMarket] = field(default_factory=list)


class MarketHistoryExporter:
    """
    Collects price history for catalogue markets and persists it to CSV files.

    Intended usage::

        exporter = MarketHistoryExporter(output_dir=\"history\")
        results = exporter.export_search(
            term=\"shutdown\", closed=False, limit=50, interval=\"1m\"
        )
    """

    def __init__(
        self,
        *,
        catalog: Optional[MarketCatalog] = None,
        history_service: Optional[PriceHistoryService] = None,
        output_dir: str | Path = "market_history",
    ) -> None:
        self.catalog = catalog or MarketCatalog()
        self.history_service = history_service or PriceHistoryService()
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export_search(
        self,
        *,
        query: Optional[str] = None,
        tag: Optional[str] = None,
        closed: Optional[bool] = None,
        limit: Optional[int] = None,
        interval: str = "1h",
        fidelity_minutes: Optional[int] = None,
        overwrite: bool = False,
    ) -> ExportSummary:
        markets = self.catalog.search_markets(
            query=query,
            tag=tag,
            closed=closed,
            limit=limit,
        )
        return self.export_markets(
            markets,
            interval=interval,
            fidelity_minutes=fidelity_minutes,
            overwrite=overwrite,
        )

    def export_markets(
        self,
        markets: Sequence[CatalogMarket],
        *,
        interval: str = "1h",
        fidelity_minutes: Optional[int] = None,
        overwrite: bool = False,
    ) -> ExportSummary:
        results: List[ExportResult] = []
        failed = 0
        failed_markets: List[CatalogMarket] = []
        for market in markets:
            try:
                enriched = self._hydrate_market(market)
            except LookupError:
                failed += 1
                failed_markets.append(market)
                continue
            if not enriched.condition_id or not enriched.clob_token_ids:
                continue
            for token_id in enriched.clob_token_ids:
                history = self.history_service.get_price_history(
                    enriched.condition_id,
                    token_id,
                    interval=interval,
                    fidelity_minutes=fidelity_minutes,
                )
                frame = history.to_dataframe()
                if frame.empty:
                    continue
                filename = self._build_filename(enriched, token_id, interval)
                path = self.output_dir / filename
                if not overwrite and path.exists():
                    results.append(
                        ExportResult(
                            market=enriched,
                            token_id=token_id,
                            interval=interval,
                            path=path,
                            rows=len(frame),
                        )
                    )
                    continue
                frame.to_csv(path, index=True)
                results.append(
                    ExportResult(
                        market=enriched,
                        token_id=token_id,
                        interval=interval,
                        path=path,
                        rows=len(frame),
                    )
                )
        return ExportSummary(successes=results, failed=failed, failed_markets=failed_markets)

    def _hydrate_market(self, market: CatalogMarket) -> CatalogMarket:
        if market.condition_id and market.clob_token_ids:
            return market
        slugs: List[str] = []
        if market.slug:
            slugs.append(market.slug)
        if market.raw:
            maybe_slug = market.raw.get("slug")
            if isinstance(maybe_slug, str):
                slugs.append(maybe_slug)
            events = market.raw.get("events") or []
            if isinstance(events, list):
                for event_info in events:
                    if isinstance(event_info, dict):
                        s = event_info.get("slug")
                        if isinstance(s, str):
                            slugs.append(s)
        seen = set()
        for slug in slugs:
            if not slug or slug in seen:
                continue
            seen.add(slug)
            try:
                event = self.catalog.get_event(slug)
            except ValueError:
                continue
            matched = _match_market(event, market)
            if matched:
                return matched
        raise LookupError(f"Unable to hydrate market metadata for slug(s): {', '.join(seen) or 'unknown'}")

    @staticmethod
    def _build_filename(market: CatalogMarket, token_id: str, interval: str) -> str:
        base_slug = market.slug or (market.raw.get("slug") if market.raw else market.question or market.id)
        sanitized = "".join(c if c.isalnum() or c in "-_" else "_" for c in base_slug)
        return f"{sanitized}_{token_id}_{interval}.csv"


def _match_market(event: CatalogEvent, source: CatalogMarket) -> Optional[CatalogMarket]:
    for candidate in event.markets:
        if candidate.id == source.id:
            return candidate
        if candidate.condition_id and candidate.condition_id == source.condition_id:
            return candidate
        if candidate.slug and source.slug and candidate.slug == source.slug:
            return candidate
        if candidate.question == source.question:
            return candidate
    return None
