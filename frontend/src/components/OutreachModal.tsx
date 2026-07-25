'use client'
import { useState, useCallback, useEffect } from 'react'
import { TOKENS } from '@/lib/tokens'
import type { ApiFeedJob } from '@/lib/apiTypes'
import type { OutreachMessageType } from '@/lib/apiTypes'
import {
  generateOutreachMessage, generateHeadhunterMessage,
  generateJobOutreach, fetchJobOutreach,
} from '@/lib/api'

// ── Icons ─────────────────────────────────────────────────────────────────────

function CopyIcon({ s = 14 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="9" width="13" height="13" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  )
}
function CheckIcon({ s = 14 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  )
}
function SpinnerIcon({ s = 16 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" style={{ animation: 'spin 0.8s linear infinite' }}>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.5" strokeOpacity="0.2" />
      <path d="M12 3a9 9 0 0 1 9 9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  )
}

// ── Tab config ────────────────────────────────────────────────────────────────

type TabId = 'hiring_manager' | 'consultation' | 'escalation' | 'headhunter'

interface TabMeta {
  id:       TabId
  label:    string
  subtitle: string
  badge:    string
  badgeColor: string
}

const TABS: TabMeta[] = [
  {
    id:         'hiring_manager',
    label:      'Hiring Manager',
    subtitle:   'One message for THIS role, grounded in your tailored CV. Saved automatically.',
    badge:      'This role',
    badgeColor: 'bg-violet-50 text-violet-700 border-violet-200',
  },
  {
    id:         'consultation',
    label:      'Step 1 — Consultation',
    subtitle:   'Ask for advice, never for a job. Plant the seed.',
    badge:      'Low pressure',
    badgeColor: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  },
  {
    id:         'escalation',
    label:      'Step 2 — Escalation',
    subtitle:   'Follow up 24–48 hrs later with a forwardable summary.',
    badge:      'Referral ask',
    badgeColor: 'bg-teal-50 text-teal-700 border-teal-200',
  },
  {
    id:         'headhunter',
    label:      'Agency / Headhunter',
    subtitle:   'Direct pitch to recruiters at placement agencies.',
    badge:      'Value-first',
    badgeColor: 'bg-amber-50 text-amber-700 border-amber-200',
  },
]

// ── Helpers ───────────────────────────────────────────────────────────────────

function useCopyButton() {
  const [copied, setCopied] = useState(false)
  const copy = useCallback((text: string) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }, [])
  return { copied, copy }
}

// ── Main component ────────────────────────────────────────────────────────────

interface Props {
  job:     ApiFeedJob
  onClose: () => void
}

export function OutreachModal({ job, onClose }: Props) {
  const [activeTab,     setActiveTab]     = useState<TabId>('hiring_manager')
  const [targetName,    setTargetName]    = useState('')
  const [targetTitle,   setTargetTitle]   = useState('')
  const [targetCompany, setTargetCompany] = useState(job.company)
  const [context,       setContext]       = useState('')
  const [generatedMsg,  setGeneratedMsg]  = useState('')
  const [isGenerating,  setIsGenerating]  = useState(false)
  const [error,         setError]         = useState<string | null>(null)
  const { copied, copy } = useCopyButton()

  // ── Phase 3: job-anchored outreach (persisted per job) ───────────────────────
  const [jobMsg,     setJobMsg]     = useState('')      // generated / persisted text
  const [jobLoading, setJobLoading] = useState(false)   // POST generate in flight
  const [jobLoaded,  setJobLoaded]  = useState(false)   // initial GET completed
  const [jobError,   setJobError]   = useState<string | null>(null)

  // On mount, load any previously-generated message so it survives reloads.
  useEffect(() => {
    let cancelled = false
    fetchJobOutreach(job.job_id)
      .then(res => { if (!cancelled) setJobMsg(res.outreach_text ?? '') })
      .catch(() => { /* absent / transient — leave empty, user can generate */ })
      .finally(() => { if (!cancelled) setJobLoaded(true) })
    return () => { cancelled = true }
  }, [job.job_id])

  const handleGenerateJobOutreach = useCallback(async () => {
    setJobError(null)
    setJobLoading(true)
    try {
      const res = await generateJobOutreach(job.job_id)
      setJobMsg(res.outreach_text ?? '')
    } catch (e) {
      setJobError(e instanceof Error ? e.message : 'Generation failed')
    } finally {
      setJobLoading(false)
    }
  }, [job.job_id])

  const currentTab = TABS.find(t => t.id === activeTab)!

  const handleGenerate = useCallback(async () => {
    if (!targetName.trim()) {
      setError('Enter the target person\'s name first.')
      return
    }
    setError(null)
    setIsGenerating(true)
    setGeneratedMsg('')
    try {
      let result
      if (activeTab === 'headhunter') {
        result = await generateHeadhunterMessage({
          recruiter_name:  targetName.trim(),
          recruiter_title: targetTitle.trim() || 'Recruiter',
          agency_name:     targetCompany.trim() || job.company,
          context:         context.trim() || undefined,
        })
      } else {
        result = await generateOutreachMessage({
          message_type:   activeTab as OutreachMessageType,
          target_name:    targetName.trim(),
          target_title:   targetTitle.trim(),
          target_company: targetCompany.trim(),
          context:        context.trim() || undefined,
          job_id:         activeTab === 'escalation' ? job.job_id : undefined,
        })
      }
      setGeneratedMsg(result.message)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Generation failed')
    } finally {
      setIsGenerating(false)
    }
  }, [activeTab, targetName, targetTitle, targetCompany, context, job])

  // Reset generated message when tab changes so stale messages don't persist
  const handleTabChange = (id: TabId) => {
    setActiveTab(id)
    setGeneratedMsg('')
    setError(null)
    // Pre-fill company for headhunter tab from known agencies
    if (id === 'headhunter' && targetCompany === job.company) {
      setTargetCompany('')
    } else if (id !== 'headhunter' && !targetCompany) {
      setTargetCompany(job.company)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(15,23,42,0.55)', backdropFilter: 'blur(4px)' }}
      onClick={e => e.target === e.currentTarget && onClose()}
    >
      <div
        className="relative w-full max-w-2xl max-h-[92vh] overflow-y-auto rounded-2xl bg-white shadow-floating flex flex-col animate-modal-in"
        style={{ border: '1px solid rgba(0,0,0,0.08)' }}
      >
        {/* Header */}
        <div className="px-6 pt-5 pb-4 border-b border-slate-100 flex items-start justify-between gap-4 sticky top-0 bg-white z-10 rounded-t-2xl">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-0.5">
              Outreach Generator
            </div>
            <h2 className="text-[15px] font-semibold text-slate-900 leading-tight">
              {job.title}
              <span className="text-slate-400 font-normal"> · {job.company}</span>
            </h2>
          </div>
          <button
            onClick={onClose}
            className="flex-shrink-0 w-7 h-7 flex items-center justify-center rounded-full text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition"
          >
            ✕
          </button>
        </div>

        <div className="p-6 flex flex-col gap-5">
          {/* Strategy explanation */}
          <div className="rounded-2xl border border-slate-100 bg-slate-50 px-4 py-3 text-[12.5px] text-slate-600 leading-relaxed">
            <span className="font-semibold text-slate-800">The "Foot in the Door" strategy:</span>{' '}
            Message the Hiring Manager directly (Director, VP, C-level) — not HR.
            Use <strong>Step 1</strong> to start a human conversation, then escalate with <strong>Step 2</strong> after a positive reply.
            Use <strong>Agency / Headhunter</strong> for direct recruiter outreach at placement firms.
          </div>

          {/* Tab selector */}
          <div className="flex gap-2 flex-wrap">
            {TABS.map(tab => (
              <button
                key={tab.id}
                onClick={() => handleTabChange(tab.id)}
                className={`flex items-center gap-2 h-8 px-3 rounded-lg text-[12px] font-medium border transition ${
                  activeTab === tab.id
                    ? 'border-slate-300 bg-white text-slate-900 shadow-sm'
                    : 'border-transparent text-slate-500 hover:text-slate-800 hover:bg-slate-100'
                }`}
              >
                {tab.label.split(' — ')[0]}
                {tab.id !== activeTab && (
                  <span className={`text-[10px] px-1.5 py-0.5 rounded-full border font-medium ${tab.badgeColor}`}>
                    {tab.badge}
                  </span>
                )}
              </button>
            ))}
          </div>

          {/* Tab description */}
          <div className="flex items-center gap-2">
            <div className={`text-[11px] px-2 py-1 rounded-full border font-semibold ${currentTab.badgeColor}`}>
              {currentTab.badge}
            </div>
            <p className="text-[12.5px] text-slate-500">{currentTab.subtitle}</p>
          </div>

          {/* ── Phase 3: job-anchored hiring-manager outreach ─────────────── */}
          {activeTab === 'hiring_manager' && (
            <>
              {jobError && (
                <div className="rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-[12.5px] text-red-700">
                  {jobError}
                </div>
              )}

              <button
                onClick={handleGenerateJobOutreach}
                disabled={jobLoading || !jobLoaded}
                className="h-10 rounded-xl text-[13px] font-semibold text-white transition flex items-center justify-center gap-2 disabled:opacity-60"
                style={{ background: TOKENS.color.primary }}
              >
                {jobLoading ? (
                  <><SpinnerIcon s={15} /> Generating…</>
                ) : !jobLoaded ? (
                  <><SpinnerIcon s={15} /> Loading…</>
                ) : jobMsg ? (
                  '↺ Regenerate Message'
                ) : (
                  '✦ Generate Message'
                )}
              </button>

              {jobMsg && (
                <div className="rounded-2xl border border-slate-100 bg-slate-50 overflow-hidden">
                  <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-200 bg-white">
                    <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wide">
                      Hiring Manager · {jobMsg.split(/\s+/).length} words · saved
                    </span>
                    <button
                      onClick={() => copy(jobMsg)}
                      className={`flex items-center gap-1.5 h-7 px-2.5 rounded-lg text-[12px] font-medium border transition ${
                        copied
                          ? 'border-emerald-300 bg-emerald-50 text-emerald-700'
                          : 'border-slate-200 bg-white text-slate-600 hover:text-slate-900 hover:border-slate-300'
                      }`}
                    >
                      {copied ? <><CheckIcon s={12} /> Copied!</> : <><CopyIcon s={12} /> Copy</>}
                    </button>
                  </div>
                  <div className="px-4 py-4 text-[13px] text-slate-800 leading-relaxed whitespace-pre-wrap font-[system-ui]">
                    {jobMsg}
                  </div>
                </div>
              )}

              {!jobMsg && jobLoaded && (
                <div className="rounded-2xl border border-slate-100 px-4 py-3">
                  <p className="text-[11.5px] font-semibold text-slate-600 mb-2">💡 How this differs</p>
                  <ul className="space-y-1 text-[12px] text-slate-500">
                    <li>• One message tailored to <strong>this specific role</strong>, mapped to its requirements</li>
                    <li>• Grounded only in your verified CV — no invented claims</li>
                    <li>• Saved automatically, so it&apos;s here when you come back</li>
                  </ul>
                </div>
              )}
            </>
          )}

          {/* ── Person-targeted networking flow (consultation / escalation / headhunter) ── */}
          {activeTab !== 'hiring_manager' && (
          <>
          {/* Form fields */}
          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1">
              <label className="text-[11px] font-semibold text-slate-500 uppercase tracking-wide">
                {activeTab === 'headhunter' ? 'Recruiter Name' : 'Manager Name'} *
              </label>
              <input
                value={targetName}
                onChange={e => setTargetName(e.target.value)}
                placeholder={activeTab === 'headhunter' ? 'e.g. Dana Cohen' : 'e.g. Yael Ben-David'}
                className="h-9 px-3 rounded-lg border border-slate-200 text-[13px] text-slate-900 placeholder:text-slate-400 focus:outline-none focus:border-slate-400 bg-white"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-[11px] font-semibold text-slate-500 uppercase tracking-wide">
                {activeTab === 'headhunter' ? 'Agency Name' : 'Their Company'}
              </label>
              <input
                value={targetCompany}
                onChange={e => setTargetCompany(e.target.value)}
                placeholder={activeTab === 'headhunter' ? 'e.g. Gotfriends, Nisha, SQLink' : job.company}
                className="h-9 px-3 rounded-lg border border-slate-200 text-[13px] text-slate-900 placeholder:text-slate-400 focus:outline-none focus:border-slate-400 bg-white"
              />
            </div>
            <div className="flex flex-col gap-1 col-span-2">
              <label className="text-[11px] font-semibold text-slate-500 uppercase tracking-wide">
                {activeTab === 'escalation'
                  ? 'Describe the prior conversation (required for Step 2)'
                  : activeTab === 'headhunter'
                  ? 'Recruiter Title / Focus area (optional)'
                  : 'Their Title (VP Product, Director of CS…)'}
              </label>
              <input
                value={activeTab === 'escalation' ? context : targetTitle}
                onChange={e =>
                  activeTab === 'escalation'
                    ? setContext(e.target.value)
                    : setTargetTitle(e.target.value)
                }
                placeholder={
                  activeTab === 'escalation'
                    ? 'e.g. We spoke briefly at TechTLV, they mentioned scaling the CS team'
                    : activeTab === 'headhunter'
                    ? 'e.g. Tech Recruiter, PM & Product roles'
                    : 'e.g. VP Product'
                }
                className="h-9 px-3 rounded-lg border border-slate-200 text-[13px] text-slate-900 placeholder:text-slate-400 focus:outline-none focus:border-slate-400 bg-white"
              />
            </div>
            {activeTab !== 'escalation' && (
              <div className="flex flex-col gap-1 col-span-2">
                <label className="text-[11px] font-semibold text-slate-500 uppercase tracking-wide">
                  Additional context (optional)
                </label>
                <input
                  value={context}
                  onChange={e => setContext(e.target.value)}
                  placeholder="e.g. mutual connection, specific initiative you admire, shared background"
                  className="h-9 px-3 rounded-lg border border-slate-200 text-[13px] text-slate-900 placeholder:text-slate-400 focus:outline-none focus:border-slate-400 bg-white"
                />
              </div>
            )}
          </div>

          {/* Error */}
          {error && (
            <div className="rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-[12.5px] text-red-700">
              {error}
            </div>
          )}

          {/* Generate button */}
          <button
            onClick={handleGenerate}
            disabled={isGenerating}
            className="h-10 rounded-xl text-[13px] font-semibold text-white transition flex items-center justify-center gap-2 disabled:opacity-60"
            style={{ background: TOKENS.color.primary }}
          >
            {isGenerating ? (
              <><SpinnerIcon s={15} /> Generating…</>
            ) : generatedMsg ? (
              '↺ Regenerate Message'
            ) : (
              '✦ Generate Message'
            )}
          </button>

          {/* Generated message */}
          {generatedMsg && (
            <div className="rounded-2xl border border-slate-100 bg-slate-50 overflow-hidden">
              <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-200 bg-white">
                <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wide">
                  {currentTab.label} · {generatedMsg.split(/\s+/).length} words
                </span>
                <button
                  onClick={() => copy(generatedMsg)}
                  className={`flex items-center gap-1.5 h-7 px-2.5 rounded-lg text-[12px] font-medium border transition ${
                    copied
                      ? 'border-emerald-300 bg-emerald-50 text-emerald-700'
                      : 'border-slate-200 bg-white text-slate-600 hover:text-slate-900 hover:border-slate-300'
                  }`}
                >
                  {copied ? <><CheckIcon s={12} /> Copied!</> : <><CopyIcon s={12} /> Copy</>}
                </button>
              </div>
              <div className="px-4 py-4 text-[13px] text-slate-800 leading-relaxed whitespace-pre-wrap font-[system-ui]">
                {generatedMsg}
              </div>
            </div>
          )}

          {/* Tips */}
          {!generatedMsg && (
            <div className="rounded-2xl border border-slate-100 px-4 py-3">
              <p className="text-[11.5px] font-semibold text-slate-600 mb-2">
                {activeTab === 'consultation' && '💡 Tips for Step 1'}
                {activeTab === 'escalation'   && '💡 Tips for Step 2'}
                {activeTab === 'headhunter'   && '💡 Tips for Agency Outreach'}
              </p>
              <ul className="space-y-1 text-[12px] text-slate-500">
                {activeTab === 'consultation' && <>
                  <li>• Target Directors and VPs — they make hiring decisions, not HR</li>
                  <li>• Send Monday–Wednesday, 9–11am local time for best open rates</li>
                  <li>• Never mention the job opening — just ask for perspective</li>
                </>}
                {activeTab === 'escalation' && <>
                  <li>• Only send this after a positive reply (a like counts, a reply is better)</li>
                  <li>• The 3rd-person summary is designed to be forwarded verbatim to the hiring team</li>
                  <li>• Keep the transition natural — reference the prior conversation specifically</li>
                </>}
                {activeTab === 'headhunter' && <>
                  <li>• Target Gotfriends, Nisha, SQLink, Experis, Michael Page (Israel)</li>
                  <li>• Recruiters forward candidates who make their job easy — lead with value</li>
                  <li>• Specify your target role and availability clearly in the opening</li>
                </>}
              </ul>
            </div>
          )}
          </>
          )}
        </div>
      </div>
    </div>
  )
}
