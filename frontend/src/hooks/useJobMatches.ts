'use client'
import { useCallback, useEffect, useState } from 'react'
import { fetchFeedJobs } from '@/lib/api'
import type { Job } from '@/lib/data'
import type { ApiFeedJob } from '@/lib/apiTypes'

interface UseJobMatchesResult {
  jobs:      Job[]        // mapped lightweight type — used by page.tsx sort/filter logic
  feedJobs:  ApiFeedJob[] // raw API shape — used by JobCard (needs apply_url, jd_text, etc.)
  loading:   boolean
  error:     string | null
  refetch:   () => void
}

/**
 * Fetch the user's job feed from the same endpoint as the Matches tab so
 * Overview always shows the same top-ranked jobs.
 *
 * Maps ApiFeedJob → Job using match_score as the display score so the
 * Overview preview ring is consistent with the Matches tab's ScoreRing.
 */
export function useJobMatches(): UseJobMatchesResult {
  const [jobs,     setJobs]     = useState<Job[]>([])
  const [feedJobs, setFeedJobs] = useState<ApiFeedJob[]>([])
  const [loading,  setLoading]  = useState(true)
  const [error,    setError]    = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      // Feed is already sorted by match_score DESC — preserve that order.
      const raw = await fetchFeedJobs(undefined, 100)
      const active = raw.filter(f => f.status !== 'ignored')

      // Raw ApiFeedJob array — passed to JobCard which needs apply_url, jd_text, etc.
      setFeedJobs(active)

      // Mapped Job array — used by page.tsx sort / filter / dismiss logic.
      setJobs(
        active.map((f, i) => ({
          id:         f.job_id,
          title:      f.title,
          company:    f.company,
          location:   f.location,
          postedAt:   f.posted_at,
          postedRank: raw.length - i,
          score:      f.match_score,
          isNew:      f.is_new,
          reasons:    f.reasons,
          whyRon:     f.why_ron ?? null,
        }))
      )
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch job matches')
    } finally {
      setLoading(false)
    }
  }, [])

  // Mount-only — load is NOT in the dep array intentionally.
  // load has [] deps itself (stable), but if that ever gains a dependency
  // that is updated by the API response, [load] here would create a loop.
  // Subsequent loads are explicit via the returned refetch function.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load() }, [])

  return { jobs, feedJobs, loading, error, refetch: load }
}
