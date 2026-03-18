'use client';

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Area,
  AreaChart,
} from 'recharts';

export interface EquityCurveDataPoint {
  date: string;
  pnl: number;
  cumulative_pnl: number;
  trade_count: number;
}

interface EquityCurveChartProps {
  data: EquityCurveDataPoint[];
  showGrid?: boolean;
  height?: number;
}

export function EquityCurveChart({
  data,
  showGrid = true,
  height = 256,
}: EquityCurveChartProps) {
  const lastValue = data.length > 0 ? data[data.length - 1].cumulative_pnl : 0;
  const isPositive = lastValue >= 0;
  const strokeColor = isPositive ? '#22c55e' : '#ef4444';
  const fillColor = isPositive ? '#22c55e20' : '#ef444420';

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  };

  const formatPnl = (value: number) => {
    const prefix = value >= 0 ? '+' : '';
    return `${prefix}$${value.toFixed(2)}`;
  };

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
        {showGrid && <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />}
        <XAxis
          dataKey="date"
          tickFormatter={formatDate}
          tick={{ fontSize: 12 }}
          stroke="#9ca3af"
        />
        <YAxis
          tickFormatter={formatPnl}
          tick={{ fontSize: 12 }}
          stroke="#9ca3af"
          width={80}
        />
        <Tooltip
          formatter={(value: number) => [formatPnl(value), 'P&L']}
          labelFormatter={formatDate}
          contentStyle={{
            backgroundColor: 'hsl(var(--card))',
            border: '1px solid hsl(var(--border))',
            borderRadius: '6px',
          }}
        />
        <defs>
          <linearGradient id="colorPnl" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={strokeColor} stopOpacity={0.3} />
            <stop offset="95%" stopColor={strokeColor} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area
          type="monotone"
          dataKey="cumulative_pnl"
          stroke={strokeColor}
          strokeWidth={2}
          fill="url(#colorPnl)"
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
