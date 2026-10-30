'use client'

import { Suspense, useCallback, useEffect, useRef, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useI18n } from '@/contexts/I18nContext'
import AuthGuard            from '@/components/AuthGuard'
import { OnboardingHeader } from '@/components/OnboardingHeader'
import { useAuth }          from '@/contexts/AuthContext'
import { useOnboarding }    from '@/contexts/OnboardingContext'
import { resolveDisplayName } from '@/lib/nameUtils'
import { TOKENS }           from '@/lib/tokens'
import {
  saveRolePreferences, fetchRolePreferences, markOnboardingComplete, saveHebrewForm,
  uploadCvFiles,
  cvUploadErrorMessage,
  type CvUploadStage,
  type RoleSeniorityItem,
  type SeniorityLevel,
  type HebrewForm,
} from '@/lib/api'
import { HebrewFormPicker } from '@/components/HebrewFormPicker'
import { CvUploadProgress } from '@/components/CvUploadProgress'
import { armArielWelcome } from '@/lib/onboardingFlags'
import { RolePicker, type PendingRole } from '@/components/RolePicker'

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

// ── Page ──────────────────────────────────────────────────────────────────────

type Phase = 'showcase' | 'preferences' | 'intake'

function OnboardingContent() {
  const router = useRouter()
  const { user, updateUserMeta } = useAuth()
  const { set: setOnboarding }   = useOnboarding()
  const { t } = useI18n()
  const O = t.onboarding

  // The step lives in the URL (?step=preferences|intake), not only in state.
  // With state alone the browser's Back button left /onboarding entirely,
  // and coming back started the flow over from the first screen; now Back
  // and Forward move between steps, and a refresh stays on the current one.
  const searchParams = useSearchParams()
  const stepParam = searchParams.get('step')
  const phase: Phase = stepParam === 'preferences' || stepParam === 'intake' ? stepParam : 'showcase'
  const setPhase = useCallback((next: Phase) => {
    router.push(next === 'showcase' ? '/onboarding' : `/onboarding?step=${next}`)
  }, [router])
  const [active, setActive] = useState(0)

  // Role & seniority step state
  const [selected,  setSelected]  = useState<PendingRole[]>([])
  const [saving,    setSaving]    = useState(false)
  const [saveError, setSaveError] = useState('')
  const [hebrewForm, setHebrewForm] = useState<HebrewForm | null>(null)

  // CV upload state (in-place — no intermediate screen)
  const fileRef = useRef<HTMLInputElement>(null)
  const [cvBusy,      setCvBusy]      = useState(false)
  const [cvFileCount, setCvFileCount] = useState(0)
  const [cvStage,     setCvStage]     = useState<CvUploadStage>('uploading')
  const [cvDragOver,  setCvDragOver]  = useState(false)
  const [cvError,     setCvError]     = useState('')

  // One role is enough to continue; the level is optional. Requiring a level
  // for every role kept this button disabled for most users, who then pressed
  // Skip — so in production no user had saved a single target role, and the
  // matcher fell back to a global list of someone else's roles.
  // Load what this user already saved. The picker used to start empty on
  // every visit, so a returning user saw a blank form, assumed nothing had
  // been kept and pressed Skip. Roles live in Postgres (user_preferences +
  // profile_answers), so they survive deploys and other devices.
  const prefilled = useRef(false)
  useEffect(() => {
    if (prefilled.current) return
    prefilled.current = true
    fetchRolePreferences()
      .then(({ roles }) => {
        if (!roles.length) return
        setSelected(prev => prev.length ? prev : roles.map(r => ({
          role:      r.role,
          seniority: (r.seniority || null) as SeniorityLevel | null,
        })))
      })
      .catch(() => { /* empty picker, as before */ })
  }, [])

  // Someone who already finished onboarding came here only to change their
  // roles (from the in-app prompt). Saving takes them back to the app instead
  // of on to the CV upload they already did.
  const alreadyOnboarded =
    (user?.user_metadata as Record<string, unknown> | null)?.profile_completed === true

  // Every role needs a level, and Hebrew wording must be chosen: the app asks
  // for anything missing at the next login (RequiredDetailsGate), so letting
  // it through here would only mean asking twice.
  const hasRoles = selected.length > 0 && selected.every(r => r.seniority) && hebrewForm !== null
  const toItems = (): RoleSeniorityItem[] =>
    selected.map(r => ({ role: r.role, seniority: r.seniority ?? '' }))

  const handleSavePreferences = async () => {
    setSaving(true)
    setSaveError('')
    try {
      await saveRolePreferences({ roles: toItems() })
      if (hebrewForm) await saveHebrewForm(hebrewForm)
      if (alreadyOnboarded) router.push('/?tab=overview')
      else setPhase('intake')
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
      roles: toItems(),
    })
    try { await updateUserMeta({ profile_completed: true }) } catch { /* backfilled by sync-user later */ }
    // The flag above drives the UI; this one is what the matching pipeline
    // reads. They are separate columns in separate systems, and for a long time
    // only the first was set — so the dashboard said "done" while the user was
    // never matched. Not fatal if it fails: the user still lands in the app,
    // and the Ariel finalize_onboarding tool remains a second route in.
    try { await markOnboardingComplete() } catch (err) {
      console.error('[onboarding] could not mark onboarding complete:', err)
    }
    armArielWelcome()
    router.push('/?tab=overview')   // soft transition to Overview
  }

  const handleCvFiles = async (files: File[]) => {
    if (!files.length || cvBusy) return
    setCvBusy(true)
    setCvFileCount(files.length)
    setCvError('')
    try {
      await uploadCvFiles(files, setCvStage)   // all files go up together under the `files` key
      await completeOnboarding()
    } catch (err) {
      console.error('[onboarding] CV upload failed:', err)
      setCvError(cvUploadErrorMessage(err, t.cv_upload_errors))
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

          <p className="block text-[12px] font-semibold uppercase tracking-wider text-slate-400 mt-7 mb-1">
            {t.required_details.hebrew_heading}
          </p>
          <p className="text-[12px] text-slate-500 mb-3 leading-relaxed">{t.required_details.hebrew_hint}</p>
          <HebrewFormPicker value={hebrewForm} onChange={setHebrewForm} disabled={saving} />

          {saveError && (
            <p className="text-[12.5px] text-red-600 mt-4" role="alert">{saveError}</p>
          )}

          <div className="flex items-center gap-3 mt-8">
            <button
              onClick={handleSavePreferences}
              disabled={saving || !hasRoles}
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
          onDragOver={e => { e.preventDefault(); if (!cvBusy) setCvDragOver(true) }}
          onDragLeave={() => setCvDragOver(false)}
          onDrop={e => {
            e.preventDefault()
            setCvDragOver(false)
            if (cvBusy) return
            void handleCvFiles(Array.from(e.dataTransfer.files).filter(f => /\.(pdf|docx)$/i.test(f.name)))
          }}
          className={`w-full flex items-center gap-4 rounded-2xl border-2 border-dashed p-5 hover:border-teal-400 hover:bg-teal-50 transition text-start group disabled:opacity-60 disabled:pointer-events-none ${
            cvDragOver ? 'border-teal-400 bg-teal-50' : 'border-slate-200'
          }`}
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
        {cvBusy && <CvUploadProgress stage={cvStage} />}
        {cvError && (
          <p className="text-[12px] text-red-600 mt-2" role="alert">{cvError}</p>
        )}

        {/* Testers uploaded other documents here (e.g. a regulations PDF) and
            got nothing back. Say up front what belongs here and where the
            rest goes, rather than only after a failed upload. */}
        <p className="text-[12px] text-slate-500 mt-4 leading-relaxed rounded-xl bg-slate-50 px-3.5 py-3">
          {O.intake.cv_only_note}
        </p>

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
      {/* useSearchParams needs a Suspense boundary under the app router. */}
      <Suspense fallback={null}>
        <OnboardingContent />
      </Suspense>
    </AuthGuard>
  )
}
