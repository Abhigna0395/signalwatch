/**
 * The Attention Queue — the triage centrepiece.
 *
 * Sorted by attention score, grouped into bands, and filterable by *why*
 * something is here rather than by what it is. The "top reason" column is the
 * one that does the work: it converts a number into a decision.
 */

import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import clsx from 'clsx'
import { Inbox } from 'lucide-react'
import type { Band, Category, StockRow } from '../lib/types'
import { BAND_META, directionClass, formatCompact, formatPercent, formatPrice } from '../lib/format'
import { BandBadge, EmptyState, FreshnessDot, ScoreRing } from './primitives'

type Filter = 'all' | 'high' | 'changed' | Category

const FILTERS: { key: Filter; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'high', label: 'High attention' },
  { key: 'changed', label: 'Newly changed' },
  { key: 'PRICE', label: 'Price' },
  { key: 'VOLUME', label: 'Volume' },
  { key: 'TECHNICAL', label: 'Technical' },
  { key: 'NEWS', label: 'News' },
]

function matches(row: StockRow, filter: Filter) {
  switch (filter) {
    case 'all':
      return true
    case 'high':
      return row.band === 'HIGH_ATTENTION'
    case 'changed':
      return row.since_last_visit.is_meaningful
    default:
      return row.categories.includes(filter)
  }
}

export function AttentionQueue({ rows, showBandHeadings = true }: { rows: StockRow[]; showBandHeadings?: boolean }) {
  const [filter, setFilter] = useState<Filter>('all')

  const filtered = useMemo(() => rows.filter((r) => matches(r, filter)), [rows, filter])

  const grouped = useMemo(() => {
    const groups: Record<Band, StockRow[]> = { HIGH_ATTENTION: [], WATCH: [], STABLE: [] }
    for (const row of filtered) groups[row.band].push(row)
    return groups
  }, [filtered])

  const counts = useMemo(() => {
    const out = {} as Record<Filter, number>
    for (const f of FILTERS) out[f.key] = rows.filter((r) => matches(r, f.key)).length
    return out
  }, [rows])

  return (
    <div className="space-y-3">
      {/* Filters */}
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter the attention queue">
        {FILTERS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setFilter(key)}
            aria-pressed={filter === key}
            disabled={counts[key] === 0 && key !== 'all'}
            className={clsx(
              'rounded-lg border px-2.5 py-1 text-2xs font-medium transition-colors disabled:opacity-35',
              filter === key
                ? 'border-accent/40 bg-accent/15 text-accent'
                : 'border-line bg-ink-800 text-slate-400 hover:border-line-strong hover:text-slate-200',
            )}
          >
            {label}
            <span className="tnum ml-1.5 text-slate-600">{counts[key]}</span>
          </button>
        ))}
      </div>

      <div className="card overflow-hidden">
        {/* Desktop column header */}
        <div className="hidden grid-cols-[1fr_7rem_6.5rem_9rem_7.5rem] items-center gap-3 border-b border-line px-4 py-2 lg:grid">
          <span className="eyebrow">Stock</span>
          <span className="eyebrow text-right">Price</span>
          <span className="eyebrow text-right">Change</span>
          <span className="eyebrow">Top signal</span>
          <span className="eyebrow text-right">Attention</span>
        </div>

        {filtered.length === 0 ? (
          <EmptyState
            icon={Inbox}
            title="Nothing matches this filter"
            description="Try a different category, or clear the filter to see the full queue."
          />
        ) : (
          (['HIGH_ATTENTION', 'WATCH', 'STABLE'] as Band[]).map((band) => {
            const group = grouped[band]
            if (group.length === 0) return null
            return (
              <section key={band}>
                {showBandHeadings && (
                  <div className="flex items-center gap-2 border-b border-line bg-ink-850/60 px-4 py-1.5">
                    <span className={clsx('h-1.5 w-1.5 rounded-full', BAND_META[band].dot)} aria-hidden />
                    <h3 className={clsx('text-2xs font-semibold uppercase tracking-label', BAND_META[band].text)}>
                      {BAND_META[band].label}
                    </h3>
                    <span className="tnum text-2xs text-slate-600">{group.length}</span>
                  </div>
                )}
                <ul>
                  {group.map((row, index) => (
                    <QueueRow key={row.symbol} row={row} index={index} />
                  ))}
                </ul>
              </section>
            )
          })
        )}
      </div>
    </div>
  )
}

function QueueRow({ row, index }: { row: StockRow; index: number }) {
  const meaningful = row.since_last_visit.is_meaningful

  return (
    <li style={{ ['--i' as string]: index }} className="stagger animate-fade-up">
      <Link
        to={`/stocks/${row.symbol}`}
        className="grid grid-cols-[1fr_auto] items-center gap-3 border-b border-line px-4 py-3 transition-colors last:border-b-0 hover:bg-ink-750 lg:grid-cols-[1fr_7rem_6.5rem_9rem_7.5rem]"
      >
        {/* Identity */}
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-white">{row.symbol}</span>
            {meaningful && (
              <span
                className="h-1.5 w-1.5 shrink-0 rounded-full bg-accent"
                title="Changed since your last review"
                aria-label="Changed since your last review"
              />
            )}
          </div>
          <p className="truncate text-2xs text-slate-500">{row.name}</p>
          {/* Mobile-only compact summary */}
          <div className="mt-1.5 flex items-center gap-3 lg:hidden">
            <span className="tnum text-xs text-slate-300">
              {formatPrice(row.quote.price, row.currency)}
            </span>
            <span className={clsx('tnum text-xs', directionClass(row.quote.change_percent))}>
              {formatPercent(row.quote.change_percent)}
            </span>
            <span className="truncate text-2xs text-slate-500">{row.top_reason}</span>
          </div>
        </div>

        {/* Price */}
        <div className="hidden text-right lg:block">
          <p className="tnum text-sm text-slate-200">{formatPrice(row.quote.price, row.currency)}</p>
          <p className="tnum text-2xs text-slate-600">
            Vol {formatCompact(row.quote.volume)}
          </p>
        </div>

        {/* Change */}
        <div className="hidden text-right lg:block">
          <p className={clsx('tnum text-sm font-medium', directionClass(row.quote.change_percent))}>
            {formatPercent(row.quote.change_percent)}
          </p>
          {row.quote.volume_ratio !== null && row.quote.volume_ratio >= 1.4 && (
            <p className="tnum text-2xs text-slate-500">{row.quote.volume_ratio.toFixed(1)}× vol</p>
          )}
        </div>

        {/* Top reason + freshness */}
        <div className="hidden min-w-0 lg:block">
          <p className="truncate text-xs text-slate-300">{row.top_reason}</p>
          <FreshnessDot freshness={row.freshness} className="mt-0.5" />
        </div>

        {/* Score */}
        <div className="flex items-center justify-end gap-2.5">
          <div className="hidden text-right sm:block lg:hidden">
            <BandBadge band={row.band} />
          </div>
          <ScoreRing
            score={row.score}
            size={40}
            showDelta
            delta={row.since_last_visit.score_delta}
          />
        </div>
      </Link>
    </li>
  )
}
