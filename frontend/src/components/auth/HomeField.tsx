'use client'

import { useI18n } from '@/contexts/I18nContext'
import { CityPicker, type HomeCity } from './CityPicker'
import { authInput, authLabel, kycOption } from './authStyles'

export type HomeWhere = 'israel' | 'abroad'
const WHERE: readonly HomeWhere[] = ['israel', 'abroad']

/** Where the user lives, for signup step 2 and the required-details step at login. */
export function HomeField({ cities, where, onWhere, city, onCity, abroad, onAbroad, error, disabled }: {
  cities:   HomeCity[]
  where:    HomeWhere
  onWhere:  (w: HomeWhere) => void
  city:     string | null
  onCity:   (c: string | null) => void
  abroad:   string
  onAbroad: (a: string) => void
  error?:   string
  disabled: boolean
}) {
  const A = useI18n().t.onboarding.about
  return (
    <>
      <div role="radiogroup" aria-label={A.home_label} className="grid grid-cols-2 gap-2.5">
        {WHERE.map(w => (
          <button key={w} type="button" role="radio" aria-checked={where === w} disabled={disabled}
            onClick={() => onWhere(w)} className={kycOption(where === w)}>
            {A.home_where[w]}
          </button>
        ))}
      </div>
      <div key={where} className="mt-4 animate-ja-tab-in motion-reduce:animate-none">
        {where === 'israel' ? (
          <>
            <CityPicker id="home-city" cities={cities} value={city} onChange={onCity} disabled={disabled} />
            <p className="mt-2 text-[13px] text-slate-600">{A.credit}</p>
          </>
        ) : (
          <>
            <label htmlFor="home-abroad" className={authLabel}>{A.home_abroad_label}</label>
            <input id="home-abroad" value={abroad} maxLength={80} disabled={disabled}
              placeholder={A.home_abroad_placeholder}
              onChange={e => onAbroad(e.target.value)} className={authInput()} />
          </>
        )}
        {error && <p className="text-[14px] text-rose-600 mt-2" role="alert">{error}</p>}
      </div>
    </>
  )
}
