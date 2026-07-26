'use client'
import { useEffect, useRef, useState } from 'react'
import { fetchLinkedInJobs } from '@/lib/api'
import type { LinkedInJobItem, PaginationMeta } from '@/lib/api'
import { useAuth } from '@/contexts/AuthContext'

// This project has no TanStack Query / SWR (confirmed — neither is a
// dependency, no QueryClientProvider exists anywhere); every other data
// hook in frontend/src/hooks/ is a hand-rolled useState/useEffect fetch
// (see useAgentStatus.ts, useJobMatches.ts). This hook follows that same
// convention while reproducing the specific behaviors a TanStack Query
// `useQuery({ queryKey: ['linkedin-jobs', page, pageSize], placeholderData:
// keepPreviousData })` would give you:
//   - refetch whenever [page, pageSize] changes (the effect's dep array is
//     the query-key equivalent — a change to either always triggers a
//     fresh fetch, never a stale cached page's data).
//   - "keep previous data" — `jobs`/`pagination` are only ever replaced
//     once the NEW page's response arrives; a page change does not clear
//     the table first, so there's no flash of empty/loading between pages.
//   - race-condition safety — an AbortController cancels the in-flight
//     request whenever page/pageSize changes again before it resolves, and
//     an `aborted` guard additionally ignores a late response that arrives
//     after a newer request has already started (belt and suspenders: some
//     browsers deliver the fetch's abort rejection a tick later than the
//     next effect run).

interface UseLinkedInJobsResult {
  jobs: LinkedInJobItem[]
  pagination: PaginationMeta | null
  loading: boolean
  error: string | null
  refetch: () => void
}

export function useLinkedInJobs(page: number, pageSize: number): UseLinkedInJobsResult {
  const { session, loading: authLoading } = useAuth()

  const [jobs, setJobs] = useState<LinkedInJobItem[]>([])
  const [pagination, setPagination] = useState<PaginationMeta | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [refetchTick, setRefetchTick] = useState(0)

  const requestIdRef = useRef(0)

  useEffect(() => {
    if (authLoading || !session) return

    const requestId = ++requestIdRef.current
    const controller = new AbortController()
    setLoading(true)

    fetchLinkedInJobs(page, pageSize, controller.signal)
      .then((data) => {
        if (requestId !== requestIdRef.current) return  // superseded by a newer request
        setJobs(data.items)
        setPagination(data.pagination)
        setError(null)
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
  }, [page, pageSize, authLoading, session?.user?.id, refetchTick])  // eslint-disable-line react-hooks/exhaustive-deps

  return { jobs, pagination, loading, error, refetch: () => setRefetchTick((t) => t + 1) }
}
