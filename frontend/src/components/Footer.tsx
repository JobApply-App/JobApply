'use client'
import { useCallback, useRef, useState } from 'react'
import { useI18n } from '@/contexts/I18nContext'
import { useChat } from '@/contexts/ChatContext'
import { Logo } from './ui/Logo'
import { useDialogA11y } from '@/hooks/useDialogA11y'
import {
  CONTACT_EMAIL, CONTACT_PHONE_DISPLAY, CONTACT_PHONE_E164, CONTACT_WHATSAPP_URL,
} from '@/lib/contact'

// Help opens Eliya, the support assistant, for everyone, signed in or not:
// she explains the product and helps with sign-up, login and technical
// trouble, and her conversation is saved so it continues later. Contact shows
// the real email, phone and WhatsApp (lib/contact.ts). Rendered once, from
// the root layout, so every page ends with the same footer.

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


function CookiesDialog({ onClose }: { onClose: () => void }) {
  const F = useI18n().t.footer
  const ref = useRef<HTMLDivElement>(null)
  useDialogA11y(onClose, ref)
  return (
    <div className="fixed inset-0 z-[200] flex items-end sm:items-center justify-center p-4 bg-slate-900/40" onClick={onClose}>
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby="cookies-dialog-title"
        tabIndex={-1}
        onClick={e => e.stopPropagation()}
        className="w-full max-w-md rounded-2xl bg-white p-5 border border-slate-100"
        style={{ boxShadow: '0 1px 2px rgba(15,23,42,.08), 0 12px 32px rgba(15,23,42,.18)' }}
      >
        <div className="flex items-center justify-between mb-2">
          <h2 id="cookies-dialog-title" className="text-[16px] font-bold text-slate-900">{F.cookies_title}</h2>
          <button type="button" onClick={onClose} aria-label={F.cookies_close}
            className="h-11 w-11 -me-2 rounded-lg flex items-center justify-center text-slate-600 hover:bg-slate-100">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M6 6l12 12M18 6 6 18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <p className="text-[13px] text-slate-600 mb-4 leading-relaxed">{F.cookies_body}</p>
        <ul className="space-y-2 mb-4">
          {F.cookies_items.map(item => (
            <li key={item.name} className="rounded-xl border border-slate-200 px-4 py-3">
              <div className="flex items-center justify-between gap-3">
                <span className="text-[13.5px] font-semibold text-slate-800">{item.name}</span>
                <span className="text-[11.5px] font-medium text-slate-500">{F.cookies_always_on}</span>
              </div>
              <p className="text-[12.5px] text-slate-500 mt-1 leading-relaxed">{item.purpose}</p>
            </li>
          ))}
        </ul>
        <p className="text-[12.5px] text-slate-500 leading-relaxed">{F.cookies_none_optional}</p>
      </div>
    </div>
  )
}


export function Footer() {
  const F = useI18n().t.footer
  const { openEliya } = useChat()
  const [dialog, setDialog] = useState<'contact' | 'cookies' | null>(null)
  const closeDialog = useCallback(() => setDialog(null), [])

  // 44px tap targets on phones; on a pointer screen the rows sit closer.
  const link = 'inline-flex items-center min-h-[44px] sm:min-h-0 sm:py-1 text-start text-slate-500 hover:text-slate-900 transition-colors whitespace-nowrap'
  const group = 'text-[12.5px] font-semibold text-slate-900'

  return (
    <>
      {dialog === 'contact' && <ContactDialog onClose={closeDialog} />}
      {dialog === 'cookies' && <CookiesDialog onClose={closeDialog} />}
      <footer className="border-t border-slate-200 bg-white">
        <div className="max-w-content mx-auto w-full px-4 sm:px-6 py-8 sm:py-10 flex flex-col gap-8 sm:flex-row sm:justify-between text-[13px]">
          <div className="flex flex-col gap-3">
            <Logo size={22} />
            <p className="text-[12.5px] text-slate-500">
              <span dir="ltr">&copy; {new Date().getFullYear()} JOB-APPLY</span>
              <br />
              {F.rights}
            </p>
          </div>
          <nav aria-label={F.nav_label} className="grid grid-cols-2 gap-x-10 gap-y-6 sm:gap-x-16">
            <div>
              <p id="footer-support" className={group}>{F.group_support}</p>
              <ul aria-labelledby="footer-support" className="mt-2 sm:mt-3 sm:space-y-1">
                <li><button type="button" onClick={openEliya} className={link}>{F.help}</button></li>
                <li><button type="button" onClick={() => setDialog('contact')} className={link}>{F.contact}</button></li>
              </ul>
            </div>
            <div>
              <p id="footer-legal" className={group}>{F.group_legal}</p>
              <ul aria-labelledby="footer-legal" className="mt-2 sm:mt-3 sm:space-y-1">
                <li><a href="/privacy" className={link}>{F.privacy}</a></li>
                <li><a href="/terms" className={link}>{F.terms}</a></li>
                <li><button type="button" onClick={() => setDialog('cookies')} className={link}>{F.cookies}</button></li>
                <li><a href="/accessibility" className={link}>{F.accessibility}</a></li>
              </ul>
            </div>
          </nav>
        </div>
      </footer>
    </>
  )
}
