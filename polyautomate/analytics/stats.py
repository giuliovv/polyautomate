"""
Statistical utilities for backtest result validation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import BacktestResult


@dataclass(frozen=True)
class ConfidenceInterval:
    lower: float
    upper: float
    n: int

    def __str__(self) -> str:
        return f"[{self.lower:.1%}, {self.upper:.1%}]  n={self.n}"


def wilson_ci(wins: int, n: int, z: float = 1.96) -> ConfidenceInterval:
    """
    Wilson score 95 % confidence interval for a binomial win rate.

    More accurate than the normal approximation, especially for small n or
    extreme win rates.
    """
    if n == 0:
        return ConfidenceInterval(0.0, 1.0, 0)
    p = wins / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1.0 - p) / n + z * z / (4 * n * n)) / denom
    return ConfidenceInterval(
        lower=max(0.0, centre - margin),
        upper=min(1.0, centre + margin),
        n=n,
    )


def min_trades_for_significance(
    observed_win_rate: float = 0.75,
    null_win_rate: float = 0.50,
    alpha: float = 0.05,
    power: float = 0.80,
) -> int:
    """
    Minimum number of trades needed to detect ``observed_win_rate`` vs
    the null hypothesis of ``null_win_rate`` at the given significance level
    and power (two-proportion z-test approximation).
    """
    z_alpha = 1.96 if alpha == 0.05 else 2.576  # one-sided 5 % or 1 %
    z_beta = 0.842 if power == 0.80 else 1.282   # 80 % or 90 % power
    p0, p1 = null_win_rate, observed_win_rate
    p_bar = (p0 + p1) / 2
    num = (z_alpha * math.sqrt(2 * p_bar * (1 - p_bar)) +
           z_beta * math.sqrt(p0 * (1 - p0) + p1 * (1 - p1))) ** 2
    denom = (p1 - p0) ** 2
    return math.ceil(num / denom)


# ── Correlation helpers ───────────────────────────────────────────────────────

def _pearson(a: list[float], b: list[float]) -> float | None:
    n = min(len(a), len(b))
    if n < 3:
        return None
    a, b = a[:n], b[:n]
    ma = sum(a) / n
    mb = sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((x - mb) ** 2 for x in b)
    if va == 0.0 or vb == 0.0:
        return None
    return cov / math.sqrt(va * vb)


def price_correlation_matrix(
    price_series: dict[str, list[float]],
) -> dict[tuple[str, str], float | None]:
    """
    Compute pairwise Pearson correlations between price series.

    Parameters
    ----------
    price_series:
        ``{market_label: [price_at_t0, price_at_t1, ...]}``

    Returns
    -------
    dict mapping ``(label_a, label_b)`` → correlation coefficient.
    """
    labels = sorted(price_series)
    result: dict[tuple[str, str], float | None] = {}
    for i, a in enumerate(labels):
        for b in labels[i + 1 :]:
            result[(a, b)] = _pearson(price_series[a], price_series[b])
    return result


def effective_sample_size(correlations: list[float | None]) -> float:
    """
    Rough effective N given a list of pairwise correlations.

    Uses the formula  n_eff = n / (1 + (n-1) * mean_|rho|) where n is the
    number of series, applied to the upper-triangle correlations.
    """
    rhos = [abs(r) for r in correlations if r is not None]
    if not rhos:
        return float("nan")
    n = (1 + math.sqrt(1 + 8 * len(rhos))) / 2  # solve k*(k-1)/2 = len
    mean_rho = sum(rhos) / len(rhos)
    return n / (1.0 + (n - 1) * mean_rho)
