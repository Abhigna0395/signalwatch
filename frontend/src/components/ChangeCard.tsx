/**
 * A single "Since your last visit" card.
 *
 * The information hierarchy is the whole point, and it is deliberately not the
 * hierarchy of an ordinary watchlist row:
 *
 *   1. WHAT CHANGED   — the delta against the user's own baseline, largest type
 *   2. WHY IT MATTERS — a written interpretation, not a list of indicators
 *   3. THE EVIDENCE   — the specific new signals, as chips
 *   4. the price      — present, but subordinate; the price is the *least*
 *                       novel thing on this card
 */

import { Link } from 'react-router-dom'
import clsx from 'clsx'
import { ArrowRight, Sparkles, TrendingDown, TrendingUp } from 'lucide-react'
import type { ChangeCard as ChangeCardType } from '../lib/types'
import { directionClass, formatPercent, formatPrice, formatMultiple } from '../lib/format'
import { BandBadge, CategoryChip, FreshnessDot, ScoreRing } from './primitives'

export function ChangeCard({ change, index = 0 }: { change: ChangeCardType; index?: number }) {
  const since = change.since_last_visit
  const delta = since.price_change_percent
  const Icon = (delta ?? 0) >= 0 ? TrendingUp : TrendingDown

  return (
    <Link
      to={`/stocks/${change.symbol}`}
      style={{ ['--i' as string]: index }}
      className="card card-hover stagger group flex animate-fade-up flex-col gap-3 p-4 focus-visible:border-accent/40"
    >
      {/* ── Identity + score ────────────────────────────────────────────── */}
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold tracking-tight text-white">{change.symbol}</span>
            <BandBadge band={change.band} />
            {since.escalated && (
              <span className="chip animate-pulse-ring border-attention-high/30 bg-attention-high/10 text-attention-high">
                <Sparkles className="h-3 w-3" aria-hidden />
                Escalated
              </span>
            )}
          </div>
          <p className="mt-0.5 truncate text-2xs text-slate-500">{change.name}</p>
        </div>

        <ScoreRing score={change.score} delta={since.score_delta} showDelta size={52} />
      </div>

      {/* ── The delta: the headline of the card ─────────────────────────── */}
      <div className="rounded-lg border border-line bg-ink-850 px-3 py-2.5">
        <p className="eyebrow">Since you last checked</p>
        <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className={clsx('flex items-center gap-1.5 tnum text-xl font-semibold', directionClass(delta))}>
            <Icon className="h-4 w-4" aria-hidden />
            {formatPercent(delta)}
          </span>
          {since.price_from !== null && (
            <span className="tnum text-2xs text-slate-500">
              {formatPrice(since.price_from, change.currency)}
              <ArrowRight className="mx-1 inline h-3 w-3" aria-hidden />
              {formatPrice(since.price_to, change.currency)}
            </span>
          )}
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-slate-500">
          {since.score_delta !== null && Math.abs(since.score_delta) >= 1 && (
            <span className="tnum">
              Attention{' '}
              <span className="text-slate-300">
                {Math.round(since.score_from ?? 0)} → {Math.round(since.score_to ?? 0)}
              </span>
            </span>
          )}
          {change.quote.volume_ratio !== null && (
            <span className="tnum">
              Volume <span className="text-slate-300">{formatMultiple(change.quote.volume_ratio)}</span> normal
            </span>
          )}
        </div>
      </div>

      {/* ── Why it matters ──────────────────────────────────────────────── */}
      <div>
        <p className="eyebrow">Why this matters</p>
        <p className="mt-1 text-xs leading-relaxed text-slate-400">{change.why_it_matters}</p>
      </div>

      {/* ── The evidence ────────────────────────────────────────────────── */}
      {change.new_signals.length > 0 && (
        <div>
          <p className="eyebrow mb-1.5">
            New since your review · {change.new_signals.length}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {change.new_signals.slice(0, 4).map((signal) => (
              <CategoryChip key={signal.fingerprint} category={signal.category} label={signal.title} />
            ))}
            {change.new_signals.length > 4 && (
              <span className="chip border-line text-slate-500">
                +{change.new_signals.length - 4} more
              </span>
            )}
          </div>
        </div>
      )}

      {/* ── Price, subordinate ──────────────────────────────────────────── */}
      <div className="mt-auto flex items-center justify-between border-t border-line pt-2.5">
        <div className="flex items-baseline gap-2">
          <span className="tnum text-sm font-medium text-slate-200">
            {formatPrice(change.quote.price, change.currency)}
          </span>
          <span className={clsx('tnum text-2xs', directionClass(change.quote.change_percent))}>
            {formatPercent(change.quote.change_percent)} today
          </span>
        </div>
        <FreshnessDot freshness={change.freshness} showLabel={false} />
      </div>
    </Link>
  )
}
