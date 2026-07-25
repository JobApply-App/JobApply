/** TypeScript mirrors of the FastAPI Pydantic models. */

// ── B2C types ─────────────────────────────────────────────────────────────────

/**
 * Bullet-level skills-gap entry from match_score_service.py's
 * _map_bullet_matches(). Addressed by position — (experience_index,
 * bullet_index) — NOT a ParsedBullet.id: the backend has no notion of the
 * frontend's content-hashed bullet ids (lib/cv.ts), since the wire-format
 * CvData sends bullets as plain strings. Resolve to a stable id via
 * `cv.experience[experience_index].bullets[bullet_index].id` (lib/cv.ts)
 * when keying Ariel's per-bullet analysis off something persistent.
 */
export interface BulletMatch {
  experience_index:  number
  bullet_index:       number
  matched_terms:      string[]
  seniority_aligned:  boolean
}

export interface MatchScoreResult {
  total:               number
  keyword_overlap:     number
  skills_alignment:    number
  seniority_alignment: number
  matched_keywords:    string[]
  missing_keywords:    string[]
  matched_skills:      string[]
  missing_skills:      string[]
  suggestions:         string[]
  llm_validated:       boolean
  /** Skills Gap Analysis at bullet granularity — always populated,
   *  LLM-independent, never truncated. See BulletMatch for id resolution. */
  bullet_matches:      BulletMatch[]

  // ── JOB-20: Dynamic culture fit scoring dimensions ───────────────────────
  culture_delta:       number | null
  culture_alignment:   number | null
  culture_category:    string | null
  culture_note:        string | null
}

export interface TemplateInfo {
  id:          string
  name:        string
  description: string
}

export interface TailorOkResponse {
  status:             'ok'
  cv_data:            Record<string, unknown>
  pdf_b64:            string
  match_score:        MatchScoreResult | null
  preferred_template: string
}

export interface TailorMissingResponse {
  status:                'missing_data'
  missing_data_requests: Array<{ id: string; question: string; context?: string }>
}

export type TailorApiResponse = TailorOkResponse | TailorMissingResponse

export type AgentState = 'active' | 'idle' | 'queued' | 'error' | 'paused'
export type AgentName  =
  | 'Scraper'
  | 'Sourcing Specialist'
  | 'Content Strategist'
  | 'Quality Guard'

/** Request body for POST /api/jobs/analyze */
export interface AnalyzeRequest { url: string }

/** Response from POST /api/jobs/analyze */
export interface AnalyzeResponse { status: string; message: string }

export interface ApiAgentStats {
  today: number
  queue: number
  spark: number[]
}

export interface ApiAgentStatus {
  id: string
  name: AgentName
  role: string
  state: AgentState
  current_task:  string | null
  queue_msg:     string | null
  error_msg:     string | null
  stats: ApiAgentStats
}

export type ReasonKind = 'skill' | 'exp' | 'loc' | 'neg'

export interface ApiReasonTag {
  kind:  ReasonKind
  label: string
}

export interface ApiJobMatch {
  job_id:    string
  title:     string
  company:   string
  location:  string
  score:     number
  reasons:   ApiReasonTag[]
  apply_url: string | null
  is_new:    boolean
  posted_at: string
  why_ron:   string | null
}

// ── Multi-source Feed types ───────────────────────────────────────────────────

export type JobSourceType = 'linkedin' | 'company_site' | 'other'
/**
 * 'new'       — fully analysed and ready; the default active state.
 * 'analysing' — pipeline incomplete: jd_structured is null OR score_is_proxy is true.
 *               Derived dynamically by job_store._from_row — never written to DB directly.
 * 'saved'     — user bookmarked the job.
 * 'applied'   — user confirmed they applied.
 * 'ignored'   — user dismissed the job (filtered from feed).
 */
export type JobStatus     = 'new' | 'saved' | 'ignored' | 'applied' | 'analysing' | 'auth_wall'

// ── CRM Kanban ────────────────────────────────────────────────────────────────

export interface CrmCard {
  application_id: string
  job_id:         string
  company:        string
  title:          string
  last_update:    string
  score:          number
}

export interface CrmColumn {
  stage:  string
  label:  string
  cards:  CrmCard[]
}

export interface CrmBoard {
  columns: CrmColumn[]
}

export interface MarkAppliedResponse {
  application_id: string
  job_id:         string
  company:        string
  title:          string
  status:         string
  created:        boolean
}

/** Shape returned by GET /api/jobs/feed — extends ApiJobMatch with feed fields. */
export interface ApiFeedJob {
  job_id:                string
  title:                 string
  company:               string
  location:              string
  score:                 number          // AI fit score from MatcherAgent
  match_score:           number          // ATS keyword score (0-100)
  score_is_proxy:        boolean         // true = Phase A only; LLM Phase B not yet run
  source_type:           JobSourceType
  company_website_url:   string | null
  status:                JobStatus
  user_id:               string
  is_direct_application: boolean | null
  is_bulk_import:        boolean | null  // true if job_id is prefixed "li-bulk-" (LinkedIn Bulk Import CLI)
  apply_url:             string | null
  is_new:                boolean
  posted_at:             string
  created_at:            string | null
  reasons:               ApiReasonTag[]
  why_ron:               string | null
  jd_text:               string | null   // raw JD text; null until backfill runs
  jd_structured:         string | null   // LLM-structured JSON string; null until structure pass runs
  /** BCP-47 primary tag: 'he' | 'en' | null.
   *  Set by Israeli-board scrapers to enable RTL-priority rendering
   *  without per-character Hebrew detection on every field. */
  locale:                string | null
  /** True when a tailored CV has been generated and cached for this job. */
  has_tailored_cv:       boolean
  /** How many times s2 LLM enrichment returned a non-substantive result. */
  enrichment_failures:   number

  // ── JOB-20: Dynamic culture fit scoring dimensions ───────────────────────
  culture_delta:         number | null
  culture_alignment:     number | null
  culture_category:      string | null
  culture_note:          string | null
}

export interface JobAnalysisState {
  job_id:              string
  why_ron:             string | null
  score_is_proxy:      boolean
  enrichment_failures: number
}

export interface BackfillResponse {
  status:  string
  queued:  number
  message: string
}

/** Response from POST /api/jobs/{job_id}/fetch-jd */
export interface FetchJdResponse {
  job_id:          string
  jd_text:         string | null
  new_match_score: number | null
  /** False when a real ATS score was computed in this call; true when rescore failed/skipped. */
  score_is_proxy:  boolean
  /** LLM-structured JSON string from this call; null when structuring was skipped or failed. */
  jd_structured:   string | null
}

export interface RefreshResponse {
  status:  string
  scored:  number
  message: string
}

// ── Tailor CV brief ──────────────────────────────────────────────────────────

export interface TailoredSection {
  role:    string
  company: string
  dates:   string
  bullets: string[]
}

/** Response from POST /api/jobs/{job_id}/tailor-cv */
export interface TailorBriefResponse {
  job_id:              string
  job_title:           string
  company:             string
  generated_at:        string
  positioning_summary: string
  tailored_sections:   TailoredSection[]
  cached:              boolean
}

// ── CV Copilot — inline section editor ──────────────────────────────────────

export interface TailorEditRequest {
  sections:    TailoredSection[]
  instruction: string
}

export interface TailorEditResponse {
  sections: TailoredSection[]
  reply:    string
}

// ── Truth-check verification (multi-turn chat) ───────────────────────────────

export interface VerifyChatEntry {
  role:           'agent' | 'user'
  content:        string
  gap_addressed?: string
  raw?:           string   // raw JSON from agent turn — sent back for context reconstruction
}

export type VerifyChatStatus = 'question' | 'verified' | 'failed'

export interface VerifyChatResponse {
  status:               VerifyChatStatus
  question?:            string
  gap_addressed?:       string
  raw?:                 string
  fit_score_adjustment?: number
  new_fit_score?:        number
  cv_advice?:            string | null
  summary?:              string
}

// ── Outreach message generation ───────────────────────────────────────────────

export type OutreachMessageType = 'consultation' | 'escalation' | 'headhunter'

export interface OutreachRequest {
  message_type:   OutreachMessageType
  target_name:    string
  target_title:   string
  target_company: string
  context?:       string
  job_id?:        string
}

export interface OutreachResponse {
  message_type: string
  message:      string
  word_count:   number
}

export interface HeadhunterRequest {
  recruiter_name:  string
  recruiter_title?: string
  agency_name:     string
  context?:        string
}

// ── Profile Interview (Conversational Onboarding) ────────────────────────────

export interface InterviewMessage {
  role:    'user' | 'assistant'
  content: string
  ts:      string
}

export interface ConfidenceClaim {
  score:           number   // 15 | 30 | 60 | 75 | 100
  status:          'incomplete' | 'unverified' | 'consistent' | 'document_pending' | 'verified'
  missing_details: string[]
  evidence:        string | null
  label:           string
}

export interface DocRequest {
  for_claim:     string
  document_type: string
}

export interface InterviewSession {
  session_id:     string
  messages:       InterviewMessage[]
  draft_profile:  Record<string, unknown> | null
  confidence_map: Record<string, ConfidenceClaim>
  pending_probes: string[]
  doc_request:    DocRequest | null
  status:         'active' | 'complete' | 'abandoned'
}

export interface VerificationResult {
  status:          'verified' | 'partial' | 'failed' | 'unreadable'
  confidence:      number | null
  match_notes:     string
  extracted_facts: Record<string, string | null>
}

// ── ATS Keyword extraction ────────────────────────────────────────────────────

export interface AtsKeywordsResponse {
  job_title:   string
  company:     string
  jd_keywords: string[]
  present:     string[]
  missing:     string[]
}

// ── Trust / Confidence Matrix ─────────────────────────────────────────────────

/** One evidence_records row, surface-summarised for the UI. */
export interface TrustEvidenceEntry {
  evidence_id:    string
  source_type:    string
  /** Human-readable label, e.g. "STAR Behavioral Probe" */
  source_label:   string
  verified_at:    string       // ISO-8601
  raw_content:    string | null
  base_weight:    number
  is_ai_assisted: boolean
}

export type EntityType       = 'skill' | 'trait' | 'domain' | 'experience'
export type SkillTier        = 'Core_Mastery' | 'System_Orchestration' | null
export type VerificationLevel = 'VERIFIED_MANUAL' | 'ORCHESTRATION_ONLY' | 'UNVERIFIED'

/** One profile_entities row with its full evidence ledger. */
export interface TrustProfileEntity {
  entity_id:               string
  name:                    string
  entity_type:             EntityType
  confidence_score:        number   // 0–100  blended final score
  verification_status:     string   // 'verified' | 'partial' | 'needs_evidence' | 'unverified'
  manual_review_required:  boolean
  skill_tier:              SkillTier
  // Decoupled truth-based scores
  architecture_confidence: number   // 0–100  portfolio / STAR / CV evidence
  syntax_confidence:       number   // 0–100  manual_assessment evidence only
  verification_level:      VerificationLevel
  // Dynamic trust model (optional — absent on entities loaded before v2 scoring)
  evidence_multiplier?:    number   // 0.5–1.0 dynamic weight based on engagement
  evidence_count?:         number   // AI-verified challenge count
  trust_breakdown:         TrustEvidenceEntry[]
}

/** Response from GET /api/profile/{user_id}/trust-score */
export interface TrustScoreResponse {
  user_id:          string
  entities:         TrustProfileEntity[]
  category_averages: {
    skill:      number
    trait:      number
    domain:     number
    experience: number
  }
  /** Weighted composite 0-100 from ProfileUpdateService.compute_profile_trust_score. */
  overall_trust_score: number
  /** Three-pillar breakdown of the Holistic Familiarity score (Phase 32).
   *  Maxes: breadth 40, depth 40, context 20. Optional for backward-compat with
   *  any cached/older response shape. */
  score_breakdown?: ScoreBreakdown
  fetched_at: string
}

/** Holistic Familiarity sub-scores. breadth+depth+context ≈ overall_trust_score. */
export interface ScoreBreakdown {
  breadth: number   // 0-40  — volume of extracted landscape data
  depth:   number   // 0-40  — verified claims + honest proficiency levels
  context: number   // 0-20  — profile completeness + AI interaction
}

// ── Confidence Matrix (four semantic categories) ──────────────────────────────

export type MatrixCategory =
  | 'Technical'
  | 'Product_Leadership'
  | 'Data_Analysis'
  | 'Customer_Success'

export interface ConfidenceEntityBreakdown {
  entity_id:               string
  name:                    string
  category:                MatrixCategory
  score:                   number
  architecture_confidence: number
  syntax_confidence:       number
  verification_level:      VerificationLevel
  skill_tier:              SkillTier
}

export interface ConfidenceRadarDatum {
  category:   string
  value:      number   // blended final
  arch_value: number   // Architecture_Confidence avg for category
  syn_value:  number   // Syntax_Confidence avg for category
}

/** Response from GET /api/profile/{user_id}/confidence-matrix */
export interface ConfidenceMatrixResponse {
  user_id:          string
  radar_data:       ConfidenceRadarDatum[]
  entity_breakdown: ConfidenceEntityBreakdown[]
  computed_at:      string
}
