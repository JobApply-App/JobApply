'use client'
import { useEffect, useState } from 'react'
import { fetchAllJobsFilterOptions } from '@/lib/api'
import type { AllJobsFilterOptions } from '@/lib/api'
import { useAuth } from '@/contexts/AuthContext'

// Fetched once per mount — the dropdown option lists change only as new
// jobs are scraped in (twice daily, see run_scheduled_linkedin_scrape.sh),
// not on every filter interaction, so there's no reason to refetch this
// alongside useAllJobs's page/filter-driven requests.
export function useAllJobsFilterOptions(): AllJobsFilterOptions | null {
  const { session, loading: authLoading } = useAuth()
  const [options, setOptions] = useState<AllJobsFilterOptions | null>(null)

  useEffect(() => {
    if (authLoading || !session) return
    const controller = new AbortController()
    fetchAllJobsFilterOptions(controller.signal)
      .then(setOptions)
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'AbortError') return
        // Silent — filter dropdowns just render empty; not worth an error UI
        // for a progressive-enhancement feature over the base job list.
      })
    return () => controller.abort()
  }, [authLoading, session?.user?.id])

  return options
}
