'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchCrmBoard, moveCrmCard, deleteApplication } from '@/lib/api'
import type { CrmBoard, CrmCard, CrmColumn } from '@/lib/apiTypes'
import { TOKENS } from '@/lib/tokens'

// ── Stage visual config ───────────────────────────────────────────────────────

type StageKey = 'submitted' | 'phone screen' | 'technical' | 'interview' | 'offer' | 'rejected'

const STAGE_STYLE: Record<StageKey, { header: string; dot: string; count: string; dropBg: string }> = {
  'submitted':    { header: 'bg-teal-50   border-teal-200',   dot: 'bg-teal-500',    count: 'bg-teal-100   text-teal-700',   dropBg: 'bg-teal-100   border-teal-400'   },
  'phone screen': { header: 'bg-sky-50    border-sky-200',    dot: 'bg-sky-400',     count: 'bg-sky-100    text-sky-700',    dropBg: 'bg-sky-100    border-sky-400'    },
  'technical':    { header: 'bg-violet-50 border-violet-200', dot: 'bg-violet-500',  count: 'bg-violet-100 text-violet-700', dropBg: 'bg-violet-100 border-violet-400' },
  'interview':    { header: 'bg-amber-50  border-amber-200',  dot: 'bg-amber-500',   count: 'bg-amber-100  text-amber-700',  dropBg: 'bg-amber-100  border-amber-400'  },
  'offer':        { header: 'bg-emerald-50 border-emerald-200', dot: 'bg-emerald-500', count: 'bg-emerald-100 text-emerald-700', dropBg: 'bg-emerald-100 border-emerald-400' },
  'rejected':     { header: 'bg-rose-50   border-rose-200',   dot: 'bg-rose-400',    count: 'bg-rose-100   text-rose-700',   dropBg: 'bg-rose-100   border-rose-400'   },
}

function stageStyle(stage: string) {
  return STAGE_STYLE[stage as StageKey] ?? {
    header: 'bg-slate-50 border-slate-200',
    dot:    'bg-slate-400',
    count:  'bg-slate-100 text-slate-600',
    dropBg: 'bg-slate-200 border-slate-400',
  }
}

const ALL_STAGES: { key: StageKey; label: string }[] = [
  { key: 'submitted',    label: 'Submitted'    },
  { key: 'phone screen', label: 'Phone Screen' },
  { key: 'technical',    label: 'Technical'    },
  { key: 'interview',    label: 'Interview'    },
  { key: 'offer',        label: 'Offer'        },
  { key: 'rejected',     label: 'Rejected'     },
]

// ── Date formatter ─────────────────────────────────────────────────────────────
// Converts "2026-05-27 09:17 UTC" → "May 27, 09:17"

function formatCardDate(raw: string): string {
  if (!raw) return ''
  try {
    // Normalise "2026-05-27 09:17 UTC" → ISO by replacing space with T and removing " UTC"
    const iso = raw.replace(' UTC', 'Z').replace(' ', 'T')
    const d   = new Date(iso)
    if (isNaN(d.getTime())) return raw
    const month = d.toLocaleString('en-US', { month: 'short', timeZone: 'UTC' })
    const day   = d.getUTCDate()
    const hh    = String(d.getUTCHours()).padStart(2, '0')
    const mm    = String(d.getUTCMinutes()).padStart(2, '0')
    return `${month} ${day}, ${hh}:${mm}`
  } catch {
    return raw
  }
}

// ── Card Detail Modal ──────────────────────────────────────────────────────────

interface CardModalProps {
  card:         CrmCard
  currentStage: string
  onClose:      () => void
  onMove:       (toStage: string) => void
  moving:       boolean
  onDelete:     () => Promise<void>
  deleting:     boolean
}

function CardDetailModal({ card, currentStage, onClose, onMove, moving, onDelete, deleting }: CardModalProps) {
  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  const s = stageStyle(currentStage)

  return (
    <>
      {/* Backdrop — Meridian V2 §3.2 scrim */}
      <div
        className="fixed inset-0 z-40 bg-slate-900/55 backdrop-blur-[4px]"
        onClick={onClose}
      />

      {/* Panel */}
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none">
        <div
          className="w-full max-w-md rounded-2xl bg-white shadow-floating pointer-events-auto flex flex-col animate-modal-in"
          style={{ boxShadow: '0 24px 64px rgba(15,23,42,0.22)' }}
          onClick={e => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-start justify-between px-5 pt-5 pb-4 border-b border-slate-100">
            <div className="min-w-0 flex-1 pr-3">
              <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-1">
                {card.company}
              </p>
              <h3 className="text-[15px] font-bold text-slate-900 leading-snug">
                {card.title}
              </h3>
              <div className="flex items-center gap-2 mt-2">
                {/* Current stage badge */}
                <span className={`inline-flex items-center gap-1.5 text-[11px] font-semibold px-2.5 py-1 rounded-full ${
                  stageStyle(currentStage).count
                }`}>
                  <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} />
                  {ALL_STAGES.find(s => s.key === currentStage)?.label ?? currentStage}
                </span>
                {card.score > 0 && (
                  <span className="text-[11px] text-slate-400 font-medium">
                    {Math.round(card.score)}% ATS
                  </span>
                )}
              </div>
              {card.last_update && (
                <p className="text-[11px] text-slate-400 mt-1.5">
                  Updated: {formatCardDate(card.last_update)}
                </p>
              )}
            </div>
            <button
              onClick={onClose}
              className="shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition"
            >
              <svg width={14} height={14} viewBox="0 0 24 24" fill="none"
                stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
                <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>

          {/* Stage action buttons */}
          <div className="px-5 py-4">
            <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-3">
              Move to stage
            </p>
            <div className="grid grid-cols-3 gap-2">
              {ALL_STAGES.map(({ key, label }) => {
                const isCurrent = key === currentStage
                const s2        = stageStyle(key)
                return (
                  <button
                    key={key}
                    onClick={() => !isCurrent && onMove(key)}
                    disabled={moving || isCurrent}
                    className={`
                      flex items-center gap-1.5 h-8 px-2.5 rounded-lg text-[11.5px] font-medium
                      transition-all duration-100 border
                      ${isCurrent
                        ? `${s2.count} border-transparent cursor-default ring-2 ring-offset-1 ring-current/30`
                        : `bg-white text-slate-600 border-slate-200 hover:${s2.count} hover:border-transparent`
                      }
                      disabled:opacity-50
                    `}
                  >
                    <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${s2.dot}`} />
                    {label}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Footer */}
          <div className="px-5 pb-5 pt-1 flex items-center justify-between">
            <button
              onClick={() => {
                if (window.confirm(`Delete the application for "${card.title}"? This cannot be undone.`)) {
                  void onDelete()
                }
              }}
              disabled={deleting}
              className="h-8 px-3 rounded-lg text-[12.5px] font-medium border transition disabled:opacity-50 text-rose-600 border-rose-200 hover:bg-rose-50"
            >
              {deleting ? 'Deleting…' : 'Delete'}
            </button>
            <button
              onClick={onClose}
              className="h-8 px-4 rounded-lg text-[12.5px] font-medium text-slate-600 border border-slate-200 hover:bg-slate-50 transition"
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </>
  )
}

// ── Card ──────────────────────────────────────────────────────────────────────

function KanbanCard({
  card,
  currentStage,
  onDragStart,
  isMoving,
  onOpen,
  onQuickMove,
}: {
  card:         CrmCard
  currentStage: string
  onDragStart:  (card: CrmCard) => void
  isMoving:     boolean
  onOpen:       (card: CrmCard) => void
  onQuickMove:  (card: CrmCard, toStage: string) => void
}) {
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  // Close the quick-move menu on outside click or Escape
  useEffect(() => {
    if (!menuOpen) return
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false)
    }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenuOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [menuOpen])

  return (
    <div
      draggable
      onDragStart={e => { e.stopPropagation(); onDragStart(card) }}
      onClick={() => onOpen(card)}
      className={`
        group relative bg-white rounded-2xl border border-slate-100
        hover:border-slate-200 hover:shadow-elevation-2
        transition-all duration-150 cursor-pointer active:cursor-grabbing
        select-none p-3.5
        ${isMoving ? 'opacity-40 scale-95' : ''}
      `}
    >
      {/* Title + quick-move menu trigger */}
      <div className="flex items-start justify-between gap-2 mb-2">
        <p className="text-[12px] font-semibold text-slate-900 leading-snug line-clamp-2 flex-1">
          {card.title}
        </p>
        <div className="relative shrink-0" ref={menuRef}>
          <button
            onClick={e => { e.stopPropagation(); setMenuOpen(v => !v) }}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            aria-label="Move to stage"
            title="Move to…"
            className={`mt-0.5 w-5 h-6 flex items-center justify-center rounded transition-colors ${
              menuOpen
                ? 'text-slate-600 bg-slate-100'
                : 'text-slate-300 group-hover:text-slate-400 hover:!text-slate-600 hover:bg-slate-100'
            }`}
          >
            <svg width={10} height={14} viewBox="0 0 10 14" fill="currentColor">
              <circle cx="2.5" cy="2.5"  r="1.5" />
              <circle cx="7.5" cy="2.5"  r="1.5" />
              <circle cx="2.5" cy="7"    r="1.5" />
              <circle cx="7.5" cy="7"    r="1.5" />
              <circle cx="2.5" cy="11.5" r="1.5" />
              <circle cx="7.5" cy="11.5" r="1.5" />
            </svg>
          </button>

          {/* Quick "Move to…" dropdown — same mutation as drag-and-drop (doMove) */}
          {menuOpen && (
            <div
              role="menu"
              onClick={e => e.stopPropagation()}
              className="absolute right-0 top-7 z-30 w-44 rounded-xl bg-white/85 backdrop-blur-xl border border-white/60 shadow-floating py-1"
            >
              <p className="px-3 pt-1.5 pb-1 text-[9.5px] font-bold uppercase tracking-widest text-slate-400">
                Move to…
              </p>
              {ALL_STAGES.map(({ key, label }) => {
                const isCurrent = key === currentStage
                const s = stageStyle(key)
                return (
                  <button
                    key={key}
                    role="menuitem"
                    disabled={isCurrent}
                    onClick={e => {
                      e.stopPropagation()
                      setMenuOpen(false)
                      onQuickMove(card, key)
                    }}
                    className={`w-full flex items-center gap-2 px-3 py-1.5 text-[11.5px] text-left transition ${
                      isCurrent ? 'text-slate-300 cursor-default' : 'text-slate-600 hover:bg-slate-50'
                    }`}
                  >
                    <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${s.dot}`} />
                    {label}
                    {isCurrent && (
                      <span className="ml-auto text-[9px] font-semibold text-slate-300">CURRENT</span>
                    )}
                  </button>
                )
              })}
            </div>
          )}
        </div>
      </div>

      <p className="text-[11px] font-medium text-slate-500 mb-2 truncate">
        {card.company}
      </p>

      <div className="flex items-center justify-between">
        <span className="text-[10px] text-slate-400 truncate max-w-[70%]">
          {formatCardDate(card.last_update)}
        </span>
        {card.score > 0 && (
          <span className="text-[10px] font-semibold text-slate-500 shrink-0">
            {Math.round(card.score)}%
          </span>
        )}
      </div>
    </div>
  )
}

// ── Column ────────────────────────────────────────────────────────────────────

function KanbanColumn({
  col,
  movingId,
  onDragStart,
  onDrop,
  onOpenCard,
  onQuickMove,
}: {
  col:         CrmColumn
  movingId:    string | null
  onDragStart: (card: CrmCard) => void
  onDrop:      (targetStage: string) => void
  onOpenCard:  (card: CrmCard, stage: string) => void
  onQuickMove: (card: CrmCard, toStage: string) => void
}) {
  const [isDragOver, setIsDragOver] = useState(false)
  const s = stageStyle(col.stage)

  return (
    <div
      className="flex flex-col w-[260px] min-w-[240px] shrink-0"
      onDragOver={e => { e.preventDefault(); setIsDragOver(true) }}
      onDragLeave={() => setIsDragOver(false)}
      onDrop={() => { setIsDragOver(false); onDrop(col.stage) }}
    >
      {/* Column header */}
      <div className={`
        flex items-center gap-2 px-3 py-2.5 rounded-t-xl border-x border-t
        ${s.header}
      `}>
        <span className={`w-2 h-2 rounded-full shrink-0 ${s.dot}`} />
        <span className="text-[12px] font-semibold text-slate-700 flex-1">{col.label}</span>
        <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${s.count}`}>
          {col.cards.length}
        </span>
      </div>

      {/* Cards container — scrolls vertically within the column so a long
          pipeline stage never stretches the whole board */}
      <div
        className={`
          flex-1 min-h-[400px] max-h-[70vh] overflow-y-auto rounded-b-xl border border-t-0
          transition-all duration-150
          flex flex-col gap-2 p-2
          ${isDragOver
            ? `${s.dropBg} border-dashed`
            : 'bg-slate-50 border-slate-200'
          }
        `}
      >
        {col.cards.length === 0 && !isDragOver && (
          <p className="text-[11px] text-slate-400 italic text-center pt-8 px-2">
            No applications here
          </p>
        )}
        {col.cards.map(card => (
          <KanbanCard
            key={card.application_id}
            card={card}
            currentStage={col.stage}
            onDragStart={onDragStart}
            isMoving={movingId === card.application_id}
            onOpen={c => onOpenCard(c, col.stage)}
            onQuickMove={onQuickMove}
          />
        ))}
        {isDragOver && (
          <div className={`
            h-14 rounded-lg border-2 border-dashed flex items-center justify-center
            ${s.dropBg} border-current
          `}>
            <span className="text-[11px] font-medium text-slate-600">Drop here</span>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export function ApplicationsKanban({ onRefresh }: { onRefresh?: () => void }) {
  const [board,    setBoard]    = useState<CrmBoard | null>(null)
  const [loading,  setLoading]  = useState(true)
  const [error,    setError]    = useState<string | null>(null)
  const [movingId, setMovingId] = useState<string | null>(null)
  // Toast with an optional Undo action (used by the move-success toast)
  const [toast,    setToast]    = useState<{ message: string; undo?: () => void } | null>(null)

  // Modal state
  const [modalCard,  setModalCard]  = useState<CrmCard | null>(null)
  const [modalStage, setModalStage] = useState<string>('')
  const [modalMoving, setModalMoving] = useState(false)
  const [modalDeleting, setModalDeleting] = useState(false)

  const draggedCard = useRef<CrmCard | null>(null)

  const load = useCallback(async () => {
    try {
      const data = await fetchCrmBoard()
      setBoard(data)
      setError(null)
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  // Toast auto-dismiss — actionable toasts (Undo) linger longer so the user
  // has time to notice and click; plain confirmations stay short.
  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), toast.undo ? 5000 : 2500)
    return () => clearTimeout(t)
  }, [toast])

  const handleDragStart = useCallback((card: CrmCard) => {
    draggedCard.current = card
  }, [])

  // Ref mirror of doMove so the Undo closure inside a toast can call the
  // latest version without doMove depending on itself (useCallback can't
  // self-reference).
  const doMoveRef = useRef<
    ((card: CrmCard, targetStage: string, opts?: { isUndo?: boolean }) => Promise<void>) | null
  >(null)

  const doMove = useCallback(async (
    card: CrmCard,
    targetStage: string,
    opts: { isUndo?: boolean } = {},
  ) => {
    if (!board) return

    // Capture the card's origin column BEFORE the optimistic update — this is
    // what Undo reverses to. Dropping a card onto its own column is a no-op.
    const previousStage = board.columns
      .find(col => col.cards.some(c => c.application_id === card.application_id))
      ?.stage ?? null
    if (previousStage === targetStage) return

    // Optimistic update
    setBoard(prev => {
      if (!prev) return prev
      return {
        columns: prev.columns.map(col => ({
          ...col,
          cards: col.stage === targetStage
            ? [...col.cards.filter(c => c.application_id !== card.application_id), { ...card }]
            : col.cards.filter(c => c.application_id !== card.application_id),
        })),
      }
    })

    setMovingId(card.application_id)
    try {
      await moveCrmCard(card.application_id, targetStage)
      const label = ALL_STAGES.find(s => s.key === targetStage)?.label ?? targetStage
      if (opts.isUndo) {
        // Terminal confirmation — no undo-of-undo chains.
        setToast({ message: `Move undone — back in ${label}` })
      } else {
        setToast({
          message: `Moved to ${label}`,
          // Reverse mutation: same doMove path (optimistic update + API +
          // failure rollback), from the new stage back to the origin.
          undo: previousStage
            ? () => { void doMoveRef.current?.(card, previousStage, { isUndo: true }) }
            : undefined,
        })
      }
      onRefresh?.()
    } catch {
      setToast({ message: 'Move failed — reloading…' })
      await load()
    } finally {
      setMovingId(null)
    }
  }, [board, load, onRefresh])

  doMoveRef.current = doMove

  const handleDrop = useCallback(async (targetStage: string) => {
    const card = draggedCard.current
    draggedCard.current = null
    if (!card) return
    await doMove(card, targetStage)
  }, [doMove])

  const handleOpenCard = useCallback((card: CrmCard, stage: string) => {
    setModalCard(card)
    setModalStage(stage)
  }, [])

  const handleModalMove = useCallback(async (toStage: string) => {
    if (!modalCard) return
    setModalMoving(true)
    // Update the modal's current stage immediately for visual feedback
    const prevStage = modalStage
    setModalStage(toStage)
    try {
      await doMove(modalCard, toStage)
    } catch {
      setModalStage(prevStage)
    } finally {
      setModalMoving(false)
    }
  }, [modalCard, modalStage, doMove])

  const handleModalDelete = useCallback(async () => {
    if (!modalCard || !board) return
    const card = modalCard
    setModalDeleting(true)
    // Optimistic removal from the board
    setBoard(prev => prev && {
      columns: prev.columns.map(col => ({
        ...col,
        cards: col.cards.filter(c => c.application_id !== card.application_id),
      })),
    })
    try {
      await deleteApplication(card.application_id)
      setToast({ message: `Deleted "${card.title}"` })
      setModalCard(null)
      onRefresh?.()
    } catch {
      setToast({ message: 'Delete failed — reloading…' })
      await load()
    } finally {
      setModalDeleting(false)
    }
  }, [modalCard, board, load, onRefresh])

  // ── States ────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-sm text-slate-400">
        Loading board…
      </div>
    )
  }

  if (error || !board) {
    return (
      <div className="flex items-center justify-center h-64 text-sm" style={{ color: TOKENS.color.danger }}>
        Failed to load board. {error}
      </div>
    )
  }

  const totalCards = board.columns.reduce((n, c) => n + c.cards.length, 0)

  return (
    <div className="relative">
      {/* Refresh button */}
      <div className="flex items-center justify-between mb-4">
        <p className="text-[12px] text-slate-500">
          {totalCards} application{totalCards !== 1 ? 's' : ''} in pipeline
          <span className="ml-2 text-slate-400">· drag cards between columns or click to update status</span>
        </p>
        <button
          onClick={load}
          className="text-[12px] text-slate-500 hover:text-slate-800 transition flex items-center gap-1.5"
        >
          <svg width={12} height={12} viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="23 4 23 10 17 10" />
            <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
          </svg>
          Refresh
        </button>
      </div>

      {/* Board — nowrap + horizontal scroll so trailing columns (e.g. Rejected)
          are always reachable; pb-4 keeps the scrollbar off the column cards */}
      <div className="flex flex-nowrap gap-3 overflow-x-auto pb-4">
        {board.columns.map(col => (
          <KanbanColumn
            key={col.stage}
            col={col}
            movingId={movingId}
            onDragStart={handleDragStart}
            onDrop={handleDrop}
            onOpenCard={handleOpenCard}
            onQuickMove={doMove}
          />
        ))}
      </div>

      {/* Card detail modal */}
      {modalCard && (
        <CardDetailModal
          card={modalCard}
          currentStage={modalStage}
          onClose={() => setModalCard(null)}
          onMove={handleModalMove}
          moving={modalMoving}
          onDelete={handleModalDelete}
          deleting={modalDeleting}
        />
      )}

      {/* Toast — with actionable Undo for card moves */}
      {toast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 px-4 py-2.5 rounded-xl shadow-floating text-[13px] font-medium text-white"
          style={{ background: TOKENS.color.success }}>
          {toast.message}
          {toast.undo && (
            <button
              onClick={() => {
                const undo = toast.undo
                setToast(null)   // dismiss immediately; the undo move raises its own toast
                undo?.()
              }}
              className="shrink-0 h-6 px-2.5 rounded-lg bg-white/20 hover:bg-white/30 text-white text-[11.5px] font-semibold transition active:scale-95"
            >
              Undo
            </button>
          )}
        </div>
      )}
    </div>
  )
}
