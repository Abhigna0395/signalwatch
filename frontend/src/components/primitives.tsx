/**
 * Shared display primitives.
 *
 * These carry the product's visual grammar, so that a freshness dot or an
 * attention band looks and reads identically everywhere it appears. Anything
 * used on more than one screen belongs here rather than being re-styled inline.
 */

import clsx from 'clsx'
import {
  AlertTriangle,
  Activity,
  BarChart3,
  Bell,
  Database,
  LineChart,
  Newspaper,
  TrendingDown,
  TrendingUp,
  type LucideIcon,
} from 'lucide-react'
import type { Band, Category, Freshness, Severity } from '../lib/types'
import {
  BAND_META,
  CATEGORY_META,
  FRESHNESS_META,
  directionClass,
  formatPercent,
  scoreColor,
} from '../lib/format'

// ─────────────────────────────────────────────────────────────────────────────
// Attention band
// ─────────────────────────────────────────────────────────────────────────────

export function BandBadge({ band, className }: { band: Band; className?: string }) {
  const meta = BAND_META[band]
  return (
    <span
      className={clsx('chip', meta.bg, meta.border, meta.text, className)}
      // The colour alone must never be the only carrier of meaning.
      aria-label={`Attention level: ${meta.label}`}
    >
      <span className={clsx('h-1.5 w-1.5 rounded-full', meta.dot)} aria-hidden />
      {meta.label}
    </span>
  )
}

/**
 * The attention score, drawn as a ring.
 *
 * The ring is a progress indicator, not decoration: the arc length *is* the
 * score out of 100, so two stocks can be compared at a glance without reading
 * the number.
 */
export function ScoreRing({
  score,
  size = 56,
  showDelta,
  delta,
}: {
  score: number
  size?: number
  showDelta?: boolean
  delta?: number | null
}) {
  const stroke = size >= 48 ? 4 : 3
  const radius = (size - stroke) / 2
  const circumference = 2 * Math.PI * radius
  const offset = circumference * (1 - Math.max(0, Math.min(100, score)) / 100)
  const color = scoreColor(score)

  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90" role="img"
           aria-label={`Attention score ${Math.round(score)} out of 100`}>
        <circle
          cx={size / 2} cy={size / 2} r={radius}
          fill="none" stroke="rgba(148,163,184,0.14)" strokeWidth={stroke}
        />
        <circle
          cx={size / 2} cy={size / 2} r={radius}
          fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          className="animate-segment"
          style={{ ['--dash' as string]: `${circumference}` }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span
          className="tnum font-semibold leading-none"
          style={{ color, fontSize: size >= 56 ? '1.05rem' : '0.8rem' }}
        >
          {Math.round(score)}
        </span>
        {showDelta && delta !== null && delta !== undefined && Math.abs(delta) >= 1 && (
          <span className={clsx('tnum text-2xs leading-none', delta > 0 ? 'text-attention-high' : 'text-slate-500')}>
            {delta > 0 ? '+' : ''}
            {Math.round(delta)}
          </span>
        )}
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Data freshness — reused everywhere a number is shown
// ─────────────────────────────────────────────────────────────────────────────

export function FreshnessDot({
  freshness,
  showLabel = true,
  className,
}: {
  freshness: Freshness
  showLabel?: boolean
  className?: string
}) {
  const meta = FRESHNESS_META[freshness.status]
  const conflicted = freshness.verification === 'conflict'

  return (
    <span
      className={clsx('inline-flex items-center gap-1.5 text-2xs', meta.text, className)}
      title={`${meta.description} · source: ${freshness.source}${
        freshness.note ? ` · ${freshness.note}` : ''
      }`}
    >
      {conflicted ? (
        <AlertTriangle className="h-3 w-3" aria-hidden />
      ) : (
        <span
          className={clsx(
            'h-1.5 w-1.5 rounded-full',
            meta.dot,
            freshness.status === 'FRESH' && 'animate-pulse',
          )}
          aria-hidden
        />
      )}
      {showLabel && (
        <span>
          {freshness.status === 'FRESH' ? freshness.label : `${meta.label} · ${freshness.label}`}
        </span>
      )}
      <span className="sr-only">
        Data status: {meta.label}. {meta.description}.
        {conflicted && ' Sources disagree on this value.'}
      </span>
    </span>
  )
}

/** The louder, explicit banner used on the detail page for degraded data. */
export function StaleWarning({ freshness }: { freshness: Freshness }) {
  if (freshness.status === 'FRESH' || freshness.status === 'RECENT') {
    if (freshness.verification !== 'conflict') return null
  }

  const isConflict = freshness.verification === 'conflict'
  const d = freshness.discrepancy

  return (
    <div
      className={clsx(
        'flex items-start gap-2.5 rounded-lg border px-3 py-2.5 text-xs',
        isConflict
          ? 'border-attention-high/30 bg-attention-high/5 text-attention-high'
          : 'border-attention-high/25 bg-attention-high/5 text-attention-high',
      )}
      role="alert"
    >
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
      <div className="space-y-1">
        {isConflict && d ? (
          <>
            <p className="font-medium">Data discrepancy detected</p>
            <p className="text-slate-400">
              <span className="tnum">{d.source_a}</span> reports{' '}
              <span className="tnum text-slate-200">{d.value_a.toFixed(2)}</span>;{' '}
              <span className="tnum">{d.source_b}</span> reports{' '}
              <span className="tnum text-slate-200">{d.value_b.toFixed(2)}</span> — a{' '}
              <span className="tnum">{d.difference_percent.toFixed(2)}%</span> gap against a{' '}
              <span className="tnum">{d.tolerance_percent}%</span> tolerance. Showing{' '}
              {d.resolved_with}: {d.reason.toLowerCase()}.
            </p>
          </>
        ) : (
          <>
            <p className="font-medium">Data is delayed</p>
            <p className="text-slate-400">
              Last updated {freshness.label} from {freshness.source}. Signals below are computed
              from that snapshot.
            </p>
          </>
        )}
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Categories & severity
// ─────────────────────────────────────────────────────────────────────────────

export const CATEGORY_ICON: Record<Category, LucideIcon> = {
  PRICE: LineChart,
  VOLUME: BarChart3,
  TECHNICAL: Activity,
  NEWS: Newspaper,
  USER: Bell,
  DATA: Database,
}

export function CategoryChip({ category, label }: { category: Category; label?: string }) {
  const meta = CATEGORY_META[category]
  const Icon = CATEGORY_ICON[category]
  return (
    <span className={clsx('chip border-transparent', meta.bg, meta.text)}>
      <Icon className="h-3 w-3" aria-hidden />
      {label ?? meta.label}
    </span>
  )
}

const SEVERITY_BAR: Record<Severity, string> = {
  critical: 'bg-attention-high',
  high: 'bg-attention-high/70',
  medium: 'bg-attention-watch/70',
  info: 'bg-slate-600',
}

export function SeverityBar({ severity }: { severity: Severity }) {
  return (
    <span
      className={clsx('h-full w-0.5 shrink-0 rounded-full', SEVERITY_BAR[severity])}
      aria-hidden
    />
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Numbers
// ─────────────────────────────────────────────────────────────────────────────

export function ChangePill({ value, className }: { value: number | null; className?: string }) {
  const Icon = (value ?? 0) >= 0 ? TrendingUp : TrendingDown
  return (
    <span className={clsx('inline-flex items-center gap-1 tnum font-medium', directionClass(value), className)}>
      {value !== null && <Icon className="h-3.5 w-3.5" aria-hidden />}
      {formatPercent(value)}
    </span>
  )
}

export function Stat({
  label,
  value,
  hint,
  accent,
}: {
  label: string
  value: React.ReactNode
  hint?: React.ReactNode
  accent?: string
}) {
  return (
    <div className="min-w-0">
      <p className="eyebrow">{label}</p>
      <p className={clsx('mt-1 tnum text-sm font-semibold', accent ?? 'text-slate-100')}>{value}</p>
      {hint && <p className="mt-0.5 truncate text-2xs text-slate-500">{hint}</p>}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// States
// ─────────────────────────────────────────────────────────────────────────────

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx('skeleton', className)} />
}

export function EmptyState({
  icon: Icon = Activity,
  title,
  description,
  action,
}: {
  icon?: LucideIcon
  title: string
  description?: string
  action?: React.ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-12 text-center">
      <div className="rounded-full border border-line bg-ink-750 p-3">
        <Icon className="h-5 w-5 text-slate-500" aria-hidden />
      </div>
      <div className="space-y-1">
        <p className="text-sm font-medium text-slate-300">{title}</p>
        {description && <p className="max-w-sm text-xs text-slate-500">{description}</p>}
      </div>
      {action}
    </div>
  )
}

export function ErrorState({
  title = 'Something went wrong',
  message,
  onRetry,
}: {
  title?: string
  message: string
  onRetry?: () => void
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-12 text-center" role="alert">
      <div className="rounded-full border border-down/30 bg-down/10 p-3">
        <AlertTriangle className="h-5 w-5 text-down" aria-hidden />
      </div>
      <div className="space-y-1">
        <p className="text-sm font-medium text-slate-200">{title}</p>
        <p className="max-w-sm text-xs text-slate-500">{message}</p>
      </div>
      {onRetry && (
        <button onClick={onRetry} className="btn-ghost btn-sm">
          Try again
        </button>
      )}
    </div>
  )
}

export function SectionHeading({
  title,
  count,
  description,
  action,
}: {
  title: string
  count?: number
  description?: string
  action?: React.ReactNode
}) {
  return (
    <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
      <div>
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-label text-slate-300">
          {title}
          {count !== undefined && (
            <span className="tnum rounded-md bg-ink-700 px-1.5 py-0.5 text-2xs text-slate-400">
              {count}
            </span>
          )}
        </h2>
        {description && <p className="mt-1 text-xs text-slate-500">{description}</p>}
      </div>
      {action}
    </div>
  )
}

/** The persistent, unmissable "this is not real data" marker. */
export function DemoBadge({ compact }: { compact?: boolean }) {
  return (
    <span
      className="chip border-amber-400/30 bg-amber-400/10 text-amber-300"
      title="Deterministic seeded market data — no live provider is configured. Every number on screen is synthetic."
    >
      <Database className="h-3 w-3" aria-hidden />
      {compact ? 'DEMO' : 'DEMO DATA'}
    </span>
  )
}
