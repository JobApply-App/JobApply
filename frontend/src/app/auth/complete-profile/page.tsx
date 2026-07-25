'use client'

import { useState, type FormEvent }  from 'react'
import { isValidPhoneNumber }        from 'react-phone-number-input'
import dynamic                       from 'next/dynamic'
import { useRouter }                 from 'next/navigation'
import AuthGuard                     from '@/components/AuthGuard'
import { CareerStageCards, type CareerStage } from '@/components/auth/CareerStageCards'
import { useAuth }                   from '@/contexts/AuthContext'
import { useOnboarding }             from '@/contexts/OnboardingContext'
import { getAuthHeaders }            from '@/lib/api'
import { TOKENS }                    from '@/lib/tokens'

const PhoneInput = dynamic(
  () => import('@/components/auth/PhoneInput').then(m => ({ default: m.PhoneInput })),
  { ssr: false, loading: () => <div className="h-[42px] rounded-lg border border-slate-200 bg-slate-50 animate-pulse" /> }
)

const LOG = '[JobApply-Debug][complete-profile]'

// ── Workspace overlay ─────────────────────────────────────────────────────────

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

// ── Inner content ─────────────────────────────────────────────────────────────

function CompleteProfileContent() {
  const { user, updateUserMeta } = useAuth()
  const { set: setOnboarding }   = useOnboarding()
  const router = useRouter()

  const meta      = user?.user_metadata as Record<string, unknown> | null
  const fullName  = String(meta?.full_name ?? meta?.name ?? '')
  const firstName = fullName.split(' ')[0]
  const picture   = typeof meta?.picture === 'string' ? meta.picture : null

  const [phone,       setPhone]       = useState('+972')
  const [careerStage, setCareerStage] = useState<CareerStage | ''>('')
  const [busy,        setBusy]        = useState(false)
  const [creating,    setCreating]    = useState(false)
  const [error,       setError]       = useState<string | null>(null)

  // E164 value from PhoneInput — validate with isValidPhoneNumber, no manual regex
  const phoneOk = phone.length > 3 && isValidPhoneNumber(phone)
  const canSubmit = phoneOk && careerStage !== ''

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!canSubmit || busy) return
    console.log(`${LOG} submit — careerStage: ${careerStage}`)
    setError(null)
    setBusy(true)
    try {
      await updateUserMeta({ career_stage: careerStage, phone })
      console.log(`${LOG} updateUserMeta success`)
      setOnboarding({ fullName, careerStage })

      void fetch('/api/profile/init', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
      }).catch(err => console.warn(`${LOG} profile/init failed:`, err))

      setCreating(true)
      await new Promise(r => setTimeout(r, 1500))
      router.replace('/discover')
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Something went wrong.'
      console.error(`${LOG} error:`, msg)
      setError(msg)
      setBusy(false)
    }
  }

  if (creating) return <WorkspaceAnimation name={firstName} />

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-slate-50 px-6 py-12">
      <div className="w-full max-w-md">

        {/* Avatar + welcome */}
        <div className="flex flex-col items-center gap-3 mb-8 text-center">
          {picture ? (
            <img src={picture} alt={fullName} className="w-16 h-16 rounded-full border-2 border-white shadow-md" />
          ) : (
            <div className="w-16 h-16 rounded-full flex items-center justify-center text-white text-xl font-bold"
              style={{ background: TOKENS.color.primary }}>
              {firstName.charAt(0).toUpperCase()}
            </div>
          )}
          <div>
            <h1 className="text-xl font-bold text-slate-900">
              Welcome, {firstName || 'there'}!
            </h1>
            <p className="text-sm text-slate-500 mt-0.5">
              One last step — complete your profile details.
            </p>
          </div>
        </div>

        <div className="bg-white rounded-2xl border border-slate-100 p-8"
          style={{ boxShadow: '0 2px 8px rgba(0,0,0,0.02),0 20px 40px rgba(0,0,0,0.04)' }}>

          <form onSubmit={handleSubmit} className="space-y-6">

            {/* Phone */}
            <div>
              <label htmlFor="phone" className="block text-xs font-medium text-slate-700 mb-1.5">
                Phone <span className="text-rose-400">*</span>
              </label>
              <PhoneInput
                id="phone"
                value={phone}
                onChange={setPhone}
                disabled={busy}
              />
            </div>

            {/* Career Stage */}
            <div>
              <p className="text-xs font-medium text-slate-700 mb-2.5">
                Career Stage <span className="text-rose-400">*</span>
              </p>
              <CareerStageCards
                value={careerStage}
                onChange={setCareerStage}
                disabled={busy}
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

            {/* Error */}
            {error && (
              <div className="flex items-start gap-2 rounded-lg px-3 py-2.5 text-xs bg-ja-dangerSubtle text-ja-danger"
                role="alert">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                  strokeWidth="2" strokeLinecap="round" className="flex-shrink-0 mt-0.5" aria-hidden="true">
                  <circle cx="12" cy="12" r="10" />
                  <line x1="12" y1="8" x2="12" y2="12" />
                  <line x1="12" y1="16" x2="12.01" y2="16" />
                </svg>
                <span>{error}</span>
              </div>
            )}

            <button type="submit" disabled={busy || !canSubmit}
              className="w-full rounded-lg py-2.5 text-sm font-semibold text-white flex items-center justify-center gap-2 transition-opacity disabled:opacity-40 disabled:cursor-not-allowed"
              style={{ background: TOKENS.color.primary }}>
              {busy && <span className="w-4 h-4 rounded-full border-2 border-white/40 border-t-white animate-spin flex-shrink-0" />}
              {busy ? 'Setting up…' : 'Complete Setup'}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}

// ── Page (guarded) ────────────────────────────────────────────────────────────

export default function CompleteProfilePage() {
  return (
    <AuthGuard>
      <CompleteProfileContent />
    </AuthGuard>
  )
}
