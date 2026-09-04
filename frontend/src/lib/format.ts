/** Presentation helpers. Pure, dependency-free, tested by eye across the app. */

import type { Band, Category, FreshnessStatus, Sentiment } from './types'

const CURRENCY_SYMBOL: Record<string, string> = {
  USD: '$',
  INR: '₹',
  EUR: '€',
  GBP: '£',
  JPY: '¥',
}

export function currencySymbol(code: string | undefined) {
  return CURRENCY_SYMBOL[code ?? 'USD'] ?? `${code} `
}

export function formatPrice(value: number | null | undefined, currency = 'USD') {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${currencySymbol(currency)}${value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

export function formatPercent(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}%`
}

export function formatSigned(value: number | null | undefined, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}`
}

/** Compact volume/market-cap: 2.4B, 214M, 47.2K. */
export function formatCompact(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  const abs = Math.abs(value)
  if (abs >= 1e12) return `${(value / 1e12).toFixed(2)}T`
  if (abs >= 1e9) return `${(value / 1e9).toFixed(2)}B`
  if (abs >= 1e6) return `${(value / 1e6).toFixed(1)}M`
  if (abs >= 1e3) return `${(value / 1e3).toFixed(1)}K`
  return value.toFixed(0)
}

export function formatMultiple(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${value.toFixed(2)}×`
}

/** Direction of money. The *only* thing allowed to select green vs red. */
export function directionClass(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return 'text-slate-400'
  if (value > 0) return 'text-up'
  if (value < 0) return 'text-down'
  return 'text-slate-400'
}

export const BAND_META: Record<Band, { label: string; text: string; bg: string; border: string; dot: string }> = {
  HIGH_ATTENTION: {
    label: 'High attention',
    text: 'text-attention-high',
    bg: 'bg-attention-high/10',
    border: 'border-attention-high/30',
    dot: 'bg-attention-high',
  },
  WATCH: {
    label: 'Watch',
    text: 'text-attention-watch',
    bg: 'bg-attention-watch/10',
    border: 'border-attention-watch/30',
    dot: 'bg-attention-watch',
  },
  STABLE: {
    label: 'Stable',
    text: 'text-attention-stable',
    bg: 'bg-attention-stable/10',
    border: 'border-attention-stable/25',
    dot: 'bg-attention-stable',
  },
}

export const FRESHNESS_META: Record<
  FreshnessStatus,
  { label: string; text: string; dot: string; description: string }
> = {
  FRESH: { label: 'Fresh', text: 'text-up', dot: 'bg-up', description: 'Updated moments ago' },
  RECENT: { label: 'Recent', text: 'text-slate-400', dot: 'bg-slate-400', description: 'Updated within the last few minutes' },
  STALE: { label: 'Delayed', text: 'text-attention-high', dot: 'bg-attention-high', description: 'This data is behind the market' },
  UNAVAILABLE: { label: 'Unavailable', text: 'text-down', dot: 'bg-down', description: 'No recent data could be retrieved' },
}

export const CATEGORY_META: Record<Category, { label: string; text: string; bg: string }> = {
  PRICE: { label: 'Price', text: 'text-sky-300', bg: 'bg-sky-500/10' },
  VOLUME: { label: 'Volume', text: 'text-violet-300', bg: 'bg-violet-500/10' },
  TECHNICAL: { label: 'Technical', text: 'text-amber-300', bg: 'bg-amber-500/10' },
  NEWS: { label: 'News', text: 'text-teal-300', bg: 'bg-teal-500/10' },
  USER: { label: 'For you', text: 'text-fuchsia-300', bg: 'bg-fuchsia-500/10' },
  DATA: { label: 'Data', text: 'text-slate-400', bg: 'bg-slate-500/10' },
}

export const SENTIMENT_META: Record<Sentiment, { label: string; text: string; bg: string }> = {
  positive: { label: 'Positive', text: 'text-up', bg: 'bg-up/10' },
  negative: { label: 'Negative', text: 'text-down', bg: 'bg-down/10' },
  neutral: { label: 'Neutral', text: 'text-slate-400', bg: 'bg-slate-500/10' },
  mixed: { label: 'Mixed', text: 'text-slate-300', bg: 'bg-slate-500/10' },
}

export function scoreColor(score: number) {
  if (score >= 75) return '#FF9F45'
  if (score >= 45) return '#5EA8FF'
  return '#7A879C'
}

/** "3:42 PM" from an ISO string. */
export function clockTime(iso: string | null | undefined) {
  if (!iso) return '—'
  return new Date(iso).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

export function relativeTime(iso: string | null | undefined) {
  if (!iso) return 'unknown'
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (seconds < 60) return `${Math.floor(seconds)} sec ago`
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`
  if (seconds < 86400) {
    const h = Math.floor(seconds / 3600)
    return `${h} hr${h === 1 ? '' : 's'} ago`
  }
  const d = Math.floor(seconds / 86400)
  return `${d} day${d === 1 ? '' : 's'} ago`
}

/** Human label for an event type, used where the raw enum would leak through. */
export function humanizeEventType(type: string) {
  return type
    .split('_')
    .map((w) => w.charAt(0) + w.slice(1).toLowerCase())
    .join(' ')
}
