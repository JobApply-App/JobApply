'use client'

import { useI18n } from '@/contexts/I18nContext'
import { Ring } from '@/components/landing/Ring'

// The landing's example jobs, sorted best first, beside the login form. Phones
// skip it, because someone here came to sign in; so do short screens, where the
// form needs the attention.
export function ExampleFeed() {
  const { t, dir } = useI18n()
  const L = t.landing
  const flip = dir === 'rtl' ? -1 : 1
  const cards = [
    { job: L.jobs[1], score: 91.2, fan: `translateX(${-14 * flip}px) rotate(${-2 * flip}deg)` },
    { job: L.jobs[0], score: 82.4, fan: `translateX(${12 * flip}px) rotate(${1.5 * flip}deg)` },
    { job: L.jobs[3], score: 74.0, fan: 'none' },
  ]
  return (
    <div role="group" aria-label={L.hero.feed_label} className="max-lg:hidden [@media(max-height:719px)]:hidden max-w-[440px]">
      {cards.map(({ job, score, fan }, i) => (
        <div key={score} style={{ transform: fan, zIndex: i }} className={`relative ${i > 0 ? '-mt-1' : ''}`}>
          <div style={{ animationDelay: `${i * 90}ms` }}
            className="animate-ja-rise motion-reduce:animate-none flex items-center justify-between gap-4 rounded-[20px] bg-white shadow-floating px-5 py-4">
            <div className="min-w-0">
              <div dir="auto" className="font-bold text-[16px] tracking-tight text-slate-900 text-start truncate">{job.title}</div>
              <div className="text-[13px] text-slate-500">{job.place}</div>
            </div>
            <Ring value={score} size={52} />
          </div>
        </div>
      ))}
      <p className="mt-6 text-[13px] text-slate-600">{L.hero.example}</p>
    </div>
  )
}
