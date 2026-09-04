/**
 * News, grouped rather than listed.
 *
 * Three headlines about the same catalyst are one piece of information, not
 * three. Each cluster collapses to a topic, a count and a net tone, and expands
 * on demand — which is the difference between informing the user and burying
 * them.
 */

import { useState } from 'react'
import clsx from 'clsx'
import { ChevronDown, ExternalLink, Newspaper } from 'lucide-react'
import type { NewsCluster } from '../lib/types'
import { SENTIMENT_META } from '../lib/format'
import { EmptyState } from './primitives'

export function NewsClusters({ clusters }: { clusters: NewsCluster[] }) {
  if (clusters.length === 0) {
    return (
      <div className="card">
        <EmptyState
          icon={Newspaper}
          title="No recent catalysts detected."
          description="SignalWatch groups related headlines into topics. Nothing has clustered in the last 72 hours."
        />
      </div>
    )
  }

  return (
    <div className="card p-4">
      <h2 className="mb-3 text-sm font-semibold text-slate-200">News &amp; catalysts</h2>
      <ul className="space-y-2">
        {clusters.map((cluster) => (
          <ClusterRow key={cluster.topic} cluster={cluster} />
        ))}
      </ul>
    </div>
  )
}

function ClusterRow({ cluster }: { cluster: NewsCluster }) {
  const [open, setOpen] = useState(false)
  const tone = SENTIMENT_META[cluster.sentiment]

  return (
    <li className="overflow-hidden rounded-lg border border-line bg-ink-850">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors hover:bg-ink-800"
        aria-expanded={open}
      >
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-slate-100">{cluster.topic}</p>
          <p className="mt-0.5 text-2xs text-slate-500">
            {cluster.count} related {cluster.count === 1 ? 'story' : 'stories'} · latest{' '}
            {cluster.latest_label}
          </p>
        </div>

        <span className={clsx('chip shrink-0 border-transparent', tone.bg, tone.text)}>
          {tone.label}
          <span className="tnum text-slate-500">
            {Math.round(cluster.sentiment_confidence * 100)}%
          </span>
        </span>

        <ChevronDown
          className={clsx('h-3.5 w-3.5 shrink-0 text-slate-500 transition-transform', open && 'rotate-180')}
          aria-hidden
        />
      </button>

      {open && (
        <ul className="animate-fade-in divide-y divide-line border-t border-line">
          {cluster.headlines.map((item) => {
            const itemTone = SENTIMENT_META[item.sentiment]
            return (
              <li key={item.id} className="px-3 py-2.5">
                <div className="flex items-start gap-2">
                  <span
                    className={clsx('mt-1.5 h-1 w-1 shrink-0 rounded-full', itemTone.text.replace('text-', 'bg-'))}
                    aria-hidden
                  />
                  <div className="min-w-0 flex-1">
                    <p className="text-xs leading-relaxed text-slate-200">
                      {item.headline}
                      {item.url && (
                        <a
                          href={item.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="ml-1 inline-flex text-slate-500 hover:text-accent"
                          aria-label="Open the original article in a new tab"
                        >
                          <ExternalLink className="h-3 w-3" />
                        </a>
                      )}
                    </p>
                    {item.summary && (
                      <p className="mt-1 text-2xs leading-relaxed text-slate-500">{item.summary}</p>
                    )}
                    <p className="mt-1 flex flex-wrap items-center gap-x-2 text-2xs text-slate-600">
                      <span>{item.source || 'Unknown source'}</span>
                      <span aria-hidden>·</span>
                      <span>{item.published_label}</span>
                      <span aria-hidden>·</span>
                      <span className={itemTone.text}>{itemTone.label}</span>
                      <span className="text-slate-700">via {item.sentiment_provider}</span>
                    </p>
                  </div>
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </li>
  )
}
