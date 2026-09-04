/** Shared response types. These mirror the FastAPI service layer's payloads. */

export type Band = 'HIGH_ATTENTION' | 'WATCH' | 'STABLE'
export type FreshnessStatus = 'FRESH' | 'RECENT' | 'STALE' | 'UNAVAILABLE'
export type Category = 'PRICE' | 'VOLUME' | 'TECHNICAL' | 'NEWS' | 'USER' | 'DATA'
export type Severity = 'critical' | 'high' | 'medium' | 'info'
export type Sentiment = 'positive' | 'neutral' | 'negative' | 'mixed'

export interface Quote {
  price: number | null
  previous_close: number | null
  change_absolute: number | null
  change_percent: number | null
  open: number | null
  day_high: number | null
  day_low: number | null
  volume: number | null
  avg_volume: number | null
  volume_ratio: number | null
  market_cap: number | null
  week52_high: number | null
  week52_low: number | null
  currency: string
}

export interface Discrepancy {
  field: string
  source_a: string
  value_a: number
  timestamp_a: string | null
  source_b: string
  value_b: number
  timestamp_b: string | null
  difference_percent: number
  tolerance_percent: number
  resolved_with: string
  reason: string
}

export interface Freshness {
  status: FreshnessStatus
  label: string
  source: string
  source_timestamp?: string | null
  age_seconds: number | null
  is_delayed: boolean
  note: string | null
  served_from: string
  degraded?: boolean
  degraded_reason?: string | null
  verification: 'verified' | 'conflict' | 'single_source' | 'unavailable'
  is_demo: boolean
  discrepancy?: Discrepancy | null
}

export interface SinceLastVisit {
  has_baseline: boolean
  price_change_percent: number | null
  price_from: number | null
  price_to: number | null
  score_from: number | null
  score_to: number | null
  score_delta: number | null
  band_from: Band | null
  band_to: Band | null
  new_signals: string[]
  resolved_signals: string[]
  persisting_signals: string[]
  escalated: boolean
  technical_changes: string[]
  news_delta: number
  last_reviewed_at: string | null
  is_meaningful: boolean
  headline: string
}

export interface ScoreComponent {
  key: string
  label: string
  points: number
  max_points: number
  intensity: number
  detail: string
  inputs: Record<string, unknown>
}

export interface Explanation {
  score: number
  band: Band
  confidence: number
  top_reason: string
  why_it_matters: string
  components: ScoreComponent[]
  weights: Record<string, number>
  reasons: string[]
}

export interface SignalEvent {
  type: string
  category: Category
  severity: Severity
  direction: 'up' | 'down' | 'neutral'
  title: string
  description: string
  metrics: Record<string, unknown>
  confidence: number
  fingerprint: string
  timestamp: string | null
}

export interface StockRow {
  symbol: string
  name: string
  exchange: string
  sector: string
  currency: string
  quote: Quote
  freshness: Freshness
  score: number
  band: Band
  top_reason: string
  confidence: number
  since_last_visit: SinceLastVisit
  event_count: number
  categories: Category[]
  error: string | null
  position?: number
  threshold_percent?: number | null
}

export interface ChangeCard extends StockRow {
  why_it_matters: string
  headline: string
  reasons: string[]
  new_signals: { fingerprint: string; title: string; category: Category; severity: Severity; direction: string }[]
  resolved_signals: string[]
  escalated: boolean
}

export interface NewsHeadline {
  id: number
  headline: string
  summary: string
  source: string
  url: string
  sentiment: Sentiment
  sentiment_confidence: number
  sentiment_provider: string
  published_at: string | null
  published_label: string
}

export interface NewsCluster {
  topic: string
  count: number
  sentiment: Sentiment
  sentiment_confidence: number
  latest_published_at: string | null
  latest_label: string
  headlines: NewsHeadline[]
}

export interface TimelineEntry {
  id: number
  bucket: string
  type: string
  category: Category
  severity: Severity
  direction: 'up' | 'down' | 'neutral'
  title: string
  description: string
  metrics: Record<string, unknown>
  confidence: number
  timestamp: string | null
  clock: string
}

export interface StockDetail extends StockRow {
  why_it_matters: string
  explanation: Explanation
  events: SignalEvent[]
  news: NewsCluster[]
  timeline: TimelineEntry[]
  technical: {
    sma20: number | null
    sma50: number | null
    rsi14: number | null
    rsi_zone: string
    volatility_20d: number | null
    volatility_baseline: number | null
    volatility_ratio: number | null
    resistance60: number | null
    support60: number | null
    move_zscore: number | null
  }
}

export interface MarketSession {
  exchange: string
  state: 'OPEN' | 'CLOSED' | 'PRE_MARKET' | 'AFTER_HOURS'
  is_open: boolean
  detail: string
  local_time: string
}

export interface DataQuality {
  status: 'HEALTHY' | 'PARTIAL' | 'DEGRADED'
  is_demo: boolean
  provider: string
  fallback_reason: string | null
  freshness_counts: Record<FreshnessStatus, number>
  conflicts: (Discrepancy & { symbol: string })[]
  delayed: { symbol: string; label: string; age_seconds: number | null }[]
  missing: string[]
  sources: {
    name: string
    kind: string
    is_primary: boolean
    status: string
    success_count: number
    error_count: number
    last_success_at: string | null
    last_error_at: string | null
    last_error: string | null
  }[]
  tolerance_percent: number
}

export interface WatchlistSummary {
  id: number
  name: string
  position: number
  selected: boolean
  count: number
  items: StockRow[]
  high_attention: number
  changed: number
  average_score: number
}

export interface Dashboard {
  greeting: string
  generated_at: string
  last_visit: { last_reviewed_at: string | null; label: string; has_reviewed: boolean }
  market_status: {
    primary: MarketSession
    sessions: MarketSession[]
    indices: { name: string; change_percent: number; is_proxy: boolean }[]
    is_demo: boolean
    provider: string
    replay_step: number | null
  }
  summary: {
    tracked: number
    meaningful_changes: number
    high_attention: number
    watch: number
    stable: number
    headline: string
  }
  since_last_visit: { count: number; changes: ChangeCard[]; empty_message: string }
  attention_queue: StockRow[]
  stable_stocks: StockRow[]
  unavailable: StockRow[]
  watchlists: WatchlistSummary[]
  recent_events: {
    id: number
    symbol: string
    type: string
    category: Category
    severity: Severity
    direction: string
    title: string
    timestamp: string
    label: string
  }[]
  data_quality: DataQuality
  onboarding?: {
    is_first_run: boolean
    title: string
    description: string
    suggested: string[]
  }
  config: {
    thresholds: { high_attention: number; watch: number }
    weights: Record<string, number>
  }
}

export interface Watchlist {
  id: number
  name: string
  position: number
  created_at: string
  items: {
    id: number
    position: number
    threshold_percent: number | null
    stock: { id: number; symbol: string; name: string; exchange: string; sector: string; currency: string }
  }[]
}

export interface SymbolMatch {
  symbol: string
  name: string
  exchange: string
  currency: string
}

export interface HistoryPoint {
  date: string
  close: number
  open: number
  high: number
  low: number
  volume: number
  sma20: number | null
  sma50: number | null
}

export interface History {
  symbol: string
  range: string
  points: HistoryPoint[]
  source: string
  days: number
}

export interface ReplayFrame {
  step: number
  clock: string
  caption: string
  symbol: string
  change_percent: number
  volume_ratio: number
  news_count: number
}

export interface ReplayState {
  available: boolean
  current_step: number
  steps: ReplayFrame[]
  frame?: ReplayFrame | null
  is_final?: boolean
  message?: string
}

export interface Health {
  status: string
  time: string
  database: string
  demo_mode: boolean
  provider: string
  provider_is_demo: boolean
  fallback_reason: string | null
  replay_step: number | null
  sources: { name: string; status: string; success: number; errors: number }[]
}
