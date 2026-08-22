from __future__ import annotations

import json
from pathlib import Path

import pytest

from polyautomate.portfolio import equity_curve, load_state, render_html, summarize, write_report


def sample_state():
    return {
        "last_run_at": "2026-08-22T12:00:00+00:00",
        "last_candidates": 7,
        "open_positions": {
            "open-market": {
                "slug": "open-market",
                "question": "Will this still be open?",
                "at": "2026-08-21T10:00:00+00:00",
                "yes_price": 0.22,
                "no_price": 0.78,
                "entry_notional_usd": 3.5,
                "end_date": "2026-09-01T00:00:00+00:00",
            }
        },
        "closed_positions": [
            {
                "slug": "win-market",
                "question": "Winning market",
                "at": "2026-08-20T10:00:00+00:00",
                "closed_at": "2026-08-21T10:00:00+00:00",
                "no_price": 0.70,
                "close_no_price": 0.95,
                "entry_order_size": 10,
                "pnl_usd": 2.5,
                "closed_reason": "resolved",
            },
            {
                "slug": "loss-market",
                "question": "Losing market",
                "at": "2026-08-21T10:00:00+00:00",
                "closed_at": "2026-08-22T10:00:00+00:00",
                "no_price": 0.70,
                "close_no_price": 0.10,
                "entry_order_size": 10,
                "pnl_usd": -6.0,
                "closed_reason": "resolved",
            },
        ],
    }


def test_summarize_portfolio_state():
    summary = summarize(sample_state())

    assert summary.open_count == 1
    assert summary.closed_count == 2
    assert summary.realized_pnl_usd == pytest.approx(-3.5)
    assert summary.open_entry_notional_usd == pytest.approx(3.5)
    assert summary.wins == 1
    assert summary.losses == 1
    assert summary.win_rate == pytest.approx(0.5)
    assert summary.best_closed_pnl_usd == pytest.approx(2.5)
    assert summary.worst_closed_pnl_usd == pytest.approx(-6.0)


def test_equity_curve_is_chronological_and_cumulative():
    points = equity_curve(sample_state())

    assert [p["slug"] for p in points] == ["win-market", "loss-market"]
    assert points[0]["cumulative_pnl_usd"] == pytest.approx(2.5)
    assert points[1]["cumulative_pnl_usd"] == pytest.approx(-3.5)


def test_load_state_migrates_legacy_traded_schema(tmp_path: Path):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"traded": {"legacy": {"slug": "legacy"}}}), encoding="utf-8")

    state = load_state(state_path)

    assert "legacy" in state["open_positions"]
    assert state["closed_positions"] == []


def test_write_report_contains_positions(tmp_path: Path):
    state_path = tmp_path / "state.json"
    out_path = tmp_path / "portfolio.html"
    state_path.write_text(json.dumps(sample_state()), encoding="utf-8")

    write_report(state_path, out_path)

    html = out_path.read_text(encoding="utf-8")
    assert "Longshot Portfolio" in html
    assert "Winning market" in html
    assert "Losing market" in html
    assert "Will this still be open?" in html


def test_render_escapes_market_text():
    state = sample_state()
    state["open_positions"]["open-market"]["question"] = "<script>alert(1)</script>"

    html = render_html(state)

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
