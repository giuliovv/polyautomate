import { getAccessToken } from './auth';

const API_BASE = `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/v1`;

interface ApiError {
  detail: string;
}

class ApiClient {
  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const headers: HeadersInit = {
      'Content-Type': 'application/json',
      ...options.headers,
    };

    // Get Cognito access token
    const token = await getAccessToken();
    if (token) {
      (headers as Record<string, string>)['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(`${API_BASE}${endpoint}`, {
      ...options,
      headers,
    });

    if (!response.ok) {
      if (response.status === 401) {
        // Token expired or invalid - redirect to login
        if (typeof window !== 'undefined') {
          window.location.href = '/login';
        }
        throw new Error('Unauthorized');
      }
      const error: ApiError = await response.json();
      throw new Error(error.detail || 'An error occurred');
    }

    if (response.status === 204) {
      return {} as T;
    }

    return response.json();
  }

  // Auth - just session validation now (auth is handled by Cognito)
  async getSession() {
    return this.request<{ user_id: string; email: string }>('/auth/session');
  }

  // Wallets
  async getWallets() {
    return this.request<Array<{
      id: string;
      name: string;
      address: string;
      wallet_type: string;
      status: string;
    }>>('/wallets');
  }

  async createWallet(name: string) {
    return this.request<{ id: string; name: string; address: string }>('/wallets', {
      method: 'POST',
      body: JSON.stringify({ name }),
    });
  }

  // Bots
  async getBots() {
    return this.request<Array<{
      id: string;
      name: string;
      strategy: string;
      status: string;
      wallet_id: string;
    }>>('/bots');
  }

  async createBot(data: {
    wallet_id: string;
    name: string;
    strategy: string;
    config?: Record<string, unknown>;
  }) {
    return this.request<{ id: string }>('/bots', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async startBot(botId: string) {
    return this.request(`/bots/${botId}/start`, { method: 'POST' });
  }

  async stopBot(botId: string) {
    return this.request(`/bots/${botId}/stop`, { method: 'POST' });
  }

  // Trades
  async getTrades() {
    return this.request<Array<{
      id: string;
      market_slug: string;
      side: string;
      entry_price: number;
      pnl_usd: number | null;
      status: string;
    }>>('/trades');
  }

  async getTradeSummary() {
    return this.request<{
      total_trades: number;
      total_pnl_usd: number;
      win_rate: number;
    }>('/trades/summary');
  }
}

export const api = new ApiClient();
