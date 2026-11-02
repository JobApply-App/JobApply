'use client'

import { useState, type FormEvent } from 'react'
import dynamic from 'next/dynamic'
import { useRouter } from 'next/navigation'
import { isValidPhoneNumber } from 'react-phone-number-input'
import { useAuth } from '@/contexts/AuthContext'
import { useOnboarding } from '@/contexts/OnboardingContext'
import { useI18n } from '@/contexts/I18nContext'
import { authInput, authLabel, kycPrimary, kycSub, kycTitle } from './authStyles'

const PhoneInput = dynamic(
  () => import('./PhoneInput').then(m => ({ default: m.PhoneInput })),
  { ssr: false, loading: () => <div className="h-12 rounded-xl border border-slate-200 bg-slate-50" /> },
)

/**
 * Where Back from step 2 lands. The account already exists by then, so this is
 * step 1 for editing: name and phone change, and no password is asked for.
 */
export function AccountStep({ onName }: { onName: (name: string) => void }) {
  const { t } = useI18n()
  const S = t.signup.page
  const A = t.onboarding.account
  const { user, updateUserMeta } = useAuth()
  const { set: setOnboarding } = useOnboarding()
  const router = useRouter()

  const meta = user?.user_metadata as Record<string, unknown> | null
  const [first, ...rest] = String(meta?.full_name ?? meta?.name ?? '').trim().split(/\s+/)
  const [firstName, setFirstName] = useState(first ?? '')
  const [lastName,  setLastName]  = useState(rest.join(' '))
  const [phone,     setPhone]     = useState(typeof meta?.phone === 'string' && meta.phone ? meta.phone : '+972')
  const [busy,      setBusy]      = useState(false)
  const [error,     setError]     = useState('')

  const canSave = firstName.trim() !== '' && lastName.trim() !== '' && isValidPhoneNumber(phone) && !busy

  async function save(e: FormEvent) {
    e.preventDefault()
    if (!canSave) return
    setBusy(true)
    setError('')
    const fullName = `${firstName.trim()} ${lastName.trim()}`
    try {
      await updateUserMeta({ full_name: fullName, name: fullName, phone })
      setOnboarding({ fullName, careerStage: typeof meta?.career_stage === 'string' ? meta.career_stage : '' })
      router.push('/onboarding?step=preferences')
    } catch {
      setError(A.save_failed)
      setBusy(false)
    }
  }

  return (
    <div className="w-full">
      <h1 className={kycTitle}>{A.title}</h1>
      <p className={kycSub}>{A.subtitle}</p>
      <form onSubmit={save} noValidate className="mt-8 space-y-5">
        <div className="grid grid-cols-2 gap-3">
          <div className="min-w-0">
            <label htmlFor="firstName" className={authLabel}>{S.first_name}</label>
            <input id="firstName" autoComplete="given-name" value={firstName} disabled={busy}
              onChange={e => { setFirstName(e.target.value); onName(`${e.target.value} ${lastName}`) }} className={authInput()} />
          </div>
          <div className="min-w-0">
            <label htmlFor="lastName" className={authLabel}>{S.last_name}</label>
            <input id="lastName" autoComplete="family-name" value={lastName} disabled={busy}
              onChange={e => { setLastName(e.target.value); onName(`${firstName} ${e.target.value}`) }} className={authInput()} />
          </div>
        </div>
        <div>
          <label htmlFor="phone" className={authLabel}>{S.phone}</label>
          <PhoneInput id="phone" value={phone} onChange={setPhone} disabled={busy} hasError={false} />
        </div>
        <div>
          <label htmlFor="email" className={authLabel}>{S.email}</label>
          <input id="email" dir="ltr" value={user?.email ?? ''} disabled aria-describedby="email-note"
            className={`${authInput()} bg-slate-50 text-start`} />
          <p id="email-note" className="mt-2 text-[14px] text-slate-500">{A.email_note}</p>
        </div>
        {error && <p className="text-[14px] text-rose-600" role="alert">{error}</p>}
        <button type="submit" disabled={!canSave} className={kycPrimary}>{A.cta}</button>
      </form>
    </div>
  )
}
