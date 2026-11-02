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
  saveRolePreferences, fetchRolePreferences, markOnboardingComplete,
  fetchAbout, saveAbout, REGIONS,
  uploadCvFiles,
  cvUploadErrorMessage,
  type CvUploadStage,
  type RoleSeniorityItem,
  type SeniorityLevel,
  type Gender, type WorkEnvironment, type CareerChange, type Region,
  type SearchMode,
} from '@/lib/api'
import { AccountStep } from '@/components/auth/AccountStep'
import { AuthLayout } from '@/components/auth/AuthLayout'
import { useLocalities } from '@/components/auth/CityPicker'
import { HomeField, type HomeWhere } from '@/components/auth/HomeField'
import { SignupSteps } from '@/components/auth/SignupSteps'
import { authChip, authLabel, authPrimary, authSub, authTitle } from '@/components/auth/authStyles'
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

function OnboardingShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-col min-h-screen bg-[#FBFBFA]">
      <OnboardingHeader />
      <main className="flex-1 flex flex-col items-center px-4 py-12">
        <div className="w-full max-w-3xl">{children}</div>
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

// One question with a few answers. multi: any number may be on (areas).
function Choices<T extends string>({ label, hint, options, labels, value, onChange, multi = false, disabled, className = 'mt-8' }: {
  label?:   string
  hint?:    string
  options:  readonly T[]
  labels:   Record<T, string>
  value:    T[]
  onChange: (v: T[]) => void
  multi?:   boolean
  disabled: boolean
  className?: string
}) {
  return (
    <fieldset className={className} disabled={disabled}>
      {label && <legend className="block text-[15px] font-semibold text-slate-900 mb-1">{label}</legend>}
      {hint && <p className="text-[14px] text-slate-500 leading-relaxed">{hint}</p>}
      <div className={`flex flex-wrap gap-2 ${label || hint ? 'mt-3' : ''}`}>
        {options.map(o => {
          const on = value.includes(o)
          return (
            <button
              key={o}
              type="button"
              role={multi ? 'checkbox' : 'radio'}
              aria-checked={on}
              onClick={() => onChange(multi ? (on ? value.filter(v => v !== o) : [...value, o]) : [o])}
              className={authChip(on)}
            >
              {labels[o]}
            </button>
          )
        })}
      </div>
    </fieldset>
  )
}

const GENDERS: readonly Gender[] = ['male', 'female', 'unspecified']
const WORK_MODELS: readonly WorkEnvironment[] = ['onsite', 'hybrid', 'remote', 'any']
const CAREER_CHANGE: readonly CareerChange[] = ['yes', 'maybe', 'no']
const SEARCH_MODES: readonly SearchMode[] = ['radius', 'regions']
const RADII = ['10', '25', '50', 'all'] as const
type Radius = typeof RADII[number]

// ── Steps data ────────────────────────────────────────────────────────────────

// Icons only — title/body live in the dictionaries (onboarding.showcase.steps)
// and are indexed positionally against this list. Keep both in the same order.
const STEP_ICONS = ['🗂️', '⚡', '📊'] as const

// ── Page ──────────────────────────────────────────────────────────────────────

type Phase = 'showcase' | 'account' | 'preferences' | 'intake'

function OnboardingContent() {
  const router = useRouter()
  const { user, updateUserMeta, signOut } = useAuth()
  const { set: setOnboarding }   = useOnboarding()
  const { t } = useI18n()
  const O = t.onboarding
  const A = O.about

  // The step lives in the URL (?step=preferences|intake), not only in state.
  // With state alone the browser's Back button left /onboarding entirely,
  // and coming back started the flow over from the first screen; now Back
  // and Forward move between steps, and a refresh stays on the current one.
  const searchParams = useSearchParams()
  const stepParam = searchParams.get('step')
  const phase: Phase = stepParam === 'account' || stepParam === 'preferences' || stepParam === 'intake' ? stepParam : 'showcase'
  const setPhase = useCallback((next: Phase) => {
    router.push(next === 'showcase' ? '/onboarding' : `/onboarding?step=${next}`)
  }, [router])
  const [active, setActive] = useState(0)

  // Role & seniority step state
  const [selected,  setSelected]  = useState<PendingRole[]>([])
  const [saving,    setSaving]    = useState(false)
  const [saveError, setSaveError] = useState('')
  const [gender,    setGender]    = useState<Gender | null>(null)
  const [locations, setLocations] = useState<Region[]>([])
  const cities = useLocalities()
  const [homeCity,  setHomeCity]  = useState<string | null>(null)
  const [mode,      setMode]      = useState<SearchMode>('radius')
  const [radius,    setRadius]    = useState<Radius>('all')
  const [homeWhere, setHomeWhere] = useState<HomeWhere>('israel')
  const [homeAbroad, setHomeAbroad] = useState('')
  const [showErrors, setShowErrors] = useState(false)
  // Not required, so they start on the answer most people would give (Ron).
  const [work,      setWork]      = useState<WorkEnvironment>('any')
  const [change,    setChange]    = useState<CareerChange>('maybe')

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
    fetchAbout()
      .then(a => {
        setGender(prev => prev ?? a.gender)
        setLocations(prev => prev.length ? prev : a.locations)
        if (a.work_environment) setWork(a.work_environment)
        if (a.career_change) setChange(a.career_change)
        setHomeCity(prev => prev ?? a.home_city ?? null)
        if (a.home_abroad) { setHomeWhere('abroad'); setHomeAbroad(a.home_abroad) }
        // The older backend sends neither field: its saved areas must not read as "no mode".
        setMode(a.search_mode ?? (a.locations.length ? 'regions' : 'radius'))
        // A saved home city with no radius means the whole country was chosen.
        if (a.home_city) setRadius(a.radius_km ? String(a.radius_km) as Radius : 'all')
      })
      .catch(() => { /* empty answers */ })
  }, [])

  // Someone who already finished onboarding came here only to change their
  // roles (from the in-app prompt). Saving takes them back to the app instead
  // of on to the CV upload they already did.
  const alreadyOnboarded =
    (user?.user_metadata as Record<string, unknown> | null)?.profile_completed === true

  // What the product cannot work without, and there is no skipping past it:
  // roles with a level (what to look for), gender (the Hebrew wording; the app
  // would ask at the next login anyway, see RequiredDetailsGate) and where the
  // user lives (what distance is measured from). The city only counts as missing
  // once its list has loaded, so a failed load cannot trap anyone on this step.
  const rolesOk  = selected.length > 0 && selected.every(r => r.seniority)
  const homeOk   = homeWhere === 'abroad' ? homeAbroad.trim() !== '' : Boolean(homeCity) || cities.length === 0
  const hasRoles = rolesOk && gender !== null && homeOk
  const toItems = (): RoleSeniorityItem[] =>
    selected.map(r => ({ role: r.role, seniority: r.seniority ?? '' }))

  const handleSavePreferences = async () => {
    if (!hasRoles) {
      setShowErrors(true)
      const first = !rolesOk ? 'target-roles-combobox' : gender === null ? 'field-gender' : homeWhere === 'abroad' ? 'home-abroad' : 'home-city'
      const el = document.getElementById(first)
      el?.scrollIntoView({ block: 'center' })
      el?.focus({ preventScroll: true })
      return
    }
    setSaving(true)
    setSaveError('')
    try {
      await saveRolePreferences({ roles: toItems() })
      if (gender) {
        const abroad = homeWhere === 'abroad'
        await saveAbout({
          gender,
          locations:        !abroad && mode === 'regions' ? locations : [],
          work_environment: work,
          career_change:    change,
          home_city:        abroad ? null : homeCity,
          home_abroad:      abroad ? homeAbroad.trim() : null,
          search_mode:      mode,
          radius_km:        !abroad && mode === 'radius' && radius !== 'all' ? Number(radius) : null,
        })
      }
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

  const signOutButton = (
    <button type="button" onClick={() => void signOut()}
      className="min-h-[44px] px-2 whitespace-nowrap text-[14px] font-medium text-slate-500 hover:text-slate-900 transition-colors">
      {t.header.sign_out}
    </button>
  )

  // ── Step 1 again, from Back on step 2 ────────────────────────────────────────

  if (phase === 'account') {
    return (
      <AuthLayout headline={t.landing.close.h2} subline={t.landing.close.body} headerEnd={signOutButton}>
        <div key={phase} className="w-full flex justify-center animate-ja-tab-in motion-reduce:animate-none">
          <AccountStep />
        </div>
      </AuthLayout>
    )
  }

  // ── Role & seniority step ────────────────────────────────────────────────────

  if (phase === 'preferences') {
    return (
      <AuthLayout
        headline={O.panels.preferences.headline}
        subline={O.panels.preferences.subline}
        headerEnd={signOutButton}
        back={alreadyOnboarded
          ? { href: '/?tab=overview', label: t.signup.page.back, aria: t.signup.page.back }
          : { href: '/onboarding?step=account', label: t.signup.page.back, aria: O.account.title }}
      >
        <div key={phase} className="w-full max-w-[520px] animate-ja-tab-in motion-reduce:animate-none">
          {!alreadyOnboarded && <SignupSteps current={2} />}
          <h1 className={authTitle}>{O.preferences.title}</h1>
          <p className={authSub}>{O.preferences.intro}</p>

          <div className="mt-8">
            <label htmlFor="target-roles-combobox" className={authLabel}>{O.preferences.roles_label}</label>
            <RolePicker selected={selected} setSelected={setSelected} />
            {showErrors && !rolesOk && <p className="text-[14px] text-rose-600 mt-2" role="alert">{A.errors.roles}</p>}
          </div>

          <div id="field-gender" tabIndex={-1} className="outline-none">
            <Choices
              label={A.gender_label} hint={A.gender_hint}
              options={GENDERS} labels={A.genders}
              value={gender ? [gender] : []} onChange={v => setGender(v[0])}
              disabled={saving}
            />
            {showErrors && gender === null && <p className="text-[14px] text-rose-600 mt-2" role="alert">{A.errors.gender}</p>}
          </div>
          {gender === 'unspecified' && (
            <p className="text-[14px] text-slate-500 mt-3 leading-relaxed">{A.gender_default_note}</p>
          )}

          <div className="mt-8">
            <p className="text-[15px] font-semibold text-slate-900 mb-1">{A.home_label}</p>
            <p className="text-[14px] text-slate-500 leading-relaxed mb-3">{A.home_hint}</p>
            <HomeField
              cities={cities}
              where={homeWhere} onWhere={setHomeWhere}
              city={homeCity} onCity={setHomeCity}
              abroad={homeAbroad} onAbroad={setHomeAbroad}
              error={showErrors && !homeOk ? A.errors.home : undefined}
              disabled={saving}
            />
          </div>

          {/* Distance needs a home we can place, so this stays inside Israel. */}
          {homeWhere === 'israel' && (
            <>
              <Choices
                label={A.range_label} hint={A.range_hint}
                options={SEARCH_MODES} labels={A.range_modes}
                value={[mode]} onChange={v => setMode(v[0])}
                disabled={saving}
              />
              <div key={mode} className="animate-ja-tab-in motion-reduce:animate-none">
                {mode === 'radius' ? (
                  <Choices
                    className="mt-4"
                    options={RADII} labels={A.radius}
                    value={[radius]} onChange={v => setRadius(v[0])}
                    disabled={saving}
                  />
                ) : (
                  <Choices
                    className="mt-4"
                    hint={A.locations_hint}
                    options={REGIONS} labels={A.regions}
                    value={locations} onChange={setLocations} multi
                    disabled={saving}
                  />
                )}
              </div>
            </>
          )}

          <Choices
            label={A.work_label}
            options={WORK_MODELS} labels={A.work}
            value={[work]} onChange={v => setWork(v[0])}
            disabled={saving}
          />

          <Choices
            label={A.change_label}
            options={CAREER_CHANGE} labels={A.change}
            value={[change]} onChange={v => setChange(v[0])}
            disabled={saving}
          />

          {saveError && (
            <p className="text-[14px] text-rose-600 mt-6" role="alert">{saveError}</p>
          )}

          <button
            type="button"
            onClick={handleSavePreferences}
            disabled={saving}
            className={`${authPrimary} mt-10`}
          >
            {saving ? O.preferences.saving : O.preferences.continue_cta}
          </button>
        </div>
      </AuthLayout>
    )
  }

  // ── Intake hub ───────────────────────────────────────────────────────────────

  return (
    <AuthLayout
      headline={O.panels.intake.headline}
      subline={O.panels.intake.subline}
      headerEnd={signOutButton}
      back={{ href: '/onboarding?step=preferences', label: t.signup.page.back, aria: t.signup.page.back }}
    >
      <div key={phase} className="w-full max-w-[440px] animate-ja-tab-in motion-reduce:animate-none">
        <SignupSteps current={3} />
        <h1 className={authTitle}>{O.intake.title}</h1>
        <p className={authSub}>{O.intake.intro}</p>

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
          type="button"
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
          className={`mt-8 w-full flex flex-col items-center gap-4 rounded-2xl border-2 border-dashed px-6 py-10 text-center transition-[background-color,border-color,transform] duration-ja-ui active:scale-[0.99] active:duration-ja-press hover:border-teal-600 hover:bg-teal-50/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-600 disabled:opacity-60 disabled:pointer-events-none ${
            cvDragOver ? 'border-teal-600 bg-teal-50/60' : 'border-slate-200'
          }`}
        >
          <span className="w-12 h-12 rounded-xl bg-teal-50 flex items-center justify-center text-ja-primaryHover">
            {cvBusy ? <SpinnerIcon s={22} /> : <UploadIcon s={22} />}
          </span>
          {cvBusy ? (
            <span>
              <span className="block text-[16px] font-semibold text-slate-900">
                {(cvFileCount === 1 ? O.intake.uploading_one : O.intake.uploading_many)
                  .replace('{n}', String(cvFileCount))}
              </span>
              <span className="block text-[14px] text-slate-500 mt-1">{O.intake.analyzing}</span>
            </span>
          ) : (
            <span>
              <span className="block text-[16px] font-semibold text-slate-900">{O.intake.upload_cta}</span>
              <span className="block text-[14px] text-slate-500 mt-1 leading-relaxed">{O.intake.upload_hint}</span>
            </span>
          )}
        </button>
        {cvBusy && <CvUploadProgress stage={cvStage} />}
        {cvError && (
          <p className="text-[14px] text-rose-600 mt-3" role="alert">{cvError}</p>
        )}

        {/* Testers uploaded other documents here (e.g. a regulations PDF) and
            got nothing back. Say up front what belongs here and where the
            rest goes, rather than only after a failed upload. */}
        <p className="text-[14px] text-slate-500 mt-5 leading-relaxed">
          {O.intake.cv_only_note}
        </p>

        {/* Skip — straight to the dashboard (profile stays incomplete) */}
        <button
          type="button"
          onClick={() => router.push('/?tab=overview')}
          disabled={cvBusy}
          className="w-full mt-4 min-h-[44px] text-[14px] font-medium text-slate-500 hover:text-slate-900 transition-colors disabled:opacity-40"
        >
          {O.intake.skip}
        </button>
      </div>
    </AuthLayout>
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
