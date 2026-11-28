// The Profile page's data shaping (docs/redesign-plan-2026-11.md, §6 and Ron's
// notes on mockups v1-v3). Pure functions, so the rules can be tested without
// rendering: how target roles are grouped, how capabilities fall into the
// user's own domains, how a company's roles stack into one entry, and how
// "how well Ariel knows you" is scored.

import type { RoleSeniorityItem, AboutAnswers } from './api'

// ── GET /api/profile/view ─────────────────────────────────────────────────────

export interface ProfileExperience {
  company: string
  role:    string
  start:   string
  end:     string
  details: string
  kind:    string            // 'military' for army service
  source:  'ariel' | 'cv' | ''
}

export interface ProfileView {
  personal:   { name: string; email: string; phone: string; linkedin: string; location: string }
  summary:    string
  education:  { degree: string; school: string; period: string; status: string }[]
  experience: ProfileExperience[]   // most recent first
  languages:  { language: string; level: string }[]
}

export interface CapabilityEntity { name: string; category: string; score: number; verification_level?: string }

export const round1 = (x: number): number => Math.round(x * 10) / 10

// ── Target roles, grouped so similar ones sit together ────────────────────────

export type RoleFamily =
  | 'customer' | 'product' | 'data' | 'engineering' | 'design'
  | 'marketing' | 'sales' | 'operations' | 'finance' | 'people' | 'other'

// First match wins, so the more specific families come first ("Product
// Designer" is design, "Sales Engineer" is sales).
const FAMILY_WORDS: [RoleFamily, RegExp][] = [
  ['design',      /\b(design|designer|ux|ui)\b|מעצב/i],
  ['sales',       /\b(sales|business development|bdr|sdr|account executive)\b|מכירות/i],
  ['customer',    /\b(customer|client|account|success|support|service|partnership|onboarding)\b|לקוח|שירות/i],
  ['product',     /\b(product|owner)\b|מוצר/i],
  ['data',        /\b(data|analyst|analytics|bi|insights)\b|נתונים|אנליסט/i],
  ['engineering', /\b(engineer|developer|software|devops|qa|architect|programmer)\b|מפתח|מהנדס/i],
  ['marketing',   /\b(marketing|growth|content|seo|brand|community)\b|שיווק/i],
  ['operations',  /\b(operations|project|program|logistics|supply)\b|תפעול|פרויקט/i],
  ['finance',     /\b(finance|financial|fp&a|accountant|controller|economist)\b|כספים|חשב/i],
  ['people',      /\b(hr|recruit|recruiter|talent|people)\b|גיוס|משאבי אנוש/i],
]

export function roleFamily(role: string): RoleFamily {
  for (const [family, re] of FAMILY_WORDS) if (re.test(role)) return family
  return 'other'
}

/** The user's target roles by family, families in the order the user first named one. */
export function roleFamilies(roles: RoleSeniorityItem[]): { family: RoleFamily; items: RoleSeniorityItem[] }[] {
  const out: { family: RoleFamily; items: RoleSeniorityItem[] }[] = []
  for (const r of roles) {
    if (!r.role.trim()) continue
    const family = roleFamily(r.role)
    const group = out.find(g => g.family === family)
    if (group) group.items.push(r)
    else out.push({ family, items: [r] })
  }
  return out
}

// ── Capabilities, by the domains this user actually has ───────────────────────

export interface CapabilityDomain {
  category: string
  avg:      number
  count:    number
  skills:   { name: string; score: number }[]   // strongest first
}

export function capabilityDomains(entities: CapabilityEntity[], hidden: string[] = []): CapabilityDomain[] {
  const hide = new Set(hidden.map(h => h.toLowerCase()))
  const by = new Map<string, { name: string; score: number }[]>()
  for (const e of entities) {
    if (!e.name || hide.has(e.name.toLowerCase())) continue
    const list = by.get(e.category) ?? []
    list.push({ name: e.name, score: e.score })
    by.set(e.category, list)
  }
  return [...by.entries()]
    .map(([category, skills]) => ({
      category,
      count: skills.length,
      avg: skills.reduce((s, k) => s + k.score, 0) / skills.length,
      skills: [...skills].sort((a, b) => b.score - a.score),
    }))
    .sort((a, b) => b.avg - a.avg)
}

// ── Experience: one entry per company, roles stacked inside ───────────────────

const isMilitary = (e: ProfileExperience) => e.kind.toLowerCase() === 'military'

/** "2023", "2023-04", "04/2023" → 2023.25; "present" → open; nothing → NaN. */
export function when(s: string, open: number): number {
  const y = /(19|20)\d{2}/.exec(s)
  if (!y) return s.trim() ? open : NaN          // "present", "היום"
  const m = /(?:^|\D)(0?[1-9]|1[0-2])(?:\D|$)/.exec(s.replace(y[0], ' '))
  return Number(y[0]) + (m ? (Number(m[1]) - 1) / 12 : 0)
}
const span = (e: ProfileExperience): [number, number] => [when(e.start, Infinity), when(e.end, Infinity)]
const overlaps = ([s1, e1]: [number, number], [s2, e2]: [number, number], slack = 0) => s1 < e2 + slack && s2 < e1 + slack

/**
 * Two roles held side by side: they overlap and started within half a year
 * of each other (Ron, 27.11: support alongside customer success at the
 * start). Roles that follow one another (2023-2025, then 2025-2026) don't.
 */
function parallel(a: ProfileExperience, b: ProfileExperience): boolean {
  const sa = span(a), sb = span(b)
  if ([sa[0], sb[0]].some(Number.isNaN)) return false
  return overlaps(sa, sb) && Math.abs(sa[0] - sb[0]) <= 0.5
}

export interface RoleStep { role: ProfileExperience; parallel: ProfileExperience[] }
export interface CompanyEntry { company: string; start: string; end: string; steps: RoleStep[] }

const norm = (c: string) => c.trim().toLowerCase()

/**
 * Jobs (not army service) as one entry per stint at a company, newest first.
 * A company's roles join one entry even when another line of the timeline
 * falls between them (a course taken while employed), as long as the
 * stint is continuous (no gap of more than a year).
 */
export function companyEntries(experience: ProfileExperience[]): CompanyEntry[] {
  const groups: { company: string; roles: ProfileExperience[]; lo: number; hi: number; start: string; end: string }[] = []
  for (const e of experience) {
    if (isMilitary(e)) continue
    const [s, en] = span(e)
    const g = e.company.trim()
      ? groups.find(x => norm(x.company) === norm(e.company) && !Number.isNaN(s) && overlaps([x.lo, x.hi], [s, en], 1))
      : undefined
    if (!g) { groups.push({ company: e.company, roles: [e], lo: s, hi: en, start: e.start, end: e.end }); continue }
    g.roles.push(e)
    if (s < g.lo) { g.lo = s; g.start = e.start }
    if (en > g.hi) { g.hi = en; g.end = e.end }
  }
  return groups.map(g => {
    const steps: RoleStep[] = []
    const ordered = [...g.roles].sort((a, b) => (span(b)[0] || 0) - (span(a)[0] || 0))
    for (const r of ordered) {
      const step = steps.find(st => parallel(st.role, r))
      if (step) step.parallel.push(r)
      else steps.push({ role: r, parallel: [] })
    }
    // The role a group is named for is the one held longest (latest end,
    // then earliest start); the others are listed beside it.
    const lead = (st: RoleStep): RoleStep => {
      const all = [st.role, ...st.parallel]
      const main = [...all].sort((a, b) => (span(b)[1] - span(a)[1]) || (span(a)[0] - span(b)[0]))[0]
      return { role: main, parallel: all.filter(x => x !== main) }
    }
    return { company: g.company, start: g.start, end: g.end, steps: steps.map(lead) }
  })
}

export const militaryService = (experience: ProfileExperience[]) => experience.filter(isMilitary)

/** The role for the card's headline: the newest job, current or the last one held. */
export function latestRole(experience: ProfileExperience[]): ProfileExperience | null {
  return experience.find(e => !isMilitary(e)) ?? null
}

/** A period for display, in years: "2023–2026", "2026–present". */
export function periodYears(start: string, end: string, present: string): string {
  const y = (s: string) => /(19|20)\d{2}/.exec(s)?.[0] ?? ''
  const a = y(start)
  const b = !end.trim() || /present|current|now|היום|כיום/i.test(end) ? present : (y(end) || end)
  if (!a) return b
  return a === b ? a : `${a}–${b}`
}

// ── How well Ariel knows you ──────────────────────────────────────────────────
//
// Four topics, each 0-100, and the overall score is their average. Every
// check is listed so the page can show what Ariel knows and what is missing.

export type TopicId = 'exp' | 'cap' | 'mob' | 'edu'
export interface Check { key: string; ok: boolean; n?: number; of?: number }
export interface Topic { id: TopicId; value: number; checks: Check[] }

export interface KnowledgeInput {
  view:     ProfileView
  entities: CapabilityEntity[]
  roles:    RoleSeniorityItem[]
  about:    AboutAnswers | null
}

export function knowledgeTopics({ view, entities, roles, about }: KnowledgeInput): { topics: Topic[]; overall: number } {
  // Experience: 70% for roles with dates and a description, 30% for roles
  // Ariel has talked through with the user (written in conversation).
  const jobs = view.experience.filter(e => !isMilitary(e))
  const described = jobs.filter(j => j.start.trim() && j.details.trim()).length
  const talked = jobs.filter(j => j.source === 'ariel').length
  const exp: Topic = {
    id: 'exp',
    value: jobs.length ? 70 * described / jobs.length + 30 * talked / jobs.length : 0,
    checks: [
      { key: 'exp_described', ok: jobs.length > 0 && described === jobs.length, n: described, of: jobs.length },
      { key: 'exp_talked', ok: jobs.length > 0 && talked === jobs.length, n: talked, of: jobs.length },
    ],
  }

  // Capabilities: the average of the ten strongest, so marginal ones the CV
  // happened to mention don't pull the score down (note 26).
  const top = [...entities].map(e => e.score).sort((a, b) => b - a).slice(0, 10)
  const verified = entities.filter(e => e.verification_level === 'VERIFIED_MANUAL').length
  const cap: Topic = {
    id: 'cap',
    value: top.length ? top.reduce((s, x) => s + x, 0) / top.length : 0,
    checks: [
      { key: 'cap_found', ok: entities.length > 0, n: entities.length },
      { key: 'cap_verified', ok: verified > 0, n: verified },
    ],
  }

  // Mobility and preferences: six things, equal weight. (Salary isn't
  // collected anywhere yet, so it isn't counted against anyone.)
  const range = about
    ? (about.search_mode === 'regions' ? about.locations.length > 0 : about.radius_km != null)
    : false
  const mobChecks: Check[] = [
    { key: 'mob_home', ok: !!(about?.home_city || about?.home_abroad) },
    { key: 'mob_roles', ok: roles.length > 0, n: roles.length },
    { key: 'mob_range', ok: range },
    { key: 'mob_work_model', ok: !!about?.work_environment },
    { key: 'mob_career_change', ok: !!about?.career_change },
    { key: 'mob_company', ok: !!about?.company_type },
  ]
  const mob: Topic = { id: 'mob', value: 100 * mobChecks.filter(c => c.ok).length / mobChecks.length, checks: mobChecks }

  // Education, army and languages: four things, equal weight.
  const eduChecks: Check[] = [
    { key: 'edu_degree', ok: view.education.length > 0 },
    { key: 'edu_more', ok: view.education.length > 1 },
    { key: 'edu_military', ok: militaryService(view.experience).length > 0 },
    { key: 'edu_languages', ok: view.languages.length > 0 },
  ]
  const edu: Topic = { id: 'edu', value: 25 * eduChecks.filter(c => c.ok).length, checks: eduChecks }

  const topics = [exp, cap, mob, edu].map(t => ({ ...t, value: round1(t.value) }))
  return { topics, overall: round1(topics.reduce((s, t) => s + t.value, 0) / topics.length) }
}
