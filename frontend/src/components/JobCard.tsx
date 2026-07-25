'use client'
import { useState, useCallback, useEffect, useRef } from 'react'
import type { ApiFeedJob, JobSourceType, ReasonKind } from '@/lib/apiTypes'
import { markJobApplied, refreshFeedScores, fetchJobJd, ensureFreshToken, getAuthHeaders } from '@/lib/api'
import { getScoreBand as scoreBand } from '@/lib/scoreBand'
import { ProbeModal, type ProbeState } from './TrustDashboard'

const IS_DEV = process.env.NODE_ENV === 'development'
import { SkillIcon, ExpIcon, LocIcon, WarnIcon } from './icons'
import { OutreachModal }    from './OutreachModal'
import { DirectPitchModal } from './DirectPitchModal'
import { InterviewSimulatorModal } from './InterviewSimulatorModal'
import { AtsKeywordsPanel } from './AtsKeywordsPanel'
import { SkillsGapPanel }   from './SkillsGapPanel'

// ── Chevron ───────────────────────────────────────────────────────────────────

function ChevronDown({ s = 14, flipped = false }: { s?: number; flipped?: boolean }) {
  return (
    <svg
      width={s} height={s} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"
      style={{ transition: 'transform 250ms ease', transform: flipped ? 'rotate(180deg)' : 'none' }}
    >
      <polyline points="6 9 12 15 18 9" />
    </svg>
  )
}

// ── External link / LinkedIn icons ────────────────────────────────────────────

function ExternalLinkIcon({ s = 12 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
    >
      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
      <polyline points="15 3 21 3 21 9" />
      <line x1="10" y1="14" x2="21" y2="3" />
    </svg>
  )
}

function LinkedInIcon({ s = 13 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="currentColor" aria-label="LinkedIn">
      <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 0 1-2.063-2.065 2.064 2.064 0 1 1 2.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z" />
    </svg>
  )
}

// RTL detection no longer needed due to dir="auto"

// ── Workplace type from the unstructured location string ─────────────────────
// Returns null when the type is already spelled out inside the location text
// (avoids "Tel Aviv · Hybrid · Hybrid") or when no location exists at all.

function deriveWorkplaceType(location: string | null | undefined): string | null {
  const loc = (location ?? '').toLowerCase()
  if (!loc.trim()) return null
  if (/(remote|wfh|work from home)/.test(loc)) return null   // already visible in location
  if (loc.includes('hybrid')) return null                    // already visible in location
  return 'On-site'
}

// ── Posted-at formatting ──────────────────────────────────────────────────────
// < 7 days old → relative ("2d ago"); ≥ 7 days → exact date ("Jul 4").
// Falls back to the backend-provided string; never fabricates "just now".

function formatPostedAt(createdAt: string | null, postedAt: string): string | null {
  if (createdAt) {
    const d = new Date(createdAt)
    if (!isNaN(d.getTime())) {
      const diffMs = Math.max(0, Date.now() - d.getTime())
      const diffH  = Math.floor(diffMs / 3_600_000)
      const diffD  = Math.floor(diffMs / 86_400_000)
      if (diffD >= 7) {
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
      }
      if (diffD >= 1) return `${diffD}d ago`
      if (diffH >= 1) return `${diffH}h ago`
      return `${Math.max(1, Math.floor(diffMs / 60_000))}m ago`
    }
  }
  const p = (postedAt ?? '').trim()
  if (!p || /just now/i.test(p)) return null
  return p
}

// ── Strength badge ────────────────────────────────────────────────────────────
// Subtle highlight chips under the metadata row — the user's top strengths for
// this role (source advantage + positive skill/experience reason tags).

function StrengthBadge({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center h-[18px] px-1.5 rounded-md text-[10.5px] font-medium bg-slate-50 text-slate-500 border border-slate-100">
      {label}
    </span>
  )
}

// ── RTL-aware bullet & paragraph atoms ───────────────────────────────────────

function BulletItem({ text }: { text: string }) {
  return (
    <li
      dir="auto"
      className="flex items-start gap-2 text-[12px] leading-relaxed text-slate-600 [unicode-bidi:plaintext] text-start"
    >
      <span className="mt-[6px] shrink-0 h-[5px] w-[5px] rounded-full bg-slate-400" />
      <span className="flex-1" dir="auto">{text}</span>
    </li>
  )
}

function ParagraphBlock({ text, className = '' }: { text: string; className?: string }) {
  return (
    <p
      dir="auto"
      className={`text-[12px] leading-relaxed text-slate-600 [unicode-bidi:plaintext] text-start ${className}`}
    >
      {text}
    </p>
  )
}

// ── JD formatter (unchanged) ──────────────────────────────────────────────────

const _EXPLICIT_BULLET = /^\s*[•\-\*–◦▪▸→◆]\s+/
const _NUMBER_BULLET   = /^\s*\d{1,2}[.)]\s+/
const _EM_DASH_BULLET  = /^\s*—\s+\S/

const _ACTION_VERBS_LINE = new RegExp(
  '^(develop|build|work|manage|lead|create|ensure|define|collaborate|design|analyze|' +
  'implement|support|drive|own|partner|coordinate|conduct|provide|identify|execute|' +
  'maintain|evaluate|monitor|deliver|contribute|prepare|write|review|oversee|' +
  'facilitate|research|optimize|scale|launch|engage|improve|track|prioritize|' +
  'establish|help|assist|communicate|report|gather|test|validate|deploy|integrate|' +
  'transform|shape|influence|architect|spec|ship)\\s',
  'i'
)

const _VERB_IN_TEXT = new RegExp(
  '\\b(develop|build|work|manage|lead|create|ensure|define|collaborate|design|analyze|' +
  'implement|support|drive|coordinate|conduct|provide|identify|execute|maintain|evaluate|' +
  'monitor|deliver|contribute|write|review|research|optimize|deploy|integrate|validate|' +
  'prioritize|establish|communicate|gather|test|launch|engage|improve|track)\\b',
  'gi'
)

const _TECH_TERM = /\b(SQL|Python|JavaScript|TypeScript|JS|TS|React|Node|AWS|GCP|Azure|API|REST|JSON|HTML|CSS|Git|Docker|Kubernetes|CI|CD|ML|AI|NLP|SaaS|B2B|KPI|OKR|CRM|ERP|MBA|BSc|MSc|Jira|Figma|Sketch|Tableau|Looker|dbt|Snowflake|Redshift|Spark|Kafka|Redis|Postgres|MySQL|MongoDB|GraphQL|gRPC|Terraform|Agile|Scrum|Kanban|[A-Z]{2,6})\b/g

const _HEADING_KW = new RegExp(
  '^(about|requirements?|qualifications?|responsibilities|what you[\\u2019\']?ll|what we[\\u2019\']?re|' +
  'who you are|nice to have|preferred|skills|experience|education|benefits?|compensation|' +
  'the role|your role|about us|about the company|you will|you have|you bring|the ideal|' +
  'minimum|basic|additional|key|core|primary|essential|overview|summary|' +
  'job description|responsibilities and|position overview|role overview|' +
  'we are looking|we[\\u2019\']re looking|what you[\\u2019\']ll|perks|culture|mission)\\b',
  'i'
)

function isBulletLine(l: string): boolean {
  return _EXPLICIT_BULLET.test(l) || _NUMBER_BULLET.test(l) || _EM_DASH_BULLET.test(l)
}
function stripBullet(l: string): string {
  return l.replace(_EXPLICIT_BULLET, '').replace(_NUMBER_BULLET, '').replace(/^\s*—\s+/, '').trim()
}
function isVerbLine(l: string): boolean {
  const t = l.trim()
  return t.length > 10 && t.length < 180 && _ACTION_VERBS_LINE.test(t)
}
function isHeadingLine(l: string): boolean {
  const t = l.trim()
  if (!t || t.length > 90) return false
  if (t.endsWith(':') && t.length < 60) return true
  if (_HEADING_KW.test(t) && !t.includes('. ')) return true
  if (t === t.toUpperCase() && t.length >= 4 && t.length < 50 && /^[A-Z\s&/]+$/.test(t)) return true
  return false
}
function trySplitParagraph(text: string): string[] | null {
  if (text.length < 100) return null
  const techHits = (text.match(_TECH_TERM) ?? []).length
  _VERB_IN_TEXT.lastIndex = 0
  const verbHits = (text.match(_VERB_IN_TEXT) ?? []).length
  if (techHits + verbHits < 3) return null
  const semiParts = text.split(/;\s+/).map(s => s.trim()).filter(s => s.length > 5)
  if (semiParts.length >= 2) return semiParts
  const commaParts = text.split(/,\s+/).map(s => s.trim()).filter(s => s.length > 8)
  if (commaParts.length >= 3) {
    _VERB_IN_TEXT.lastIndex = 0
    const qualifying = commaParts.filter(p =>
      (p.match(_TECH_TERM) ?? []).length > 0 || _VERB_IN_TEXT.test(p)
    )
    _VERB_IN_TEXT.lastIndex = 0
    if (qualifying.length / commaParts.length >= 0.6) return commaParts
  }
  return null
}
function renderBulletList(items: string[], bkey: number): React.ReactNode {
  return (
    <ul key={bkey} className="space-y-1 mb-3">
      {items.map((item, j) => <BulletItem key={j} text={item} />)}
    </ul>
  )
}
function formatJdText(text: string): React.ReactNode {
  let src = text.trim().replace(/\r\n/g, '\n').replace(/\r/g, '\n')
  const nlCount   = (src.match(/\n/g) ?? []).length
  const semiCount = (src.match(/;\s/g) ?? []).length
  if (nlCount < 4 && semiCount >= 3) src = src.replace(/;\s*/g, '\n')
  const lines  = src.split('\n')
  const blocks: React.ReactNode[] = []
  let   i = 0, bkey = 0
  while (i < lines.length) {
    const line = lines[i], trimmed = line.trim()
    if (!trimmed) { i++; continue }
    if (isHeadingLine(line)) {
      blocks.push(
        <p key={bkey++} className="text-[10.5px] font-bold tracking-widest uppercase text-slate-400 mt-4 mb-1 first:mt-0">
          {trimmed.replace(/:$/, '')}
        </p>
      )
      i++; continue
    }
    if (isBulletLine(line)) {
      const items: string[] = []
      while (i < lines.length) {
        const l = lines[i]
        if (isBulletLine(l)) { items.push(stripBullet(l)); i++ }
        else if (!l.trim()) {
          const next = lines.slice(i + 1).find(x => x.trim())
          if (next && isBulletLine(next)) { i++; continue }
          break
        } else break
      }
      if (items.length > 0) blocks.push(renderBulletList(items, bkey++))
      continue
    }
    if (isVerbLine(line)) {
      const items: string[] = []
      while (i < lines.length) {
        const l = lines[i]
        if (isVerbLine(l) && !isHeadingLine(l)) { items.push(l.trim()); i++ }
        else if (!l.trim()) {
          const next = lines.slice(i + 1).find(x => x.trim())
          if (next && isVerbLine(next) && !isHeadingLine(next)) { i++; continue }
          break
        } else break
      }
      if (items.length > 0) blocks.push(renderBulletList(items, bkey++))
      continue
    }
    const paraLines: string[] = []
    while (i < lines.length && lines[i].trim() && !isBulletLine(lines[i]) && !isHeadingLine(lines[i]) && !isVerbLine(lines[i])) {
      paraLines.push(lines[i].trim()); i++
    }
    const para = paraLines.join(' ')
    if (!para) continue
    const splitItems = trySplitParagraph(para)
    if (splitItems) blocks.push(renderBulletList(splitItems, bkey++))
    else blocks.push(<ParagraphBlock key={bkey++} text={para} className="mb-3" />)
  }
  return blocks.length > 0 ? <>{blocks}</> : <ParagraphBlock text={text.trim()} />
}

// ── Source badge ──────────────────────────────────────────────────────────────

const SOURCE_LABELS: Record<JobSourceType, string> = {
  linkedin:     'LinkedIn',
  company_site: 'Company Site',
  other:        'Other',
}
// Tone pairs use the Tailwind 50/700 scale — same recipe as the "Strong Match"
// badge (teal-50/teal-700), so every badge shares one visual grammar and clears
// WCAG AA contrast on its subtle background.
const SOURCE_STYLES: Record<JobSourceType, string> = {
  linkedin:     'bg-blue-50 text-blue-700',
  company_site: 'bg-emerald-50 text-emerald-700',
  other:        'bg-slate-100 text-slate-600',
}
function SourceBadge({ type }: { type: JobSourceType }) {
  return (
    <span
      className={`inline-flex items-center h-[17px] px-1.5 rounded text-[10px] font-semibold tracking-wide ${SOURCE_STYLES[type]}`}
    >
      {SOURCE_LABELS[type]}
    </span>
  )
}

function DirectApplyBadge() {
  return (
    <span
      className="inline-flex items-center gap-0.5 h-[17px] px-1.5 rounded text-[10px] font-semibold bg-emerald-100 text-emerald-800"
      title="Apply directly on the company's careers page"
    >
      ⚡ Direct
    </span>
  )
}

function BulkImportBadge() {
  return (
    <span
      className="inline-flex items-center h-[17px] px-1.5 rounded text-[10px] font-semibold bg-slate-100 text-slate-600"
      title="Imported via the LinkedIn Bulk Import pipeline, not a live scraper run"
    >
      Bulk Import
    </span>
  )
}

// ── Gap / reason tags ─────────────────────────────────────────────────────────

const GAP_TONES: Record<ReasonKind, { cls: string; Icon: (p: { s?: number }) => JSX.Element }> = {
  skill: { cls: 'bg-emerald-50 text-emerald-700', Icon: SkillIcon },
  exp:   { cls: 'bg-teal-50 text-teal-700',       Icon: ExpIcon   },
  loc:   { cls: 'bg-violet-50 text-violet-700',   Icon: LocIcon   },
  neg:   { cls: 'bg-ja-dangerSubtle text-red-700', Icon: WarnIcon  },
}
function GapTag({ kind, label }: { kind: ReasonKind; label: string }) {
  const t = GAP_TONES[kind] ?? GAP_TONES.neg
  const { Icon } = t
  return (
    <span
      className={`inline-flex items-center gap-1 h-5 px-1.5 rounded-md text-[11px] font-medium ${t.cls}`}
    >
      <Icon s={10} />
      {label}
    </span>
  )
}

// ── Action button ─────────────────────────────────────────────────────────────

interface ActionBtnProps {
  onClick:    (e: React.MouseEvent) => void
  className?: string
  style?:     React.CSSProperties
  children:   React.ReactNode
  title?:     string
  disabled?:  boolean
}
function ActionBtn({ onClick, className = '', style, children, title, disabled }: ActionBtnProps) {
  return (
    <button
      onClick={onClick}
      title={title}
      disabled={disabled}
      className={`inline-flex items-center justify-center gap-1.5 h-8 px-3 rounded-lg text-[12px] font-medium transition active:scale-[0.97] disabled:opacity-40 disabled:pointer-events-none ${className}`}
      style={style}
    >
      {children}
    </button>
  )
}

// ── Structured JD renderer ───────────────────────────────────────────────────
//
// Parses the LLM-produced JSON string from jd_structured and renders each
// section with appropriate headings and bullet lists.
//
// Returns { node, ok } so the caller can fall back to raw-text rendering when
// parsing fails rather than silently rendering nothing.

interface StructuredJd {
  company_details:  string
  role_overview:    string
  responsibilities: string[]
  requirements:     string[]
  advantages:       string[]
  additional_info:  string
}

function parseStructuredJd(jsonStr: string): StructuredJd | null {
  try {
    const parsed = JSON.parse(jsonStr)
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return parsed as StructuredJd
    }
  } catch { /* fall through */ }
  return null
}

const STRUCTURED_SECTION_LABELS: { key: keyof StructuredJd; label: string }[] = [
  { key: 'company_details',  label: 'About the Company'   },
  { key: 'role_overview',    label: 'Role Overview'        },
  { key: 'responsibilities', label: 'Responsibilities'     },
  { key: 'requirements',     label: 'Requirements'         },
  { key: 'advantages',       label: 'Nice to Have'         },
  { key: 'additional_info',  label: 'Additional Info'      },
]

function StructuredJdPanel({ parsed }: { parsed: StructuredJd }) {
  const sections = STRUCTURED_SECTION_LABELS.filter(({ key }) => {
    const val = parsed[key]
    return Array.isArray(val) ? val.length > 0 : Boolean(val)
  })

  if (sections.length === 0) return null

  return (
    <div className="rounded-lg bg-white border border-slate-200 divide-y divide-slate-100"
      style={{ boxShadow: 'inset 0 2px 4px rgba(15,23,42,0.04)' }}
    >
      {sections.map(({ key, label }) => {
        const val = parsed[key]
        return (
          <div key={key} className="px-4 py-3">
            <p className="text-[10.5px] font-bold tracking-widest uppercase text-slate-400 mb-2">
              {label}
            </p>
            {Array.isArray(val) ? (
              <ul className="space-y-1.5">
                {(val as string[]).map((item, i) => (
                  <li key={i} dir="auto" className="flex items-start gap-2 text-[12.5px] leading-relaxed text-slate-700 [unicode-bidi:plaintext] text-start">
                    <span className="mt-[7px] shrink-0 h-[4px] w-[4px] rounded-full bg-slate-400" />
                    <span className="flex-1" dir="auto">{item}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p dir="auto" className="text-[12.5px] leading-relaxed text-slate-700 [unicode-bidi:plaintext] text-start">{val as string}</p>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ── JD panel ──────────────────────────────────────────────────────────────────

const JD_COLLAPSE_THRESHOLD = 900

interface JdPanelProps {
  text:           string
  expanded:       boolean
  onToggleExpand: () => void
  isHebrewLocale?: boolean
}
function JdPanel({ text, expanded, onToggleExpand, isHebrewLocale = false }: JdPanelProps) {
  const isLong   = text.length > JD_COLLAPSE_THRESHOLD
  return (
    <div>
      <div className="relative">
        <div
          className="overflow-y-auto rounded-lg bg-white border border-slate-200 p-4"
          dir="auto"
          style={{
            boxShadow: 'inset 0 2px 4px rgba(15,23,42,0.04)',
            maxHeight: isLong ? (expanded ? '60vh' : '16rem') : undefined,
            transition: 'max-height 300ms ease',
          }}
        >
          {formatJdText(text)}
        </div>
        {isLong && !expanded && (
          <div
            className="absolute bottom-0 left-0 right-0 h-12 pointer-events-none rounded-b-lg"
            style={{ background: 'linear-gradient(to bottom, transparent, white)' }}
          />
        )}
      </div>
      {isLong && (
        <button
          onClick={onToggleExpand}
          className="mt-1.5 inline-flex items-center gap-1 text-[11.5px] font-medium text-teal-600 hover:text-teal-800 transition"
        >
          <ChevronDown s={11} flipped={expanded} />
          {expanded ? 'Collapse' : 'See more'}
        </button>
      )}
    </div>
  )
}

// ── Agent Analysis box ────────────────────────────────────────────────────────
//
// Three visual states:
//   pending  — score_is_proxy=true OR why_ron absent: animated skeleton
//   ready    — substantive why_ron text: rendered analysis
//   (dev)    — Retry button appears in both pending states when IS_DEV=true

function AnalysisSkeleton() {
  return (
    <div
      className="rounded-lg px-4 py-4 space-y-2.5 bg-slate-50 border border-slate-200"
      aria-busy="true"
      aria-label="Generating analysis"
    >
      <div className="flex items-center gap-2 mb-1">
        <span className="relative flex h-2 w-2">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-50 bg-ja-primary" />
          <span className="relative inline-flex rounded-full h-2 w-2 bg-ja-primary" />
        </span>
        <span className="text-[12px] font-medium text-ja-primary">
          Generating deep insights…
        </span>
      </div>
      {[70, 90, 55].map((w, i) => (
        <div
          key={i}
          className="h-2.5 rounded-full animate-pulse bg-slate-200"
          style={{ width: `${w}%`, animationDelay: `${i * 120}ms` }}
        />
      ))}
    </div>
  )
}

// Mirror of the backend constant — jobs retired after this many failures.
const ENRICHMENT_MAX_FAILURES = 3

function _isSubstantiveText(text: string): boolean {
  // Two conditions only — mirrors is_substantive_analysis() in feed_service.py.
  // The third "core strengths" check was removed because it matched the first
  // line of every valid analysis that uses the required template format
  // ("🟢 Core Strengths:\n• ..."), causing all good analyses to show as skeleton.
  return (
    text.length >= 50 &&
    !/^[^\w]*[\w\s]+:\s*$/.test(text)
  )
}

// Backend sentinel values — must match feed_service.py constants exactly.
const AUTH_WALL_SENTINEL  = '__auth_wall__'

function AnalysisUnavailable() {
  return (
    <div
      className="rounded-lg px-4 py-3 flex items-start gap-3 bg-ja-dangerSubtle border border-red-200"
    >
      <span className="text-[15px] mt-0.5" aria-hidden="true">⚠️</span>
      <div className="flex-1 min-w-0">
        <p className="text-[12.5px] font-semibold text-slate-700 mb-0.5">Manual analysis required</p>
        <p className="text-[12px] text-slate-500 leading-relaxed">
          The scraper couldn&apos;t hydrate this job after {ENRICHMENT_MAX_FAILURES} attempts.
          This is likely a bot-block or expired posting. Open the original listing to review manually.
        </p>
      </div>
    </div>
  )
}

function AnalysisAuthWall() {
  return (
    <div
      className="rounded-lg px-4 py-3 flex items-start gap-3 bg-ja-primarySubtle border border-teal-200"
    >
      <span className="text-[15px] mt-0.5" aria-hidden="true">🔒</span>
      <div className="flex-1 min-w-0">
        <p className="text-[12.5px] font-semibold text-slate-700 mb-0.5">LinkedIn session expired</p>
        <p className="text-[12px] text-slate-500 leading-relaxed">
          The scraper hit a LinkedIn login wall. The <code className="font-mono text-[11px]">li_at</code> cookie
          needs refreshing. Update <code className="font-mono text-[11px]">LINKEDIN_LI_AT</code> in{' '}
          <code className="font-mono text-[11px]">backend/.env</code>, delete the browser profile, and restart
          the server. This job will be retried automatically.
        </p>
      </div>
    </div>
  )
}

// ── Shared tiny spinner (used by both AnalyzeJobButton and ArielInsightButton) ─

function SpinnerTiny({ s = 13 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none"
      style={{ animation: 'spin 0.8s linear infinite', flexShrink: 0 }}
    >
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.5" strokeOpacity="0.2" />
      <path d="M12 3a9 9 0 0 1 9 9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  )
}

// ── Analyze Job Button ────────────────────────────────────────────────────────
//
// Replaces the match score in the collapsed row when jd_text is absent/thin
// (score_is_proxy=true AND jd_text < 300 chars). Clicking triggers the scraper
// for this specific job so the backend can hydrate it and run Phase B scoring.

function AnalyzeJobButton({ jobId }: { jobId: string }) {
  const [state, setState] = useState<'idle' | 'loading' | 'done' | 'error'>('idle')

  async function handleClick(e: React.MouseEvent) {
    e.stopPropagation()
    if (state !== 'idle') return
    setState('loading')
    try {
      await fetchJobJd(jobId)
      setState('done')
    } catch {
      setState('error')
      setTimeout(() => setState('idle'), 3000)
    }
  }

  if (state === 'done') {
    return (
      <span className="text-[11px] font-medium text-teal-600 shrink-0">
        ✓ Queued
      </span>
    )
  }

  return (
    <button
      onClick={handleClick}
      disabled={state === 'loading'}
      className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg text-[11.5px] font-semibold shrink-0 bg-ja-primarySubtle text-ja-primary border border-teal-200 hover:bg-teal-100 transition active:scale-[0.97] disabled:opacity-50"
    >
      {state === 'loading' ? (
        <><SpinnerTiny s={11} /> Analyzing…</>
      ) : state === 'error' ? (
        <span className="text-red-500">Failed</span>
      ) : (
        <>⚡ Analyze Job</>
      )}
    </button>
  )
}

// ── Ariel Insight Button ─────────────────────────────────────────────────────
//
// Appears when the analysis is ready AND the job has negative reason tags
// (skill/keyword gaps). Clicking launches a STAR probe for the first missing
// skill found in the user's Confidence Matrix.

function ArielInsightButton({
  userId,
  skillName,
}: {
  userId: string
  skillName: string
}) {
  const [loading,    setLoading]    = useState(false)
  const [probeState, setProbeState] = useState<ProbeState | null>(null)
  const [error,      setError]      = useState<string | null>(null)

  async function handleClick() {
    if (loading || !userId) return
    setLoading(true)
    setError(null)
    try {
      // Guard both fetches below against the mount-time token race.
      await ensureFreshToken()
      // 1. Fetch trust entities to find the matching entity_id
      const trustRes = await fetch(`/api/profile/${userId}/trust-score`, {
        headers: getAuthHeaders(),
        cache:   'no-store',
      })
      if (!trustRes.ok) throw new Error(`Trust API: HTTP ${trustRes.status}`)
      const trust = await trustRes.json()
      const entities: Array<{ entity_id: string; name: string; confidence_score: number }> =
        trust.entities ?? []

      // Case-insensitive fuzzy match on skill name
      const needle = skillName.toLowerCase()
      const match  = entities.find(e =>
        e.name.toLowerCase().includes(needle) || needle.includes(e.name.toLowerCase())
      )
      if (!match) throw new Error(`No entity found for "${skillName}". Upload CV to add it.`)
      if (match.confidence_score >= 70) throw new Error(`"${match.name}" already has high confidence (${match.confidence_score.toFixed(0)}).`)

      // 2. Start the probe
      const probeRes = await fetch('/api/ariel/probe/start', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body:    JSON.stringify({ entity_id: match.entity_id }),
      })
      if (!probeRes.ok) {
        const body = await probeRes.json().catch(() => ({}))
        throw new Error((body as { detail?: string }).detail ?? `HTTP ${probeRes.status}`)
      }
      const data = await probeRes.json()
      setProbeState({
        session_id:     data.session_id,
        entity_id:      data.entity_id,
        entity_name:    data.entity_name,
        turn:           1,
        question:       data.question,
        answers:        {},
        done:           false,
        flag_type:      null,
        new_confidence: null,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start probe.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <div className="flex items-center gap-2 flex-wrap mt-2">
        <button
          onClick={handleClick}
          disabled={loading}
          className="inline-flex items-center gap-1.5 h-7 px-3 rounded-lg text-[11.5px] font-semibold bg-ja-primarySubtle text-ja-primary border border-teal-200 hover:bg-teal-100 transition active:scale-[0.97] disabled:opacity-50"
          title={`Strengthen your "${skillName}" evidence with Ariel`}
        >
          {loading ? <SpinnerTiny s={11} /> : <span aria-hidden="true">⚡</span>}
          Ariel Insight: {skillName}
        </button>
        {error && (
          <span className="text-[11px] text-amber-600">{error}</span>
        )}
      </div>
      {probeState && (
        <ProbeModal
          probe={probeState}
          onClose={() => setProbeState(null)}
          onDone={() => setProbeState(null)}
        />
      )}
    </>
  )
}

function AgentAnalysisBox({ job, userId }: { job: ApiFeedJob; userId?: string }) {
  const raw           = (job.why_ron ?? '').trim()
  const analysisReady = _isSubstantiveText(raw) && !job.score_is_proxy
  const hardFailed    = (job.enrichment_failures ?? 0) >= ENRICHMENT_MAX_FAILURES
  const isAuthWall    = job.status === 'auth_wall'

  // Detect skill gaps from structured reason tags (kind === 'neg')
  const negReasons = job.reasons.filter(r => r.kind === 'neg')

  return (
    <div>
      <div className="flex items-center gap-1.5 mb-2">
        <span aria-hidden="true" className="h-2 w-2 rounded-full bg-violet-500 shrink-0" />
        <span className="text-[10.5px] font-bold uppercase tracking-widest text-slate-400">
          Ariel&apos;s Analysis
        </span>
        {IS_DEV && !analysisReady && !hardFailed && !isAuthWall && (
          <span className="ml-auto text-[10px] text-amber-600 font-medium">
            [DEV] enrichment pending — check server logs
          </span>
        )}
      </div>

      {analysisReady ? (
        <>
          {/* Generated-content marker (Meridian V2 §6.1) — amethyst left border + bg-ja-aiSubtle: Ariel wrote this */}
          <div
            className="rounded-lg px-4 py-3 bg-ja-aiSubtle border border-l-2 border-slate-200 border-l-ja-ai"
          >
            <p dir="auto" className="text-[13px] text-slate-600 leading-relaxed max-w-3xl [unicode-bidi:plaintext] text-start">
              {raw}
            </p>
          </div>
          {/* Ariel Insight: one button per negative reason, shown when userId available */}
          {userId && negReasons.length > 0 && (
            <div className="space-y-1">
              {negReasons.map(r => (
                <ArielInsightButton key={r.label} userId={userId} skillName={r.label} />
              ))}
            </div>
          )}
        </>
      ) : isAuthWall ? (
        <AnalysisAuthWall />
      ) : hardFailed ? (
        <AnalysisUnavailable />
      ) : (
        <AnalysisSkeleton />
      )}
    </div>
  )
}

// ── JobCard ───────────────────────────────────────────────────────────────────
//
// UX Pattern: Accordion with clickable compact row.
//
// COLLAPSED (default):
//   Score ring · Title · Company · Location · Badges · Reason tags · Chevron
//   → The entire row is the click target. No action buttons visible.
//     Users scan the list quickly with zero visual noise.
//
// EXPANDED (on click):
//   ① AI Analysis box  — why_ron first; highest decision-relevance per word.
//   ② Action bar       — all CTAs appear only after the user signals intent.
//   ③ Job description  — full formatted JD; fetched inline if not yet stored.
//   ④ ATS keyword gap  — power-user detail, collapsed within the panel.
//
// Design rationale:
//   • Removing buttons from the collapsed row eliminates "button soup" across
//     a list of 50+ cards. Users scan title → score → tags to decide interest;
//     only then do they need actions.
//   • "Why Ron" is the most decision-relevant sentence the AI produces. Putting
//     it at the top of the expanded state gives it the prominence it deserves.
//   • Source link lives in the action bar (not a separate row) to reduce chrome.
//   • Smooth accordion animation (CSS grid 0fr → 1fr) avoids abrupt layout jump.

export interface JobCardProps {
  job:              ApiFeedJob
  userId?:          string
  isTopFit?:        boolean
  belowThreshold?:  boolean
  initialExpanded?: boolean
  onSkip:           (id: string) => void
  onSave:           (id: string) => void
  onTailorCV:       (job: ApiFeedJob) => void
  onInteractionChange?: (jobId: string, active: boolean) => void
  onMarkApplied?:   (jobId: string) => void
}

export function JobCard({
  job, userId, isTopFit = false, belowThreshold = false, initialExpanded = false,
  onSkip, onSave, onTailorCV, onInteractionChange, onMarkApplied,
}: JobCardProps) {
  const [showDetails,      setShowDetails]      = useState(initialExpanded)
  const [jdExpanded,       setJdExpanded]       = useState(false)
  const [showOutreach,     setShowOutreach]     = useState(false)
  const [showPitch,        setShowPitch]        = useState(false)
  const [showInterview,    setShowInterview]    = useState(false)
  const [showAtsPanel,     setShowAtsPanel]     = useState(false)
  const [showSkillsGap,    setShowSkillsGap]    = useState(false)
  const [isMarkingApplied, setIsMarkingApplied] = useState(false)
  // Seed from server state so a refresh doesn't show "Mark Applied" again
  // for a job that's already in the applied/submitted pipeline stage.
  const [markedApplied,    setMarkedApplied]    = useState(
    () => job.status === 'applied'
  )
  const cardRef = useRef<HTMLElement>(null)

  useEffect(() => {
    onInteractionChange?.(job.job_id, showDetails)
  }, [showDetails, job.job_id, onInteractionChange])

  useEffect(() => {
    if (initialExpanded && cardRef.current) {
      setTimeout(() => {
        cardRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }, 100)
    }
  }, [initialExpanded])

  const isDirect           = job.is_direct_application === true || job.source_type === 'company_site'
  const workplaceType      = deriveWorkplaceType(job.location)
  const postedLabel        = formatPostedAt(job.created_at, job.posted_at)
  // Top strengths for this role: source advantage first, then positive
  // skill/experience reason tags (never the negative "neg" kind).
  const strengths: string[] = [
    ...(isDirect ? ['Company Site'] : []),
    ...job.reasons.filter(r => r.kind === 'skill' || r.kind === 'exp').map(r => r.label),
  ].slice(0, 4)
  const isSaved            = job.status === 'saved'
  // Server-authoritative applied state — button must be visible/enabled for
  // any job NOT already in the 'applied' pipeline stage, regardless of
  // apply_url presence or has_tailored_cv. ('submitted' is an ApplicationRow
  // /CRM-pipeline status, not a JobStatus — it doesn't apply to job.status.)
  const isAlreadyApplied   = job.status === 'applied'
  const isHebrewLocale     = job.locale === 'he'
  const parsedStructuredJd = job.jd_structured ? parseStructuredJd(job.jd_structured) : null
  const hasJD              = Boolean(parsedStructuredJd) || Boolean(job.jd_text && job.jd_text.trim().length > 80)

  const handleMarkApplied = useCallback(async () => {
    if (isMarkingApplied || markedApplied || isAlreadyApplied) return
    setIsMarkingApplied(true)
    try {
      await markJobApplied(job.job_id)
      setMarkedApplied(true)
      onMarkApplied?.(job.job_id)
    } catch { /* silently fail */ }
    finally { setIsMarkingApplied(false) }
  }, [isMarkingApplied, markedApplied, isAlreadyApplied, job.job_id, onMarkApplied])

  const handleToggleDetails = () => setShowDetails(v => !v)

  // Title / company direction handled by dir="auto"

  return (
    <article
      ref={cardRef}
      className={`bg-white rounded-2xl border transition-shadow duration-200 ${
        isDirect ? 'border-emerald-200' : 'border-slate-100'
      } ${showDetails ? 'shadow-elevation-2' : 'shadow-elevation-1'}`}
    >
      {/* Direct-apply teal accent bar */}
      {isDirect && (
        <div
          className="h-0.5 rounded-t-2xl"
          style={{ background: 'linear-gradient(90deg, var(--ja-success), var(--ja-primary))' }}
        />
      )}

      {/* ── Collapsed header row — always visible, click to expand ────────── */}
      <div
        role="button"
        tabIndex={0}
        aria-expanded={showDetails}
        aria-label={`${job.title} at ${job.company || 'Unknown Company'} — ${showDetails ? 'collapse' : 'expand'} details`}
        onClick={handleToggleDetails}
        onKeyDown={e => {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleToggleDetails() }
        }}
        className={`group px-6 py-5 flex items-center gap-4 cursor-pointer select-none transition-colors rounded-t-2xl ${
          showDetails ? 'bg-slate-50/50' : 'hover:bg-slate-50/60'
        }`}
      >
        {/* Title + meta */}
        <div className="flex-1 min-w-0" dir="auto" style={{ textAlign: 'start', unicodeBidi: 'plaintext' }}>
          <div className="flex items-center gap-2.5 flex-wrap">
            <h2 className="text-[15px] font-bold text-slate-900 tracking-tight">
              {job.is_new && (
                <span
                  className="inline-block h-1.5 w-1.5 rounded-full align-middle mr-2 -translate-y-[2px] bg-ja-primary"
                  title="New"
                />
              )}
              {job.title}
            </h2>
            {job.match_score >= 85 && (
              <span className="bg-emerald-50 text-emerald-700 text-[11px] font-semibold px-2 py-0.5 rounded-lg ring-1 ring-inset ring-emerald-600/20 shrink-0">
                Exceptional Match
              </span>
            )}
            {job.match_score >= 70 && job.match_score < 85 && (
              <span className="bg-teal-50 text-teal-700 text-[11px] font-semibold px-2 py-0.5 rounded-lg ring-1 ring-inset ring-teal-600/20 shrink-0">
                Strong Match
              </span>
            )}
            {isDirect && <DirectApplyBadge />}
            {job.is_bulk_import && <BulkImportBadge />}
            {belowThreshold && (
              <span
                className="inline-flex items-center px-1.5 py-0.5 rounded-lg text-[10px] font-semibold shrink-0 bg-ja-warnSubtle text-amber-700"
              >
                ↓ Below threshold
              </span>
            )}
          </div>
          {/* [Company] · [Location] · [Workplace Type] · [Time Ago] */}
          <p className="text-[12.5px] text-slate-400 mt-1" dir="auto" style={{ textAlign: 'start', unicodeBidi: 'plaintext' }}>
            {job.company || 'Unknown Company'}
            {job.location && <> · {job.location}</>}
            {workplaceType && <> · {workplaceType}</>}
            {postedLabel && <> · <span className="tabular-nums">{postedLabel}</span></>}
          </p>
          {/* Strength badges — top strengths for this role, subtle by design */}
          {strengths.length > 0 && (
            <div className="flex items-center gap-1.5 flex-wrap mt-1.5">
              {strengths.map(s => <StrengthBadge key={s} label={s} />)}
            </div>
          )}
        </div>

        {/* Score numeral — hidden and replaced with Analyze CTA when JD is absent */}
        {job.score_is_proxy && (!job.jd_text || job.jd_text.trim().length < 300) ? (
          <AnalyzeJobButton jobId={job.job_id} />
        ) : (
          (() => {
            const band = scoreBand(job.match_score)
            // Thin-JD-capped composite (§2.3 DESIGN_SYSTEM_V2.md): still marked
            // provisional by the backend even though jd_text cleared the 300-char
            // AnalyzeJobButton gate above — never dress up an un-hydrated score.
            const isProvisional = job.score_is_proxy && job.match_score > 0 && job.match_score < 30
            return (
              <div className="flex flex-col items-end gap-1 shrink-0">
                <div className={`inline-flex items-baseline gap-0.5 px-2.5 py-1 rounded-lg ${
                  job.match_score > 0 ? band.bg : 'bg-slate-100'
                }`}>
                  <span className={`text-2xl font-bold tracking-tight tabular-nums ${
                    job.match_score > 0 ? band.text : 'text-slate-400'
                  }`}>
                    {job.match_score > 0 ? job.match_score.toFixed(1) : '—'}
                  </span>
                  <span className={`text-[10px] font-semibold ml-0.5 ${
                    job.match_score > 0 ? band.text : 'text-slate-400'
                  }`}>/100</span>
                </div>
                {isProvisional && (
                  <span className="text-[10px] font-medium text-slate-400 text-end max-w-[130px] leading-tight">
                    Awaiting full description — provisional score.
                  </span>
                )}
              </div>
            )
          })()
        )}

        {/* Expand chevron — signals interactivity */}
        <div className="shrink-0 text-slate-300 transition-colors group-hover:text-slate-500">
          <ChevronDown s={15} flipped={showDetails} />
        </div>
      </div>

      {/* ── Accordion: snippet + gaps + actions + JD ─────────────────────── */}
      <div
        style={{
          display: 'grid',
          gridTemplateRows: showDetails ? '1fr' : '0fr',
          transition: 'grid-template-rows 280ms cubic-bezier(0.4, 0, 0.2, 1)',
        }}
      >
        <div style={{ overflow: 'hidden' }}>
          <div className="border-t border-slate-100 px-6 pt-6 pb-7 space-y-6">

            {/* ① Source badge row */}
            <div className="flex items-center gap-2 flex-wrap">
              <SourceBadge type={job.source_type} />
            </div>

            {/* ② Agent Analysis */}
            <AgentAnalysisBox job={job} userId={userId} />

            {/* ③ Primary action row */}
            <div className="flex items-center gap-3 flex-wrap">
              <button
                onClick={e => { e.stopPropagation(); onTailorCV(job) }}
                className="bg-ja-primary text-white text-xs font-semibold tracking-wide uppercase px-6 py-3 rounded-lg hover:bg-ja-primaryHover transition-colors shadow-sm active:scale-[0.97]"
              >
                Tailor CV
              </button>

              <button
                onClick={e => { e.stopPropagation(); setJdExpanded(v => !v) }}
                className="border border-slate-200 text-slate-600 text-xs font-semibold tracking-wide uppercase px-6 py-3 rounded-lg hover:bg-slate-50 transition-colors active:scale-[0.97]"
              >
                {jdExpanded ? 'Hide Description' : 'View Job Description'}
              </button>

              <ActionBtn
                onClick={e => { (e as React.MouseEvent).stopPropagation(); setShowOutreach(true) }}
                className="border border-violet-200 text-violet-700 bg-violet-50 hover:bg-violet-100"
              >
                Outreach
              </ActionBtn>

              <ActionBtn
                onClick={e => { (e as React.MouseEvent).stopPropagation(); setShowPitch(true) }}
                className="border border-teal-200 text-teal-700 bg-teal-50 hover:bg-teal-100"
              >
                Direct Pitch
              </ActionBtn>

              <ActionBtn
                onClick={e => { (e as React.MouseEvent).stopPropagation(); setShowInterview(true) }}
                disabled={!hasJD}
                title={hasJD
                  ? 'Practice a targeted interview question with Ariel'
                  : 'Fetch the full job description first'}
                className="border border-violet-200 text-violet-700 bg-white hover:bg-violet-50"
              >
                Mock Interview
              </ActionBtn>

              {/* Secondary: source, save, skip */}
              <div className="flex items-center gap-2 ml-auto">
                {job.apply_url && (
                  <a
                    href={job.apply_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={e => e.stopPropagation()}
                    className={`inline-flex items-center gap-1.5 h-8 px-3 rounded-lg text-[11.5px] font-semibold transition ${
                      job.source_type === 'linkedin'
                        ? 'border border-ja-linkedin/25 bg-ja-linkedin/5 text-ja-linkedin hover:border-ja-linkedin/50'
                        : 'border border-teal-200 bg-teal-50 text-teal-700 hover:bg-teal-100'
                    }`}
                  >
                    {job.source_type === 'linkedin' ? <LinkedInIcon s={12} /> : <ExternalLinkIcon s={11} />}
                    {job.source_type === 'linkedin' ? 'LinkedIn' : 'Listing'}
                  </a>
                )}

                <ActionBtn
                  onClick={e => { (e as React.MouseEvent).stopPropagation(); onSave(job.job_id) }}
                  className={isSaved
                    ? 'border border-slate-300 text-slate-900 bg-slate-50'
                    : 'border border-slate-200 text-slate-500 hover:text-slate-900 hover:bg-slate-50'
                  }
                >
                  {isSaved ? '✓ Saved' : 'Save'}
                </ActionBtn>

                <ActionBtn
                  onClick={e => { (e as React.MouseEvent).stopPropagation(); onSkip(job.job_id) }}
                  className="text-slate-400 hover:text-slate-700 hover:bg-slate-100 border border-transparent hover:border-slate-200"
                >
                  Skip
                </ActionBtn>

                {/*
                  Always rendered for any job not already applied/submitted.
                  No dependency on apply_url or has_tailored_cv — manual status
                  updates must work regardless of whether the scraper found a
                  direct application link or a CV has been tailored yet.
                */}
                <ActionBtn
                  onClick={e => { (e as React.MouseEvent).stopPropagation(); handleMarkApplied() }}
                  disabled={isMarkingApplied || isAlreadyApplied || markedApplied}
                  className={(markedApplied || isAlreadyApplied)
                    ? 'border border-emerald-300 bg-emerald-50 text-emerald-700'
                    : 'border border-emerald-200 bg-white text-emerald-700 hover:bg-emerald-50'
                  }
                >
                  {(markedApplied || isAlreadyApplied)
                    ? '✓ Applied'
                    : isMarkingApplied ? 'Saving…' : '✓ Mark Applied'}
                </ActionBtn>
              </div>
            </div>

            {/* ⑤ Job description sub-panel */}
            <div
              style={{
                display: 'grid',
                gridTemplateRows: jdExpanded ? '1fr' : '0fr',
                transition: 'grid-template-rows 260ms cubic-bezier(0.4, 0, 0.2, 1)',
              }}
            >
              <div style={{ overflow: 'hidden' }}>
                <div className="pt-4 space-y-4">
                  <p className="text-[11px] font-bold tracking-widest uppercase text-slate-400">
                    Job Description
                  </p>
                  {hasJD ? (
                    parsedStructuredJd ? (
                      <StructuredJdPanel parsed={parsedStructuredJd} />
                    ) : job.jd_text ? (
                      <JdPanel
                        text={job.jd_text.trim()}
                        expanded={jdExpanded}
                        onToggleExpand={() => setJdExpanded(v => !v)}
                        isHebrewLocale={isHebrewLocale}
                      />
                    ) : null
                  ) : (
                    <p className="text-[12px] text-slate-400 italic">
                      No description available.
                      {job.apply_url && (
                        <> <a href={job.apply_url} target="_blank" rel="noopener noreferrer"
                          className="underline text-teal-600 hover:text-teal-800">View original posting.</a></>
                      )}
                    </p>
                  )}

                  {/* ATS Breakdown — keywords injected / excluded + confidence snapshot */}
                  <div className="pt-3 border-t border-slate-100">
                    <button
                      onClick={e => { e.stopPropagation(); setShowAtsPanel(p => !p) }}
                      className="flex items-center gap-1.5 text-[12px] font-medium text-slate-500 hover:text-slate-800 transition"
                    >
                      <span className="text-[10px]">{showAtsPanel ? '▼' : '▶'}</span>
                      ATS Breakdown
                      {!hasJD && <span className="text-[10px] text-amber-500 ml-0.5">(fetch JD first)</span>}
                    </button>
                    {showAtsPanel && (
                      <div className="mt-2">
                        <AtsKeywordsPanel jobId={job.job_id} hasJd={hasJD} userId={userId} />
                      </div>
                    )}
                  </div>

                  {/* Active Skills Gap Analysis (JOB-59) */}
                  <div className="pt-3 border-t border-slate-100">
                    <button
                      onClick={e => { e.stopPropagation(); setShowSkillsGap(p => !p) }}
                      className="flex items-center gap-1.5 text-[12px] font-medium text-slate-500 hover:text-slate-800 transition"
                    >
                      <span className="text-[10px]">{showSkillsGap ? '▼' : '▶'}</span>
                      Skills Gap Analysis
                      {!hasJD && <span className="text-[10px] text-amber-500 ml-0.5">(fetch JD first)</span>}
                    </button>
                    {showSkillsGap && (
                      <div className="mt-2">
                        <SkillsGapPanel jobId={job.job_id} hasJd={hasJD} />
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>

          </div>
        </div>
      </div>

      {showOutreach && (
        <OutreachModal job={job} onClose={() => setShowOutreach(false)} />
      )}
      {showPitch && (
        <DirectPitchModal job={job} onClose={() => setShowPitch(false)} />
      )}
      {showInterview && (
        <InterviewSimulatorModal job={job} onClose={() => setShowInterview(false)} />
      )}
    </article>
  )
}
