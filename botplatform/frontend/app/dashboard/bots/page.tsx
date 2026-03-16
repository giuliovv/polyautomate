'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';

interface Bot {
  id: string;
  name: string;
  strategy: string;
  status: string;
  wallet_id: string;
}

interface Wallet {
  id: string;
  name: string;
}

export default function BotsPage() {
  const [bots, setBots] = useState<Bot[]>([]);
  const [wallets, setWallets] = useState<Wallet[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [creating, setCreating] = useState(false);
  const [formData, setFormData] = useState({
    name: '',
    wallet_id: '',
    strategy: 'longshot',
  });

  useEffect(() => {
    loadData();
  }, []);

  async function loadData() {
    try {
      const [botsData, walletsData] = await Promise.all([
        api.getBots(),
        api.getWallets(),
      ]);
      setBots(botsData);
      setWallets(walletsData);
      if (walletsData.length > 0 && !formData.wallet_id) {
        setFormData((prev) => ({ ...prev, wallet_id: walletsData[0].id }));
      }
    } catch (error) {
      console.error('Failed to load data:', error);
    } finally {
      setLoading(false);
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!formData.name || !formData.wallet_id) return;

    setCreating(true);
    try {
      await api.createBot(formData);
      setFormData({ name: '', wallet_id: wallets[0]?.id || '', strategy: 'longshot' });
      setShowForm(false);
      loadData();
    } catch (error) {
      console.error('Failed to create bot:', error);
    } finally {
      setCreating(false);
    }
  }

  async function handleToggle(bot: Bot) {
    try {
      if (bot.status === 'running') {
        await api.stopBot(bot.id);
      } else {
        await api.startBot(bot.id);
      }
      loadData();
    } catch (error) {
      console.error('Failed to toggle bot:', error);
    }
  }

  if (loading) {
    return <div>Loading...</div>;
  }

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold">Bots</h1>
        <button
          onClick={() => setShowForm(!showForm)}
          disabled={wallets.length === 0}
          className="px-4 py-2 bg-primary text-primary-foreground rounded-md text-sm disabled:opacity-50"
        >
          Create Bot
        </button>
      </div>

      {wallets.length === 0 && (
        <div className="mb-6 p-4 bg-yellow-50 border border-yellow-200 rounded-lg text-yellow-800">
          You need to create a wallet before you can create a bot.
        </div>
      )}

      {showForm && (
        <form onSubmit={handleCreate} className="mb-6 p-4 border rounded-lg bg-card">
          <div className="grid gap-4">
            <div>
              <label className="block text-sm font-medium mb-1">Bot Name</label>
              <input
                type="text"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                placeholder="My Longshot Bot"
                className="w-full px-3 py-2 border rounded-md"
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Wallet</label>
              <select
                value={formData.wallet_id}
                onChange={(e) => setFormData({ ...formData, wallet_id: e.target.value })}
                className="w-full px-3 py-2 border rounded-md"
              >
                {wallets.map((wallet) => (
                  <option key={wallet.id} value={wallet.id}>
                    {wallet.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Strategy</label>
              <select
                value={formData.strategy}
                onChange={(e) => setFormData({ ...formData, strategy: e.target.value })}
                className="w-full px-3 py-2 border rounded-md"
              >
                <option value="longshot">Longshot</option>
              </select>
            </div>
            <button
              type="submit"
              disabled={creating}
              className="px-4 py-2 bg-primary text-primary-foreground rounded-md disabled:opacity-50"
            >
              {creating ? 'Creating...' : 'Create Bot'}
            </button>
          </div>
        </form>
      )}

      {bots.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground">
          No bots yet. Create one to start trading.
        </div>
      ) : (
        <div className="grid gap-4">
          {bots.map((bot) => (
            <div key={bot.id} className="p-4 border rounded-lg bg-card">
              <div className="flex justify-between items-center">
                <div>
                  <h3 className="font-semibold">{bot.name}</h3>
                  <p className="text-sm text-muted-foreground">
                    Strategy: {bot.strategy}
                  </p>
                </div>
                <div className="flex gap-2 items-center">
                  <span
                    className={`text-xs px-2 py-1 rounded ${
                      bot.status === 'running'
                        ? 'bg-green-100 text-green-800'
                        : 'bg-gray-100 text-gray-800'
                    }`}
                  >
                    {bot.status}
                  </span>
                  <button
                    onClick={() => handleToggle(bot)}
                    className={`px-3 py-1 rounded text-sm ${
                      bot.status === 'running'
                        ? 'bg-red-100 text-red-800 hover:bg-red-200'
                        : 'bg-green-100 text-green-800 hover:bg-green-200'
                    }`}
                  >
                    {bot.status === 'running' ? 'Stop' : 'Start'}
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
