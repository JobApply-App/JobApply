'use client'
import { useEffect, useRef, useState } from 'react'
import { fetchAllJobs } from '@/lib/api'
import type { AllJobItem, AllJobsFilters, AllJobsPage, AllJobsSortBy, PaginationMeta } from '@/lib/api'
import { useAuth } from '@/contexts/AuthContext'

// Mirrors useLinkedInJobs.ts exactly (same hand-rolled useState/useEffect
// convention this project uses everywhere — no TanStack Query/SWR), just
// pointed at public.all_jobs instead of linkedin.jobs. See that hook's
// comment for the full "keep previous data" / race-safety rationale.

interface UseAllJobsResult {
  jobs: AllJobItem[]
  pagination: PaginationMeta | null
  loading: boolean
  error: string | null
  refetch: () => void
}

// ── Adjacent-page cache ──────────────────────────────────────────────────────
// Module-level (survives across re-renders/remounts of the hook, not just
// one component instance) so Next/Previous between pages that were already
// prefetched is instant instead of waiting on a fresh round-trip every
// click. Keyed by every param that changes the actual result set — a cache
// hit under a different filter/sort combination would silently show wrong
// data otherwise. Capped with simple FIFO eviction so a long session
// browsing many pages/filter combos doesn't grow this unbounded.
const _pageCache = new Map<string, AllJobsPage>()
const _MAX_CACHE_ENTRIES = 30

function _cacheKey(page: number, pageSize: number, filtersKey: string, sortBy?: AllJobsSortBy): string {
  return `${page}|${pageSize}|${filtersKey}|${sortBy ?? ''}`
}

function _cacheSet(key: string, data: AllJobsPage): void {
  if (!_pageCache.has(key) && _pageCache.size >= _MAX_CACHE_ENTRIES) {
    const oldestKey = _pageCache.keys().next().value
    if (oldestKey !== undefined) _pageCache.delete(oldestKey)
  }
  _pageCache.set(key, data)
}

// ── Shared loads and the early start ─────────────────────────────────────────
// Entering the Market waited on its first request (about a second, Ron
// 27.11). The app now starts that request quietly once the user is signed in,
// and a screen that asks for a page already on its way joins that request
// instead of sending another.
const _inflight = new Map<string, Promise<AllJobsPage>>()

/** A page from the cache, a request already on its way, or a new request. */
export function loadAllJobsPage(
  page: number, pageSize: number, filters?: AllJobsFilters, sortBy?: AllJobsSortBy,
): Promise<AllJobsPage> {
  const key = _cacheKey(page, pageSize, JSON.stringify(filters ?? {}), sortBy)
  const cached = _pageCache.get(key)
  if (cached) return Promise.resolve(cached)
  const going = _inflight.get(key)
  if (going) return going
  const p = fetchAllJobs(page, pageSize, filters, sortBy)
    .then((data) => { _cacheSet(key, data); return data })
    .finally(() => { _inflight.delete(key) })
  _inflight.set(key, p)
  return p
}

export function peekAllJobsPage(
  page: number, pageSize: number, filters?: AllJobsFilters, sortBy?: AllJobsSortBy,
): AllJobsPage | undefined {
  return _pageCache.get(_cacheKey(page, pageSize, JSON.stringify(filters ?? {}), sortBy))
}

/** The Market's opening view and its two counts, so entering it is instant. */
export const MARKET_FIRST_PAGE = { page: 1, pageSize: 25, sortBy: 'recent' as AllJobsSortBy }
export const MARKET_RECENT_FILTER: AllJobsFilters = { posted_within_hours: 24 }
export function prefetchMarket(): void {
  const ignore = () => { /* best-effort; the screen asks again when opened */ }
  loadAllJobsPage(MARKET_FIRST_PAGE.page, MARKET_FIRST_PAGE.pageSize, {}, MARKET_FIRST_PAGE.sortBy).catch(ignore)
  loadAllJobsPage(1, 1).catch(ignore)
  loadAllJobsPage(1, 1, MARKET_RECENT_FILTER).catch(ignore)
}

export function useAllJobs(
  page: number, pageSize: number, filters?: AllJobsFilters, sortBy?: AllJobsSortBy,
): UseAllJobsResult {
  const { session, loading: authLoading } = useAuth()

  const [jobs, setJobs] = useState<AllJobItem[]>([])
  const [pagination, setPagination] = useState<PaginationMeta | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [refetchTick, setRefetchTick] = useState(0)

  const requestIdRef = useRef(0)

  // Serialized so a fresh filters object literal on every render (the
  // common case — callers rarely useMemo their filter state) doesn't
  // retrigger the effect unless its actual contents changed.
  const filtersKey = JSON.stringify(filters ?? {})

  useEffect(() => {
    if (authLoading || !session) return

    const requestId = ++requestIdRef.current
    const controller = new AbortController()
    const key = _cacheKey(page, pageSize, filtersKey, sortBy)
    const parsedFilters = JSON.parse(filtersKey)

    const applyData = (data: AllJobsPage) => {
      if (requestId !== requestIdRef.current) return  // superseded by a newer request
      setJobs(data.items)
      setPagination(data.pagination)
      setError(null)
    }

    // Prefetches a neighboring page into the cache — fire-and-forget, no
    // loading state, no effect on the currently-displayed page. Skipped
    // silently on failure (a failed prefetch just means that page falls
    // back to a normal network fetch when/if the user navigates to it).
    const prefetch = (targetPage: number, totalPages: number) => {
      if (targetPage < 1 || targetPage > totalPages) return
      const targetKey = _cacheKey(targetPage, pageSize, filtersKey, sortBy)
      if (_pageCache.has(targetKey)) return
      fetchAllJobs(targetPage, pageSize, parsedFilters, sortBy)
        .then((data) => _cacheSet(targetKey, data))
        .catch(() => { /* best-effort only */ })
    }

    const cached = _pageCache.get(key)
    if (cached) {
      // Instant — no skeleton, no network wait. Still prefetches the new
      // neighbors below so paging further in the same direction stays fast.
      applyData(cached)
      setLoading(false)
      prefetch(page - 1, cached.pagination.total_pages)
      prefetch(page + 1, cached.pagination.total_pages)
      return
    }

    setLoading(true)
    const going = _inflight.get(key)
    ;(going ?? fetchAllJobs(page, pageSize, parsedFilters, sortBy, controller.signal))
      .then((data) => {
        _cacheSet(key, data)
        applyData(data)
        prefetch(page - 1, data.pagination.total_pages)
        prefetch(page + 1, data.pagination.total_pages)
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'AbortError') return
        if (requestId !== requestIdRef.current) return
        setError(err instanceof Error ? err.message : 'Failed to load jobs')
      })
      .finally(() => {
        if (requestId === requestIdRef.current) setLoading(false)
      })

    return () => controller.abort()
  }, [page, pageSize, filtersKey, sortBy, authLoading, session?.user?.id, refetchTick])  // eslint-disable-line react-hooks/exhaustive-deps

  return {
    jobs, pagination, loading, error,
    refetch: () => {
      // A manual refetch should bypass the cache too, or "Retry" would just
      // redisplay the same (possibly still-broken) cached data.
      _pageCache.delete(_cacheKey(page, pageSize, filtersKey, sortBy))
      setRefetchTick((t) => t + 1)
    },
  }
}
