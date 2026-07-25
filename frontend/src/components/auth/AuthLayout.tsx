'use client'

import Link from 'next/link'
import { TOKENS } from '@/lib/tokens'

// ── Decorative SVG — abstract tech / neural-network pattern ──────────────────

function TechPattern() {
  return (
    <svg
      aria-hidden="true"
      className="absolute inset-0 w-full h-full opacity-[0.06] pointer-events-none"
      viewBox="0 0 800 600"
      preserveAspectRatio="xMidYMid slice"
      xmlns="http://www.w3.org/2000/svg"
    >
      {/* Grid lines */}
      {Array.from({ length: 12 }).map((_, i) => (
        <line key={`v${i}`} x1={i * 73} y1="0" x2={i * 73} y2="600"
          stroke="white" strokeWidth="0.5" />
      ))}
      {Array.from({ length: 9 }).map((_, i) => (
        <line key={`h${i}`} x1="0" y1={i * 75} x2="800" y2={i * 75}
          stroke="white" strokeWidth="0.5" />
      ))}
      {/* Network nodes */}
      {[
        [73,75],[219,150],[365,75],[511,150],[657,75],
        [146,225],[292,300],[438,225],[584,300],[730,225],
        [73,375],[219,450],[365,375],[511,450],[657,375],
        [292,525],[438,525],
      ].map(([cx, cy], i) => (
        <circle key={i} cx={cx} cy={cy} r="4" fill="white" />
      ))}
      {/* Connection lines */}
      {[
        [73,75,219,150],[219,150,365,75],[365,75,511,150],[511,150,657,75],
        [73,75,146,225],[219,150,292,300],[365,75,438,225],[511,150,584,300],
        [146,225,292,300],[292,300,438,225],[438,225,584,300],
        [146,225,73,375],[292,300,219,450],[438,225,365,375],[584,300,511,450],
        [73,375,219,450],[219,450,365,375],[365,375,511,450],
        [219,450,292,525],[365,375,438,525],
      ].map(([x1,y1,x2,y2], i) => (
        <line key={i} x1={x1} y1={y1} x2={x2} y2={y2}
          stroke="white" strokeWidth="0.8" />
      ))}
      {/* Accent circles */}
      <circle cx="365" cy="75"  r="8" fill="none" stroke={TOKENS.color.primary} strokeWidth="1.5" />
      <circle cx="292" cy="300" r="6" fill="none" stroke={TOKENS.color.primary} strokeWidth="1.5" />
      <circle cx="511" cy="450" r="8" fill="none" stroke={TOKENS.color.primary} strokeWidth="1.5" />
    </svg>
  )
}

// ── Left panel brand metrics ───────────────────────────────────────────────────

const METRICS = [
  { value: '3×',  label: 'More interviews'  },
  { value: '92%', label: 'ATS pass rate'    },
  { value: '<5m', label: 'Per CV tailored'  },
]

// ── Component ─────────────────────────────────────────────────────────────────

interface AuthLayoutProps {
  children:         React.ReactNode
  /** Shown above the main headline on the left panel */
  leftEyebrow?:     string
  leftHeadline?:    string
  leftSubline?:     string
}

export function AuthLayout({
  children,
  leftEyebrow   = 'Intelligent career management',
  leftHeadline  = 'Your career, intelligently managed.',
  leftSubline   = 'Tailoring every CV, mapping every skill gap, and tracking every application.',
}: AuthLayoutProps) {
  return (
    <div className="min-h-screen flex">

      {/* ── Left: dark branded panel ─────────────────────────────────────────── */}
      <div
        className="hidden lg:flex lg:w-[46%] xl:w-[42%] flex-shrink-0 flex-col justify-between p-12 relative overflow-hidden h-screen sticky top-0"
        style={{ background: 'linear-gradient(155deg, #0F172A 0%, #0a1f1c 55%, #0F172A 100%)' }}
      >
        <TechPattern />

        {/* Top: wordmark */}
        <Link
          href="/"
          className="relative z-10 text-xl font-extrabold tracking-tight text-white hover:text-teal-400 transition-colors w-fit"
        >
          JobApply
        </Link>

        {/* Middle: hero copy */}
        <div className="relative z-10 space-y-6">
          <div className="space-y-3">
            <p className="text-xs font-semibold tracking-widest uppercase"
              style={{ color: TOKENS.color.primary }}>
              {leftEyebrow}
            </p>
            <h2 className="text-4xl font-extrabold text-white leading-tight tracking-tight">
              {leftHeadline}
            </h2>
            <p className="text-[15px] leading-relaxed max-w-sm" style={{ color: '#94a3b8' }}>
              {leftSubline}
            </p>
          </div>

          {/* Metric chips */}
          <div className="flex flex-wrap gap-3 pt-2">
            {METRICS.map(m => (
              <div
                key={m.label}
                className="flex flex-col px-4 py-2.5 rounded-xl"
                style={{
                  background: 'rgba(255,255,255,0.05)',
                  border:     '1px solid rgba(255,255,255,0.08)',
                }}
              >
                <span className="text-xl font-extrabold leading-none"
                  style={{ color: TOKENS.color.primary }}>
                  {m.value}
                </span>
                <span className="text-[11px] mt-0.5" style={{ color: '#64748b' }}>
                  {m.label}
                </span>
              </div>
            ))}
          </div>

          {/* Testimonial */}
          <blockquote
            className="relative z-10 rounded-2xl p-4 mt-2"
            style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.07)' }}
          >
            <p className="text-[13.5px] leading-relaxed italic" style={{ color: '#cbd5e1' }}>
              &ldquo;I was applying to jobs for 3 months with no response. JobApply got me 5 interviews
              in my first week.&rdquo;
            </p>
            <footer className="mt-3 flex items-center gap-2.5">
              <div
                className="w-7 h-7 rounded-full flex items-center justify-center text-[11px] font-bold text-white flex-shrink-0"
                style={{ background: TOKENS.color.primary }}
              >
                DL
              </div>
              <div>
                <p className="text-[12px] font-semibold text-white">Daniel Levi</p>
                <p className="text-[11px]" style={{ color: '#475569' }}>Product Manager, hired at Meta</p>
              </div>
            </footer>
          </blockquote>
        </div>

        {/* Bottom: copyright */}
        <p className="relative z-10 text-xs" style={{ color: '#334155' }}>
          JobApply &copy; {new Date().getFullYear()}
        </p>
      </div>

      {/* ── Right: form area ──────────────────────────────────────────────────── */}
      <div className="flex flex-1 flex-col overflow-y-auto bg-slate-50">
        {children}
      </div>
    </div>
  )
}
