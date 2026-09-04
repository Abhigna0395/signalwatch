/**
 * Watchlist management.
 *
 * Reordering is drag-and-drop using the native HTML5 API — no dependency, and
 * it degrades to keyboard-accessible move buttons, which matters because native
 * drag-and-drop is effectively unusable without a mouse.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import clsx from 'clsx'
import {
  ChevronDown,
  ChevronUp,
  GripVertical,
  Loader2,
  Pencil,
  Plus,
  Trash2,
  X,
} from 'lucide-react'
import { useApi } from '../hooks/useApi'
import { useToast } from '../hooks/useToast'
import { api, ApiError } from '../lib/api'
import type { StockRow, WatchlistSummary } from '../lib/types'
import { BandBadge, EmptyState, ErrorState, FreshnessDot, ScoreRing, Skeleton } from '../components/primitives'
import { directionClass, formatPercent, formatPrice } from '../lib/format'

export function Watchlists() {
  const [params, setParams] = useSearchParams()
  const { data, error, isLoading, reload } = useApi(() => api.dashboard(), [])
  const toast = useToast()

  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [renamingId, setRenamingId] = useState<number | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [busy, setBusy] = useState(false)
  const [dragSymbol, setDragSymbol] = useState<string | null>(null)
  const [order, setOrder] = useState<string[] | null>(null)

  const watchlists = data?.watchlists ?? []
  const selectedId = Number(params.get('id')) || watchlists[0]?.id || null
  const selected = useMemo(
    () => watchlists.find((w) => w.id === selectedId) ?? watchlists[0] ?? null,
    [watchlists, selectedId],
  )

  // Local ordering mirror, so drag feedback is instant and the server call can
  // settle afterwards.
  useEffect(() => {
    setOrder(selected ? selected.items.map((i) => i.symbol) : null)
  }, [selected?.id, selected?.items.length]) // eslint-disable-line react-hooks/exhaustive-deps

  const rows: StockRow[] = useMemo(() => {
    if (!selected) return []
    if (!order) return selected.items
    const bySymbol = new Map(selected.items.map((i) => [i.symbol, i]))
    return order.map((s) => bySymbol.get(s)).filter(Boolean) as StockRow[]
  }, [selected, order])

  const run = useCallback(
    async (action: () => Promise<unknown>, success: string) => {
      setBusy(true)
      try {
        await action()
        toast.push('success', success)
        await reload()
      } catch (err) {
        toast.push('error', err instanceof ApiError ? err.message : 'Something went wrong')
      } finally {
        setBusy(false)
      }
    },
    [reload, toast],
  )

  const persistOrder = useCallback(
    async (symbols: string[]) => {
      if (!selected) return
      try {
        await api.reorderItems(selected.id, symbols)
      } catch (err) {
        toast.push('error', err instanceof ApiError ? err.message : 'Could not save the new order')
        await reload()
      }
    },
    [selected, toast, reload],
  )

  const move = useCallback(
    (symbol: string, direction: -1 | 1) => {
      if (!order) return
      const from = order.indexOf(symbol)
      const to = from + direction
      if (from < 0 || to < 0 || to >= order.length) return
      const next = [...order]
      ;[next[from], next[to]] = [next[to], next[from]]
      setOrder(next)
      void persistOrder(next)
    },
    [order, persistOrder],
  )

  if (isLoading) return <Skeleton className="h-96 w-full rounded-xl" />
  if (error || !data) {
    return (
      <div className="card">
        <ErrorState title="Cannot load watchlists" message={error?.message ?? ''} onRetry={reload} />
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-white">Watchlists</h1>
          <p className="mt-1 text-xs text-slate-500">
            Group the market however you think about it. Attention scores are computed per stock,
            so a stock in two lists carries the same reading in both.
          </p>
        </div>
        <button onClick={() => setCreating(true)} className="btn-primary btn-sm">
          <Plus className="h-3.5 w-3.5" aria-hidden />
          New watchlist
        </button>
      </header>

      {creating && (
        <form
          className="card flex flex-wrap items-center gap-2 p-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (!newName.trim()) return
            void run(() => api.createWatchlist(newName.trim()), `Created “${newName.trim()}”`).then(() => {
              setNewName('')
              setCreating(false)
            })
          }}
        >
          <input
            autoFocus
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="e.g. High conviction"
            className="input max-w-xs"
            aria-label="New watchlist name"
          />
          <button type="submit" disabled={busy || !newName.trim()} className="btn-primary btn-sm">
            Create
          </button>
          <button
            type="button"
            onClick={() => {
              setCreating(false)
              setNewName('')
            }}
            className="btn-ghost btn-sm"
          >
            Cancel
          </button>
        </form>
      )}

      <div className="grid gap-5 lg:grid-cols-[16rem_minmax(0,1fr)]">
        {/* ── List of watchlists ────────────────────────────────────────── */}
        <nav className="card h-fit p-2" aria-label="Your watchlists">
          <ul className="space-y-0.5">
            {watchlists.map((list) => (
              <li key={list.id}>
                {renamingId === list.id ? (
                  <form
                    className="flex items-center gap-1 p-1"
                    onSubmit={(e) => {
                      e.preventDefault()
                      void run(
                        () => api.renameWatchlist(list.id, renameValue.trim()),
                        'Watchlist renamed',
                      ).then(() => setRenamingId(null))
                    }}
                  >
                    <input
                      autoFocus
                      value={renameValue}
                      onChange={(e) => setRenameValue(e.target.value)}
                      className="input py-1 text-xs"
                      aria-label="Watchlist name"
                    />
                    <button type="submit" className="btn-ghost btn-sm" disabled={busy}>
                      Save
                    </button>
                    <button type="button" onClick={() => setRenamingId(null)} className="btn-ghost btn-sm">
                      <X className="h-3 w-3" aria-hidden />
                    </button>
                  </form>
                ) : (
                  <div
                    className={clsx(
                      'group flex items-center gap-1 rounded-lg px-2 py-2 transition-colors',
                      selected?.id === list.id ? 'bg-ink-700' : 'hover:bg-ink-750',
                    )}
                  >
                    <button
                      onClick={() => setParams({ id: String(list.id) })}
                      className="min-w-0 flex-1 text-left"
                    >
                      <span className="block truncate text-xs font-medium text-slate-200">
                        {list.name}
                      </span>
                      <span className="text-2xs text-slate-500">
                        {list.count} stocks
                        {list.high_attention > 0 && ` · ${list.high_attention} high`}
                        {list.changed > 0 && ` · ${list.changed} changed`}
                      </span>
                    </button>
                    <button
                      onClick={() => {
                        setRenamingId(list.id)
                        setRenameValue(list.name)
                      }}
                      className="rounded p-1 text-slate-600 opacity-0 transition hover:text-slate-300 focus:opacity-100 group-hover:opacity-100"
                      aria-label={`Rename ${list.name}`}
                    >
                      <Pencil className="h-3 w-3" />
                    </button>
                    <button
                      onClick={() => {
                        if (confirm(`Delete “${list.name}”? The stocks stay in your other lists.`)) {
                          void run(() => api.deleteWatchlist(list.id), 'Watchlist deleted')
                        }
                      }}
                      className="rounded p-1 text-slate-600 opacity-0 transition hover:text-down focus:opacity-100 group-hover:opacity-100"
                      aria-label={`Delete ${list.name}`}
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </nav>

        {/* ── Selected watchlist ────────────────────────────────────────── */}
        <div className="card overflow-hidden">
          {!selected || rows.length === 0 ? (
            <EmptyState
              title={selected ? `“${selected.name}” is empty` : 'No watchlists yet'}
              description="Press ⌘K to search for a stock and add it."
            />
          ) : (
            <>
              <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
                <h2 className="text-sm font-semibold text-slate-200">{selected.name}</h2>
                <span className="text-2xs text-slate-500">
                  Avg attention <span className="tnum text-slate-300">{selected.average_score}</span>
                </span>
              </div>
              <ul>
                {rows.map((row, index) => (
                  <li
                    key={row.symbol}
                    draggable
                    onDragStart={() => setDragSymbol(row.symbol)}
                    onDragEnd={() => setDragSymbol(null)}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={(e) => {
                      e.preventDefault()
                      if (!dragSymbol || !order || dragSymbol === row.symbol) return
                      const next = order.filter((s) => s !== dragSymbol)
                      next.splice(next.indexOf(row.symbol), 0, dragSymbol)
                      setOrder(next)
                      void persistOrder(next)
                      setDragSymbol(null)
                    }}
                    className={clsx(
                      'flex items-center gap-3 border-b border-line px-3 py-3 last:border-b-0 transition-colors hover:bg-ink-750',
                      dragSymbol === row.symbol && 'opacity-40',
                    )}
                  >
                    <GripVertical
                      className="h-3.5 w-3.5 shrink-0 cursor-grab text-slate-700"
                      aria-hidden
                    />

                    {/* Keyboard-accessible reordering */}
                    <div className="flex shrink-0 flex-col">
                      <button
                        onClick={() => move(row.symbol, -1)}
                        disabled={index === 0}
                        className="rounded text-slate-700 hover:text-slate-300 disabled:opacity-25"
                        aria-label={`Move ${row.symbol} up`}
                      >
                        <ChevronUp className="h-3 w-3" />
                      </button>
                      <button
                        onClick={() => move(row.symbol, 1)}
                        disabled={index === rows.length - 1}
                        className="rounded text-slate-700 hover:text-slate-300 disabled:opacity-25"
                        aria-label={`Move ${row.symbol} down`}
                      >
                        <ChevronDown className="h-3 w-3" />
                      </button>
                    </div>

                    <Link to={`/stocks/${row.symbol}`} className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold text-white">{row.symbol}</span>
                        <BandBadge band={row.band} />
                      </div>
                      <p className="truncate text-2xs text-slate-500">{row.name}</p>
                      <FreshnessDot freshness={row.freshness} className="mt-0.5" />
                    </Link>

                    <div className="hidden text-right sm:block">
                      <p className="tnum text-sm text-slate-200">
                        {formatPrice(row.quote.price, row.currency)}
                      </p>
                      <p className={clsx('tnum text-2xs', directionClass(row.quote.change_percent))}>
                        {formatPercent(row.quote.change_percent)}
                      </p>
                    </div>

                    <div className="hidden w-28 shrink-0 text-2xs text-slate-500 md:block">
                      {row.top_reason}
                    </div>

                    <ScoreRing score={row.score} size={38} />

                    <button
                      onClick={() => {
                        void run(
                          () => api.removeStock(selected.id, row.symbol),
                          `${row.symbol} removed from ${selected.name}`,
                        )
                      }}
                      disabled={busy}
                      className="shrink-0 rounded p-1 text-slate-700 transition hover:text-down"
                      aria-label={`Remove ${row.symbol} from ${selected.name}`}
                    >
                      {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <X className="h-3.5 w-3.5" />}
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

export type { WatchlistSummary }
