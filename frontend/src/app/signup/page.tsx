'use client'

import {
  useState,
  useEffect,
  useRef,
  useCallback,
  type FormEvent,
  type ChangeEvent,
} from 'react'
import dynamic                      from 'next/dynamic'
import { isValidPhoneNumber }       from 'react-phone-number-input'
import { useRouter }                from 'next/navigation'
import Link                         from 'next/link'
import { useAuth }                  from '@/contexts/AuthContext'
import { useOnboarding }            from '@/contexts/OnboardingContext'
import { getAuthHeaders }           from '@/lib/api'
import { LanguageSwitcher }         from '@/components/LanguageSwitcher'
import { AuthLayout }               from '@/components/auth/AuthLayout'
import { CareerStageCards, type CareerStage } from '@/components/auth/CareerStageCards'
import { evaluatePassword }         from '@/components/auth/PasswordMeter'
import { TOKENS }                   from '@/lib/tokens'

// ── SSR-safe dynamic imports (prevents hydration mismatch) ───────────────────
const PhoneInput = dynamic(
  () => import('@/components/auth/PhoneInput').then(m => ({ default: m.PhoneInput })),
  { ssr: false, loading: () => <div className="h-[42px] rounded-lg border border-slate-200 bg-slate-50 animate-pulse" /> }
)

const PasswordMeter = dynamic(
  () => import('@/components/auth/PasswordMeter').then(m => ({ default: m.PasswordMeter })),
  { ssr: false }
)

const LOG = '[JobApply-Debug][signup]'

// ── Icons ─────────────────────────────────────────────────────────────────────

function ArrowLeftIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true">
      <line x1="19" y1="12" x2="5" y2="12" />
      <polyline points="12 19 5 12 12 5" />
    </svg>
  )
}

function EyeOpenIcon() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M1 12S5 5 12 5s11 7 11 7-4 7-11 7S1 12 1 12z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  )
}

function EyeClosedIcon() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20C5 20 1 12 1 12a18.45 18.45 0 0 1 5.06-5.94" />
      <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
      <line x1="1" y1="1" x2="23" y2="23" />
    </svg>
  )
}

function GoogleLogo() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true">
      <path d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844c-.209 1.125-.843 2.078-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.875 2.684-6.616z" fill="#4285F4"/>
      <path d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18z" fill="#34A853"/>
      <path d="M3.964 10.71A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.042l3.007-2.332z" fill="#FBBC05"/>
      <path d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z" fill="#EA4335"/>
    </svg>
  )
}

// ── Input style helper ────────────────────────────────────────────────────────

function inputCls(hasError = false) {
  return `w-full rounded-lg border bg-slate-50 px-3 py-2.5 text-sm text-slate-900 outline-none
    transition placeholder:text-slate-400 disabled:opacity-50 ${
    hasError
      ? 'border-rose-400 focus:border-rose-400 focus:ring-2 focus:ring-rose-500/20'
      : 'border-slate-200 focus:border-teal-400 focus:ring-2 focus:ring-teal-500/20'
  }`
}

// ── Workspace animation overlay ───────────────────────────────────────────────

function WorkspaceAnimation({ name }: { name: string }) {
  return (
    <div className="fixed inset-0 z-[200] flex flex-col items-center justify-center gap-6"
      style={{ background: 'linear-gradient(145deg, var(--ja-ink) 0%, var(--ja-ink-deep) 60%, var(--ja-ink) 100%)' }}>
      <div className="relative">
        <div className="w-20 h-20 rounded-3xl flex items-center justify-center text-white text-2xl font-extrabold tracking-tight"
          style={{ background: TOKENS.color.primary, animation: 'logo-pulse 1.5s ease-in-out infinite' }}>
          JA
        </div>
        <span className="absolute -bottom-1 -right-1 w-5 h-5 rounded-full border-[3px] bg-green-500"
          style={{ borderColor: 'var(--ja-ink)', animation: 'dot-blink 1.2s ease-in-out infinite' }} />
      </div>
      <div className="text-center space-y-1.5">
        <p className="text-white text-xl font-bold tracking-tight">
          Creating your workspace{name ? `, ${name}` : ''}…
        </p>
        <p className="text-sm" style={{ color: TOKENS.color.primary }}>
          Setting up your career profile
        </p>
      </div>
      <div className="w-52 h-1.5 rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.1)' }}>
        <div className="h-full rounded-full"
          style={{ background: TOKENS.color.primary, animation: 'ws-fill 1.4s ease-in-out forwards' }} />
      </div>
      <style>{`
        @keyframes logo-pulse { 0%,100%{box-shadow:0 0 0 0px ${TOKENS.color.primary}60} 50%{box-shadow:0 0 0 18px ${TOKENS.color.primary}00} }
        @keyframes dot-blink  { 0%,100%{opacity:1} 50%{opacity:0.3} }
        @keyframes ws-fill    { from{width:0%} to{width:100%} }
      `}</style>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function SignupPage() {
  const { signUp, signInWithGoogle } = useAuth()
  const { set: setOnboarding }       = useOnboarding()
  const router = useRouter()

  // ── Field state ───────────────────────────────────────────────────────────
  const [fullName,     setFullName]     = useState('')
  const [phone,        setPhone]        = useState('+972')
  const [careerStage,  setCareerStage]  = useState<CareerStage | ''>('')
  const [email,        setEmail]        = useState('')
  const [password,     setPassword]     = useState('')
  const [showPassword, setShowPassword] = useState(false)

  // ── Async / UI state ──────────────────────────────────────────────────────
  const [busy,          setBusy]          = useState(false)
  const [googleBusy,    setGoogleBusy]    = useState(false)
  const [creating,      setCreating]      = useState(false)
  const [submitError,   setSubmitError]   = useState<string | null>(null)
  const [emailExists,   setEmailExists]   = useState(false)
  const [emailChecking, setEmailChecking] = useState(false)

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // AbortController ref — cancelled when a newer check fires, preventing stale
  // responses from racing and toggling the error state incorrectly.
  const abortRef    = useRef<AbortController | null>(null)

  const pw = evaluatePassword(password)

  // ── Email availability check (debounced + abort-controlled) ──────────────
  const checkEmail = useCallback(async (em: string) => {
    if (!em.includes('@') || !em.includes('.')) { setEmailExists(false); return }

    // Cancel any in-flight request from a previous keystroke
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setEmailChecking(true)
    console.log(`${LOG} checking email availability: ${em}`)

    try {
      const res  = await fetch('/api/auth/check-email', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ email: em }),
        signal:  controller.signal,
      })
      const json = (await res.json()) as { exists?: boolean }
      console.log(`${LOG} check-email response for ${em}:`, json)
      setEmailExists(json.exists === true)
    } catch (err) {
      if ((err as Error).name === 'AbortError') {
        // Superseded by a newer request — do not update state
        console.log(`${LOG} check-email aborted for ${em} (superseded)`)
        return
      }
      console.warn(`${LOG} check-email fetch failed:`, err)
      setEmailExists(false)
    } finally {
      // Only clear spinner if this controller is still the current one
      if (abortRef.current === controller) {
        setEmailChecking(false)
      }
    }
  }, [])

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (!email) {
      abortRef.current?.abort()
      setEmailExists(false)
      setEmailChecking(false)
      return
    }
    debounceRef.current = setTimeout(() => { void checkEmail(email) }, 600)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [email, checkEmail])

  // ── Validation ────────────────────────────────────────────────────────────
  const phoneOk = phone.length > 3 && isValidPhoneNumber(phone)

  const canSubmit =
    fullName.trim().length >= 2                    &&
    phoneOk                                        &&
    careerStage !== ''                             &&
    email.includes('@') && email.includes('.')     &&
    pw.level !== 'empty' && pw.level !== 'weak'   &&
    !emailExists                                   &&
    !emailChecking

  // ── Handlers ──────────────────────────────────────────────────────────────
  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!canSubmit || busy || creating) return
    console.log(`${LOG} submit — email: ${email}, careerStage: ${careerStage}`)
    setSubmitError(null)
    setBusy(true)
    try {
      await signUp(email, password, fullName.trim())
      console.log(`${LOG} signUp success`)
      setOnboarding({ fullName: fullName.trim(), careerStage })

      void fetch('/api/profile/init', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
      }).catch(err => console.warn(`${LOG} profile/init failed:`, err))

      setCreating(true)
      await new Promise(r => setTimeout(r, 1500))
      router.replace('/discover')
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Sign-up failed.'
      console.error(`${LOG} signUp error:`, msg)
      if (msg.toLowerCase().includes('already registered') || msg.toLowerCase().includes('already exists')) {
        setEmailExists(true)
      } else {
        setSubmitError(msg)
      }
      setBusy(false)
    }
  }

  async function handleGoogle() {
    setSubmitError(null)
    setGoogleBusy(true)
    console.log(`${LOG} initiating Google OAuth`)
    try {
      await signInWithGoogle(`${window.location.origin}/auth/callback`)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Google sign-in failed.'
      console.error(`${LOG} Google OAuth error:`, msg)
      setSubmitError(msg)
      setGoogleBusy(false)
    }
  }

  if (creating) return <WorkspaceAnimation name={fullName.split(' ')[0]} />

  const disableAll = busy || googleBusy

  return (
    <AuthLayout
      leftEyebrow="Join thousands of professionals"
      leftHeadline="Your career, intelligently managed."
      leftSubline="Tailoring every CV, mapping every skill gap, and tracking every application."
    >
      {/* Header strip */}
      <header className="flex-shrink-0 w-full">
        <div className="h-16 flex items-center justify-between px-6 sm:px-10">
          <Link href="/login"
            className="inline-flex items-center gap-1.5 text-sm font-medium text-slate-500 hover:text-slate-900 transition-colors"
            aria-label="Back to login">
            <ArrowLeftIcon />
            Back
          </Link>
          <div className="flex items-center gap-3">
            <LanguageSwitcher />
            <Link href="/login"
              className="text-sm font-semibold text-teal-600 hover:text-teal-800 transition-colors">
              Log in
            </Link>
          </div>
        </div>
      </header>

      {/* Form */}
      <div className="flex-1 px-6 sm:px-10 pb-12 pt-4">
        <div className="max-w-lg mx-auto">
          <div className="mb-7">
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Set up your account</h1>
            <p className="text-sm text-slate-500 mt-1">Fill in your details to get started.</p>
          </div>

          <div className="bg-white rounded-2xl border border-slate-100 p-8 space-y-6"
            style={{ boxShadow: '0 2px 8px rgba(0,0,0,0.02),0 20px 40px rgba(0,0,0,0.04)' }}>

            {/* Google SSO */}
            <button type="button" onClick={handleGoogle} disabled={disableAll}
              className="w-full flex items-center justify-center gap-3 rounded-lg border border-slate-200 px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50 transition disabled:opacity-50 disabled:cursor-not-allowed">
              {googleBusy
                ? <span className="w-[18px] h-[18px] rounded-full border-2 border-slate-300 border-t-slate-600 animate-spin flex-shrink-0" />
                : <GoogleLogo />}
              {googleBusy ? 'Redirecting…' : 'Continue with Google'}
            </button>

            {/* Divider */}
            <div className="relative">
              <div className="absolute inset-0 flex items-center">
                <div className="w-full border-t border-slate-100" />
              </div>
              <div className="relative flex justify-center text-xs text-slate-400">
                <span className="bg-white px-3">or fill in your details</span>
              </div>
            </div>

            <form onSubmit={handleSubmit} noValidate className="space-y-5">

              {/* Full Name */}
              <div>
                <label htmlFor="fullName" className="block text-xs font-medium text-slate-700 mb-1.5">
                  Full Name <span className="text-rose-400">*</span>
                </label>
                <input
                  id="fullName" type="text" autoComplete="name" required
                  disabled={disableAll}
                  placeholder="e.g. Ron Cohen"
                  value={fullName}
                  onChange={(e: ChangeEvent<HTMLInputElement>) => {
                    setSubmitError(null)
                    setFullName(e.target.value)
                  }}
                  className={inputCls()}
                />
              </div>

              {/* Phone */}
              <div>
                <label htmlFor="phone" className="block text-xs font-medium text-slate-700 mb-1.5">
                  Phone <span className="text-rose-400">*</span>
                </label>
                <PhoneInput
                  id="phone"
                  value={phone}
                  onChange={v => { setSubmitError(null); setPhone(v) }}
                  disabled={disableAll}
                  hasError={false}
                />
              </div>

              {/* Career Stage */}
              <div>
                <p className="text-xs font-medium text-slate-700 mb-2.5">
                  Career Stage <span className="text-rose-400">*</span>
                </p>
                <CareerStageCards
                  value={careerStage}
                  onChange={v => { setSubmitError(null); setCareerStage(v) }}
                  disabled={disableAll}
                />
                {careerStage !== '' && (
                  <p className="mt-1.5 text-[11px] text-teal-600 flex items-center gap-1">
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                      strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                    Career stage selected
                  </p>
                )}
              </div>

              {/* Email */}
              <div>
                <label htmlFor="email" className="block text-xs font-medium text-slate-700 mb-1.5">
                  Email <span className="text-rose-400">*</span>
                </label>
                <div className="relative">
                  <input
                    id="email" type="email" autoComplete="username" required
                    disabled={disableAll}
                    placeholder="you@example.com"
                    value={email}
                    onChange={(e: ChangeEvent<HTMLInputElement>) => {
                      setSubmitError(null)
                      setEmailExists(false)
                      setEmail(e.target.value)
                    }}
                    className={inputCls(emailExists)}
                  />
                  {emailChecking && (
                    <span className="absolute right-3 top-1/2 -translate-y-1/2">
                      <span className="w-4 h-4 rounded-full border-2 border-slate-300 border-t-slate-600 animate-spin block" />
                    </span>
                  )}
                </div>
                {emailExists && !emailChecking && (
                  <p className="mt-1.5 text-xs text-rose-600" role="alert">
                    Account already exists.{' '}
                    <Link href="/login"
                      className="font-semibold underline hover:text-rose-800 transition-colors">
                      Log in here
                    </Link>
                  </p>
                )}
              </div>

              {/* Password */}
              <div>
                <label htmlFor="password" className="block text-xs font-medium text-slate-700 mb-1.5">
                  Password <span className="text-rose-400">*</span>
                </label>
                <div className="relative">
                  <input
                    id="password" type={showPassword ? 'text' : 'password'}
                    autoComplete="new-password" required minLength={8}
                    disabled={disableAll}
                    placeholder="Min. 8 characters"
                    value={password}
                    onChange={(e: ChangeEvent<HTMLInputElement>) => {
                      setSubmitError(null)
                      setPassword(e.target.value)
                    }}
                    className={`${inputCls(pw.level === 'weak' && password.length > 0)} pr-10`}
                  />
                  <button type="button" tabIndex={-1}
                    onClick={() => setShowPassword(v => !v)}
                    className="absolute inset-y-0 right-0 flex items-center px-3 text-slate-400 hover:text-slate-600 transition-colors"
                    aria-label={showPassword ? 'Hide password' : 'Show password'}>
                    {showPassword ? <EyeClosedIcon /> : <EyeOpenIcon />}
                  </button>
                </div>
                <PasswordMeter password={password} />
              </div>

              {/* Error banner */}
              {submitError && (
                <div className="flex items-start gap-2 rounded-lg px-3 py-2.5 text-xs bg-ja-dangerSubtle text-ja-danger"
                  role="alert">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                    strokeWidth="2" strokeLinecap="round" className="flex-shrink-0 mt-0.5" aria-hidden="true">
                    <circle cx="12" cy="12" r="10" />
                    <line x1="12" y1="8" x2="12" y2="12" />
                    <line x1="12" y1="16" x2="12.01" y2="16" />
                  </svg>
                  <span>{submitError}</span>
                </div>
              )}

              {/* Submit */}
              <button
                type="submit"
                disabled={disableAll || !canSubmit}
                className="w-full rounded-lg py-2.5 text-sm font-semibold text-white flex items-center justify-center gap-2 transition-opacity disabled:opacity-40 disabled:cursor-not-allowed"
                style={{ background: TOKENS.color.primary }}
              >
                {busy && (
                  <span className="w-4 h-4 rounded-full border-2 border-white/40 border-t-white animate-spin flex-shrink-0" />
                )}
                {busy ? 'Creating account…' : 'Create account'}
              </button>
            </form>

            <p className="text-center text-xs text-slate-500">
              Already have an account?{' '}
              <Link href="/login" className="font-semibold text-teal-600 hover:text-teal-800 transition-colors">
                Sign in
              </Link>
            </p>
          </div>

          <p className="mt-6 text-center text-[11px] text-slate-400 leading-relaxed max-w-md mx-auto">
            By creating an account you agree to our{' '}
            <span className="text-teal-600 cursor-pointer hover:underline">Terms of Service</span>
            {' '}and{' '}
            <span className="text-teal-600 cursor-pointer hover:underline">Privacy Policy</span>.
          </p>
        </div>
      </div>
    </AuthLayout>
  )
}
