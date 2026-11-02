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
import { CareerCard } from '@/components/auth/CareerCard'
import { useLocalities } from '@/components/auth/CityPicker'
import { CvDropzone } from '@/components/auth/CvDropzone'
import { HomeField, type HomeWhere } from '@/components/auth/HomeField'
import { KycShell } from '@/components/auth/KycShell'
import { WelcomeScene } from '@/components/auth/WelcomeScene'
import { authLabel, kycOption, kycPrimary, kycSub, kycTitle } from '@/components/auth/authStyles'
import { roleLabel } from '@/lib/roleCatalog'
import { armArielWelcome } from '@/lib/onboardingFlags'
import { RolePicker, SENIORITY_VALUES, type PendingRole } from '@/components/RolePicker'

// ── Icons ─────────────────────────────────────────────────────────────────────

// One question with a few answers. multi: any number may be on (areas).
function Choices<T extends string>({ label, hint, options, labels, value, onChange, multi = false, disabled, className = 'mt-6' }: {
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
      {label && <legend className="block text-[17px] font-semibold tracking-tight text-slate-900 mb-1">{label}</legend>}
      {hint && <p className="text-[15px] text-slate-600 leading-relaxed">{hint}</p>}
      <div className={`grid grid-cols-2 sm:grid-cols-[repeat(auto-fit,minmax(112px,1fr))] gap-2.5 ${label || hint ? 'mt-3' : ''}`}>
        {options.map(o => {
          const on = value.includes(o)
          return (
            <button
              key={o}
              type="button"
              role={multi ? 'checkbox' : 'radio'}
              aria-checked={on}
              onClick={() => onChange(multi ? (on ? value.filter(v => v !== o) : [...value, o]) : [o])}
              className={kycOption(on)}
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

// ── Page ──────────────────────────────────────────────────────────────────────

type Phase = 'showcase' | 'account' | 'preferences' | 'intake'

function OnboardingContent() {
  const router = useRouter()
  const { user, updateUserMeta, signOut } = useAuth()
  const { set: setOnboarding }   = useOnboarding()
  const { t, locale } = useI18n()
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

  // The question within that step, in the URL for the same reason.
  const qParam = Number(searchParams.get('q'))
  const question = qParam >= 1 && qParam <= 4 ? qParam : 1
  const seenQuestion = useRef(question)
  const forward = useRef(true)
  if (seenQuestion.current !== question) {
    forward.current = question > seenQuestion.current
    seenQuestion.current = question
  }
  const [accountName, setAccountName] = useState<string | null>(null)
  // Set when an unanswered question sends the user back to it, focused once it is on screen.
  const pendingFocus = useRef<string | null>(null)
  useEffect(() => {
    if (!pendingFocus.current) return
    const el = document.getElementById(pendingFocus.current)
    pendingFocus.current = null
    el?.scrollIntoView({ block: 'center' })
    el?.focus({ preventScroll: true })
  }, [question])

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
      const [q, first] = !rolesOk ? [1, 'target-roles-combobox'] : gender === null ? [2, 'field-gender'] : [3, homeWhere === 'abroad' ? 'home-abroad' : 'home-city']
      if (q === question) {
        const el = document.getElementById(first)
        el?.scrollIntoView({ block: 'center' })
        el?.focus({ preventScroll: true })
      } else {
        pendingFocus.current = first
        router.push(`/onboarding?step=preferences&q=${q}`)
      }
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

  const nextQuestion = () => {
    const missing = question === 1 ? (rolesOk ? null : 'target-roles-combobox')
      : question === 2 ? (gender !== null ? null : 'field-gender')
      : question === 3 && !homeOk ? (homeWhere === 'abroad' ? 'home-abroad' : 'home-city')
      : null
    if (missing) {
      setShowErrors(true)
      const el = document.getElementById(missing)
      el?.scrollIntoView({ block: 'center' })
      el?.focus({ preventScroll: true })
      return
    }
    setShowErrors(false)
    router.push(`/onboarding?step=preferences&q=${question + 1}`)
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

  const metaName = (() => {
    const meta = user?.user_metadata as Record<string, unknown> | null
    return String(meta?.full_name ?? meta?.name ?? '').trim() || null
  })()
  const firstRole = selected[0]
  const roleValue = firstRole
    ? [
        roleLabel(firstRole.role, locale),
        firstRole.seniority && O.preferences.seniority[SENIORITY_VALUES.indexOf(firstRole.seniority)],
      ].filter(Boolean).join(', ') + (selected.length > 1 ? ` +${selected.length - 1}` : '')
    : null
  const cityValue = cities.find(c => c.en === homeCity)
  const homeValue = homeWhere === 'abroad'
    ? homeAbroad.trim() || null
    : homeCity && (locale === 'he' && cityValue ? cityValue.he : homeCity)
  // Work starts on a default, so it joins the card once the user has reached it.
  const card = (
    <CareerCard
      name={accountName?.trim() || metaName}
      role={roleValue}
      home={homeValue}
      work={phase === 'intake' || (phase === 'preferences' && question === 4) ? A.work[work] : null}
      scanning={cvBusy}
    />
  )

  if (phase === 'account') {
    return (
      <KycShell step={1} progress={0.2} aside={card} headerEnd={signOutButton}
        caption={{ headline: t.landing.close.h2, subline: t.landing.close.body }}>
        <div key={phase} className="w-full animate-ja-tab-in motion-reduce:animate-none">
          <AccountStep onName={setAccountName} />
        </div>
      </KycShell>
    )
  }

  // ── Role & seniority step, one question at a time ────────────────────────────

  if (phase === 'preferences') {
    const titles = [
      { title: O.preferences.title, hint: O.preferences.intro },
      { title: A.gender_label,      hint: A.gender_hint },
      { title: A.home_label,        hint: A.home_hint },
      { title: A.work_label,        hint: null },
    ]
    const { title, hint } = titles[question - 1]
    const back = question > 1
      ? { href: `/onboarding?step=preferences&q=${question - 1}`, label: t.signup.page.back, aria: t.signup.page.back }
      : alreadyOnboarded
        ? { href: '/?tab=overview', label: t.signup.page.back, aria: t.signup.page.back }
        : { href: '/onboarding?step=account', label: t.signup.page.back, aria: O.account.title }
    return (
      <KycShell
        step={alreadyOnboarded ? undefined : 2}
        progress={alreadyOnboarded ? question / 4 : 0.2 + question * 0.12}
        aside={card}
        caption={{ headline: O.panels.preferences.headline, subline: O.panels.preferences.subline }}
        headerEnd={signOutButton}
        back={back}
      >
        <div key={question} className={`w-full motion-reduce:!animate-ja-fade ${
          forward.current ? 'animate-ja-from-end rtl:animate-ja-from-start' : 'animate-ja-from-start rtl:animate-ja-from-end'
        }`}>
          <h1 className={kycTitle}>{title}</h1>
          {hint && <p className={kycSub}>{hint}</p>}

          {question === 1 && (
            <div className="mt-8">
              <label htmlFor="target-roles-combobox" className={authLabel}>{O.preferences.roles_label}</label>
              <RolePicker selected={selected} setSelected={setSelected} />
              {showErrors && !rolesOk && <p className="text-[14px] text-rose-600 mt-2" role="alert">{A.errors.roles}</p>}
            </div>
          )}

          {question === 2 && (
            <>
              <div id="field-gender" tabIndex={-1} className="outline-none">
                <Choices
                  options={GENDERS} labels={A.genders}
                  value={gender ? [gender] : []} onChange={v => setGender(v[0])}
                  disabled={saving}
                />
                {showErrors && gender === null && <p className="text-[14px] text-rose-600 mt-2" role="alert">{A.errors.gender}</p>}
              </div>
              {gender === 'unspecified' && (
                <p className="text-[15px] text-slate-600 mt-4 leading-relaxed animate-ja-tab-in motion-reduce:animate-none">{A.gender_default_note}</p>
              )}
            </>
          )}

          {question === 3 && (
            <>
              <div className="mt-6">
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
                        className="mt-3"
                        options={RADII} labels={A.radius}
                        value={[radius]} onChange={v => setRadius(v[0])}
                        disabled={saving}
                      />
                    ) : (
                      <Choices
                        className="mt-3"
                        hint={A.locations_hint}
                        options={REGIONS} labels={A.regions}
                        value={locations} onChange={setLocations} multi
                        disabled={saving}
                      />
                    )}
                  </div>
                </>
              )}
            </>
          )}

          {question === 4 && (
            <>
              <Choices
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
            </>
          )}

          <div className="max-lg:sticky max-lg:bottom-0 z-10 max-lg:-mx-5 max-sm:px-5 sm:max-lg:-mx-10 sm:max-lg:px-10 mt-7 max-lg:pb-4 max-lg:pt-3 max-lg:bg-white/60 max-lg:backdrop-blur-xl [@media(prefers-reduced-transparency:reduce)]:max-lg:bg-white">
            <button type="button" onClick={question < 4 ? nextQuestion : handleSavePreferences} disabled={saving} className={`${kycPrimary} max-lg:ms-14 max-lg:w-[calc(100%-3.5rem)]`}>
              {saving ? O.preferences.saving : O.preferences.continue_cta}
            </button>
          </div>
        </div>
      </KycShell>
    )
  }

  // ── Intake hub ───────────────────────────────────────────────────────────────

  return (
    <KycShell
      step={3}
      progress={0.85}
      aside={card}
      caption={{ headline: O.panels.intake.headline, subline: O.panels.intake.subline }}
      headerEnd={signOutButton}
      back={{ href: '/onboarding?step=preferences&q=4', label: t.signup.page.back, aria: t.signup.page.back }}
    >
      <div key={phase} className="w-full animate-ja-tab-in motion-reduce:animate-none">
        <h1 className={kycTitle}>{O.intake.title}</h1>
        <p className={kycSub}>{O.intake.intro}</p>

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
          <p className="text-[14px] text-slate-600 mt-5 leading-relaxed">
            {O.intake.cv_only_note}
          </p>
        )}

        {/* Skip — straight to the dashboard (profile stays incomplete) */}
        <button
          type="button"
          onClick={() => router.push('/?tab=overview')}
          disabled={cvBusy}
          className="w-full mt-4 min-h-[44px] text-[14px] font-medium text-slate-600 hover:text-slate-900 transition-colors disabled:opacity-40"
        >
          {O.intake.skip}
        </button>
      </div>
    </KycShell>
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
