'use client'
// Ariel's command bar (design direction 4, Ron 27.11). ⌘K (Ctrl+K) from
// anywhere in the app, or the header chip: a question field and up to four
// requests worth making now, built from the user's own matches and
// applications. Choosing one, or typing, opens the Ariel chat with that
// request sent; the work and its progress happen there, not here.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useI18n } from '@/contexts/I18nContext'
import { useChat } from '@/contexts/ChatContext'
import { fetchApplicationsList, type AppListItem } from '@/lib/api'
import type { ApiFeedJob } from '@/lib/apiTypes'
import { buildSuggestions, type Suggestion } from '@/lib/arielSuggestions'
import { stageLabel } from '@/lib/stages'

/** Dispatched on window to open the bar from elsewhere (the header chip). */
export const ARIEL_COMMAND_EVENT = 'ja:ariel-command'

const fill = (s: string, v: Record<string, string>) => s.replace(/\{(\w+)\}/g, (m, k) => v[k] ?? m)

export function ArielCommand({ jobs }: { jobs: ApiFeedJob[] }) {
  const { t } = useI18n()
  const C = t.ariel.command
  const quick = t.ariel.quick_actions
  const { openChat, isOpen: chatOpen } = useChat()

  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [sel, setSel] = useState(0)
  const [apps, setApps] = useState<AppListItem[]>([])
  const input = useRef<HTMLInputElement>(null)
  const returnFocus = useRef<HTMLElement | null>(null)

  const show = useCallback(() => {
    returnFocus.current = document.activeElement as HTMLElement | null
    setQ(''); setSel(0); setOpen(true)
    // Applications feed two of the suggestions; without them the bar still
    // works, so a failure only means fewer suggestions.
    fetchApplicationsList().then(setApps).catch(() => {})
  }, [])
  const hide = useCallback(() => {
    setOpen(false)
    returnFocus.current?.focus?.()
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === 'k') {
        if (chatOpen) return
        e.preventDefault()
        if (open) hide(); else show()
      }
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener(ARIEL_COMMAND_EVENT, show)
    return () => { window.removeEventListener('keydown', onKey); window.removeEventListener(ARIEL_COMMAND_EVENT, show) }
  }, [open, chatOpen, show, hide])

  useEffect(() => { if (open) input.current?.focus() }, [open])

  const suggestions = useMemo(() => buildSuggestions(jobs, apps, quick.length), [jobs, apps, quick.length])

  const text = useCallback((s: Suggestion) => {
    if (s.kind === 'quick') {
      const a = quick[s.index]
      return { title: a.label, sub: a.desc, topic: a.prompt }
    }
    const v: Record<string, string> = { title: s.title, company: s.company }
    if (s.kind === 'cv') v.score = s.score.toFixed(1)
    if (s.kind === 'prep') v.stage = stageLabel(s.stage, t.applications.stages)
    if (s.kind === 'follow') v.days = String(s.days)
    return { title: fill(C[`${s.kind}_title`], v), sub: fill(C[`${s.kind}_sub`], v), topic: fill(C[`${s.kind}_topic`], v) }
  }, [C, quick, t.applications.stages])

  const typed = q.trim()
  // With text typed, the first row asks it; the suggestions stay below.
  const rows: { key: string; title: string; sub?: string; run: () => void; tile: 'ask' | Suggestion['kind'] }[] = [
    ...(typed ? [{ key: 'ask', title: typed, sub: C.ask, tile: 'ask' as const, run: () => go({ topic: typed }) }] : []),
    ...suggestions.map(s => {
      const x = text(s)
      return {
        key: s.id, title: x.title, sub: x.sub, tile: s.kind,
        run: () => go(s.kind === 'quick' ? { topic: x.topic } : { topic: x.topic, jobTitle: s.title, company: s.company }),
      }
    }),
  ]
  const active = Math.min(sel, Math.max(rows.length - 1, 0))

  function go(ctx: { topic: string; jobTitle?: string; company?: string }) {
    setOpen(false)
    openChat(ctx)
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-[60] flex justify-center px-4 pt-[12vh]" onMouseDown={e => { if (e.target === e.currentTarget) hide() }}>
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-slate-900/20"
        style={{ backgroundImage: 'radial-gradient(700px 420px at 50% 25%, rgba(54,122,142,0.16), transparent 70%)' }}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={C.label}
        className="animate-ja-command-in relative h-fit w-full max-w-[640px] overflow-hidden rounded-[28px] border border-white/70 bg-white/[0.86] backdrop-blur-2xl backdrop-saturate-150 shadow-[inset_0_1px_0_rgba(255,255,255,0.9),0_2px_6px_rgba(15,23,42,0.06),0_30px_60px_-20px_rgba(22,78,92,0.35),0_70px_120px_-50px_rgba(22,78,92,0.45)]"
        onKeyDown={e => {
          if (e.key === 'Escape') { e.preventDefault(); hide() }
          else if (e.key === 'ArrowDown') { e.preventDefault(); setSel(i => (Math.min(i, rows.length - 1) + 1) % rows.length) }
          else if (e.key === 'ArrowUp') { e.preventDefault(); setSel(i => (Math.min(i, rows.length - 1) - 1 + rows.length) % rows.length) }
          else if (e.key === 'Enter' && !e.nativeEvent.isComposing) { e.preventDefault(); rows[active]?.run() }
        }}
      >
        <div className="flex items-center gap-3.5 border-b border-slate-200/80 px-5 py-4 sm:px-6">
          <span
            aria-hidden
            className="h-8 w-8 shrink-0 rounded-full"
            style={{ background: 'radial-gradient(circle at 35% 30%, #8CC4D3, #367A8E 55%, #1F5F70)', boxShadow: '0 0 0 5px rgba(54,122,142,0.12), 0 8px 20px -6px rgba(54,122,142,0.6)' }}
          />
          <input
            ref={input}
            value={q}
            onChange={e => { setQ(e.target.value); setSel(0) }}
            placeholder={C.placeholder}
            aria-label={C.label}
            role="combobox"
            aria-expanded
            aria-controls="ariel-command-list"
            aria-activedescendant={rows[active] ? `ariel-cmd-${rows[active].key}` : undefined}
            dir="auto"
            className="min-w-0 flex-1 bg-transparent text-[18px] sm:text-[20px] font-medium tracking-[-0.01em] text-slate-900 placeholder:text-slate-400 focus:outline-none"
          />
          <kbd className="hidden sm:inline rounded-lg bg-slate-100 px-2 py-1 text-[12px] text-slate-500">esc</kbd>
        </div>

        <div className="max-h-[52vh] overflow-y-auto p-2.5">
          {suggestions.length > 0 && <p className="px-3.5 pb-1.5 pt-2 text-[13px] text-slate-500">{C.suggested}</p>}
          <ul id="ariel-command-list" role="listbox" aria-label={C.label}>
            {rows.map((r, i) => (
              <li
                key={r.key}
                id={`ariel-cmd-${r.key}`}
                role="option"
                aria-selected={i === active}
                onMouseMove={() => setSel(i)}
                onClick={r.run}
                className={`animate-ja-rise flex cursor-pointer items-center gap-3.5 rounded-2xl px-3.5 py-3 ${i === active ? 'bg-[rgba(54,122,142,0.10)]' : ''}`}
                style={{ animationDelay: `${60 + i * 40}ms` }}
              >
                <Tile kind={r.tile} />
                <span className="min-w-0 flex-1">
                  <span dir="auto" className="block truncate text-[15px] sm:text-[16px] font-semibold text-slate-900">{r.title}</span>
                  {r.sub && <span dir="auto" className="block truncate text-[13px] text-slate-500">{r.sub}</span>}
                </span>
                {i === active && <span aria-hidden className="text-[13px] text-slate-400">↵</span>}
              </li>
            ))}
          </ul>
        </div>

        <div className="flex justify-between gap-3 border-t border-slate-200/80 px-5 py-3 sm:px-6 text-[12px] text-slate-400">
          <span>{C.footer}</span>
          <span className="hidden sm:inline whitespace-nowrap">{C.hint}</span>
        </div>
      </div>
    </div>
  )
}

const TILE_ICON: Record<string, string> = { ask: '↗', cv: 'CV', prep: '?', follow: '↻', quick: '✦' }

function Tile({ kind }: { kind: string }) {
  return (
    <span
      aria-hidden
      className="grid h-9 w-9 shrink-0 place-items-center rounded-[11px] text-[13px] font-bold text-white"
      style={{ background: kind === 'cv' ? 'linear-gradient(135deg,#14B8A6,#0F766E)' : 'linear-gradient(135deg,#4592A6,#2A6577)' }}
    >
      {TILE_ICON[kind]}
    </span>
  )
}

/** The header's entry point; shows the shortcut for this keyboard. */
export function ArielCommandChip() {
  const { t } = useI18n()
  const [mac, setMac] = useState(true)
  useEffect(() => { setMac(/Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent)) }, [])
  return (
    <button
      onClick={() => window.dispatchEvent(new Event(ARIEL_COMMAND_EVENT))}
      aria-label={t.ariel.command.open_label}
      aria-keyshortcuts={mac ? 'Meta+K' : 'Control+K'}
      className="hidden md:inline-flex h-9 items-center gap-2 rounded-full bg-[rgba(54,122,142,0.11)] px-3.5 text-[13.5px] font-medium text-ja-aiInk transition-colors duration-ja-ui hover:bg-[rgba(54,122,142,0.17)] active:scale-[0.97]"
    >
      <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: 'linear-gradient(135deg,#4592A6,#2A6577)' }} />
      {t.ariel.command.label}
      <kbd className="font-sans text-[11px] text-[#367A8E]">{mac ? '⌘K' : 'Ctrl K'}</kbd>
    </button>
  )
}
