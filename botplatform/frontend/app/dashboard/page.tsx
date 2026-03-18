'use client';

import { useEffect, useState } from 'react';
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

interface Summary {
  total_trades: number;
  open_trades: number;
  closed_trades: number;
  total_pnl_usd: number;
  win_count: number;
  loss_count: number;
  win_rate: number;
}

export default function DashboardPage() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [walletCount, setWalletCount] = useState(0);
  const [botCount, setBotCount] = useState(0);
  const [pnlData, setPnlData] = useState<EquityCurveDataPoint[]>([]);
  const [activityData, setActivityData] = useState<TradeActivityDataPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [chartsLoading, setChartsLoading] = useState(true);

  useEffect(() => {
    async function loadData() {
      try {
        const [summaryData, wallets, bots] = await Promise.all([
          api.getTradeSummary(),
          api.getWallets(),
          api.getBots(),
        ]);
        setSummary(summaryData);
        setWalletCount(wallets.length);
        setBotCount(bots.filter((b) => b.status === 'running').length);
      } catch (error) {
        console.error('Failed to load dashboard data:', error);
      } finally {
        setLoading(false);
      }
    }

    async function loadCharts() {
      try {
        const [pnlResponse, activityResponse] = await Promise.all([
          api.getPnlTimeSeries({ period: 'daily' }),
          api.getTradeActivity({ period: 'daily', days: 30 }),
        ]);
        setPnlData(pnlResponse.data);
        setActivityData(activityResponse.data);
      } catch (error) {
        console.error('Failed to load chart data:', error);
      } finally {
        setChartsLoading(false);
      }
    }

    loadData();
    loadCharts();
  }, []);

  if (loading) {
    return <div className="flex items-center justify-center h-64">Loading...</div>;
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Dashboard</h1>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <div className="p-6 rounded-lg border bg-card">
          <p className="text-sm text-muted-foreground">Wallets</p>
          <p className="text-3xl font-bold">{walletCount}</p>
        </div>
        <div className="p-6 rounded-lg border bg-card">
          <p className="text-sm text-muted-foreground">Active Bots</p>
          <p className="text-3xl font-bold">{botCount}</p>
        </div>
        <div className="p-6 rounded-lg border bg-card">
          <p className="text-sm text-muted-foreground">Total Trades</p>
          <p className="text-3xl font-bold">{summary?.total_trades ?? 0}</p>
        </div>
        <div className="p-6 rounded-lg border bg-card">
          <p className="text-sm text-muted-foreground">Total P&L</p>
          <p
            className={cn(
              'text-3xl font-bold',
              (summary?.total_pnl_usd ?? 0) >= 0 ? 'text-green-600' : 'text-red-600'
            )}
          >
            ${(Number(summary?.total_pnl_usd) || 0).toFixed(2)}
          </p>
        </div>
      </div>

      {/* Equity Curve */}
      <ChartContainer
        title="Portfolio Performance"
        subtitle="Cumulative P&L over time"
        loading={chartsLoading}
        empty={pnlData.length === 0}
        emptyMessage="No closed trades yet. Start a bot to see your performance."
        className="mb-6"
      >
        <EquityCurveChart data={pnlData} />
      </ChartContainer>

      {/* Win Rate & Trade Activity */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
        <ChartContainer
          title="Win Rate"
          subtitle={`${summary?.win_count ?? 0} wins, ${summary?.loss_count ?? 0} losses`}
          loading={loading}
          empty={(summary?.win_count ?? 0) + (summary?.loss_count ?? 0) === 0}
          emptyMessage="No closed trades yet"
        >
          <WinRateChart
            wins={summary?.win_count ?? 0}
            losses={summary?.loss_count ?? 0}
            winRate={summary?.win_rate ?? 0}
          />
        </ChartContainer>

        <ChartContainer
          title="Trade Activity"
          subtitle="Trades per day (last 30 days)"
          loading={chartsLoading}
          empty={activityData.every((d) => d.trade_count === 0)}
          emptyMessage="No trades in the last 30 days"
        >
          <TradeActivityChart data={activityData} />
        </ChartContainer>
      </div>

      {/* Quick Actions */}
      <div className="p-6 rounded-lg border bg-card">
        <h2 className="font-semibold mb-4">Quick Actions</h2>
        <div className="flex gap-4">
          <a
            href="/dashboard/wallets"
            className="px-4 py-2 bg-primary text-primary-foreground rounded-md text-sm"
          >
            Create Wallet
          </a>
          <a
            href="/dashboard/bots"
            className="px-4 py-2 bg-secondary text-secondary-foreground rounded-md text-sm"
          >
            Create Bot
          </a>
        </div>
      </div>
    </div>
  );
}
