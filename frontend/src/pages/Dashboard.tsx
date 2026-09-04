/**
 * The dashboard.
 *
 * Deliberate ordering, top to bottom — this is the product argument in layout
 * form:
 *
 *   1. Market pulse       — context, one line
 *   2. SINCE YOUR LAST VISIT — what changed while you were away. The hero.
 *   3. Attention queue    — everything, triaged by how much it deserves you
 *   4. Watchlists / activity — the conventional views, last
 *
 * An ordinary watchlist opens with a price table. This opens with an answer to
 * "what did I miss?", because that is the question the user actually arrived
 * with.
 */

import { useCallback, useState } from 'react'
import { Link } from 'react-router-dom'
import clsx from 'clsx'
import { CheckCheck, Loader2, RefreshCw, Sparkles } from 'lucide-react'
import { useApi } from '../hooks/useApi'
import { useToast } from '../hooks/useToast'
import { api, ApiError } from '../lib/api'
import { AttentionQueue } from '../components/AttentionQueue'
import { ChangeCard } from '../components/ChangeCard'
import { DataQualityPanel } from '../components/DataQualityPanel'
import { MarketPulse } from '../components/MarketPulse'
import { ReplayControl } from '../components/ReplayControl'
import { EmptyState, ErrorState, SectionHeading, Skeleton } from '../components/primitives'

export function Dashboard() {
  const { data, error, isLoading, isRefreshing, reload, refresh } = useApi(
    () => api.dashboard(),
    [],
    { refreshMs: 60_000 },
  )
  const [reviewing, setReviewing] = useState(false)
  const toast = useToast()

  const markReviewed = useCallback(async () => {
    setReviewing(true)
    try {
      const result = await api.markReviewed()
      toast.push('success', `${result.message}. Your baseline is now current.`)
      await reload()
    } catch (err) {
      toast.push('error', err instanceof ApiError ? err.message : 'Could not mark as reviewed')
    } finally {
      setReviewing(false)
    }
  }, [reload, toast])

  if (isLoading) return <DashboardSkeleton />

  if (error || !data) {
    return (
      <div className="card">
        <ErrorState
          title="Cannot load your dashboard"
          message={error?.message ?? 'Unknown error'}
          onRetry={reload}
        />
      </div>
    )
  }

  const { since_last_visit: since, summary, onboarding } = data

  // ── First run ───────────────────────────────────────────────────────────
  if (onboarding?.is_first_run) {
    return <FirstRun suggested={onboarding.suggested} onDone={reload} />
  }

  return (
    <div className="space-y-6">
      {/* ── Greeting ─────────────────────────────────────────────────────── */}
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-white sm:text-2xl">
            {data.greeting}
          </h1>
          <p className="mt-1 text-sm text-slate-400">{summary.headline}</p>
          <p className="mt-0.5 text-2xs text-slate-600">
            Last reviewed {data.last_visit.label} · tracking {summary.tracked} stocks ·{' '}
            {summary.high_attention} high attention, {summary.watch} watch, {summary.stable} stable
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={refresh}
            disabled={isRefreshing}
            className="btn-ghost btn-sm"
            aria-label="Refresh market data"
          >
            <RefreshCw className={clsx('h-3.5 w-3.5', isRefreshing && 'animate-spin')} aria-hidden />
            {isRefreshing ? 'Refreshing' : 'Refresh'}
          </button>
          {since.count > 0 && (
            <button onClick={markReviewed} disabled={reviewing} className="btn-primary btn-sm">
              {reviewing ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
              ) : (
                <CheckCheck className="h-3.5 w-3.5" aria-hidden />
              )}
              Mark all as reviewed
            </button>
          )}
        </div>
      </header>

      <MarketPulse market={data.market_status} />

      {/* ── THE HERO: since your last visit ──────────────────────────────── */}
      <section aria-labelledby="since-heading">
        <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
          <div>
            <h2
              id="since-heading"
              className="flex items-center gap-2 text-lg font-semibold tracking-tight text-white"
            >
              Since your last visit
              {since.count > 0 && (
                <span className="tnum rounded-md bg-accent/15 px-2 py-0.5 text-xs font-semibold text-accent">
                  {since.count}
                </span>
              )}
            </h2>
            <p className="mt-0.5 text-xs text-slate-500">
              {since.count > 0
                ? `Measured against the state you acknowledged ${data.last_visit.label}.`
                : 'Your baseline is current.'}
            </p>
          </div>
        </div>

        {since.count === 0 ? (
          <div className="card">
            <EmptyState
              icon={CheckCheck}
              title={since.empty_message}
              description="SignalWatch is watching in the background. Anything meaningful will appear here."
            />
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
            {since.changes.map((change, index) => (
              <ChangeCard key={change.symbol} change={change} index={index} />
            ))}
          </div>
        )}
      </section>

      {/* ── Attention queue + sidebar ────────────────────────────────────── */}
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <section aria-labelledby="queue-heading">
          <SectionHeading
            title="Attention queue"
            count={data.attention_queue.length + data.stable_stocks.length}
            description="Every tracked stock, ranked by how much it deserves your attention right now."
          />
          <div id="queue-heading" className="sr-only">
            Attention queue
          </div>
          <AttentionQueue rows={[...data.attention_queue, ...data.stable_stocks]} />
        </section>

        <aside className="space-y-4">
          {data.market_status.is_demo && <ReplayControl onWorldChange={reload} />}
          <DataQualityPanel quality={data.data_quality} />
          <WatchlistsCard watchlists={data.watchlists} />
          <RecentActivityCard events={data.recent_events} />
        </aside>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────

function WatchlistsCard({ watchlists }: { watchlists: import('../lib/types').WatchlistSummary[] }) {
  return (
    <div className="card p-4">
      <div className="mb-2.5 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-200">Your watchlists</h2>
        <Link to="/watchlists" className="text-2xs text-slate-500 hover:text-accent">
          Manage
        </Link>
      </div>
      <ul className="space-y-1">
        {watchlists.map((list) => (
          <li key={list.id}>
            <Link
              to={`/watchlists?id=${list.id}`}
              className="flex items-center gap-2 rounded-lg px-2 py-1.5 transition-colors hover:bg-ink-750"
            >
              <span className="min-w-0 flex-1 truncate text-xs text-slate-300">{list.name}</span>
              {list.changed > 0 && (
                <span className="tnum rounded bg-accent/15 px-1.5 text-2xs text-accent">
                  {list.changed} new
                </span>
              )}
              <span className="tnum text-2xs text-slate-600">{list.count}</span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}

function RecentActivityCard({ events }: { events: import('../lib/types').Dashboard['recent_events'] }) {
  if (events.length === 0) return null
  return (
    <div className="card p-4">
      <div className="mb-2.5 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-200">Recent activity</h2>
        <Link to="/activity" className="text-2xs text-slate-500 hover:text-accent">
          All
        </Link>
      </div>
      <ul className="space-y-2">
        {events.slice(0, 6).map((event) => (
          <li key={event.id} className="flex items-start gap-2">
            <span
              className={clsx(
                'mt-1.5 h-1 w-1 shrink-0 rounded-full',
                event.direction === 'up'
                  ? 'bg-up'
                  : event.direction === 'down'
                    ? 'bg-down'
                    : 'bg-slate-600',
              )}
              aria-hidden
            />
            <div className="min-w-0 flex-1">
              <p className="truncate text-2xs text-slate-300">
                <Link to={`/stocks/${event.symbol}`} className="font-medium hover:text-accent">
                  {event.symbol}
                </Link>{' '}
                {event.title}
              </p>
              <p className="text-2xs text-slate-600">{event.label}</p>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

function FirstRun({ suggested, onDone }: { suggested: string[]; onDone: () => void }) {
  const [busy, setBusy] = useState(false)
  const toast = useToast()

  const create = async () => {
    setBusy(true)
    try {
      await api.createStarter()
      toast.push('success', 'Starter watchlist created')
      onDone()
    } catch (error) {
      toast.push('error', error instanceof ApiError ? error.message : 'Could not create the watchlist')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-lg py-16 text-center">
      <div className="mx-auto mb-5 flex h-12 w-12 items-center justify-center rounded-xl border border-line bg-ink-750">
        <Sparkles className="h-5 w-5 text-accent" aria-hidden />
      </div>
      <h1 className="text-xl font-semibold tracking-tight text-white">
        Build your first market watchlist.
      </h1>
      <p className="mx-auto mt-2 max-w-md text-sm text-slate-400">
        SignalWatch remembers what you have already seen, so when you come back it can show you
        only what actually changed — and explain why it matters.
      </p>

      <div className="mt-6 flex flex-wrap justify-center gap-1.5">
        {suggested.map((symbol) => (
          <span key={symbol} className="chip border-line bg-ink-800 text-slate-300">
            {symbol}
          </span>
        ))}
      </div>

      <button onClick={create} disabled={busy} className="btn-primary mx-auto mt-6">
        {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
        Add starter watchlist
      </button>
      <p className="mt-3 text-2xs text-slate-600">
        Or press <kbd className="rounded border border-line bg-ink-750 px-1">⌘K</kbd> to search for
        any stock.
      </p>
    </div>
  )
}

function DashboardSkeleton() {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Skeleton className="h-7 w-52" />
        <Skeleton className="h-4 w-80" />
      </div>
      <Skeleton className="h-14 w-full rounded-xl" />
      <div>
        <Skeleton className="mb-3 h-6 w-48" />
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-64 rounded-xl" />
          ))}
        </div>
      </div>
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <Skeleton className="h-96 rounded-xl" />
        <Skeleton className="h-96 rounded-xl" />
      </div>
    </div>
  )
}
