'use client'
import { useEffect, useRef } from 'react'
import { TOKENS } from '@/lib/tokens'
import type { Job } from '@/lib/data'
import { XIcon } from './icons'

// ── Report text parser ────────────────────────────────────────────────────────

type Block =
  | { type: 'h1';      text: string }
  | { type: 'subtitle'; text: string }
  | { type: 'divider' }
  | { type: 'section-heading'; text: string }
  | { type: 'emoji-heading'; text: string }  // green/orange circle section headers (AI Analysis)
  | { type: 'bullet'; text: string }         // bullet point items (U+2022)
  | { type: 'stars';   text: string }
  | { type: 'meta';    text: string }   // indented key: value lines
  | { type: 'numbered'; n: number; text: string }
  | { type: 'body';    text: string }
  | { type: 'spacer' }

function parseReport(raw: string): Block[] {
  const lines = raw.split('\n')
  const blocks: Block[] = []

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const trimmed = line.trim()

    if (!trimmed) {
      if (blocks.length && blocks[blocks.length - 1].type !== 'spacer') {
        blocks.push({ type: 'spacer' })
      }
      continue
    }

    // H1: starts with #
    if (trimmed.startsWith('# ')) {
      blocks.push({ type: 'h1', text: trimmed.slice(2) })
      continue
    }

    // Subtitle: starts with — and ends with —
    if (trimmed.startsWith('—') && trimmed.endsWith('—')) {
      blocks.push({ type: 'subtitle', text: trimmed.replace(/^—\s*/, '').replace(/\s*—$/, '') })
      continue
    }

    // Divider: ━ repeated 10+ times
    if (/^━{10,}/.test(trimmed)) {
      blocks.push({ type: 'divider' })
      continue
    }

    // Section heading: ALL CAPS + no lowercase + 3+ chars
    // (but not star lines)
    if (
      !trimmed.startsWith('★') &&
      trimmed === trimmed.toUpperCase() &&
      trimmed.length >= 3 &&
      /[A-Z]/.test(trimmed)
    ) {
      blocks.push({ type: 'section-heading', text: trimmed })
      continue
    }

    // Stars line: starts with ★ (indented or not)
    if (trimmed.startsWith('★')) {
      blocks.push({ type: 'stars', text: trimmed })
      continue
    }

    // Emoji section headers — match via codePointAt to avoid raw 4-byte emoji
    // in eval() strings (webpack eval-source-map crash fix).
    // U+1F7E2 = 🟢 green circle, U+1F7E0 = 🟠 orange circle
    {
      const firstCp = trimmed.codePointAt(0)
      if (firstCp === 0x1F7E2 || firstCp === 0x1F7E0) {
        blocks.push({ type: 'emoji-heading', text: trimmed })
        continue
      }
    }

    // Bullet lines starting with • (U+2022 BULLET)
    if (trimmed.codePointAt(0) === 0x2022) {
      blocks.push({ type: 'bullet', text: trimmed.slice(1).trim() })
      continue
    }

    // Numbered list: starts with digit(s) followed by .
    const numMatch = trimmed.match(/^(\d+)\.\s+(.+)/)
    if (numMatch) {
      blocks.push({ type: 'numbered', n: parseInt(numMatch[1]), text: numMatch[2] })
      continue
    }

    // Meta line: indented (starts with 2+ spaces in original) + contains ":"
    if (line.startsWith('  ') && trimmed.includes(':') && trimmed.length < 160) {
      blocks.push({ type: 'meta', text: trimmed })
      continue
    }

    blocks.push({ type: 'body', text: trimmed })
  }

  return blocks
}

// ── Block renderers ───────────────────────────────────────────────────────────

function renderBlock(block: Block, idx: number) {
  switch (block.type) {
    case 'h1':
      return (
        <h1 key={idx} className="text-[18px] font-bold text-slate-900 leading-snug mt-2">
          {block.text}
        </h1>
      )

    case 'subtitle':
      return (
        <p key={idx} className="text-[12.5px] text-slate-400 font-medium tracking-wide mt-1">
          {block.text}
        </p>
      )

    case 'divider':
      return <hr key={idx} className="border-slate-200 my-5" />

    case 'section-heading':
      return (
        <h2 key={idx} className="text-[11px] font-bold tracking-widest mt-1 mb-3"
          style={{ color: TOKENS.color.muted }}>
          {block.text}
        </h2>
      )

    case 'stars': {
      // Parse stars out of the label (e.g. "★★★★★  LEADERSHIP & PEOPLE MANAGEMENT")
      const starMatch = block.text.match(/^(★+(?:☆*))\s+(.+)/)
      if (starMatch) {
        return (
          <div key={idx} className="flex items-center gap-2 mt-4 mb-1">
            <span className="text-[14px] tracking-tighter" style={{ color: TOKENS.color.warn }}>
              {starMatch[1]}
            </span>
            <span className="text-[13px] font-semibold text-slate-800">{starMatch[2]}</span>
          </div>
        )
      }
      return <p key={idx} className="text-[13px] text-slate-700">{block.text}</p>
    }

    case 'meta': {
      const colonIdx = block.text.indexOf(':')
      if (colonIdx > -1) {
        const label = block.text.slice(0, colonIdx).trim()
        const value = block.text.slice(colonIdx + 1).trim()
        return (
          <div key={idx} className="flex gap-2 text-[12.5px] leading-relaxed pl-4 my-0.5">
            <span className="text-slate-400 shrink-0 min-w-[100px]">{label}</span>
            <span className="text-slate-700">{value}</span>
          </div>
        )
      }
      return <p key={idx} className="text-[12.5px] text-slate-600 pl-4">{block.text}</p>
    }

    case 'numbered':
      return (
        <div key={idx} className="flex gap-3 text-[13px] leading-relaxed text-slate-700 my-1.5">
          <span className="shrink-0 w-5 text-right font-semibold"
            style={{ color: TOKENS.color.primary }}>
            {block.n}.
          </span>
          <span>{block.text}</span>
        </div>
      )

    case 'emoji-heading':
      return (
        <p key={idx} className="text-[13px] font-semibold text-slate-800 mt-4 first:mt-0">
          {block.text}
        </p>
      )

    case 'bullet':
      return (
        <div key={idx} className="flex gap-2 text-[12.5px] leading-relaxed text-slate-600 pl-4 my-0.5">
          <span className="shrink-0 mt-[3px]" style={{ color: TOKENS.color.muted }}>•</span>
          <span>{block.text}</span>
        </div>
      )

    case 'body':
      return (
        <p key={idx} className="text-[13px] leading-relaxed text-slate-700">
          {block.text}
        </p>
      )

    case 'spacer':
      return <div key={idx} className="h-2" />

    default:
      return null
  }
}

// ── Drawer component ──────────────────────────────────────────────────────────

interface ReportDrawerProps {
  job:     Job | null
  onClose: () => void
}

export function ReportDrawer({ job, onClose }: ReportDrawerProps) {
  const scrollRef = useRef<HTMLDivElement>(null)

  // Reset scroll position when a different job is opened
  useEffect(() => {
    if (job && scrollRef.current) scrollRef.current.scrollTop = 0
  }, [job?.id])

  // Close on Escape
  useEffect(() => {
    if (!job) return
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [job, onClose])

  const isOpen = !!job

  return (
    <>
      {/* Backdrop — Meridian V2 §3.2 scrim */}
      <div
        onClick={onClose}
        className="fixed inset-0 z-40 transition-opacity duration-300"
        style={{
          background:    'rgba(15,23,42,0.55)',
          backdropFilter: 'blur(4px)',
          opacity:       isOpen ? 1 : 0,
          pointerEvents: isOpen ? 'auto' : 'none',
        }}
      />

      {/* Drawer panel */}
      <div
        className="fixed top-0 right-0 bottom-0 z-50 flex flex-col bg-white"
        style={{
          width:      'min(600px, 100vw)',
          boxShadow:  '-4px 0 24px rgba(15,23,42,0.10)',
          transform:  isOpen ? 'translateX(0)' : 'translateX(100%)',
          transition: 'transform 300ms cubic-bezier(0.32,0,0.15,1)',
        }}
      >
        {/* Sticky header */}
        <div className="shrink-0 px-6 py-4 border-b border-slate-100 flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-[11px] font-semibold tracking-widest uppercase"
              style={{ color: TOKENS.color.muted }}>
              Analysis Report
            </p>
            {job && (
              <>
                <h2 className="text-[15px] font-bold text-slate-900 leading-tight mt-0.5 truncate">
                  {job.title}
                </h2>
                <p className="text-[12.5px] text-slate-500 mt-0.5">
                  {job.company}
                  {job.location ? ` · ${job.location}` : ''}
                </p>
              </>
            )}
          </div>
          <div className="flex items-center gap-3 shrink-0 mt-0.5">
            {job && (
              <div className="flex items-center gap-1.5 px-3 h-7 rounded-full text-[12px] font-bold"
                style={{
                  background: 'oklch(0.96 0.02 255)',
                  color:      TOKENS.color.primary,
                }}>
                {job.score}/100
              </div>
            )}
            <button
              onClick={onClose}
              className="h-8 w-8 flex items-center justify-center rounded-full text-slate-400 hover:text-slate-900 hover:bg-slate-100 transition"
              aria-label="Close"
            >
              <XIcon s={16} />
            </button>
          </div>
        </div>

        {/* Scrollable body */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-5">
          {!job ? null : !job.whyRon ? (
            <div className="flex flex-col items-center justify-center h-full gap-3 text-center">
              <p className="text-[13px] text-slate-500">
                No analysis report available for this job.
              </p>
              <p className="text-[12px] text-slate-400">
                Run the analysis pipeline on this URL to generate a full recruiter brief.
              </p>
            </div>
          ) : (
            <div className="space-y-0">
              {parseReport(job.whyRon).map((block, i) => renderBlock(block, i))}
            </div>
          )}
        </div>
      </div>
    </>
  )
}
