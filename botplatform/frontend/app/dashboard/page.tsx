'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';

interface Summary {
  total_trades: number;
  total_pnl_usd: number;
  win_rate: number;
}

export default function DashboardPage() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [walletCount, setWalletCount] = useState(0);
  const [botCount, setBotCount] = useState(0);
  const [loading, setLoading] = useState(true);

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
    loadData();
  }, []);

  if (loading) {
    return <div>Loading...</div>;
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Dashboard</h1>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
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

function cn(...classes: (string | boolean | undefined)[]) {
  return classes.filter(Boolean).join(' ');
}
