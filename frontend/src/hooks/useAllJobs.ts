'use client'
import { useEffect, useRef, useState } from 'react'
import { fetchAllJobs } from '@/lib/api'
import type { AllJobItem, PaginationMeta } from '@/lib/api'
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

export function useAllJobs(page: number, pageSize: number): UseAllJobsResult {
  const { session, loading: authLoading } = useAuth()

  const [jobs, setJobs] = useState<AllJobItem[]>([])
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

    fetchAllJobs(page, pageSize, controller.signal)
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
