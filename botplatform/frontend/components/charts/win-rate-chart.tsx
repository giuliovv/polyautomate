'use client';

import { PieChart, Pie, Cell, ResponsiveContainer, Legend, Tooltip } from 'recharts';

interface WinRateChartProps {
  wins: number;
  losses: number;
  winRate: number;
}

export function WinRateChart({ wins, losses, winRate }: WinRateChartProps) {
  const data = [
    { name: 'Wins', value: wins, color: '#22c55e' },
    { name: 'Losses', value: losses, color: '#ef4444' },
  ];

  const total = wins + losses;

  if (total === 0) {
    return (
      <div className="h-full flex items-center justify-center">
        <p className="text-muted-foreground">No trades yet</p>
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height="100%">
      <PieChart>
        <Pie
          data={data}
          cx="50%"
          cy="50%"
          innerRadius={60}
          outerRadius={80}
          paddingAngle={2}
          dataKey="value"
        >
          {data.map((entry, index) => (
            <Cell key={`cell-${index}`} fill={entry.color} />
          ))}
        </Pie>
        <Tooltip
          formatter={(value: number, name: string) => [value, name]}
          contentStyle={{
            backgroundColor: 'hsl(var(--card))',
            border: '1px solid hsl(var(--border))',
            borderRadius: '6px',
          }}
        />
        <Legend
          verticalAlign="bottom"
          height={36}
          formatter={(value, entry) => {
            const item = data.find((d) => d.name === value);
            return (
              <span style={{ color: item?.color }}>
                {value}: {item?.value}
              </span>
            );
          }}
        />
        {/* Center text */}
        <text
          x="50%"
          y="50%"
          textAnchor="middle"
          dominantBaseline="middle"
          className="fill-foreground"
        >
          <tspan x="50%" dy="-0.5em" fontSize="24" fontWeight="bold">
            {(winRate * 100).toFixed(0)}%
          </tspan>
          <tspan x="50%" dy="1.5em" fontSize="12" fill="#9ca3af">
            Win Rate
          </tspan>
        </text>
      </PieChart>
    </ResponsiveContainer>
  );
}
