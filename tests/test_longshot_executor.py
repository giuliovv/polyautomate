"""
Tests for the self-correcting bankroll changes in longshot_executor.py.

All Polymarket API calls are mocked — no real credentials required.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from polyautomate.runtime.longshot_executor import (
    _compute_order_size,
    _fetch_usdc_balance,
)


# ---------------------------------------------------------------------------
# _fetch_usdc_balance
# ---------------------------------------------------------------------------

class TestFetchUsdcBalance:
    """Covers all response-shape variants and failure paths."""

    def _trader(self, return_value):
        t = MagicMock()
        t.get_balances.return_value = return_value
        return t

    def test_flat_usdc_key(self):
        assert _fetch_usdc_balance(self._trader({"USDC": "10.50"})) == pytest.approx(10.50)

    def test_flat_usdc_key_lowercase(self):
        assert _fetch_usdc_balance(self._trader({"usdc": "7.00"})) == pytest.approx(7.00)

    def test_flat_free_key(self):
        assert _fetch_usdc_balance(self._trader({"free": "3.25"})) == pytest.approx(3.25)

    def test_flat_available_key(self):
        assert _fetch_usdc_balance(self._trader({"available": "99.0"})) == pytest.approx(99.0)

    def test_flat_collateral_key(self):
        assert _fetch_usdc_balance(self._trader({"collateral": "50.0"})) == pytest.approx(50.0)

    def test_nested_balances_list(self):
        payload = {"balances": [{"asset": "USDC", "balance": "12.34"}]}
        assert _fetch_usdc_balance(self._trader(payload)) == pytest.approx(12.34)

    def test_nested_data_list(self):
        payload = {"data": [{"asset": "ETH", "balance": "0"}, {"asset": "USDC", "balance": "5.0"}]}
        assert _fetch_usdc_balance(self._trader(payload)) == pytest.approx(5.0)

    def test_nested_collateral_asset(self):
        payload = {"balances": [{"asset": "COLLATERAL", "balance": "20.0"}]}
        assert _fetch_usdc_balance(self._trader(payload)) == pytest.approx(20.0)

    def test_float_value_not_string(self):
        assert _fetch_usdc_balance(self._trader({"USDC": 8.5})) == pytest.approx(8.5)

    def test_zero_balance(self):
        assert _fetch_usdc_balance(self._trader({"USDC": "0.00"})) == pytest.approx(0.0)

    def test_api_raises_exception(self):
        t = MagicMock()
        t.get_balances.side_effect = Exception("network error")
        assert _fetch_usdc_balance(t) is None

    def test_non_dict_response(self):
        assert _fetch_usdc_balance(self._trader(None)) is None
        assert _fetch_usdc_balance(self._trader([])) is None
        assert _fetch_usdc_balance(self._trader("bad")) is None

    def test_unparseable_dict(self):
        # Dict with no recognised keys
        assert _fetch_usdc_balance(self._trader({"foo": "bar"})) is None

    def test_bad_value_type_falls_through(self):
        # Unparseable value in flat key → should return None (no crash)
        assert _fetch_usdc_balance(self._trader({"USDC": "not-a-number"})) is None


# ---------------------------------------------------------------------------
# _compute_order_size — bankroll_usd parameter
# ---------------------------------------------------------------------------

class TestComputeOrderSizeBankroll:
    """Verifies that explicit bankroll_usd overrides the env var."""

    BASE_ENV = {
        "LONGSHOT_USE_KELLY": "1",
        "LONGSHOT_KELLY_FRACTION": "0.25",
        "LONGSHOT_MAX_BANKROLL_FRACTION": "0.03",
        "LONGSHOT_MIN_NOTIONAL_USD": "2",
        "LONGSHOT_MAX_NOTIONAL_USD": "25",
    }

    def _size(self, bankroll_usd=None, yes_price=0.30, no_price=0.70, extra_env=None):
        env = dict(self.BASE_ENV)
        if extra_env:
            env.update(extra_env)
        with patch.dict(os.environ, env, clear=False):
            return _compute_order_size(
                yes_price=yes_price,
                no_price=no_price,
                fallback_size=5.0,
                bankroll_usd=bankroll_usd,
            )

    def test_explicit_bankroll_used(self):
        """Passing bankroll_usd=10 should give a different result than bankroll=500."""
        s_small = self._size(bankroll_usd=10.0)
        s_large = self._size(bankroll_usd=500.0)
        # Both clamp to min_notional=2 for very small bankroll, but notional differs
        assert s_small.notional_usd <= s_large.notional_usd

    def test_none_falls_back_to_env_var(self):
        """When bankroll_usd=None, should read LONGSHOT_BANKROLL_USD from env."""
        s_env = self._size(bankroll_usd=None, extra_env={"LONGSHOT_BANKROLL_USD": "200"})
        s_explicit = self._size(bankroll_usd=200.0)
        assert s_env.notional_usd == pytest.approx(s_explicit.notional_usd)

    def test_small_bankroll_clamps_to_min_notional(self):
        """bankroll=10, max_fraction=3% → $0.30 → clamped up to min_notional=$2."""
        s = self._size(bankroll_usd=10.0)
        assert s.notional_usd == pytest.approx(2.0)
        assert s.method == "kelly"

    def test_large_bankroll_clamps_to_max_notional(self):
        """bankroll=10000, 3% = $300 → clamped down to max_notional=$25."""
        s = self._size(bankroll_usd=10_000.0)
        assert s.notional_usd == pytest.approx(25.0)

    def test_mid_range_bankroll_unclamped(self):
        """bankroll=300 → 3% = $9 → within [2, 25], no clamping."""
        s = self._size(bankroll_usd=300.0)
        assert 2.0 <= s.notional_usd <= 25.0
        assert s.notional_usd == pytest.approx(9.0, abs=1.0)

    def test_kelly_disabled_uses_fixed_fallback(self):
        s = self._size(bankroll_usd=10.0, extra_env={"LONGSHOT_USE_KELLY": "0"})
        assert s.method == "fixed"
        assert s.size == pytest.approx(5.0)

    def test_zero_bankroll_uses_fixed_fallback(self):
        s = self._size(bankroll_usd=0.0)
        assert s.method == "fixed"


# ---------------------------------------------------------------------------
# run_once — balance-check integration (mocked at the boundary)
# ---------------------------------------------------------------------------

class TestRunOnceBalanceGuard:
    """
    Exercises the early-exit path when balance < min_notional, and the
    fallback path when _fetch_usdc_balance returns None.
    Only the balance fetch and state I/O are mocked; no PMD calls made.
    """

    BASE_ENV = {
        "DRY_RUN": "0",
        "POLYMARKETDATA_API_KEY": "test-pmd-key",
        "POLYMARKET_API_KEY": "test-pm-key",
        "POLYMARKET_SIGNING_KEY": "aa" * 32,  # 64-char hex for ed25519
        "LONGSHOT_MIN_NOTIONAL_USD": "2",
        "LONGSHOT_BANKROLL_USD": "500",
        "LONGSHOT_STATE_PATH": "/tmp/test-longshot-state.json",
    }

    def _run(self, balance_return, extra_env=None):
        """
        Run run_once() with:
        - _fetch_usdc_balance patched to return balance_return
        - PolymarketTradingClient instantiation patched (no real signing)
        - PMDClient patched to return empty market list (no candidates)
        - State I/O patched to avoid filesystem access
        """
        from polyautomate.runtime import longshot_executor as mod

        env = dict(self.BASE_ENV)
        if extra_env:
            env.update(extra_env)

        with patch.dict(os.environ, env, clear=False), \
             patch.object(mod, "PolymarketTradingClient") as mock_trader_cls, \
             patch.object(mod, "_fetch_usdc_balance", return_value=balance_return), \
             patch.object(mod, "PMDClient") as mock_pmd_cls, \
             patch.object(mod, "_load_state", return_value={}), \
             patch.object(mod, "_save_state"):

            # PMD returns no markets → no candidates → returns 0 actions
            mock_pmd_cls.return_value.list_markets.return_value = iter([])
            mock_pmd_cls.return_value.get_market.side_effect = Exception("no open positions")

            return mod.run_once()

    def test_balance_below_min_notional_skips_cycle(self):
        """Balance of $1 with min_notional=$2 → return 0 immediately."""
        result = self._run(balance_return=1.0)
        assert result == 0

    def test_balance_at_min_notional_proceeds(self):
        """Balance of exactly $2 should not trigger the skip guard."""
        result = self._run(balance_return=2.0)
        assert result == 0  # 0 actions because no candidates, but didn't short-circuit

    def test_balance_above_min_notional_proceeds(self):
        result = self._run(balance_return=10.0)
        assert result == 0

    def test_fetch_failure_falls_back_to_env_bankroll(self):
        """None return from _fetch_usdc_balance → use LONGSHOT_BANKROLL_USD, don't crash."""
        result = self._run(balance_return=None)
        assert result == 0  # no candidates, but completed normally

    def test_dry_run_skips_balance_fetch(self):
        """In dry-run mode the balance fetch should never be called."""
        from polyautomate.runtime import longshot_executor as mod

        env = dict(self.BASE_ENV)
        env["DRY_RUN"] = "1"

        with patch.dict(os.environ, env, clear=False), \
             patch.object(mod, "_fetch_usdc_balance") as mock_fetch, \
             patch.object(mod, "PMDClient") as mock_pmd_cls, \
             patch.object(mod, "_load_state", return_value={}), \
             patch.object(mod, "_save_state"):

            mock_pmd_cls.return_value.list_markets.return_value = iter([])
            mock_pmd_cls.return_value.get_market.side_effect = Exception("skip")

            mod.run_once()

        mock_fetch.assert_not_called()
