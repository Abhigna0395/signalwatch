/**
 * Centralised API client.
 *
 * Every network call in the app goes through `request()`. That gives one place
 * for the base URL, the demo-user header, timeouts, and — most importantly —
 * turning a failed response into a typed `ApiError` carrying the backend's
 * human-readable message, so the UI can show *what* went wrong rather than a
 * generic "something failed".
 */

import type {
  Dashboard,
  Health,
  History,
  ReplayState,
  StockDetail,
  SymbolMatch,
  Watchlist,
  ChangeCard,
} from './types'

const BASE = import.meta.env.VITE_API_BASE_URL ?? ''
const TIMEOUT_MS = 20_000

export class ApiError extends Error {
  status: number
  code?: string
  detail?: unknown

  constructor(message: string, status: number, code?: string, detail?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.detail = detail
  }

  /** Whether retrying unchanged could plausibly succeed. */
  get isRetryable() {
    return this.status === 0 || this.status === 429 || this.status >= 500
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS)

  try {
    const response = await fetch(`${BASE}/api${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        // The auth layer resolves the user from this header. Swapping in a real
        // token means changing this one line plus the backend resolver.
        'X-User-Email': 'demo@signalwatch.app',
        ...init.headers,
      },
    })

    if (!response.ok) {
      let message = `Request failed (${response.status})`
      let code: string | undefined
      let detail: unknown
      try {
        const body = await response.json()
        message = body.error ?? body.detail ?? message
        code = body.code
        detail = body.detail
      } catch {
        /* a non-JSON error body is not itself an error worth surfacing */
      }
      throw new ApiError(message, response.status, code, detail)
    }

    if (response.status === 204) return undefined as T
    return (await response.json()) as T
  } catch (error) {
    if (error instanceof ApiError) throw error
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiError('The request timed out. The server may be starting up.', 0, 'TIMEOUT')
    }
    throw new ApiError(
      'Cannot reach the SignalWatch API. Is the backend running on port 8000?',
      0,
      'NETWORK',
    )
  } finally {
    clearTimeout(timer)
  }
}

const post = <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

export const api = {
  health: () => request<Health>('/health'),
  config: () => request<Record<string, unknown>>('/config'),

  // ── Dashboard ────────────────────────────────────────────────────────────
  dashboard: (watchlistId?: number) =>
    request<Dashboard>(`/dashboard${watchlistId ? `?watchlist_id=${watchlistId}` : ''}`),
  changesSinceLastVisit: () =>
    request<{ count: number; changes: ChangeCard[]; last_reviewed_at: string | null; label: string }>(
      '/changes/since-last-visit',
    ),
  markReviewed: (symbols?: string[]) =>
    post<{ reviewed: number; reviewed_at: string; message: string }>('/changes/mark-reviewed', {
      symbols: symbols ?? null,
    }),

  // ── Watchlists ───────────────────────────────────────────────────────────
  watchlists: () => request<Watchlist[]>('/watchlists'),
  createWatchlist: (name: string) => post<Watchlist>('/watchlists', { name }),
  renameWatchlist: (id: number, name: string) =>
    request<Watchlist>(`/watchlists/${id}`, { method: 'PATCH', body: JSON.stringify({ name }) }),
  deleteWatchlist: (id: number) =>
    request<{ message: string }>(`/watchlists/${id}`, { method: 'DELETE' }),
  reorderWatchlists: (orderedIds: number[]) =>
    post<Watchlist[]>('/watchlists/reorder', { ordered_ids: orderedIds }),
  addStock: (watchlistId: number, symbol: string, thresholdPercent?: number | null) =>
    post<Watchlist>(`/watchlists/${watchlistId}/stocks`, {
      symbol,
      threshold_percent: thresholdPercent ?? null,
    }),
  removeStock: (watchlistId: number, symbol: string) =>
    request<Watchlist>(`/watchlists/${watchlistId}/stocks/${symbol}`, { method: 'DELETE' }),
  reorderItems: (watchlistId: number, orderedSymbols: string[]) =>
    post<Watchlist>(`/watchlists/${watchlistId}/reorder`, { ordered_symbols: orderedSymbols }),
  setThreshold: (watchlistId: number, symbol: string, thresholdPercent: number | null) =>
    request<Watchlist>(`/watchlists/${watchlistId}/stocks/${symbol}`, {
      method: 'PATCH',
      body: JSON.stringify({ threshold_percent: thresholdPercent }),
    }),
  createStarter: () => post<Watchlist>('/watchlists/starter'),

  // ── Stocks ───────────────────────────────────────────────────────────────
  search: (q: string) => request<SymbolMatch[]>(`/stocks/search?q=${encodeURIComponent(q)}`),
  stock: (symbol: string) => request<StockDetail>(`/stocks/${symbol}`),
  history: (symbol: string, range: string) =>
    request<History>(`/stocks/${symbol}/history?range=${range}`),
  news: (symbol: string) =>
    request<{ symbol: string; clusters: import('./types').NewsCluster[]; total: number; empty_message: string }>(
      `/stocks/${symbol}/news`,
    ),

  // ── Demo replay ──────────────────────────────────────────────────────────
  replay: () => request<ReplayState>('/demo/replay'),
  replayStep: (step?: number) =>
    post<ReplayState>('/demo/replay/step', step === undefined ? {} : { step }),
  replayReset: () => post<ReplayState>('/demo/replay/reset'),
}
