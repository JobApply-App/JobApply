'use client'
// "What works" (Ron 27.11): the part of the old Analytics page that the
// journey does not already show, at the foot of Applications. Three recorded
// facts: how many applications stand at an interview or an offer, where the
// user applied most, and the skills their tailored CVs lead with. Hidden until
// there is an application to read, and when the summary cannot be loaded.

import { useEffect, useState } from 'react'
import { useI18n } from '@/contexts/I18nContext'
import { fetchAnalyticsSummary, type AnalyticsSummary } from '@/lib/api'
import { useCountUp, useReducedMotion } from '@/hooks/useMotion'
import { CompanyLogo } from '../ui/CompanyLogo'

const COMPANIES = 5
const SKILLS = 8

export function WhatWorks({ refreshKey }: { refreshKey: number }) {
  const W = useI18n().t.applications.works
  const reduced = useReducedMotion()
  const [data, setData] = useState<AnalyticsSummary | null>(null)

  useEffect(() => {
    let live = true
    fetchAnalyticsSummary().then(d => { if (live) setData(d) }).catch(() => {})
    return () => { live = false }
  }, [refreshKey])

  const rate = useCountUp(data ? data.interview_conversion_rate : null, reduced, 1100, 1)
  if (!data || data.total_applications === 0) return null

  const companies = data.top_companies.slice(0, COMPANIES)
  const skills = data.top_keywords.slice(0, SKILLS)
  const pct = Math.max(0, Math.min(100, data.interview_conversion_rate))

  return (
    <section aria-labelledby="what-works" className="animate-ja-reveal pt-4" style={{ animationDelay: '300ms' }}>
      <h2 id="what-works" className="text-[24px] sm:text-[30px] font-extrabold tracking-[-0.035em] text-slate-900">{W.title}</h2>
      <p className="mt-1.5 text-[15px] text-slate-500">{W.lead}</p>

      {/* The skills card waits for a tailored CV: an empty card the height of
          the others read as broken (Ron 27.11), so until then there are two. */}
      <div className={`mt-5 grid gap-4 ${skills.length > 0 ? 'lg:grid-cols-3' : 'lg:grid-cols-2'}`}>
        <div className="rounded-3xl border border-slate-100 bg-white p-6 shadow-elevation-2">
          <p className="text-[13px] font-semibold text-slate-500">{W.rate_label}</p>
          <p className="mt-2 text-[44px] font-extrabold leading-none tracking-[-0.05em] tabular-nums text-teal-700">
            {(rate ?? 0).toFixed(1)}%
          </p>
          <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-slate-100" aria-hidden>
            <span
              className="block h-full origin-left rtl:origin-right animate-ja-grow rounded-full bg-gradient-to-r rtl:bg-gradient-to-l from-teal-700 to-teal-500"
              style={{ width: `${pct}%`, animationDelay: '400ms' }}
            />
          </div>
          <p className="mt-3 text-[14px] leading-relaxed text-slate-600">
            {W.rate_body.replace('{total}', String(data.total_applications))}
          </p>
        </div>

        <div className="rounded-3xl border border-slate-100 bg-white p-6 shadow-elevation-2">
          <p className="text-[13px] font-semibold text-slate-500">{W.companies_label}</p>
          {companies.length === 0 ? (
            <p className="mt-3 text-[14px] text-slate-400">{W.none}</p>
          ) : (
            <ol className="mt-3 space-y-2.5">
              {companies.map(c => (
                <li key={c.company} className="flex items-center gap-3">
                  <CompanyLogo company={c.company} size={30} />
                  <span dir="auto" className="min-w-0 flex-1 truncate text-[14px] font-medium text-slate-800">{c.company}</span>
                  <span className="shrink-0 text-[13px] tabular-nums text-slate-500">
                    {c.count === 1 ? W.apps_one : W.apps_many.replace('{n}', String(c.count))}
                  </span>
                </li>
              ))}
            </ol>
          )}
        </div>

        {skills.length > 0 && (
          <div className="rounded-3xl border border-slate-100 bg-white p-6 shadow-elevation-2">
            <p className="text-[13px] font-semibold text-slate-500">{W.skills_label}</p>
            <ul className="mt-3 flex flex-wrap gap-2">
              {skills.map(k => (
                <li key={k.keyword} dir="auto" className="inline-flex items-center gap-1.5 rounded-full bg-teal-50 px-3 py-1 text-[13px] text-teal-800">
                  {k.keyword}<span className="text-teal-600/70 tabular-nums">{k.count}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  )
}
