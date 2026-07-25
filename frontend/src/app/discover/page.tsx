'use client'

import Link        from 'next/link'
import AuthGuard   from '@/components/AuthGuard'

// ── Trending job seed data ─────────────────────────────────────────────────────

// Deliberately diverse placeholder mix — this page is shown to visitors and
// incomplete profiles across every field, not just product management.
const TRENDING_JOBS = [
  {
    id: '1',
    title: 'Account Manager',
    company: 'Monday.com',
    location: 'Tel Aviv, IL',
    tags: ['SaaS', 'Client-facing', 'B2B'],
    postedAgo: '2h ago',
  },
  {
    id: '2',
    title: 'Full Stack Developer',
    company: 'Wix',
    location: 'Tel Aviv, IL',
    tags: ['React', 'Node.js', 'Platform'],
    postedAgo: '4h ago',
  },
  {
    id: '3',
    title: 'Marketing Director',
    company: 'Fiverr',
    location: 'Hybrid — Tel Aviv',
    tags: ['Brand', 'Growth', 'Leadership'],
    postedAgo: '7h ago',
  },
  {
    id: '4',
    title: 'Data Analyst',
    company: 'Lightricks',
    location: 'Jerusalem, IL',
    tags: ['SQL', 'Dashboards', 'Product Analytics'],
    postedAgo: '1d ago',
  },
  {
    id: '5',
    title: 'Customer Success Manager',
    company: 'Gong',
    location: 'Remote',
    tags: ['Enterprise', 'Onboarding', 'Renewals'],
    postedAgo: '1d ago',
  },
  {
    id: '6',
    title: 'Product Manager',
    company: 'Stripe',
    location: 'Remote',
    tags: ['Fintech', 'API', 'B2B'],
    postedAgo: '2d ago',
  },
]

// ── Sub-components ────────────────────────────────────────────────────────────

function CompanyAvatar({ name }: { name: string }) {
  const initials = name.split(' ').slice(0, 2).map(w => w[0]).join('')
  const hue = name.split('').reduce((acc, c) => acc + c.charCodeAt(0), 0) % 360
  return (
    <div
      className="w-10 h-10 rounded-xl flex items-center justify-center text-white text-xs font-bold flex-shrink-0"
      style={{ background: `hsl(${hue},55%,45%)` }}
      aria-hidden="true"
    >
      {initials}
    </div>
  )
}

function MatchScoreTeaser() {
  // Inviting placeholder — replaces the old "Match score pending" +
  // "Complete your profile to unlock" pair that read like an error state.
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] font-medium text-ja-primary bg-ja-primarySubtle rounded-full px-2.5 py-1">
      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
      </svg>
      Sign in to see your match score
    </span>
  )
}

function JobCard({ job }: { job: typeof TRENDING_JOBS[0] }) {
  return (
    <div
      className="bg-white rounded-2xl border border-slate-100 p-5 flex flex-col gap-4 shadow-elevation-1 hover:shadow-elevation-2 transition-shadow"
    >
      <div className="flex items-start gap-3">
        <CompanyAvatar name={job.company} />
        <div className="flex-1 min-w-0">
          <h3 className="text-[14px] font-semibold text-slate-900 leading-tight truncate">
            {job.title}
          </h3>
          <p className="text-[12px] text-slate-500 mt-0.5">
            {job.company} &middot; {job.location}
          </p>
        </div>
        <span className="text-[11px] text-slate-400 flex-shrink-0 mt-0.5">{job.postedAgo}</span>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {job.tags.map(tag => (
          <span
            key={tag}
            className="text-[11px] px-2 py-0.5 rounded-md font-medium bg-ja-primarySubtle text-ja-primary"
          >
            {tag}
          </span>
        ))}
      </div>

      <div className="flex items-center pt-1 border-t border-slate-50">
        <MatchScoreTeaser />
      </div>
    </div>
  )
}

// ── Page content ──────────────────────────────────────────────────────────────

function DiscoverContent() {
  return (
    <div className="min-h-screen bg-slate-50">
      {/* Single primary CTA policy: the "Complete profile" banner below is the
          one and only profile CTA on this page — no duplicate header button. */}
      <header className="bg-white border-b border-slate-100 sticky top-0 z-20">
        <div className="max-w-5xl mx-auto px-6 h-14 flex items-center">
          <span className="text-base font-extrabold tracking-tight text-slate-900">JobApply</span>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-10 space-y-8">

        {/* Profile prompt banner */}
        <div
          className="rounded-2xl p-6 flex flex-col sm:flex-row sm:items-center gap-4 border border-white/[0.06]"
          style={{ background: 'linear-gradient(135deg, var(--ja-ink) 0%, var(--ja-ink-deep) 100%)' }}
        >
          <div className="flex-1 space-y-1">
            <p className="text-white font-semibold text-[15px]">Your match scores are waiting</p>
            <p className="text-[13px] text-ja-subtle">
              Complete your profile to unlock personalised match scores for every job below.
            </p>
          </div>
          <Link
            href="/onboarding"
            className="flex-shrink-0 text-sm font-semibold px-5 py-2.5 rounded-xl text-white text-center bg-ja-primary hover:bg-ja-primaryHover transition-colors"
          >
            Complete profile
          </Link>
        </div>

        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-slate-900">Trending jobs</h1>
            <p className="text-sm text-slate-500 mt-0.5">Updated daily based on market demand</p>
          </div>
          <span
            className="text-[11px] font-semibold px-2.5 py-1 rounded-full bg-ja-primarySubtle text-ja-primary"
          >
            {TRENDING_JOBS.length} roles
          </span>
        </div>

        {/* Job grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {TRENDING_JOBS.map(job => <JobCard key={job.id} job={job} />)}
        </div>

      </main>
    </div>
  )
}

// ── Page (guarded) ────────────────────────────────────────────────────────────

export default function DiscoverPage() {
  return (
    <AuthGuard>
      <DiscoverContent />
    </AuthGuard>
  )
}
