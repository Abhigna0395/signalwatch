/**
 * Quick Add — search a symbol and drop it into a watchlist.
 *
 * Keyboard-first: ⌘K / Ctrl-K opens it, arrows move, Enter selects, Escape
 * closes. Search is debounced so typing "NVIDIA" is one request, not six.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import clsx from 'clsx'
import { Loader2, Plus, Search } from 'lucide-react'
import { api, ApiError } from '../lib/api'
import type { SymbolMatch, Watchlist } from '../lib/types'
import { useToast } from '../hooks/useToast'

export function QuickAdd() {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SymbolMatch[]>([])
  const [watchlists, setWatchlists] = useState<Watchlist[]>([])
  const [targetId, setTargetId] = useState<number | null>(null)
  const [cursor, setCursor] = useState(0)
  const [busy, setBusy] = useState(false)
  const [searching, setSearching] = useState(false)

  const inputRef = useRef<HTMLInputElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()
  const toast = useToast()

  // ── Open / close ────────────────────────────────────────────────────────
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setOpen((o) => !o)
      }
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    if (!open) return
    inputRef.current?.focus()
    api
      .watchlists()
      .then((lists) => {
        setWatchlists(lists)
        setTargetId((current) => current ?? lists[0]?.id ?? null)
      })
      .catch(() => setWatchlists([]))
  }, [open])

  useEffect(() => {
    if (!open) return
    const onClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [open])

  // ── Debounced search ────────────────────────────────────────────────────
  useEffect(() => {
    if (!open) return
    const term = query.trim()
    if (!term) {
      setResults([])
      setSearching(false)
      return
    }
    setSearching(true)
    const id = setTimeout(() => {
      api
        .search(term)
        .then((matches) => {
          setResults(matches)
          setCursor(0)
        })
        .catch(() => setResults([]))
        .finally(() => setSearching(false))
    }, 220)
    return () => clearTimeout(id)
  }, [query, open])

  const targetName = useMemo(
    () => watchlists.find((w) => w.id === targetId)?.name ?? 'watchlist',
    [watchlists, targetId],
  )

  const add = useCallback(
    async (match: SymbolMatch) => {
      if (!targetId) {
        toast.push('error', 'Create a watchlist first')
        return
      }
      setBusy(true)
      try {
        await api.addStock(targetId, match.symbol)
        toast.push('success', `${match.symbol} added to ${targetName}`)
        setOpen(false)
        setQuery('')
        // A full reload guarantees every panel reflects the new membership;
        // cheap here, and impossible to get subtly out of sync.
        navigate(0)
      } catch (error) {
        toast.push('error', error instanceof ApiError ? error.message : 'Could not add that stock')
      } finally {
        setBusy(false)
      }
    },
    [targetId, targetName, toast, navigate],
  )

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setCursor((c) => Math.min(c + 1, results.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setCursor((c) => Math.max(c - 1, 0))
    } else if (e.key === 'Enter' && results[cursor]) {
      e.preventDefault()
      void add(results[cursor])
    }
  }

  return (
    <div className="relative" ref={containerRef}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 rounded-lg border border-line bg-ink-800 px-2.5 py-1.5 text-xs text-slate-500 transition-colors hover:border-line-strong hover:text-slate-300 sm:w-56 sm:justify-start"
        aria-expanded={open}
        aria-haspopup="dialog"
      >
        <Search className="h-3.5 w-3.5" aria-hidden />
        <span className="hidden sm:inline">Search stocks…</span>
        <kbd className="ml-auto hidden rounded border border-line bg-ink-700 px-1.5 py-0.5 text-[10px] text-slate-500 sm:inline">
          ⌘K
        </kbd>
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Quick add a stock"
          className="absolute right-0 top-11 z-50 w-[min(26rem,calc(100vw-2rem))] animate-fade-up overflow-hidden rounded-xl border border-line-strong bg-ink-800 shadow-lift"
        >
          <div className="flex items-center gap-2 border-b border-line px-3">
            <Search className="h-4 w-4 shrink-0 text-slate-500" aria-hidden />
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder="NVIDIA, TSLA, RELIANCE…"
              className="w-full bg-transparent py-3 text-sm text-slate-100 placeholder:text-slate-600 focus:outline-none"
              aria-label="Search for a stock by symbol or company name"
            />
            {searching && <Loader2 className="h-3.5 w-3.5 animate-spin text-slate-500" aria-hidden />}
          </div>

          {watchlists.length > 0 && (
            <div className="flex items-center gap-2 border-b border-line px-3 py-2">
              <span className="eyebrow shrink-0">Add to</span>
              <select
                value={targetId ?? ''}
                onChange={(e) => setTargetId(Number(e.target.value))}
                className="min-w-0 flex-1 rounded-md border border-line bg-ink-850 px-2 py-1 text-xs text-slate-200 focus:outline-none"
                aria-label="Choose which watchlist to add to"
              >
                {watchlists.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="max-h-72 overflow-y-auto">
            {results.length === 0 && query.trim() && !searching && (
              <p className="px-3 py-6 text-center text-xs text-slate-500">
                No matches for “{query.trim()}”.
              </p>
            )}
            {results.length === 0 && !query.trim() && (
              <p className="px-3 py-6 text-center text-xs text-slate-600">
                Search by symbol or company name.
              </p>
            )}
            {results.map((match, index) => (
              <button
                key={match.symbol}
                onClick={() => add(match)}
                onMouseEnter={() => setCursor(index)}
                disabled={busy}
                className={clsx(
                  'flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors',
                  index === cursor ? 'bg-ink-700' : 'hover:bg-ink-750',
                )}
              >
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-slate-100">{match.symbol}</p>
                  <p className="truncate text-2xs text-slate-500">{match.name}</p>
                </div>
                <span className="shrink-0 text-2xs text-slate-600">{match.exchange}</span>
                <Plus className="h-3.5 w-3.5 shrink-0 text-slate-500" aria-hidden />
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
