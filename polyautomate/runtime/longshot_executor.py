from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from polyautomate.clients.polymarketdata import PMDClient, PMDError
from polyautomate.clients.trading import PolymarketTradingClient
from polyautomate.models import OrderRequest


LOGGER = logging.getLogger("longshot_executor")

_SPORTS_KEYWORDS = (
    "map 1",
    "map 2",
    "map 3",
    "game 1",
    "game 2",
    "game 3",
    "first blood",
    "total kills",
    "game handicap",
    "map handicap",
    "games total",
    "win on ",
    " vs. ",
    " vs ",
    "up or down",
    "o/u ",
    "both teams to score",
    "spread:",
)


@dataclass
class Candidate:
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
class SizingDecision:
    size: float
    notional_usd: float
    method: str
    no_win_prob: float | None = None
    full_kelly: float | None = None
    applied_fraction: float | None = None


def _is_sports_market(question: str) -> bool:
    q = question.lower()
    return any(kw in q for kw in _SPORTS_KEYWORDS)


def _parse_dt(raw: object) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _load_state(path: Path) -> dict:
    if not path.exists():
        return {"traded": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        LOGGER.exception("state_load_failed path=%s", path)
        return {"traded": {}}


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _normalize_state(state: dict) -> dict:
    # Backward-compat migration from previous schema.
    if "open_positions" not in state:
        old = state.get("traded", {})
        state["open_positions"] = old if isinstance(old, dict) else {}
    if "closed_positions" not in state:
        state["closed_positions"] = []
    return state


def _extract_token_ids(market: dict) -> tuple[str | None, str | None]:
    yes_token = None
    no_token = None
    for token in market.get("tokens", []) or []:
        if not isinstance(token, dict):
            continue
        token_id = token.get("token_id") or token.get("tokenId")
        label = str(token.get("outcome") or token.get("label") or token.get("name") or "").strip().lower()
        if not isinstance(token_id, str) or not token_id:
            continue
        if label == "yes":
            yes_token = token_id
        elif label == "no":
            no_token = token_id
    return yes_token, no_token


def _latest_price(points: list[dict]) -> float | None:
    if not points:
        return None
    raw = points[-1].get("p") or points[-1].get("price")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _scan_candidates(
    client: PMDClient,
    *,
    now: datetime,
    lookback_minutes: int,
    market_limit: int,
    min_days_left: float,
    longshot_threshold: float,
    min_price: float,
    max_price: float,
    max_spread: float,
    max_rel_spread: float,
    open_positions: dict,
) -> list[Candidate]:
    start = now - timedelta(minutes=lookback_minutes)
    candidates: list[Candidate] = []

    for market in client.list_markets(
        sort="updated_at",
        order="desc",
        end_date_min=now.isoformat(),
        limit=market_limit,
    ):
        if str(market.get("status", "")).lower() in {"closed", "resolved"}:
            continue

        question = str(market.get("question", ""))
        if _is_sports_market(question):
            continue

        end_date = _parse_dt(
            market.get("end_date")
            or market.get("endDate")
            or market.get("resolution_date")
            or market.get("resolutionDate")
        )
        if end_date:
            days_left = (end_date - now).total_seconds() / 86400
            if days_left < min_days_left:
                continue

        slug = str(market.get("slug") or market.get("id") or "")
        if not slug:
            continue

        yes_token_id, no_token_id = _extract_token_ids(market)
        if not yes_token_id or not no_token_id:
            continue

        try:
            prices = client.get_prices(slug, start.isoformat(), now.isoformat(), resolution="10m")
        except PMDError:
            continue

        yes_points = prices.get("Yes") or prices.get("YES") or []
        no_points = prices.get("No") or prices.get("NO") or []

        yes_price = _latest_price(yes_points)
        no_price = _latest_price(no_points)
        if yes_price is None or no_price is None:
            continue
        if yes_price < min_price or yes_price > max_price:
            continue
        if yes_price > longshot_threshold:
            continue
        if slug in open_positions:
            continue

        avg_spread = 0.0
        rel_spread = 0.0
        try:
            metrics = client.get_metrics(slug, start.isoformat(), now.isoformat(), resolution="10m")
            spreads = [float(m["spread"]) for m in metrics if "spread" in m and m.get("spread") is not None]
            if spreads:
                avg_spread = sum(spreads) / len(spreads)
        except PMDError:
            continue

        denom = min(yes_price, 1.0 - yes_price)
        if denom <= 0:
            continue
        rel_spread = avg_spread / denom

        if avg_spread > max_spread:
            continue
        if rel_spread > max_rel_spread:
            continue

        candidates.append(
            Candidate(
                slug=slug,
                question=question,
                yes_token_id=yes_token_id,
                no_token_id=no_token_id,
                yes_price=yes_price,
                no_price=no_price,
                end_date=end_date,
                avg_spread=avg_spread,
                rel_spread=rel_spread,
            )
        )

    candidates.sort(key=lambda c: c.yes_price)
    return candidates


def _estimate_no_win_prob(yes_price: float) -> float:
    """
    Heuristic calibrated from LONGSHOT_ANALYSIS.md.
    Returns estimated probability that NO resolves true.
    """
    if yes_price <= 0.10:
        return 0.995
    if yes_price <= 0.20:
        return 0.985
    if yes_price <= 0.35:
        return 0.957
    return 0.917


def _compute_order_size(
    *,
    yes_price: float,
    no_price: float,
    fallback_size: float,
) -> SizingDecision:
    use_kelly = os.getenv("LONGSHOT_USE_KELLY", "1") == "1"
    bankroll_usd = float(os.getenv("LONGSHOT_BANKROLL_USD", "500"))
    kelly_fraction = float(os.getenv("LONGSHOT_KELLY_FRACTION", "0.25"))
    max_fraction = float(os.getenv("LONGSHOT_MAX_BANKROLL_FRACTION", "0.03"))
    min_notional = float(os.getenv("LONGSHOT_MIN_NOTIONAL_USD", "2"))
    max_notional = float(os.getenv("LONGSHOT_MAX_NOTIONAL_USD", "25"))

    if not use_kelly or bankroll_usd <= 0:
        return SizingDecision(
            size=fallback_size,
            notional_usd=max(0.0, fallback_size * no_price),
            method="fixed",
        )

    p = _estimate_no_win_prob(yes_price)
    q = 1.0 - p
    b = (1.0 - no_price) / max(no_price, 1e-6)
    full_kelly = max(0.0, ((b * p) - q) / max(b, 1e-9))
    applied_fraction = min(max_fraction, full_kelly * kelly_fraction)
    notional_usd = bankroll_usd * applied_fraction
    notional_usd = max(min_notional, min(max_notional, notional_usd))
    size = notional_usd / max(no_price, 1e-6)

    return SizingDecision(
        size=size,
        notional_usd=notional_usd,
        method="kelly",
        no_win_prob=p,
        full_kelly=full_kelly,
        applied_fraction=applied_fraction,
    )


def run_once() -> int:
    pmd_api_key = os.getenv("POLYMARKETDATA_API_KEY", "")
    pm_api_key = os.getenv("POLYMARKET_API_KEY", "")
    pm_signing_key = os.getenv("POLYMARKET_SIGNING_KEY", "")
    dry_run = os.getenv("DRY_RUN", "1") == "1"

    if not pmd_api_key:
        LOGGER.warning("missing_polymarketdata_api_key")
        return 0

    now = datetime.now(timezone.utc)
    state_path = Path(os.getenv("LONGSHOT_STATE_PATH", "/var/lib/polyautomate/longshot-state.json"))
    state = _normalize_state(_load_state(state_path))
    open_positions: dict = state.setdefault("open_positions", {})

    lookback_minutes = int(os.getenv("LONGSHOT_LOOKBACK_MINUTES", "240"))
    market_limit = int(os.getenv("LONGSHOT_MARKET_LIMIT", "120"))
    min_days_left = float(os.getenv("LONGSHOT_MIN_DAYS_LEFT", "2"))
    longshot_threshold = float(os.getenv("LONGSHOT_THRESHOLD", "0.40"))
    min_price = float(os.getenv("LONGSHOT_MIN_PRICE", "0.02"))
    max_price = float(os.getenv("LONGSHOT_MAX_PRICE", "0.96"))
    max_spread = float(os.getenv("LONGSHOT_MAX_SPREAD", "0.03"))
    max_rel_spread = float(os.getenv("LONGSHOT_MAX_REL_SPREAD", "0.15"))
    hold_grace_hours = int(os.getenv("LONGSHOT_HOLD_GRACE_HOURS", "24"))
    fallback_order_size = float(os.getenv("LONGSHOT_ORDER_SIZE", "5"))
    max_actions = int(os.getenv("LONGSHOT_MAX_ACTIONS_PER_CYCLE", "1"))

    pmd = PMDClient(api_key=pmd_api_key)

    # Hold-to-resolution: keep positions open until market resolves/closes.
    for slug, pos in list(open_positions.items()):
        try:
            market = pmd.get_market(slug)
        except PMDError:
            continue
        status = str(market.get("status", "")).lower()
        end_date = _parse_dt(
            market.get("end_date")
            or market.get("endDate")
            or market.get("resolution_date")
            or market.get("resolutionDate")
        )
        if status in {"resolved", "closed"}:
            pos["closed_at"] = now.isoformat()
            pos["closed_reason"] = status
            state["closed_positions"].append(pos)
            del open_positions[slug]
            continue
        if end_date and now > (end_date + timedelta(hours=hold_grace_hours)):
            pos["closed_at"] = now.isoformat()
            pos["closed_reason"] = "end_date_elapsed"
            state["closed_positions"].append(pos)
            del open_positions[slug]

    candidates = _scan_candidates(
        pmd,
        now=now,
        lookback_minutes=lookback_minutes,
        market_limit=market_limit,
        min_days_left=min_days_left,
        longshot_threshold=longshot_threshold,
        min_price=min_price,
        max_price=max_price,
        max_spread=max_spread,
        max_rel_spread=max_rel_spread,
        open_positions=open_positions,
    )

    LOGGER.info(
        "longshot_candidates count=%s threshold=%.2f open_positions=%s max_spread=%.3f max_rel_spread=%.2f",
        len(candidates),
        longshot_threshold,
        len(open_positions),
        max_spread,
        max_rel_spread,
    )
    if not candidates:
        return 0

    trader = None
    if not dry_run:
        if not pm_api_key or not pm_signing_key:
            LOGGER.warning("missing_trading_credentials")
            return 0
        trader = PolymarketTradingClient(api_key=pm_api_key, signing_key=pm_signing_key)

    actions = 0
    for c in candidates:
        if actions >= max_actions:
            break
        if c.slug in open_positions:
            continue

        # Longshot edge: buy NO when YES enters <= threshold.
        side = "buy"
        token_id = c.no_token_id
        price = min(max(c.no_price, 0.01), 0.99)

        sizing = _compute_order_size(
            yes_price=c.yes_price,
            no_price=price,
            fallback_size=fallback_order_size,
        )
        order_size = max(round(sizing.size, 4), 0.01)

        if dry_run:
            LOGGER.info(
                "DRY_RUN order slug=%s side=%s token_id=%s price=%.4f size=%.4f yes_price=%.4f sizing=%s notional=%.2f p_no=%s full_kelly=%s f=%s",
                c.slug,
                side,
                token_id,
                price,
                order_size,
                c.yes_price,
                sizing.method,
                sizing.notional_usd,
                f"{sizing.no_win_prob:.3f}" if sizing.no_win_prob is not None else "na",
                f"{sizing.full_kelly:.4f}" if sizing.full_kelly is not None else "na",
                f"{sizing.applied_fraction:.4f}" if sizing.applied_fraction is not None else "na",
            )
        else:
            expiration = int((now + timedelta(minutes=15)).timestamp())
            order = OrderRequest(
                token_id=token_id,
                side=side,
                price=f"{price:.4f}",
                size=f"{order_size:.4f}",
                expiration=expiration,
            )
            ack = trader.place_order(order, post_only=True)  # type: ignore[union-attr]
            LOGGER.info(
                "order_submitted slug=%s order_id=%s status=%s price=%.4f size=%.4f yes_price=%.4f avg_spread=%.4f rel_spread=%.2f sizing=%s notional=%.2f p_no=%s full_kelly=%s f=%s",
                c.slug,
                ack.order_id,
                ack.status,
                price,
                order_size,
                c.yes_price,
                c.avg_spread,
                c.rel_spread,
                sizing.method,
                sizing.notional_usd,
                f"{sizing.no_win_prob:.3f}" if sizing.no_win_prob is not None else "na",
                f"{sizing.full_kelly:.4f}" if sizing.full_kelly is not None else "na",
                f"{sizing.applied_fraction:.4f}" if sizing.applied_fraction is not None else "na",
            )

        open_positions[c.slug] = {
            "slug": c.slug,
            "question": c.question,
            "at": now.isoformat(),
            "yes_price": c.yes_price,
            "no_price": c.no_price,
            "end_date": c.end_date.isoformat() if c.end_date else None,
            "entry_order_size": order_size,
            "entry_notional_usd": round(sizing.notional_usd, 4),
            "avg_spread": c.avg_spread,
            "rel_spread": c.rel_spread,
        }
        actions += 1

    state["last_run_at"] = now.isoformat()
    state["last_candidates"] = len(candidates)
    state["open_position_count"] = len(open_positions)
    _save_state(state_path, state)
    return actions
