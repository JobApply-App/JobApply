'use client'

import { Suspense, useCallback, useEffect, useRef, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useI18n } from '@/contexts/I18nContext'
import AuthGuard            from '@/components/AuthGuard'
import { useAuth }          from '@/contexts/AuthContext'
import { useOnboarding }    from '@/contexts/OnboardingContext'
import { resolveDisplayName } from '@/lib/nameUtils'
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
import { CityPicker, type HomeCity } from '@/components/auth/CityPicker'
import { CvDropzone } from '@/components/auth/CvDropzone'
import { SignupSteps } from '@/components/auth/SignupSteps'
import { WelcomeScene } from '@/components/auth/WelcomeScene'
import { authChip, authInput, authLabel, authPrimary, authSub, authTitle } from '@/components/auth/authStyles'
import { armArielWelcome } from '@/lib/onboardingFlags'
import { RolePicker, type PendingRole } from '@/components/RolePicker'

// ── Icons ─────────────────────────────────────────────────────────────────────

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
const HOME_WHERE = ['israel', 'abroad'] as const
const RADII = ['10', '25', '50', 'all'] as const
type Radius = typeof RADII[number]

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

  // Role & seniority step state
  const [selected,  setSelected]  = useState<PendingRole[]>([])
  const [saving,    setSaving]    = useState(false)
  const [saveError, setSaveError] = useState('')
  const [gender,    setGender]    = useState<Gender | null>(null)
  const [locations, setLocations] = useState<Region[]>([])
  const [cities,    setCities]    = useState<HomeCity[]>([])
  const [homeCity,  setHomeCity]  = useState<string | null>(null)
  const [mode,      setMode]      = useState<SearchMode>('radius')
  const [radius,    setRadius]    = useState<Radius>('all')
  const [homeWhere, setHomeWhere] = useState<typeof HOME_WHERE[number]>('israel')
  const [homeAbroad, setHomeAbroad] = useState('')
  const [showErrors, setShowErrors] = useState(false)
  // Not required, so they start on the answer most people would give (Ron).
  const [work,      setWork]      = useState<WorkEnvironment>('any')
  const [change,    setChange]    = useState<CareerChange>('maybe')

  // CV upload state (in-place — no intermediate screen)
  const [cvBusy,      setCvBusy]      = useState(false)
  const [cvStage,     setCvStage]     = useState<CvUploadStage>('uploading')
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
    // Bundled, not fetched: about 50 KB that only this step needs.
    import('@/lib/israelLocalities.json')
      .then(m => setCities(m.default as HomeCity[]))
      .catch(err => console.error('[onboarding] could not load the localities list:', err))
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

  const signOutButton = (
    <button type="button" onClick={() => void signOut()}
      className="min-h-[44px] px-2 whitespace-nowrap text-[14px] font-medium text-slate-500 hover:text-slate-900 transition-colors">
      {t.header.sign_out}
    </button>
  )

  // ── Welcome ──────────────────────────────────────────────────────────────────

  if (phase === 'showcase') {
    const meta = user?.user_metadata as Record<string, unknown> | null
    const name = String(meta?.full_name ?? meta?.name ?? '').trim() || null
    return <WelcomeScene name={name} onStart={() => setPhase('preferences')} headerEnd={signOutButton} />
  }

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

          <Choices
            label={A.home_label} hint={A.home_hint}
            options={HOME_WHERE} labels={A.home_where}
            value={[homeWhere]} onChange={v => setHomeWhere(v[0])}
            disabled={saving}
          />
          <div key={homeWhere} className="mt-4 animate-ja-tab-in motion-reduce:animate-none">
            {homeWhere === 'israel' ? (
              <CityPicker id="home-city" cities={cities} value={homeCity} onChange={setHomeCity} disabled={saving} />
            ) : (
              <>
                <label htmlFor="home-abroad" className={authLabel}>{A.home_abroad_label}</label>
                <input id="home-abroad" value={homeAbroad} maxLength={80} disabled={saving}
                  placeholder={A.home_abroad_placeholder}
                  onChange={e => setHomeAbroad(e.target.value)} className={authInput()} />
              </>
            )}
            {showErrors && !homeOk && <p className="text-[14px] text-rose-600 mt-2" role="alert">{A.errors.home}</p>}
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
          <p className="mt-4 text-center text-[13px] text-slate-500">{A.credit}</p>
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

        <CvDropzone
          busy={cvBusy}
          stage={cvStage}
          error={cvError}
          onFiles={files => void handleCvFiles(files)}
          onWrongType={() => setCvError(O.intake.wrong_type)}
        />

        {/* Testers uploaded other documents here (e.g. a regulations PDF) and
            got nothing back. Say up front what belongs here and where the
            rest goes, rather than only after a failed upload. */}
        {!cvBusy && (
          <p className="text-[14px] text-slate-500 mt-5 leading-relaxed">
            {O.intake.cv_only_note}
          </p>
        )}

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
