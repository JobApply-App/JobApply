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

  // Keyed on the user id, not the `session` object. Supabase hands back a new
  // session object on every silent token refresh, so depending on `session`
  // would refire this fetch on a timer for no reason — the option lists only
  // change when new jobs are scraped in. Guarding on `userId` rather than
  // `session` makes the narrower dependency exhaustive instead of suppressed;
  // a session with no user is not a usable authenticated state either way.
  const userId = session?.user?.id

  useEffect(() => {
    if (authLoading || !userId) return
    const controller = new AbortController()
    fetchAllJobsFilterOptions(controller.signal)
      .then(setOptions)
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'AbortError') return
        // Silent — filter dropdowns just render empty; not worth an error UI
        // for a progressive-enhancement feature over the base job list.
      })
    return () => controller.abort()
  }, [authLoading, userId])

  return options
}
