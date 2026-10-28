'use client'
import { useCallback, useRef, useState } from 'react'
import { useI18n } from '@/contexts/I18nContext'
import { useAuth } from '@/contexts/AuthContext'
import { useChat } from '@/contexts/ChatContext'
import { useDialogA11y } from '@/hooks/useDialogA11y'
import {
  CONTACT_EMAIL, CONTACT_PHONE_DISPLAY, CONTACT_PHONE_E164, CONTACT_WHATSAPP_URL,
} from '@/lib/contact'
import { StatusDot } from './ui/StatusDot'

// Help and Contact used to show a "coming soon" toast. Help now opens Ariel
// (the in-app assistant) for a signed-in user; a signed-out visitor, who has
// no Ariel, gets the contact details instead. Contact shows the real email,
// phone and WhatsApp (lib/contact.ts).

function ContactDialog({ onClose }: { onClose: () => void }) {
  const F = useI18n().t.footer
  const ref = useRef<HTMLDivElement>(null)
  useDialogA11y(onClose, ref)
  const row = 'flex items-center justify-between gap-3 min-h-[44px] rounded-xl border border-slate-200 px-4 text-[14px] text-slate-800 hover:bg-slate-50'
  return (
    <div className="fixed inset-0 z-[200] flex items-end sm:items-center justify-center p-4 bg-slate-900/40" onClick={onClose}>
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby="contact-dialog-title"
        tabIndex={-1}
        onClick={e => e.stopPropagation()}
        className="w-full max-w-sm rounded-2xl bg-white p-5 border border-slate-100"
        style={{ boxShadow: '0 1px 2px rgba(15,23,42,.08), 0 12px 32px rgba(15,23,42,.18)' }}
      >
        <div className="flex items-center justify-between mb-1">
          <h2 id="contact-dialog-title" className="text-[16px] font-bold text-slate-900">{F.contact_title}</h2>
          <button type="button" onClick={onClose} aria-label={F.contact_close}
            className="h-11 w-11 -me-2 rounded-lg flex items-center justify-center text-slate-600 hover:bg-slate-100">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M6 6l12 12M18 6 6 18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <p className="text-[13px] text-slate-600 mb-4">{F.contact_body}</p>
        <div className="space-y-2">
          <a href={`mailto:${CONTACT_EMAIL}`} className={row}>
            <span>{F.contact_email}</span><span dir="ltr" className="font-semibold text-teal-800">{CONTACT_EMAIL}</span>
          </a>
          <a href={`tel:${CONTACT_PHONE_E164}`} className={row}>
            <span>{F.contact_phone}</span><span dir="ltr" className="font-semibold text-teal-800">{CONTACT_PHONE_DISPLAY}</span>
          </a>
          <a href={CONTACT_WHATSAPP_URL} target="_blank" rel="noopener noreferrer" className={row}>
            <span>WhatsApp</span><span dir="ltr" className="font-semibold text-teal-800">{CONTACT_PHONE_DISPLAY}</span>
          </a>
        </div>
      </div>
    </div>
  )
}


export function Footer() {
  const F = useI18n().t.footer
  const { user } = useAuth()
  const { openChat } = useChat()
  const [contactOpen, setContactOpen] = useState(false)
  const closeContact = useCallback(() => setContactOpen(false), [])

  function openHelp(e: React.MouseEvent) {
    e.preventDefault()
    if (user) openChat()
    else setContactOpen(true)
  }

  function openContact(e: React.MouseEvent) {
    e.preventDefault()
    setContactOpen(true)
  }

  return (
    <>
      {contactOpen && <ContactDialog onClose={closeContact} />}
      {/* Full-bleed divider; inner container aligns to the same content
          boundary as <main> (max-w-content mx-auto w-full px-6). */}
      <footer className="border-t border-slate-100 mt-10">
        <div className="max-w-content mx-auto w-full px-4 sm:px-6 py-6 flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between text-[12.5px] sm:text-[11.5px] text-slate-400">
          <div className="inline-flex items-center gap-2">
            <span>v1.3.0</span>
            <span className="text-slate-300">·</span>
            <span className="inline-flex items-center gap-1.5">
              <StatusDot tone="success" pulse size={5} /> {F.operational}
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 [&>a]:py-2 sm:[&>a]:py-0 [&>a]:whitespace-nowrap">
            <a href="#" onClick={openHelp} className="hover:text-slate-700">{F.help}</a>
            <a href="/privacy" className="hover:text-slate-700">{F.privacy}</a>
            <a href="#" onClick={openContact} className="hover:text-slate-700">{F.contact}</a>
            <a href="/accessibility" className="hover:text-slate-700">{F.accessibility}</a>
          </div>
        </div>
      </footer>
    </>
  )
}
