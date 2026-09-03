'use client'

import { useMemo, useRef, useState } from 'react'
import { useRouter }        from 'next/navigation'
import { useI18n } from '@/contexts/I18nContext'
import AuthGuard            from '@/components/AuthGuard'
import { OnboardingHeader } from '@/components/OnboardingHeader'
import { useAuth }          from '@/contexts/AuthContext'
import { useOnboarding }    from '@/contexts/OnboardingContext'
import { resolveDisplayName } from '@/lib/nameUtils'
import { TOKENS }           from '@/lib/tokens'
import {
  saveRolePreferences,
  uploadCvFiles,
  type RoleSeniorityItem,
  type SeniorityLevel,
} from '@/lib/api'
import { armArielWelcome } from '@/lib/onboardingFlags'

// ── Icons ─────────────────────────────────────────────────────────────────────

function CheckIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  )
}

function UploadIcon({ s = 20 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="16 16 12 12 8 16" /><line x1="12" y1="12" x2="12" y2="21" />
      <path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3" />
    </svg>
  )
}

function SpinnerIcon({ s = 16 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" style={{ animation: 'ob-spin 0.8s linear infinite' }}>
      <style>{`@keyframes ob-spin{to{transform:rotate(360deg)}}`}</style>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.5" strokeOpacity="0.25" />
      <path d="M12 3a9 9 0 0 1 9 9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  )
}

// ── Shared layout — minimal onboarding chrome (logo + sign out only) ──────────

function OnboardingShell({ onBack, children }: {
  onBack?:  () => void
  children: React.ReactNode
}) {
  const { t, dir } = useI18n()
  return (
    <div className="flex flex-col min-h-screen bg-[#FBFBFA]">
      <OnboardingHeader />
      <main className="flex-1 flex flex-col items-center px-4 py-12">
        <div className="w-full max-w-3xl">
          {onBack && (
            <button
              onClick={onBack}
              className="text-[13px] text-slate-400 hover:text-slate-700 mb-6 flex items-center gap-1 transition"
            >
              <span aria-hidden="true">{dir === 'rtl' ? '\u2192' : '\u2190'}</span> {t.login.page.back}
            </button>
          )}
          {children}
        </div>
      </main>
    </div>
  )
}

// A "forward" arrow points right in LTR and left in RTL. A literal "→" in a
// Hebrew CTA points backwards, away from where the flow actually goes.
function DirectionalArrow() {
  const { dir } = useI18n()
  return <span aria-hidden="true">{dir === 'rtl' ? '\u2190' : '\u2192'}</span>
}

// ── Steps data ────────────────────────────────────────────────────────────────

// Icons only — title/body live in the dictionaries (onboarding.showcase.steps)
// and are indexed positionally against this list. Keep both in the same order.
const STEP_ICONS = ['🗂️', '⚡', '📊'] as const

// ── Role catalogue for autocomplete (~40 common tech/startup roles) ───────────

const ROLE_CATALOG = [
  'Account Executive', 'Account Manager', 'Backend Developer', 'Business Analyst',
  'Business Development Manager', 'Chief of Staff', 'Content Marketing Manager',
  'Customer Success Manager', 'Data Analyst', 'Data Engineer', 'Data Scientist',
  'DevOps Engineer', 'Engineering Manager', 'Finance Manager', 'Frontend Developer',
  'Full Stack Developer', 'Growth Manager', 'HR Business Partner', 'IT Manager',
  'Machine Learning Engineer', 'Marketing Director', 'Marketing Manager',
  'Mobile Developer', 'Office Manager', 'Operations Manager', 'Partnership Manager',
  'Product Analyst', 'Product Designer', 'Product Manager', 'Product Marketing Manager',
  'Program Manager', 'Project Manager', 'QA Engineer', 'Sales Development Representative',
  'Sales Manager', 'Security Engineer', 'Software Engineer', 'Solutions Architect',
  'Talent Acquisition Manager', 'Technical Support Engineer', 'Technical Writer',
  'UX Designer', 'UX Researcher',
]

// Values are persisted to the profile and stay English — the stored profile
// is canonically English so downstream matching sees one spelling per level
// (see backend migration c5a91b3e7d02). Only the display labels translate,
// from onboarding.preferences.seniority, indexed against this list.
const SENIORITY_VALUES: SeniorityLevel[] = [
  'junior', 'mid', 'senior', 'lead', 'director', 'executive',
]

// ── Roles combobox with per-role seniority ────────────────────────────────────

interface PendingRole {
  role:      string
  seniority: SeniorityLevel | null   // null until the user picks a level
}

function RolePicker({ selected, setSelected }: {
  selected:    PendingRole[]
  setSelected: React.Dispatch<React.SetStateAction<PendingRole[]>>
}) {
  const { t } = useI18n()
  const P = t.onboarding.preferences
  const [query,     setQuery]     = useState('')
  const [open,      setOpen]      = useState(false)
  const [highlight, setHighlight] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  const suggestions = useMemo(() => {
    const q = query.trim().toLowerCase()
    const taken = new Set(selected.map(r => r.role.toLowerCase()))
    const pool = ROLE_CATALOG.filter(r => !taken.has(r.toLowerCase()))
    if (!q) return pool.slice(0, 8)
    // Prefix-of-word matches first ("aco" → Account…), then substring matches.
    const starts   = pool.filter(r => r.toLowerCase().split(/\s+/).some(w => w.startsWith(q)) || r.toLowerCase().startsWith(q))
    const contains = pool.filter(r => !starts.includes(r) && r.toLowerCase().includes(q))
    return [...starts, ...contains].slice(0, 8)
  }, [query, selected])

  const addRole = (role: string) => {
    const value = role.trim()
    if (!value || selected.length >= 10) return
    if (selected.some(r => r.role.toLowerCase() === value.toLowerCase())) return
    setSelected(prev => [...prev, { role: value, seniority: null }])
    setQuery('')
    setHighlight(0)
    setOpen(false)
    inputRef.current?.focus()
  }

  return (
    <div>
      {/* Combobox input */}
      <div className="relative">
        <input
          id="target-roles-combobox"
          ref={inputRef}
          value={query}
          role="combobox"
          aria-expanded={open && suggestions.length > 0}
          aria-autocomplete="list"
          aria-controls="role-suggestions"
          onChange={e => { setQuery(e.target.value); setOpen(true); setHighlight(0) }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 120)}
          onKeyDown={e => {
            if (e.key === 'ArrowDown') { e.preventDefault(); setHighlight(h => Math.min(h + 1, suggestions.length - 1)) }
            if (e.key === 'ArrowUp')   { e.preventDefault(); setHighlight(h => Math.max(h - 1, 0)) }
            if (e.key === 'Enter') {
              e.preventDefault()
              if (suggestions[highlight]) addRole(suggestions[highlight])
              else if (query.trim())      addRole(query)   // free-text custom role
            }
            if (e.key === 'Escape') setOpen(false)
          }}
          placeholder={P.role_placeholder}
          maxLength={80}
          disabled={selected.length >= 10}
          className="w-full rounded-xl border border-slate-200 px-3.5 py-2.5 text-[13.5px] text-slate-800 placeholder:text-slate-300 outline-none focus:border-teal-400 transition disabled:opacity-50"
        />

        {open && suggestions.length > 0 && (
          <ul
            id="role-suggestions"
            role="listbox"
            className="absolute left-0 right-0 top-[calc(100%+4px)] z-30 rounded-xl bg-white border border-slate-100 shadow-elevation-2 overflow-hidden max-h-64 overflow-y-auto"
          >
            {suggestions.map((s, i) => (
              <li key={s} role="option" aria-selected={i === highlight}>
                <button
                  onMouseDown={e => { e.preventDefault(); addRole(s) }}
                  onMouseEnter={() => setHighlight(i)}
                  className={`w-full text-start px-3.5 py-2.5 text-[13px] transition ${
                    i === highlight ? 'bg-teal-50 text-teal-800' : 'text-slate-700'
                  }`}
                >
                  {s}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Selected roles — each with its own seniority selector */}
      {selected.length > 0 && (
        <ul className="mt-4 space-y-2.5">
          {selected.map(item => (
            <li
              key={item.role}
              className="rounded-xl border border-slate-100 bg-slate-50/60 px-3.5 py-3"
            >
              <div className="flex items-center justify-between gap-2 mb-2">
                <span className="text-[13.5px] font-semibold text-slate-800">{item.role}</span>
                <button
                  onClick={() => setSelected(prev => prev.filter(r => r.role !== item.role))}
                  aria-label={P.remove_role.replace('{role}', item.role)}
                  className="text-slate-300 hover:text-slate-600 text-[13px] transition"
                >✕</button>
              </div>
              <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label={P.level_for_role.replace('{role}', item.role)}>
                {SENIORITY_VALUES.map((value, i) => {
                  const on = item.seniority === value
                  return (
                    <button
                      key={value}
                      role="radio"
                      aria-checked={on}
                      onClick={() =>
                        setSelected(prev => prev.map(r =>
                          r.role === item.role ? { ...r, seniority: on ? null : value } : r
                        ))
                      }
                      className={`text-[11.5px] font-medium px-2.5 py-1 rounded-full border transition ${
                        on
                          ? 'border-teal-400 bg-teal-100 text-teal-800'
                          : 'border-slate-200 bg-white text-slate-500 hover:border-slate-300'
                      }`}
                    >
                      {P.seniority[i]}
                    </button>
                  )
                })}
              </div>
              {item.seniority === null && (
                <p className="mt-1.5 text-[11px] text-amber-600">{P.pick_level}</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

type Phase = 'showcase' | 'preferences' | 'intake'

function OnboardingContent() {
  const router = useRouter()
  const { user, updateUserMeta } = useAuth()
  const { set: setOnboarding }   = useOnboarding()
  const { t } = useI18n()
  const O = t.onboarding

  const [phase,  setPhase]  = useState<Phase>('showcase')
  const [active, setActive] = useState(0)

  // Role & seniority step state
  const [selected,  setSelected]  = useState<PendingRole[]>([])
  const [saving,    setSaving]    = useState(false)
  const [saveError, setSaveError] = useState('')

  // CV upload state (in-place — no intermediate screen)
  const fileRef = useRef<HTMLInputElement>(null)
  const [cvBusy,      setCvBusy]      = useState(false)
  const [cvFileCount, setCvFileCount] = useState(0)
  const [cvError,     setCvError]     = useState('')

  const allLeveled = selected.length > 0 && selected.every(r => r.seniority !== null)

  const handleSavePreferences = async () => {
    setSaving(true)
    setSaveError('')
    try {
      const roles: RoleSeniorityItem[] = selected
        .filter((r): r is PendingRole & { seniority: SeniorityLevel } => r.seniority !== null)
        .map(r => ({ role: r.role, seniority: r.seniority }))
      await saveRolePreferences({ roles })
      setPhase('intake')
    } catch {
      setSaveError(O.preferences.save_failed)
    } finally {
      setSaving(false)
    }
  }

  // Completion path for the CV upload:
  //   1. Sync local state FIRST — OnboardingContext (greeting data incl. the
  //      user's role/seniority picks) and Supabase user metadata — so the
  //      dashboard renders in the profile_completed state with no flash.
  //   2. Arm Ariel's one-shot welcome.
  //   3. SOFT-navigate with router.push (no window.location.assign — the hard
  //      reload caused ChunkLoadError and dropped all local React state).
  const completeOnboarding = async () => {
    const meta        = user?.user_metadata as Record<string, unknown> | null
    const displayName = resolveDisplayName(user?.email, meta)
    setOnboarding({
      fullName:    displayName,
      careerStage: typeof meta?.career_stage === 'string' ? meta.career_stage : '',
      roles: selected
        .filter((r): r is PendingRole & { seniority: SeniorityLevel } => r.seniority !== null)
        .map(r => ({ role: r.role, seniority: r.seniority })),
    })
    try { await updateUserMeta({ profile_completed: true }) } catch { /* backfilled by sync-user later */ }
    armArielWelcome()
    router.push('/?tab=overview')   // soft transition to Overview
  }

  const handleCvFiles = async (files: File[]) => {
    if (!files.length || cvBusy) return
    setCvBusy(true)
    setCvFileCount(files.length)
    setCvError('')
    try {
      await uploadCvFiles(files)   // all files go up together under the `files` key
      await completeOnboarding()
    } catch (err) {
      setCvError(err instanceof Error ? err.message : O.intake.upload_failed)
      setCvBusy(false)
    }
  }

  // ── Showcase ─────────────────────────────────────────────────────────────────

  if (phase === 'showcase') {
    return (
      <OnboardingShell>
        <div className="text-center mb-10">
          <h1 className="text-[28px] font-semibold text-slate-900 tracking-tight">
            {O.showcase.title}
          </h1>
          <p className="text-[14px] text-slate-400 mt-1.5">
            {O.showcase.subtitle}
          </p>
        </div>

        <div className="grid md:grid-cols-3 gap-5 mb-10">
          {STEP_ICONS.map((icon, idx) => {
            const isActive = active === idx
            return (
              <button
                key={idx}
                onClick={() => setActive(idx)}
                className={`relative text-start rounded-2xl border p-6 transition-all duration-200 cursor-pointer ${
                  isActive
                    ? 'border-teal-300 bg-white shadow-elevation-2 scale-[1.02]'
                    : 'border-slate-200 bg-white/70 hover:bg-white hover:border-slate-300'
                }`}
              >
                <div className={`absolute -top-3 -left-3 w-7 h-7 rounded-full flex items-center justify-center text-[12px] font-bold border-2 border-white shadow ${
                  isActive ? 'bg-teal-500 text-white' : 'bg-slate-200 text-slate-500'
                }`}>
                  {idx + 1}
                </div>

                <div className="text-3xl mb-3">{icon}</div>
                <p className="text-[15px] font-bold text-slate-900 mb-2 leading-snug">{O.showcase.steps[idx].title}</p>
                <p className="text-[13px] text-slate-500 leading-relaxed">{O.showcase.steps[idx].body}</p>

                {isActive && (
                  <div className="mt-3 flex items-center gap-1.5 text-[12px] font-semibold text-teal-700">
                    <CheckIcon /> {O.showcase.selected}
                  </div>
                )}
              </button>
            )
          })}
        </div>

        <div className="flex flex-col items-center">
          <button
            onClick={() => setPhase('preferences')}
            className="h-12 px-8 rounded-2xl text-[15px] font-semibold text-white shadow-elevation-2 hover:shadow-floating hover:-translate-y-0.5 transition-all"
            style={{ background: `linear-gradient(135deg, ${TOKENS.color.primary}, ${TOKENS.color.primaryHover})` }}
          >
            {O.showcase.cta} <DirectionalArrow />
          </button>
        </div>
      </OnboardingShell>
    )
  }

  // ── Role & seniority step ────────────────────────────────────────────────────

  if (phase === 'preferences') {
    return (
      <OnboardingShell onBack={() => setPhase('showcase')}>
        <div className="max-w-xl mx-auto bg-white rounded-3xl border border-slate-100 shadow-sm p-8">
          <h1 className="text-[20px] font-bold text-slate-900 mb-1">{O.preferences.title}</h1>
          <p className="text-[13.5px] text-slate-500 mb-7 leading-relaxed">
            {O.preferences.intro}
          </p>

          <label htmlFor="target-roles-combobox" className="block text-[12px] font-semibold uppercase tracking-wider text-slate-400 mb-2">
            {O.preferences.roles_label}
          </label>
          <RolePicker selected={selected} setSelected={setSelected} />

          {saveError && (
            <p className="text-[12.5px] text-red-600 mt-4" role="alert">{saveError}</p>
          )}

          <div className="flex items-center gap-3 mt-8">
            <button
              onClick={handleSavePreferences}
              disabled={saving || !allLeveled}
              className="flex-1 h-11 rounded-xl text-[14px] font-semibold text-white transition disabled:opacity-40"
              style={{ background: TOKENS.color.primary }}
            >
              {saving ? O.preferences.saving : <>{O.preferences.continue_cta} <DirectionalArrow /></>}
            </button>
            <button
              onClick={() => setPhase('intake')}
              className="text-[13px] text-slate-400 hover:text-slate-600 px-3 transition"
            >
              {O.preferences.skip}
            </button>
          </div>
        </div>
      </OnboardingShell>
    )
  }

  // ── Intake hub ───────────────────────────────────────────────────────────────

  return (
    <OnboardingShell onBack={() => setPhase('preferences')}>
      <div className="max-w-md mx-auto bg-white rounded-3xl border border-slate-100 shadow-sm p-8">
        <h1 className="text-[20px] font-bold text-slate-900 mb-1">{O.intake.title}</h1>
        <p className="text-[13.5px] text-slate-500 mb-7 leading-relaxed">
          {O.intake.intro}
        </p>

        {/* Upload CV — opens the OS file picker directly (no extra screen) */}
        <input
          ref={fileRef}
          type="file"
          accept=".pdf,.docx"
          multiple
          className="hidden"
          onChange={e => {
            const files = Array.from(e.target.files ?? [])
            e.target.value = ''
            void handleCvFiles(files)
          }}
        />
        <button
          onClick={() => fileRef.current?.click()}
          disabled={cvBusy}
          className="w-full flex items-center gap-4 rounded-2xl border-2 border-dashed border-slate-200 p-5 hover:border-teal-400 hover:bg-teal-50 transition text-start group disabled:opacity-60 disabled:pointer-events-none"
        >
          <div className="w-11 h-11 rounded-xl bg-slate-100 group-hover:bg-teal-100 flex items-center justify-center text-slate-500 group-hover:text-teal-600 flex-shrink-0 transition">
            {cvBusy ? <SpinnerIcon s={20} /> : <UploadIcon s={20} />}
          </div>
          <div>
            {cvBusy ? (
              <>
                <p className="text-[14px] font-semibold text-slate-800">
                  {(cvFileCount === 1 ? O.intake.uploading_one : O.intake.uploading_many)
                    .replace('{n}', String(cvFileCount))}
                </p>
                <p className="text-[12px] text-slate-400 mt-0.5">
                  {O.intake.analyzing}
                </p>
              </>
            ) : (
              <>
                <p className="text-[14px] font-semibold text-slate-800">{O.intake.upload_cta}</p>
                <p className="text-[12px] text-slate-400 mt-0.5">
                  {O.intake.upload_hint}
                </p>
              </>
            )}
          </div>
        </button>
        {cvError && (
          <p className="text-[12px] text-red-600 mt-2" role="alert">{cvError}</p>
        )}

        {/* Skip — straight to the dashboard (profile stays incomplete) */}
        <button
          onClick={() => router.push('/?tab=overview')}
          disabled={cvBusy}
          className="w-full mt-6 text-[13px] text-slate-400 hover:text-slate-600 transition disabled:opacity-40"
        >
          {O.intake.skip}
        </button>
      </div>
    </OnboardingShell>
  )
}

export default function OnboardingPage() {
  return (
    <AuthGuard>
      <OnboardingContent />
    </AuthGuard>
  )
}
