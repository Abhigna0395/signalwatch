import { useApi } from '../hooks/useApi'
import { api } from '../lib/api'
import { AttentionQueue } from '../components/AttentionQueue'
import { ErrorState, SectionHeading, Skeleton } from '../components/primitives'
import { ScoreBreakdown } from '../components/ScoreBreakdown'

/**
 * The Signals view: the full attention queue plus the scoring policy itself.
 *
 * Publishing the weights is a deliberate product choice. A user who disagrees
 * with a score should be able to see exactly which lever produced it, and an
 * operator should be able to retune it without reading the source.
 */
export function Signals() {
  const { data, error, isLoading, reload } = useApi(() => api.dashboard(), [], {
    refreshMs: 60_000,
  })

  if (isLoading) return <Skeleton className="h-96 w-full rounded-xl" />
  if (error || !data) {
    return (
      <div className="card">
        <ErrorState title="Cannot load signals" message={error?.message ?? ''} onRetry={reload} />
      </div>
    )
  }

  const rows = [...data.attention_queue, ...data.stable_stocks]
  const weights = data.config.weights
  const total = Object.values(weights).reduce((a, b) => a + b, 0)

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-xl font-semibold tracking-tight text-white">Signals</h1>
        <p className="mt-1 text-xs text-slate-500">
          Every tracked stock, scored and ranked. {data.summary.high_attention} high attention,{' '}
          {data.summary.watch} watch, {data.summary.stable} stable.
        </p>
      </header>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <section>
          <SectionHeading title="Attention queue" count={rows.length} />
          <AttentionQueue rows={rows} />
        </section>

        <aside className="space-y-4">
          <div className="card p-4">
            <h2 className="text-sm font-semibold text-slate-200">How scoring works</h2>
            <p className="mt-1.5 text-2xs leading-relaxed text-slate-500">
              An attention score is the sum of six bounded components. Each has a configured
              maximum, shown below, and each reports its own reasoning. There is no model and no
              hidden weighting — the arithmetic is the explanation.
            </p>

            <ul className="mt-3 space-y-2">
              {Object.entries(weights).map(([key, value]) => (
                <li key={key}>
                  <div className="flex items-baseline justify-between text-2xs">
                    <span className="capitalize text-slate-300">{key.replace(/_/g, ' ')}</span>
                    <span className="tnum text-slate-500">max {value}</span>
                  </div>
                  <div className="mt-1 h-1 overflow-hidden rounded-full bg-ink-700">
                    <div
                      className="h-full rounded-full bg-slate-600"
                      style={{ width: `${(value / total) * 100}%` }}
                    />
                  </div>
                </li>
              ))}
            </ul>

            <div className="mt-3 space-y-1 border-t border-line pt-3 text-2xs text-slate-500">
              <div className="flex justify-between">
                <span>Maximum possible</span>
                <span className="tnum text-slate-300">{total}</span>
              </div>
              <div className="flex justify-between">
                <span>High attention at</span>
                <span className="tnum text-attention-high">
                  ≥ {data.config.thresholds.high_attention}
                </span>
              </div>
              <div className="flex justify-between">
                <span>Watch at</span>
                <span className="tnum text-attention-watch">≥ {data.config.thresholds.watch}</span>
              </div>
            </div>
          </div>

          {/* Live worked example, using whatever currently ranks top. */}
          {data.attention_queue[0] && (
            <TopExample symbol={data.attention_queue[0].symbol} />
          )}
        </aside>
      </div>
    </div>
  )
}

function TopExample({ symbol }: { symbol: string }) {
  const { data } = useApi(() => api.stock(symbol), [symbol])
  if (!data) return null
  return (
    <div className="card p-4">
      <h2 className="text-sm font-semibold text-slate-200">
        Worked example · {data.symbol}
      </h2>
      <p className="mt-1.5 text-2xs leading-relaxed text-slate-500">{data.why_it_matters}</p>
      <div className="mt-3">
        <ScoreBreakdown explanation={data.explanation} defaultOpen />
      </div>
    </div>
  )
}
