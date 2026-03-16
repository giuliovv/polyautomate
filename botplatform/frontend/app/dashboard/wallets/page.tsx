'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';

interface Wallet {
  id: string;
  name: string;
  address: string;
  wallet_type: string;
  status: string;
}

export default function WalletsPage() {
  const [wallets, setWallets] = useState<Wallet[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [newWalletName, setNewWalletName] = useState('');
  const [showForm, setShowForm] = useState(false);

  useEffect(() => {
    loadWallets();
  }, []);

  async function loadWallets() {
    try {
      const data = await api.getWallets();
      setWallets(data);
    } catch (error) {
      console.error('Failed to load wallets:', error);
    } finally {
      setLoading(false);
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!newWalletName.trim()) return;

    setCreating(true);
    try {
      await api.createWallet(newWalletName);
      setNewWalletName('');
      setShowForm(false);
      loadWallets();
    } catch (error) {
      console.error('Failed to create wallet:', error);
    } finally {
      setCreating(false);
    }
  }

  if (loading) {
    return <div>Loading...</div>;
  }

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold">Wallets</h1>
        <button
          onClick={() => setShowForm(!showForm)}
          className="px-4 py-2 bg-primary text-primary-foreground rounded-md text-sm"
        >
          Create Wallet
        </button>
      </div>

      {showForm && (
        <form onSubmit={handleCreate} className="mb-6 p-4 border rounded-lg bg-card">
          <div className="flex gap-4 items-end">
            <div className="flex-1">
              <label className="block text-sm font-medium mb-1">Wallet Name</label>
              <input
                type="text"
                value={newWalletName}
                onChange={(e) => setNewWalletName(e.target.value)}
                placeholder="My Trading Wallet"
                className="w-full px-3 py-2 border rounded-md"
              />
            </div>
            <button
              type="submit"
              disabled={creating}
              className="px-4 py-2 bg-primary text-primary-foreground rounded-md disabled:opacity-50"
            >
              {creating ? 'Creating...' : 'Create'}
            </button>
          </div>
        </form>
      )}

      {wallets.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground">
          No wallets yet. Create one to get started.
        </div>
      ) : (
        <div className="grid gap-4">
          {wallets.map((wallet) => (
            <div key={wallet.id} className="p-4 border rounded-lg bg-card">
              <div className="flex justify-between items-start">
                <div>
                  <h3 className="font-semibold">{wallet.name}</h3>
                  <p className="text-sm text-muted-foreground font-mono">
                    {wallet.address}
                  </p>
                </div>
                <div className="flex gap-2">
                  <span
                    className={`text-xs px-2 py-1 rounded ${
                      wallet.wallet_type === 'platform_managed'
                        ? 'bg-blue-100 text-blue-800'
                        : 'bg-purple-100 text-purple-800'
                    }`}
                  >
                    {wallet.wallet_type === 'platform_managed' ? 'Platform' : 'Delegated'}
                  </span>
                  <span
                    className={`text-xs px-2 py-1 rounded ${
                      wallet.status === 'active'
                        ? 'bg-green-100 text-green-800'
                        : 'bg-gray-100 text-gray-800'
                    }`}
                  >
                    {wallet.status}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
