'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { TOKENS } from '@/lib/tokens'
import { fetchGmailVerificationCode, GmailCodeForbiddenError } from '@/lib/api'
import {
  MailIcon,
  CopyIcon,
  CheckIcon,
  ExternalLinkIcon,
  ArrowIcon,
  ForwardIcon,
  FilterIcon,
  XIcon,
} from './icons'

// ── Constants ─────────────────────────────────────────────────────────────────

const INBOUND_EMAIL = 'jobapply-tracker@ravishing-cheesy-referable.ngrok-free.dev'
const GMAIL_SETTINGS_URL = 'https://mail.google.com/mail/u/0/#settings/fwdandiop'
const FILTER_KEYWORDS = [
  'interview',
  'application',
  'screening',
  'contract',
  'job offer',
  'position',
]

// How often to poll for the verification code while the modal is open (ms)
const POLL_INTERVAL_MS = 3_000

// Dev-mode detection — true only when running on localhost
const IS_DEV =
  typeof window !== 'undefined' &&
  (window.location.hostname === 'localhost' ||
   window.location.hostname === '127.0.0.1')

// ── Step number badge ─────────────────────────────────────────────────────────

function StepBadge({ n, done = false }: { n: number; done?: boolean }) {
  return done ? (
    <span
      className="shrink-0 w-6 h-6 rounded-full flex items-center justify-center"
      style={{ background: TOKENS.color.success }}
    >
      <CheckIcon s={12} />
    </span>
  ) : (
    <span
      className="shrink-0 w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-bold text-white"
      style={{ background: TOKENS.color.primary }}
    >
      {n}
    </span>
  )
}

// ── Step card wrapper ─────────────────────────────────────────────────────────

function StepCard({
  step,
  title,
  done,
  children,
}: {
  step:     number
  title:    string
  done?:    boolean
  children: React.ReactNode
}) {
  return (
    <div className={`rounded-xl border overflow-hidden transition-colors duration-300 ${
      done ? 'border-emerald-200 bg-emerald-50/30' : 'border-slate-200 bg-white'
    }`}>
      <div className={`flex items-center gap-3 px-4 py-3 border-b ${
        done ? 'border-emerald-200 bg-emerald-50/60' : 'border-slate-100 bg-slate-50/60'
      }`}>
        <StepBadge n={step} done={done} />
        <span className="text-[13px] font-semibold text-slate-800">{title}</span>
      </div>
      <div className="px-4 py-4">{children}</div>
    </div>
  )
}

// ── Copy helper ───────────────────────────────────────────────────────────────

async function copyToClipboard(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const el = document.createElement('textarea')
    el.value = text
    document.body.appendChild(el)
    el.select()
    document.execCommand('copy')
    document.body.removeChild(el)
  }
}

// ── Gmail forwarding mock ─────────────────────────────────────────────────────

function GmailMock() {
  return (
    <div className="rounded-lg border border-slate-200 overflow-hidden text-[12px]">
      <div className="flex items-center gap-2 px-3 py-2 bg-white border-b border-slate-100">
        <div className="flex items-center gap-[1px]">
          {[['G','#4285F4'],['m','#EA4335'],['a','#FBBC05'],['i','#34A853'],['l','#4285F4']].map(([ch, col]) => (
            <span key={ch+col} className="font-bold text-[12px]" style={{ color: col }}>{ch}</span>
          ))}
        </div>
        <div className="flex-1" />
        <span className="text-slate-400 text-[10px]">Settings › Forwarding and POP/IMAP</span>
      </div>
      <div className="bg-white px-4 py-3 space-y-2.5">
        <p className="text-[11px] font-semibold text-slate-700 uppercase tracking-wide">
          Forwarding
        </p>
        <div className="flex items-center justify-between rounded-lg border border-teal-200 bg-teal-50/60 px-3 py-2.5">
          <div className="flex items-center gap-2">
            <ForwardIcon s={13} />
            <span className="text-slate-700 font-medium">Add a forwarding address</span>
          </div>
          <span
            className="text-[11px] font-semibold px-2.5 py-1 rounded-full text-white"
            style={{ background: TOKENS.color.primary }}
          >
            + Add
          </span>
        </div>
        <p className="text-[11px] text-slate-400 leading-snug">
          Paste your JobApply address from Step 1 here, then click the verification link
          Gmail sends — the code will appear below automatically.
        </p>
      </div>
    </div>
  )
}

// ── Verification code panel ───────────────────────────────────────────────────

function VerificationCodePanel({ code }: { code: string | null }) {
  const [codeCopied, setCodeCopied] = useState(false)

  const handleCopyCode = useCallback(async () => {
    if (!code) return
    await copyToClipboard(code)
    setCodeCopied(true)
    setTimeout(() => setCodeCopied(false), 2200)
  }, [code])

  if (code) {
    return (
      <div
        className="rounded-xl border-2 border-emerald-300 bg-emerald-50 px-4 py-4 flex flex-col items-center gap-3"
        style={{ boxShadow: '0 0 0 4px rgba(16,185,129,0.10), 0 0 20px rgba(16,185,129,0.12)' }}
      >
        {/* Glowing label */}
        <div className="flex items-center gap-2">
          <span className="relative flex h-2.5 w-2.5">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500" />
          </span>
          <span className="text-[11.5px] font-semibold text-emerald-700 uppercase tracking-wide">
            Confirmation code captured!
          </span>
        </div>

        {/* The code itself */}
        <div className="flex items-center gap-3">
          <span
            className="font-mono font-black text-emerald-800 tracking-[0.2em] select-all"
            style={{ fontSize: 34, letterSpacing: '0.25em', textShadow: '0 1px 3px rgba(16,185,129,0.25)' }}
          >
            {code}
          </span>
          <button
            onClick={handleCopyCode}
            className={`inline-flex items-center gap-1.5 h-9 px-3.5 rounded-lg text-[12px] font-semibold border transition-all duration-200 ${
              codeCopied
                ? 'border-emerald-400 bg-emerald-100 text-emerald-800'
                : 'border-emerald-300 bg-white text-emerald-800 hover:bg-emerald-50'
            }`}
          >
            {codeCopied ? <><CheckIcon s={13} /> Copied!</> : <><CopyIcon s={13} /> Copy</>}
          </button>
        </div>

        <p className="text-[11px] text-emerald-600 text-center leading-snug">
          Paste this code into the Gmail confirmation dialog to complete forwarding setup.
        </p>
      </div>
    )
  }

  // Waiting state — animated pulse
  return (
    <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-4 flex flex-col items-center gap-2.5">
      {/* Spinner dots */}
      <div className="flex items-center gap-1.5">
        {[0, 1, 2].map(i => (
          <span
            key={i}
            className="w-1.5 h-1.5 rounded-full bg-slate-400"
            style={{
              animation: 'bounce 1.2s infinite',
              animationDelay: `${i * 0.18}s`,
            }}
          />
        ))}
      </div>
      <p className="text-[12px] font-medium text-slate-500">
        Waiting for Gmail verification email…
      </p>
      <p className="text-[11px] text-slate-400 text-center leading-snug max-w-[280px]">
        Click <strong className="text-slate-600">"Send verification"</strong> in Gmail — the
        9-digit code will appear here automatically within seconds.
      </p>
      <style>{`
        @keyframes bounce {
          0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
          40%            { transform: scale(1);   opacity: 1;   }
        }
      `}</style>
    </div>
  )
}

// ── Filter badge ──────────────────────────────────────────────────────────────

function FilterBadge({ keyword }: { keyword: string }) {
  return (
    <span className="inline-flex items-center h-6 px-2.5 rounded-full bg-slate-100 border border-slate-200 text-[11px] font-medium text-slate-600">
      {keyword}
    </span>
  )
}

// ── Main modal ────────────────────────────────────────────────────────────────

interface EmailSetupModalProps {
  open:    boolean
  onClose: () => void
}

export function EmailSetupModal({ open, onClose }: EmailSetupModalProps) {
  const [addressCopied,    setAddressCopied]    = useState(false)
  const [verificationCode, setVerificationCode] = useState<string | null>(null)
  const [simState,         setSimState]         = useState<'idle' | 'sending' | 'sent' | 'error'>('idle')
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Reset state when modal opens/closes
  useEffect(() => {
    if (open) {
      setAddressCopied(false)
      // Don't reset the code — if it was already captured, keep showing it
    }
  }, [open])

  // ── Polling ──────────────────────────────────────────────────────────────────
  // Start polling when modal opens, stop when it closes or code arrives.
  useEffect(() => {
    if (!open) {
      if (pollRef.current) clearInterval(pollRef.current)
      return
    }

    const poll = async () => {
      try {
        const res = await fetchGmailVerificationCode()
        if (res.code) {
          setVerificationCode(res.code)
          // Stop polling once we have the code
          if (pollRef.current) clearInterval(pollRef.current)
          pollRef.current = null
        }
      } catch (err) {
        if (err instanceof GmailCodeForbiddenError) {
          // Caller is not an admin — this endpoint will never succeed for
          // them, so stop polling instead of retrying forever. No error is
          // shown; the code panel just never auto-fills.
          if (pollRef.current) clearInterval(pollRef.current)
          pollRef.current = null
          return
        }
        // Transient/network error — silently ignore and let the interval retry.
      }
    }

    // Run once immediately, then on interval
    poll()
    pollRef.current = setInterval(poll, POLL_INTERVAL_MS)

    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [open])

  // Escape to close
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, onClose])

  // Lock body scroll
  useEffect(() => {
    document.body.style.overflow = open ? 'hidden' : ''
    return () => { document.body.style.overflow = '' }
  }, [open])

  const handleCopyAddress = useCallback(async () => {
    await copyToClipboard(INBOUND_EMAIL)
    setAddressCopied(true)
    setTimeout(() => setAddressCopied(false), 2200)
  }, [])

  // ── Dev-only: simulate Gmail verification email hitting the local webhook ─
  const handleSimulate = useCallback(async () => {
    if (simState === 'sending') return
    setSimState('sending')

    // Generate a fresh random 9-digit code each run so re-runs show new codes
    const code = String(Math.floor(100_000_000 + Math.random() * 900_000_000))
    const mockBody = [
      'Gmail has received a request to forward mail from youraddress@gmail.com',
      'to jobapply-tracker@parse.jobapply.app.',
      '',
      'To confirm this request and start forwarding, please click the link below',
      'or paste the Confirmation code into Gmail:',
      '',
      `Confirmation code: ${code}`,
      '',
      'This code will expire in 48 hours.',
    ].join('\n')

    try {
      const res = await fetch('/api/webhooks/inbound-email', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sender:    'forwarding-noreply@google.com',
          subject:   'Gmail Forwarding Confirmation - Receive Mail from youraddress@gmail.com',
          body_text: mockBody,
        }),
      })
      if (!res.ok) throw new Error(`${res.status}`)
      setSimState('sent')
      // The poller will pick up the code within POLL_INTERVAL_MS — no need to
      // set verificationCode directly here; we let the real flow prove itself.
      setTimeout(() => setSimState('idle'), 4000)
    } catch (e) {
      console.error('[EmailSetupModal] Simulate failed:', e)
      setSimState('error')
      setTimeout(() => setSimState('idle'), 3500)
    }
  }, [simState])

  if (!open) return null

  const codeArrived = Boolean(verificationCode)

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center p-4"
      style={{ background: 'rgba(15, 23, 42, 0.55)', backdropFilter: 'blur(4px)' }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        className="relative w-full max-w-[520px] max-h-[90vh] overflow-y-auto rounded-2xl bg-white shadow-floating border border-slate-200 animate-modal-in"
        style={{ boxShadow: '0 24px 64px rgba(0,0,0,0.18)' }}
      >
        {/* ── Header ── */}
        <div className="sticky top-0 z-10 flex items-start justify-between gap-4 px-6 pt-5 pb-4 bg-white border-b border-slate-100">
          <div className="flex items-center gap-3">
            <div
              className="shrink-0 w-9 h-9 rounded-xl flex items-center justify-center"
              style={{ background: TOKENS.color.primarySoft }}
            >
              <MailIcon s={18} />
            </div>
            <div>
              <h2 className="text-[15px] font-bold text-slate-900 leading-tight">
                Connect Email Automation
              </h2>
              <p className="text-[12px] text-slate-500 mt-0.5">
                Auto-track recruiter replies in your Kanban board
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition mt-0.5"
            aria-label="Close"
          >
            <XIcon s={15} />
          </button>
        </div>

        {/* ── Body ── */}
        <div className="px-6 py-5 space-y-4">

          <p className="text-[13px] text-slate-600 leading-relaxed">
            Forward recruiter emails to your personal JobApply address and the AI will
            automatically detect status updates —{' '}
            <em>phone screens, interview invites, offers, rejections</em> — and move your
            cards in real time.
          </p>

          {/* ── Step 1: Copy inbound address ── */}
          <StepCard step={1} title="Copy your personal inbound address">
            <div className="space-y-3">
              <p className="text-[12px] text-slate-500">
                This is your unique forwarding address. Keep it private.
              </p>
              <div className="flex items-center gap-2">
                <div className="flex-1 flex items-center gap-2 h-10 px-3 rounded-lg border border-slate-200 bg-slate-50 overflow-hidden">
                  <MailIcon s={13} />
                  <span className="text-[12.5px] text-slate-700 font-mono truncate flex-1">
                    {INBOUND_EMAIL}
                  </span>
                </div>
                <button
                  onClick={handleCopyAddress}
                  className={`shrink-0 inline-flex items-center gap-1.5 h-10 px-3.5 rounded-lg text-[12px] font-semibold border transition-all duration-200 ${
                    addressCopied
                      ? 'border-emerald-300 bg-emerald-50 text-emerald-700'
                      : 'border-slate-200 bg-white text-slate-700 hover:bg-slate-50 hover:border-slate-300'
                  }`}
                >
                  {addressCopied
                    ? <><CheckIcon s={13} /> Copied!</>
                    : <><CopyIcon s={13} /> Copy</>}
                </button>
              </div>
            </div>
          </StepCard>

          {/* ── Step 2: Gmail forwarding + live verification code ── */}
          <StepCard
            step={2}
            title="Add as a Gmail forwarding address"
            done={codeArrived}
          >
            <div className="space-y-3">
              <p className="text-[12px] text-slate-500">
                In Gmail Settings → Forwarding and POP/IMAP, click{' '}
                <strong className="text-slate-700">"Add a forwarding address"</strong> and
                paste the address above. When Gmail sends the verification email, the
                confirmation code will appear below automatically.
              </p>
              <GmailMock />

              {/* ── Dev-only simulation banner ──────────────────────────── */}
              {IS_DEV && (
                <div className="rounded-lg border border-dashed border-violet-300 bg-violet-50/60 px-3 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <p className="text-[11px] font-bold text-violet-700 uppercase tracking-wide mb-0.5">
                        ⚡ Dev mode
                      </p>
                      <p className="text-[11.5px] text-violet-700 leading-snug">
                        No live MX domain locally — click to fire a mock Gmail
                        verification email directly to{' '}
                        <code className="bg-violet-100 px-1 py-0.5 rounded text-[10.5px] font-mono">
                          localhost:8000
                        </code>{' '}
                        and watch the code appear below.
                      </p>
                    </div>
                    <button
                      onClick={handleSimulate}
                      disabled={simState === 'sending'}
                      className={`shrink-0 inline-flex items-center gap-1.5 h-8 px-3 rounded-lg text-[11.5px] font-semibold border transition-all duration-200 disabled:opacity-60 disabled:pointer-events-none ${
                        simState === 'sent'
                          ? 'border-emerald-300 bg-emerald-50 text-emerald-700'
                          : simState === 'error'
                          ? 'border-rose-300 bg-rose-50 text-rose-700'
                          : 'border-violet-300 bg-white text-violet-700 hover:bg-violet-50'
                      }`}
                    >
                      {simState === 'sending' && (
                        <svg width={11} height={11} viewBox="0 0 24 24" fill="none"
                          stroke="currentColor" strokeWidth="2.5"
                          style={{ animation: 'spin 0.8s linear infinite', flexShrink: 0 }}>
                          <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
                          <circle cx="12" cy="12" r="9" strokeOpacity="0.25"/>
                          <path d="M12 3a9 9 0 0 1 9 9" strokeLinecap="round"/>
                        </svg>
                      )}
                      {simState === 'idle'    && 'Simulate Gmail Verification'}
                      {simState === 'sending' && 'Sending…'}
                      {simState === 'sent'    && '✓ Sent — polling…'}
                      {simState === 'error'   && '✗ Backend unreachable'}
                    </button>
                  </div>
                </div>
              )}

              {/* Live code panel — waiting dots → glowing code */}
              <VerificationCodePanel code={verificationCode} />
            </div>
          </StepCard>

          {/* ── Step 3: Filter rule ── */}
          <StepCard step={3} title="Create a Gmail filter rule">
            <div className="space-y-3">
              <p className="text-[12px] text-slate-500">
                In{' '}
                <strong className="text-slate-700">
                  Settings → Filters and Blocked Addresses
                </strong>
                , create a new filter matching emails with any of the keywords below, then
                set the action to{' '}
                <strong className="text-slate-700">Forward to</strong> your JobApply address.
              </p>
              <div>
                <div className="flex items-center gap-1.5 mb-2">
                  <FilterIcon s={12} />
                  <span className="text-[11px] font-semibold text-slate-600 uppercase tracking-wide">
                    Filter keywords
                  </span>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {FILTER_KEYWORDS.map(kw => <FilterBadge key={kw} keyword={kw} />)}
                </div>
              </div>
              <div className="rounded-lg bg-amber-50 border border-amber-200 px-3 py-2.5">
                <p className="text-[11.5px] text-amber-800 leading-snug">
                  <strong>Tip:</strong> Use the{' '}
                  <code className="bg-amber-100 px-1 py-0.5 rounded text-[10.5px] font-mono">
                    subject:
                  </code>{' '}
                  field and enter{' '}
                  <code className="bg-amber-100 px-1 py-0.5 rounded text-[10.5px] font-mono">
                    interview OR screening OR "job offer" OR position
                  </code>{' '}
                  to catch the most common recruiter subjects.
                </p>
              </div>
            </div>
          </StepCard>

          {/* ── How it works ── */}
          <div className="rounded-xl border border-slate-100 bg-slate-50 px-4 py-3">
            <p className="text-[11.5px] font-semibold text-slate-600 uppercase tracking-wide mb-2">
              How it works
            </p>
            <div className="space-y-1.5">
              {[
                'Recruiter sends you an email',
                'Gmail filter auto-forwards it to JobApply',
                'AI reads sender, subject & body to detect the stage',
                'Your Kanban card moves automatically',
              ].map((s, i) => (
                <div key={i} className="flex items-start gap-2">
                  <ArrowIcon s={12} />
                  <span className="text-[12px] text-slate-600 leading-snug">{s}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* ── Footer ── */}
        <div className="sticky bottom-0 flex items-center justify-between gap-3 px-6 py-4 border-t border-slate-100 bg-white/95 backdrop-blur-sm">
          <button
            onClick={onClose}
            className="h-9 px-4 rounded-full text-[13px] font-medium text-slate-600 hover:bg-slate-100 transition"
          >
            Done
          </button>
          <a
            href={GMAIL_SETTINGS_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 h-9 px-4 rounded-full text-[13px] font-semibold border border-slate-200 bg-white text-slate-700 hover:bg-slate-50 hover:border-slate-300 transition"
          >
            <ExternalLinkIcon s={13} />
            Open Gmail Settings
          </a>
        </div>
      </div>
    </div>
  )
}
