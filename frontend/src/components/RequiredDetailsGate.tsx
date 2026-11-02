'use client'

import { useEffect, useState } from 'react'
import { useI18n } from '@/contexts/I18nContext'
import { HebrewFormPicker } from '@/components/HebrewFormPicker'
import { RolePicker, type PendingRole } from '@/components/RolePicker'
import { useLocalities } from '@/components/auth/CityPicker'
import { HomeField, type HomeWhere } from '@/components/auth/HomeField'
import {
  fetchMissingRequiredDetails, fetchRolePreferences, saveHebrewForm, saveHome, saveRolePreferences,
  type HebrewForm, type RequiredDetail, type SeniorityLevel,
} from '@/lib/api'
import { TOKENS } from '@/lib/tokens'

/**
 * Asks, once, for the details the product cannot work well without: target
 * roles with a level in each, how Hebrew text should refer to the user, and
 * where they live.
 * New users give these during onboarding; this catches everyone who skipped
 * them or signed up before they were asked. It blocks the app until saved,
 * and shows only the questions that are actually missing.
 */
export function RequiredDetailsGate() {
  const { t } = useI18n()
  const R = t.required_details
  const A = t.onboarding.about
  const [missing, setMissing] = useState<RequiredDetail[]>([])
  const needHome = missing.includes('home')
  const cities = useLocalities(needHome)
  const [where, setWhere] = useState<HomeWhere>('israel')
  const [city, setCity] = useState<string | null>(null)
  const [abroad, setAbroad] = useState('')
  const [roles, setRoles] = useState<PendingRole[]>([])
  const [form, setForm] = useState<HebrewForm | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    fetchMissingRequiredDetails()
      .then(async m => {
        if (!alive || !m.length) return
        if (m.includes('roles')) {
          // Start from what the user already saved, so they only add the levels.
          const saved = await fetchRolePreferences().catch(() => ({ roles: [] }))
          if (alive) setRoles(saved.roles.map(r => ({
            role: r.role, seniority: (r.seniority || null) as SeniorityLevel | null,
          })))
        }
        if (alive) setMissing(m)
      })
      .catch(() => { /* never block the app on a failed check */ })
    return () => { alive = false }
  }, [])

  if (!missing.length) return null

  const needRoles = missing.includes('roles')
  const needForm = missing.includes('hebrew_form')
  const rolesOk = !needRoles || (roles.length > 0 && roles.every(r => r.seniority))
  const formOk = !needForm || form !== null
  // A list that failed to load must not lock anyone out of the app.
  const homeOk = !needHome || (where === 'abroad' ? abroad.trim() !== '' : Boolean(city) || cities.length === 0)
  const canSave = rolesOk && formOk && homeOk && !saving

  const save = async () => {
    setSaving(true)
    setError('')
    try {
      if (needRoles) {
        await saveRolePreferences({ roles: roles.map(r => ({ role: r.role, seniority: r.seniority ?? '' })) })
      }
      if (needForm && form) await saveHebrewForm(form)
      if (needHome && where === 'abroad') await saveHome({ home_city: null, home_abroad: abroad.trim() })
      if (needHome && where === 'israel' && city) await saveHome({ home_city: city, home_abroad: null })
      setMissing([])
    } catch {
      setError(R.save_failed)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[900] flex items-end sm:items-center justify-center bg-slate-900/50 px-0 sm:px-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="required-details-title"
        className="w-full sm:max-w-lg max-h-[92vh] overflow-y-auto bg-white rounded-t-2xl sm:rounded-2xl p-6 sm:p-8"
        style={{ boxShadow: '0 2px 8px rgba(0,0,0,0.04),0 24px 48px rgba(0,0,0,0.12)' }}
      >
        <h2 id="required-details-title" className="text-[19px] font-bold text-slate-900">{R.title}</h2>
        <p className="text-[13.5px] text-slate-500 mt-1 mb-6 leading-relaxed">{R.intro}</p>

        {needRoles && (
          <section className="mb-7">
            <h3 className="text-[14px] font-semibold text-slate-800">{R.roles_heading}</h3>
            <p className="text-[12px] text-slate-500 mb-3">{R.roles_hint}</p>
            <RolePicker selected={roles} setSelected={setRoles} />
          </section>
        )}

        {needForm && (
          <section className="mb-7">
            <h3 className="text-[14px] font-semibold text-slate-800">{R.hebrew_heading}</h3>
            <p className="text-[12px] text-slate-500 mb-3 leading-relaxed">{R.hebrew_hint}</p>
            <HebrewFormPicker value={form} onChange={setForm} disabled={saving} />
          </section>
        )}

        {needHome && (
          <section className="mb-7">
            <h3 className="text-[14px] font-semibold text-slate-800">{A.home_label}</h3>
            <p className="text-[12px] text-slate-500 mb-3 leading-relaxed">{A.home_hint}</p>
            <HomeField
              cities={cities}
              where={where} onWhere={setWhere}
              city={city} onCity={setCity}
              abroad={abroad} onAbroad={setAbroad}
              disabled={saving}
            />
          </section>
        )}

        {error && <p className="text-[12.5px] text-red-600 mb-3" role="alert">{error}</p>}

        <button
          type="button"
          onClick={save}
          disabled={!canSave}
          className="w-full h-11 rounded-lg text-[14px] font-semibold text-white transition disabled:opacity-40"
          style={{ background: TOKENS.color.primary }}
        >
          {saving ? R.saving : R.save}
        </button>
      </div>
    </div>
  )
}
