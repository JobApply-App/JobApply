from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel

JobSource  = Literal['automatic', 'manual']
SourceType = Literal['linkedin', 'company_site', 'other']
# 'analysing' = job persisted but pipeline (JD structuring + composite ATS
# scoring) not yet finished.  Presentational gate; never a terminal state.
JobStatus  = Literal['new', 'saved', 'ignored', 'applied', 'analysing', 'auth_wall']
JobLocale  = Literal['he', 'en']   # BCP-47 primary tag; None = unknown


class RawJobPosting(BaseModel):
    id: str
    title: str
    company: str
    source_url: str
    raw_text: str
    scraped_at: str


class JobAnalysis(BaseModel):
    job_id: str
    required_skills: list[str]
    nice_to_have_skills: list[str]
    seniority_level: Literal["junior", "mid", "senior", "staff", "principal"]
    is_remote: bool
    location: str
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    summary: str


class CompanyResearch(BaseModel):
    """
    Structured output of research_company(). Populated by a real web-search
    integration in production; currently returned as a structured placeholder.
    """
    company_name: str
    estimated_headcount: str        # e.g. "~40 employees", "10 000+"
    maturity_stage: str             # e.g. "Series B", "Public / NYSE", "Bootstrapped"
    public_reputation: str          # synthesised Glassdoor / LinkedIn / press vibe
    employee_profile: str           # what kind of people typically thrive there
    known_red_flags: list[str]      # layoffs, toxic-culture reviews, revolving-door pattern
    data_confidence: Literal["high", "medium", "low", "placeholder"]


class ReasonTag(BaseModel):
    kind: Literal["skill", "exp", "loc", "neg"]
    label: str


class DetailedAnalysis(BaseModel):
    strengths: list[str]
    critical_gaps: list[str]
    strategic_advice: list[str]


class JobMatch(BaseModel):
    job_id: str
    title: str
    company: str
    location: str
    score: float
    confidence_score: int
    culture_fit_score: int
    trajectory_alignment: str
    company_dna_inference: str
    detailed_analysis: DetailedAnalysis
    investigation_points: list[str]
    reasons: list[ReasonTag]
    apply_url: Optional[str] = None
    is_new: bool = True
    posted_at: str = ""
    why_ron: Optional[str] = None
    scoring_rationale: Optional[str] = None
    category: Optional[str] = None
    applied: bool = False
    applied_at: Optional[str] = None
    source: JobSource = 'automatic'
    is_open: bool = True
    # Raw employer JD text — stored at match time so match scoring never
    # reads AI-generated analysis fields as if they were employer requirements.
    jd_text: Optional[str] = None
    # LLM-structured JD as a JSON string produced by jd_structure_service.
    jd_structured: Optional[str] = None
    # ── Multi-user & feed fields ──────────────────────────────────────────────
    user_id:              str             = "default"
    source_type:          SourceType      = 'other'
    company_website_url:  Optional[str]   = None
    # Workflow status (independent of the existing applied/is_new flags)
    status:               JobStatus       = 'new'
    # ATS keyword match score (0-100) from compute_match_score_async.
    # Distinct from the AI-generated fit `score` above.
    match_score:          float           = 0.0
    # True when match_score is only the fast Phase A proxy (title+seniority),
    # i.e. the LLM-backed Phase B has not yet run.  Set to False after Phase B.
    score_is_proxy:       bool            = True
    # Derived at read-time by the feed endpoint; not stored in DB.
    is_direct_application: Optional[bool] = None
    # True when this job came from the LinkedIn Bulk Import CLI pipeline
    # (job_id prefixed "li-bulk-") rather than a live scraper run. Purely
    # presentational — deliberately NOT source_type, so it never affects
    # _source_rank()/cross-board dedup priority in job_store.py (JOB-92).
    # Derived at read-time by the feed endpoint; not stored in DB.
    is_bulk_import: Optional[bool] = None
    # True when a tailored CV has been generated and cached for this job.
    # Derived at read-time; not stored in DB.
    has_tailored_cv: bool = False
    # Incremented each time the s2 LLM enrichment pass produces a non-substantive
    # result for this job.  Exposed to the UI so it can show a hard-failure state
    # instead of an infinite skeleton after 3 failures.
    enrichment_failures: int = 0
    # ISO-8601 UTC timestamp set on first insert; used for feed tie-breaking.
    created_at:           Optional[str]   = None
    # BCP-47 primary language tag ('he' | 'en' | None).
    # Set by scrapers that know the source language (e.g. Israeli boards → 'he').
    # Drives RTL rendering priority in the UI without requiring per-char detection.
    locale:               Optional[str]   = None
    
    # ── JOB-20: Dynamic culture fit scoring dimensions ────────────────────────
    culture_delta:        Optional[float] = None
    culture_alignment:    Optional[float] = None
    culture_category:     Optional[str]   = None
    culture_note:         Optional[str]   = None
