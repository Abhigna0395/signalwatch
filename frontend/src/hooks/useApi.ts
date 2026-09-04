/**
 * A small async-resource hook.
 *
 * Deliberately hand-rolled rather than pulling in a data-fetching library: the
 * app has a handful of endpoints and one refresh policy, and the three states
 * that actually matter to the UI (loading / error / stale-while-revalidating)
 * are ~40 lines. It tracks `isRefreshing` separately from `isLoading` so a
 * background poll never blanks the screen the user is reading.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../lib/api'

interface State<T> {
  data: T | null
  error: ApiError | null
  isLoading: boolean
  isRefreshing: boolean
}

export function useApi<T>(
  fetcher: () => Promise<T>,
  deps: unknown[] = [],
  options: { refreshMs?: number; enabled?: boolean } = {},
) {
  const { refreshMs, enabled = true } = options
  const [state, setState] = useState<State<T>>({
    data: null,
    error: null,
    isLoading: true,
    isRefreshing: false,
  })

  // Keep the latest fetcher without making it a dependency — otherwise an
  // inline arrow function would restart the effect on every render.
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const load = useCallback(async (background = false) => {
    if (!mounted.current) return
    setState((s) => ({
      ...s,
      isLoading: background ? s.isLoading : s.data === null,
      isRefreshing: background,
      error: background ? s.error : null,
    }))
    try {
      const data = await fetcherRef.current()
      if (!mounted.current) return
      setState({ data, error: null, isLoading: false, isRefreshing: false })
    } catch (error) {
      if (!mounted.current) return
      setState((s) => ({
        // A failed background refresh keeps the last good data on screen; it is
        // better to show slightly old numbers, clearly labelled, than nothing.
        data: background ? s.data : null,
        error: error instanceof ApiError ? error : new ApiError(String(error), 0),
        isLoading: false,
        isRefreshing: false,
      }))
    }
  }, [])

  useEffect(() => {
    if (!enabled) {
      setState((s) => ({ ...s, isLoading: false }))
      return
    }
    void load(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, enabled])

  useEffect(() => {
    if (!refreshMs || !enabled) return
    const id = setInterval(() => {
      // Pausing while the tab is hidden avoids pointless provider traffic — the
      // scalability argument in miniature.
      if (document.visibilityState === 'visible') void load(true)
    }, refreshMs)
    return () => clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshMs, enabled, ...deps])

  return {
    ...state,
    reload: () => load(false),
    refresh: () => load(true),
    setData: (updater: (prev: T | null) => T | null) =>
      setState((s) => ({ ...s, data: updater(s.data) })),
  }
}
