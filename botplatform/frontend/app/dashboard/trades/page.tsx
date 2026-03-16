'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';

interface Trade {
  id: string;
  market_slug: string;
  side: string;
  entry_price: number;
  pnl_usd: number | null;
  status: string;
}

export default function TradesPage() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadTrades() {
      try {
        const data = await api.getTrades();
        setTrades(data);
      } catch (error) {
        console.error('Failed to load trades:', error);
      } finally {
        setLoading(false);
      }
    }
    loadTrades();
  }, []);

  if (loading) {
    return <div>Loading...</div>;
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Trades</h1>

      {trades.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground">
          No trades yet. Start a bot to begin trading.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr className="border-b">
                <th className="text-left p-3 text-sm font-medium">Market</th>
                <th className="text-left p-3 text-sm font-medium">Side</th>
                <th className="text-right p-3 text-sm font-medium">Entry Price</th>
                <th className="text-right p-3 text-sm font-medium">P&L</th>
                <th className="text-left p-3 text-sm font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((trade) => (
                <tr key={trade.id} className="border-b hover:bg-muted/50">
                  <td className="p-3 text-sm">{trade.market_slug}</td>
                  <td className="p-3 text-sm">
                    <span
                      className={`px-2 py-1 rounded text-xs ${
                        trade.side === 'buy'
                          ? 'bg-green-100 text-green-800'
                          : 'bg-red-100 text-red-800'
                      }`}
                    >
                      {trade.side.toUpperCase()}
                    </span>
                  </td>
                  <td className="p-3 text-sm text-right">
                    ${trade.entry_price.toFixed(4)}
                  </td>
                  <td
                    className={`p-3 text-sm text-right font-medium ${
                      trade.pnl_usd === null
                        ? ''
                        : trade.pnl_usd >= 0
                        ? 'text-green-600'
                        : 'text-red-600'
                    }`}
                  >
                    {trade.pnl_usd !== null ? `$${trade.pnl_usd.toFixed(2)}` : '-'}
                  </td>
                  <td className="p-3 text-sm">
                    <span
                      className={`px-2 py-1 rounded text-xs ${
                        trade.status === 'open'
                          ? 'bg-blue-100 text-blue-800'
                          : 'bg-gray-100 text-gray-800'
                      }`}
                    >
                      {trade.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
