'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { api } from '@/lib/api';
import { cn } from '@/lib/utils';

interface Strategy {
  id: string;
  name: string;
  description: string;
}

interface BacktestSummary {
  backtest_id: string;
  status: string;
  strategy_name: string;
  market_id: string;
  token_label: string;
  n_trades: number | null;
  win_rate: number | null;
  total_pnl: number | null;
  created_at: string | null;
  error_message: string | null;
}

export default function BacktestPage() {
  const router = useRouter();
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [recentBacktests, setRecentBacktests] = useState<BacktestSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const [formData, setFormData] = useState({
    strategy: 'longshot',
    market_id: '',
    token_label: 'YES',
    start_date: '',
    end_date: '',
    resolution: '1h',
    stop_loss: 0.05,
    take_profit: 0.10,
    hold_periods: 24,
    position_size: 100,
  });

  useEffect(() => {
    async function loadData() {
      try {
        const [strategiesData, backtestsData] = await Promise.all([
          api.getBacktestStrategies(),
          api.listBacktests(),
        ]);
        setStrategies(strategiesData);
        setRecentBacktests(backtestsData);

        // Set default dates (last 30 days)
        const endDate = new Date();
        const startDate = new Date();
        startDate.setDate(startDate.getDate() - 30);

        setFormData((prev) => ({
          ...prev,
          start_date: startDate.toISOString().split('T')[0],
          end_date: endDate.toISOString().split('T')[0],
        }));
      } catch (error) {
        console.error('Failed to load data:', error);
      } finally {
        setLoading(false);
      }
    }

    loadData();
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!formData.market_id || !formData.start_date || !formData.end_date) {
      return;
    }

    setSubmitting(true);
    try {
      const result = await api.runBacktest({
        strategy: formData.strategy,
        market_id: formData.market_id,
        token_label: formData.token_label,
        start_date: formData.start_date,
        end_date: formData.end_date,
        resolution: formData.resolution,
        stop_loss: formData.stop_loss,
        take_profit: formData.take_profit,
        hold_periods: formData.hold_periods,
        position_size: formData.position_size,
      });

      router.push(`/dashboard/backtest/results/${result.backtest_id}`);
    } catch (error) {
      console.error('Failed to run backtest:', error);
    } finally {
      setSubmitting(false);
    }
  }

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return '-';
    return new Date(dateStr).toLocaleDateString();
  };

  const formatPnl = (value: number | null) => {
    if (value === null) return '-';
    const prefix = value >= 0 ? '+' : '';
    return `${prefix}${(value * 100).toFixed(2)}%`;
  };

  if (loading) {
    return <div className="flex items-center justify-center h-64">Loading...</div>;
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Backtest</h1>

      {/* Backtest Form */}
      <div className="p-6 rounded-lg border bg-card mb-6">
        <h2 className="font-semibold mb-4">Run New Backtest</h2>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Strategy */}
            <div>
              <label className="block text-sm font-medium mb-1">Strategy</label>
              <select
                value={formData.strategy}
                onChange={(e) => setFormData({ ...formData, strategy: e.target.value })}
                className="w-full px-3 py-2 border rounded-md"
              >
                {strategies.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
              <p className="text-xs text-muted-foreground mt-1">
                {strategies.find((s) => s.id === formData.strategy)?.description}
              </p>
            </div>

            {/* Market ID */}
            <div>
              <label className="block text-sm font-medium mb-1">Market ID</label>
              <input
                type="text"
                value={formData.market_id}
                onChange={(e) => setFormData({ ...formData, market_id: e.target.value })}
                placeholder="Polymarket market UUID"
                className="w-full px-3 py-2 border rounded-md"
                required
              />
              <p className="text-xs text-muted-foreground mt-1">
                Find market IDs at polymarket.com
              </p>
            </div>

            {/* Token */}
            <div>
              <label className="block text-sm font-medium mb-1">Token</label>
              <select
                value={formData.token_label}
                onChange={(e) => setFormData({ ...formData, token_label: e.target.value })}
                className="w-full px-3 py-2 border rounded-md"
              >
                <option value="YES">YES</option>
                <option value="NO">NO</option>
              </select>
            </div>

            {/* Resolution */}
            <div>
              <label className="block text-sm font-medium mb-1">Resolution</label>
              <select
                value={formData.resolution}
                onChange={(e) => setFormData({ ...formData, resolution: e.target.value })}
                className="w-full px-3 py-2 border rounded-md"
              >
                <option value="1m">1 minute</option>
                <option value="10m">10 minutes</option>
                <option value="1h">1 hour</option>
                <option value="6h">6 hours</option>
                <option value="1d">1 day</option>
              </select>
            </div>

            {/* Date Range */}
            <div>
              <label className="block text-sm font-medium mb-1">Start Date</label>
              <input
                type="date"
                value={formData.start_date}
                onChange={(e) => setFormData({ ...formData, start_date: e.target.value })}
                className="w-full px-3 py-2 border rounded-md"
                required
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-1">End Date</label>
              <input
                type="date"
                value={formData.end_date}
                onChange={(e) => setFormData({ ...formData, end_date: e.target.value })}
                className="w-full px-3 py-2 border rounded-md"
                required
              />
            </div>
          </div>

          {/* Advanced Options */}
          <div>
            <button
              type="button"
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="text-sm text-muted-foreground hover:text-foreground"
            >
              {showAdvanced ? '- Hide' : '+ Show'} Advanced Options
            </button>

            {showAdvanced && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4">
                <div>
                  <label className="block text-sm font-medium mb-1">Stop Loss</label>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    max="1"
                    value={formData.stop_loss}
                    onChange={(e) =>
                      setFormData({ ...formData, stop_loss: parseFloat(e.target.value) })
                    }
                    className="w-full px-3 py-2 border rounded-md"
                  />
                  <p className="text-xs text-muted-foreground mt-1">
                    {(formData.stop_loss * 100).toFixed(0)}%
                  </p>
                </div>

                <div>
                  <label className="block text-sm font-medium mb-1">Take Profit</label>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    max="1"
                    value={formData.take_profit}
                    onChange={(e) =>
                      setFormData({ ...formData, take_profit: parseFloat(e.target.value) })
                    }
                    className="w-full px-3 py-2 border rounded-md"
                  />
                  <p className="text-xs text-muted-foreground mt-1">
                    {(formData.take_profit * 100).toFixed(0)}%
                  </p>
                </div>

                <div>
                  <label className="block text-sm font-medium mb-1">Hold Periods</label>
                  <input
                    type="number"
                    min="1"
                    value={formData.hold_periods}
                    onChange={(e) =>
                      setFormData({ ...formData, hold_periods: parseInt(e.target.value) })
                    }
                    className="w-full px-3 py-2 border rounded-md"
                  />
                  <p className="text-xs text-muted-foreground mt-1">Max bars to hold</p>
                </div>

                <div>
                  <label className="block text-sm font-medium mb-1">Position Size</label>
                  <input
                    type="number"
                    min="1"
                    value={formData.position_size}
                    onChange={(e) =>
                      setFormData({ ...formData, position_size: parseFloat(e.target.value) })
                    }
                    className="w-full px-3 py-2 border rounded-md"
                  />
                  <p className="text-xs text-muted-foreground mt-1">USD per trade</p>
                </div>
              </div>
            )}
          </div>

          <button
            type="submit"
            disabled={submitting || !formData.market_id}
            className="px-6 py-2 bg-primary text-primary-foreground rounded-md disabled:opacity-50"
          >
            {submitting ? 'Running...' : 'Run Backtest'}
          </button>
        </form>
      </div>

      {/* Recent Backtests */}
      <div className="p-6 rounded-lg border bg-card">
        <h2 className="font-semibold mb-4">Recent Backtests</h2>

        {recentBacktests.length === 0 ? (
          <p className="text-muted-foreground">No backtests yet. Run one above!</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b">
                  <th className="text-left py-2 px-2 text-sm font-medium">Strategy</th>
                  <th className="text-left py-2 px-2 text-sm font-medium">Market</th>
                  <th className="text-left py-2 px-2 text-sm font-medium">Token</th>
                  <th className="text-left py-2 px-2 text-sm font-medium">Trades</th>
                  <th className="text-left py-2 px-2 text-sm font-medium">Win Rate</th>
                  <th className="text-left py-2 px-2 text-sm font-medium">P&L</th>
                  <th className="text-left py-2 px-2 text-sm font-medium">Status</th>
                  <th className="text-left py-2 px-2 text-sm font-medium">Date</th>
                  <th className="text-left py-2 px-2 text-sm font-medium"></th>
                </tr>
              </thead>
              <tbody>
                {recentBacktests.map((bt) => (
                  <tr key={bt.backtest_id} className="border-b hover:bg-accent/50">
                    <td className="py-2 px-2 text-sm capitalize">{bt.strategy_name}</td>
                    <td className="py-2 px-2 text-sm font-mono text-xs">
                      {bt.market_id.slice(0, 8)}...
                    </td>
                    <td className="py-2 px-2 text-sm">{bt.token_label}</td>
                    <td className="py-2 px-2 text-sm">{bt.n_trades ?? '-'}</td>
                    <td className="py-2 px-2 text-sm">
                      {bt.win_rate !== null ? `${(bt.win_rate * 100).toFixed(1)}%` : '-'}
                    </td>
                    <td
                      className={cn(
                        'py-2 px-2 text-sm',
                        bt.total_pnl !== null && bt.total_pnl >= 0
                          ? 'text-green-600'
                          : 'text-red-600'
                      )}
                    >
                      {formatPnl(bt.total_pnl)}
                    </td>
                    <td className="py-2 px-2">
                      <span
                        className={cn(
                          'text-xs px-2 py-1 rounded',
                          bt.status === 'completed'
                            ? 'bg-green-100 text-green-800'
                            : bt.status === 'failed'
                            ? 'bg-red-100 text-red-800'
                            : bt.status === 'running'
                            ? 'bg-blue-100 text-blue-800'
                            : 'bg-gray-100 text-gray-800'
                        )}
                      >
                        {bt.status}
                      </span>
                    </td>
                    <td className="py-2 px-2 text-sm text-muted-foreground">
                      {formatDate(bt.created_at)}
                    </td>
                    <td className="py-2 px-2">
                      <Link
                        href={`/dashboard/backtest/results/${bt.backtest_id}`}
                        className="text-sm text-primary hover:underline"
                      >
                        View
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
