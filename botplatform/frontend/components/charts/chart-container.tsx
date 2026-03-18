'use client';

import { cn } from '@/lib/utils';

interface ChartContainerProps {
  title: string;
  subtitle?: string;
  loading?: boolean;
  empty?: boolean;
  emptyMessage?: string;
  className?: string;
  children: React.ReactNode;
}

export function ChartContainer({
  title,
  subtitle,
  loading = false,
  empty = false,
  emptyMessage = 'No data available',
  className,
  children,
}: ChartContainerProps) {
  return (
    <div className={cn('p-6 rounded-lg border bg-card', className)}>
      <div className="mb-4">
        <h3 className="font-semibold text-lg">{title}</h3>
        {subtitle && (
          <p className="text-sm text-muted-foreground">{subtitle}</p>
        )}
      </div>

      {loading ? (
        <div className="h-64 flex items-center justify-center">
          <div className="animate-pulse flex flex-col items-center gap-2">
            <div className="h-32 w-full bg-muted rounded" />
            <div className="h-4 w-24 bg-muted rounded" />
          </div>
        </div>
      ) : empty ? (
        <div className="h-64 flex items-center justify-center">
          <p className="text-muted-foreground">{emptyMessage}</p>
        </div>
      ) : (
        <div className="h-64">{children}</div>
      )}
    </div>
  );
}
