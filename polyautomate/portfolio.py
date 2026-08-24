from __future__ import annotations

import argparse
import html
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import requests

DEFAULT_STATE_PATH = Path("/var/lib/polyautomate/longshot-state.json")
DATA_API_BASE_URL = "https://data-api.polymarket.com"


@dataclass(frozen=True)
class PortfolioSummary:
    open_count: int
    closed_count: int
    realized_pnl_usd: float
    open_entry_notional_usd: float
    wins: int
    losses: int
    win_rate: float
    avg_closed_pnl_usd: float
    best_closed_pnl_usd: float | None
    worst_closed_pnl_usd: float | None
    last_run_at: str | None
    last_candidates: int | None


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_dt(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        value = str(raw).replace("Z", "+00:00")
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _format_dt(raw: Any) -> str:
    dt = _parse_dt(raw)
    if dt is None:
        return "-"
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _money(value: float | None) -> str:
    if value is None:
        return "-"
    sign = "+" if value > 0 else ""
    return f"{sign}${value:,.2f}"


def _usd(value: float | None) -> str:
    if value is None:
        return "-"
    return f"${value:,.2f}"


def load_state(path: Path = DEFAULT_STATE_PATH) -> dict[str, Any]:
    if not path.exists():
        return {"open_positions": {}, "closed_positions": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"state file must contain a JSON object: {path}")
    if "open_positions" not in data:
        traded = data.get("traded", {})
        data["open_positions"] = traded if isinstance(traded, dict) else {}
    if "closed_positions" not in data:
        data["closed_positions"] = []
    return data


def _open_positions(state: dict[str, Any]) -> list[dict[str, Any]]:
    positions = state.get("open_positions", {})
    if isinstance(positions, dict):
        return [p for p in positions.values() if isinstance(p, dict)]
    if isinstance(positions, list):
        return [p for p in positions if isinstance(p, dict)]
    return []


def _closed_positions(state: dict[str, Any]) -> list[dict[str, Any]]:
    positions = state.get("closed_positions", [])
    if isinstance(positions, list):
        return [p for p in positions if isinstance(p, dict)]
    return []


def summarize(state: dict[str, Any]) -> PortfolioSummary:
    open_positions = _open_positions(state)
    closed_positions = _closed_positions(state)
    closed_pnls = [_as_float(p.get("pnl_usd")) for p in closed_positions if p.get("pnl_usd") is not None]
    wins = sum(1 for pnl in closed_pnls if pnl > 0)
    losses = sum(1 for pnl in closed_pnls if pnl < 0)
    closed_count = len(closed_positions)
    realized = sum(closed_pnls)
    return PortfolioSummary(
        open_count=len(open_positions),
        closed_count=closed_count,
        realized_pnl_usd=realized,
        open_entry_notional_usd=sum(_as_float(p.get("entry_notional_usd")) for p in open_positions),
        wins=wins,
        losses=losses,
        win_rate=wins / max(wins + losses, 1),
        avg_closed_pnl_usd=realized / max(len(closed_pnls), 1),
        best_closed_pnl_usd=max(closed_pnls) if closed_pnls else None,
        worst_closed_pnl_usd=min(closed_pnls) if closed_pnls else None,
        last_run_at=state.get("last_run_at"),
        last_candidates=_as_int(state.get("last_candidates")),
    )


def equity_curve(state: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[tuple[datetime, dict[str, Any]]] = []
    for pos in _closed_positions(state):
        dt = _parse_dt(pos.get("closed_at")) or _parse_dt(pos.get("at"))
        if dt is not None:
            rows.append((dt, pos))
    rows.sort(key=lambda item: item[0])

    cumulative = 0.0
    points: list[dict[str, Any]] = []
    for dt, pos in rows:
        pnl = _as_float(pos.get("pnl_usd"))
        cumulative += pnl
        points.append(
            {
                "date": dt.date().isoformat(),
                "timestamp": dt.isoformat(),
                "pnl_usd": pnl,
                "cumulative_pnl_usd": cumulative,
                "slug": pos.get("slug", ""),
            }
        )
    return points


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _short_addr(address: str) -> str:
    return f"{address[:8]}...{address[-6:]}" if len(address) > 16 else address


def fetch_data_api_portfolio(user: str, *, timeout: int = 20) -> dict[str, Any]:
    positions: list[dict[str, Any]] = []
    offset = 0
    while True:
        response = requests.get(
            f"{DATA_API_BASE_URL}/positions",
            params={
                "user": user,
                "limit": 500,
                "offset": offset,
                "sizeThreshold": 0,
                "sortBy": "CURRENT",
                "sortDirection": "DESC",
            },
            timeout=timeout,
        )
        response.raise_for_status()
        batch = response.json()
        if not isinstance(batch, list):
            raise ValueError(f"unexpected positions response for {user}: {batch!r}")
        positions.extend([p for p in batch if isinstance(p, dict)])
        if len(batch) < 500:
            break
        offset += 500

    value_response = requests.get(f"{DATA_API_BASE_URL}/value", params={"user": user}, timeout=timeout)
    value_response.raise_for_status()
    value_payload = value_response.json()

    activity_response = requests.get(
        f"{DATA_API_BASE_URL}/activity",
        params={"user": user, "limit": 50, "excludeDepositsWithdrawals": "false"},
        timeout=timeout,
    )
    activity_response.raise_for_status()
    activity_payload = activity_response.json()

    return {
        "user": user,
        "positions": positions,
        "value": value_payload if isinstance(value_payload, list) else [],
        "activity": activity_payload if isinstance(activity_payload, list) else [],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def _portfolio_value(payload: dict[str, Any]) -> float:
    rows = payload.get("value") or []
    if isinstance(rows, list) and rows:
        return _as_float(rows[0].get("value"))
    return sum(_as_float(p.get("currentValue")) for p in payload.get("positions", []))


def _fetch_spendable_usdc_from_env() -> float | None:
    try:
        from polyautomate.runtime.longshot_executor import _fetch_usdc_balance

        return _fetch_usdc_balance()
    except Exception:
        return None


def render_data_api_html(
    payload: dict[str, Any],
    *,
    spendable_usdc: float | None = None,
) -> str:
    positions = sorted(
        [p for p in payload.get("positions", []) if isinstance(p, dict)],
        key=lambda p: _as_float(p.get("currentValue")),
        reverse=True,
    )
    user = str(payload.get("user") or "")
    fetched_at = str(payload.get("fetched_at") or "")
    total_value = _portfolio_value(payload)
    total_initial = sum(_as_float(p.get("initialValue")) for p in positions)
    total_pnl = sum(_as_float(p.get("cashPnl")) for p in positions)
    realized_pnl = sum(_as_float(p.get("realizedPnl")) for p in positions)
    winners = sum(1 for p in positions if _as_float(p.get("cashPnl")) > 0)
    losers = sum(1 for p in positions if _as_float(p.get("cashPnl")) < 0)
    pnl_class = "good" if total_pnl >= 0 else "bad"

    max_value = max([_as_float(p.get("currentValue")) for p in positions] or [1.0])
    bars = "".join(
        f'<div class="bar {"good" if _as_float(p.get("cashPnl")) >= 0 else "bad"}" '
        f'title="{_esc(p.get("title"))}: {_money(_as_float(p.get("cashPnl")))}" '
        f'style="height:{max(8, min(130, _as_float(p.get("currentValue")) / max_value * 130)):.0f}px"></div>'
        for p in positions
    ) or '<div class="empty">No current positions returned by the Data API.</div>'

    rows = "".join(
        f"<tr>"
        f"<td><strong>{_esc(p.get('title'))}</strong><div class='sub'>{_esc(p.get('slug'))}</div></td>"
        f"<td>{_esc(p.get('outcome'))}</td>"
        f"<td>{_as_float(p.get('size')):.4g}</td>"
        f"<td>{_as_float(p.get('avgPrice')):.3f}</td>"
        f"<td>{_as_float(p.get('curPrice')):.3f}</td>"
        f"<td>{_usd(_as_float(p.get('currentValue')))}</td>"
        f"<td class='{ 'good' if _as_float(p.get('cashPnl')) >= 0 else 'bad' }'>{_money(_as_float(p.get('cashPnl')))}</td>"
        f"<td>{_as_float(p.get('percentPnl')):.1f}%</td>"
        f"</tr>"
        for p in positions
    ) or '<tr><td colspan="8" class="empty">No current positions.</td></tr>'

    recent_activity = [
        a for a in payload.get("activity", []) if isinstance(a, dict) and a.get("type") in {"DEPOSIT", "WITHDRAWAL", "TRADE"}
    ][:12]
    activity_rows = "".join(
        f"<tr><td>{_esc(a.get('type'))}</td>"
        f"<td>{datetime.fromtimestamp(_as_int(a.get('timestamp')) or 0, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</td>"
        f"<td>{_money(_as_float(a.get('usdcSize') or a.get('size')))}</td>"
        f"<td>{_esc(a.get('outcome'))}</td>"
        f"<td>{_esc(a.get('title'))}</td></tr>"
        for a in recent_activity
    ) or '<tr><td colspan="5" class="empty">No recent activity.</td></tr>'

    spendable_text = _usd(spendable_usdc)
    spendable_note = ""
    if spendable_usdc is not None and spendable_usdc < 5:
        spendable_note = "Below typical 5-share minimum order notional for expensive NO tokens."

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="60">
  <title>Polyautomate Portfolio</title>
  <style>
    :root {{ color-scheme: dark; --bg:#09110d; --card:#111d17; --line:#234031; --text:#eef7ef; --muted:#8aa092; --good:#49d17d; --bad:#ff6b6b; --gold:#e6c56b; }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: radial-gradient(circle at top left, #203b2d 0, #09110d 38%, #050806 100%); color:var(--text); }}
    main {{ max-width:1200px; margin:0 auto; padding:32px 20px 56px; }}
    header {{ display:flex; justify-content:space-between; gap:24px; align-items:flex-end; margin-bottom:28px; }}
    h1 {{ margin:0; font-size:40px; letter-spacing:-0.04em; }}
    h2 {{ margin:0 0 14px; font-size:18px; }}
    .sub {{ color:var(--muted); margin-top:6px; font-size:13px; }}
    .grid {{ display:grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap:14px; margin-bottom:18px; }}
    .card {{ background:linear-gradient(180deg, rgba(255,255,255,.05), rgba(255,255,255,.02)); border:1px solid var(--line); border-radius:18px; padding:18px; box-shadow:0 24px 80px rgba(0,0,0,.22); }}
    .label {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.12em; }}
    .value {{ font-size:30px; font-weight:800; margin-top:8px; letter-spacing:-0.03em; }}
    .good {{ color:var(--good); }} .bad {{ color:var(--bad); }} .gold {{ color:var(--gold); }}
    .chart {{ display:flex; align-items:flex-end; gap:5px; height:160px; padding-top:20px; border-bottom:1px solid var(--line); overflow:hidden; }}
    .bar {{ width:18px; min-width:8px; border-radius:8px 8px 0 0; opacity:.85; }}
    .bar.good {{ background:linear-gradient(var(--good), rgba(73,209,125,.18)); }}
    .bar.bad {{ background:linear-gradient(var(--bad), rgba(255,107,107,.18)); }}
    table {{ width:100%; border-collapse:collapse; font-size:14px; }}
    th, td {{ padding:12px 10px; border-bottom:1px solid rgba(255,255,255,.07); text-align:left; vertical-align:top; }}
    th {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.08em; }}
    td:first-child {{ max-width:520px; }}
    .stack {{ display:grid; grid-template-columns: 1fr; gap:18px; }}
    .empty {{ color:var(--muted); padding:20px; text-align:center; }}
    .pill {{ border:1px solid var(--line); border-radius:999px; padding:7px 10px; color:var(--muted); font-size:13px; }}
    .note {{ color:var(--muted); margin:-6px 0 12px; font-size:13px; line-height:1.45; }}
    @media (max-width: 800px) {{ header {{ display:block; }} .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} .value {{ font-size:24px; }} main {{ padding:22px 12px 36px; }} table {{ font-size:12px; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div>
      <h1>Longshot Portfolio</h1>
      <div class="sub">Live Data API view for {_esc(_short_addr(user))}. Auto-refreshes every 60 seconds.</div>
    </div>
    <div class="pill">Fetched: {_format_dt(fetched_at)}</div>
  </header>

  <section class="grid">
    <div class="card"><div class="label">Portfolio value</div><div class="value">{_usd(total_value)}</div><div class="sub">{len(positions)} current positions</div></div>
    <div class="card"><div class="label">Unrealized P&L</div><div class="value {pnl_class}">{_money(total_pnl)}</div><div class="sub">Basis {_usd(total_initial)} · realized {_money(realized_pnl)}</div></div>
    <div class="card"><div class="label">Spendable CLOB cash</div><div class="value {'gold' if spendable_usdc is not None and spendable_usdc < 5 else ''}">{spendable_text}</div><div class="sub">{_esc(spendable_note)}</div></div>
    <div class="card"><div class="label">Position hit rate</div><div class="value">{_pct(winners / max(winners + losers, 1))}</div><div class="sub">{winners} up · {losers} down</div></div>
  </section>

  <section class="card" style="margin-bottom:18px">
    <h2>Position Value Bars</h2>
    <div class="chart">{bars}</div>
  </section>

  <div class="stack">
    <section class="card">
      <h2>Current Positions</h2>
      <table><thead><tr><th>Market</th><th>Side</th><th>Size</th><th>Avg</th><th>Now</th><th>Value</th><th>P&L</th><th>%</th></tr></thead><tbody>{rows}</tbody></table>
    </section>
    <section class="card">
      <h2>Historical Activity</h2>
      <div class="note">Deposits and trades below are past account events from Polymarket. They are not unallocated cash; use the Spendable CLOB cash card above for current capital available to the bot.</div>
      <table><thead><tr><th>Type</th><th>Time</th><th>Event amount</th><th>Outcome</th><th>Market</th></tr></thead><tbody>{activity_rows}</tbody></table>
    </section>
  </div>
</main>
</body>
</html>"""


def render_html(state: dict[str, Any], *, state_path: Path | None = None) -> str:
    summary = summarize(state)
    open_positions = sorted(_open_positions(state), key=lambda p: str(p.get("at") or ""), reverse=True)
    closed_positions = sorted(_closed_positions(state), key=lambda p: str(p.get("closed_at") or p.get("at") or ""), reverse=True)
    curve = equity_curve(state)
    pnl_class = "good" if summary.realized_pnl_usd >= 0 else "bad"
    bars = "".join(
        f'<div class="bar {"good" if point["cumulative_pnl_usd"] >= 0 else "bad"}" '
        f'title="{_esc(point["date"])} {_money(point["cumulative_pnl_usd"])}" '
        f'style="height:{max(8, min(120, abs(point["cumulative_pnl_usd"]) * 18 + 8)):.0f}px"></div>'
        for point in curve[-60:]
    ) or '<div class="empty">No closed positions yet.</div>'

    open_rows = "".join(
        f"<tr><td>{_esc(p.get('question') or p.get('slug'))}</td>"
        f"<td>{_format_dt(p.get('at'))}</td>"
        f"<td>{_as_float(p.get('yes_price')):.3f}</td>"
        f"<td>{_as_float(p.get('no_price')):.3f}</td>"
        f"<td>{_money(_as_float(p.get('entry_notional_usd')))}</td>"
        f"<td>{_format_dt(p.get('end_date'))}</td></tr>"
        for p in open_positions
    ) or '<tr><td colspan="6" class="empty">No open positions.</td></tr>'

    closed_rows = "".join(
        f"<tr><td>{_esc(p.get('question') or p.get('slug'))}</td>"
        f"<td>{_format_dt(p.get('closed_at') or p.get('at'))}</td>"
        f"<td>{_as_float(p.get('no_price')):.3f}</td>"
        f"<td>{_as_float(p.get('close_no_price')):.3f}</td>"
        f"<td class='{ 'good' if _as_float(p.get('pnl_usd')) >= 0 else 'bad' }'>{_money(_as_float(p.get('pnl_usd')))}</td>"
        f"<td>{_esc(p.get('closed_reason') or '-')}</td></tr>"
        for p in closed_positions[:100]
    ) or '<tr><td colspan="6" class="empty">No closed positions.</td></tr>'

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="60">
  <title>Polyautomate Portfolio</title>
  <style>
    :root {{ color-scheme: dark; --bg:#09110d; --card:#111d17; --line:#234031; --text:#eef7ef; --muted:#8aa092; --good:#49d17d; --bad:#ff6b6b; --gold:#e6c56b; }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: radial-gradient(circle at top left, #203b2d 0, #09110d 38%, #050806 100%); color:var(--text); }}
    main {{ max-width:1200px; margin:0 auto; padding:32px 20px 56px; }}
    header {{ display:flex; justify-content:space-between; gap:24px; align-items:flex-end; margin-bottom:28px; }}
    h1 {{ margin:0; font-size:40px; letter-spacing:-0.04em; }}
    h2 {{ margin:0 0 14px; font-size:18px; }}
    .sub {{ color:var(--muted); margin-top:8px; }}
    .grid {{ display:grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap:14px; margin-bottom:18px; }}
    .card {{ background:linear-gradient(180deg, rgba(255,255,255,.05), rgba(255,255,255,.02)); border:1px solid var(--line); border-radius:18px; padding:18px; box-shadow:0 24px 80px rgba(0,0,0,.22); }}
    .label {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.12em; }}
    .value {{ font-size:30px; font-weight:800; margin-top:8px; letter-spacing:-0.03em; }}
    .good {{ color:var(--good); }} .bad {{ color:var(--bad); }}
    .chart {{ display:flex; align-items:flex-end; gap:4px; height:150px; padding-top:20px; border-bottom:1px solid var(--line); overflow:hidden; }}
    .bar {{ width:10px; min-width:4px; border-radius:8px 8px 0 0; opacity:.85; }}
    .bar.good {{ background:linear-gradient(var(--good), rgba(73,209,125,.18)); }}
    .bar.bad {{ background:linear-gradient(var(--bad), rgba(255,107,107,.18)); }}
    table {{ width:100%; border-collapse:collapse; font-size:14px; }}
    th, td {{ padding:12px 10px; border-bottom:1px solid rgba(255,255,255,.07); text-align:left; vertical-align:top; }}
    th {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.08em; }}
    td:first-child {{ max-width:520px; }}
    .stack {{ display:grid; grid-template-columns: 1fr; gap:18px; }}
    .empty {{ color:var(--muted); padding:20px; text-align:center; }}
    .pill {{ border:1px solid var(--line); border-radius:999px; padding:7px 10px; color:var(--muted); font-size:13px; }}
    @media (max-width: 800px) {{ header {{ display:block; }} .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} .value {{ font-size:24px; }} main {{ padding:22px 12px 36px; }} table {{ font-size:12px; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div>
      <h1>Longshot Portfolio</h1>
      <div class="sub">Read-only view of executor state{f' at <code>{_esc(state_path)}</code>' if state_path else ''}. Auto-refreshes every 60 seconds.</div>
    </div>
    <div class="pill">Last bot cycle: {_format_dt(summary.last_run_at)} · candidates: {summary.last_candidates if summary.last_candidates is not None else '-'}</div>
  </header>

  <section class="grid">
    <div class="card"><div class="label">Realized P&L</div><div class="value {pnl_class}">{_money(summary.realized_pnl_usd)}</div></div>
    <div class="card"><div class="label">Win rate</div><div class="value">{_pct(summary.win_rate)}</div><div class="sub">{summary.wins} wins · {summary.losses} losses</div></div>
    <div class="card"><div class="label">Open exposure</div><div class="value">{_money(summary.open_entry_notional_usd)}</div><div class="sub">{summary.open_count} open positions</div></div>
    <div class="card"><div class="label">Closed trades</div><div class="value">{summary.closed_count}</div><div class="sub">Avg {_money(summary.avg_closed_pnl_usd)} · best {_money(summary.best_closed_pnl_usd)} · worst {_money(summary.worst_closed_pnl_usd)}</div></div>
  </section>

  <section class="card" style="margin-bottom:18px">
    <h2>Equity Curve</h2>
    <div class="chart">{bars}</div>
  </section>

  <div class="stack">
    <section class="card">
      <h2>Open Positions</h2>
      <table><thead><tr><th>Market</th><th>Opened</th><th>YES</th><th>NO</th><th>Entry notional</th><th>End date</th></tr></thead><tbody>{open_rows}</tbody></table>
    </section>

    <section class="card">
      <h2>Closed Positions</h2>
      <table><thead><tr><th>Market</th><th>Closed</th><th>Entry NO</th><th>Close NO</th><th>P&L</th><th>Reason</th></tr></thead><tbody>{closed_rows}</tbody></table>
    </section>
  </div>
</main>
</body>
</html>"""


def write_report(state_path: Path, output_path: Path) -> None:
    state = load_state(state_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_html(state, state_path=state_path), encoding="utf-8")


def write_data_api_report(user: str, output_path: Path, *, include_clob_balance: bool = False) -> None:
    payload = fetch_data_api_portfolio(user)
    spendable_usdc = _fetch_spendable_usdc_from_env() if include_clob_balance else None
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_data_api_html(payload, spendable_usdc=spendable_usdc),
        encoding="utf-8",
    )


def serve(state_path: Path, host: str, port: int, *, user: str | None = None, include_clob_balance: bool = False) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            if self.path not in {"/", "/index.html"}:
                self.send_response(404)
                self.end_headers()
                return
            try:
                if user:
                    spendable_usdc = _fetch_spendable_usdc_from_env() if include_clob_balance else None
                    body = render_data_api_html(
                        fetch_data_api_portfolio(user),
                        spendable_usdc=spendable_usdc,
                    ).encode("utf-8")
                else:
                    body = render_html(load_state(state_path), state_path=state_path).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:  # pragma: no cover - defensive HTTP fallback
                body = f"portfolio render failed: {exc}".encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"portfolio_dashboard {self.address_string()} {fmt % args}")

    server = ThreadingHTTPServer((host, port), Handler)
    source = f"Data API user {user}" if user else f"state file {state_path}"
    print(f"Serving portfolio dashboard on http://{host}:{port} from {source}")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a read-only dashboard for the longshot executor state file.")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH, help="Path to longshot-state.json")
    parser.add_argument("--user", help="Polymarket proxy/profile wallet address for Data API mode")
    parser.add_argument("--include-clob-balance", action="store_true", help="Read authenticated CLOB cash balance from POLYMARKET_* env vars")
    parser.add_argument("--out", type=Path, help="Write a static HTML report to this path")
    parser.add_argument("--serve", action="store_true", help="Serve the dashboard over HTTP")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host for --serve")
    parser.add_argument("--port", type=int, default=8765, help="HTTP port for --serve")
    args = parser.parse_args()

    if args.serve:
        serve(args.state, args.host, args.port, user=args.user, include_clob_balance=args.include_clob_balance)
        return
    if args.out:
        if args.user:
            write_data_api_report(args.user, args.out, include_clob_balance=args.include_clob_balance)
        else:
            write_report(args.state, args.out)
        print(f"wrote {args.out}")
        return

    if args.user:
        payload = fetch_data_api_portfolio(args.user)
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        state = load_state(args.state)
        summary = summarize(state)
        print(json.dumps(summary.__dict__, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
