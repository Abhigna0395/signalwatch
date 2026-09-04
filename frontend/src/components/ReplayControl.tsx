/**
 * "Replay Market Changes".
 *
 * Worth being precise about what this is: it is *not* a front-end animation.
 * Each step posts to the backend, which advances the demo world's clock. The
 * provider then returns different prices, volumes and news; the signal engine
 * re-detects events from scratch; the attention score genuinely re-rates. The
 * dashboard reload afterwards is reading real recomputed state.
 *
 * That distinction is the entire point of the feature — it demonstrates that
 * SignalWatch detects state *changes* rather than rendering a data feed.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import clsx from 'clsx'
import { Loader2, Play, RotateCcw, SkipForward, X } from 'lucide-react'
import { api, ApiError } from '../lib/api'
import type { ReplayFrame } from '../lib/types'
import { useToast } from '../hooks/useToast'

const STEP_DELAY_MS = 1900

export function ReplayControl({ onWorldChange }: { onWorldChange: () => Promise<unknown> | void }) {
  const [open, setOpen] = useState(false)
  const [frames, setFrames] = useState<ReplayFrame[]>([])
  const [current, setCurrent] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [busy, setBusy] = useState(false)
  const toast = useToast()

  // A ref, not state: the async play loop must be able to see a cancellation
  // that happened after it started awaiting.
  const cancelled = useRef(false)

  useEffect(() => {
    api
      .replay()
      .then((state) => {
        setFrames(state.steps)
        setCurrent(state.current_step)
      })
      .catch(() => setFrames([]))
  }, [])

  useEffect(() => () => { cancelled.current = true }, [])

  const sync = useCallback(async () => {
    await onWorldChange()
  }, [onWorldChange])

  const reset = useCallback(async () => {
    setBusy(true)
    cancelled.current = true
    setPlaying(false)
    try {
      const state = await api.replayReset()
      setCurrent(state.current_step)
      await sync()
      toast.push('info', 'Rewound to the quiet market — and marked as reviewed')
    } catch (error) {
      toast.push('error', error instanceof ApiError ? error.message : 'Could not reset the replay')
    } finally {
      setBusy(false)
    }
  }, [sync, toast])

  const step = useCallback(
    async (target?: number) => {
      setBusy(true)
      try {
        const state = await api.replayStep(target)
        setCurrent(state.current_step)
        await sync()
        return state
      } catch (error) {
        toast.push('error', error instanceof ApiError ? error.message : 'Replay step failed')
        return null
      } finally {
        setBusy(false)
      }
    },
    [sync, toast],
  )

  const play = useCallback(async () => {
    cancelled.current = false
    setPlaying(true)
    // Always start from the beginning so the narrative is the same every time.
    await reset0()
    for (let i = 1; i < frames.length; i += 1) {
      if (cancelled.current) break
      await new Promise((r) => setTimeout(r, STEP_DELAY_MS))
      if (cancelled.current) break
      await step(i)
    }
    setPlaying(false)
    if (!cancelled.current) {
      toast.push('success', 'Replay complete — NVDA has re-rated. Check "Since your last visit".')
    }

    async function reset0() {
      setBusy(true)
      try {
        const state = await api.replayReset()
        setCurrent(state.current_step)
        await sync()
      } finally {
        setBusy(false)
      }
    }
  }, [frames.length, step, sync, toast])

  const stop = () => {
    cancelled.current = true
    setPlaying(false)
  }

  if (frames.length === 0) return null

  return (
    <div className="card overflow-hidden">
      <div className="space-y-2.5 px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-200">Replay market changes</h2>
          <p className="mt-0.5 text-2xs leading-relaxed text-slate-500">
            Advances the demo world on the server. Signals are re-detected and the score is
            recomputed at every step — nothing here is pre-recorded.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          {playing ? (
            <button onClick={stop} className="btn-ghost btn-sm">
              <X className="h-3.5 w-3.5" aria-hidden />
              Stop
            </button>
          ) : (
            <button onClick={play} disabled={busy} className="btn-primary btn-sm">
              {busy ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
              ) : (
                <Play className="h-3.5 w-3.5" aria-hidden />
              )}
              Replay
            </button>
          )}
          <button
            onClick={() => step()}
            disabled={busy || playing || current >= frames.length - 1}
            className="btn-ghost btn-sm"
            title="Advance one step"
          >
            <SkipForward className="h-3.5 w-3.5" aria-hidden />
            Step
          </button>
          <button onClick={reset} disabled={busy || playing} className="btn-ghost btn-sm" title="Rewind to the quiet market">
            <RotateCcw className="h-3.5 w-3.5" aria-hidden />
            Reset
          </button>
          <button
            onClick={() => setOpen((o) => !o)}
            className="btn-ghost btn-sm"
            aria-expanded={open}
          >
            {open ? 'Hide' : 'Timeline'}
          </button>
        </div>

        <p className="tnum text-2xs text-slate-600">
          Step {current + 1} / {frames.length} · {frames[current]?.clock} — {frames[current]?.caption}
        </p>
      </div>

      {/* Progress track */}
      <div className="flex gap-1 px-4 pb-3" role="progressbar" aria-valuenow={current + 1}
           aria-valuemin={1} aria-valuemax={frames.length}
           aria-label={`Replay step ${current + 1} of ${frames.length}`}>
        {frames.map((frame, index) => (
          <div
            key={frame.step}
            className={clsx(
              'h-1 flex-1 rounded-full transition-colors duration-500',
              index < current ? 'bg-accent/50' : index === current ? 'bg-accent' : 'bg-ink-700',
            )}
          />
        ))}
      </div>

      {open && (
        <ol className="animate-fade-in border-t border-line">
          {frames.map((frame, index) => {
            const isCurrent = index === current
            const isPast = index < current
            return (
              <li
                key={frame.step}
                className={clsx(
                  'flex items-start gap-3 border-b border-line px-4 py-2.5 last:border-b-0 transition-colors',
                  isCurrent && 'bg-accent/5',
                )}
              >
                <span
                  className={clsx(
                    'mt-1 h-1.5 w-1.5 shrink-0 rounded-full',
                    isCurrent ? 'bg-accent animate-pulse' : isPast ? 'bg-accent/40' : 'bg-ink-600',
                  )}
                  aria-hidden
                />
                <span className={clsx('tnum shrink-0 text-2xs', isCurrent ? 'text-accent' : 'text-slate-600')}>
                  {frame.clock}
                </span>
                <div className="min-w-0 flex-1">
                  <p className={clsx('text-xs', isCurrent ? 'text-slate-100' : 'text-slate-400')}>
                    {frame.caption}
                  </p>
                  <p className="tnum mt-0.5 text-2xs text-slate-600">
                    {frame.symbol} {frame.change_percent >= 0 ? '+' : ''}
                    {frame.change_percent.toFixed(2)}% · vol {frame.volume_ratio.toFixed(2)}× ·{' '}
                    {frame.news_count} news
                  </p>
                </div>
              </li>
            )
          })}
        </ol>
      )}
    </div>
  )
}
