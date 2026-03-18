'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { api } from '@/lib/api';
import { cn } from '@/lib/utils';
import {
  ChartContainer,
  EquityCurveChart,
  WinRateChart,
  TradeActivityChart,
  type EquityCurveDataPoint,
  type TradeActivityDataPoint,
} from '@/components/charts';

interface BotMetrics {
  bot_id: string;
  bot_name: string;
  total_trades: number;
  open_trades: number;
  closed_trades: number;
  total_pnl_usd: number;
  win_rate: number;
  win_count: number;
  loss_count: number;
  avg_trade_pnl: number;
  best_trade_pnl: number | null;
  worst_trade_pnl: number | null;
  avg_hold_time_hours: number | null;
  exit_reason_breakdown: Record<string, number>;
}

interface Bot {
  id: string;
  name: string;
  strategy: string;
  status: string;
  wallet_id: string;
}

export default function BotDetailPage() {
  const params = useParams();
  const router = useRouter();
  const botId = params.id as string;

  const [bot, setBot] = useState<Bot | null>(null);
  const [metrics, setMetrics] = useState<BotMetrics | null>(null);
  const [pnlData, setPnlData] = useState<EquityCurveDataPoint[]>([]);
  const [activityData, setActivityData] = useState<TradeActivityDataPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadData() {
      try {
        // Load bot info
        const bots = await api.getBots();
        const foundBot = bots.find((b) => b.id === botId);
        if (!foundBot) {
          setError('Bot not found');
          setLoading(false);
          return;
        }
        setBot(foundBot);

        // Load metrics and charts in parallel
        const [metricsData, pnlResponse, activityResponse] = await Promise.all([
          api.getBotMetrics(botId),
          api.getPnlTimeSeries({ botId, period: 'daily' }),
          api.getTradeActivity({ botId, period: 'daily', days: 30 }),
        ]);

        setMetrics(metricsData);
        setPnlData(pnlResponse.data);
        setActivityData(activityResponse.data);
      } catch (err) {
        console.error('Failed to load bot data:', err);
        setError('Failed to load bot data');
      } finally {
        setLoading(false);
      }
    }

    if (botId) {
      loadData();
    }
  }, [botId]);

  const handleToggleBot = async () => {
    if (!bot) return;
    try {
      if (bot.status === 'running') {
        await api.stopBot(bot.id);
        setBot({ ...bot, status: 'stopped' });
      } else {
        await api.startBot(bot.id);
        setBot({ ...bot, status: 'running' });
      }
    } catch (err) {
      console.error('Failed to toggle bot:', err);
    }
  };

  if (loading) {
    return <div className="flex items-center justify-center h-64">Loading...</div>;
  }

  if (error || !bot) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4">
        <p className="text-muted-foreground">{error || 'Bot not found'}</p>
        <Link
          href="/dashboard/bots"
          className="px-4 py-2 bg-primary text-primary-foreground rounded-md text-sm"
        >
          Back to Bots
        </Link>
      </div>
    );
  }

  const formatPnl = (value: number | null) => {
    if (value === null) return '-';
    const prefix = value >= 0 ? '+' : '';
    return `${prefix}$${value.toFixed(2)}`;
  };

  const formatHours = (hours: number | null) => {
    if (hours === null) return '-';
    if (hours < 1) return `${Math.round(hours * 60)}m`;
    if (hours < 24) return `${hours.toFixed(1)}h`;
    return `${(hours / 24).toFixed(1)}d`;
  };

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <Link
            href="/dashboard/bots"
            className="text-muted-foreground hover:text-foreground"
          >
            &larr; Bots
          </Link>
          <h1 className="text-2xl font-bold">{bot.name}</h1>
          <span
            className={cn(
              'px-2 py-1 rounded text-xs',
              bot.status === 'running'
                ? 'bg-green-100 text-green-800'
                : 'bg-gray-100 text-gray-800'
            )}
          >
            {bot.status}
          </span>
        </div>
        <button
          onClick={handleToggleBot}
          className={cn(
            'px-4 py-2 rounded-md text-sm',
            bot.status === 'running'
              ? 'bg-red-100 text-red-800 hover:bg-red-200'
              : 'bg-green-100 text-green-800 hover:bg-green-200'
          )}
        >
          {bot.status === 'running' ? 'Stop Bot' : 'Start Bot'}
        </button>
      </div>

      {/* Bot Info */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <div className="p-4 rounded-lg border bg-card">
          <p className="text-sm text-muted-foreground">Strategy</p>
          <p className="text-lg font-semibold capitalize">{bot.strategy}</p>
        </div>
        <div className="p-4 rounded-lg border bg-card">
          <p className="text-sm text-muted-foreground">Total Trades</p>
          <p className="text-lg font-semibold">{metrics?.total_trades ?? 0}</p>
        </div>
        <div className="p-4 rounded-lg border bg-card">
          <p className="text-sm text-muted-foreground">Total P&L</p>
          <p
            className={cn(
              'text-lg font-semibold',
              (metrics?.total_pnl_usd ?? 0) >= 0 ? 'text-green-600' : 'text-red-600'
            )}
          >
            {formatPnl(metrics?.total_pnl_usd ?? 0)}
          </p>
        </div>
      </div>

      {/* Metrics Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div className="p-4 rounded-lg border bg-card">
          <p className="text-sm text-muted-foreground">Win Rate</p>
          <p className="text-lg font-semibold">
            {((metrics?.win_rate ?? 0) * 100).toFixed(1)}%
          </p>
        </div>
        <div className="p-4 rounded-lg border bg-card">
          <p className="text-sm text-muted-foreground">Avg P&L</p>
          <p
            className={cn(
              'text-lg font-semibold',
              (metrics?.avg_trade_pnl ?? 0) >= 0 ? 'text-green-600' : 'text-red-600'
            )}
          >
            {formatPnl(metrics?.avg_trade_pnl ?? null)}
          </p>
        </div>
        <div className="p-4 rounded-lg border bg-card">
          <p className="text-sm text-muted-foreground">Best Trade</p>
          <p className="text-lg font-semibold text-green-600">
            {formatPnl(metrics?.best_trade_pnl ?? null)}
          </p>
        </div>
        <div className="p-4 rounded-lg border bg-card">
          <p className="text-sm text-muted-foreground">Worst Trade</p>
          <p className="text-lg font-semibold text-red-600">
            {formatPnl(metrics?.worst_trade_pnl ?? null)}
          </p>
        </div>
        <div className="p-4 rounded-lg border bg-card">
          <p className="text-sm text-muted-foreground">Open Trades</p>
          <p className="text-lg font-semibold">{metrics?.open_trades ?? 0}</p>
        </div>
        <div className="p-4 rounded-lg border bg-card">
          <p className="text-sm text-muted-foreground">Closed Trades</p>
          <p className="text-lg font-semibold">{metrics?.closed_trades ?? 0}</p>
        </div>
        <div className="p-4 rounded-lg border bg-card">
          <p className="text-sm text-muted-foreground">Avg Hold Time</p>
          <p className="text-lg font-semibold">
            {formatHours(metrics?.avg_hold_time_hours ?? null)}
          </p>
        </div>
        <div className="p-4 rounded-lg border bg-card">
          <p className="text-sm text-muted-foreground">Wins / Losses</p>
          <p className="text-lg font-semibold">
            <span className="text-green-600">{metrics?.win_count ?? 0}</span>
            {' / '}
            <span className="text-red-600">{metrics?.loss_count ?? 0}</span>
          </p>
        </div>
      </div>

      {/* Equity Curve */}
      <ChartContainer
        title="Performance"
        subtitle="Cumulative P&L for this bot"
        empty={pnlData.length === 0}
        emptyMessage="No closed trades yet"
        className="mb-6"
      >
        <EquityCurveChart data={pnlData} />
      </ChartContainer>

      {/* Win Rate & Activity */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
        <ChartContainer
          title="Win Rate"
          subtitle={`${metrics?.win_count ?? 0} wins, ${metrics?.loss_count ?? 0} losses`}
          empty={(metrics?.win_count ?? 0) + (metrics?.loss_count ?? 0) === 0}
          emptyMessage="No closed trades yet"
        >
          <WinRateChart
            wins={metrics?.win_count ?? 0}
            losses={metrics?.loss_count ?? 0}
            winRate={metrics?.win_rate ?? 0}
          />
        </ChartContainer>

        <ChartContainer
          title="Trade Activity"
          subtitle="Trades per day (last 30 days)"
          empty={activityData.every((d) => d.trade_count === 0)}
          emptyMessage="No trades in the last 30 days"
        >
          <TradeActivityChart data={activityData} />
        </ChartContainer>
      </div>

      {/* Exit Reasons */}
      {metrics?.exit_reason_breakdown &&
        Object.keys(metrics.exit_reason_breakdown).length > 0 && (
          <div className="p-6 rounded-lg border bg-card">
            <h3 className="font-semibold mb-4">Exit Reasons</h3>
            <div className="flex flex-wrap gap-4">
              {Object.entries(metrics.exit_reason_breakdown).map(([reason, count]) => (
                <div key={reason} className="flex items-center gap-2">
                  <span
                    className={cn(
                      'px-2 py-1 rounded text-xs',
                      reason === 'take_profit'
                        ? 'bg-green-100 text-green-800'
                        : reason === 'stop_loss'
                        ? 'bg-red-100 text-red-800'
                        : 'bg-gray-100 text-gray-800'
                    )}
                  >
                    {reason.replace('_', ' ')}
                  </span>
                  <span className="text-sm font-medium">{count}</span>
                </div>
              ))}
            </div>
          </div>
        )}
    </div>
  );
}
