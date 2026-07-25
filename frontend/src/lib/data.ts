import { TOKENS } from './tokens'

export type ReasonKind = 'skill' | 'exp' | 'loc' | 'neg'

export interface Reason {
  kind: ReasonKind
  label: string
}

export interface Job {
  id: string
  title: string
  company: string
  location: string
  postedAt: string
  postedRank: number
  score: number
  isNew?: boolean
  reasons: Reason[]
  whyRon?: string | null
}

export interface Application {
  id: string
  title: string
  company: string
  stage: 'submitted' | 'viewed' | 'screening' | 'interview' | 'offer' | 'rejected'
  when: string
}

export interface AgentInfo {
  name: string
  detail: string
  tone: 'success' | 'muted' | 'warn' | 'danger'
  accent: string
}

// ── Preference enumerations ────────────────────────────────────────────────────

/** Work arrangement filter — empty array means "all modes accepted" */
export type WorkMode     = 'remote' | 'hybrid' | 'onsite'

/** Israeli geographic regions — empty array means "all regions" */
export type Region       = 'tel-aviv' | 'central' | 'sharon' | 'haifa' | 'jerusalem' | 'south'

/** Company maturity filter — empty array means "all stages" */
export type CompanyStage = 'startup' | 'growth' | 'enterprise'

/** Notification delivery cadence */
export type Cadence      = 'immediate' | 'daily' | 'weekly' | 'off'

/** Maximum search radius from a city centre; 0 = unlimited */
export type RadiusKm     = 0 | 10 | 20 | 40

export interface AutomationSettings {
  // ── Match filters (Matches page only — never touch Analytics) ─────────────
  minScore:      number          // 0 = no minimum; 1–100 = hard floor
  workModes:     WorkMode[]      // [] = show all modes
  regions:       Region[]        // [] = show all regions
  radiusKm:      RadiusKm        // 0 = unlimited
  companyStages: CompanyStage[]  // [] = show all stages

  // ── Notifications ──────────────────────────────────────────────────────────
  cadence: Cadence
}

export const JOBS: Job[] = [
  {
    id: 'j1',
    title: 'Senior Product Designer, Platform',
    company: 'Linear Orbit',
    location: 'San Francisco · Remote OK',
    postedAt: '2h ago',
    postedRank: 10,
    score: 94,
    isNew: true,
    reasons: [
      { kind: 'skill', label: 'Design systems · 7y' },
      { kind: 'exp',   label: 'Platform UX' },
      { kind: 'loc',   label: 'Remote-friendly' },
    ],
  },
  {
    id: 'j2',
    title: 'Principal Designer, AI Products',
    company: 'Harbor AI',
    location: 'Remote, US',
    postedAt: '4h ago',
    postedRank: 9,
    score: 91,
    isNew: true,
    reasons: [
      { kind: 'skill', label: 'AI product UX' },
      { kind: 'skill', label: 'Prototyping in code' },
      { kind: 'exp',   label: '10+ yrs leadership' },
      { kind: 'loc',   label: 'Fully remote' },
    ],
  },
  {
    id: 'j3',
    title: 'Staff UX Researcher',
    company: 'Northwind Health',
    location: 'New York — Hybrid',
    postedAt: '6h ago',
    postedRank: 8,
    score: 88,
    isNew: true,
    reasons: [
      { kind: 'skill', label: 'Mixed-methods research' },
      { kind: 'exp',   label: 'Healthcare · 4y' },
      { kind: 'neg',   label: 'On-site 3d/wk' },
    ],
  },
  {
    id: 'j4',
    title: 'Senior Designer, Growth',
    company: 'Fernway',
    location: 'Austin · Remote OK',
    postedAt: '1d ago',
    postedRank: 7,
    score: 82,
    reasons: [
      { kind: 'skill', label: 'Growth experimentation' },
      { kind: 'exp',   label: 'B2C marketplace' },
    ],
  },
  {
    id: 'j5',
    title: 'Lead Designer, Design Systems',
    company: 'Quillford',
    location: 'Remote, Americas',
    postedAt: '1d ago',
    postedRank: 6,
    score: 79,
    reasons: [
      { kind: 'skill', label: 'Tokens & theming' },
      { kind: 'exp',   label: 'Multi-brand systems' },
    ],
  },
  {
    id: 'j6',
    title: 'Product Designer II',
    company: 'Pallet & Co.',
    location: 'Remote, EU',
    postedAt: '2d ago',
    postedRank: 4,
    score: 71,
    reasons: [
      { kind: 'skill', label: 'SaaS dashboards' },
      { kind: 'neg',   label: 'EU hours' },
    ],
  },
]

export const APPS: Application[] = [
  { id: 'a1', title: 'Senior Product Designer, Growth', company: 'Cedar Labs',  stage: 'interview', when: 'Today'      },
  { id: 'a2', title: 'Lead Designer, Mobile',           company: 'Kite & Kin',  stage: 'screening', when: 'Today'      },
  { id: 'a3', title: 'Principal Designer, Platform',    company: 'Rivet Works', stage: 'offer',     when: '2 days ago' },
  { id: 'a4', title: 'Sr. UX Designer, Enterprise',     company: 'Marbletown',  stage: 'viewed',    when: 'Yesterday'  },
  { id: 'a5', title: 'Staff Product Designer',          company: 'Northfield',  stage: 'submitted', when: 'Yesterday'  },
  { id: 'a6', title: 'Senior Designer, Payments',       company: 'Tidecaster',  stage: 'rejected',  when: '3 days ago' },
]

export const AGENTS: AgentInfo[] = [
  { name: 'Scraper',             detail: 'Fetches raw job data from source URLs',              tone: 'success', accent: TOKENS.color.primary },
  { name: 'Sourcing Specialist', detail: 'Analyzes role fit against candidate profile',        tone: 'success', accent: TOKENS.color.violet  },
  { name: 'Content Strategist',  detail: 'Drafts tailored cover letters and content',          tone: 'success', accent: TOKENS.color.success  },
  { name: 'Quality Guard',       detail: 'Verifies quality and flags issues before submission', tone: 'muted',   accent: TOKENS.color.warn    },
]

export const DEFAULT_SETTINGS: AutomationSettings = {
  // Match filters
  minScore:      0,
  workModes:     [],
  regions:       [],
  radiusKm:      0,
  companyStages: [],

  // Notifications
  cadence: 'daily',
}
