'use client'

import { useState, useRef, type FormEvent } from 'react'
import { useRouter }           from 'next/navigation'
import Link                    from 'next/link'
import { useAuth }             from '@/contexts/AuthContext'
import { LanguageSwitcher }    from '@/components/LanguageSwitcher'
import { AuthLayout }          from '@/components/auth/AuthLayout'
import { PasswordMeter, evaluatePassword } from '@/components/auth/PasswordMeter'
import { TOKENS }              from '@/lib/tokens'

// ── Types ─────────────────────────────────────────────────────────────────────

type LoginPhase =
  | 'login'              // normal sign-in form
  | 'forgot-email'       // enter email to receive OTP
  | 'forgot-otp'         // enter 6-digit OTP
  | 'forgot-new-pw'      // enter and confirm new password

// ── Shared icons ──────────────────────────────────────────────────────────────

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

// ── Input class helper ────────────────────────────────────────────────────────

function inputCls(hasError = false) {
  return `w-full rounded-lg border bg-slate-50 px-3 py-2.5 text-sm text-slate-900 outline-none
    transition placeholder:text-slate-400 disabled:opacity-50 ${
    hasError
      ? 'border-rose-400 focus:border-rose-400 focus:ring-2 focus:ring-rose-500/20'
      : 'border-slate-200 focus:border-teal-400 focus:ring-2 focus:ring-teal-500/20'
  }`
}

// ── Error banner ──────────────────────────────────────────────────────────────

function ErrorBanner({ msg }: { msg: string }) {
  return (
    <div className="flex items-start gap-2 rounded-lg px-3 py-2.5 text-xs bg-ja-dangerSubtle text-ja-danger"
      role="alert">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        strokeWidth="2" strokeLinecap="round" className="flex-shrink-0 mt-0.5" aria-hidden="true">
        <circle cx="12" cy="12" r="10" />
        <line x1="12" y1="8" x2="12" y2="12" />
        <line x1="12" y1="16" x2="12.01" y2="16" />
      </svg>
      <span>{msg}</span>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function LoginPage() {
  const { signIn, signInWithGoogle, sendPasswordResetOtp, verifyPasswordResetOtp, updatePassword } = useAuth()
  const router = useRouter()

  // ── Login form state ───────────────────────────────────────────────────────
  const [email,         setEmail]         = useState('')
  const [password,      setPassword]      = useState('')
  const [showPassword,  setShowPassword]  = useState(false)

  // ── Forgot password state ──────────────────────────────────────────────────
  const [phase,         setPhase]         = useState<LoginPhase>('login')
  const [fpEmail,       setFpEmail]       = useState('')
  const [otp,           setOtp]           = useState(['','','','','',''])
  const [newPw,         setNewPw]         = useState('')
  const [showNewPw,     setShowNewPw]     = useState(false)
  const otpRefs = [
    useRef<HTMLInputElement>(null),
    useRef<HTMLInputElement>(null),
    useRef<HTMLInputElement>(null),
    useRef<HTMLInputElement>(null),
    useRef<HTMLInputElement>(null),
    useRef<HTMLInputElement>(null),
  ]

  // ── Shared ─────────────────────────────────────────────────────────────────
  const [busy,          setBusy]          = useState(false)
  const [googleBusy,    setGoogleBusy]    = useState(false)
  const [error,         setError]         = useState<string | null>(null)
  const [successMsg,    setSuccessMsg]    = useState<string | null>(null)

  const newPwStrength = evaluatePassword(newPw)

  // ── Handlers: normal login ─────────────────────────────────────────────────
  async function handleLogin(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await signIn(email, password)
      router.replace('/')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Sign-in failed.')
    } finally {
      setBusy(false)
    }
  }

  async function handleGoogle() {
    setError(null)
    setGoogleBusy(true)
    try {
      await signInWithGoogle(`${window.location.origin}/auth/callback`)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Google sign-in failed.')
      setGoogleBusy(false)
    }
  }

  // ── Handlers: forgot password ──────────────────────────────────────────────
  async function handleSendOtp(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await sendPasswordResetOtp(fpEmail.trim())
      setSuccessMsg(`A 6-digit code was sent to ${fpEmail}`)
      setPhase('forgot-otp')
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to send code.'
      // Supabase won't create a new user — surface a clear message
      if (msg.toLowerCase().includes('signups not allowed') || msg.toLowerCase().includes('not found')) {
        setError('No account found with that email address.')
      } else {
        setError(msg)
      }
    } finally {
      setBusy(false)
    }
  }

  async function handleVerifyOtp(e: FormEvent) {
    e.preventDefault()
    const code = otp.join('')
    if (code.length < 6) { setError('Enter all 6 digits.'); return }
    setError(null)
    setBusy(true)
    try {
      await verifyPasswordResetOtp(fpEmail.trim(), code)
      setSuccessMsg(null)
      setPhase('forgot-new-pw')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Invalid code. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  async function handleSetNewPassword(e: FormEvent) {
    e.preventDefault()
    if (newPwStrength.level === 'weak' || newPwStrength.level === 'empty') {
      setError('Please choose a stronger password.')
      return
    }
    setError(null)
    setBusy(true)
    try {
      await updatePassword(newPw)
      router.replace('/')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to update password.')
    } finally {
      setBusy(false)
    }
  }

  function handleOtpInput(idx: number, val: string) {
    const digit = val.replace(/\D/g, '').slice(-1)
    const next  = [...otp]
    next[idx]   = digit
    setOtp(next)
    if (digit && idx < 5) otpRefs[idx + 1].current?.focus()
  }

  function handleOtpKeyDown(idx: number, e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Backspace' && !otp[idx] && idx > 0) {
      otpRefs[idx - 1].current?.focus()
    }
  }

  function resetToLogin() {
    setPhase('login')
    setError(null)
    setSuccessMsg(null)
    setFpEmail('')
    setOtp(['','','','','',''])
    setNewPw('')
  }

  // ── Forgot password sub-views ─────────────────────────────────────────────

  function ForgotEmailView() {
    return (
      <form onSubmit={handleSendOtp} className="space-y-5">
        <div>
          <h2 className="text-xl font-bold text-slate-900 tracking-tight">Reset your password</h2>
          <p className="text-sm text-slate-500 mt-1">
            Enter your account email — we&apos;ll send a 6-digit code.
          </p>
        </div>
        <div>
          <label htmlFor="fpEmail" className="block text-xs font-medium text-slate-700 mb-1.5">Email</label>
          <input
            id="fpEmail"
            type="email"
            required
            disabled={busy}
            autoFocus
            value={fpEmail}
            onChange={e => { setError(null); setFpEmail(e.target.value) }}
            placeholder="you@example.com"
            className={inputCls()}
          />
        </div>
        {error && <ErrorBanner msg={error} />}
        <button type="submit" disabled={busy || !fpEmail.includes('@')}
          className="w-full rounded-lg py-2.5 text-sm font-semibold text-white flex items-center justify-center gap-2 transition-opacity disabled:opacity-50"
          style={{ background: TOKENS.color.primary }}>
          {busy && <span className="w-4 h-4 rounded-full border-2 border-white/40 border-t-white animate-spin" />}
          {busy ? 'Sending…' : 'Send Code'}
        </button>
        <button type="button" onClick={resetToLogin}
          className="w-full text-sm text-slate-400 hover:text-slate-700 transition-colors">
          ← Back to sign in
        </button>
      </form>
    )
  }

  function ForgotOtpView() {
    return (
      <form onSubmit={handleVerifyOtp} className="space-y-5">
        <div>
          <h2 className="text-xl font-bold text-slate-900 tracking-tight">Enter the code</h2>
          {successMsg && (
            <p className="text-sm text-teal-700 mt-1 bg-teal-50 border border-teal-200 rounded-lg px-3 py-2">
              {successMsg}
            </p>
          )}
        </div>

        {/* OTP digit inputs */}
        <div className="flex gap-2 justify-center">
          {otp.map((digit, i) => (
            <input
              key={i}
              ref={otpRefs[i]}
              type="text"
              inputMode="numeric"
              maxLength={1}
              value={digit}
              onChange={e => handleOtpInput(i, e.target.value)}
              onKeyDown={e => handleOtpKeyDown(i, e)}
              disabled={busy}
              className="w-11 h-12 rounded-xl border border-slate-200 bg-slate-50 text-center text-xl font-bold text-slate-900
                outline-none focus:border-teal-400 focus:ring-2 focus:ring-teal-500/20 transition disabled:opacity-50"
              autoFocus={i === 0}
              aria-label={`OTP digit ${i + 1}`}
            />
          ))}
        </div>

        {error && <ErrorBanner msg={error} />}
        <button type="submit" disabled={busy || otp.join('').length < 6}
          className="w-full rounded-lg py-2.5 text-sm font-semibold text-white flex items-center justify-center gap-2 transition-opacity disabled:opacity-50"
          style={{ background: TOKENS.color.primary }}>
          {busy && <span className="w-4 h-4 rounded-full border-2 border-white/40 border-t-white animate-spin" />}
          {busy ? 'Verifying…' : 'Verify Code'}
        </button>
        <div className="flex items-center justify-between text-xs text-slate-400">
          <button type="button" onClick={resetToLogin} className="hover:text-slate-700 transition-colors">
            ← Back
          </button>
          <button type="button" disabled={busy}
            onClick={() => { setError(null); void handleSendOtp({ preventDefault: () => {} } as FormEvent) }}
            className="text-teal-600 hover:text-teal-800 font-medium transition-colors disabled:opacity-50">
            Resend code
          </button>
        </div>
      </form>
    )
  }

  function ForgotNewPwView() {
    return (
      <form onSubmit={handleSetNewPassword} className="space-y-5">
        <div>
          <h2 className="text-xl font-bold text-slate-900 tracking-tight">Set new password</h2>
          <p className="text-sm text-slate-500 mt-1">Choose a strong password for your account.</p>
        </div>
        <div>
          <label htmlFor="newPw" className="block text-xs font-medium text-slate-700 mb-1.5">New Password</label>
          <div className="relative">
            <input
              id="newPw"
              type={showNewPw ? 'text' : 'password'}
              required
              minLength={8}
              disabled={busy}
              autoFocus
              value={newPw}
              onChange={e => { setError(null); setNewPw(e.target.value) }}
              placeholder="Min. 8 characters"
              className={`${inputCls()} pr-10`}
            />
            <button type="button" tabIndex={-1}
              onClick={() => setShowNewPw(v => !v)}
              className="absolute inset-y-0 right-0 flex items-center px-3 text-slate-400 hover:text-slate-600 transition-colors"
              aria-label={showNewPw ? 'Hide password' : 'Show password'}>
              {showNewPw ? <EyeClosedIcon /> : <EyeOpenIcon />}
            </button>
          </div>
          <PasswordMeter password={newPw} />
        </div>
        {error && <ErrorBanner msg={error} />}
        <button type="submit"
          disabled={busy || newPwStrength.level === 'weak' || newPwStrength.level === 'empty'}
          className="w-full rounded-lg py-2.5 text-sm font-semibold text-white flex items-center justify-center gap-2 transition-opacity disabled:opacity-50"
          style={{ background: TOKENS.color.primary }}>
          {busy && <span className="w-4 h-4 rounded-full border-2 border-white/40 border-t-white animate-spin" />}
          {busy ? 'Saving…' : 'Save Password & Sign In'}
        </button>
      </form>
    )
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <AuthLayout
      leftHeadline="Welcome back."
      leftEyebrow="Your career engine is ready"
      leftSubline="Ariel has been tracking new opportunities for you. Sign in to review your matches and continue building your profile."
    >
      {/* Header strip */}
      <header className="flex-shrink-0 w-full">
        <div className="h-16 flex items-center justify-between px-6 sm:px-10">
          <Link href="/"
            className="inline-flex items-center gap-1.5 text-sm font-medium text-slate-500 hover:text-slate-900 transition-colors"
            aria-label="Back to home">
            <ArrowLeftIcon />
            Back
          </Link>
          <div className="flex items-center gap-3">
            <LanguageSwitcher />
            <Link href="/signup"
              className="inline-flex items-center h-9 px-4 rounded-lg text-sm font-semibold text-white transition-opacity hover:opacity-90"
              style={{ background: TOKENS.color.primary }}>
              Get Started
            </Link>
          </div>
        </div>
      </header>

      {/* Form area */}
      <div className="flex flex-1 items-center justify-center px-6 py-10">
        <div className="w-full max-w-sm">

          {/* Sub-views for forgot password */}
          {phase === 'forgot-email'  && <ForgotEmailView  />}
          {phase === 'forgot-otp'    && <ForgotOtpView    />}
          {phase === 'forgot-new-pw' && <ForgotNewPwView  />}

          {/* Normal login */}
          {phase === 'login' && (
            <>
              <div className="mb-7">
                <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Sign in</h1>
                <p className="text-sm text-slate-500 mt-1">Access your account and job matches</p>
              </div>

              <div
                className="bg-white rounded-2xl border border-slate-100 p-8 space-y-5"
                style={{ boxShadow: '0 2px 8px rgba(0,0,0,0.02),0 20px 40px rgba(0,0,0,0.04)' }}
              >
                {/* Google */}
                <button type="button" onClick={handleGoogle}
                  disabled={busy || googleBusy}
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
                    <span className="bg-white px-3">or sign in with email</span>
                  </div>
                </div>

                {/* Form */}
                <form onSubmit={handleLogin} className="space-y-4">
                  <div>
                    <label htmlFor="email" className="block text-xs font-medium text-slate-700 mb-1.5">Email</label>
                    <input id="email" type="email" autoComplete="username" required
                      disabled={busy} value={email}
                      onChange={e => { setError(null); setEmail(e.target.value) }}
                      className={inputCls()} />
                  </div>

                  <div>
                    <div className="flex items-center justify-between mb-1.5">
                      <label htmlFor="password" className="block text-xs font-medium text-slate-700">
                        Password
                      </label>
                      <button type="button"
                        onClick={() => { setFpEmail(email); setPhase('forgot-email'); setError(null) }}
                        className="text-xs text-teal-600 hover:text-teal-800 font-medium transition-colors">
                        Forgot password?
                      </button>
                    </div>
                    <div className="relative">
                      <input id="password" type={showPassword ? 'text' : 'password'}
                        autoComplete="current-password" required disabled={busy}
                        value={password}
                        onChange={e => { setError(null); setPassword(e.target.value) }}
                        className={`${inputCls()} pr-10`} />
                      <button type="button" tabIndex={-1}
                        onClick={() => setShowPassword(v => !v)}
                        className="absolute inset-y-0 right-0 flex items-center px-3 text-slate-400 hover:text-slate-600 transition-colors"
                        aria-label={showPassword ? 'Hide password' : 'Show password'}>
                        {showPassword ? <EyeClosedIcon /> : <EyeOpenIcon />}
                      </button>
                    </div>
                  </div>

                  {error && <ErrorBanner msg={error} />}

                  <button type="submit" disabled={busy}
                    className="w-full rounded-lg py-2.5 text-sm font-semibold text-white flex items-center justify-center gap-2 transition-opacity disabled:opacity-50"
                    style={{ background: TOKENS.color.primary }}>
                    {busy && <span className="w-4 h-4 rounded-full border-2 border-white/40 border-t-white animate-spin" />}
                    {busy ? 'Signing in…' : 'Sign in'}
                  </button>
                </form>

                <p className="text-center text-xs text-slate-500">
                  Don&apos;t have an account?{' '}
                  <Link href="/signup"
                    className="font-semibold text-teal-600 hover:text-teal-800 transition-colors">
                    Get Started
                  </Link>
                </p>
              </div>
            </>
          )}
        </div>
      </div>
    </AuthLayout>
  )
}
