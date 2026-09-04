/**
 * Data quality, stated plainly.
 *
 * The brief asks how the system handles stale, delayed and conflicting data.
 * The answer is that it never hides any of it: this panel reports the freshness
 * distribution, every source's health, and — crucially — both sides of any
 * disagreement between providers, rather than silently picking a winner.
 */

import clsx from 'clsx'
import { Link } from 'react-router-dom'
import { AlertTriangle, CheckCircle2, Clock, Database } from 'lucide-react'
import type { DataQuality } from '../lib/types'

const STATUS_META = {
  HEALTHY: { label: 'All sources healthy', icon: CheckCircle2, text: 'text-up', border: 'border-up/25' },
  PARTIAL: { label: 'Some data is delayed or disputed', icon: Clock, text: 'text-attention-high', border: 'border-attention-high/25' },
  DEGRADED: { label: 'Data is degraded', icon: AlertTriangle, text: 'text-down', border: 'border-down/25' },
} as const

export function DataQualityPanel({ quality }: { quality: DataQuality }) {
  const meta = STATUS_META[quality.status]
  const Icon = meta.icon
  const counts = quality.freshness_counts

  return (
    <div className={clsx('card p-4', meta.border)}>
      <div className="flex items-center gap-2">
        <Icon className={clsx('h-4 w-4 shrink-0', meta.text)} aria-hidden />
        <h2 className="text-sm font-semibold text-slate-200">Data quality</h2>
        <span className={clsx('ml-auto text-2xs font-medium', meta.text)}>{meta.label}</span>
      </div>

      {/* Freshness distribution */}
      <dl className="mt-3 grid grid-cols-4 gap-2">
        {(['FRESH', 'RECENT', 'STALE', 'UNAVAILABLE'] as const).map((key) => (
          <div key={key} className="rounded-lg border border-line bg-ink-850 px-2 py-1.5">
            <dt className="eyebrow">{key.toLowerCase()}</dt>
            <dd
              className={clsx(
                'tnum mt-0.5 text-sm font-semibold',
                key === 'FRESH' && counts[key] > 0 && 'text-up',
                key === 'STALE' && counts[key] > 0 && 'text-attention-high',
                key === 'UNAVAILABLE' && counts[key] > 0 && 'text-down',
                counts[key] === 0 && 'text-slate-600',
              )}
            >
              {counts[key] ?? 0}
            </dd>
          </div>
        ))}
      </dl>

      {/* Conflicts — both values, always */}
      {quality.conflicts.length > 0 && (
        <div className="mt-3 space-y-2">
          <p className="eyebrow">Source disagreements</p>
          {quality.conflicts.map((conflict) => (
            <div
              key={conflict.symbol}
              className="rounded-lg border border-attention-high/25 bg-attention-high/5 px-3 py-2"
            >
              <div className="flex items-center gap-2">
                <AlertTriangle className="h-3 w-3 shrink-0 text-attention-high" aria-hidden />
                <Link
                  to={`/stocks/${conflict.symbol}`}
                  className="text-xs font-medium text-slate-200 hover:text-accent"
                >
                  {conflict.symbol}
                </Link>
                <span className="tnum ml-auto text-2xs text-attention-high">
                  {conflict.difference_percent.toFixed(2)}% apart
                </span>
              </div>
              <div className="mt-1.5 grid grid-cols-2 gap-2 text-2xs">
                <div className="rounded border border-line bg-ink-850 px-2 py-1">
                  <p className="text-slate-500">{conflict.source_a}</p>
                  <p className="tnum text-slate-200">{conflict.value_a.toFixed(2)}</p>
                </div>
                <div className="rounded border border-line bg-ink-850 px-2 py-1">
                  <p className="text-slate-500">{conflict.source_b}</p>
                  <p className="tnum text-slate-200">{conflict.value_b.toFixed(2)}</p>
                </div>
              </div>
              <p className="mt-1.5 text-2xs text-slate-500">
                Tolerance is {conflict.tolerance_percent}%. Showing{' '}
                <span className="text-slate-300">{conflict.resolved_with}</span> —{' '}
                {conflict.reason.toLowerCase()}. Both values are retained.
              </p>
            </div>
          ))}
        </div>
      )}

      {/* Delayed symbols */}
      {quality.delayed.length > 0 && (
        <div className="mt-3">
          <p className="eyebrow mb-1.5">Delayed</p>
          <div className="flex flex-wrap gap-1.5">
            {quality.delayed.map((item) => (
              <Link
                key={item.symbol}
                to={`/stocks/${item.symbol}`}
                className="chip border-attention-high/25 bg-attention-high/5 text-attention-high hover:border-attention-high/50"
              >
                <Clock className="h-3 w-3" aria-hidden />
                {item.symbol} · {item.label}
              </Link>
            ))}
          </div>
        </div>
      )}

      {/* Source health */}
      <div className="mt-3 border-t border-line pt-3">
        <p className="eyebrow mb-1.5">Sources</p>
        <ul className="space-y-1">
          {quality.sources.map((source) => (
            <li key={source.name} className="flex items-center gap-2 text-2xs">
              <Database className="h-3 w-3 shrink-0 text-slate-600" aria-hidden />
              <span className="text-slate-300">{source.name}</span>
              {source.is_primary && <span className="text-slate-600">primary</span>}
              <span
                className={clsx(
                  'tnum ml-auto',
                  source.status === 'HEALTHY' && 'text-up',
                  source.status === 'DEGRADED' && 'text-attention-high',
                  source.status === 'DOWN' && 'text-down',
                  source.status === 'IDLE' && 'text-slate-600',
                )}
              >
                {source.status.toLowerCase()}
                {source.error_count > 0 && ` · ${source.error_count} errors`}
              </span>
            </li>
          ))}
        </ul>
        {quality.fallback_reason && (
          <p className="mt-2 rounded border border-attention-high/25 bg-attention-high/5 px-2 py-1.5 text-2xs text-attention-high">
            {quality.fallback_reason}
          </p>
        )}
      </div>
    </div>
  )
}
