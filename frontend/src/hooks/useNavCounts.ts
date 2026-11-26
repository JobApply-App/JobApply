'use client'
import { useEffect, useState } from 'react'
import { fetchApplicationsList, fetchFeedJobs } from '@/lib/api'
import type { Job } from '@/lib/data'

// The numbers beside the section tabs ("Matches 12", "Applications 4").
// The header sits on every page but only the dashboard loads the feed, so the
// counts live in a module cache: the dashboard writes its own jobs into it,
// and any other page reads the cache, fetching once if it is still empty.
// null = not known yet; the tab then shows no number rather than a wrong 0.

export interface NavCounts { feed: number | null; apps: number | null }

let cache: NavCounts = { feed: null, apps: null }
let inflight: Promise<void> | null = null
const listeners = new Set<(c: NavCounts) => void>()

function publish(next: Partial<NavCounts>) {
  cache = { ...cache, ...next }
  listeners.forEach(l => l(cache))
}

function load(needFeed: boolean): Promise<void> {
  if (inflight) return inflight
  inflight = Promise.allSettled([
    fetchApplicationsList().then(a => publish({ apps: a.length })),
    needFeed
      ? fetchFeedJobs(undefined, 100).then(f =>
          publish({ feed: f.filter(j => j.status !== 'ignored' && j.is_new).length }))
      : Promise.resolve(),
  ]).then(() => { inflight = null })
  return inflight
}

/** `jobs` is the dashboard's already-loaded feed; leave it out on other pages. */
export function useNavCounts(jobs?: Job[], enabled = true): NavCounts {
  const [counts, setCounts] = useState<NavCounts>(cache)

  useEffect(() => {
    listeners.add(setCounts)
    return () => { listeners.delete(setCounts) }
  }, [])

  // An empty array also arrives while the dashboard is still loading; it
  // only counts once something is in it, so a 0 is never shown too early.
  const fromPage = jobs && jobs.length > 0 ? jobs.filter(j => j.isNew).length : null
  useEffect(() => {
    if (fromPage !== null) publish({ feed: fromPage })
  }, [fromPage])

  // Applications are re-read each time a page mounts the header (one small
  // GET), so a job applied to elsewhere shows up on the next page.
  const needFeed = jobs === undefined
  useEffect(() => {
    if (enabled) void load(needFeed && cache.feed === null)
  }, [enabled, needFeed])

  return counts
}
