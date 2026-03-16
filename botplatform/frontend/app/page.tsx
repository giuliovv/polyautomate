import Link from 'next/link';

export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-24">
      <div className="max-w-3xl text-center">
        <h1 className="text-5xl font-bold tracking-tight mb-6">
          Polymarket Bot Platform
        </h1>
        <p className="text-xl text-muted-foreground mb-8">
          Create and manage trading bots for Polymarket without sharing your private keys.
          We handle the infrastructure, you control the strategy.
        </p>

        <div className="flex gap-4 justify-center mb-12">
          <Link
            href="/signup"
            className="inline-flex items-center justify-center rounded-md bg-primary px-8 py-3 text-sm font-medium text-primary-foreground shadow hover:bg-primary/90"
          >
            Get Started
          </Link>
          <Link
            href="/login"
            className="inline-flex items-center justify-center rounded-md border border-input bg-background px-8 py-3 text-sm font-medium shadow-sm hover:bg-accent hover:text-accent-foreground"
          >
            Sign In
          </Link>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 text-left">
          <div className="p-6 rounded-lg border bg-card">
            <h3 className="font-semibold mb-2">Secure Wallets</h3>
            <p className="text-sm text-muted-foreground">
              Platform-managed wallets with encrypted keys. Or connect your own wallet via delegation.
            </p>
          </div>
          <div className="p-6 rounded-lg border bg-card">
            <h3 className="font-semibold mb-2">Smart Strategies</h3>
            <p className="text-sm text-muted-foreground">
              Pre-built strategies like Longshot bias, or configure your own with custom parameters.
            </p>
          </div>
          <div className="p-6 rounded-lg border bg-card">
            <h3 className="font-semibold mb-2">Full Control</h3>
            <p className="text-sm text-muted-foreground">
              Set risk limits, monitor P&L in real-time, and stop bots instantly when needed.
            </p>
          </div>
        </div>
      </div>
    </main>
  );
}
