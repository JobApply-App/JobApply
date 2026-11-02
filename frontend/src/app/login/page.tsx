'use client'

import { useState, useRef, useEffect, type FormEvent } from 'react'
import { useRouter }           from 'next/navigation'
import Link                    from 'next/link'
import { useAuth }             from '@/contexts/AuthContext'
import { useI18n }             from '@/contexts/I18nContext'
import { KycShell }            from '@/components/auth/KycShell'
import { SignInScene }         from '@/components/auth/SignInScene'
import { PasswordMeter, evaluatePassword } from '@/components/auth/PasswordMeter'
import { authInput, authLabel, authSecondary, kycPrimary, kycSub, kycTitle } from '@/components/auth/authStyles'
import { authErrorKind, authErrorMessage } from '@/lib/authErrors'

// ── Types ─────────────────────────────────────────────────────────────────────

type LoginPhase =
  | 'login'              // normal sign-in form
  | 'forgot-email'       // enter email to receive OTP
  | 'forgot-otp'         // enter the emailed OTP (see OTP_LENGTH)
  | 'forgot-new-pw'      // enter and confirm new password

// ── Shared icons ──────────────────────────────────────────────────────────────

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

// ── Error banner ──────────────────────────────────────────────────────────────

function ErrorBanner({ msg }: { msg: string }) {
  return (
    <div className="flex items-start gap-2 rounded-xl px-3.5 py-3 text-[13px] bg-ja-dangerSubtle text-ja-danger"
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

// The "back" affordance points left in LTR and right in RTL — a hardcoded
// "←" points forward, not back, for a Hebrew reader.
function BackArrow() {
  const { dir } = useI18n()
  return <span aria-hidden="true">{dir === 'rtl' ? '\u2192' : '\u2190'}</span>
}

// ── Page ──────────────────────────────────────────────────────────────────────

/**
 * Number of boxes in the reset-code input.
 *
 * This MUST match Supabase's "Email OTP Length" (Authentication → Sign In /
 * Providers → Email). The two are set in different places and nothing checks
 * they agree: with the dashboard on 8 and this on 6, the emailed code
 * physically could not be typed in and password reset was unusable — and
 * silently so, because the form simply never became submittable.
 *
 * If you change one, change the other.
 */
const OTP_LENGTH = 6

export default function LoginPage() {
  const { signIn, signInWithGoogle, sendPasswordResetOtp, verifyPasswordResetOtp, updatePassword } = useAuth()
  const router = useRouter()
  const { t } = useI18n()
  const L = t.login
  const AE = t.common.auth_errors

  // ── Login form state ───────────────────────────────────────────────────────
  const [email,         setEmail]         = useState('')
  const [password,      setPassword]      = useState('')
  const [showPassword,  setShowPassword]  = useState(false)

  // ── Forgot password state ──────────────────────────────────────────────────
  const [phase,         setPhase]         = useState<LoginPhase>('login')
  const [fpEmail,       setFpEmail]       = useState('')
  const [otp,           setOtp]           = useState<string[]>(() => Array(OTP_LENGTH).fill(''))
  const [newPw,         setNewPw]         = useState('')
  const [showNewPw,     setShowNewPw]     = useState(false)
  // One ref array rather than N useRef calls, so OTP_LENGTH can change without
  // breaking the rules of hooks.
  const otpRefs = useRef<(HTMLInputElement | null)[]>([])
  /**
   * Box to focus once the digit that was just typed (or pasted) has rendered.
   *
   * Focus cannot be moved inline in the change handler: that runs before React
   * commits, so the call lands on the pre-update DOM and the caret stays put.
   * The visible effect is that typing appears to do nothing after the first
   * digit — the next keystroke goes to a box that is already full and is
   * dropped by maxLength, silently. Moving focus in an effect runs it after
   * the commit, when the target box actually exists in its new state.
   */
  const advanceTo = useRef<number | null>(null)

  useEffect(() => {
    if (advanceTo.current === null) return
    otpRefs.current[advanceTo.current]?.focus()
    advanceTo.current = null
  })

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
      setError(authErrorMessage(err, AE, L.errors.sign_in_failed))
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
      setError(authErrorMessage(err, AE, L.errors.google_failed))
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
      setSuccessMsg(L.reset.code_sent.replace('{n}', String(OTP_LENGTH)).replace('{email}', fpEmail))
      setPhase('forgot-otp')
    } catch (err: unknown) {
      // Supabase won't create a new user — surface a clear message
      setError(authErrorKind(err) === 'no_account'
        ? L.errors.no_account
        : authErrorMessage(err, AE, L.errors.send_code_failed))
    } finally {
      setBusy(false)
    }
  }

  async function handleVerifyOtp(e: FormEvent) {
    e.preventDefault()
    const code = otp.join('')
    if (code.length < OTP_LENGTH) { setError(L.errors.enter_all_digits); return }
    setError(null)
    setBusy(true)
    try {
      await verifyPasswordResetOtp(fpEmail.trim(), code)
      setSuccessMsg(null)
      setPhase('forgot-new-pw')
    } catch (err: unknown) {
      setError(authErrorMessage(err, AE, L.errors.invalid_code))
    } finally {
      setBusy(false)
    }
  }

  async function handleSetNewPassword(e: FormEvent) {
    e.preventDefault()
    if (newPwStrength.level === 'weak' || newPwStrength.level === 'empty') {
      setError(L.errors.stronger_password)
      return
    }
    setError(null)
    setBusy(true)
    try {
      await updatePassword(newPw)
      router.replace('/')
    } catch (err: unknown) {
      setError(authErrorMessage(err, AE, L.errors.update_password_failed))
    } finally {
      setBusy(false)
    }
  }

  function handleOtpInput(idx: number, val: string) {
    const digit = val.replace(/\D/g, '').slice(-1)
    const next  = [...otp]
    next[idx]   = digit
    setOtp(next)
    if (digit && idx < OTP_LENGTH - 1) advanceTo.current = idx + 1
  }

  /**
   * Accept the whole code at once. Without this, the only way in is typing one
   * digit per box — paste drops everything but the first character, which is
   * the single worst part of this screen when the code is sitting in another
   * window ready to copy.
   */
  function handleOtpPaste(idx: number, e: React.ClipboardEvent<HTMLInputElement>) {
    const digits = e.clipboardData.getData('text').replace(/\D/g, '')
    if (!digits) return
    e.preventDefault()
    const next = [...otp]
    for (let i = 0; i < digits.length && idx + i < OTP_LENGTH; i++) next[idx + i] = digits[i]
    setOtp(next)
    advanceTo.current = Math.min(idx + digits.length, OTP_LENGTH - 1)
  }

  function handleOtpKeyDown(idx: number, e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Backspace' && !otp[idx] && idx > 0) {
      otpRefs.current[idx - 1]?.focus()
    }
  }

  function resetToLogin() {
    setPhase('login')
    setError(null)
    setSuccessMsg(null)
    setFpEmail('')
    setOtp(Array(OTP_LENGTH).fill(''))
    setNewPw('')
  }

  // ── Forgot password sub-views ─────────────────────────────────────────────

  function ForgotEmailView() {
    return (
      <form onSubmit={handleSendOtp} className="space-y-5">
        <div>
          <h1 className={kycTitle}>{L.reset.request_title}</h1>
          <p className={kycSub}>
            {L.reset.request_sub.replace('{n}', String(OTP_LENGTH))}
          </p>
        </div>
        <div>
          <label htmlFor="fpEmail" className={authLabel}>{L.card.email_label}</label>
          <input
            id="fpEmail"
            type="email"
            required
            disabled={busy}
            autoFocus
            value={fpEmail}
            onChange={e => { setError(null); setFpEmail(e.target.value) }}
            placeholder="you@example.com"
            className={authInput()}
          />
        </div>
        {error && <ErrorBanner msg={error} />}
        <button type="submit" disabled={busy || !fpEmail.includes('@')}
          className={kycPrimary}>
          {busy && <span className="w-4 h-4 rounded-full border-2 border-white/40 border-t-white animate-spin" />}
          {busy ? L.reset.sending : L.reset.send_code}
        </button>
        <button type="button" onClick={resetToLogin}
          className="w-full min-h-[44px] text-[14px] text-slate-500 hover:text-slate-900 transition-colors">
          <BackArrow /> {L.page.back_to_sign_in}
        </button>
      </form>
    )
  }

  function ForgotOtpView() {
    return (
      <form onSubmit={handleVerifyOtp} className="space-y-5">
        <div>
          <h1 className={kycTitle}>{L.reset.otp_title}</h1>
          {successMsg && (
            <p className="mt-3 text-[14px] text-teal-800 bg-teal-50 rounded-xl px-3.5 py-3">
              {successMsg}
            </p>
          )}
        </div>

        {/* OTP digit inputs */}
        <div className="flex gap-2 justify-center">
          {otp.map((digit, i) => (
            <input
              key={i}
              ref={el => { otpRefs.current[i] = el }}
              type="text"
              inputMode="numeric"
              maxLength={1}
              value={digit}
              onChange={e => handleOtpInput(i, e.target.value)}
              onKeyDown={e => handleOtpKeyDown(i, e)}
              onPaste={e => handleOtpPaste(i, e)}
              disabled={busy}
              className="w-12 h-14 rounded-xl border border-slate-200 bg-white text-center text-xl font-bold text-slate-900
                outline-none hover:border-slate-300 focus:border-teal-600 focus:ring-4 focus:ring-teal-600/10 transition-[border-color,box-shadow] duration-ja-ui disabled:opacity-50"
              autoFocus={i === 0}
              aria-label={L.reset.otp_digit_label.replace('{n}', String(i + 1))}
            />
          ))}
        </div>

        {error && <ErrorBanner msg={error} />}
        <button type="submit" disabled={busy || otp.join('').length < OTP_LENGTH}
          className={kycPrimary}>
          {busy && <span className="w-4 h-4 rounded-full border-2 border-white/40 border-t-white animate-spin" />}
          {busy ? L.reset.verifying : L.reset.verify_code}
        </button>
        <div className="flex items-center justify-between text-[14px] text-slate-500">
          <button type="button" onClick={resetToLogin} className="min-h-[44px] px-1 hover:text-slate-900 transition-colors">
            <BackArrow /> {L.page.back}
          </button>
          <button type="button" disabled={busy}
            onClick={() => { setError(null); void handleSendOtp({ preventDefault: () => {} } as FormEvent) }}
            className="text-teal-700 hover:text-teal-800 font-medium transition-colors disabled:opacity-50">
            {L.reset.resend_code}
          </button>
        </div>
      </form>
    )
  }

  function ForgotNewPwView() {
    return (
      <form onSubmit={handleSetNewPassword} className="space-y-5">
        <div>
          <h1 className={kycTitle}>{L.reset.new_pw_title}</h1>
          <p className={kycSub}>{L.reset.new_pw_sub}</p>
        </div>
        <div>
          <label htmlFor="newPw" className={authLabel}>{L.reset.new_pw_label}</label>
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
              placeholder={L.reset.new_pw_placeholder}
              className={`${authInput()} pe-11`}
            />
            <button type="button"
              onClick={() => setShowNewPw(v => !v)}
              className="absolute inset-y-0 end-0 flex items-center px-3.5 rounded-xl text-slate-400 hover:text-slate-600 transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-teal-600"
              aria-label={showNewPw ? L.card.hide_password : L.card.show_password}>
              {showNewPw ? <EyeClosedIcon /> : <EyeOpenIcon />}
            </button>
          </div>
          <PasswordMeter password={newPw} />
        </div>
        {error && <ErrorBanner msg={error} />}
        <button type="submit"
          disabled={busy || newPwStrength.level === 'weak' || newPwStrength.level === 'empty'}
          className={kycPrimary}>
          {busy && <span className="w-4 h-4 rounded-full border-2 border-white/40 border-t-white animate-spin" />}
          {busy ? L.reset.saving : L.reset.save_and_sign_in}
        </button>
      </form>
    )
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <KycShell
      aside={
        <SignInScene
          email={phase === 'login' ? email : ''}
          hasPassword={phase === 'login' && password !== ''}
          going={phase === 'login' && (busy || googleBusy)}
          failed={phase === 'login' && error !== null}
        />
      }
      back={{ href: '/', label: L.page.back, aria: L.page.back_to_home }}
    >
        <div key={phase} className="w-full animate-ja-tab-in motion-reduce:animate-none">

          {/* Sub-views for forgot password */}
          {phase === 'forgot-email'  && <ForgotEmailView  />}
          {phase === 'forgot-otp'    && <ForgotOtpView    />}
          {phase === 'forgot-new-pw' && <ForgotNewPwView  />}

          {/* Normal login */}
          {phase === 'login' && (
            <>
              <div className="mb-8">
                <h1 className={kycTitle}>{L.page.sign_in_title}</h1>
                <p className={kycSub}>{L.page.sign_in_sub}</p>
              </div>

              <div className="space-y-5">
                {/* Google */}
                <button type="button" onClick={handleGoogle}
                  disabled={busy || googleBusy}
                  className={authSecondary}>
                  {googleBusy
                    ? <span className="w-[18px] h-[18px] rounded-full border-2 border-slate-300 border-t-slate-600 animate-spin flex-shrink-0" />
                    : <GoogleLogo />}
                  {googleBusy ? L.card.redirecting : L.card.continue_google}
                </button>

                {/* Divider */}
                <div className="flex items-center gap-3 text-[13px] text-slate-600">
                  <span className="h-px flex-1 bg-slate-900/10" />
                  {L.page.or_sign_in_email}
                  <span className="h-px flex-1 bg-slate-900/10" />
                </div>

                {/* Form */}
                <form onSubmit={handleLogin} className="space-y-4">
                  <div>
                    <label htmlFor="email" className={authLabel}>{L.card.email_label}</label>
                    <input id="email" type="email" autoComplete="username" required
                      disabled={busy} value={email}
                      onChange={e => { setError(null); setEmail(e.target.value) }}
                      className={authInput()} />
                  </div>

                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <label htmlFor="password" className="block text-[14px] font-medium text-slate-700">
                        {L.card.password_label}
                      </label>
                      <button type="button"
                        onClick={() => { setFpEmail(email); setPhase('forgot-email'); setError(null) }}
                        className="min-h-[44px] sm:min-h-0 px-1 text-[13px] text-teal-700 hover:text-teal-800 font-medium transition-colors">
                        {L.page.forgot_password}
                      </button>
                    </div>
                    <div className="relative">
                      <input id="password" type={showPassword ? 'text' : 'password'}
                        autoComplete="current-password" required disabled={busy}
                        value={password}
                        onChange={e => { setError(null); setPassword(e.target.value) }}
                        className={`${authInput()} pe-11`} />
                      <button type="button"
                        onClick={() => setShowPassword(v => !v)}
                        className="absolute inset-y-0 end-0 flex items-center px-3.5 rounded-xl text-slate-400 hover:text-slate-600 transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-teal-600"
                        aria-label={showPassword ? L.card.hide_password : L.card.show_password}>
                        {showPassword ? <EyeClosedIcon /> : <EyeOpenIcon />}
                      </button>
                    </div>
                  </div>

                  {error && <ErrorBanner msg={error} />}

                  <button type="submit" disabled={busy}
                    className={kycPrimary}>
                    {busy && <span className="w-4 h-4 rounded-full border-2 border-white/40 border-t-white animate-spin" />}
                    {busy ? L.card.signing_in : L.card.sign_in_btn}
                  </button>
                </form>

                {/* The landing page sends everyone here first, so the way to
                    a new account has to be as easy to see as the form. */}
                <div className="grid gap-3 pt-5 border-t border-slate-100">
                  <p className="text-center text-[14px] text-slate-600">{L.card.no_account}</p>
                  <Link href="/signup"
                    className={`${authSecondary} !text-teal-800`}>
                    {L.card.sign_up_link}
                  </Link>
                </div>
              </div>
            </>
          )}
        </div>
    </KycShell>
  )
}
