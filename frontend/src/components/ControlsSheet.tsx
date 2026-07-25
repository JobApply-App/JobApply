'use client'

import { useState, useEffect, useCallback } from 'react'
import { TOKENS } from '@/lib/tokens'
import {
  DEFAULT_SETTINGS,
  type AutomationSettings,
  type WorkMode,
  type Region,
  type CompanyStage,
  type Cadence,
  type RadiusKm,
} from '@/lib/data'
import { IconBtn } from './ui/IconBtn'
import { XIcon, CheckIcon } from './icons'

// ── Section header ────────────────────────────────────────────────────────────

function SectionHeader({
  title,
  badge,
}: {
  title: string
  badge?: string
}) {
  return (
    <div className="flex items-center gap-2 mb-4">
      <span className="text-[11px] font-bold text-slate-500 uppercase tracking-widest">{title}</span>
      {badge && (
        <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700 border border-amber-200">
          {badge}
        </span>
      )}
    </div>
  )
}

// ── Multi-select pill group ───────────────────────────────────────────────────

function PillGroup<T extends string>({
  options,
  selected,
  onChange,
}: {
  options:  { value: T; label: string; icon?: string }[]
  selected: T[]
  onChange: (next: T[]) => void
}) {
  const toggle = (v: T) =>
    onChange(selected.includes(v) ? selected.filter(x => x !== v) : [...selected, v])

  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map(opt => {
        const active = selected.includes(opt.value)
        return (
          <button
            key={opt.value}
            type="button"
            onClick={() => toggle(opt.value)}
            className={`inline-flex items-center gap-1 h-7 px-3 rounded-full text-[12px] font-medium border transition-all duration-150 ${
              active
                ? 'text-white border-transparent'
                : 'border-slate-200 text-slate-600 bg-white hover:border-slate-300 hover:bg-slate-50'
            }`}
            style={active ? { background: TOKENS.color.primary, borderColor: TOKENS.color.primary } : undefined}
          >
            {opt.icon && <span>{opt.icon}</span>}
            {opt.label}
            {active && <CheckIcon s={10} />}
          </button>
        )
      })}
    </div>
  )
}

// ── Notification cadence cards ────────────────────────────────────────────────

const CADENCE_OPTIONS: { value: Cadence; icon: string; label: string; sub: string }[] = [
  {
    value: 'immediate',
    icon:  '⚡',
    label: 'Immediate',
    sub:   'Alert when match > 90%',
  },
  {
    value: 'daily',
    icon:  '📋',
    label: 'Daily Digest',
    sub:   'Morning summary of new matches',
  },
  {
    value: 'weekly',
    icon:  '📅',
    label: 'Weekly Summary',
    sub:   'Sunday overview of the week',
  },
  {
    value: 'off',
    icon:  '🔕',
    label: 'Off',
    sub:   'No automated alerts',
  },
]

function CadenceCard({
  option,
  active,
  onClick,
}: {
  option:  typeof CADENCE_OPTIONS[number]
  active:  boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex items-center gap-3 w-full px-3 py-2.5 rounded-xl border text-left transition-all duration-150 ${
        active
          ? 'border-teal-300 bg-teal-50/60'
          : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50'
      }`}
    >
      <span className="text-base leading-none shrink-0">{option.icon}</span>
      <div className="flex-1 min-w-0">
        <p className={`text-[12.5px] font-semibold ${active ? 'text-teal-800' : 'text-slate-800'}`}>
          {option.label}
        </p>
        <p className="text-[11px] text-slate-500 truncate">{option.sub}</p>
      </div>
      <div className={`shrink-0 w-4 h-4 rounded-full border-2 flex items-center justify-center transition-colors ${
        active ? 'border-teal-500 bg-teal-500' : 'border-slate-300 bg-white'
      }`}>
        {active && <span className="w-1.5 h-1.5 rounded-full bg-white" />}
      </div>
    </button>
  )
}

// ── Slider with value badge ───────────────────────────────────────────────────

function SliderRow({
  label,
  min,
  max,
  step,
  value,
  onChange,
  format,
  sub,
}: {
  label:    string
  min:      number
  max:      number
  step:     number
  value:    number
  onChange: (v: number) => void
  format?:  (v: number) => string
  sub?:     string
}) {
  const display = format ? format(value) : String(value)
  const pct = Math.round(((value - min) / (max - min)) * 100)

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <span className="text-[13px] font-medium text-slate-800">{label}</span>
        <span
          className="text-[12px] font-bold px-2 py-0.5 rounded-full text-white tabular-nums"
          style={{ background: TOKENS.color.primary }}
        >
          {display}
        </span>
      </div>
      <div className="relative h-2 rounded-full bg-slate-100 mb-1">
        <div
          className="absolute left-0 top-0 h-full rounded-full transition-[width] duration-100"
          style={{ width: `${pct}%`, background: TOKENS.color.primary }}
        />
        <input
          type="range"
          min={min} max={max} step={step} value={value}
          onChange={e => onChange(Number(e.target.value))}
          className="absolute inset-0 w-full opacity-0 cursor-pointer"
          style={{ height: '100%' }}
        />
        <div
          className="absolute top-1/2 -translate-y-1/2 w-4 h-4 rounded-full bg-white border-2 shadow-sm pointer-events-none"
          style={{ left: `calc(${pct}% - 8px)`, borderColor: TOKENS.color.primary }}
        />
      </div>
      {sub && <p className="text-[11.5px] text-slate-400 mt-1.5">{sub}</p>}
    </div>
  )
}

// ── Props & main component ────────────────────────────────────────────────────

interface Props {
  open:        boolean
  onClose:     () => void
  settings:    AutomationSettings
  setSettings: (s: AutomationSettings) => void
}

const WORK_MODE_OPTIONS: { value: WorkMode; label: string; icon: string }[] = [
  { value: 'hybrid', label: 'Hybrid',  icon: '🏢' },
  { value: 'remote', label: 'Remote',  icon: '🌐' },
  { value: 'onsite', label: 'Office',  icon: '📍' },
]

const REGION_OPTIONS: { value: Region; label: string }[] = [
  { value: 'tel-aviv',   label: 'Tel Aviv'   },
  { value: 'central',    label: 'Central'    },
  { value: 'sharon',     label: 'Sharon'     },
  { value: 'haifa',      label: 'Haifa'      },
  { value: 'jerusalem',  label: 'Jerusalem'  },
  { value: 'south',      label: 'South'      },
]

const RADIUS_OPTIONS: { value: RadiusKm; label: string }[] = [
  { value: 10, label: '10 km'     },
  { value: 20, label: '20 km'     },
  { value: 40, label: '40 km'     },
  { value: 0,  label: 'Unlimited' },
]

const COMPANY_STAGE_OPTIONS: { value: CompanyStage; label: string; icon: string }[] = [
  { value: 'startup',    label: 'Startup',    icon: '🚀' },
  { value: 'growth',     label: 'Growth',     icon: '📈' },
  { value: 'enterprise', label: 'Enterprise', icon: '🏛' },
]

const ACTIVE_FILTERS_THAT_COUNT = (s: AutomationSettings) =>
  (s.minScore > 0 ? 1 : 0)
  + (s.workModes.length > 0 ? 1 : 0)
  + (s.regions.length > 0 ? 1 : 0)
  + (s.companyStages.length > 0 ? 1 : 0)

export function ControlsSheet({ open, onClose, settings, setSettings }: Props) {
  // Local draft — only committed on Save
  const [draft, setDraft] = useState<AutomationSettings>(settings)
  const [saved, setSaved] = useState(false)

  // Sync draft when sheet opens
  useEffect(() => {
    if (open) {
      setDraft(settings)
      setSaved(false)
    }
  }, [open, settings])

  const patch = useCallback(<K extends keyof AutomationSettings>(
    key: K,
    value: AutomationSettings[K],
  ) => setDraft(prev => ({ ...prev, [key]: value })), [])

  const handleSave = useCallback(() => {
    setSettings(draft)
    setSaved(true)
    setTimeout(() => { setSaved(false); onClose() }, 900)
  }, [draft, setSettings, onClose])

  const handleReset = useCallback(() => {
    setDraft(DEFAULT_SETTINGS)
  }, [])

  const activeCount = ACTIVE_FILTERS_THAT_COUNT(draft)
  const hasChanges  = JSON.stringify(draft) !== JSON.stringify(settings)

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50" onClick={onClose}>
      {/* Backdrop — Meridian V2 §3.2 scrim */}
      <div className="absolute inset-0 bg-slate-900/55 backdrop-blur-[4px]" />

      <aside
        onClick={e => e.stopPropagation()}
        className="absolute right-0 top-0 bottom-0 w-full max-w-[440px] bg-white border-l border-slate-200 shadow-floating flex flex-col"
      >
        {/* ── Header ── */}
        <div className="flex items-center justify-between px-6 h-14 border-b border-slate-100 shrink-0">
          <div className="flex items-center gap-2.5">
            <span className="text-[15px] font-semibold text-slate-900">Match &amp; Notification Preferences</span>
            {activeCount > 0 && (
              <span
                className="text-[10px] font-bold px-1.5 py-0.5 rounded-full text-white"
                style={{ background: TOKENS.color.primary }}
              >
                {activeCount} active
              </span>
            )}
          </div>
          <IconBtn onClick={onClose} title="Close"><XIcon s={14} /></IconBtn>
        </div>

        {/* ── Scrollable body ── */}
        <div className="flex-1 overflow-y-auto">
          <div className="p-6 space-y-8">

            {/* ════ MATCH FILTERS ═════════════════════════════════════════ */}
            <section>
              <SectionHeader title="Match Filters" badge="Matches page only" />

              <div className="space-y-6">

                {/* Min score */}
                <SliderRow
                  label="Minimum match score"
                  min={0} max={100} step={5}
                  value={draft.minScore}
                  onChange={v => patch('minScore', v)}
                  format={v => v === 0 ? 'Off' : `${v}%+`}
                  sub={draft.minScore === 0
                    ? 'Showing all scores — drag right to set a floor'
                    : `Hiding jobs below ${draft.minScore}% match`}
                />

                {/* Work mode */}
                <div>
                  <p className="text-[13px] font-medium text-slate-800 mb-2">Work mode</p>
                  <PillGroup
                    options={WORK_MODE_OPTIONS}
                    selected={draft.workModes}
                    onChange={v => patch('workModes', v as WorkMode[])}
                  />
                  {draft.workModes.length === 0 && (
                    <p className="text-[11.5px] text-slate-400 mt-1.5">All modes shown</p>
                  )}
                </div>

                {/* Location */}
                <div>
                  <p className="text-[13px] font-medium text-slate-800 mb-2.5">Location</p>

                  {/* Region grid */}
                  <div className="grid grid-cols-3 gap-1.5 mb-3">
                    {REGION_OPTIONS.map(r => {
                      const on = draft.regions.includes(r.value)
                      return (
                        <button
                          key={r.value}
                          type="button"
                          onClick={() =>
                            patch('regions',
                              on
                                ? draft.regions.filter(x => x !== r.value)
                                : [...draft.regions, r.value],
                            )
                          }
                          className={`h-8 rounded-lg border text-[12px] font-medium transition-all duration-150 ${
                            on
                              ? 'text-white border-transparent'
                              : 'border-slate-200 text-slate-600 bg-white hover:border-slate-300'
                          }`}
                          style={on ? { background: TOKENS.color.primary } : undefined}
                        >
                          {r.label}
                        </button>
                      )
                    })}
                  </div>

                  {/* Radius */}
                  <div className="flex items-center gap-2">
                    <span className="text-[12px] text-slate-500 shrink-0">Radius:</span>
                    <div className="flex gap-1.5">
                      {RADIUS_OPTIONS.map(opt => {
                        const active = draft.radiusKm === opt.value
                        return (
                          <button
                            key={opt.value}
                            type="button"
                            disabled={draft.regions.length === 0}
                            onClick={() => patch('radiusKm', opt.value)}
                            className={`h-7 px-2.5 rounded-full text-[11.5px] font-medium border transition-all duration-150 disabled:opacity-40 disabled:pointer-events-none ${
                              active
                                ? 'text-white border-transparent'
                                : 'border-slate-200 text-slate-600 bg-white hover:border-slate-300'
                            }`}
                            style={active ? { background: TOKENS.color.primary } : undefined}
                          >
                            {opt.label}
                          </button>
                        )
                      })}
                    </div>
                  </div>
                  {draft.regions.length === 0 && (
                    <p className="text-[11.5px] text-slate-400 mt-1.5">All regions shown — select regions to enable radius</p>
                  )}
                </div>

                {/* Company stage */}
                <div>
                  <p className="text-[13px] font-medium text-slate-800 mb-2">Company stage</p>
                  <PillGroup
                    options={COMPANY_STAGE_OPTIONS}
                    selected={draft.companyStages}
                    onChange={v => patch('companyStages', v as CompanyStage[])}
                  />
                  {draft.companyStages.length === 0 && (
                    <p className="text-[11.5px] text-slate-400 mt-1.5">All company stages shown</p>
                  )}
                </div>

              </div>
            </section>

            <div className="border-t border-slate-100" />

            {/* ════ NOTIFICATIONS ════════════════════════════════════════ */}
            <section>
              <SectionHeader title="Alert Notifications" />
              <div className="space-y-2">
                {CADENCE_OPTIONS.map(opt => (
                  <CadenceCard
                    key={opt.value}
                    option={opt}
                    active={draft.cadence === opt.value}
                    onClick={() => patch('cadence', opt.value)}
                  />
                ))}
              </div>
            </section>

          </div>
        </div>

        {/* ── Sticky footer ── */}
        <div className="shrink-0 border-t border-slate-100 bg-white px-6 py-4 flex items-center gap-3">
          <button
            type="button"
            onClick={handleReset}
            className="text-[12.5px] text-slate-500 hover:text-slate-800 transition underline underline-offset-2"
          >
            Reset to defaults
          </button>

          <div className="flex-1" />

          <button
            type="button"
            onClick={handleSave}
            disabled={saved}
            className="inline-flex items-center gap-2 h-9 px-5 rounded-full text-[13px] font-semibold text-white transition-all duration-200 disabled:opacity-80"
            style={{ background: saved ? TOKENS.color.success : TOKENS.color.primary }}
          >
            {saved ? (
              <><CheckIcon s={13} /> Saved!</>
            ) : (
              <>
                Save Changes
                {hasChanges && (
                  <span className="w-1.5 h-1.5 rounded-full bg-white/70" />
                )}
              </>
            )}
          </button>
        </div>
      </aside>
    </div>
  )
}
