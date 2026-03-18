'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { cn } from '@/lib/utils';
import { AuthProvider } from '@/components/auth-provider';

const navItems = [
  { href: '/dashboard', label: 'Overview' },
  { href: '/dashboard/wallets', label: 'Wallets' },
  { href: '/dashboard/bots', label: 'Bots' },
  { href: '/dashboard/trades', label: 'Trades' },
  { href: '/dashboard/backtest', label: 'Backtest' },
];

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();

  return (
    <AuthProvider>
      <div className="min-h-screen flex">
        {/* Sidebar */}
        <aside className="w-64 border-r bg-card">
          <div className="p-6">
            <Link href="/" className="font-bold text-lg">
              Bot Platform
            </Link>
          </div>
          <nav className="px-3">
            {navItems.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  'block px-3 py-2 rounded-md text-sm mb-1',
                  pathname === item.href ||
                    (item.href !== '/dashboard' && pathname.startsWith(item.href))
                    ? 'bg-primary text-primary-foreground'
                    : 'hover:bg-accent'
                )}
              >
                {item.label}
              </Link>
            ))}
          </nav>
        </aside>

        {/* Main content */}
        <main className="flex-1 p-8">{children}</main>
      </div>
    </AuthProvider>
  );
}
