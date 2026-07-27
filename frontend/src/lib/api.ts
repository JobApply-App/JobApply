import type { ApiAgentStatus, ApiJobMatch, AnalyzeRequest, AnalyzeResponse, MatchScoreResult, ApiFeedJob, RefreshResponse, BackfillResponse, FetchJdResponse, JobStatus, VerifyChatEntry, VerifyChatResponse, TailorBriefResponse, OutreachRequest, OutreachResponse, HeadhunterRequest, AtsKeywordsResponse, InterviewSession, VerificationResult, CrmBoard, MarkAppliedResponse, JobAnalysisState } from './apiTypes'
import type { Job } from './data'
import { supabase } from './supabase'

// Empty base → all requests are relative (/api/...) and are proxied to
// FastAPI by the rewrites rule in next.config.mjs. Set NEXT_PUBLIC_API_URL
// only when you need to bypass the proxy (e.g. hitting a staging server).
const BASE = process.env.NEXT_PUBLIC_API_URL ?? ''

// ── Auth token ────────────────────────────────────────────────────────────────
// Module-level variable so it persists across re-renders.
// AuthContext calls setAuthToken() when the Supabase session changes.
let _authToken: string | null = null

export function setAuthToken(token: string | null): void {
  _authToken = token
}

function _authHeaders(): Record<string, string> {
  return _authToken ? { Authorization: `Bearer ${_authToken}` } : {}
}

/** Public accessor for components that call fetch() directly outside api.ts. */
export function getAuthHeaders(): Record<string, string> {
  return _authHeaders()
}

/**
 * Global token-refresh guard — called at the start of every fetch wrapper.
 *
 * WHY THIS EXISTS
 * ───────────────
 * _authToken is a module-level variable set by AuthContext one async tick
 * after the app mounts.  Parallel layout components (Overview stats, agent
 * status, notifications, JobFeed) all fire their initial GET requests
 * simultaneously at mount time, before AuthContext has had a chance to call
 * setAuthToken().  Any one of those parallel requests going out with an empty
 * Authorization header receives a 401, which triggers _onAuthError() →
 * localStorage.clear() + hard-evict to /login, wiping the saved tab and
 * producing the "redirect to overview" symptom.
 *
 * This function is the single fix point: if _authToken is absent, it makes one
 * synchronous-ish Supabase session call to populate it before the request goes
 * out.  The result is cached back into _authToken so subsequent parallel calls
 * that land here within the same event-loop turn benefit too.
 */
async function _ensureFreshToken(): Promise<void> {
  if (_authToken) return  // fast path — already have a token
  if (!supabase) return
  try {
    const { data: { session } } = await supabase.auth.getSession()
    if (session?.access_token) {
      _authToken = session.access_token
    }
  } catch {
    // Non-fatal — request will proceed without a token and may 401,
    // but at least we tried; the error is the backend's to surface.
  }
}

/**
 * Public token-freshness guard for components that call fetch() directly
 * instead of going through the get/post/patch wrappers.
 *
 * The internal wrappers already await _ensureFreshToken() before every
 * request. Direct-fetch call sites (e.g. the Confidence Matrix and
 * Trust Score fetches in TrustDashboard) must do the same, or they will
 * send an empty Authorization header on the first mount-time request —
 * before AuthContext has called setAuthToken() — receive a 401, and trip
 * the global _onAuthError() sign-out (the auto-logout loop).
 *
 * Usage:
 *   await ensureFreshToken()
 *   const res = await fetch(url, { headers: getAuthHeaders() })
 */
export async function ensureFreshToken(): Promise<void> {
  return _ensureFreshToken()
}

// ── Auth error handler ────────────────────────────────────────────────────────
// AuthContext wires this up so any 401 or 503 from the backend triggers an
// immediate sign-out and clears the stale session from local storage.
// Using a callback (rather than importing AuthContext directly) keeps this
// module free of React dependencies.
let _onAuthError: (() => void) | null = null

export function setAuthErrorHandler(handler: () => void): void {
  _onAuthError = handler
}

/**
 * Call on every non-ok response; fires the sign-out callback for auth errors.
 *
 * Reads the JSON body's `detail` field when present — FastAPI's HTTPException
 * puts the actual failure reason there (e.g. "Scrape Failed: page returned no
 * job description text"), which is far more useful to surface to the user
 * than a bare "422 Unprocessable Entity".
 */
async function _handleHttpError(res: Response, path: string): Promise<never> {
  // Only 401 signals a possibly-dead session. 503 means the BACKEND is
  // unavailable/misconfigured (e.g. LLM key missing) — treating it as an auth
  // failure hard-evicted logged-in users the moment any degraded endpoint was
  // hit (notably right after onboarding, when Ariel auto-opens and the chat
  // endpoints are called for the first time).
  if (res.status === 401) {
    _onAuthError?.()
  }
  let detail: string | undefined
  try {
    const body = await res.json()
    detail = typeof body?.detail === 'string' ? body.detail : undefined
  } catch {
    // Non-JSON or empty body — fall back to status text below.
  }
  throw new Error(detail || `${res.status} ${res.statusText} — ${path}`)
}

/**
 * Translate a raw fetch()-level failure into a message worth showing a user.
 *
 * fetch() throws a bare TypeError ("Failed to fetch" / "NetworkError...")
 * for anything that never reached a server — offline, DNS failure, CORS,
 * backend down. Left unhandled, that raw TypeError propagates all the way
 * up to whatever component's catch block called this wrapper, and gets
 * rendered verbatim (e.g. "Failed to load applications. TypeError: Failed
 * to fetch"). Every wrapper below routes fetch() failures through this so
 * callers only ever see a message meant for a human.
 */
function _networkErrorOr(err: unknown): Error {
  if (err instanceof TypeError) {
    return new Error('Could not reach the server — check your connection and try again.')
  }
  return err instanceof Error ? err : new Error(String(err))
}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  await _ensureFreshToken()
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      cache:   'no-store',
      headers: _authHeaders(),
      signal,
    })
  } catch (err) {
    // AbortError (caller cancelled — e.g. a superseded pagination request)
    // is not a real failure; let it propagate as-is so callers can tell it
    // apart from a genuine network/HTTP error and skip showing an error UI.
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw _networkErrorOr(err)
  }
  if (!res.ok) await _handleHttpError(res, path)
  return res.json() as Promise<T>
}

/** POST with no request body — for endpoints that take only query params. */
async function postEmpty<TRes>(path: string): Promise<TRes> {
  await _ensureFreshToken()
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      method:  'POST',
      headers: _authHeaders(),
    })
  } catch (err) {
    throw _networkErrorOr(err)
  }
  if (!res.ok) await _handleHttpError(res, path)
  return res.json() as Promise<TRes>
}

async function post<TBody, TRes>(path: string, body: TBody, timeoutMs?: number): Promise<TRes> {
  await _ensureFreshToken()
  const controller = timeoutMs ? new AbortController() : undefined
  const timer = controller
    ? setTimeout(() => controller.abort(), timeoutMs)
    : undefined

  try {
    const res = await fetch(`${BASE}${path}`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json', ..._authHeaders() },
      body:    JSON.stringify(body),
      signal:  controller?.signal,
    })
    if (!res.ok) await _handleHttpError(res, path)
    return res.json() as Promise<TRes>
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new Error('Request timed out — the server is taking longer than expected. Please try again.')
    }
    throw _networkErrorOr(err)
  } finally {
    if (timer !== undefined) clearTimeout(timer)
  }
}

async function del<TRes>(path: string): Promise<TRes> {
  await _ensureFreshToken()
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      method:  'DELETE',
      headers: _authHeaders(),
    })
  } catch (err) {
    throw _networkErrorOr(err)
  }
  if (!res.ok) await _handleHttpError(res, path)
  return res.json() as Promise<TRes>
}

async function patch<TBody, TRes>(path: string, body: TBody): Promise<TRes> {
  await _ensureFreshToken()
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      method:  'PATCH',
      headers: { 'Content-Type': 'application/json', ..._authHeaders() },
      body:    JSON.stringify(body),
    })
  } catch (err) {
    throw _networkErrorOr(err)
  }
  if (!res.ok) await _handleHttpError(res, path)
  return res.json() as Promise<TRes>
}

export async function fetchAgents(): Promise<ApiAgentStatus[]> {
  return get<ApiAgentStatus[]>('/api/agents/')
}

export interface RunAgentResponse {
  agent_id:  string
  state:     string
  triggered: boolean
}

export async function runAgent(agentId: string): Promise<RunAgentResponse> {
  return post<Record<string, never>, RunAgentResponse>(`/api/agents/${agentId}/run`, {})
}

// Triggers the full sequential pipeline: s1 → s2 → s3 → s4 in one shot.
export interface SyncPipelineResponse {
  triggered: boolean
  state?:    string
  reason?:   string
}

export async function syncPipeline(): Promise<SyncPipelineResponse> {
  return post<Record<string, never>, SyncPipelineResponse>('/api/agents/sync', {})
}

export async function fetchJobs(
  filter = 'all',
  sort   = 'match',
): Promise<ApiJobMatch[]> {
  return get<ApiJobMatch[]>(`/api/jobs/?filter=${filter}&sort=${sort}`)
}

export async function startAnalysis(url: string): Promise<ApiFeedJob> {
  return post<AnalyzeRequest, ApiFeedJob>('/api/jobs/analyze', { url })
}

export async function fetchTemplates(): Promise<import('./apiTypes').TemplateInfo[]> {
  const data = await get<{ templates: import('./apiTypes').TemplateInfo[] }>('/api/resumes/templates')
  return data.templates
}

export async function renderPdf(cvData: Record<string, unknown>, templateId: string): Promise<string> {
  const data = await post<object, { pdf_b64: string }>('/api/resumes/render-pdf', {
    cv_data: cvData, template_id: templateId,
  })
  return data.pdf_b64
}

export interface TailorOkResponse {
  status:             string
  cv_data:            Record<string, unknown>
  pdf_b64:            string | null
  match_score:        MatchScoreResult | null
  preferred_template: string
}

export async function fetchCachedCV(jobId: string): Promise<TailorOkResponse | null> {
  await _ensureFreshToken()
  const res = await fetch(`${BASE}/api/resumes/cached/${jobId}`, {
    headers: _authHeaders(),
    cache:   'no-store',
  })
  if (res.status === 204 || !res.ok) return null
  return res.json() as Promise<TailorOkResponse>
}

/**
 * Explicitly persist the given cv_data (+ match_score) as the saved base
 * state for this job. This is the ONLY way Copilot/LiveEditor draft edits
 * become durable — until this is called, edits live only in local React
 * state and are discarded if the modal is closed/reopened.
 */
export async function saveCv(
  jobId: string,
  cvData: Record<string, unknown>,
  matchScore: Record<string, unknown> | null,
): Promise<void> {
  await post('/api/resumes/save-cv', {
    job_id: jobId, cv_data: cvData, match_score: matchScore,
  })
}

export async function fetchMatchScore(
  jobId: string,
  cvData: Record<string, unknown>,
  llmValidation = false,
): Promise<import('./apiTypes').MatchScoreResult> {
  return post('/api/resumes/match-score', {
    job_id: jobId, cv_data: cvData, llm_validation: llmValidation,
  })
}

// ── Feed API ──────────────────────────────────────────────────────────────────

/**
 * User preference filters forwarded to the feed endpoint.
 * Only affects the Matches page — Analytics always uses raw data.
 */
export interface FeedPreferences {
  /** Server-side: hide jobs whose match_score is below this floor (0 = off) */
  minScore?:      number
  /** Client-side: comma-separated "remote|hybrid|onsite"; [] = all */
  workModes?:     string[]
  /** Client-side: comma-separated region keys; [] = all */
  regions?:       string[]
  /** Client-side: comma-separated "startup|growth|enterprise"; [] = all */
  companyStages?: string[]
}

export async function fetchFeedJobs(
  status?: string,
  limit  = 100,
  prefs?: FeedPreferences,
): Promise<ApiFeedJob[]> {
  const params = new URLSearchParams({ limit: String(limit) })
  if (status) params.set('status', status)
  // min_score is applied server-side (simple numeric WHERE clause)
  if (prefs?.minScore && prefs.minScore > 0) params.set('min_score', String(prefs.minScore))
  return get<ApiFeedJob[]>(`/api/jobs/feed?${params}`)
}

export async function refreshFeedScores(): Promise<RefreshResponse> {
  return post<null, RefreshResponse>('/api/jobs/feed/refresh', null)
}

export async function forceRefreshAllScores(): Promise<RefreshResponse> {
  return post<null, RefreshResponse>('/api/jobs/feed/refresh-all', null)
}

/** Poll the analysis state for a single job. Cheap — returns only why_ron + proxy flag + failure count. */
export async function fetchJobAnalysis(jobId: string): Promise<JobAnalysisState> {
  return get<JobAnalysisState>(`/api/jobs/${encodeURIComponent(jobId)}/analysis`)
}

export async function updateJobStatus(jobId: string, status: JobStatus): Promise<void> {
  await patch<{ status: JobStatus }, unknown>(`/api/jobs/${jobId}/status`, { status })
}

/**
 * Fetch the full JD text for a single job, save it, and trigger a rescore.
 * Runs synchronously on the server (~1-3 s). Returns the scraped text and
 * updated match_score so the card can update in place without a full reload.
 */
export async function fetchJobJd(jobId: string): Promise<FetchJdResponse> {
  return post<null, FetchJdResponse>(`/api/jobs/${encodeURIComponent(jobId)}/fetch-jd`, null)
}

export async function backfillJdText(minScore = 50.0): Promise<BackfillResponse> {
  await _ensureFreshToken()
  const url = `${BASE}/api/jobs/feed/backfill-jd?min_score=${minScore}`
  console.log('[backfillJdText] POST', url, '— no body, no Content-Type')

  const res = await fetch(url, {
    method: 'POST',
    headers: _authHeaders(),
    // No body, no Content-Type — endpoint reads min_score from query string only
  })

  if (!res.ok) {
    const errText = await res.text().catch(() => '(unreadable)')
    console.error('[backfillJdText] failed', res.status, errText)
    throw new Error(`backfill-jd ${res.status}: ${errText}`)
  }

  return res.json() as Promise<BackfillResponse>
}

// ── Truth-check verification (multi-turn chat) ───────────────────────────────

export async function sendVerifyChat(
  jobId:   string,
  history: VerifyChatEntry[],
): Promise<VerifyChatResponse> {
  return post<object, VerifyChatResponse>(
    `/api/jobs/${jobId}/verify/chat`,
    { history },
  )
}

/**
 * Generate (or return cached) a focused CV-tailoring brief for a job.
 * Calls POST /api/jobs/{job_id}/tailor-cv.
 * Pass forceRefresh=true to bypass the cache and re-generate.
 */
export async function tailorCvForJob(
  jobId:        string,
  forceRefresh: boolean = false,
): Promise<TailorBriefResponse> {
  const params = forceRefresh ? '?force_refresh=true' : ''
  return post<null, TailorBriefResponse>(
    `/api/jobs/${encodeURIComponent(jobId)}/tailor-cv${params}`,
    null,
    90_000,
  )
}

/**
 * CV Copilot: apply a natural-language editing instruction to tailored sections.
 * Calls POST /api/jobs/{job_id}/tailor-cv/edit.
 */
export async function editTailoredCv(
  jobId:       string,
  sections:    import('./apiTypes').TailoredSection[],
  instruction: string,
): Promise<import('./apiTypes').TailorEditResponse> {
  return post<import('./apiTypes').TailorEditRequest, import('./apiTypes').TailorEditResponse>(
    `/api/jobs/${encodeURIComponent(jobId)}/tailor-cv/edit`,
    { sections, instruction },
    90_000,
  )
}

// ── Profile Interview (Conversational Onboarding) ────────────────────────────

/**
 * Optional context hints the frontend can pass at session start.
 * The backend reads authoritative data from USER_PROFILE directly,
 * so these are only used as a fallback (e.g. when profile data is unavailable)
 * or when a real auth system is wired up in the future.
 */
export interface StartInterviewContext {
  user_name?:    string   // full name or given name
  current_role?: string   // most recent role + company as a plain string
  intent?:       string   // optional flow override, e.g. 'optimize_gaps'
}

export async function startInterview(context?: StartInterviewContext): Promise<InterviewSession> {
  return post<StartInterviewContext, InterviewSession>(
    '/api/profile/interview/start',
    context ?? {},
  )
}

export async function sendInterviewMessage(
  sessionId: string,
  message:   string,
): Promise<InterviewSession> {
  return post<{ session_id: string; message: string }, InterviewSession>(
    '/api/profile/interview/message',
    { session_id: sessionId, message },
  )
}

export async function getInterviewSession(sessionId: string): Promise<InterviewSession> {
  return get<InterviewSession>(`/api/profile/interview/${sessionId}`)
}

/**
 * Resume an existing interview session.
 * The backend generates a context-aware "Resume & Status" message summarising
 * captured data, strengths, gaps, and the next question, then appends it to
 * the session history.  Returns the updated full session state.
 */
export async function resumeInterviewSession(sessionId: string): Promise<InterviewSession> {
  return post<Record<string, never>, InterviewSession>(
    `/api/profile/interview/${sessionId}/resume`,
    {},
  )
}

export async function uploadVerificationDocument(
  sessionId: string,
  claim:     string,
  docType:   string,
  file:      File,
): Promise<{ verification: VerificationResult; session_id: string }> {
  await _ensureFreshToken()
  const fd = new FormData()
  fd.append('claim',    claim)
  fd.append('doc_type', docType)
  fd.append('file',     file)
  const res = await fetch(`${BASE}/api/profile/interview/${sessionId}/upload`, {
    method:  'POST',
    headers: _authHeaders(),
    body:    fd,
  })
  if (!res.ok) await _handleHttpError(res, `/api/profile/interview/${sessionId}/upload`)
  return res.json()
}

// ── Onboarding role/seniority preferences ─────────────────────────────────────

export type SeniorityLevel = 'junior' | 'entry' | 'mid' | 'senior' | 'lead' | 'director' | 'executive'

export interface RoleSeniorityItem {
  role:      string
  seniority: SeniorityLevel
}

export interface RolePreferences {
  roles: RoleSeniorityItem[]
}

/** Persist onboarding target roles, each with its own seniority (used by job matching). */
export async function saveRolePreferences(prefs: RolePreferences): Promise<void> {
  await post<RolePreferences, { status: string }>('/api/profile/preferences', prefs)
}

/** Fetch the saved role/seniority preferences (empty arrays when unset). */
export async function fetchRolePreferences(): Promise<RolePreferences> {
  const data = await get<{ roles: RoleSeniorityItem[] }>('/api/profile/preferences')
  return { roles: data.roles ?? [] }
}

export interface LinkedInImportResponse {
  status:   string
  imported: boolean
  message:  string
}

/** Stub LinkedIn import — stores the URL server-side; no scraping yet. */
export async function importLinkedInProfile(linkedinUrl: string): Promise<LinkedInImportResponse> {
  return post<{ linkedin_url: string }, LinkedInImportResponse>(
    '/api/profile/linkedin-import',
    { linkedin_url: linkedinUrl },
  )
}

// ── CV upload & aggregation ───────────────────────────────────────────────────

export interface CvClaimsResult {
  skills:      string[]
  experiences: { company: string; role: string; start: string; end: string; summary: string }[]
  education:   { degree: string; institution: string; years: string }[]
  summary:     string
}

export interface CvUploadResponse {
  status:    string
  processed: string[]
  errors:    string[]
  cv_claims: CvClaimsResult
}

/**
 * Upload one or more CV files (PDF/DOCX) for aggregation.
 * The backend extracts text, deduplicates via LLM, and persists cv_claims
 * to the user's profile so Jonathan can use them during gap-analysis.
 */
export async function uploadCvFiles(files: File[]): Promise<CvUploadResponse> {
  await _ensureFreshToken()
  const fd = new FormData()
  for (const file of files) {
    fd.append('files', file)
  }
  let res: Response
  try {
    res = await fetch(`${BASE}/api/profile/cv-upload`, {
      method:  'POST',
      headers: _authHeaders(),
      body:    fd,
    })
  } catch (err) {
    if (err instanceof TypeError) {
      throw new Error('Could not reach the server — is the backend running? (network error)')
    }
    throw err
  }
  if (!res.ok) await _handleHttpError(res, "/api/profile/cv-upload")
  return res.json()
}

// ── Outreach message generation ───────────────────────────────────────────────

export async function generateOutreachMessage(req: OutreachRequest): Promise<OutreachResponse> {
  return post<OutreachRequest, OutreachResponse>('/api/outreach/message', req)
}

export async function generateHeadhunterMessage(req: HeadhunterRequest): Promise<OutreachResponse> {
  return post<HeadhunterRequest, OutreachResponse>('/api/outreach/headhunter', req)
}

// ── Phase 3: job-anchored outreach (generate + persist + fetch) ───────────────
// Both go through the internal get/post helpers, which already await
// _ensureFreshToken() before attaching auth — no token race.

export interface JobOutreachResponse {
  job_id:        string
  outreach_text: string | null
  word_count:    number
}

/** POST — generate + persist the hiring-manager outreach message for a job. */
export async function generateJobOutreach(jobId: string): Promise<JobOutreachResponse> {
  return postEmpty<JobOutreachResponse>(`/api/outreach/generate/${jobId}`)
}

/** GET — the persisted outreach message for a job (outreach_text=null if none). */
export async function fetchJobOutreach(jobId: string): Promise<JobOutreachResponse> {
  return get<JobOutreachResponse>(`/api/outreach/${jobId}`)
}

// ── Direct Pitch Generator (JOB-64) ───────────────────────────────────────────
// Stateless — not persisted server-side; the frontend holds/edits the text.

export interface PitchResponse {
  job_id:     string
  pitch:      string
  word_count: number
}

/** POST — generate a short direct recruiter pitch for a job. */
export async function generateDirectPitch(jobId: string): Promise<PitchResponse> {
  return postEmpty<PitchResponse>(`/api/outreach/pitch/${jobId}`)
}

// ── Ariel Mock Interview Simulator (JOB-61) ───────────────────────────────────
// Stateless: the modal holds the session (question + answer) locally.

export interface InterviewQuestionResponse {
  job_id:   string
  question: string
}

export interface InterviewFeedbackResponse {
  job_id:   string
  feedback: string
}

/** POST — one targeted mock-interview question for this job. */
export async function generateInterviewQuestion(jobId: string): Promise<InterviewQuestionResponse> {
  return postEmpty<InterviewQuestionResponse>(`/api/jobs/${jobId}/interview/question`)
}

/** POST — constructive feedback on the candidate's answer. */
export async function evaluateInterviewAnswer(
  jobId: string,
  question: string,
  answer: string,
): Promise<InterviewFeedbackResponse> {
  return post<{ question: string; answer: string }, InterviewFeedbackResponse>(
    `/api/jobs/${jobId}/interview/answer`,
    { question, answer },
  )
}

// ── CRM Kanban ────────────────────────────────────────────────────────────────

export async function fetchCrmBoard(): Promise<CrmBoard> {
  return get<CrmBoard>('/api/crm/board')
}

export interface AppListItem {
  application_id: string
  job_id:         string
  company:        string
  title:          string
  status:         string
  last_update:    string
  score:          number
}

export async function fetchApplicationsList(): Promise<AppListItem[]> {
  // No trailing slash — see the comment on the backend's list_applications
  // route for why this exact match (on both ends) matters: a slash mismatch
  // here triggers a Next.js + FastAPI redirect round-trip that leaks the
  // internal Docker hostname into a Location header the browser can't resolve.
  return get<AppListItem[]>('/api/applications')
}

export async function moveCrmCard(applicationId: string, toStage: string): Promise<void> {
  await post<object, unknown>('/api/crm/move', {
    application_id: applicationId,
    to_stage:       toStage,
  })
}

export async function deleteApplication(applicationId: string): Promise<void> {
  await del<{ deleted: boolean }>(`/api/applications/${applicationId}`)
}

// ── LinkedIn scraped jobs (All Jobs tab) ─────────────────────────────────────

export interface LinkedInJobItem {
  id:                 string
  linkedin_job_id:    string | null
  title:              string
  company:            string
  location:           string | null
  job_url:            string
  posted_text:        string | null
  exact_posted_text:  string | null
  applicants_text:    string | null
  seniority_level:    string | null
  employment_type:    string | null
  job_function:       string | null
  industries:         string[] | null
  company_logo_url:   string | null
  linkedin_status:    string
  is_active:          boolean | null
  insertion_time:     string
  first_seen_at:      string
  last_seen_at:       string
  updated_at:         string
}

export interface PaginationMeta {
  page:          number
  page_size:     number
  total_items:   number
  total_pages:   number
  has_next:      boolean
  has_previous:  boolean
}

export interface LinkedInJobsPage {
  items:      LinkedInJobItem[]
  pagination: PaginationMeta
}

export async function fetchLinkedInJobs(
  page: number,
  pageSize: number,
  signal?: AbortSignal,
): Promise<LinkedInJobsPage> {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  return get<LinkedInJobsPage>(`/api/linkedin/jobs?${params}`, signal)
}

// ── Canonical, cross-provider jobs (All Jobs tab — public.all_jobs) ─────────
// Distinct from LinkedInJobItem/linkedin.jobs above: this is the normalized
// table designed to hold multiple providers via `source`, not LinkedIn's
// raw scraped shape. See backend/models/all_jobs.py.

export interface AllJobItem {
  id:                 string
  source:             string
  source_job_id:      string | null
  canonical_job_key:  string
  job_title:          string | null
  company_name:       string | null
  company_name_normalized: string | null
  company_url:        string | null
  company_logo_url:   string | null
  job_url:            string
  normalized_job_url: string
  location:           { city: string | null; district: string | null; country: string | null } | null
  seniority_level:    string | null
  employment_type:    string | null
  job_function:       string[] | null
  industries:         string[] | null
  description:        string | null
  posted_text:        string | null
  exact_posted_text:  string | null
  posted_at:          string | null
  applicants:         { value: number | null; exact: boolean } | null
  first_seen_at:      string
  last_seen_at:       string
  insertion_time:     string
  updated_at:         string
  last_scraped_at:    string | null
}

export interface AllJobsPage {
  items:      AllJobItem[]
  pagination: PaginationMeta
}

// Every field optional/AND-combined server-side (see backend/repositories/
// all_jobs_repository.py's AllJobsFilters) — omit a field entirely rather
// than passing '' when it's unset, so the query string stays clean.
// source/seniority_level/employment_type/job_function/industry are
// multi-select (OR'd within the field server-side) — each becomes a
// repeated query param, e.g. ?seniority_level=A&seniority_level=B.
export interface AllJobsFilters {
  source?:              string[]
  seniority_level?:     string[]
  employment_type?:     string[]
  job_function?:        string[]
  industry?:            string[]
  company?:             string
  title?:               string
  min_applicants?:      number
  max_applicants?:      number
  posted_within_hours?: number
}

export type AllJobsSortBy = 'recent' | 'posted' | 'applicants_desc' | 'applicants_asc' | 'company'

export interface AllJobsFilterOptions {
  sources:           string[]
  seniority_levels:  string[]
  employment_types:  string[]
  job_functions:     string[]
  industries:        string[]
}

export async function fetchAllJobs(
  page: number,
  pageSize: number,
  filters?: AllJobsFilters,
  sortBy?: AllJobsSortBy,
  signal?: AbortSignal,
): Promise<AllJobsPage> {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  if (sortBy) params.set('sort_by', sortBy)
  if (filters) {
    for (const [key, value] of Object.entries(filters)) {
      if (value === undefined || value === null || value === '') continue
      if (Array.isArray(value)) {
        for (const v of value) params.append(key, v)
      } else {
        params.set(key, String(value))
      }
    }
  }
  return get<AllJobsPage>(`/api/all-jobs?${params}`, signal)
}

export async function fetchAllJobsFilterOptions(signal?: AbortSignal): Promise<AllJobsFilterOptions> {
  return get<AllJobsFilterOptions>('/api/all-jobs/filter-options', signal)
}

export async function markJobApplied(jobId: string): Promise<MarkAppliedResponse> {
  return post<object, MarkAppliedResponse>('/api/applications/mark-applied', { job_id: jobId })
}

// ── Gmail verification code polling ───────────────────────────────────────────

export interface GmailVerificationCodeResponse {
  code:        string | null
  captured_at: string | null
}

/** Thrown by fetchGmailVerificationCode() specifically on a 403 (admin-only
 * endpoint, caller is not an admin) so pollers can stop retrying instead of
 * treating it like a transient network error. */
export class GmailCodeForbiddenError extends Error {}

export async function fetchGmailVerificationCode(): Promise<GmailVerificationCodeResponse> {
  await ensureFreshToken()
  const res = await fetch(`${BASE}/api/settings/gmail-verification-code`, {
    cache:   'no-store',
    headers: getAuthHeaders(),
  })
  if (res.status === 403) {
    throw new GmailCodeForbiddenError('Admin access required for gmail-verification-code.')
  }
  if (!res.ok) await _handleHttpError(res, '/api/settings/gmail-verification-code')
  return res.json() as Promise<GmailVerificationCodeResponse>
}

// ── Analytics ─────────────────────────────────────────────────────────────────

export interface AnalyticsSummary {
  total_applications:        number
  active_processes:          number
  interview_conversion_rate: number
  funnel_stages:             Array<{ stage: string; count: number }>
  top_companies:             Array<{ company: string; count: number }>
  top_keywords:              Array<{ keyword: string; count: number }>
}

export async function fetchAnalyticsSummary(): Promise<AnalyticsSummary> {
  return get<AnalyticsSummary>('/api/analytics/summary')
}

// ── Analytics overview (Overview dashboard daily KPIs) ────────────────────────
// Daily activity snapshot — the two "today" counters reset at UTC midnight;
// average_match_score is the stable lifetime quality signal.

export interface AnalyticsOverview {
  jobs_scanned_today:  number
  actions_taken_today: number
  average_match_score: number
}

/** Thrown on HTTP 429 so callers can render a "busy" state instead of an error. */
export class RateLimitError extends Error {
  constructor() {
    super('Rate limit exceeded')
    this.name = 'RateLimitError'
  }
}

/**
 * GET /api/analytics/overview — direct fetch (not the get<> wrapper) so a 429
 * can be surfaced as RateLimitError without tripping the global auth-error
 * sign-out. ensureFreshToken() runs first to avoid the mount-time empty-token
 * race (see _ensureFreshToken docs above).
 */
export async function fetchAnalyticsOverview(): Promise<AnalyticsOverview> {
  await ensureFreshToken()
  const res = await fetch(`${BASE}/api/analytics/overview`, {
    headers: getAuthHeaders(),
    cache:   'no-store',
  })
  if (res.status === 429) throw new RateLimitError()
  if (!res.ok) throw new Error(`analytics/overview HTTP ${res.status}`)
  return res.json() as Promise<AnalyticsOverview>
}

// ── ATS keyword extraction ────────────────────────────────────────────────────

export async function fetchAtsKeywords(jobId: string): Promise<AtsKeywordsResponse> {
  return post<Record<string, never>, AtsKeywordsResponse>(`/api/jobs/${jobId}/ats-keywords`, {})
}

// ── Active Skills Gap Analysis (JOB-59) ───────────────────────────────────────
// Stateless — free-text LLM analysis, not persisted.

export interface SkillsGapResponse {
  job_id:   string
  analysis: string
}

export async function fetchSkillsGap(jobId: string): Promise<SkillsGapResponse> {
  return post<Record<string, never>, SkillsGapResponse>(`/api/jobs/${jobId}/skills-gap`, {})
}

// ── LinkedIn scraper status ───────────────────────────────────────────────────

export interface ScraperStatus {
  status:        'ok' | 'suspicious' | 'BLOCKED' | 'PAUSED'
  blocked_at:    string | null
  cookie_status: string | null
}

export async function fetchScraperStatus(): Promise<ScraperStatus> {
  await _ensureFreshToken()
  const res = await fetch(`${BASE}/api/settings/scraper-status`, {
    headers: getAuthHeaders(),
    cache:   'no-store',
  })
  if (!res.ok) throw new Error(`scraper-status HTTP ${res.status}`)
  return res.json() as Promise<ScraperStatus>
}

// ─────────────────────────────────────────────────────────────────────────────

/** Normalise the API shape to the frontend Job type used throughout the UI. */
export function normaliseJob(m: ApiJobMatch, rank: number): Job {
  return {
    id:         m.job_id,
    title:      m.title,
    company:    m.company,
    location:   m.location,
    postedAt:   m.posted_at,
    postedRank: rank,
    score:      m.score,
    isNew:      m.is_new,
    reasons:    m.reasons,
    whyRon:     m.why_ron,
  }
}
