import clsx from 'clsx'
import { Clock } from 'lucide-react'
import type { Dashboard } from '../lib/types'
import { directionClass, formatPercent } from '../lib/format'
import { DemoBadge } from './primitives'

const STATE_META: Record<string, { label: string; dot: string; text: string }> = {
  OPEN: { label: 'Open', dot: 'bg-up', text: 'text-up' },
  CLOSED: { label: 'Closed', dot: 'bg-slate-500', text: 'text-slate-400' },
  PRE_MARKET: { label: 'Pre-market', dot: 'bg-attention-watch', text: 'text-attention-watch' },
  AFTER_HOURS: { label: 'After hours', dot: 'bg-attention-watch', text: 'text-attention-watch' },
}

export function MarketPulse({ market }: { market: Dashboard['market_status'] }) {
  return (
    <div className="card flex flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3">
      <div className="flex items-center gap-4">
        {market.sessions.map((session) => {
          const meta = STATE_META[session.state] ?? STATE_META.CLOSED
          return (
            <div key={session.exchange} className="flex items-center gap-2">
              <span
                className={clsx('h-2 w-2 rounded-full', meta.dot, session.is_open && 'animate-pulse')}
                aria-hidden
              />
              <div className="leading-tight">
                <p className="text-xs font-medium text-slate-200">
                  {session.exchange === 'US' ? 'US markets' : 'India'}{' '}
                  <span className={meta.text}>{meta.label}</span>
                </p>
                <p className="text-2xs text-slate-500">{session.detail}</p>
              </div>
            </div>
          )
        })}
      </div>

      {market.indices.length > 0 && (
        <div className="flex items-center gap-5 border-line pl-0 sm:border-l sm:pl-6">
          {market.indices.map((index) => (
            <div key={index.name} className="leading-tight">
              <p className="eyebrow">{index.name}</p>
              <p className={clsx('tnum text-xs font-medium', directionClass(index.change_percent))}>
                {formatPercent(index.change_percent)}
              </p>
            </div>
          ))}
          {market.indices.some((i) => i.is_proxy) && (
            <span
              className="text-2xs text-slate-600"
              title="Index levels are derived from a basket of demo constituents, so they stay consistent with the watchlist below."
            >
              proxy
            </span>
          )}
        </div>
      )}

      <div className="ml-auto flex items-center gap-3">
        <span className="hidden items-center gap-1.5 text-2xs text-slate-500 sm:flex">
          <Clock className="h-3 w-3" aria-hidden />
          {market.sessions[0]?.local_time}
        </span>
        {market.is_demo && <DemoBadge />}
      </div>
    </div>
  )
}
