'use client'
import { useState, useEffect } from 'react'
import { useI18n } from '@/contexts/I18nContext'
import { StatusDot } from './ui/StatusDot'


export function Footer() {
  const F = useI18n().t.footer
  const [toast, setToast] = useState(false)

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(false), 3500)
    return () => clearTimeout(t)
  }, [toast])

  function showComingSoon(e: React.MouseEvent) {
    e.preventDefault()
    setToast(true)
  }

  return (
    <>
      {toast && (
        // Dark glass (§3.2) — this toast already committed to a dark theme.
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-[200] flex items-center gap-3 bg-[#0A1F1C]/80 backdrop-blur-xl border border-white/10 text-white text-[13px] font-medium px-5 py-3 rounded-xl shadow-floating max-w-sm text-center animate-modal-in">
          <span>🚧</span>
          <span>{F.coming_soon}</span>
        </div>
      )}
      {/* Full-bleed divider; inner container aligns to the same content
          boundary as <main> (max-w-content mx-auto w-full px-6). */}
      <footer className="border-t border-slate-100 mt-10">
        <div className="max-w-content mx-auto w-full px-6 py-6 flex items-center justify-between text-[11.5px] text-slate-400">
          <div className="inline-flex items-center gap-2">
            <span>v1.3.0</span>
            <span className="text-slate-300">·</span>
            <span className="inline-flex items-center gap-1.5">
              <StatusDot tone="success" pulse size={5} /> {F.operational}
            </span>
          </div>
          <div className="inline-flex items-center gap-4">
            <a href="#" onClick={showComingSoon} className="hover:text-slate-700">{F.help}</a>
            <a href="#" onClick={showComingSoon} className="hover:text-slate-700">{F.privacy}</a>
            <a href="#" onClick={showComingSoon} className="hover:text-slate-700">{F.contact}</a>
            <a href="/accessibility" className="hover:text-slate-700">{F.accessibility}</a>
          </div>
        </div>
      </footer>
    </>
  )
}
