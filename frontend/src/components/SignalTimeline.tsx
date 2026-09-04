/**
 * The signal timeline.
 *
 * Grouped by day bucket, colour-coded by category, so the *sequence* of events
 * is legible: volume built, then price broke, then news arrived. A flat list of
 * indicators cannot convey causation; an ordered one at least lets the reader
 * infer it.
 */

import clsx from 'clsx'
import { History } from 'lucide-react'
import type { TimelineEntry } from '../lib/types'
import { CATEGORY_META } from '../lib/format'
import { CATEGORY_ICON, EmptyState } from './primitives'

export function SignalTimeline({ entries }: { entries: TimelineEntry[] }) {
  if (entries.length === 0) {
    return (
      <div className="card">
        <EmptyState
          icon={History}
          title="No events recorded yet"
          description="Events appear here as SignalWatch detects meaningful changes for this stock."
        />
      </div>
    )
  }

  // Preserve backend ordering (newest first) while grouping by bucket.
  const buckets: { name: string; items: TimelineEntry[] }[] = []
  for (const entry of entries) {
    const last = buckets[buckets.length - 1]
    if (last && last.name === entry.bucket) last.items.push(entry)
    else buckets.push({ name: entry.bucket, items: [entry] })
  }

  return (
    <div className="card p-4">
      <h2 className="mb-3 text-sm font-semibold text-slate-200">Signal timeline</h2>

      <div className="space-y-4">
        {buckets.map((bucket) => (
          <section key={bucket.name}>
            <h3 className="eyebrow mb-2">{bucket.name}</h3>
            <ol className="relative space-y-3 border-l border-line pl-4">
              {bucket.items.map((entry, index) => {
                const meta = CATEGORY_META[entry.category]
                const Icon = CATEGORY_ICON[entry.category]
                return (
                  <li
                    key={entry.id}
                    style={{ ['--i' as string]: index }}
                    className="stagger relative animate-fade-up"
                  >
                    {/* Node on the rail */}
                    <span
                      className={clsx(
                        'absolute -left-[1.3rem] top-1 flex h-4 w-4 items-center justify-center rounded-full border border-line',
                        meta.bg,
                      )}
                      aria-hidden
                    >
                      <Icon className={clsx('h-2.5 w-2.5', meta.text)} />
                    </span>

                    <div className="flex flex-wrap items-baseline gap-x-2">
                      <span className="tnum text-2xs text-slate-600">{entry.clock}</span>
                      <span className="text-xs font-medium text-slate-200">{entry.title}</span>
                      <span className={clsx('text-2xs', meta.text)}>{meta.label}</span>
                      {entry.severity === 'critical' && (
                        <span className="chip border-attention-high/30 bg-attention-high/10 text-attention-high">
                          Critical
                        </span>
                      )}
                    </div>
                    <p className="mt-0.5 text-2xs leading-relaxed text-slate-500">
                      {entry.description}
                    </p>
                  </li>
                )
              })}
            </ol>
          </section>
        ))}
      </div>
    </div>
  )
}
