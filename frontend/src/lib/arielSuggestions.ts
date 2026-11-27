// Ariel's command bar (design direction 4, Ron 27.11): up to four requests
// worth making right now, from the user's own data. Ariel cannot read
// applications or send anything, so each suggestion carries its details into
// the request text, and a follow-up is drafted for the user to send.

import type { ApiFeedJob } from './apiTypes'
import type { AppListItem } from './api'
import { nextStep, parseUpdated, stepIndex } from './journey'

/** A match worth sharpening the CV for. */
export const CV_SUGGEST_SCORE = 70
export const MAX_SUGGESTIONS = 4

export type Suggestion =
  | { kind: 'cv';     id: string; title: string; company: string; score: number }
  | { kind: 'prep';   id: string; title: string; company: string; stage: string }
  | { kind: 'follow'; id: string; title: string; company: string; days: number }
  | { kind: 'quick';  id: string; index: number }

export function buildSuggestions(
  jobs: Pick<ApiFeedJob, 'job_id' | 'title' | 'company' | 'match_score' | 'status'>[],
  apps: AppListItem[],
  quickCount: number,
  now: Date = new Date(),
): Suggestion[] {
  const out: Suggestion[] = []

  const top = jobs
    .filter(j => j.status === 'new' || j.status === 'saved')
    .reduce<typeof jobs[number] | null>((best, j) => (!best || j.match_score > best.match_score ? j : best), null)
  if (top && top.match_score >= CV_SUGGEST_SCORE) {
    out.push({ kind: 'cv', id: `cv-${top.job_id}`, title: top.title, company: top.company, score: top.match_score })
  }

  // The most advanced live process first: an interview beats a screening call.
  const live = apps
    .filter(a => { const s = stepIndex(a.status); return s === 1 || s === 2 })
    .sort((a, b) => stepIndex(b.status) - stepIndex(a.status))[0]
  if (live) out.push({ kind: 'prep', id: `prep-${live.application_id}`, title: live.title, company: live.company, stage: live.status })

  // The longest wait first.
  const quiet = apps
    .map(a => ({ a, at: parseUpdated(a.last_update) }))
    .filter(({ a, at }) => nextStep(a.status, at, now) === 'follow_up')
    .sort((x, y) => (x.at?.getTime() ?? 0) - (y.at?.getTime() ?? 0))[0]
  if (quiet?.at) {
    const days = Math.floor((now.getTime() - quiet.at.getTime()) / 86_400_000)
    out.push({ kind: 'follow', id: `follow-${quiet.a.application_id}`, title: quiet.a.title, company: quiet.a.company, days })
  }

  for (let i = 0; out.length < MAX_SUGGESTIONS && i < quickCount; i++) out.push({ kind: 'quick', id: `quick-${i}`, index: i })
  return out
}
