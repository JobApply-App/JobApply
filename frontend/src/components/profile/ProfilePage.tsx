'use client'

// The Profile page (docs/redesign-plan-2026-11.md §6, mockup approved by Ron
// 2026-11-27). Everything the user sees here is what Ariel knows about them,
// and every change goes through Ariel: there are no edit forms on this page.
//
// Motion follows the Apple design skill: the side panel is a parallel,
// non-blocking surface (no scrim) that enters and leaves from the inline end
// on the same path. On wide screens it pushes the column aside; narrower, it
// floats over it; on a phone it rises as a sheet. Presses answer on
// pointer-down; reduced motion swaps slides for a plain cross-fade.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { useI18n } from '@/contexts/I18nContext'
import { useChat } from '@/contexts/ChatContext'
import { useAuth } from '@/contexts/AuthContext'
import { Button, buttonClasses } from '@/components/ui/Button'
import { SparkIcon, XIcon, CheckIcon, ChevIcon, PinIcon, MailIcon } from '@/components/icons'
import { fetchProfileView, fetchRolePreferences, fetchAbout, fetchTrustScore, type AboutAnswers, type RoleSeniorityItem } from '@/lib/api'
import type { TrustProfileEntity } from '@/lib/apiTypes'
import { resolveDisplayName } from '@/lib/nameUtils'
import { CompanyLogo } from '@/components/ui/CompanyLogo'
import {
  capabilityDomains, companyEntries, latestRole, knowledgeTopics, militaryService, periodYears, roleFamilies, round1,
  type CapabilityDomain, type Check, type ProfileView, type Topic, type TopicId,
} from '@/lib/profileView'

type Panel = { type: 'skill'; entity: TrustProfileEntity; domain: string } | { type: 'topic'; id: TopicId } | null

interface Data {
  view:     ProfileView
  roles:    RoleSeniorityItem[]
  about:    AboutAnswers | null
  entities: TrustProfileEntity[]
}

const fmt = (n: number) => round1(n).toFixed(1)
const fill = (s: string, v: Record<string, string | number>) =>
  Object.entries(v).reduce((out, [k, x]) => out.split(`{${k}}`).join(String(x)), s)

// ── Small pieces ──────────────────────────────────────────────────────────────

function Bar({ value, className = '' }: { value: number; className?: string }) {
  return (
    <div className={`h-2 rounded-full bg-slate-200 overflow-hidden ${className}`}>
      <div
        className="h-full rounded-full bg-teal-700 transition-[width] duration-ja-enter ease-ja-out motion-reduce:transition-none"
        style={{ width: `${Math.min(100, Math.max(0, value))}%` }}
      />
    </div>
  )
}

function ArielDot({ size = 26 }: { size?: number }) {
  const { locale } = useI18n()
  return (
    <span
      aria-hidden
      className="inline-grid place-items-center rounded-full text-white font-bold shrink-0 bg-gradient-to-br from-[#4592A6] to-[#2A6577]"
      style={{ width: size, height: size, fontSize: size * 0.46 }}
    >
      {locale === 'he' ? 'א' : 'A'}
    </span>
  )
}

/** The quiet ✦ next to a section heading: "this part is Ariel's to change". */
function ArielIcon({ section, prompt }: { section: string; prompt: string }) {
  const P = useI18n().t.profile
  const { openChat } = useChat()
  return (
    <button
      type="button"
      onClick={() => openChat({ topic: prompt })}
      aria-label={fill(P.improve_named, { section })}
      title={fill(P.improve_named, { section })}
      className="ja-press inline-grid place-items-center w-11 h-11 sm:w-8 sm:h-8 rounded-full text-ja-aiInk opacity-60 transition-[opacity,background-color] duration-200 [@media(hover:hover)]:hover:opacity-100 [@media(hover:hover)]:hover:bg-ja-ai/[.11] focus-visible:opacity-100 align-middle"
    >
      <SparkIcon s={15} />
    </button>
  )
}

function PhoneIcon() {
  return (
    <svg width={15} height={15} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <rect x="7" y="2.5" width="10" height="19" rx="2.5" /><path d="M11 18h2" />
    </svg>
  )
}
function LinkedInIcon() {
  return (
    <svg width={15} height={15} viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M4.98 3.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5zM3 9.75h4v11H3zM9.5 9.75h3.8v1.6h.06c.53-1 1.83-2.05 3.77-2.05 4.03 0 4.77 2.6 4.77 6v5.45h-4v-4.83c0-1.15-.02-2.63-1.6-2.63-1.6 0-1.85 1.25-1.85 2.55v4.91h-4z" />
    </svg>
  )
}
function PersonIcon() {
  return (
    <svg width={30} height={30} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <circle cx="12" cy="8.5" r="3.6" /><path d="M4.5 20c1.2-3.6 4-5.4 7.5-5.4s6.3 1.8 7.5 5.4" />
    </svg>
  )
}
function DashedCircle() {
  return (
    <svg width={15} height={15} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} aria-hidden>
      <circle cx="12" cy="12" r="7" strokeDasharray="3 3" />
    </svg>
  )
}

const card = 'rounded-[20px] bg-white shadow-elevation-2'
const h2 = 'text-[20px] font-bold tracking-[-0.015em] text-slate-900 text-balance'

// ── §1 Identity card ──────────────────────────────────────────────────────────

function Identity({ data }: { data: Data }) {
  const { t } = useI18n()
  const P = t.profile
  const { user } = useAuth()
  const { openChat } = useChat()
  const { view, roles } = data

  // "Your Name" is a placeholder some accounts were saved with; the sign-in
  // name is the better answer than showing it.
  const stored = view.personal.name.trim()
  const name = stored && stored.toLowerCase() !== 'your name'
    ? stored
    : resolveDisplayName(user?.email, user?.user_metadata as Record<string, unknown> | null)
  const now = latestRole(view.experience)
  const families = roleFamilies(roles)
  const S = t.ariel.seniority as Record<string, string>

  const contact: { key: 'location' | 'phone' | 'email' | 'linkedin'; icon: React.ReactNode; value: string; ltr: boolean }[] = [
    { key: 'location', icon: <PinIcon s={15} />, value: view.personal.location || data.about?.home_city || '', ltr: false },
    { key: 'phone', icon: <PhoneIcon />, value: view.personal.phone, ltr: true },
    { key: 'email', icon: <MailIcon s={15} />, value: view.personal.email || user?.email || '', ltr: true },
    { key: 'linkedin', icon: <LinkedInIcon />, value: view.personal.linkedin.replace(/^https?:\/\/(www\.)?/, '').replace(/\/+$/, ''), ltr: true },
  ]

  return (
    <div>
      <section aria-label={P.sections.card} className={`${card} p-5 sm:p-7`}>
        <div className="flex items-center gap-4 sm:gap-5">
          <span
            aria-label={P.photo}
            role="img"
            className="grid place-items-center shrink-0 w-16 h-16 sm:w-24 sm:h-24 rounded-full bg-teal-50 text-teal-700 ring-[1.5px] ring-inset ring-teal-700/30"
          >
            <PersonIcon />
          </span>
          <div className="flex-1 min-w-0">
            <h1 className="text-[23px] sm:text-[30px] font-extrabold tracking-[-0.025em] leading-[1.15] text-slate-900">{name}</h1>
            {now && (
              <p className="mt-1 text-[13.5px] sm:text-[15px] leading-snug text-slate-500">
                <bdi>{now.role}</bdi>
                {now.company && <><span className="hidden sm:inline"> · </span><span className="block sm:inline font-medium sm:font-normal"><bdi>{now.company}</bdi></span></>}
              </p>
            )}
          </div>
          <span className="self-start"><ArielIcon section={P.sections.card} prompt={P.section_prompts.card} /></span>
        </div>

        {view.summary && (
          <div className="mt-4">
            <p dir="auto" className="text-[16px] sm:text-[16.5px] leading-[1.65] text-slate-700 max-w-[62ch]">{view.summary}</p>
            <Button variant="ariel" size="compact" className="mt-3" onClick={() => openChat({ topic: P.section_prompts.summary })}>
              <SparkIcon s={13} />{P.change_with_ariel}
            </Button>
          </div>
        )}

        <div className="mt-5 pt-5 border-t border-slate-900/[.08] flex flex-col gap-4">
          {families.length > 0 && (
            <div>
              <p className="text-[13px] font-medium text-slate-400 mb-2.5">{P.target_roles}</p>
              <div className="flex flex-col gap-3">
                {families.map(f => (
                  <div key={f.family} className="grid gap-1.5 sm:gap-4 sm:grid-cols-[150px_1fr] sm:items-center">
                    <span className="text-[14px] font-medium text-slate-500">{P.families[f.family]}</span>
                    <div className="flex flex-wrap gap-2">
                      {f.items.map(r => (
                        <span key={r.role} className="inline-flex items-center gap-2 h-[34px] px-3.5 rounded-full bg-teal-600/10 text-ja-inkDeep text-[15px] font-medium">
                          <bdi>{r.role}</bdi>
                          {r.seniority && (
                            <span className="text-[12.5px] font-semibold text-teal-700 bg-white rounded-full px-2 py-0.5 ring-1 ring-inset ring-teal-700/25">
                              {S[r.seniority] ?? r.seniority}
                            </span>
                          )}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
          <ul className="flex flex-wrap gap-x-[22px] gap-y-2 text-[15px] text-slate-500">
            {contact.map(c => (
              <li key={c.key} className="inline-flex items-center gap-[7px] min-w-0">
                <span className="text-slate-400 shrink-0">{c.icon}</span>
                {c.value
                  ? <span dir={c.ltr ? 'ltr' : undefined} className="truncate">{c.value}</span>
                  : <span className="text-amber-700 font-medium">{P.missing[c.key]}</span>}
              </li>
            ))}
          </ul>
        </div>
      </section>
      <div className="flex items-center gap-3 mt-3 px-1.5">
        <ArielDot />
        <p className="text-[14.5px] text-ja-aiDeep">{P.ariel_note}</p>
      </div>
    </div>
  )
}

// ── §2 How well Ariel knows you ───────────────────────────────────────────────

function topicSub(tp: Topic, P: ReturnType<typeof useI18n>['t']['profile']): string {
  const c = tp.checks
  if (tp.id === 'exp') return fill(P.topics.exp.sub, { n: c[0].of ?? 0 })
  if (tp.id === 'cap') return fill(P.topics.cap.sub, { n: c[0].n ?? 0 })
  return fill(P.topics[tp.id].sub, { n: c.filter(x => x.ok).length, of: c.length })
}

function Knows({ topics, overall, selected, onPick }: { topics: Topic[]; overall: number; selected: TopicId | null; onPick: (id: TopicId) => void }) {
  const P = useI18n().t.profile
  const sorted = [...topics].sort((a, b) => b.value - a.value)
  const sentence = sorted[sorted.length - 1].value >= 80
    ? P.know_all_good
    : fill(P.know_sentence, { best: P.topics[sorted[0].id].name, worst: P.topics[sorted[sorted.length - 1].id].name })
  return (
    <section aria-labelledby="h-know">
      <h2 id="h-know" className={h2}>{P.know_title}</h2>
      <p className="mt-1 mb-3.5 text-[14px] text-slate-400">{P.know_sub}</p>
      <div className={`${card} p-5 sm:px-7 sm:py-6 grid gap-4 sm:gap-7 sm:grid-cols-[220px_1fr] items-start`}>
        <div>
          <p className="text-[44px] sm:text-[52px] font-bold tracking-[-0.04em] leading-none text-ja-harbor tabular-nums">
            {fmt(overall)}<span className="text-[22px] text-slate-400 font-medium ms-0.5">%</span>
          </p>
          <p className="mt-2.5 text-[15px] leading-[1.55] text-slate-700">{sentence}</p>
        </div>
        <div className="flex flex-col">
          {topics.map(tp => (
            <button
              key={tp.id}
              type="button"
              onClick={() => onPick(tp.id)}
              aria-expanded={selected === tp.id}
              className={`ja-press group grid grid-cols-[1fr_46px_18px] sm:grid-cols-[150px_1fr_52px_22px] items-center gap-x-3.5 gap-y-1.5 py-3 px-2.5 -mx-2.5 rounded-xl text-start transition-colors duration-200 ${
                selected === tp.id ? 'bg-ja-ai/[.11]' : '[@media(hover:hover)]:hover:bg-ja-ai/[.07]'
              }`}
            >
              <span className="text-[15.5px] font-medium text-slate-900">
                {P.topics[tp.id].name}
                <small className="block text-[12.5px] font-normal text-slate-400">{topicSub(tp, P)}</small>
              </span>
              <Bar value={tp.value} className="col-span-full row-start-2 sm:col-span-1 sm:row-start-auto" />
              <span className="text-[15px] font-semibold text-end tabular-nums text-slate-900">{fmt(tp.value)}</span>
              <span className="text-ja-aiInk opacity-70 rtl:rotate-180 justify-self-center"><ChevIcon s={14} /></span>
            </button>
          ))}
          <details className="mt-1 rounded-xl bg-slate-50 px-3.5 py-3 text-[13px] text-slate-600">
            <summary className="cursor-pointer font-medium text-teal-700 list-none [&::-webkit-details-marker]:hidden">{P.how_title}</summary>
            <dl className="mt-2.5">
              {topics.map(tp => (
                <div key={tp.id} className="grid sm:grid-cols-[130px_1fr] gap-x-2.5 py-1.5 border-t border-slate-900/[.08]">
                  <dt className="font-semibold text-slate-700">{P.topics[tp.id].name}</dt><dd>{P.topics[tp.id].how}</dd>
                </div>
              ))}
              <div className="grid sm:grid-cols-[130px_1fr] gap-x-2.5 py-1.5 border-t border-slate-900/[.08]">
                <dt className="font-semibold text-slate-700">{P.overall}</dt><dd>{P.how_overall}</dd>
              </div>
            </dl>
          </details>
        </div>
      </div>
    </section>
  )
}

// ── §3 Capabilities ───────────────────────────────────────────────────────────

const SHOWN = 6

function Capabilities({ domains, byName, selected, onPick }: {
  domains: CapabilityDomain[]; byName: Map<string, TrustProfileEntity>; selected: string | null
  onPick: (e: TrustProfileEntity, domain: string) => void
}) {
  const { t } = useI18n()
  const P = t.profile
  const labels = t.trust.radar.categories as Record<string, string>
  const [open, setOpen] = useState<string | null>(domains[0]?.category ?? null)
  const [all, setAll] = useState<Record<string, boolean>>({})
  if (!domains.length) return null
  const label = (c: string) => labels[c] ?? P.other_domain
  return (
    <section aria-labelledby="h-caps">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 mb-3.5">
        <h2 id="h-caps" className={h2}>{P.caps_title} <ArielIcon section={P.sections.caps} prompt={P.section_prompts.caps} /></h2>
        <small className="text-[14px] text-slate-400">{fill(P.caps_sub, { n: domains.length })}</small>
      </div>
      <div className="grid gap-3.5 sm:grid-cols-2">
        {domains.map(d => {
          const isOpen = open === d.category
          const shown = all[d.category] ? d.skills : d.skills.slice(0, SHOWN)
          return (
            <div key={d.category} className={`rounded-[18px] bg-white transition-shadow duration-ja-ui ${isOpen ? 'sm:col-span-2 shadow-elevation-2' : 'shadow-elevation-1'}`}>
              <button
                type="button"
                onClick={() => setOpen(isOpen ? null : d.category)}
                aria-expanded={isOpen}
                className="ja-press w-full grid grid-cols-[1fr_auto] gap-x-4 gap-y-1.5 px-5 py-[18px] rounded-[18px] text-start [@media(hover:hover)]:hover:bg-slate-900/[.02]"
              >
                <span>
                  <b className="block text-[16.5px] font-semibold text-slate-900">{label(d.category)}</b>
                  <small className="text-[13.5px] text-slate-400">{fill(P.domain_meta, { n: d.count })}</small>
                </span>
                <span className={`text-slate-400 transition-transform duration-ja-ui ${isOpen ? 'rotate-180' : ''}`}><ChevIcon s={18} /></span>
                <span className="col-span-full flex items-center gap-2.5">
                  <Bar value={d.avg} className="flex-1" />
                  <span className="text-[15px] font-semibold tabular-nums text-slate-900">{fmt(d.avg)}</span>
                </span>
              </button>
              {isOpen && (
                <div className="px-2.5 pb-3 animate-ja-tab-in">
                  {shown.map(s => {
                    const e = byName.get(s.name.toLowerCase())
                    return (
                      <button
                        key={s.name}
                        type="button"
                        disabled={!e}
                        onClick={() => e && onPick(e, label(d.category))}
                        className={`ja-press w-full grid grid-cols-[minmax(0,1fr)_46px] sm:grid-cols-[minmax(0,1fr)_180px_46px] items-center gap-x-4 gap-y-1.5 px-2.5 py-[11px] rounded-xl text-start border-t border-slate-900/[.08] first:border-t-0 transition-colors ${
                          selected === s.name ? 'bg-teal-600/10' : '[@media(hover:hover)]:hover:bg-teal-600/10'
                        }`}
                      >
                        <span className="text-[15.5px] text-slate-900 [overflow-wrap:anywhere]"><bdi>{s.name}</bdi></span>
                        <Bar value={s.score} className="col-span-full row-start-2 sm:col-span-1 sm:row-start-auto" />
                        <span className="text-[15px] font-semibold text-end tabular-nums text-slate-900">{fmt(s.score)}</span>
                      </button>
                    )
                  })}
                  {d.skills.length > SHOWN && (
                    <button
                      type="button"
                      onClick={() => setAll(a => ({ ...a, [d.category]: !a[d.category] }))}
                      className="mt-1 px-2.5 py-2 text-[14px] font-medium text-teal-700 underline underline-offset-[3px] decoration-teal-700/35"
                    >
                      {all[d.category] ? P.show_less : fill(P.show_all, { n: d.count })}
                    </button>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}

// ── §4 Experience ─────────────────────────────────────────────────────────────


function Experience({ view }: { view: ProfileView }) {
  const P = useI18n().t.profile
  const companies = companyEntries(view.experience)
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const period = (s: string, e: string) => periodYears(s, e, P.present)
  return (
    <section aria-labelledby="h-exp">
      <h2 id="h-exp" className={`${h2} mb-3.5`}>{P.exp_title} <ArielIcon section={P.sections.exp} prompt={P.section_prompts.exp} /></h2>
      <div className={`${card} px-5 sm:px-[22px] py-1.5`}>
        {companies.length === 0 && <p className="py-5 text-[15px] text-slate-500">{P.no_experience}</p>}
        {companies.map((c, i) => (
          <div key={`${c.company}-${i}`} className="grid grid-cols-[40px_1fr] sm:grid-cols-[44px_1fr] gap-x-3 sm:gap-x-4 py-5 border-t border-slate-900/[.08] first:border-t-0">
            <CompanyLogo company={c.company} size={40} radius={12} />
            <div className="flex flex-col justify-center min-h-10 sm:min-h-11">
              <b className="text-[17px] font-bold text-slate-900"><bdi>{c.company || '—'}</bdi></b>
              {c.steps.length > 1 && <span className="text-[14px] text-slate-400 tabular-nums">{period(c.start, c.end)}</span>}
            </div>
            <ol className="col-span-full sm:col-start-2 mt-3.5 flex flex-col gap-[18px]">
              {c.steps.map((st, j) => (
                <li key={j} className={`relative ${c.steps.length > 1 ? 'ps-5' : ''}`}>
                  {c.steps.length > 1 && (
                    <>
                      <span aria-hidden className="absolute start-0 top-[9px] w-2 h-2 rounded-full bg-teal-700" />
                      {j < c.steps.length - 1 && <span aria-hidden className="absolute start-[3.5px] top-[22px] -bottom-[14px] w-px bg-teal-700/25" />}
                    </>
                  )}
                  <span className="block text-[16px] font-semibold text-slate-900"><bdi>{st.role.role}</bdi></span>
                  {st.parallel.map(p => (
                    <span key={p.role} className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[15px] font-medium text-slate-700">
                      <bdi>{p.role}</bdi>
                      <span className="text-[12px] px-2.5 py-0.5 rounded-full bg-teal-600/10 text-ja-inkDeep font-medium">{P.parallel}</span>
                    </span>
                  ))}
                  <span className="block mt-0.5 text-[13.5px] text-slate-400 tabular-nums">{period(st.role.start, st.role.end)}</span>
                  {st.role.details.trim() && (() => {
                    // One paragraph per step, the main role's. Long CV text is
                    // cut to four lines until Ariel writes the short version.
                    const key = `${i}-${j}`, more = !!expanded[key], long = st.role.details.length > 320
                    return (
                      <>
                        <p dir="auto" className={`mt-2 text-[15.5px] leading-[1.7] text-slate-700 max-w-[64ch] ${long && !more ? 'line-clamp-4' : ''}`}>{st.role.details}</p>
                        {long && (
                          <button
                            type="button"
                            aria-expanded={more}
                            onClick={() => setExpanded(x => ({ ...x, [key]: !more }))}
                            className="mt-1 text-[14px] font-medium text-teal-700 underline underline-offset-[3px] decoration-teal-700/35"
                          >
                            {more ? P.read_less : P.read_more}
                          </button>
                        )}
                      </>
                    )
                  })()}
                </li>
              ))}
            </ol>
          </div>
        ))}
      </div>
    </section>
  )
}

// ── §5 Education, service and languages ───────────────────────────────────────

function Education({ view }: { view: ProfileView }) {
  const { t } = useI18n()
  const P = t.profile
  const army = militaryService(view.experience)
  const mini = 'rounded-[18px] bg-white shadow-elevation-1 px-5 py-[18px]'
  const it = 'py-2 border-t border-slate-900/[.08] first-of-type:border-t-0 first-of-type:pt-0'
  const none = <p className="text-[14px] text-slate-400">{P.none_yet}</p>
  return (
    <section aria-labelledby="h-edu">
      <h2 id="h-edu" className={`${h2} mb-3.5`}>{P.edu_title} <ArielIcon section={P.sections.edu} prompt={P.section_prompts.edu} /></h2>
      <div className="grid gap-3.5 md:grid-cols-3">
        <div className={mini}>
          <h3 className="mb-3 text-[15px] font-semibold text-slate-500">{P.education}</h3>
          {view.education.length ? view.education.map((e, i) => (
            <div key={i} className={it}>
              <b dir="auto" className="block text-[15.5px] font-semibold text-slate-900">{e.degree}</b>
              <span dir="auto" className="text-[14px] text-slate-500">{[e.school, e.period].filter(Boolean).join(' · ')}</span>
            </div>
          )) : none}
        </div>
        <div className={mini}>
          <h3 className="mb-3 text-[15px] font-semibold text-slate-500">{P.military}</h3>
          {army.length ? army.map((e, i) => (
            <div key={i} className={it}>
              <b dir="auto" className="block text-[15.5px] font-semibold text-slate-900">{e.role}</b>
              <span dir="auto" className="text-[14px] text-slate-500">{[e.company, periodYears(e.start, e.end, P.present)].filter(Boolean).join(' · ')}</span>
            </div>
          )) : none}
        </div>
        <div className={mini}>
          <h3 className="mb-3 text-[15px] font-semibold text-slate-500">{P.languages}</h3>
          {view.languages.length ? view.languages.map((l, i) => (
            <div key={i} className={`${it} flex items-center justify-between gap-2.5`}>
              <b dir="auto" className="text-[15.5px] font-semibold text-slate-900">{l.language}</b>
              {l.level && <span dir="auto" className="text-[13px] px-2.5 py-0.5 rounded-full bg-teal-600/10 text-ja-inkDeep font-medium">{l.level}</span>}
            </div>
          )) : none}
        </div>
      </div>
    </section>
  )
}

// ── Side panel ────────────────────────────────────────────────────────────────

function checkText(c: Check, P: ReturnType<typeof useI18n>['t']['profile']): string {
  const t = P.checks[c.key]
  if (!t) return c.key
  const of = c.of ?? 0, n = c.n ?? 0
  return fill(c.ok ? t.ok : t.no, { n, of, miss: of - n })
}

function SidePanel({ panel, topics, onClose }: { panel: Panel; topics: Topic[]; onClose: () => void }) {
  const { t } = useI18n()
  const P = t.profile
  const sources = t.trust.sources as Record<string, string>
  const { openChat } = useChat()
  const headRef = useRef<HTMLHeadingElement>(null)
  // Keep the last content while the panel slides out, so it doesn't empty mid-exit.
  const [shown, setShown] = useState<Panel>(panel)
  useEffect(() => { if (panel) setShown(panel) }, [panel])
  useEffect(() => { if (panel) headRef.current?.focus() }, [panel])

  const open = !!panel
  const chip = 'text-[13px] font-medium px-[11px] py-1 rounded-full bg-teal-600/10 text-ja-inkDeep'
  let body: React.ReactNode = null

  if (shown?.type === 'skill') {
    const e = shown.entity
    const quotes = e.trust_breakdown.filter(ev => ev.raw_content?.trim()).slice(0, 3)
    body = (
      <>
        <div className="flex items-center justify-between gap-2.5">
          <span className={chip}>{shown.domain}</span>
          <Button variant="quiet" size="compact" iconOnly aria-label={P.close} onClick={onClose}><XIcon s={14} /></Button>
        </div>
        <h2 ref={headRef} tabIndex={-1} className="text-[24px] font-bold tracking-[-0.02em] leading-tight text-slate-900 [overflow-wrap:anywhere] outline-none"><bdi>{e.name}</bdi></h2>
        <div className="flex items-center gap-3.5">
          <Bar value={e.confidence_score} className="flex-1 h-2.5" />
          <span className="text-[22px] font-bold tabular-nums text-slate-900">{fmt(e.confidence_score)}</span>
        </div>
        <div>
          <h3 className="mb-2 text-[13.5px] font-semibold text-slate-400">{P.why_title}</h3>
          <p className="text-[15.5px] leading-[1.65] text-slate-700">{P.verification[e.verification_level] ?? P.verification.UNVERIFIED}</p>
          <div className="mt-3 flex flex-col gap-2.5">
            {quotes.length ? quotes.map(q => (
              <blockquote key={q.evidence_id} className="border-s-2 border-teal-600/35 ps-3">
                <small className="block text-[12.5px] font-medium text-slate-400 mb-0.5">{sources[q.source_type] ?? q.source_label}</small>
                <p dir="auto" className="text-[14.5px] text-slate-700 line-clamp-4">{q.raw_content}</p>
              </blockquote>
            )) : <p className="text-[14.5px] text-slate-500">{P.no_evidence}</p>}
          </div>
        </div>
        <Button variant="primary" size="md" className="w-full" onClick={() => {
          openChat({ topic: fill(P.strengthen_prompt, { name: e.name, score: fmt(e.confidence_score) }) }); onClose()
        }}>
          <SparkIcon s={14} />{P.strengthen}
        </Button>
      </>
    )
  } else if (shown?.type === 'topic') {
    const tp = topics.find(x => x.id === shown.id)
    if (tp) {
      const known = tp.checks.filter(c => c.ok), missing = tp.checks.filter(c => !c.ok)
      body = (
        <>
          <div className="flex items-center justify-between gap-2.5">
            <span className={chip}>{P.know_title}</span>
            <Button variant="quiet" size="compact" iconOnly aria-label={P.close} onClick={onClose}><XIcon s={14} /></Button>
          </div>
          <h2 ref={headRef} tabIndex={-1} className="text-[24px] font-bold tracking-[-0.02em] leading-tight text-slate-900 outline-none">{P.topics[tp.id].name}</h2>
          <div className="flex items-center gap-3.5">
            <Bar value={tp.value} className="flex-1 h-2.5" />
            <span className="text-[22px] font-bold tabular-nums text-slate-900">{fmt(tp.value)}</span>
          </div>
          <div>
            <h3 className="mb-2 text-[13.5px] font-semibold text-slate-400">{P.known}</h3>
            <ul className="flex flex-col gap-2.5">
              {known.length ? known.map(c => (
                <li key={c.key} className="flex gap-2.5 items-start text-[15px] leading-[1.55] text-slate-700">
                  <span className="mt-1 text-teal-700 shrink-0"><CheckIcon s={15} /></span>{checkText(c, P)}
                </li>
              )) : <li className="text-[15px] text-slate-500">{P.nothing_yet}</li>}
            </ul>
          </div>
          {missing.length > 0 && (
            <div>
              <h3 className="mb-2 text-[13.5px] font-semibold text-slate-400">{P.still_missing}</h3>
              <ul className="flex flex-col gap-2.5">
                {missing.map(c => (
                  <li key={c.key} className="flex gap-2.5 items-start text-[15px] leading-[1.55] text-slate-700">
                    <span className="mt-1 text-amber-700 shrink-0"><DashedCircle /></span>{checkText(c, P)}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="flex flex-col gap-2.5 pt-1.5">
            <Button variant="ariel" size="md" className="w-full" onClick={() => { openChat({ topic: P.topics[tp.id].prompt }); onClose() }}>
              <SparkIcon s={14} />{P.complete_with_ariel}
            </Button>
            {/* The company questions are chips, quicker to tap than to tell Ariel. */}
            {tp.id === 'mob' && (
              <Link href="/onboarding?step=preferences&q=5" className={`${buttonClasses({ variant: 'secondary', size: 'md' })} w-full`}>
                {P.edit_company}
              </Link>
            )}
            <p className="text-[13px] leading-normal text-slate-400">{P.topics[tp.id].how}</p>
          </div>
        </>
      )
    }
  }

  return (
    <aside
      aria-label={shown?.type === 'skill' ? shown.entity.name : shown?.type === 'topic' ? P.topics[shown.id].name : undefined}
      aria-hidden={!open}
      inert={!open}
      className={`fixed z-50 md:z-30 bg-white overflow-y-auto overscroll-contain
        inset-x-0 bottom-0 top-14 rounded-t-[24px] shadow-floating
        md:top-[108px] md:bottom-0 md:inset-x-auto md:end-0 md:w-[420px] md:rounded-none md:shadow-floating xl:shadow-none md:border-s md:border-slate-900/[.08]
        transition-[transform,opacity] duration-ja-enter ease-ja-out motion-reduce:transition-opacity motion-reduce:duration-200
        ${open
          ? 'translate-x-0 translate-y-0 opacity-100'
          : 'translate-y-full md:translate-y-0 md:ltr:translate-x-full md:rtl:-translate-x-full motion-reduce:translate-x-0 motion-reduce:translate-y-0 opacity-0 pointer-events-none'}`}
    >
      <div className="flex flex-col gap-[22px] px-[18px] pt-[18px] pb-28 md:px-6 md:pt-[22px]">{body}</div>
    </aside>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function ProfilePage({ userId }: { userId: string }) {
  const P = useI18n().t.profile
  const { openChat, profileVersion } = useChat()
  const [data, setData] = useState<Data | null>(null)
  const [failed, setFailed] = useState(false)
  const [panel, setPanel] = useState<Panel>(null)

  const load = useCallback(async () => {
    setFailed(false)
    try {
      const [view, prefs, about, trust] = await Promise.all([
        fetchProfileView(),
        fetchRolePreferences(),
        fetchAbout().catch(() => null),
        fetchTrustScore(userId).catch(() => null),
      ])
      setData({ view, roles: prefs.roles, about, entities: trust?.entities ?? [] })
    } catch {
      setFailed(true)
    }
  }, [userId])

  // Refetch whenever Ariel may have changed the profile.
  useEffect(() => { void load() }, [load, profileVersion])

  useEffect(() => {
    if (!panel) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setPanel(null) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [panel])

  const derived = useMemo(() => {
    if (!data) return null
    const entities = data.entities.map(e => ({ name: e.name, category: e.category ?? 'Other', score: e.confidence_score, verification_level: e.verification_level }))
    return {
      domains: capabilityDomains(entities),
      byName: new Map(data.entities.map(e => [e.name.toLowerCase(), e])),
      ...knowledgeTopics({ view: data.view, entities, roles: data.roles, about: data.about }),
    }
  }, [data])

  if (failed) {
    return (
      <div className="max-w-[860px] mx-auto px-4 py-16 text-center">
        <p className="text-[16px] text-slate-600">{P.load_failed}</p>
        <Button variant="secondary" className="mt-4" onClick={() => void load()}>{P.retry}</Button>
      </div>
    )
  }
  if (!data || !derived) {
    return (
      <div className="max-w-[860px] mx-auto px-4 sm:px-7 py-9 flex flex-col gap-11" aria-busy="true">
        {[200, 240, 300].map(h => <div key={h} className="rounded-[20px] bg-slate-900/[.04] animate-pulse" style={{ height: h }} />)}
      </div>
    )
  }

  const isEmpty = data.view.experience.length === 0 && data.entities.length === 0
  const selectedSkill = panel?.type === 'skill' ? panel.entity.name : null
  const selectedTopic = panel?.type === 'topic' ? panel.id : null

  return (
    <>
      <div className={`transition-[margin] duration-ja-enter ease-ja-out motion-reduce:transition-none ${panel ? 'xl:me-[420px]' : ''}`}>
        <div className="max-w-[860px] mx-auto px-4 sm:px-7 pt-6 sm:pt-9 pb-20 flex flex-col gap-9 sm:gap-11">
          {isEmpty ? (
            <section className={`${card} px-6 sm:px-8 py-10 flex flex-col items-center text-center gap-3.5`}>
              <span className="grid place-items-center w-20 h-20 rounded-full bg-teal-50 text-teal-700"><PersonIcon /></span>
              <h1 className="text-[28px] font-extrabold tracking-[-0.02em] text-slate-900">{P.title}</h1>
              <p className="text-[16.5px] text-slate-500 max-w-[44ch]">{P.empty_body}</p>
              <div className="flex flex-wrap justify-center gap-2.5 mt-2">
                <Link href="/profile-builder" className={buttonClasses({ variant: 'primary', size: 'lg' })}>{P.empty_upload}</Link>
                <Button variant="ariel" size="md" onClick={() => openChat({ topic: P.topics.exp.prompt })}><SparkIcon s={14} />{P.empty_talk}</Button>
              </div>
            </section>
          ) : (
            <>
              <Identity data={data} />
              <Knows
                topics={derived.topics}
                overall={derived.overall}
                selected={selectedTopic}
                onPick={id => setPanel(p => (p?.type === 'topic' && p.id === id ? null : { type: 'topic', id }))}
              />
              <Capabilities
                domains={derived.domains}
                byName={derived.byName}
                selected={selectedSkill}
                onPick={(entity, domain) => setPanel({ type: 'skill', entity, domain })}
              />
              <Experience view={data.view} />
              <Education view={data.view} />
            </>
          )}
        </div>
      </div>
      <SidePanel panel={panel} topics={derived.topics} onClose={() => setPanel(null)} />
    </>
  )
}
