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
      open_trades: number;
      closed_trades: number;
      total_pnl_usd: number;
      win_count: number;
      loss_count: number;
      win_rate: number;
    }>('/trades/summary');
  }

  // Analytics
  async getPnlTimeSeries(params: {
    botId?: string;
    period?: 'daily' | 'weekly';
    startDate?: string;
    endDate?: string;
  } = {}) {
    const query = new URLSearchParams();
    if (params.botId) query.set('bot_id', params.botId);
    if (params.period) query.set('period', params.period);
    if (params.startDate) query.set('start_date', params.startDate);
    if (params.endDate) query.set('end_date', params.endDate);
    const queryStr = query.toString();
    return this.request<{
      data: Array<{
        date: string;
        pnl: number;
        cumulative_pnl: number;
        trade_count: number;
      }>;
      period: string;
      total_pnl: number;
    }>(`/analytics/pnl-timeseries${queryStr ? `?${queryStr}` : ''}`);
  }

  async getTradeActivity(params: {
    botId?: string;
    period?: 'daily' | 'weekly';
    days?: number;
  } = {}) {
    const query = new URLSearchParams();
    if (params.botId) query.set('bot_id', params.botId);
    if (params.period) query.set('period', params.period);
    if (params.days) query.set('days', params.days.toString());
    const queryStr = query.toString();
    return this.request<{
      data: Array<{
        date: string;
        trade_count: number;
      }>;
      period: string;
    }>(`/analytics/trade-activity${queryStr ? `?${queryStr}` : ''}`);
  }

  async getBotMetrics(botId: string) {
    return this.request<{
      bot_id: string;
      bot_name: string;
      total_trades: number;
      open_trades: number;
      closed_trades: number;
      total_pnl_usd: number;
      win_rate: number;
      win_count: number;
      loss_count: number;
      avg_trade_pnl: number;
      best_trade_pnl: number | null;
      worst_trade_pnl: number | null;
      avg_hold_time_hours: number | null;
      exit_reason_breakdown: Record<string, number>;
    }>(`/analytics/bots/${botId}/metrics`);
  }

  // Backtest
  async getBacktestStrategies() {
    return this.request<Array<{
      id: string;
      name: string;
      description: string;
    }>>('/backtest/strategies');
  }

  async runBacktest(request: {
    strategy: string;
    market_id: string;
    token_label?: string;
    start_date: string;
    end_date: string;
    resolution?: string;
    stop_loss?: number;
    take_profit?: number;
    hold_periods?: number;
    position_size?: number;
    strategy_params?: Record<string, unknown>;
  }) {
    return this.request<{
      backtest_id: string;
      status: string;
    }>('/backtest/run', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  }

  async getBacktestResult(backtestId: string) {
    return this.request<{
      backtest_id: string;
      status: string;
      strategy_name: string;
      market_id: string;
      token_label: string;
      resolution: string;
      n_trades: number | null;
      win_rate: number | null;
      win_rate_ci_low: number | null;
      win_rate_ci_high: number | null;
      total_pnl: number | null;
      avg_pnl: number | null;
      max_drawdown: number | null;
      sharpe_ratio: number | null;
      exit_reason_breakdown: Record<string, number> | null;
      trades: Array<{
        entry_timestamp: string;
        exit_timestamp: string | null;
        direction: string;
        entry_price: number;
        exit_price: number | null;
        pnl: number | null;
        exit_reason: string | null;
      }> | null;
      equity_curve: Array<{
        timestamp: string;
        cumulative_pnl: number;
      }> | null;
      error_message: string | null;
      created_at: string | null;
      completed_at: string | null;
    }>(`/backtest/${backtestId}`);
  }

  async listBacktests() {
    return this.request<Array<{
      backtest_id: string;
      status: string;
      strategy_name: string;
      market_id: string;
      token_label: string;
      resolution: string;
      n_trades: number | null;
      win_rate: number | null;
      total_pnl: number | null;
      created_at: string | null;
      completed_at: string | null;
      error_message: string | null;
    }>>('/backtest');
  }
}

export const api = new ApiClient();
