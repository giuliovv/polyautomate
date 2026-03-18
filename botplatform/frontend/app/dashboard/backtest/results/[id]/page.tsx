'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { api } from '@/lib/api';
import { cn } from '@/lib/utils';
import { ChartContainer, EquityCurveChart } from '@/components/charts';

interface BacktestResult {
  backtest_id: string;
  status: string;
  strategy_name: string;
  market_id: string;
  token_label: string;
  resolution: string;
  n_trades: number | null;
  win_rate: number | null;
  win_rate_ci_low: number | null;
  win_rate_ci_high: number | null;
  total_pnl: number | null;
  avg_pnl: number | null;
  max_drawdown: number | null;
  sharpe_ratio: number | null;
  exit_reason_breakdown: Record<string, number> | null;
  trades: Array<{
    entry_timestamp: string;
    exit_timestamp: string | null;
    direction: string;
    entry_price: number;
    exit_price: number | null;
    pnl: number | null;
    exit_reason: string | null;
  }> | null;
  equity_curve: Array<{
    timestamp: string;
    cumulative_pnl: number;
  }> | null;
  error_message: string | null;
  created_at: string | null;
  completed_at: string | null;
}

export default function BacktestResultPage() {
  const params = useParams();
  const backtestId = params.id as string;

  const [result, setResult] = useState<BacktestResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [polling, setPolling] = useState(false);

  useEffect(() => {
    async function loadResult() {
      try {
        const data = await api.getBacktestResult(backtestId);
        setResult(data);

        // Poll if still running
        if (data.status === 'running' || data.status === 'pending') {
          setPolling(true);
        } else {
          setPolling(false);
        }
      } catch (error) {
        console.error('Failed to load backtest:', error);
      } finally {
        setLoading(false);
      }
    }

    loadResult();
  }, [backtestId]);

  // Poll for updates if running
  useEffect(() => {
    if (!polling) return;

    const interval = setInterval(async () => {
      try {
        const data = await api.getBacktestResult(backtestId);
        setResult(data);

        if (data.status !== 'running' && data.status !== 'pending') {
          setPolling(false);
        }
      } catch (error) {
        console.error('Failed to poll backtest:', error);
      }
    }, 2000);

    return () => clearInterval(interval);
  }, [polling, backtestId]);

  const formatPnl = (value: number | null, isPercentage = true) => {
    if (value === null) return '-';
    const displayValue = isPercentage ? value * 100 : value;
    const prefix = displayValue >= 0 ? '+' : '';
    return `${prefix}${displayValue.toFixed(2)}${isPercentage ? '%' : ''}`;
  };

  const formatTimestamp = (ts: string | null) => {
    if (!ts) return '-';
    return new Date(ts).toLocaleString();
  };

  // Convert equity curve for chart
  const equityCurveData =
    result?.equity_curve?.map((point) => ({
      date: point.timestamp,
      pnl: point.cumulative_pnl * 100, // Convert to percentage points
      cumulative_pnl: point.cumulative_pnl * 100,
      trade_count: 1,
    })) ?? [];

  if (loading) {
    return <div className="flex items-center justify-center h-64">Loading...</div>;
  }

  if (!result) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4">
        <p className="text-muted-foreground">Backtest not found</p>
        <Link
          href="/dashboard/backtest"
          className="px-4 py-2 bg-primary text-primary-foreground rounded-md text-sm"
        >
          Back to Backtest
        </Link>
      </div>
    );
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-center gap-4 mb-6">
        <Link
          href="/dashboard/backtest"
          className="text-muted-foreground hover:text-foreground"
        >
          &larr; Backtest
        </Link>
        <h1 className="text-2xl font-bold capitalize">{result.strategy_name} Backtest</h1>
        <span
          className={cn(
            'px-2 py-1 rounded text-xs',
            result.status === 'completed'
              ? 'bg-green-100 text-green-800'
              : result.status === 'failed'
              ? 'bg-red-100 text-red-800'
              : result.status === 'running'
              ? 'bg-blue-100 text-blue-800'
              : 'bg-gray-100 text-gray-800'
          )}
        >
          {result.status}
          {polling && '...'}
        </span>
      </div>

      {/* Error Message */}
      {result.error_message && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-800">
          <p className="font-medium">Backtest Failed</p>
          <p className="text-sm">{result.error_message}</p>
        </div>
      )}

      {/* Still Running */}
      {(result.status === 'running' || result.status === 'pending') && (
        <div className="mb-6 p-4 bg-blue-50 border border-blue-200 rounded-lg text-blue-800">
          <p className="font-medium">Backtest Running</p>
          <p className="text-sm">This may take a minute. Results will appear automatically.</p>
        </div>
      )}

      {/* Market Info */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div className="p-4 rounded-lg border bg-card">
          <p className="text-sm text-muted-foreground">Market ID</p>
          <p className="text-sm font-mono truncate">{result.market_id}</p>
        </div>
        <div className="p-4 rounded-lg border bg-card">
          <p className="text-sm text-muted-foreground">Token</p>
          <p className="text-lg font-semibold">{result.token_label}</p>
        </div>
        <div className="p-4 rounded-lg border bg-card">
          <p className="text-sm text-muted-foreground">Resolution</p>
          <p className="text-lg font-semibold">{result.resolution}</p>
        </div>
        <div className="p-4 rounded-lg border bg-card">
          <p className="text-sm text-muted-foreground">Created</p>
          <p className="text-sm">{formatTimestamp(result.created_at)}</p>
        </div>
      </div>

      {/* Results (only if completed) */}
      {result.status === 'completed' && (
        <>
          {/* Summary Stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <div className="p-4 rounded-lg border bg-card">
              <p className="text-sm text-muted-foreground">Total Trades</p>
              <p className="text-2xl font-bold">{result.n_trades ?? 0}</p>
            </div>
            <div className="p-4 rounded-lg border bg-card">
              <p className="text-sm text-muted-foreground">Win Rate</p>
              <p className="text-2xl font-bold">
                {result.win_rate !== null ? `${(result.win_rate * 100).toFixed(1)}%` : '-'}
              </p>
              {result.win_rate_ci_low !== null && result.win_rate_ci_high !== null && (
                <p className="text-xs text-muted-foreground">
                  95% CI: [{(result.win_rate_ci_low * 100).toFixed(1)}%,{' '}
                  {(result.win_rate_ci_high * 100).toFixed(1)}%]
                </p>
              )}
            </div>
            <div className="p-4 rounded-lg border bg-card">
              <p className="text-sm text-muted-foreground">Total P&L</p>
              <p
                className={cn(
                  'text-2xl font-bold',
                  (result.total_pnl ?? 0) >= 0 ? 'text-green-600' : 'text-red-600'
                )}
              >
                {formatPnl(result.total_pnl)}
              </p>
            </div>
            <div className="p-4 rounded-lg border bg-card">
              <p className="text-sm text-muted-foreground">Avg P&L</p>
              <p
                className={cn(
                  'text-2xl font-bold',
                  (result.avg_pnl ?? 0) >= 0 ? 'text-green-600' : 'text-red-600'
                )}
              >
                {formatPnl(result.avg_pnl)}
              </p>
            </div>
          </div>

          {/* Advanced Stats */}
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-6">
            <div className="p-4 rounded-lg border bg-card">
              <p className="text-sm text-muted-foreground">Sharpe Ratio</p>
              <p className="text-lg font-semibold">
                {result.sharpe_ratio !== null ? result.sharpe_ratio.toFixed(3) : '-'}
              </p>
            </div>
            <div className="p-4 rounded-lg border bg-card">
              <p className="text-sm text-muted-foreground">Max Drawdown</p>
              <p className="text-lg font-semibold text-red-600">
                {result.max_drawdown !== null
                  ? `${(result.max_drawdown * 100).toFixed(2)}%`
                  : '-'}
              </p>
            </div>
            {result.exit_reason_breakdown && (
              <div className="p-4 rounded-lg border bg-card">
                <p className="text-sm text-muted-foreground mb-2">Exit Reasons</p>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(result.exit_reason_breakdown).map(([reason, count]) => (
                    <span
                      key={reason}
                      className={cn(
                        'text-xs px-2 py-1 rounded',
                        reason === 'take_profit'
                          ? 'bg-green-100 text-green-800'
                          : reason === 'stop_loss'
                          ? 'bg-red-100 text-red-800'
                          : 'bg-gray-100 text-gray-800'
                      )}
                    >
                      {reason.replace('_', ' ')}: {count}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Equity Curve */}
          {equityCurveData.length > 0 && (
            <ChartContainer
              title="Equity Curve"
              subtitle="Cumulative P&L over time (percentage points)"
              className="mb-6"
            >
              <EquityCurveChart data={equityCurveData} />
            </ChartContainer>
          )}

          {/* Trade Table */}
          {result.trades && result.trades.length > 0 && (
            <div className="p-6 rounded-lg border bg-card">
              <h3 className="font-semibold mb-4">Trade Log</h3>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b">
                      <th className="text-left py-2 px-2">#</th>
                      <th className="text-left py-2 px-2">Direction</th>
                      <th className="text-left py-2 px-2">Entry</th>
                      <th className="text-left py-2 px-2">Exit</th>
                      <th className="text-left py-2 px-2">P&L</th>
                      <th className="text-left py-2 px-2">Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.trades.map((trade, i) => (
                      <tr key={i} className="border-b hover:bg-accent/50">
                        <td className="py-2 px-2 text-muted-foreground">{i + 1}</td>
                        <td className="py-2 px-2">
                          <span
                            className={cn(
                              'px-2 py-1 rounded text-xs',
                              trade.direction === 'buy'
                                ? 'bg-green-100 text-green-800'
                                : 'bg-red-100 text-red-800'
                            )}
                          >
                            {trade.direction}
                          </span>
                        </td>
                        <td className="py-2 px-2 font-mono">
                          {trade.entry_price.toFixed(4)}
                        </td>
                        <td className="py-2 px-2 font-mono">
                          {trade.exit_price?.toFixed(4) ?? '-'}
                        </td>
                        <td
                          className={cn(
                            'py-2 px-2 font-mono',
                            (trade.pnl ?? 0) >= 0 ? 'text-green-600' : 'text-red-600'
                          )}
                        >
                          {formatPnl(trade.pnl)}
                        </td>
                        <td className="py-2 px-2">
                          <span
                            className={cn(
                              'text-xs px-2 py-1 rounded',
                              trade.exit_reason === 'take_profit'
                                ? 'bg-green-100 text-green-800'
                                : trade.exit_reason === 'stop_loss'
                                ? 'bg-red-100 text-red-800'
                                : 'bg-gray-100 text-gray-800'
                            )}
                          >
                            {trade.exit_reason?.replace('_', ' ') ?? '-'}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
