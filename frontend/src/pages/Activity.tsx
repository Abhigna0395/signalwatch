import { Link } from 'react-router-dom'
import clsx from 'clsx'
import { Activity as ActivityIcon } from 'lucide-react'
import { useApi } from '../hooks/useApi'
import { api } from '../lib/api'
import { CATEGORY_META } from '../lib/format'
import { CATEGORY_ICON, EmptyState, ErrorState, Skeleton } from '../components/primitives'

/** A chronological feed of everything the engine has detected recently. */
export function Activity() {
  const { data, error, isLoading, reload } = useApi(() => api.dashboard(), [], {
    refreshMs: 60_000,
  })

  if (isLoading) return <Skeleton className="h-96 w-full rounded-xl" />
  if (error || !data) {
    return (
      <div className="card">
        <ErrorState title="Cannot load activity" message={error?.message ?? ''} onRetry={reload} />
      </div>
    )
  }

  const events = data.recent_events

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-xl font-semibold tracking-tight text-white">Activity</h1>
        <p className="mt-1 text-xs text-slate-500">
          Every event SignalWatch has detected across your watchlists, newest first.
        </p>
      </header>

      <div className="card overflow-hidden">
        {events.length === 0 ? (
          <EmptyState
            icon={ActivityIcon}
            title="No activity recorded yet"
            description="Events appear as the engine detects meaningful changes. Try the replay on the overview page."
          />
        ) : (
          <ul>
            {events.map((event, index) => {
              const meta = CATEGORY_META[event.category]
              const Icon = CATEGORY_ICON[event.category]
              return (
                <li
                  key={event.id}
                  style={{ ['--i' as string]: index }}
                  className="stagger flex animate-fade-up items-start gap-3 border-b border-line px-4 py-3 last:border-b-0"
                >
                  <span
                    className={clsx(
                      'mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-lg',
                      meta.bg,
                    )}
                    aria-hidden
                  >
                    <Icon className={clsx('h-3 w-3', meta.text)} />
                  </span>

                  <div className="min-w-0 flex-1">
                    <p className="text-xs text-slate-200">
                      <Link
                        to={`/stocks/${event.symbol}`}
                        className="font-semibold hover:text-accent"
                      >
                        {event.symbol}
                      </Link>{' '}
                      <span className="text-slate-300">{event.title}</span>
                    </p>
                    <p className="mt-0.5 flex items-center gap-2 text-2xs text-slate-600">
                      <span className={meta.text}>{meta.label}</span>
                      <span aria-hidden>·</span>
                      <span>{event.label}</span>
                      {event.severity === 'critical' && (
                        <>
                          <span aria-hidden>·</span>
                          <span className="text-attention-high">Critical</span>
                        </>
                      )}
                    </p>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </div>
  )
}
