import { useCallback, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import clsx from 'clsx'
import { ArrowLeft, ArrowRight, CheckCheck, Loader2 } from 'lucide-react'
import { useApi } from '../hooks/useApi'
import { useToast } from '../hooks/useToast'
import { api, ApiError } from '../lib/api'
import { NewsClusters } from '../components/NewsClusters'
import { PriceChart } from '../components/PriceChart'
import { ScoreBreakdown } from '../components/ScoreBreakdown'
import { SignalTimeline } from '../components/SignalTimeline'
import {
  BandBadge,
  CategoryChip,
  ErrorState,
  FreshnessDot,
  ScoreRing,
  Skeleton,
  StaleWarning,
  Stat,
} from '../components/primitives'
import {
  directionClass,
  formatCompact,
  formatMultiple,
  formatPercent,
  formatPrice,
} from '../lib/format'

export function StockDetail() {
  const { symbol = '' } = useParams()
  const { data, error, isLoading, reload } = useApi(() => api.stock(symbol), [symbol], {
    refreshMs: 60_000,
  })
  const [reviewing, setReviewing] = useState(false)
  const toast = useToast()

  const markReviewed = useCallback(async () => {
    setReviewing(true)
    try {
      await api.markReviewed([symbol])
      toast.push('success', `${symbol} marked as reviewed`)
      await reload()
    } catch (err) {
      toast.push('error', err instanceof ApiError ? err.message : 'Could not mark as reviewed')
    } finally {
      setReviewing(false)
    }
  }, [symbol, reload, toast])

  if (isLoading) return <DetailSkeleton />

  if (error || !data) {
    return (
      <div className="card">
        <ErrorState
          title={`Cannot load ${symbol}`}
          message={error?.message ?? 'Unknown error'}
          onRetry={reload}
        />
      </div>
    )
  }

  const { quote, since_last_visit: since, technical } = data

  return (
    <div className="space-y-5">
      <Link to="/" className="inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-accent">
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
        Back to overview
      </Link>

      {/* ── Header ───────────────────────────────────────────────────────── */}
      <header className="card p-5">
        <div className="flex flex-wrap items-start justify-between gap-5">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="text-2xl font-semibold tracking-tight text-white">{data.symbol}</h1>
              <BandBadge band={data.band} />
            </div>
            <p className="mt-1 text-sm text-slate-400">{data.name}</p>
            <p className="text-2xs text-slate-600">
              {data.exchange}
              {data.sector && ` · ${data.sector}`}
            </p>

            <div className="mt-4 flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span className="tnum text-3xl font-semibold tracking-tight text-white">
                {formatPrice(quote.price, data.currency)}
              </span>
              <span className={clsx('tnum text-base font-medium', directionClass(quote.change_percent))}>
                {formatPercent(quote.change_percent)}
              </span>
              <span className={clsx('tnum text-xs', directionClass(quote.change_absolute))}>
                {quote.change_absolute !== null &&
                  `${quote.change_absolute >= 0 ? '+' : ''}${quote.change_absolute.toFixed(2)}`}
              </span>
              <span className="text-2xs text-slate-600">today</span>
            </div>

            <FreshnessDot freshness={data.freshness} className="mt-2" />
          </div>

          <div className="flex flex-col items-center gap-2">
            <ScoreRing score={data.score} size={84} />
            <div className="text-center">
              <p className="eyebrow">Attention score</p>
              <p className="text-2xs text-slate-500">
                {Math.round(data.confidence * 100)}% confidence
              </p>
            </div>
          </div>
        </div>

        {data.freshness.status !== 'FRESH' || data.freshness.verification === 'conflict' ? (
          <div className="mt-4">
            <StaleWarning freshness={data.freshness} />
          </div>
        ) : null}
      </header>

      {/* ── Since you last checked ───────────────────────────────────────── */}
      <section className="card p-5" aria-labelledby="since-detail">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 id="since-detail" className="text-sm font-semibold text-slate-200">
              Since you last checked
            </h2>
            <p className="mt-0.5 text-2xs text-slate-500">
              {since.has_baseline
                ? `Compared with the state you acknowledged ${
                    since.last_reviewed_at
                      ? new Date(since.last_reviewed_at).toLocaleString()
                      : 'previously'
                  }.`
                : 'You have not reviewed this stock yet, so there is no baseline to compare against.'}
            </p>
          </div>
          <button onClick={markReviewed} disabled={reviewing} className="btn-ghost btn-sm">
            {reviewing ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
            ) : (
              <CheckCheck className="h-3.5 w-3.5" aria-hidden />
            )}
            Mark reviewed
          </button>
        </div>

        {since.has_baseline ? (
          <>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <Stat
                label="Price"
                value={formatPercent(since.price_change_percent)}
                accent={directionClass(since.price_change_percent)}
                hint={
                  since.price_from !== null
                    ? `${formatPrice(since.price_from, data.currency)} → ${formatPrice(since.price_to, data.currency)}`
                    : undefined
                }
              />
              <Stat
                label="Volume"
                value={formatMultiple(quote.volume_ratio)}
                hint="vs 20-day average"
              />
              <Stat
                label="Attention score"
                value={
                  since.score_delta !== null
                    ? `${since.score_delta >= 0 ? '+' : ''}${Math.round(since.score_delta)}`
                    : '—'
                }
                accent={
                  (since.score_delta ?? 0) > 0 ? 'text-attention-high' : 'text-slate-300'
                }
                hint={
                  since.score_from !== null
                    ? `${Math.round(since.score_from)} → ${Math.round(since.score_to ?? 0)}`
                    : undefined
                }
              />
              <Stat
                label="Signals"
                value={`${since.new_signals.length} new`}
                hint={
                  since.resolved_signals.length > 0
                    ? `${since.resolved_signals.length} resolved`
                    : `${since.persisting_signals.length} ongoing`
                }
              />
            </div>

            {(since.technical_changes.length > 0 || since.band_from !== since.band_to) && (
              <div className="mt-3 flex flex-wrap gap-1.5 border-t border-line pt-3">
                {since.band_from && since.band_from !== since.band_to && (
                  <span className="chip border-attention-high/30 bg-attention-high/10 text-attention-high">
                    {since.band_from.replace('_', ' ').toLowerCase()}
                    <ArrowRight className="h-3 w-3" aria-hidden />
                    {since.band_to?.replace('_', ' ').toLowerCase()}
                  </span>
                )}
                {since.technical_changes.map((change) => (
                  <span key={change} className="chip border-line text-slate-400">
                    {change}
                  </span>
                ))}
              </div>
            )}
          </>
        ) : (
          <p className="text-xs text-slate-500">
            Mark this stock as reviewed to establish a baseline. From then on, SignalWatch will
            show you exactly what changed between visits.
          </p>
        )}
      </section>

      {/* ── Why this matters ─────────────────────────────────────────────── */}
      <section className="card p-5">
        <h2 className="text-sm font-semibold text-slate-200">Why this matters</h2>
        <p className="mt-2 text-sm leading-relaxed text-slate-300">{data.why_it_matters}</p>

        {data.categories.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {data.categories.map((category) => (
              <CategoryChip key={category} category={category} />
            ))}
          </div>
        )}

        <div className="mt-4">
          <ScoreBreakdown explanation={data.explanation} defaultOpen />
        </div>
      </section>

      {/* ── Chart + snapshot ─────────────────────────────────────────────── */}
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <PriceChart
          symbol={data.symbol}
          currency={data.currency}
          previousClose={quote.previous_close}
        />

        <div className="card p-4">
          <h2 className="mb-3 text-sm font-semibold text-slate-200">Market snapshot</h2>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
            <Stat label="Open" value={formatPrice(quote.open, data.currency)} />
            <Stat label="Previous close" value={formatPrice(quote.previous_close, data.currency)} />
            <Stat label="Day high" value={formatPrice(quote.day_high, data.currency)} />
            <Stat label="Day low" value={formatPrice(quote.day_low, data.currency)} />
            <Stat label="Volume" value={formatCompact(quote.volume)} />
            <Stat label="Avg volume" value={formatCompact(quote.avg_volume)} hint="20-day" />
            <Stat label="Market cap" value={formatCompact(quote.market_cap)} />
            <Stat label="Volume ratio" value={formatMultiple(quote.volume_ratio)} />
            <Stat label="52-week high" value={formatPrice(quote.week52_high, data.currency)} />
            <Stat label="52-week low" value={formatPrice(quote.week52_low, data.currency)} />
          </dl>

          <h3 className="eyebrow mb-2 mt-4 border-t border-line pt-3">Technical state</h3>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
            <Stat label="20-day avg" value={formatPrice(technical.sma20, data.currency)} />
            <Stat label="50-day avg" value={formatPrice(technical.sma50, data.currency)} />
            <Stat
              label="RSI (14)"
              value={technical.rsi14?.toFixed(0) ?? '—'}
              hint={technical.rsi_zone}
            />
            <Stat
              label="Volatility"
              value={technical.volatility_20d ? `${technical.volatility_20d.toFixed(0)}%` : '—'}
              hint={
                technical.volatility_ratio
                  ? `${technical.volatility_ratio.toFixed(2)}× baseline`
                  : undefined
              }
            />
            <Stat label="Resistance" value={formatPrice(technical.resistance60, data.currency)} hint="60-day" />
            <Stat label="Support" value={formatPrice(technical.support60, data.currency)} hint="60-day" />
          </dl>
        </div>
      </div>

      {/* ── Timeline + news ──────────────────────────────────────────────── */}
      <div className="grid gap-5 lg:grid-cols-2">
        <SignalTimeline entries={data.timeline} />
        <NewsClusters clusters={data.news} />
      </div>

      <p className="pb-2 text-2xs text-slate-600">
        SignalWatch surfaces market changes for informational purposes. It does not provide
        investment advice.
      </p>
    </div>
  )
}

function DetailSkeleton() {
  return (
    <div className="space-y-5">
      <Skeleton className="h-4 w-32" />
      <Skeleton className="h-44 w-full rounded-xl" />
      <Skeleton className="h-32 w-full rounded-xl" />
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <Skeleton className="h-80 rounded-xl" />
        <Skeleton className="h-80 rounded-xl" />
      </div>
    </div>
  )
}
