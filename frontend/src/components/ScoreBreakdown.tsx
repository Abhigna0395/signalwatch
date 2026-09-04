/**
 * The "Why?" panel.
 *
 * This is the component that makes the attention score defensible rather than
 * magical. It renders the arithmetic: every component's contribution as a
 * proportion of its own configured maximum, the sentence explaining it, and the
 * total. A judge should be able to add the numbers up by hand.
 */

import { useState } from 'react'
import clsx from 'clsx'
import { ChevronDown, HelpCircle } from 'lucide-react'
import type { Explanation } from '../lib/types'
import { scoreColor } from '../lib/format'

export function ScoreBreakdown({
  explanation,
  defaultOpen = false,
}: {
  explanation: Explanation
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  const contributing = explanation.components.filter((c) => c.points > 0.05)
  const total = explanation.components.reduce((sum, c) => sum + c.points, 0)

  return (
    <div className="rounded-lg border border-line bg-ink-850">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-3.5 py-2.5 text-left"
        aria-expanded={open}
      >
        <HelpCircle className="h-3.5 w-3.5 shrink-0 text-slate-500" aria-hidden />
        <span className="text-xs font-medium text-slate-300">
          Why is this score {Math.round(explanation.score)}?
        </span>
        <span className="ml-auto text-2xs text-slate-500">
          {contributing.length} contributing {contributing.length === 1 ? 'factor' : 'factors'}
        </span>
        <ChevronDown
          className={clsx('h-3.5 w-3.5 shrink-0 text-slate-500 transition-transform', open && 'rotate-180')}
          aria-hidden
        />
      </button>

      {open && (
        <div className="animate-fade-in space-y-3 border-t border-line px-3.5 py-3">
          <p className="text-2xs text-slate-500">
            The score is the sum of six independently-bounded components. Each maximum is
            configurable on the server; nothing here is a black box.
          </p>

          <ul className="space-y-2.5">
            {explanation.components.map((component) => {
              const pct = component.max_points > 0 ? (component.points / component.max_points) * 100 : 0
              const active = component.points > 0.05
              return (
                <li key={component.key}>
                  <div className="flex items-baseline justify-between gap-3 text-xs">
                    <span className={active ? 'text-slate-200' : 'text-slate-600'}>
                      {component.label}
                    </span>
                    <span
                      className={clsx('tnum shrink-0 font-medium', active ? 'text-slate-300' : 'text-slate-600')}
                    >
                      {component.points.toFixed(1)}
                      <span className="text-slate-600"> / {component.max_points.toFixed(0)}</span>
                    </span>
                  </div>

                  <div
                    className="mt-1 h-1 overflow-hidden rounded-full bg-ink-700"
                    role="meter"
                    aria-valuenow={Math.round(component.points)}
                    aria-valuemin={0}
                    aria-valuemax={component.max_points}
                    aria-label={`${component.label}: ${component.points.toFixed(1)} of ${component.max_points} points`}
                  >
                    <div
                      className="h-full rounded-full transition-all duration-700"
                      style={{
                        width: `${Math.max(pct, active ? 2 : 0)}%`,
                        backgroundColor: active ? scoreColor(explanation.score) : 'transparent',
                      }}
                    />
                  </div>

                  <p className={clsx('mt-1 text-2xs', active ? 'text-slate-500' : 'text-slate-600')}>
                    {component.detail}
                  </p>
                </li>
              )
            })}
          </ul>

          <div className="flex items-center justify-between border-t border-line pt-2.5 text-xs">
            <span className="font-medium text-slate-300">Total attention score</span>
            <span className="tnum font-semibold" style={{ color: scoreColor(explanation.score) }}>
              {total.toFixed(1)} → {Math.round(explanation.score)}
            </span>
          </div>

          <div className="flex items-center justify-between text-2xs text-slate-500">
            <span>Confidence in this reading</span>
            <span className="tnum">{Math.round(explanation.confidence * 100)}%</span>
          </div>
        </div>
      )}
    </div>
  )
}
