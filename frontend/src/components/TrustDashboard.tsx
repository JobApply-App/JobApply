'use client'

/**
 * TrustDashboard — v2
 * ===================
 * Visualises the Active Confidence Matrix and closes the feedback loop:
 *
 *   Dashboard shows low confidence
 *     → "Strengthen Trust" button on each weak entity
 *       → Ariel STAR probe starts (POST /api/ariel/probe/start)
 *         → 3-turn conversation in ProbeModal
 *           → LLM evaluates → confidence updates → dashboard re-fetches
 *
 * New in v2:
 *   • ProbeModal        — 3-turn STAR interview driven by the Ariel Probe API
 *   • ManualReviewModal — shows the audit log note explaining the flag +
 *                         re-upload cert option
 *   • AuthWallCallout   — auth_wall / LinkedIn cookie-expired banner
 *   • Loading skeleton  — animated placeholder during initial fetch
 *   • "Strengthen Trust" button on EntityTrustRow (score < 70, no flag)
 *
 * Styling contract (unchanged from v1):
 *   • JobCard.tsx patterns: rounded-2xl, border-slate-100, TOKENS.shadow.card
 *   • Accordions: CSS grid 0fr → 1fr (no framer-motion)
 *   • All icons: inline SVG (no lucide-react at runtime)
 *   • Primary brand: TOKENS.color.primary (#0D9488 teal-600)
 */

import {
  useState, useEffect, useCallback, useRef, lazy, Suspense,
} from 'react'
import Link from 'next/link'
import { TOKENS } from '@/lib/tokens'
import { ensureFreshToken, getAuthHeaders, setAuthToken } from '@/lib/api'
import { supabase } from '@/lib/supabase'
import type {
  TrustScoreResponse, TrustProfileEntity, TrustEvidenceEntry, EntityType,
  SkillTier, VerificationLevel, ConfidenceMatrixResponse, ConfidenceRadarDatum,
  ScoreBreakdown,
} from '@/lib/apiTypes'

// ── recharts — lazy so the rest of the UI is not blocked ─────────────────────

// Teal  = Core_Mastery (direct hands-on proficiency)
const RADAR_TEAL   = TOKENS.color.primary          // #0D9488
// Violet = System_Orchestration (AI-augmented, architecture-level)
const RADAR_VIOLET = '#7C3AED'

interface RadarDatum {
  category:   string
  arch_value: number   // Architecture_Confidence — outer polygon
  syn_value:  number   // Syntax_Confidence — inner polygon
  value:      number   // blended final (shown in tooltip)
}

const RadarChartLazy = lazy(() =>
  import('recharts').then(m => ({
    default: function RechartsRadar({ data }: { data: RadarDatum[] }) {
      const { RadarChart, Radar, PolarGrid, PolarAngleAxis, Legend,
              ResponsiveContainer, Tooltip } = m
      const hasSyntax = data.some(d => d.syn_value > 0)
      return (
        <ResponsiveContainer width="100%" height={260}>
          <RadarChart
            data={data}
            outerRadius={72}
            margin={{ top: 10, right: 30, bottom: 10, left: 30 }}
          >
            <PolarGrid stroke="#E2E8F0" strokeDasharray="3 3" />
            <PolarAngleAxis
              dataKey="category"
              tick={{ fontSize: 10.5, fontWeight: 600, fill: '#64748B' }}
            />
            <Tooltip
              contentStyle={{
                fontSize: 11, background: '#fff',
                border: '1px solid #E2E8F0', borderRadius: 8,
                padding: '6px 10px', boxShadow: '0 2px 8px rgba(0,0,0,0.06)',
              }}
              formatter={(value: number, name: string) => [
                `${(value as number).toFixed(1)}`,
                name === 'arch'   ? 'Architecture' :
                name === 'syntax' ? 'Syntax (Manual)' : 'Blended',
              ]}
            />
            {/* Architecture — outer teal polygon */}
            <Radar
              name="arch" dataKey="arch_value"
              stroke={RADAR_TEAL} fill={RADAR_TEAL}
              fillOpacity={0.12} strokeWidth={2}
              dot={{ r: 3, fill: RADAR_TEAL, strokeWidth: 0 }}
            />
            {/* Syntax — inner violet polygon (only when manual evidence exists) */}
            {hasSyntax && (
              <Radar
                name="syntax" dataKey="syn_value"
                stroke={RADAR_VIOLET} fill={RADAR_VIOLET}
                fillOpacity={0.18} strokeWidth={2}
                dot={{ r: 3, fill: RADAR_VIOLET, strokeWidth: 0 }}
              />
            )}
            <Legend
              iconType="circle" iconSize={8}
              wrapperStyle={{ fontSize: 10.5, paddingTop: 4 }}
              formatter={(v: string) =>
                v === 'arch'   ? 'Architecture Confidence' :
                v === 'syntax' ? 'Syntax Confidence (Manual)' : v
              }
            />
          </RadarChart>
        </ResponsiveContainer>
      )
    },
  }))
)

// ── Types ─────────────────────────────────────────────────────────────────────

interface AuditEntry {
  log_id:         number
  old_score:      number
  new_score:      number
  delta:          number
  trigger_source: string
  changed_at:     string
  note:           string | null
}

interface AuditResponse {
  entity_id:              string
  entity_name:            string
  entity_type:            string
  confidence_score:       number
  manual_review_required: boolean
  latest_flag_note:       string | null
  audit_log:              AuditEntry[]
}

export interface ProbeState {
  session_id:     string
  entity_id:      string
  entity_name:    string
  probe_method?:  'STAR' | 'SCOPE' | 'SIGNAL'
  turn:           number          // current turn being shown (1–3)
  question:       string
  answers:        Record<number, string>   // turn → text typed so far
  done:           boolean
  flag_type:      string | null
  new_confidence: number | null
}

const PROBE_STEP_LABELS: Record<string, [string, string, string, string]> = {
  STAR:    ['Situation', 'Task',      'Action',     'Result'],
  SCOPE:   ['Scale',     'Context',   'Trade-off',  'Result'],
  SIGNAL:  ['Situation', 'Task',      'Action',     'Result'],
}

function probeMethodFromEntityType(type: EntityType | string | undefined): 'STAR' | 'SCOPE' | 'SIGNAL' {
  const t = (type ?? '').toLowerCase()
  if (t === 'domain' || t === 'experience') return 'SCOPE'
  if (t === 'trait') return 'SIGNAL'
  return 'STAR'
}

// Soft message returned when the LLM timed out — shown in ProbeModal as an
// amber callout.  NOT an error state; the user stays on turn 3 and can retry.
const ARIEL_THINKING_THRESHOLD_MS = 3000   // show "thinking" indicator after 3 s

// ── Inline SVG icons ──────────────────────────────────────────────────────────

function ChevronDown({ s = 14, flipped = false }: { s?: number; flipped?: boolean }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"
      style={{ transition: 'transform 250ms ease', transform: flipped ? 'rotate(180deg)' : 'none' }}
    >
      <polyline points="6 9 12 15 18 9" />
    </svg>
  )
}
function WarnTriangle({ s = 14 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
    >
      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  )
}
function ShieldCheck({ s = 14 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
    >
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
      <polyline points="9 12 11 14 15 10" />
    </svg>
  )
}
function ZapIcon({ s = 12 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"
    >
      <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
    </svg>
  )
}
function LinkIcon({ s = 12 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
    >
      <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
      <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
    </svg>
  )
}
function FileText({ s = 12 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
    >
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" />
      <polyline points="10 9 9 9 8 9" />
    </svg>
  )
}
function UploadIcon({ s = 14 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
    >
      <polyline points="16 16 12 12 8 16" />
      <line x1="12" y1="12" x2="12" y2="21" />
      <path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3" />
    </svg>
  )
}
function XIcon({ s = 14 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"
    >
      <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  )
}
function SpinnerIcon({ s = 16 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none"
      style={{ animation: 'spin 0.8s linear infinite', flexShrink: 0 }}
    >
      <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.5" strokeOpacity="0.2" />
      <path d="M12 3a9 9 0 0 1 9 9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  )
}
function CheckCircle({ s = 14 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
    >
      <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
      <polyline points="22 4 12 14.01 9 11.01" />
    </svg>
  )
}

// ── TrustBadge ────────────────────────────────────────────────────────────────

type TrustTier = 'high' | 'medium' | 'low' | 'unverified'

function getTrustTier(score: number): TrustTier {
  if (score >= 80) return 'high'
  if (score >= 60) return 'medium'
  if (score >= 40) return 'low'
  return 'unverified'
}

const TRUST_BADGE_CONFIG: Record<TrustTier, { label: string; bg: string; fg: string }> = {
  high:       { label: 'High Trust', bg: '#F0FDF4', fg: '#15803D' },
  medium:     { label: 'Med Trust',  bg: '#FEFCE8', fg: '#A16207' },
  low:        { label: 'Low Trust',  bg: '#FFF7ED', fg: '#C2410C' },
  unverified: { label: 'Unverified', bg: '#F3F4F6', fg: '#4B5563' },
}

function TrustBadge({ score }: { score: number }) {
  const tier   = getTrustTier(score)
  const config = TRUST_BADGE_CONFIG[tier]
  return (
    <span
      className="inline-flex items-center h-[18px] px-2 rounded-md text-[10.5px] font-semibold tracking-wide shrink-0"
      style={{ background: config.bg, color: config.fg }}
    >
      {config.label}
    </span>
  )
}

// ── Verification Level display label ─────────────────────────────────────────
// Maps the backend verification_level to a human status string.
// 30-capped unverified skills show "Baseline Knowledge" — not a punishment score.

const VERIFICATION_LABELS: Record<string, { text: string; color: string; dot: string }> = {
  VERIFIED_MANUAL:    { text: 'Verified',                color: 'oklch(0.42 0.16 170)', dot: 'oklch(0.60 0.18 170)' },
  ORCHESTRATION_ONLY: { text: 'Orchestration Ready',     color: 'oklch(0.42 0.18 250)', dot: 'oklch(0.58 0.20 250)' },
  UNVERIFIED:         { text: 'Baseline · Verify Needed', color: 'oklch(0.48 0.16 50)',  dot: 'oklch(0.72 0.17 55)'  },
}

// ── ProgressBar ───────────────────────────────────────────────────────────────

function ProgressBar({ score, verificationLevel }: {
  score:              number
  verificationLevel?: string
}) {
  const pct = Math.min(100, Math.max(0, score))
  const vl  = verificationLevel ?? 'UNVERIFIED'

  const [from, to] = vl === 'VERIFIED_MANUAL'
    ? ['oklch(0.65 0.18 160)', 'oklch(0.50 0.20 200)']   // teal  — verified
    : vl === 'ORCHESTRATION_ONLY'
      ? ['oklch(0.55 0.18 250)', 'oklch(0.48 0.20 270)']  // blue  — orchestration
      : ['oklch(0.78 0.17 60)',  'oklch(0.65 0.20 40)']   // amber — baseline

  const label = VERIFICATION_LABELS[vl] ?? VERIFICATION_LABELS.UNVERIFIED

  return (
    <div className="w-full flex items-center gap-2.5 min-w-0">
      {/* Prominent numeric score — anchors the row's visual hierarchy */}
      <span className="shrink-0 w-11 text-right text-[13px] font-bold tabular-nums leading-none" style={{ color: to }}>
        {pct.toFixed(1)}
        <span className="text-[9px] font-semibold align-top ml-px">%</span>
      </span>
      {/* Track — inset shadow for depth; taller rounded rail with a gradient fill */}
      <div
        className="flex-1 h-[7px] rounded-full bg-slate-100 overflow-hidden"
        style={{ boxShadow: 'inset 0 1px 2px rgba(15,23,42,0.08)' }}
      >
        <div
          className="h-full rounded-full"
          style={{
            width:      `${pct}%`,
            background: `linear-gradient(90deg, ${from}, ${to})`,
            boxShadow:  `0 0 8px color-mix(in oklab, ${to} 45%, transparent)`,
            transition: 'width 600ms cubic-bezier(0.22,1,0.36,1)',
          }}
        />
      </div>
      <div className="flex items-center gap-1 shrink-0 max-w-[120px]">
        <span
          className="w-[6px] h-[6px] rounded-full shrink-0"
          style={{ background: label.dot }}
        />
        <span
          className="text-[10.5px] font-medium leading-tight"
          style={{ color: label.color }}
        >
          {label.text}
        </span>
      </div>
    </div>
  )
}

// ── Source labels ─────────────────────────────────────────────────────────────

const SOURCE_LABELS: Record<string, string> = {
  cv_parse:                 'CV Parse',
  self_assertion:           'Self-Assertion',
  contextual_reinforcement: 'Contextual Mention',
  certification:            'Certification',
  portfolio:                'Portfolio',
  conversation_star:        'STAR Behavioral Probe',
  negative_flag:            'Negative Flag',
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString('en-GB', {
      day: '2-digit', month: 'short', year: 'numeric',
    })
  } catch { return iso.slice(0, 10) }
}

// ── EvidenceAccordion ─────────────────────────────────────────────────────────

function EvidenceAccordion({ entries, open }: { entries: TrustEvidenceEntry[]; open: boolean }) {
  return (
    <div style={{
      display: 'grid',
      gridTemplateRows: open ? '1fr' : '0fr',
      transition: 'grid-template-rows 260ms cubic-bezier(0.4,0,0.2,1)',
    }}>
      <div style={{ overflow: 'hidden' }}>
        <div className="pt-3 pb-1 space-y-2">
          {entries.length === 0 ? (
            <p className="text-[11.5px] text-slate-400 italic px-1">No evidence records yet.</p>
          ) : entries.map(entry => <EvidenceRow key={entry.evidence_id} entry={entry} />)}
        </div>
      </div>
    </div>
  )
}

function EvidenceRow({ entry }: { entry: TrustEvidenceEntry }) {
  const isNeg       = entry.base_weight < 0
  const sourceLabel = SOURCE_LABELS[entry.source_type] ?? entry.source_type
  return (
    <div
      className="flex items-start gap-3 rounded-lg px-3 py-2.5"
      style={{
        background: isNeg ? 'oklch(0.98 0.02 25)' : 'oklch(0.975 0.00 0)',
        border: `1px solid ${isNeg ? 'oklch(0.90 0.04 25)' : 'oklch(0.93 0.00 0)'}`,
      }}
    >
      <span
        className="shrink-0 inline-flex items-center h-[18px] px-1.5 rounded text-[10px] font-bold tabular-nums mt-0.5"
        style={{
          background: isNeg ? 'oklch(0.94 0.05 25)' : 'oklch(0.94 0.05 155)',
          color:      isNeg ? 'oklch(0.48 0.14 25)' : 'oklch(0.32 0.12 155)',
        }}
      >
        {isNeg ? '' : '+'}{entry.base_weight.toFixed(0)}
      </span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[11px] font-semibold text-slate-600 flex items-center gap-1">
            <FileText s={10} />{sourceLabel}
          </span>
          <span className="text-[10.5px] text-slate-400">{formatDate(entry.verified_at)}</span>
          {entry.is_ai_assisted && (
            <span
              className="inline-flex items-center h-[16px] px-1.5 rounded text-[9px] font-bold tracking-wide uppercase"
              style={{ background: 'oklch(0.94 0.07 290)', color: 'oklch(0.35 0.18 290)' }}
              title="AI-assisted: architecture understood, AI generated the boilerplate"
            >
              AI-Aug ×0.6
            </span>
          )}
        </div>
        {entry.raw_content && (
          <p className="mt-1 text-[11.5px] text-slate-500 leading-relaxed line-clamp-3">
            {entry.raw_content}
          </p>
        )}
      </div>
    </div>
  )
}

// ── EntityTypeChip ────────────────────────────────────────────────────────────

const ENTITY_TYPE_CONFIG: Record<EntityType, { label: string; bg: string; fg: string }> = {
  skill:      { label: 'Skill',      bg: 'oklch(0.94 0.05 155)', fg: 'oklch(0.30 0.12 155)' },
  trait:      { label: 'Trait',      bg: 'oklch(0.94 0.06 290)', fg: 'oklch(0.38 0.16 290)' },
  domain:     { label: 'Domain',     bg: 'oklch(0.94 0.06 255)', fg: 'oklch(0.35 0.18 255)' },
  experience: { label: 'Experience', bg: 'oklch(0.94 0.04 55)',  fg: 'oklch(0.38 0.12 50)'  },
}

function EntityTypeChip({ type }: { type: EntityType }) {
  const cfg = ENTITY_TYPE_CONFIG[type] ?? ENTITY_TYPE_CONFIG.skill
  return (
    <span
      className="shrink-0 inline-flex items-center h-[18px] px-1.5 rounded text-[9.5px] font-bold tracking-wide uppercase"
      style={{ background: cfg.bg, color: cfg.fg }}
    >
      {cfg.label}
    </span>
  )
}

// ── VerificationLevelBadge ────────────────────────────────────────────────────

const VL_CONFIG: Record<
  VerificationLevel,
  { label: string; bg: string; fg: string; title: string }
> = {
  VERIFIED_MANUAL: {
    label: 'Manual ✓',
    bg:    'oklch(0.93 0.07 155)',
    fg:    'oklch(0.28 0.14 155)',
    title: 'Verified: passed a manual (no-AI) assessment',
  },
  ORCHESTRATION_ONLY: {
    label: 'Arch only',
    bg:    'oklch(0.95 0.05 50)',
    fg:    'oklch(0.48 0.14 50)',
    title: 'Architecture evidence present — no manual syntax verification yet',
  },
  UNVERIFIED: {
    label: 'No evidence',
    bg:    'oklch(0.94 0.00 0)',
    fg:    'oklch(0.48 0.00 0)',
    title: 'No meaningful evidence on record',
  },
}

function VerificationLevelBadge({ level }: { level: VerificationLevel }) {
  const cfg = VL_CONFIG[level] ?? VL_CONFIG.UNVERIFIED
  return (
    <span
      className="shrink-0 inline-flex items-center h-[18px] px-1.5 rounded text-[9.5px] font-bold tracking-wide"
      style={{ background: cfg.bg, color: cfg.fg }}
      title={cfg.title}
    >
      {cfg.label}
    </span>
  )
}

// ── SkillTierChip ─────────────────────────────────────────────────────────────

const SKILL_TIER_CONFIG: Record<
  'Core_Mastery' | 'System_Orchestration',
  { label: string; bg: string; fg: string; title: string }
> = {
  Core_Mastery: {
    label: 'Core',
    bg:    'oklch(0.94 0.08 170)',
    fg:    'oklch(0.32 0.14 170)',
    title: 'Core Mastery — direct hands-on proficiency',
  },
  System_Orchestration: {
    label: 'Orchestration',
    bg:    'oklch(0.94 0.07 290)',
    fg:    'oklch(0.35 0.18 290)',
    title: 'System Orchestration — understands architecture, uses AI for boilerplate',
  },
}

function SkillTierChip({ tier }: { tier: SkillTier }) {
  if (!tier) return null
  const cfg = SKILL_TIER_CONFIG[tier]
  return (
    <span
      className="shrink-0 inline-flex items-center h-[18px] px-1.5 rounded text-[9.5px] font-bold tracking-wide uppercase"
      style={{ background: cfg.bg, color: cfg.fg }}
      title={cfg.title}
    >
      {cfg.label}
    </span>
  )
}

// ── EntityTrustRow ────────────────────────────────────────────────────────────
//
// Shows "Strengthen Trust" button when:
//   • confidence_score < 70
//   • manual_review_required === false
//
// The button fires onProbe(entity) — handled by TrustDashboard to open ProbeModal.

interface EntityTrustRowProps {
  entity:        TrustProfileEntity
  defaultOpen?:  boolean
  onProbe:       (entity: TrustProfileEntity) => void
  onReview:      (entity: TrustProfileEntity) => void
  onManualVerify:(entity: TrustProfileEntity) => void
  probing:       boolean   // true while this entity's probe is initialising
}

function EntityTrustRow({
  entity, defaultOpen = false, onProbe, onReview, onManualVerify, probing,
}: EntityTrustRowProps) {
  const [open, setOpen] = useState(defaultOpen)

  const canProbe  = entity.confidence_score < 70 && !entity.manual_review_required
  const needsFlag = entity.manual_review_required

  return (
    <div
      className={`group/row rounded-xl border bg-white transition-all duration-200 ease-out ${
        needsFlag ? 'border-amber-200' : 'border-slate-100 hover:border-slate-200'
      } ${open ? '' : 'hover:-translate-y-0.5'}`}
      style={{
        boxShadow: open
          ? '0 2px 8px rgba(0,0,0,0.04), 0 12px 28px rgba(0,0,0,0.05)'
          : '0 1px 3px rgba(15,23,42,0.05)',
        transition: 'box-shadow 200ms ease, border-color 150ms ease, transform 200ms ease',
      }}
    >
      {/* Amber accent bar for flagged entities */}
      {needsFlag && (
        <div
          className="h-0.5 rounded-t-xl"
          style={{ background: 'linear-gradient(90deg, #F59E0B, #D97706)' }}
        />
      )}

      {/* ── Clickable header ─────────────────────────────────────────────────
          Mobile (<sm): stacked — [type chip + name + chevron] / [progress bar]
          / [action buttons, wrapping]. The 160px/140px min-widths below were
          forcing a ~300px+ floor on a single un-wrapped row, overflowing any
          375–428px viewport. At sm: and up this reverts to the original
          single-row layout byte-for-byte (same flex-[2]/flex-[3]/min-w values). */}
      <div
        role="button"
        aria-expanded={open}
        onClick={() => setOpen(v => !v)}
        className={`group px-4 py-3.5 flex flex-col gap-2.5 sm:flex-row sm:items-center sm:gap-3 cursor-pointer select-none transition-colors ${
          open ? 'bg-slate-50/60' : 'hover:bg-slate-50/60'
        }`}
      >
        {/* Type chip + name + mobile-only chevron — one row on every breakpoint */}
        <div className="flex items-center gap-2 min-w-0 sm:contents">
          <EntityTypeChip type={entity.entity_type} />

          {/* Name — fixed min-width at sm: so it never collapses there; on
              mobile it just fills the row and truncates naturally. */}
          <span className="flex-1 min-w-0 sm:min-w-[160px] sm:flex-[2] text-[13px] font-semibold text-slate-800 overflow-hidden text-ellipsis whitespace-nowrap">
            {entity.name}
          </span>

          {/* Chevron — inline here on mobile (end of the header row); the
              sm:+ chevron is a separate element at the end of the flex row,
              matching the original desktop position. */}
          <span className="sm:hidden shrink-0 text-slate-300 transition-colors group-hover:text-slate-500">
            <ChevronDown s={13} flipped={open} />
          </span>
        </div>

        {/* Progress bar — fixed width at sm: so it doesn't steal space from
            the name; full-width on its own row on mobile. */}
        <div className="sm:flex-[3] sm:min-w-[140px] sm:max-w-[340px]">
          <ProgressBar
            score={entity.confidence_score}
            verificationLevel={entity.verification_level}
          />
        </div>

        {/* Action buttons — stop propagation so they don't toggle the accordion.
            44px tall on mobile (touch target minimum), wrapping if all three
            show at once; 28px/nowrap at sm: and up, matching the original. */}
        <div
          className="flex items-center gap-2 flex-wrap sm:flex-nowrap sm:gap-1.5 sm:shrink-0 sm:min-w-0"
          onClick={e => e.stopPropagation()}
        >
          {/* Verify — shown for all unverified skills; amber styling signals urgency */}
          {entity.verification_level !== 'VERIFIED_MANUAL' && (
            <button
              onClick={() => onManualVerify(entity)}
              title="Manual verification required to unlock full score"
              className="inline-flex items-center gap-1 h-11 sm:h-7 px-2.5 rounded-lg text-[11px] font-semibold transition active:scale-[0.97]"
              style={{
                background: 'oklch(0.93 0.12 50)',
                color:      'oklch(0.40 0.20 30)',
                border:     '1px solid oklch(0.78 0.16 45)',
              }}
            >
              <svg width={10} height={10} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={2.2}>
                <path d="M9 12l2 2 4-4M4 6h12M4 10h6M4 14h4"/>
              </svg>
              Verify
            </button>
          )}
          {canProbe && (
            <button
              onClick={() => onProbe(entity)}
              disabled={probing}
              title="Start a STAR behavioral probe to strengthen this skill's evidence"
              className="inline-flex items-center gap-1 h-11 sm:h-7 px-2.5 rounded-lg text-[11px] font-semibold transition active:scale-[0.97] disabled:opacity-50 disabled:cursor-not-allowed"
              style={{
                background: TOKENS.color.primarySoft,
                color:      TOKENS.color.primary,
                border:     `1px solid oklch(0.85 0.07 170)`,
              }}
            >
              {probing ? <SpinnerIcon s={11} /> : <ZapIcon s={11} />}
              Strengthen
            </button>
          )}
          {needsFlag && (
            <button
              onClick={() => onReview(entity)}
              title="View why this entity was flagged and re-submit evidence"
              className="inline-flex items-center gap-1 h-11 sm:h-7 px-2.5 rounded-lg text-[11px] font-semibold transition active:scale-[0.97]"
              style={{
                background: 'oklch(0.96 0.06 60)',
                color:      'oklch(0.40 0.12 50)',
                border:     '1px solid oklch(0.88 0.07 60)',
              }}
            >
              <WarnTriangle s={10} />
              Review
            </button>
          )}
        </div>

        {/* Chevron — sm:+ only; positioned at the end of the row, same as before */}
        <span className="hidden sm:inline-flex shrink-0 text-slate-300 transition-colors group-hover:text-slate-500">
          <ChevronDown s={13} flipped={open} />
        </span>
      </div>

      {/* ── Evidence accordion ────────────────────────────────────────────── */}
      <div className="px-4 pb-0">
        <EvidenceAccordion entries={entity.trust_breakdown} open={open} />
        {open && <div className="h-3" />}
      </div>
    </div>
  )
}

// ── FlagNoteCard ──────────────────────────────────────────────────────────────
//
// Renders the confidence_audit_log `note` field with visual structure.
//
// The note is stored as:  "Negative flag [<type>]: <reason>"
// We parse this into a coloured type badge + the verbatim reason sentence so
// the user sees exactly what the evaluator found wrong — not a generic message.

const FLAG_TYPE_CONFIG: Record<string, { badge: string; bg: string; fg: string; border: string }> = {
  contradiction: {
    badge:  'Contradiction',
    bg:     'oklch(0.98 0.02 25)',
    fg:     'oklch(0.45 0.16 25)',
    border: 'oklch(0.88 0.06 25)',
  },
  shallow_star: {
    badge:  'Shallow response',
    bg:     'oklch(0.98 0.03 60)',
    fg:     'oklch(0.42 0.12 55)',
    border: 'oklch(0.88 0.07 60)',
  },
  inconsistency: {
    badge:  'Inconsistency',
    bg:     'oklch(0.98 0.02 290)',
    fg:     'oklch(0.42 0.14 290)',
    border: 'oklch(0.88 0.06 290)',
  },
}
const FLAG_TYPE_DEFAULT = {
  badge:  'Flag',
  bg:     'oklch(0.975 0.00 0)',
  fg:     'oklch(0.45 0.00 0)',
  border: 'oklch(0.90 0.00 0)',
}

function parseFlagNote(note: string): { flagType: string; reason: string } {
  // Matches: "Negative flag [contradiction]: <reason text>"
  const match = note.match(/^Negative flag \[([^\]]+)\]:\s*([\s\S]+)$/)
  if (match) return { flagType: match[1].trim(), reason: match[2].trim() }
  return { flagType: 'flag', reason: note }
}

function FlagNoteCard({ note }: { note: string }) {
  const { flagType, reason } = parseFlagNote(note)
  const cfg = FLAG_TYPE_CONFIG[flagType] ?? FLAG_TYPE_DEFAULT

  return (
    <div
      className="rounded-xl px-4 py-3.5 space-y-2"
      style={{ background: cfg.bg, border: `1px solid ${cfg.border}` }}
    >
      <div className="flex items-center gap-2">
        <span className="text-[15px]" aria-hidden="true">⚠️</span>
        <p className="text-[10.5px] font-bold tracking-widest uppercase text-slate-400">
          Why it was flagged
        </p>
        {/* Flag type badge */}
        <span
          className="inline-flex items-center h-[18px] px-2 rounded-md text-[10px] font-bold tracking-wide ml-auto"
          style={{ background: cfg.border, color: cfg.fg }}
        >
          {cfg.badge}
        </span>
      </div>
      {/* Verbatim evaluator reason — contains the specific quote / contrast */}
      <p className="text-[12.5px] text-slate-700 leading-relaxed">{reason}</p>
    </div>
  )
}


// ── ManualReviewModal ─────────────────────────────────────────────────────────
//
// Opens when the user clicks "Review" on a flagged entity.
// Fetches the audit log from GET /api/ariel/audit/{entity_id} to show the
// exact flag note, then offers a re-upload certificate flow.

interface ManualReviewModalProps {
  entity:  TrustProfileEntity
  onClose: () => void
  onDone:  () => void   // refetch the dashboard after evidence re-upload
}

function ManualReviewModal({ entity, onClose, onDone }: ManualReviewModalProps) {
  const [audit,      setAudit]      = useState<AuditResponse | null>(null)
  const [loadingAudit, setLoadingAudit] = useState(true)
  const [auditError, setAuditError] = useState<string | null>(null)
  const [uploading,  setUploading]  = useState(false)
  const [uploadDone, setUploadDone] = useState(false)
  const [uploadError,setUploadError]= useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  // Fetch audit log on mount
  useEffect(() => {
    let cancelled = false
    setLoadingAudit(true)
    ensureFreshToken().then(() => fetch(`/api/ariel/audit/${entity.entity_id}`, {
      headers: getAuthHeaders(),
      cache:   'no-store',
    }))
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(data => { if (!cancelled) { setAudit(data as AuditResponse); setLoadingAudit(false) } })
      .catch(e  => { if (!cancelled) { setAuditError(e.message); setLoadingAudit(false) } })
    return () => { cancelled = true }
  }, [entity.entity_id])

  async function handleUpload(file: File) {
    setUploading(true)
    setUploadError(null)
    try {
      const form = new FormData()
      form.append('file',     file)
      form.append('entity_id', entity.entity_id)
      await ensureFreshToken()
      const res = await fetch('/api/profile/cv-upload', {
        method:  'POST',
        headers: getAuthHeaders(),
        body:    form,
      })
      if (!res.ok) throw new Error(`Upload failed (HTTP ${res.status})`)
      setUploadDone(true)
      setTimeout(() => { onDone(); onClose() }, 1500)
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  // Trap focus and close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    /* Backdrop — Meridian V2 §3.2 scrim */
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(15,23,42,0.55)', backdropFilter: 'blur(4px)' }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        className="bg-white rounded-2xl w-full max-w-md shadow-floating overflow-hidden animate-modal-in"
        style={{ boxShadow: '0 24px 64px rgba(15,23,42,0.22)' }}
      >
        {/* Header */}
        <div
          className="h-1"
          style={{ background: 'linear-gradient(90deg, #F59E0B, #D97706)' }}
        />
        <div className="px-5 pt-5 pb-4 flex items-start justify-between">
          <div>
            <div className="flex items-center gap-2 mb-0.5">
              <span className="text-amber-500"><WarnTriangle s={15} /></span>
              <h3 className="text-[14px] font-bold text-slate-800">Manual Review Required</h3>
            </div>
            <p className="text-[12px] text-slate-500">
              <span className="font-semibold text-slate-700">{entity.name}</span>
              {' '}— confidence {entity.confidence_score.toFixed(1)}
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-700 transition p-1 rounded-lg hover:bg-slate-100 active:scale-90"
          >
            <XIcon s={15} />
          </button>
        </div>

        <div className="px-5 pb-5 space-y-4">
          {/* Flag reason from audit log */}
          {loadingAudit && (
            <div className="flex items-center gap-2 text-[12px] text-slate-400 py-2">
              <SpinnerIcon s={13} />Loading audit log…
            </div>
          )}
          {auditError && (
            <p className="text-[12px] text-red-500">{auditError}</p>
          )}
          {audit && (
            <>
              {audit.latest_flag_note && (
                <FlagNoteCard note={audit.latest_flag_note} />
              )}

              {/* Recent audit trail (last 5 entries) */}
              {audit.audit_log.length > 0 && (
                <div>
                  <p className="text-[10.5px] font-bold tracking-widest uppercase text-slate-400 mb-2">
                    Recent score changes
                  </p>
                  <div className="space-y-1.5">
                    {audit.audit_log.slice(0, 5).map(entry => (
                      <div key={entry.log_id}
                        className="flex items-center gap-2 text-[11.5px] text-slate-500"
                      >
                        <span
                          className={`inline-flex items-center h-[18px] px-1.5 rounded text-[10px] font-bold tabular-nums shrink-0 ${
                            entry.delta >= 0 ? 'bg-teal-50 text-teal-700' : 'bg-red-50 text-red-600'
                          }`}
                        >
                          {entry.delta >= 0 ? '+' : ''}{entry.delta.toFixed(1)}
                        </span>
                        <span className="truncate">{entry.trigger_source.replace('_', ' ')}</span>
                        <span className="text-slate-300 shrink-0">{formatDate(entry.changed_at)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}

          {/* Re-upload evidence */}
          <div
            className="rounded-xl border border-dashed border-slate-200 p-4 flex flex-col items-center gap-2.5"
            style={{ background: 'oklch(0.975 0.00 0)' }}
          >
            <span className="text-slate-400"><UploadIcon s={20} /></span>
            <div className="text-center">
              <p className="text-[12.5px] font-semibold text-slate-700">
                Re-submit evidence
              </p>
              <p className="text-[11.5px] text-slate-400 mt-0.5">
                Upload a certificate, portfolio, or CV to add positive evidence.
              </p>
            </div>

            {uploadDone ? (
              <div className="flex items-center gap-1.5 text-[12px] font-semibold text-teal-600">
                <CheckCircle s={13} />Uploaded — refreshing dashboard…
              </div>
            ) : (
              <button
                onClick={() => fileRef.current?.click()}
                disabled={uploading}
                className="inline-flex items-center gap-1.5 h-8 px-4 rounded-lg text-[12px] font-semibold transition active:scale-[0.97] disabled:opacity-50"
                style={{
                  background: TOKENS.color.primary,
                  color:      '#fff',
                }}
              >
                {uploading ? <SpinnerIcon s={12} /> : <UploadIcon s={12} />}
                {uploading ? 'Uploading…' : 'Choose file'}
              </button>
            )}

            {uploadError && (
              <p className="text-[11.5px] text-red-500">{uploadError}</p>
            )}

            <input
              ref={fileRef}
              type="file"
              accept=".pdf,.docx"
              className="hidden"
              onChange={e => {
                const f = e.target.files?.[0]
                if (f) handleUpload(f)
              }}
            />
          </div>
        </div>
      </div>
    </div>
  )
}

// ── ProbeModal ────────────────────────────────────────────────────────────────
//
// Hosts the 3-turn STAR interview.
//
// State machine:
//   idle     → probe_state set → turn 1 question shown
//   typing   → user types answer, clicks Next
//   waiting  → POST /api/ariel/probe/respond in flight
//   turn 2/3 → next question rendered
//   done     → result card shown (positive STAR or flag)
//   closed   → onClose called; onDone(newScore) triggers dashboard re-fetch

interface ProbeModalProps {
  probe:   ProbeState
  onClose: () => void
  onDone:  (newConfidence: number | null) => void
}

export function ProbeModal({ probe: initialProbe, onClose, onDone }: ProbeModalProps) {
  const [probe,        setProbe]        = useState<ProbeState>(initialProbe)
  const [answer,       setAnswer]       = useState('')
  const [sending,      setSending]      = useState(false)
  const [sendError,    setSendError]    = useState<string | null>(null)
  const [retryMessage, setRetryMessage] = useState<string | null>(null)
  const [thinkingLong, setThinkingLong] = useState(false)
  const [attachment,   setAttachment]   = useState<{ name: string; dataUrl: string } | null>(null)
  const thinkingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const textareaRef      = useRef<HTMLTextAreaElement>(null)
  const fileRef          = useRef<HTMLInputElement>(null)

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = ev => setAttachment({ name: file.name, dataUrl: ev.target?.result as string })
    reader.readAsDataURL(file)
    e.target.value = ''
  }

  // Focus textarea on every turn change
  useEffect(() => {
    const t = setTimeout(() => textareaRef.current?.focus(), 50)
    return () => clearTimeout(t)
  }, [probe.turn])

  // 3 s "thinking" indicator — starts when sending begins, clears when done
  useEffect(() => {
    if (sending) {
      thinkingTimerRef.current = setTimeout(
        () => setThinkingLong(true),
        ARIEL_THINKING_THRESHOLD_MS,
      )
    } else {
      if (thinkingTimerRef.current) {
        clearTimeout(thinkingTimerRef.current)
        thinkingTimerRef.current = null
      }
      setThinkingLong(false)
    }
    return () => {
      if (thinkingTimerRef.current) clearTimeout(thinkingTimerRef.current)
    }
  }, [sending])

  // Close on Escape (only while the probe is not done)
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape' && !probe.done) onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [probe.done, onClose])

  async function submitAnswer() {
    const text = answer.trim()
    if ((!text && !attachment) || sending) return
    setSending(true)
    setSendError(null)
    setRetryMessage(null)
    const payload = attachment
      ? `[Attachment: ${attachment.name}]\n${text}`
      : text
    setAttachment(null)
    try {
      await ensureFreshToken()
      const res = await fetch('/api/ariel/probe/respond', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body:    JSON.stringify({
          session_id: probe.session_id,
          entity_id:  probe.entity_id,
          turn:       probe.turn,
          answer:     payload,
        }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error((body as { detail?: string }).detail ?? `HTTP ${res.status}`)
      }
      const data = await res.json()

      // ── LLM timed out / errored — stay on turn 3, show soft message ──────
      if (data.retry_suggested) {
        setRetryMessage(
          data.retry_message ??
          "I couldn't fully evaluate your answer. Let's try one more specific example."
        )
        setAnswer('')   // clear so the user types a fresh attempt
        return
      }

      // ── Evaluation done (turn 3 success) ─────────────────────────────────
      if (data.evaluation_done) {
        setProbe(p => ({
          ...p,
          answers:        { ...p.answers, [p.turn]: answer.trim() },
          done:           true,
          flag_type:      data.flag_type,
          new_confidence: data.new_confidence,
        }))
        return
      }

      // ── Next turn (turns 1–2) ─────────────────────────────────────────────
      setProbe(p => ({
        ...p,
        answers:  { ...p.answers, [p.turn]: answer.trim() },
        turn:     data.turn,
        question: data.next_question,
      }))
      setAnswer('')
    } catch (err) {
      setSendError(err instanceof Error ? err.message : 'Request failed')
    } finally {
      setSending(false)
    }
  }

  const totalTurns  = 3
  const isLastTurn  = probe.turn === totalTurns
  const flagPositive = probe.flag_type === 'none' || probe.flag_type === null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(15,23,42,0.55)', backdropFilter: 'blur(4px)' }}
      onClick={e => { if (e.target === e.currentTarget && !probe.done) onClose() }}
    >
      <div
        className="bg-white rounded-2xl w-full max-w-lg shadow-floating overflow-hidden animate-modal-in"
        style={{ boxShadow: '0 24px 64px rgba(15,23,42,0.22)' }}
      >
        {/* Teal accent bar */}
        <div
          className="h-1"
          style={{ background: `linear-gradient(90deg, ${TOKENS.color.primary}, oklch(0.55 0.18 240))` }}
        />

        {/* Header */}
        <div className="px-5 pt-5 pb-3 flex items-start justify-between">
          <div>
            <div className="flex items-center gap-2 mb-0.5">
              <span style={{ color: TOKENS.color.primary }}><ZapIcon s={14} /></span>
              <h3 className="text-[14px] font-bold text-slate-800">Strengthen Trust</h3>
              <span
                className="inline-flex items-center h-[18px] px-2 rounded-full text-[9.5px] font-bold tracking-wide"
                style={{ background: TOKENS.color.primarySoft, color: TOKENS.color.primary }}
              >
                Evaluated by Ariel
              </span>
            </div>
            <p className="text-[12px] text-slate-500">
              {probe.probe_method ?? 'STAR'} Interview for{' '}
              <span className="font-semibold text-slate-700">{probe.entity_name}</span>
            </p>
          </div>
          {!probe.done && (
            <button
              onClick={onClose}
              className="text-slate-400 hover:text-slate-700 transition p-1 rounded-lg hover:bg-slate-100 active:scale-90"
            >
              <XIcon s={15} />
            </button>
          )}
        </div>

        <div className="px-5 pb-5 space-y-4">
          {/* Progress stepper — 4 labeled steps matching STAR / SCOPE / SIGNAL */}
          {!probe.done && (() => {
            const method = probe.probe_method ?? 'STAR'
            const stepLabels = PROBE_STEP_LABELS[method] ?? PROBE_STEP_LABELS.STAR
            return (
              <div className="flex items-start gap-0">
                {stepLabels.map((label, idx) => {
                  const stepNum = idx + 1
                  const done    = stepNum < probe.turn
                  const active  = stepNum === probe.turn
                  return (
                    <div key={label} className="flex items-start flex-1">
                      <div className="flex flex-col items-center flex-1">
                        <div className="flex items-center w-full">
                          {/* connector left */}
                          <div
                            className="flex-1 h-[2px] rounded-full"
                            style={{ background: idx === 0 ? 'transparent' : done || active ? TOKENS.color.primary : '#E2E8F0', opacity: idx === 0 ? 0 : done ? 0.45 : 1 }}
                          />
                          {/* circle */}
                          <div
                            className="w-6 h-6 rounded-full flex items-center justify-center shrink-0 text-[10px] font-bold transition-all"
                            style={{
                              background: done || active ? TOKENS.color.primary : '#E2E8F0',
                              color:      done || active ? '#fff' : '#94A3B8',
                              transform:  active ? 'scale(1.15)' : 'scale(1)',
                            }}
                          >
                            {done ? '✓' : stepNum}
                          </div>
                          {/* connector right */}
                          <div
                            className="flex-1 h-[2px] rounded-full"
                            style={{ background: idx === stepLabels.length - 1 ? 'transparent' : done ? TOKENS.color.primary : '#E2E8F0', opacity: idx === stepLabels.length - 1 ? 0 : done ? 0.45 : 1 }}
                          />
                        </div>
                        <span
                          className="mt-1 text-[10px] font-medium text-center leading-tight whitespace-nowrap"
                          style={{ color: active ? TOKENS.color.primary : done ? TOKENS.color.primary : '#94A3B8', opacity: done ? 0.7 : 1 }}
                        >
                          {label}
                        </span>
                      </div>
                    </div>
                  )
                })}
              </div>
            )
          })()}

          {/* ── Done state ─────────────────────────────────────────────────── */}
          {probe.done ? (
            <div className="space-y-3">
              <div
                className="rounded-xl px-4 py-4 flex items-start gap-3"
                style={{
                  background: flagPositive ? 'oklch(0.97 0.04 155)' : 'oklch(0.98 0.02 25)',
                  border:     `1px solid ${flagPositive ? 'oklch(0.87 0.08 155)' : 'oklch(0.90 0.04 25)'}`,
                }}
              >
                <span className="text-[18px] mt-0.5" aria-hidden="true">
                  {flagPositive ? '✅' : '⚠️'}
                </span>
                <div className="flex-1 min-w-0">
                  <p className={`text-[13px] font-bold mb-1 ${flagPositive ? 'text-teal-800' : 'text-slate-700'}`}>
                    {flagPositive ? 'Evidence recorded' : 'Shallow response detected'}
                  </p>
                  <p className="text-[12px] leading-relaxed text-slate-500">
                    {flagPositive
                      ? `Confidence updated to ${probe.new_confidence?.toFixed(1) ?? '—'}. The dashboard will reflect this shortly.`
                      : `This response was flagged as ${probe.flag_type?.replace('_', ' ')}. A negative signal has been recorded. Try again with more specific examples.`
                    }
                  </p>
                  {probe.new_confidence !== null && (
                    <p className="mt-2">
                      <span
                        className="inline-flex items-center h-[20px] px-2 rounded-md text-[11px] font-bold tabular-nums"
                        style={{
                          background: flagPositive ? 'oklch(0.94 0.08 155)' : 'oklch(0.94 0.04 25)',
                          color:      flagPositive ? 'oklch(0.30 0.12 155)' : 'oklch(0.45 0.12 25)',
                        }}
                      >
                        {probe.new_confidence.toFixed(1)} confidence
                      </span>
                    </p>
                  )}
                </div>
              </div>
              <button
                onClick={() => onDone(probe.new_confidence)}
                className="w-full h-9 rounded-xl text-[12.5px] font-semibold transition active:scale-[0.98]"
                style={{ background: TOKENS.color.primary, color: '#fff' }}
              >
                Back to Dashboard
              </button>
            </div>
          ) : (
            /* ── Active turn ─────────────────────────────────────────────── */
            <>
              {/* Ariel's question card */}
              <div
                className="rounded-xl px-4 py-3.5"
                style={{ background: 'oklch(0.975 0.00 0)', border: '1px solid oklch(0.93 0.00 0)' }}
              >
                <p className="text-[10.5px] font-bold tracking-widest uppercase text-slate-400 mb-1.5">
                  {(PROBE_STEP_LABELS[probe.probe_method ?? 'STAR'] ?? PROBE_STEP_LABELS.STAR)[probe.turn - 1] ?? 'Question'}
                </p>
                <p className="text-[13px] text-slate-700 leading-relaxed">{probe.question}</p>
              </div>

              {/* Soft retry message — shown when LLM timed out on previous attempt */}
              {retryMessage && (
                <div
                  className="rounded-xl px-3.5 py-3 flex items-start gap-2.5"
                  style={{
                    background: 'oklch(0.98 0.03 60)',
                    border:     '1px solid oklch(0.88 0.07 60)',
                  }}
                >
                  <span className="text-[15px] shrink-0 mt-0.5" aria-hidden="true">🤔</span>
                  <p className="text-[12px] text-amber-900 leading-relaxed">{retryMessage}</p>
                </div>
              )}

              {/* Hidden file input */}
              <input
                ref={fileRef}
                type="file"
                accept="image/*,.pdf,.txt,.py,.js,.ts,.java,.go,.rs,.cpp,.c,.cs"
                className="hidden"
                onChange={handleFileChange}
              />

              {/* Answer textarea */}
              <textarea
                ref={textareaRef}
                value={answer}
                onChange={e => setAnswer(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                    e.preventDefault()
                    submitAnswer()
                  }
                }}
                rows={4}
                placeholder="Share a specific, concrete example…"
                className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-[13px] text-slate-700 leading-relaxed resize-none focus:outline-none focus:ring-2 focus:border-transparent placeholder:text-slate-300"
                style={{ '--tw-ring-color': TOKENS.color.primary } as React.CSSProperties}
              />

              {/* Attachment preview chip */}
              {attachment && (
                <div
                  className="flex items-center gap-2.5 px-3 py-2 rounded-xl"
                  style={{ background: TOKENS.color.primarySoft, border: `1px solid oklch(0.85 0.07 170)` }}
                >
                  {attachment.dataUrl.startsWith('data:image') ? (
                    <img src={attachment.dataUrl} alt="" className="w-7 h-7 rounded-lg object-cover border border-white/60 shrink-0" />
                  ) : (
                    <span
                      className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0"
                      style={{ background: TOKENS.color.primary }}
                    >
                      <FileText s={13} />
                    </span>
                  )}
                  <div className="flex-1 min-w-0">
                    <p className="text-[10px] font-bold uppercase tracking-wide" style={{ color: TOKENS.color.primary }}>
                      Evidence attached
                    </p>
                    <p className="text-[11.5px] text-slate-600 truncate leading-tight">{attachment.name}</p>
                  </div>
                  <button
                    onClick={() => setAttachment(null)}
                    aria-label={`Remove attachment ${attachment.name}`}
                    title="Remove attachment"
                    className="shrink-0 w-5 h-5 flex items-center justify-center rounded-full text-slate-400 hover:text-slate-700 hover:bg-white/60 focus-visible:text-slate-700 transition text-[13px]"
                  >×</button>
                </div>
              )}

              {/* Hard error */}
              {sendError && <p className="text-[12px] text-red-500">{sendError}</p>}

              {/* Thinking indicator */}
              {sending && thinkingLong && (
                <div className="flex items-center gap-2 text-[12px] text-slate-400 animate-pulse">
                  <SpinnerIcon s={12} />
                  <span>Ariel is analysing your STAR logic…</span>
                </div>
              )}

              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2 shrink-0">
                  {/* Paperclip — attach evidence */}
                  <button
                    onClick={() => fileRef.current?.click()}
                    title="Attach a file or screenshot as evidence"
                    aria-label="Attach a file or screenshot as evidence"
                    className="w-7 h-7 flex items-center justify-center rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition"
                  >
                    <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                      <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66L9.41 17.41a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
                    </svg>
                  </button>
                  <span className="text-[11px] text-slate-400">⌘↵ to submit</span>
                </div>
                <button
                  onClick={submitAnswer}
                  disabled={sending || (!answer.trim() && !attachment)}
                  className="inline-flex items-center justify-center gap-1.5 h-10 px-6 rounded-xl text-[13px] font-semibold transition active:scale-[0.97] disabled:opacity-40 disabled:cursor-not-allowed"
                  style={{ background: TOKENS.color.primary, color: '#fff', minWidth: '110px' }}
                >
                  {sending && !thinkingLong ? <SpinnerIcon s={12} /> : null}
                  {sending ? (thinkingLong ? 'Analysing…' : 'Sending…') : isLastTurn ? 'Finish' : 'Next →'}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ── ManualReviewCallout (banner at top of dashboard) ─────────────────────────

function ManualReviewCallout({
  entities, onReview,
}: { entities: TrustProfileEntity[]; onReview: (e: TrustProfileEntity) => void }) {
  const flagged = entities.filter(e => e.manual_review_required)
  if (flagged.length === 0) return null
  return (
    <div
      className="rounded-xl px-4 py-3.5 flex items-start gap-3"
      style={{ background: 'oklch(0.98 0.03 60)', border: '1px solid oklch(0.88 0.07 60)' }}
    >
      <span className="shrink-0 text-amber-500 mt-0.5"><WarnTriangle s={16} /></span>
      <div className="flex-1 min-w-0">
        <p className="text-[12.5px] font-semibold text-slate-700 mb-0.5">
          {flagged.length === 1
            ? '1 skill requires manual review'
            : `${flagged.length} skills require manual review`}
        </p>
        <p className="text-[12px] text-slate-500 leading-relaxed">
          A contradiction or shallow STAR response was detected. Click a skill below
          to see the flag reason and re-submit evidence.
        </p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {flagged.map(e => (
            <button
              key={e.entity_id}
              onClick={() => onReview(e)}
              className="inline-flex items-center gap-1 h-[22px] px-2 rounded-md text-[11px] font-medium transition active:scale-[0.97]"
              style={{
                background: 'oklch(0.96 0.06 60)',
                color:      'oklch(0.40 0.12 50)',
                border:     '1px solid oklch(0.88 0.07 60)',
              }}
            >
              {e.name}
              <span className="opacity-60 text-[9px] ml-0.5">→ Review</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── AuthWallCallout ───────────────────────────────────────────────────────────
//
// Shown when the API returns auth_wall status (expired LinkedIn li_at cookie).
// Mirrors AnalysisAuthWall in JobCard but adapted for the Trust context.

function AuthWallCallout() {
  return (
    <div
      className="rounded-xl px-4 py-3.5 flex items-start gap-3"
      style={{ background: 'oklch(0.97 0.04 255)', border: '1px solid oklch(0.85 0.08 255)' }}
    >
      <span className="text-[15px] mt-0.5" aria-hidden="true">🔒</span>
      <div className="flex-1 min-w-0">
        <p className="text-[12.5px] font-semibold text-slate-700 mb-0.5">
          LinkedIn session expired
        </p>
        <p className="text-[12px] text-slate-500 leading-relaxed">
          The scraper hit a LinkedIn login wall — the{' '}
          <code className="font-mono text-[11px]">li_at</code> cookie needs refreshing.
          Update <code className="font-mono text-[11px]">LINKEDIN_LI_AT</code> in{' '}
          <code className="font-mono text-[11px]">backend/.env</code>, delete the browser
          profile, and restart the server.
        </p>
      </div>
      <a
        href="https://www.linkedin.com/feed/"
        target="_blank"
        rel="noopener noreferrer"
        className="shrink-0 inline-flex items-center gap-1.5 h-8 px-3 rounded-lg text-[11.5px] font-semibold transition active:scale-[0.97]"
        style={{
          background: 'oklch(0.94 0.06 255)',
          color:      'oklch(0.35 0.18 255)',
          border:     '1px solid oklch(0.85 0.08 255)',
        }}
      >
        <LinkIcon s={11} />
        Fix Connection
      </a>
    </div>
  )
}

// ── Category filter tabs ──────────────────────────────────────────────────────

type FilterCategory = 'all' | EntityType

const FILTER_TABS: { value: FilterCategory; label: string }[] = [
  { value: 'all',        label: 'All'        },
  { value: 'skill',      label: 'Skills'     },
  { value: 'trait',      label: 'Traits'     },
  { value: 'domain',     label: 'Domain'     },
  { value: 'experience', label: 'Experience' },
]

// ── Skeleton ──────────────────────────────────────────────────────────────────

function DashboardSkeleton() {
  return (
    <div className="space-y-3" aria-busy="true" aria-label="Loading trust scores">
      {/* Radar + stats skeleton */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div
          className="md:col-span-2 rounded-2xl animate-pulse"
          style={{ height: 280, background: 'oklch(0.94 0.00 0)' }}
        />
        <div
          className="rounded-2xl animate-pulse"
          style={{ height: 280, background: 'oklch(0.94 0.00 0)', animationDelay: '80ms' }}
        />
      </div>
      {/* Entity row skeletons */}
      {[80, 65, 50, 90, 70].map((w, i) => (
        <div
          key={i}
          className="h-[54px] rounded-xl animate-pulse"
          style={{ background: 'oklch(0.94 0.00 0)', animationDelay: `${(i + 2) * 80}ms` }}
        />
      ))}
    </div>
  )
}

// ── StatRow ───────────────────────────────────────────────────────────────────

function StatRow({
  label, value, highlight = false, warn = false,
}: { label: string; value: number; highlight?: boolean; warn?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-slate-500">{label}</span>
      <span className={`font-bold tabular-nums ${
        warn ? 'text-amber-600' : highlight ? 'text-teal-600' : 'text-slate-700'
      }`}>
        {value}
      </span>
    </div>
  )
}

// ── TrustRadarChart ───────────────────────────────────────────────────────────

function TrustRadarChart({ data }: { data: RadarDatum[] }) {
  const hasSyntax = data.some(d => d.syn_value > 0)
  return (
    <div className="flex flex-col items-center">
      <div className="flex items-center justify-between w-full mb-2 px-1">
        <p className="text-[10.5px] font-bold tracking-widest uppercase text-slate-400">
          Confidence Radar
        </p>
        {!hasSyntax && (
          <span
            className="inline-flex items-center gap-1 h-[18px] px-2 rounded text-[9.5px] font-semibold"
            style={{ background: 'oklch(0.96 0.05 50)', color: 'oklch(0.48 0.14 50)' }}
            title="No Ariel-verified challenges yet. Complete a STAR probe or Whiteboard Challenge to unlock the inner polygon."
          >
            ⚠ Pending Ariel Verification
          </span>
        )}
      </div>
      <div className="relative w-full" style={{ maxWidth: 340 }}>
        <Suspense fallback={
          <div
            className="flex items-center justify-center rounded-xl"
            style={{ height: 240, background: 'oklch(0.975 0.00 0)', border: '1px solid oklch(0.93 0.00 0)' }}
          >
            <div className="flex items-center gap-2 text-[12px] text-slate-400">
              <SpinnerIcon s={14} />Loading chart…
            </div>
          </div>
        }>
          <RadarChartLazy data={data} />
        </Suspense>
        <span className="absolute top-1 right-2 text-[9.5px] text-slate-300 font-medium">100</span>
      </div>
      {/* Category scores row */}
      <div className="mt-1 flex items-center gap-4 flex-wrap justify-center">
        {data.map(d => (
          <div key={d.category} className="flex flex-col items-center gap-0.5">
            <span className="text-[10px] font-medium text-slate-500">{d.category}</span>
            <span className="text-[11px] tabular-nums" style={{ color: RADAR_TEAL }}>
              {d.arch_value.toFixed(1)}
              {d.syn_value > 0 && (
                <span className="ml-1" style={{ color: RADAR_VIOLET }}>
                  / {d.syn_value.toFixed(1)}
                </span>
              )}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── UploadZone ────────────────────────────────────────────────────────────────
//
// Shown when entities.length === 0 after a successful data fetch.
// Supports drag-and-drop OR click-to-browse.
// On a successful upload it calls onUploaded() so the dashboard re-fetches.

interface UploadZoneProps {
  userId:     string
  onUploaded: () => void
}

function UploadZone({ userId, onUploaded }: UploadZoneProps) {
  const [isDragging,  setIsDragging]  = useState(false)
  const [uploading,   setUploading]   = useState(false)
  const [uploadDone,  setUploadDone]  = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [stats,       setStats]       = useState<{
    entities_ingested: number
    overall_trust_score: number
  } | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  async function handleFiles(fileList: FileList | null) {
    if (!fileList || fileList.length === 0) return
    const allowed = Array.from(fileList).filter(
      f => f.name.endsWith('.pdf') || f.name.endsWith('.docx')
    )
    if (allowed.length === 0) {
      setUploadError('Only PDF or DOCX files are supported.')
      return
    }

    setUploading(true)
    setUploadError(null)
    try {
      const form = new FormData()
      allowed.forEach(f => form.append('files', f))

      await ensureFreshToken()
      const res = await fetch('/api/profile/cv-upload', {
        method:  'POST',
        headers: getAuthHeaders(),
        body:    form,
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error((body as { detail?: string }).detail ?? `HTTP ${res.status}`)
      }
      const data = await res.json()
      setStats({
        entities_ingested:   data.entities_ingested  ?? 0,
        overall_trust_score: data.overall_trust_score ?? 0,
      })
      setUploadDone(true)
      // Give a short pause so the user sees the success state, then re-fetch
      setTimeout(() => onUploaded(), 1800)
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : 'Upload failed.')
    } finally {
      setUploading(false)
    }
  }

  function onDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setIsDragging(false)
    handleFiles(e.dataTransfer.files)
  }

  // ── Success state ─────────────────────────────────────────────────────────
  if (uploadDone && stats) {
    return (
      <div
        className="rounded-2xl border border-teal-100 flex flex-col items-center gap-4 py-12 px-6 text-center"
        style={{ background: 'oklch(0.97 0.04 155)' }}
      >
        <span className="text-[36px]" aria-hidden="true">✅</span>
        <div>
          <p className="text-[14px] font-bold text-teal-800">
            CV uploaded — building your Confidence Matrix
          </p>
          <p className="text-[12.5px] text-teal-700 mt-1">
            {stats.entities_ingested} entities extracted · overall score {stats.overall_trust_score.toFixed(1)}
          </p>
        </div>
        <div className="flex items-center gap-2 text-[12px] text-teal-600 animate-pulse">
          <SpinnerIcon s={13} />
          Loading your matrix…
        </div>
      </div>
    )
  }

  // ── Upload state ─────────────────────────────────────────────────────────
  return (
    <div
      onDragOver={e => { e.preventDefault(); setIsDragging(true) }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={onDrop}
      onClick={() => !uploading && inputRef.current?.click()}
      className="rounded-2xl border-2 border-dashed cursor-pointer transition-all select-none"
      style={{
        borderColor: isDragging ? TOKENS.color.primary : 'oklch(0.85 0.00 0)',
        background:  isDragging ? TOKENS.color.primarySoft : 'oklch(0.985 0.00 0)',
        padding:     '48px 32px',
      }}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.docx"
        multiple
        className="hidden"
        onChange={e => handleFiles(e.target.files)}
      />

      <div className="flex flex-col items-center gap-4 text-center pointer-events-none">
        {/* Icon */}
        <div
          className="inline-flex items-center justify-center rounded-2xl"
          style={{
            width: 64, height: 64,
            background: isDragging ? 'oklch(0.94 0.08 155)' : 'oklch(0.94 0.00 0)',
          }}
        >
          {uploading ? (
            <SpinnerIcon s={28} />
          ) : (
            <svg width={28} height={28} viewBox="0 0 24 24" fill="none"
              stroke={isDragging ? TOKENS.color.primary : '#94A3B8'}
              strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
            >
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
          )}
        </div>

        {/* Headline */}
        <div>
          <p className="text-[15px] font-bold text-slate-800">
            {uploading
              ? 'Uploading and extracting entities…'
              : 'Upload your CV to start building your Confidence Matrix'
            }
          </p>
          {!uploading && (
            <p className="text-[12.5px] text-slate-400 mt-1.5 leading-relaxed max-w-sm">
              Drop a PDF or DOCX here, or click to browse.
              Ariel will extract your skills, experience, and domain knowledge
              and score each entity based on the evidence in your CV.
            </p>
          )}
        </div>

        {/* Format hint */}
        {!uploading && (
          <div className="flex items-center gap-2">
            {['PDF', 'DOCX'].map(fmt => (
              <span
                key={fmt}
                className="inline-flex items-center h-6 px-2.5 rounded-full text-[11px] font-semibold"
                style={{ background: 'oklch(0.93 0.00 0)', color: '#64748B' }}
              >
                {fmt}
              </span>
            ))}
          </div>
        )}

        {/* Error */}
        {uploadError && (
          <p className="text-[12px] text-red-500 mt-1">{uploadError}</p>
        )}
      </div>
    </div>
  )
}

// ── Status pill config for CapabilityRow ─────────────────────────────────────
// ORCHESTRATION_ONLY is intentionally silent — no pill, no noise.
// Only the two ends of the spectrum get a visible signal.

const STATUS_PILL: Record<string, { label: string | null; bg: string; text: string; hint?: string } | null> = {
  VERIFIED_MANUAL:    { label: 'Verified',   bg: '#ECFDF5', text: '#065F46' },
  ORCHESTRATION_ONLY: null,
  UNVERIFIED:         { label: null,         bg: '#FFFBEB', text: '#92400E', hint: 'Syntax mastery unverified' },
}

function validatePillLabel(entityType: EntityType | string | undefined): string {
  if (entityType === 'domain')     return 'Validate Domain'
  if (entityType === 'experience') return 'Validate Experience'
  if (entityType === 'trait')      return 'Validate Trait'
  return 'Validate Skill'
}

// ── CapabilityRow ─────────────────────────────────────────────────────────────
// Premium single-row design for the /capabilities page.
// Does NOT use the accordion — each row is scannable at a glance.

interface CapabilityRowProps {
  entity:   TrustProfileEntity
  onVerify: (entity: TrustProfileEntity) => void
  onProbe:  (entity: TrustProfileEntity) => void
  probing:  boolean
  rank?:    number   // optional 1-based rank number shown to the left of the name
}

function CapabilityRow({ entity, onVerify, onProbe, probing, rank }: CapabilityRowProps) {
  const vl   = entity.verification_level ?? 'UNVERIFIED'
  const pill = STATUS_PILL[vl]
  const pct  = Math.min(100, Math.max(0, entity.confidence_score))
  const score = entity.confidence_score.toFixed(1)

  // Action progression: Validate → Strengthen → (done)
  const showVerify     = vl === 'UNVERIFIED'
  const showStrengthen = vl === 'ORCHESTRATION_ONLY' && !entity.manual_review_required && entity.confidence_score < 70

  // Semantic design-system tokens (globals.css):
  //   VERIFIED_MANUAL    → success (emerald-600)
  //   ORCHESTRATION_ONLY → primary (teal-600) — brand-aligned "in progress via AI"
  //   UNVERIFIED         → warn (amber-600)
  const barColor = vl === 'VERIFIED_MANUAL'    ? 'var(--ja-success)'
                 : vl === 'ORCHESTRATION_ONLY' ? 'var(--ja-primary)'
                 :                               'var(--ja-warn)'

  const categoryLabel = (entity.entity_type ?? 'skill').toUpperCase()

  // Dynamic status label with numeric score baked in
  const statusLabel = vl === 'VERIFIED_MANUAL'
    ? null  // pill handles it
    : vl === 'ORCHESTRATION_ONLY'
      ? `${score} · Orchestration`
      : null  // pill handles it

  return (
    <div
      className="flex flex-col gap-2.5 sm:grid sm:items-center sm:gap-x-4 sm:grid-cols-[minmax(180px,2fr)_minmax(100px,1fr)_90px_16px_minmax(120px,1fr)_minmax(100px,1fr)] px-5 py-3.5 rounded-xl bg-white border border-slate-100 hover:border-slate-200 hover:-translate-y-0.5 transition-all duration-200 ease-out group"
      style={{ boxShadow: '0 1px 3px rgba(15,23,42,0.05)' }}
    >
      {/* ① Name + type (+ optional rank number) ───────────────────── */}
      <div className="flex items-center gap-2.5 overflow-hidden">
        {rank !== undefined && (
          <span className="text-[11px] font-bold tabular-nums text-slate-300 w-4 shrink-0 text-right">
            {rank}
          </span>
        )}
        <div className="overflow-hidden min-w-0">
          <p className="text-[14px] font-semibold text-slate-900 leading-tight overflow-hidden text-ellipsis whitespace-nowrap" title={entity.name}>
            {entity.name}
          </p>
          <p className="text-[10px] font-medium tracking-widest uppercase text-slate-400 mt-0.5">
            {categoryLabel}
          </p>
        </div>
      </div>

      {/* ② Progress bar — premium rounded rail with gradient fill + glow.
          Already sm:+ only; simply doesn't render in the mobile stack. */}
      <div className="hidden sm:flex items-center w-full">
        <div
          className="w-full h-[7px] rounded-full bg-slate-100 overflow-hidden"
          style={{ boxShadow: 'inset 0 1px 2px rgba(15,23,42,0.08)' }}
        >
          <div
            className="h-full rounded-full"
            style={{
              width:      `${pct}%`,
              background: `linear-gradient(90deg, color-mix(in oklab, ${barColor} 65%, white), ${barColor})`,
              boxShadow:  `0 0 8px color-mix(in oklab, ${barColor} 45%, transparent)`,
              transition: 'width 500ms cubic-bezier(0.22,1,0.36,1)',
            }}
          />
        </div>
      </div>

      {/* ③ Numeric score + confidence weight tooltip ───────────────── */}
      <div className="flex items-center gap-1.5 sm:justify-end">
        <span className="text-[13px] font-bold tabular-nums text-slate-700">{score}</span>
        <span className="text-[10.5px] text-slate-400">/100</span>
        <span
          tabIndex={0}
          className="relative group/tip inline-flex items-center justify-center w-[15px] h-[15px] rounded-full border border-slate-200 text-[9px] font-bold text-slate-400 cursor-default select-none hover:border-teal-400 hover:text-teal-500 focus-visible:border-teal-400 focus-visible:text-teal-500 transition-colors"
          aria-label={`Confidence Weight: x${(entity.evidence_multiplier ?? 0.5).toFixed(1)} — Based on ${entity.evidence_count ?? 0} Ariel-verified challenges`}
        >
          i
          <span
            className="pointer-events-none absolute z-20 bottom-full right-0 mb-1.5 w-max max-w-[210px] rounded-lg px-2.5 py-2 text-[11px] leading-snug text-white opacity-0 group-hover/tip:opacity-100 group-focus-within/tip:opacity-100 transition-opacity"
            style={{ background: 'oklch(0.20 0.03 250)', boxShadow: '0 4px 12px rgba(0,0,0,0.25)' }}
          >
            Confidence Weight: ×{(entity.evidence_multiplier ?? 0.5).toFixed(1)}
            <br />
            Based on {entity.evidence_count ?? 0} Ariel-verified challenges
          </span>
        </span>
      </div>

      {/* ④ Gap spacer — sm:+ grid alignment only; not needed in the mobile stack */}
      <div className="hidden sm:block" />

      {/* ⑤ Status ───────────────────────────────────────────────────── */}
      <div className="overflow-hidden">
        {pill ? (
          <div>
            <span
              className="inline-flex items-center h-[22px] px-3 rounded-full text-[11px] font-semibold"
              style={{ background: pill.bg, color: pill.text }}
            >
              {pill.label ?? validatePillLabel(entity.entity_type)}
            </span>
            {pill.hint && (
              <p className="text-[10px] text-slate-400 mt-0.5 leading-tight">{pill.hint}</p>
            )}
          </div>
        ) : statusLabel ? (
          <span className="text-[11.5px] font-medium text-slate-500 tabular-nums">
            {statusLabel}
          </span>
        ) : null}
      </div>

      {/* ⑥ Actions — always visible + 44px tall on mobile (no hover on touch);
          fades in on hover/focus only at sm: and up, matching the original. */}
      <div className="flex items-center gap-2 flex-wrap justify-start sm:justify-end opacity-100 sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100 transition-opacity">
        {showVerify && (
          <button
            onClick={() => onProbe(entity)}
            disabled={probing}
            className="h-11 sm:h-8 px-3.5 rounded-lg text-[12px] font-semibold text-white bg-ja-primary hover:bg-ja-primaryHover transition active:scale-[0.97] disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap"
          >
            {probing ? <SpinnerIcon s={12} /> : 'Verify Mastery'}
          </button>
        )}
        {showStrengthen && (
          <button
            onClick={() => onProbe(entity)}
            disabled={probing}
            className="h-11 sm:h-8 px-3.5 rounded-lg text-[12px] font-semibold text-slate-600 border border-slate-200 bg-white hover:bg-slate-50 transition active:scale-[0.97] disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
          >
            {probing ? <SpinnerIcon s={12} /> : 'Strengthen'}
          </button>
        )}
        {vl === 'VERIFIED_MANUAL' && (
          <span className="text-[13px] text-emerald-500 font-bold select-none">✓</span>
        )}
      </div>
    </div>
  )
}

// ── WhiteboardChallengeModal ──────────────────────────────────────────────────
// Used by both CapabilitiesList and TrustDashboard.
// Attachment flow: reads the file client-side as a data URL, displays a preview
// chip, and injects the filename into the session context on "Accept".

interface WhiteboardChallengeModalProps {
  entity:   TrustProfileEntity
  session:  { session_id: string; first_prompt: string } | null
  loading:  boolean
  onClose:  () => void
}

function WhiteboardChallengeModal({ entity, session, loading, onClose }: WhiteboardChallengeModalProps) {
  const [attachment, setAttachment] = useState<{ name: string; dataUrl: string } | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = ev => {
      setAttachment({ name: file.name, dataUrl: ev.target?.result as string })
    }
    reader.readAsDataURL(file)
    // reset input so the same file can be re-selected
    e.target.value = ''
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4"
      style={{ background: 'rgba(8,16,36,0.72)', backdropFilter: 'blur(6px)' }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Whiteboard Challenge: ${entity.name}`}
        // Dark command-overlay variant (§3.2) — border-white/10 + shadow-floating
        // on top of its existing per-section dark fills; those stay untouched.
        className="w-full max-w-lg rounded-2xl overflow-hidden border border-white/10 shadow-floating animate-modal-in"
        style={{ boxShadow: '0 32px 80px rgba(0,0,0,0.35), 0 0 0 1px rgba(255,255,255,0.06)' }}
      >
        {/* Dark header band */}
        <div
          className="px-6 pt-5 pb-4 flex items-start justify-between gap-3"
          style={{ background: 'oklch(0.18 0.03 250)' }}
        >
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <svg width={12} height={12} viewBox="0 0 20 20" fill="none" stroke="oklch(0.65 0.18 170)" strokeWidth={1.8}>
                <rect x="2" y="3" width="16" height="11" rx="1.5"/>
                <path d="M6 17h8M10 14v3"/><path d="M5.5 9.5l2 2 4-4" strokeLinecap="round"/>
              </svg>
              <span className="text-[10px] font-bold tracking-widest uppercase" style={{ color: 'oklch(0.65 0.18 170)' }}>
                Whiteboard Challenge
              </span>
              <span
                className="inline-flex items-center h-[16px] px-1.5 rounded text-[9px] font-bold tracking-wide"
                style={{ background: 'oklch(0.30 0.06 170)', color: 'oklch(0.75 0.18 170)' }}
              >
                Evaluated by Ariel
              </span>
            </div>
            <h3 className="text-[16px] font-bold text-white leading-tight">{entity.name}</h3>
            <p className="text-[11.5px]" style={{ color: 'oklch(0.60 0.04 250)' }}>
              No AI assistance · Score submitted to Ariel
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close challenge dialog"
            title="Close"
            className="h-7 w-7 flex items-center justify-center rounded-lg text-[16px] transition hover:bg-white/10 focus-visible:bg-white/10"
            style={{ color: 'oklch(0.55 0.04 250)' }}
          >×</button>
        </div>

        {/* Body */}
        <div className="bg-white px-6 py-5 space-y-4">
          {loading ? (
            <div className="flex items-center gap-2.5 text-[13px] text-slate-400 py-8 justify-center">
              <SpinnerIcon s={14} /> Preparing your challenge…
            </div>
          ) : !session ? (
            <div className="flex flex-col items-center gap-3 py-8 text-center">
              <span className="text-[28px]" aria-hidden="true">⚡</span>
              <p className="text-[13px] font-semibold text-slate-700">Ready to verify {entity.name}</p>
              <p className="text-[12px] text-slate-400 max-w-[280px] leading-relaxed">
                Ariel will ask you a hands-on challenge. Demonstrate your mastery without AI assistance.
              </p>
              <div className="flex items-center gap-2 text-[12px] text-slate-400 animate-pulse mt-1">
                <SpinnerIcon s={12} /> Initialising session…
              </div>
            </div>
          ) : session ? (
            <>
              {/* Ariel's question card */}
              <div
                className="rounded-xl p-4 space-y-1"
                style={{ background: 'oklch(0.97 0.01 250)', border: '1px solid oklch(0.88 0.04 250)' }}
              >
                <p className="text-[10px] font-bold tracking-widest uppercase mb-2" style={{ color: 'oklch(0.58 0.12 250)' }}>
                  Ariel's question
                </p>
                <p className="text-[13.5px] text-slate-800 leading-relaxed font-medium">
                  {session.first_prompt}
                </p>
              </div>

              {/* Attachment row */}
              <div className="flex items-center gap-3">
                <input
                  ref={fileRef}
                  type="file"
                  accept="image/*,.pdf,.txt,.py,.js,.ts,.java,.go,.rs,.cpp,.c,.cs"
                  className="hidden"
                  onChange={handleFileChange}
                />
                <button
                  onClick={() => fileRef.current?.click()}
                  className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg text-[11.5px] font-medium text-slate-500 border border-slate-200 hover:bg-slate-50 transition"
                  title="Attach a screenshot or code file as evidence"
                >
                  {/* Paperclip icon */}
                  <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66L9.41 17.41a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
                  </svg>
                  Attach evidence
                </button>
                {attachment && (
                  <div className="flex items-center gap-1.5 flex-1 min-w-0">
                    {attachment.dataUrl.startsWith('data:image') && (
                      <img
                        src={attachment.dataUrl}
                        alt="attachment preview"
                        className="w-7 h-7 rounded object-cover border border-slate-200 shrink-0"
                      />
                    )}
                    <span className="text-[11px] text-slate-600 truncate">{attachment.name}</span>
                    <button
                      onClick={() => setAttachment(null)}
                      aria-label={`Remove attachment ${attachment.name}`}
                      title="Remove attachment"
                      className="shrink-0 text-[13px] text-slate-400 hover:text-slate-700 focus-visible:text-slate-700 transition"
                    >×</button>
                  </div>
                )}
              </div>

              {/* Rules */}
              <p className="text-[11px] text-slate-400 leading-relaxed">
                Reply in the Ariel chat without AI assistance.
                Session <code className="font-mono text-[10px]">{session.session_id.slice(0, 8)}…</code>
              </p>

              {/* CTA */}
              <button
                onClick={onClose}
                className="w-full h-10 rounded-xl text-[13px] font-bold transition active:scale-[0.98]"
                style={{
                  background:  'linear-gradient(135deg, oklch(0.45 0.18 170), oklch(0.38 0.20 210))',
                  color:       '#fff',
                  boxShadow:   '0 4px 14px oklch(0.45 0.18 170 / 0.35)',
                }}
              >
                Accept the Challenge →
              </button>
            </>
          ) : null /* session loaded but falsy — shouldn't occur */}
        </div>
      </div>
    </div>
  )
}

// ── CapabilitiesList — full entity list for /capabilities page ───────────────
// Reuses the same fetch + sort + filter logic as TrustDashboard.
// Render this inside /app/capabilities/page.tsx.

export function CapabilitiesList({ userId, className = '' }: { userId: string; className?: string }) {
  const [data,    setData]    = useState<TrustScoreResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState<string | null>(null)
  const [filter,  setFilter]  = useState<FilterCategory>('all')
  const [sort,    setSort]    = useState<'score_desc' | 'needs_verification' | 'category'>('score_desc')

  const [probeTarget,   setProbeTarget]  = useState<TrustProfileEntity | null>(null)
  const [probeState,    setProbeState]   = useState<ProbeState | null>(null)
  const [probingId,     setProbingId]    = useState<string | null>(null)
  const [reviewTarget,  setReviewTarget] = useState<TrustProfileEntity | null>(null)
  const [manualTarget,  setManualTarget] = useState<TrustProfileEntity | null>(null)
  const [manualSession, setManualSession]= useState<{session_id: string; first_prompt: string} | null>(null)
  const [manualLoading, setManualLoading]= useState(false)

  const fetchData = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      // Refresh the Supabase session so the Bearer token (and its sub/user_id)
      // always reflect the current authenticated user — prevents stale cached
      // JWTs from routing requests to a different user's profile.
      if (supabase) {
        const { data: { session } } = await supabase.auth.getSession()
        if (session?.access_token) setAuthToken(session.access_token)
      }
      const res = await fetch(`/api/profile/${userId}/trust-score`, {
        headers: getAuthHeaders(), cache: 'no-store',
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setData((await res.json()) as TrustScoreResponse)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load capabilities')
    } finally { setLoading(false) }
  }, [userId])

  useEffect(() => { fetchData() }, [fetchData])

  const entities = data?.entities ?? []
  const filtered = filter === 'all' ? entities : entities.filter(e => e.entity_type === filter)

  // Validate First: strict two-partition sort.
  // Partition 0 = needs action (UNVERIFIED first, then ORCHESTRATION_ONLY), desc by score.
  // Partition 1 = VERIFIED_MANUAL, desc by score.
  // Other sorts: score_desc / category as before.
  const vlRank = (vl: string | undefined) =>
    vl === 'UNVERIFIED' ? 0 : vl === 'ORCHESTRATION_ONLY' ? 1 : 2

  const sorted = [...filtered].sort((a, b) => {
    if (sort === 'needs_verification') {
      const ra = vlRank(a.verification_level)
      const rb = vlRank(b.verification_level)
      if (ra !== rb) return ra - rb
      return b.confidence_score - a.confidence_score
    }
    if (sort === 'category') {
      if (a.entity_type !== b.entity_type) return a.entity_type.localeCompare(b.entity_type)
      return b.confidence_score - a.confidence_score
    }
    return b.confidence_score - a.confidence_score
  })

  const handleProbe = useCallback(async (entity: TrustProfileEntity) => {
    setProbeState(null)
    setProbeTarget(null)
    setProbingId(entity.entity_id)
    try {
      await ensureFreshToken()
      const res = await fetch('/api/ariel/probe/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify({ entity_id: entity.entity_id, entity_name: entity.name, user_id: userId }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      const method = probeMethodFromEntityType(entity.entity_type)
      setProbeTarget(entity)
      setProbeState({
        ...data,
        probe_method: (data.probe_method as 'STAR' | 'SCOPE' | 'SIGNAL') ?? method,
      })
    } catch { /* silent */ } finally { setProbingId(null) }
  }, [userId])

  const handleManualVerify = useCallback(async (entity: TrustProfileEntity) => {
    setManualTarget(entity); setManualLoading(true)
    try {
      await ensureFreshToken()
      const res = await fetch('/api/ariel/manual-verify/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify({ entity_id: entity.entity_id, entity_name: entity.name, user_id: userId }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setManualSession(await res.json())
    } catch { setManualTarget(null) } finally { setManualLoading(false) }
  }, [userId])

  if (loading) return <DashboardSkeleton />
  if (error)   return <p className="text-[13px] text-red-500 py-4">{error}</p>

  const unverifiedCount = entities.filter(e => e.verification_level !== 'VERIFIED_MANUAL').length

  return (
    <div className={`space-y-4 ${className}`}>
      {/* ── Utility Bar ────────────────────────────────────────────────────── */}
      <div
        className="flex items-center gap-3 flex-wrap px-4 py-3 rounded-xl border border-slate-100"
        style={{ background: '#F8FAFC' }}
      >
        {/* Sort group */}
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] font-bold tracking-widest uppercase text-slate-400 pr-1">
            Sort
          </span>
          {([
            ['score_desc',        'Highest Score'],
            ['needs_verification','Validate First'],
            ['category',         'Category'],
          ] as [typeof sort, string][]).map(([val, label]) => (
            <button
              key={val}
              onClick={() => setSort(val)}
              className="h-7 px-3 rounded-lg text-[11.5px] font-medium transition"
              style={
                sort === val
                  ? { background: '#0D9488', color: '#fff' }
                  : { color: '#64748B' }
              }
            >
              {label}
            </button>
          ))}
        </div>

        {/* Divider */}
        <div className="h-5 w-px bg-slate-200 mx-1 hidden sm:block" />

        {/* Filter group */}
        <div className="flex items-center gap-1.5 flex-wrap">
          {FILTER_TABS.map(tab => {
            const count  = tab.value === 'all' ? entities.length : entities.filter(e => e.entity_type === tab.value).length
            const active = filter === tab.value
            return (
              <button
                key={tab.value}
                onClick={() => setFilter(tab.value)}
                className="inline-flex items-center gap-1.5 h-7 px-3 rounded-lg text-[11.5px] font-medium transition"
                style={
                  active
                    ? { background: '#0D9488', color: '#fff' }
                    : { color: '#64748B' }
                }
              >
                {tab.label}
                <span
                  className="h-[16px] min-w-[16px] px-1 rounded-full text-[9px] font-bold tabular-nums inline-flex items-center justify-center"
                  style={
                    active
                      ? { background: 'rgba(255,255,255,0.25)', color: '#fff' }
                      : { background: '#E2E8F0', color: '#94A3B8' }
                  }
                >
                  {count}
                </span>
              </button>
            )
          })}
        </div>

        {/* Summary */}
        {unverifiedCount > 0 && (
          <span className="ml-auto text-[11px] text-slate-400 hidden sm:block">
            {unverifiedCount} awaiting verification
          </span>
        )}
      </div>

      {/* ── Capability rows ─────────────────────────────────────────────────── */}
      <div className="space-y-2">
        {sorted.length === 0 ? (
          <p className="text-center py-12 text-[13px] text-slate-400">
            No capabilities in this category.
          </p>
        ) : sorted.map(entity => (
          <CapabilityRow
            key={entity.entity_id}
            entity={entity}
            onVerify={handleManualVerify}
            onProbe={handleProbe}
            probing={probingId === entity.entity_id}
          />
        ))}
      </div>

      {/* Modals (same as TrustDashboard) */}
      {probeState && (
        <ProbeModal
          key={probeState.entity_id}
          probe={probeState}
          onClose={() => { setProbeState(null); setProbeTarget(null) }}
          onDone={(_c: number | null) => { setProbeState(null); setProbeTarget(null); fetchData() }}
        />
      )}
      {reviewTarget && (
        <ManualReviewModal
          entity={reviewTarget}
          onClose={() => setReviewTarget(null)}
          onDone={() => { setReviewTarget(null); fetchData() }}
        />
      )}
      {manualTarget && (
        <WhiteboardChallengeModal
          entity={manualTarget}
          session={manualSession}
          loading={manualLoading}
          onClose={() => { setManualTarget(null); setManualSession(null) }}
        />
      )}
    </div>
  )
}

// ── TrustDashboard (root) ─────────────────────────────────────────────────────

interface TrustDashboardProps {
  userId:         string
  showAuthWall?:  boolean   // pass true when the LinkedIn feed is auth_wall status
  className?:     string
  /** Fired with the backend's overall_trust_score (and the three-pillar
   *  breakdown, when present) every time fetchData resolves — lets a parent
   *  (e.g. Overview's System Confidence Score card) mirror the same numbers
   *  without firing a second /trust-score request of its own. */
  onScoreChange?: (score: number, breakdown?: ScoreBreakdown) => void
  /** Bump this (e.g. ChatContext's profileVersion) to force a silent re-fetch —
   *  used when Ariel updates the Master Profile mid-session so the score
   *  reflects it without the user reloading the page. Only the initial
   *  mount-time fetch shows the loading skeleton; refetches triggered by a
   *  version bump update in place so the UI never flashes back to a
   *  skeleton mid-session. */
  profileVersion?: number
}

export function TrustDashboard({
  userId, showAuthWall = false, className = '', onScoreChange, profileVersion,
}: TrustDashboardProps) {
  const [data,      setData]      = useState<TrustScoreResponse | null>(null)
  const [radarData, setRadarData] = useState<ConfidenceRadarDatum[]>([])
  const [loading,   setLoading]   = useState(true)
  const [error,     setError]     = useState<string | null>(null)
  const [filter,    setFilter]    = useState<FilterCategory>('all')

  // Probe state
  const [probeTarget,  setProbeTarget]  = useState<TrustProfileEntity | null>(null)
  const [probeState,   setProbeState]   = useState<ProbeState | null>(null)
  const [probingId,    setProbingId]    = useState<string | null>(null)   // entity_id loading

  // Review modal state
  const [reviewTarget,  setReviewTarget]  = useState<TrustProfileEntity | null>(null)
  // Manual verification session state
  const [manualTarget,  setManualTarget]  = useState<TrustProfileEntity | null>(null)
  const [manualSession, setManualSession] = useState<{session_id: string; first_prompt: string} | null>(null)
  const [manualLoading, setManualLoading] = useState(false)

  // Ref so fetchData's identity (and its [userId] dep array) doesn't have to
  // change every time the parent passes a fresh onScoreChange closure.
  const onScoreChangeRef = useRef(onScoreChange)
  useEffect(() => { onScoreChangeRef.current = onScoreChange }, [onScoreChange])

  // Guards the loading skeleton so only the very first fetch shows it —
  // subsequent refetches (triggered by profileVersion) update `data` in
  // place without ever flashing the dashboard back to a skeleton.
  const hasLoadedOnceRef = useRef(false)

  // ── Fetch ────────────────────────────────────────────────────────────────

  const fetchData = useCallback(async () => {
    if (!hasLoadedOnceRef.current) setLoading(true)
    setError(null)
    try {
      // Ensure the auth token is populated before these mount-time fetches —
      // both /trust-score and /confidence-matrix fire on first render, before
      // AuthContext may have called setAuthToken(). An empty Authorization
      // header 401s and trips the global sign-out (the auto-logout loop).
      await ensureFreshToken()

      // Fetch entity list + evidence (drives accordion rows and avg score)
      const res = await fetch(`/api/profile/${userId}/trust-score`, {
        headers: getAuthHeaders(),
        cache:   'no-store',
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = (await res.json()) as TrustScoreResponse
      setData(json)
      onScoreChangeRef.current?.(json.overall_trust_score ?? 0, json.score_breakdown)

      // Fetch four-category radar data independently (non-fatal if it fails)
      try {
        const radarRes = await fetch(`/api/profile/${userId}/confidence-matrix`, {
          headers: getAuthHeaders(),
          cache:   'no-store',
        })
        if (radarRes.ok) {
          const radarJson = (await radarRes.json()) as ConfidenceMatrixResponse
          // The API now returns arch_value / syn_value per category directly
          setRadarData(radarJson.radar_data.map(d => ({
            category:   d.category.replace(/_/g, ' '),
            value:      d.value,
            arch_value: (d as any).arch_value ?? d.value,
            syn_value:  (d as any).syn_value  ?? 0,
          })))
        }
      } catch {
        // Radar fetch failure is non-fatal; chart falls back to empty state
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load trust scores')
    } finally {
      setLoading(false)
      hasLoadedOnceRef.current = true
    }
  }, [userId])

  // Re-fires whenever profileVersion is bumped (Ariel chat updated the
  // profile) in addition to the initial mount-time fetch — see fetchData's
  // hasLoadedOnceRef guard for why this doesn't re-show the skeleton.
  useEffect(() => { fetchData() }, [fetchData, profileVersion])

  // ── Start probe ──────────────────────────────────────────────────────────

  const handleProbe = useCallback(async (entity: TrustProfileEntity) => {
    setProbeState(null)
    setProbeTarget(null)
    setProbingId(entity.entity_id)
    try {
      await ensureFreshToken()
      const res = await fetch('/api/ariel/probe/start', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body:    JSON.stringify({ entity_id: entity.entity_id }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error((body as { detail?: string }).detail ?? `HTTP ${res.status}`)
      }
      const data = await res.json()
      const method = probeMethodFromEntityType(entity.entity_type)
      setProbeTarget(entity)
      setProbeState({
        session_id:     data.session_id,
        entity_id:      data.entity_id,
        entity_name:    data.entity_name,
        probe_method:   (data.probe_method as 'STAR' | 'SCOPE' | 'SIGNAL') ?? method,
        turn:           1,
        question:       data.question,
        answers:        {},
        done:           false,
        flag_type:      null,
        new_confidence: null,
      })
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Could not start probe. Please try again.')
    } finally {
      setProbingId(null)
    }
  }, [])

  // ── Probe done → refresh dashboard ──────────────────────────────────────

  const handleProbeDone = useCallback((_newConf: number | null) => {
    setProbeState(null)
    setProbeTarget(null)
    fetchData()
  }, [fetchData])

  // ── Review done → refresh dashboard ─────────────────────────────────────

  const handleReviewDone = useCallback(() => {
    setReviewTarget(null)
    fetchData()
  }, [fetchData])

  const handleManualVerify = useCallback(async (entity: TrustProfileEntity) => {
    setManualTarget(entity)
    setManualLoading(true)
    try {
      await ensureFreshToken()
      const res = await fetch(`/api/profile/${userId}/manual-verify/start`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body:    JSON.stringify({ entity_id: entity.entity_id }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setManualSession({ session_id: json.session_id, first_prompt: json.first_prompt })
    } catch (err) {
      console.error('[manual-verify]', err)
      setManualTarget(null)
    } finally {
      setManualLoading(false)
    }
  }, [userId])

  // ── Derived state ────────────────────────────────────────────────────────

  const entities = data?.entities ?? []
  const filtered = filter === 'all'
    ? entities
    : entities.filter(e => e.entity_type === filter)

  // Fixed sort: (1) unverified/needs-attention first, (2) highest confidence within each group
  const sorted = [...filtered].sort((a, b) => {
    const aUnverified = a.verification_level !== 'VERIFIED_MANUAL' ? 0 : 1
    const bUnverified = b.verification_level !== 'VERIFIED_MANUAL' ? 0 : 1
    if (aUnverified !== bUnverified) return aUnverified - bUnverified
    return b.confidence_score - a.confidence_score
  })

  // Avg Confidence: use the four-category radar averages when available,
  // fall back to mean of stored entity scores when radar hasn't loaded yet.
  const avgScore = radarData.length > 0
    ? radarData.reduce((s, d) => s + d.value, 0) / radarData.length
    : entities.length > 0
      ? entities.reduce((s, e) => s + e.confidence_score, 0) / entities.length
      : 0
  const verifiedCount = entities.filter(e => e.confidence_score >= 75).length
  const flaggedCount  = entities.filter(e => e.manual_review_required).length

  // ── Render ───────────────────────────────────────────────────────────────

  return (
    <div className={`space-y-6 ${className}`}>

      {/* ── Header ───────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-[15px] font-bold text-slate-900 tracking-tight flex items-center gap-2">
            <span className="text-teal-600"><ShieldCheck s={16} /></span>
            Confidence Matrix
          </h2>
          <p className="text-[12px] text-slate-400 mt-0.5">
            Evidence-backed trust scores across your profile entities
          </p>
        </div>
        <button
          onClick={fetchData}
          disabled={loading}
          className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg border border-slate-200 text-[12px] font-medium text-slate-500 hover:text-slate-800 hover:bg-slate-50 transition disabled:opacity-40 disabled:pointer-events-none active:scale-[0.97]"
        >
          {loading
            ? <SpinnerIcon s={12} />
            : (
              <svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke="currentColor"
                strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
              >
                <polyline points="23 4 23 10 17 10" /><polyline points="1 20 1 14 7 14" />
                <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
              </svg>
            )
          }
          Refresh
        </button>
      </div>

      {/* ── Auth-wall callout ─────────────────────────────────────────────── */}
      {showAuthWall && <AuthWallCallout />}

      {/* ── Fetch error ───────────────────────────────────────────────────── */}
      {error && (
        <div
          className="rounded-xl px-4 py-3 flex items-start gap-3"
          style={{ background: 'oklch(0.98 0.02 25)', border: '1px solid oklch(0.88 0.04 25)' }}
        >
          <span className="text-[15px] mt-0.5" aria-hidden="true">⚠️</span>
          <div className="flex-1 min-w-0">
            <p className="text-[12.5px] font-semibold text-slate-700 mb-0.5">Failed to load trust scores</p>
            <p className="text-[12px] text-slate-500">{error}</p>
          </div>
          <button
            onClick={fetchData}
            className="shrink-0 text-[11.5px] font-medium text-teal-600 hover:text-teal-800 transition"
          >
            Retry
          </button>
        </div>
      )}

      {/* ── Skeleton while loading ────────────────────────────────────────── */}
      {loading && <DashboardSkeleton />}

      {/* ── Content (rendered once data arrives) ─────────────────────────── */}
      {!loading && data && (
        <>
          {entities.length === 0 ? (
            <UploadZone userId={userId} onUploaded={fetchData} />
          ) : (
            <div className="space-y-6">
              {/* Manual review banner */}
              <ManualReviewCallout entities={entities} onReview={setReviewTarget} />

              {/* ── Radar chart — full-width centred header ───────────────── */}
              <div
                className="bg-white rounded-2xl border border-slate-100 px-5 py-5"
                style={{ boxShadow: TOKENS.shadow.card }}
              >
                <TrustRadarChart data={radarData} />
              </div>

              {/* ── Top 3 by architecture_confidence ─────────────────────── */}
              {(() => {
                const top3 = [...entities]
                  .sort((a, b) => (b.architecture_confidence ?? 0) - (a.architecture_confidence ?? 0))
                  .slice(0, 3)
                return top3.length > 0 ? (
                  <div
                    className="bg-white rounded-2xl border border-slate-100 px-5 py-4"
                    style={{ boxShadow: TOKENS.shadow.card }}
                  >
                    <p className="text-[10.5px] font-bold tracking-widest uppercase text-slate-400 mb-3">
                      Top Capabilities
                    </p>
                    <div className="space-y-1.5">
                      {top3.map((ent, i) => (
                        <CapabilityRow
                          key={ent.entity_id}
                          entity={ent}
                          rank={i + 1}
                          onVerify={handleManualVerify}
                          onProbe={handleProbe}
                          probing={probingId === ent.entity_id}
                        />
                      ))}
                    </div>
                  </div>
                ) : null
              })()}

              {/* ── View All CTA ──────────────────────────────────────────── */}
              <Link
                href="/capabilities"
                className="w-full h-11 rounded-xl text-[13.5px] font-semibold flex items-center justify-center gap-2 transition active:scale-[0.98] border border-slate-200 text-slate-600 hover:text-slate-900 hover:bg-white hover:border-slate-300"
                style={{ background: 'oklch(0.98 0.00 0)' }}
              >
                View All Capabilities
                <svg width={13} height={13} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={2}>
                  <path d="M4 10h12M11 5l5 5-5 5" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </Link>
            </div>
          )}
        </>
      )}

      {/* ── Probe modal ──────────────────────────────────────────────────── */}
      {probeState && (
        <ProbeModal
          key={probeState.entity_id}
          probe={probeState}
          onClose={() => { setProbeState(null); setProbeTarget(null) }}
          onDone={handleProbeDone}
        />
      )}

      {/* ── Manual review modal ───────────────────────────────────────────── */}
      {reviewTarget && (
        <ManualReviewModal
          entity={reviewTarget}
          onClose={() => setReviewTarget(null)}
          onDone={handleReviewDone}
        />
      )}

      {/* ── Whiteboard Challenge Modal ────────────────────────────────────── */}
      {manualTarget && (
        <WhiteboardChallengeModal
          entity={manualTarget}
          session={manualSession}
          loading={manualLoading}
          onClose={() => { setManualTarget(null); setManualSession(null) }}
        />
      )}

    </div>
  )
}
