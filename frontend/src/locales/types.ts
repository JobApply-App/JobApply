// ── Dictionary type ────────────────────────────────────────────────────────────
//
// Every key in Dict must have an entry in BOTH en.ts and he.ts.
// TypeScript enforces this at compile time via the `satisfies Dict` check.

/**
 * Error codes the UI explains. Server codes mirror backend/core/errors.py
 * CODES (test_error_catalog.py keeps the two in sync); the last four are
 * raised in the browser. docs/error-catalog.md is the readable table.
 */
export const ERROR_CODES = [
  'auth_required', 'session_expired', 'forbidden', 'admin_only', 'dev_only', 'auth_not_configured',
  'rate_limited', 'daily_cv_limit', 'daily_chat_limit', 'linkedin_quota',
  'job_not_found', 'application_not_found', 'session_not_found', 'item_not_found', 'task_expired',
  'invalid_input', 'empty_message', 'invalid_linkedin_url', 'file_too_large', 'unsupported_file',
  'legacy_doc', 'file_mismatch', 'conflict',
  'posting_closed', 'linkedin_login_wall', 'linkedin_blocked', 'linkedin_job_not_found',
  'linkedin_unavailable', 'scrape_failed', 'scrape_empty', 'job_no_description', 'job_no_url',
  'analysis_failed',
  'ai_unavailable', 'ai_failed', 'ai_bad_output',
  'pdf_unavailable', 'pdf_failed',
  'service_unavailable', 'server_error',
  // Browser-side
  'network', 'timeout', 'stream_interrupted', 'unknown',
] as const
export type ErrorCode = (typeof ERROR_CODES)[number]

export const ERROR_FEATURES = [
  'chat', 'cv_tailoring', 'cv_generation', 'cv_edit', 'cv_revision', 'interview', 'outreach',
  'research', 'verification', 'ats_keywords', 'skills_gap', 'match_scoring', 'analysis',
] as const
export type ErrorFeature = (typeof ERROR_FEATURES)[number]

/** What the user sees: what happened, why, and what to do about it. */
export interface ErrorEntry {
  title:  string
  why:    string
  action: string
}

export interface Dict {
  errors: {
    codes:    Record<ErrorCode, ErrorEntry>
    /** Names for {feature} in ai_failed ("the CV tailoring"). */
    features: Record<ErrorFeature, string>
  }
  common: {
    undo: string
    retry: string
    sort: string
    template: string
    not_applied: string
    cv_copilot: string
    support: string
    terms: string
    privacy: string
    auth_errors: {
      unavailable: string
      invalid_credentials: string
      email_not_confirmed: string
      weak_password: string
      rate_limited: string
      invalid_code: string
    }
  }
  landing: {
    nav: {
      sign_in:     string
      get_started: string
    }
    hero: {
      eyebrow:        string
      h1_line1:       string
      h1_line2:       string
      sub:            string
      cta_primary:    string
      cta_secondary:  string
      no_credit_card: string
    }
    social_proof: {
      heading: string
      stats: ReadonlyArray<{ num: string; label: string }>
    }
    section_a: {
      step:    string
      h2_l1:   string
      h2_l2:   string
      body:    string
      bullets: readonly [string, string, string]
    }
    section_b: {
      step:    string
      h2_l1:   string
      h2_l2:   string
      body:    string
      bullets: readonly [string, string, string]
    }
    section_c: {
      step:    string
      h2_l1:   string
      h2_l2:   string
      body:    string
      bullets: readonly [string, string, string]
    }
    bento: {
      eyebrow: string
      h2_l1:   string
      h2_l2:   string
      cards: ReadonlyArray<{ title: string; body: string }>
    }
    cta_final: {
      h2:     string
      body:   string
      button: string
    }
    footer: {
      cols: ReadonlyArray<{ heading: string; links: readonly string[] }>
      copyright: string
    }
  }
  login: {
    left: {
      quote_l1: string
      quote_l2: string
      sub:      string
      metrics:  ReadonlyArray<{ value: string; label: string }>
    }
    card: {
      welcome_back:         string
      create_account_title: string
      sign_in_sub:          string
      sign_up_sub:          string
      continue_google:      string
      redirecting:          string
      or:                   string
      full_name_label:      string
      full_name_placeholder:string
      email_label:          string
      password_label:       string
      show_password:        string
      hide_password:        string
      sign_in_btn:          string
      signing_in:           string
      create_account_btn:   string
      creating_account:     string
      name_required:        string
      stronger_password:    string
      no_account:           string
      have_account:         string
      sign_up_link:         string
      sign_in_link:         string
      // Strength meter — index matches score (0–4)
      strength_labels: readonly [string, string, string, string, string]
      strength_hint:   string
    }
    // Copy the sign-in page actually renders. Kept separate from `card`
    // above, which was written against an earlier design and no longer
    // matches what is on screen.
    page: {
      hero_eyebrow:     string
      hero_headline:    string
      hero_subline:     string
      back_to_home:     string
      back:             string
      back_to_sign_in:  string
      get_started:      string
      sign_in_title:    string
      sign_in_sub:      string
      forgot_password:  string
      or_sign_in_email: string
      email_placeholder:string
    }
    // Password-reset flow: request a code, enter it, choose a new password.
    reset: {
      request_title:    string
      request_sub:      string
      send_code:        string
      sending:          string
      otp_title:        string
      otp_digit_label:  string   // takes the digit position, e.g. "ספרה {n}"
      verify_code:      string
      verifying:        string
      resend_code:      string
      code_sent:        string   // takes the email address, e.g. "נשלח קוד אל {email}"
      new_pw_title:     string
      new_pw_sub:       string
      new_pw_label:     string
      new_pw_placeholder: string
      save_and_sign_in: string
      saving:           string
    }
    // User-facing failure messages. In the dictionary rather than inline so
    // a Hebrew user does not get an English error at the moment something
    // has already gone wrong for them.
    errors: {
      sign_in_failed:      string
      google_failed:       string
      send_code_failed:    string
      no_account:          string
      enter_all_digits:    string
      invalid_code:        string
      stronger_password:   string
      update_password_failed: string
    }
  }
  // Score-band labels, keyed by ScoreBandKey (see lib/scoreBand.ts). The
  // keys and thresholds stay in code; only the display labels translate.
  tour: {
    step_of: string
    next: string
    back: string
    skip: string
    done: string
    replay: string
    steps: ReadonlyArray<{ title: string; body: string }>
  }
  header: {
    nav: { overview: string; feed: string; apps: string; all_jobs: string
           capabilities: string; analytics: string }
    open_menu:    string
    close_menu:   string
    help_title:   string
    help_label:   string
    notifications:string
    profile_prefs:string
    force_reset:  string
    force_reset_title: string
    sign_out:     string
    preferences: string
    alerts_title: string
    alerts_empty: string
    profile_builder: string
    mobile_tabs_label: string
  }
  footer: {
    coming_soon:  string
    operational:  string
    help:         string
    privacy:      string
    contact:      string
    accessibility:string
  }
  overview: {
    greeting_morning:   string
    greeting_afternoon: string
    greeting_evening:   string
    greeting_night:     string
    // Greeting and subline are separate sentences on purpose: the name is
    // interpolated into the first, and Hebrew orders them differently.
    greeting:           string   // takes {greeting} and {name}
    subline:            string
    refreshing:         string
    as_of:              string   // takes {time}
    confidence_title:   string
    confidence_body:    string
    confidence_tooltip: string
    improve_with_ariel: string
    pillars: {
      breadth: { label: string; caption: string; hint: string }
      depth:   { label: string; caption: string; hint: string }
      context: { label: string; caption: string; hint: string }
    }
    // Wording for the score band on this screen is softer than the feed's:
    // it describes profile progress, not a job match.
    bands: { exceptional: string; strong: string; moderate: string; weak: string; poor: string }
    glance_title:       string
    kpi: {
      scanned:  { label: string; sub: string }
      actions:  { label: string; sub: string }
      avg:      { label: string; sub: string }
    }
    analytics_rate_limited: string
    analytics_failed:       string
    quick_actions:      string
    actions: {
      review:      { label: string; sub: string }
      strengthen:  { label: string; sub: string }
      update_cv:   { label: string; sub: string }
      preferences: { label: string; sub: string }
    }
    top_matches:   string
    no_matches:    string
    linkedin_blocked:      string
    linkedin_maintenance:  string
    linkedin_maintenance_body: string
    qa_review: string
    qa_review_sub: string
    qa_profile: string
    qa_profile_sub: string
    qa_cv: string
    qa_cv_sub: string
    qa_prefs: string
    qa_prefs_sub: string
    improve_score_topic: string
    see_all: string
  }
  live_editor: {
    title:            string
    unsaved:          string
    reset:            string
    reset_title:      string
    save:             string
    saving:           string
    add_skill:        string
    sections: {
      summary: string; experience: string; military: string
      volunteering: string; skills: string
    }
    summary_aria:     string
    volunteering_aria:string
    military_note:    string
  }
  applier: {
    close_preview:    string
    cv_language:      string
    cv_language_regen_hint: string
    edit_cv:          string
    back_to_preview:  string
    approve_apply:    string
    regenerate:       string
    empty_title:      string
    empty_body:       string   // takes {cta}
    generate_cv:      string
    pct_match:        string   // takes {pct}
    title:            string
    subtitle:         string
    additional_info:  string
    answer_placeholder: string
    generating:       string
    save_continue:    string
    skip_all:         string
    skip_all_title:   string
    // Rotating status lines shown while the CV is being written.
    loading_statuses: readonly [string, string, string, string]
    unsaved_draft:    string
    save_to_profile:  string
    saving:           string
    copilot_placeholder: string
    copilot_editing:  string
    apply_edit:       string
    evaluating:       string
    fill_form:        string
    one_detail:       string
    answer_hint_one:  string
    answer_hint_many: string
    submitting:       string
    mobile_ready_title: string
    mobile_ready_body:  string
    n_details:        string   // takes {n}
    download_pdf:     string
    download_title:   string
    preparing:        string
    errors: {
      timeout:        string
      still_loading:  string
      save_failed:    string
      save_draft_failed: string
      download_failed:string
      copilot_failed: string
      edit_applied:   string
    }
    core_questions: {
      core_name: {
        q: string
        ctx: string
      }
      core_phone: {
        q: string
        ctx: string
      }
      core_location: {
        q: string
        ctx: string
      }
    }
  }
  legal: {
    draft_label:   string
    draft_body:    string
    last_updated:  string   // takes {date}
    back_to_signup:string
    contact:       string
    privacy_title: string
    terms_title:   string
    updated_date:  string
  }
  controls: {
    close:            string
    match_filters:    string
    matches_only:     string
    min_score:        string
    work_mode:        string
    all_modes:        string
    location:         string
    all_regions:      string
    company_stage:    string
    all_stages:       string
    alerts:           string
    reset:            string
    saved:            string
    save:             string
    unlimited:        string
    modes:    { hybrid: string; remote: string; onsite: string }
    regions:  { tel_aviv: string; central: string; sharon: string; haifa: string; jerusalem: string; south: string }
    stages:   { startup: string; growth: string; enterprise: string }
    cadence: {
      immediate_label: string; immediate_sub: string
      daily_label:     string; daily_sub:     string
      weekly_label:    string; weekly_sub:    string
      off_label:       string; off_sub:       string
    }
    title: string
    score_off: string
    score_all: string
    score_hiding: string
    radius: string
  }
  outreach: {
    title:            string
    close:            string
    copy:             string
    copied:           string
    hint_hm:          string
    words:            string
    strategy_title:   string
    hint_after_reply: string
    hint_steps:       string
    hint_agency:      string
    extra_context:    string
    extra_ph:         string
    generation_failed:string
    default_recruiter:string
    name_recruiter:   string
    name_manager:     string
    company_agency:   string
    company_their:    string
    title_escalation: string
    title_recruiter:  string
    title_manager:    string
    ph_escalation:    string
    ph_recruiter:     string
    ph_manager:       string
    tabs: {
      hm_label:         string; hm_sub:         string; hm_badge:         string
      step1_label:      string; step1_sub:      string; step1_badge:      string
      step2_label:      string; step2_sub:      string; step2_badge:      string
      headhunter_label: string; headhunter_sub: string; headhunter_badge: string
    }
    generating: string
    loading: string
    regenerate: string
    generate: string
    hm_saved: string
    differs_title: string
    differs_1a: string
    differs_1b: string
    differs_1c: string
    differs_2: string
    differs_3: string
  }
  trust: {
    confidence_matrix:   string
    confidence_radar:    string
    subtitle:            string
    top_capabilities:    string
    view_all:            string
    back_to_dashboard:   string
    evidence_ledger:     string
    recent_changes:      string
    score_reasoning:     string
    improvement_tips:    string
    improve_with_ariel:  string
    evaluated_by_ariel:  string
    none_in_category:    string
    refresh:             string
    retry:               string
    verify:              string
    strengthen:          string
    review:              string
    resubmit:            string
    why_flagged:         string
    whiteboard:          string
    attach_evidence:     string
    evidence_attached:   string
    drop_file:           string
    reply_no_ai:         string
    linkedin_expired:    string
    fix_connection:      string
    answer_placeholder:  string
    loading_label:       string
    close_challenge:     string
    remove_attachment:   string
    tips: {
      verify_locked:     string
      start_probe:       string
      view_flagged:      string
      attach_file:       string
      attach_screenshot: string
      ai_assisted:       string
      no_verified_yet:   string
    }
    bands:   { high: string; medium: string; low: string; unverified: string }
    entity:  { skill: string; trait: string; domain: string; experience: string }
    sources: {
      cv_parse: string
      self_assertion: string
      contextual_reinforcement: string
      certification: string
      portfolio: string
      conversation_star: string
      negative_flag: string
    }
    vl: {
      manual: string
      manual_title: string
      arch: string
      arch_title: string
      none: string
      none_title: string
    }
    tier: {
      core: string
      core_title: string
      orch: string
      orch_title: string
    }
    flags: {
      contradiction: string
      shallow_star: string
      inconsistency: string
      flag: string
    }
    pill: {
      verified: string
      unverified_hint: string
      validate_domain: string
      validate_experience: string
      validate_trait: string
      validate_skill: string
    }
    insights: {
      score: string
      weight_one: string
      weight_many: string
      verified: string
      orch_only: string
      unverified: string
      review_flagged: string
      tip_baseline: string
      tip_strengthen: string
      tip_arch: string
      tip_syntax: string
      tip_strong: string
    }
    no_evidence_yet: string
    ai_aug: string
    manual_review: string
    confidence_of: string
    upload_evidence_hint: string
    uploaded_refreshing: string
    uploading: string
    choose_file: string
    retry_answer: string
    strengthen_trust: string
    evidence_recorded: string
    shallow_detected: string
    confidence_updated: string
    flagged_as: string
    remove_attachment_named: string
    analysing_star: string
    cmd_submit: string
    review_one: string
    review_many: string
    review_body: string
    review_link: string
    cv_uploaded: string
    cv_uploaded_stats: string
    loading_matrix: string
    uploading_extracting: string
    upload_to_start: string
    extract_explainer: string
    weight_aria: string
    improve_topic: string
    score_breakdown: string
    score_breakdown_named: string
    no_ai_assist: string
    close: string
    preparing: string
    ready_verify: string
    challenge_intro: string
    initialising: string
    attachment_preview: string
    accept_challenge: string
    load_failed: string
    load_caps_failed: string
    probe_start_failed: string
    caps_title: string
    caps_subtitle: string
    caps_failed: string
    caps_failed_body: string
    try_again: string
    error_id: string
    persist_hint: string
    improve_hint: string
    explainer: {
      title: string
      body: string
      start: string
      raise: string
    }
    radar: {
      arch: string
      syntax: string
      blended: string
      legend_arch: string
      legend_syntax: string
      loading: string
      pending: string
      categories: {
        Technical: string
        Product_Leadership: string
        Data_Analysis: string
        Customer_Success: string
      }
    }
    verification: {
      verified: string
      orchestration: string
      baseline: string
    }
    sort: {
      label: string
      score_desc: string
      needs_verification: string
      category: string
    }
    filter: {
      all: string
      skill: string
      trait: string
      domain: string
      experience: string
    }
    verify_mastery: string
    orch_score: string
    weight_tip: string
    weight_tip_basis: string
    probe: {
      interview_for: string
      question: string
      analysing: string
      sending: string
      finish: string
      next: string
      ariel_question: string
      request_failed: string
      steps: {
        STAR: string
        SCOPE: string
        SIGNAL: string
      }
    }
  }
  score_bands: {
    exceptional: string
    strong:      string
    moderate:    string
    weak:        string
    poor:        string
  }
  job_card: {
    sources: { linkedin: string; company_site: string; other: string }
    direct_title:      string
    bulk_import:       string
    bulk_import_title: string
    // JD section headings, keyed by the backend's section keys.
    jd_sections: {
      company_details:  string
      role_overview:    string
      responsibilities: string
      requirements:     string
      advantages:       string
      additional_info:  string
    }
    collapse:          string
    see_more:          string
    generating_label:  string
    generating_body:   string
    analysis_unavailable_title: string
    analysis_unavailable_body:  string   // takes {attempts}
    analyzing:         string
    probe_failed:      string
    card_label:        string   // takes {title}, {company}, {action}
    expand:            string
    collapse_action:   string
    unknown_company:   string
    new_badge:         string
    exceptional_match: string
    strong_match:      string
    provisional_score: string
    tailor_cv:         string
    outreach:          string
    direct_pitch:      string
    mock_interview:    string
    mock_ready:        string
    mock_needs_jd:     string
    view_jd:           string
    hide_jd:           string
    listing:           string
    applied:           string
    saving:            string
    mark_applied:      string
    jd_heading:        string
    no_description:    string
    skills_gap:        string
    auth_wall_title: string
    auth_wall_body: string
    analyze_failed: string
    analyze_job: string
    insight_no_entity: string
    insight_high: string
    insight_title: string
    insight_label: string
    ariel_analysis: string
    view_original: string
    ats_breakdown: string
    fetch_jd_first: string
    jd_first_short: string
    ats_needs_jd: string
    analysing_kw: string
    kw_injected: string
    kw_excluded: string
    confidence_snapshot: string
    no_kw: string
    gap_needs_jd: string
    gap_failed: string
    analysing_gaps: string
    save: string
    saved: string
    skip: string
    below_threshold: string
  }
  ariel: {
    name:            string
    role:            string
    launcher_title:  string
    launcher_label:  string
    launcher_cta:    string
    job_context:     string
    continue_recent: string
    continue_hint:   string
    start_new:       string
    what_work_on:    string
    input_start:     string
    input_reply:     string
    quick_actions: ReadonlyArray<{ label: string; desc: string; prompt: string }>
    tagline: string
    capabilities_title: string
    launcher_sub: string
    intro: string
    intro_dismiss: string
    intro_open: string
    msg: {
      copy: string; copied: string; reply: string; translate: string
      regenerate: string; pin: string; unpin: string; report: string; delete: string
      show_original: string; show_translation: string
    }
    history_close_label: string
    close:           string
    minimize:        string
    minimize_label:  string
    close_label:     string
    minimize_hint:   string
    history_title:   string
    new_conversation:string
    remove:          string
    attach:          string
    stop:            string
    send:            string
    generic_error:   string
    attached_files:  string
    no_history: string
    msgs_one: string
    msgs_many: string
    empty_convo: string
    active: string
    greet: string
    greet_roles: string
    greet_stage: string
    list_and: string
    role_with_level: string
    replying_to: string
    cancel_reply: string
    preview_named: string
    preview_attachment: string
    seniority: {
      junior: string
      entry: string
      mid: string
      senior: string
      lead: string
      director: string
      executive: string
    }
    stages: {
      student: string
      junior: string
      mid: string
      senior: string
      management: string
    }
    history: string
    err_rate_limited: string
  }
  support_chat: {
    name:            string
    role:            string
    greeting_title:  string
    greeting_body:   string
    placeholder:     string
    clear:           string
    close:           string
    close_label:     string
    attach:          string
    send:            string
    remove:          string
    resize:          string
    resize_label:    string
    launcher_label:  string
    generic_error:   string
    attached_files:  string
    suggestions: ReadonlyArray<{ label: string; prompt: string }>
    tool_labels: { tailor_resume_for_job: string }
    tailoring_started: string
    confirm_generate:  string
    cancel:            string
    focus_skills: string
    no_response: string
    attach_title: string
    err_rate_limited: string
  }
  discover: {
    // LinkedIn's fixed English seniority / job-function values → UI language.
    // Unknown values are shown as-is.
    linkedin_terms: Record<string, string>
    banner_title:    string
    banner_body:     string
    complete_cta:    string
    heading:         string
    subheading:      string
    roles_count:     string   // takes {n}
    teaser:          string
    unknown_company: string
    empty_title:     string
    empty_body:      string
    error_title:     string
    error_body:      string
  }
  job_feed: {
    heading:        string
    subheading:     string
    sync_title:     string
    syncing:        string
    sync_cta:       string
    url_placeholder:string
    analysing:      string
    analyse:        string
    search_placeholder: string
    clear_search_label: string
    sources: { all: string; company_site: string; linkedin: string; other: string }
    // Keyed by StatusFilter ('all' + every JobStatus). The tab row shows a
    // subset, but the empty-state message can name any of them, so all are
    // covered here — a missing key would render `undefined` to the user.
    statuses: {
      all: string; new: string; saved: string; applied: string
      ignored: string; analysing: string; auth_wall: string
    }
    sort_score:     string
    sort_date:      string
    top_fits:       string
    top_fits_on:    string   // takes {threshold}
    top_fits_off:   string
    sort_paused:    string
    sort_paused_label: string
    indexing_title: string
    indexing_body_one:  string   // takes {n}
    indexing_body_many: string   // takes {n}
    check_updates:  string
    empty_none_title: string
    empty_none_body:  string
    empty_title:      string
    empty_search:     string   // takes {query}
    empty_top_fits:   string   // takes {threshold}
    empty_status:     string   // takes {status}
    clear_search:     string
    show_all_scores:  string
    load_more:        string
    count_of:         string   // takes {shown} and {total}
    errors: {
      load_failed:    string
      sync_failed:    string
      analysis_failed:string
      skip_failed:    string
      update_failed:  string
      still_loading:  string
    }
    toast_synced_one: string
    toast_synced_many: string
    toast_rescored: string
    toast_added: string
    toast_applied: string
    load_feed_failed: string
    retry: string
  }
  match_score: {
    band_suffix:      string   // "{band} match"
    optimized_ats:    string
    boosted_from:     string   // takes {score}
    ai_validated:     string
    keyword_overlap:  string
    skills_alignment: string
    seniority_match:  string
    keywords_injected:string
    skills_excluded:  string
  }
  profile_chat: {
    empty_title:      string
    empty_body:       string
    draft_heading:    string
    education:        string
    experience:       string
    military:         string
    skills_mentioned: string
    degree_fallback:  string
    missing_prefix:   string   // "Missing: " + comma-joined details
    upload_transcript: string
    upload_letter:    string
    upload_discharge: string
    claims_summary:   string   // takes {claims} and {verified}
    restoring:        string
    optimize: {
      badge:     string
      title:     string
      body:      string
      features:  ReadonlyArray<{ label: string; sub: string }>
      analysing: string
      cta:       string
    }
    intro: {
      title:    string
      body:     string
      features: ReadonlyArray<{ label: string; sub: string }>
      starting: string
      cta:      string
    }
    accuracy_label: string
    disclaimer:     string
    upload_modal: {
      title:          string
      claim_label:    string
      analysing:      string
      drop_prompt:    string
      formats_hint:   string
      verified:       string
      partial:        string
      failed:         string
      unreadable:     string
      upload_failed:  string
      close:          string
      cancel:         string
    }
    composer: {
      placeholder:  string
      attach:       string
      new_session:  string
      specialist:   string
      send:         string
      send_failed:  string
    }
  }
  complete_profile: {
    welcome:        string   // takes {name}
    welcome_there:  string   // fallback name when none is known
    subtitle:       string
    setting_up:     string
    submit:         string
    generic_error:  string
  }
  profile_builder: {
    back:            string
    title:           string
    intro:           string
    upload_prompt:   string
    drop_prompt:     string
    upload_hint:     string
    uploading:       string
    analyzing:       string
    done_title:      string
    // Counts are interpolated as {roles} / {skills}; the singular and
    // plural variants are separate strings because the two languages
    // inflect differently.
    done_roles_one:   string
    done_roles_many:  string
    done_skills_one:  string
    done_skills_many: string
    done_summary:     string   // takes {roles} and {skills} phrases
    upload_failed:   string
    error_prefix:    string
    try_again:       string
    skip:            string
  }
  onboarding: {
    showcase: {
      title:    string
      subtitle: string
      selected: string
      cta:      string
      steps: ReadonlyArray<{ title: string; body: string }>
    }
    preferences: {
      title:            string
      intro:            string
      roles_label:      string
      role_placeholder: string
      add_custom_role:  string   // takes the typed role, {role}
      remove_role:      string   // takes the role name, {role}
      level_for_role:   string   // takes the role name, {role}
      pick_level:       string
      saving:           string
      continue_cta:     string
      skip:             string
      save_failed:      string
      // Seniority VALUES stay English in the database; only these labels
      // are translated. Indexed positionally against SENIORITY_OPTIONS.
      seniority: readonly [string, string, string, string, string, string]
      seniority_hint: readonly [string, string, string, string, string, string]
      level_heading: string
    }
    intake: {
      title:          string
      intro:          string
      upload_cta:     string
      upload_hint:    string
      cv_only_note:   string   // only CVs here; other documents later, via Ariel
      uploading_one:  string   // takes {n}
      uploading_many: string   // takes {n}
      analyzing:      string
      upload_failed:  string
      skip:           string
    }
  }
  signup: {
    page: {
      hero_eyebrow:   string
      back_to_login:  string
      back:           string
      log_in:         string
      title:          string
      subtitle:       string
      or_fill_details:string
      full_name:      string
      full_name_placeholder: string
      phone:          string
      career_stage:   string
      career_stage_selected: string
      email:          string
      email_placeholder: string
      account_exists: string
      log_in_here:    string
      password:       string
      password_placeholder: string
      creating:       string
      create_account: string
      have_account:   string
      sign_in:        string
      // Legal line is one sentence with two inline links, so it is stored
      // as the fragments between them rather than as a single string.
      legal_prefix:   string
      legal_terms:    string
      legal_middle:   string
      legal_privacy:  string
      legal_suffix:   string
    }
    errors: {
      sign_up_failed: string
      google_failed:  string
    }
    career_stages: ReadonlyArray<{ title: string; subtitle: string }>
    password_rules: readonly [string, string, string, string]
    password_levels: { weak: string; fair: string; strong: string }
    phone: {
      select_country_code: string
      phone_number:        string
      number_placeholder:  string
      select_country:      string
      search_country:      string
    }
  }
  auth_layout: {
    default_eyebrow:     string
    default_headline:    string
    default_subline:     string
    verifying: string
    link_invalid_title: string
    link_invalid_body: string
    redirecting: string
    creating_ws: string
    creating_ws_named: string
    setting_up: string
    language: string
    phone_invalid: string
    no_results: string
  }
  settings: {
    language: {
      heading:         string
      intro:           string
      interface_label: string
      interface_help:  string
      cv_label:        string
      cv_help:         string
      loading:         string
    }
  }
  // Static labels used inside the landing-page UI mockups
  mockup: {
    strong_match:    string
    ats_gap_title:   string
    missing_label:   string   // "{n}" = count of missing keywords
    present_label:   string   // "{n}" = count already in the profile
    coverage_hint:   string   // "{pct}" = share of the job's keywords already present
    sample_caption:  string
    score_hint:      string
    tailored_title:  string
    ai_written_sub:  string
    missing_kw:      string
    cv_copilot:      string
    auto_refreshes:  string
    coverage_label:  string   // role · company label inside keyword panel
    kpi_scanned: string
    kpi_scanned_sub: string
    kpi_high: string
    kpi_high_sub: string
    kpi_tailored: string
    kpi_tailored_sub: string
    sample_title: string
    sample_meta: string
    sample_loc: string
    feed_head: string
    feed_growth: string
    feed_lead: string
    remote: string
    match_pct: string
    tpl_classic: string
    tpl_modern: string
    tpl_compact: string
  }
  // Why a CV upload failed, keyed by the backend's stable error code
  // (backend/api/routes/profile.py _cv_error). Shared by every upload surface.
  cv_upload_errors: {
    no_text:            string   // scanned / image-only PDF
    unsupported_format: string
    too_large:          string
    too_many_files:     string
    no_files:           string
    not_a_cv:           string
    llm_unavailable:    string
    timeout:            string
    network:            string
    failed:             string
  }
  app_shell: {
    securing: string
    please_wait: string
  }
  applications: {
    title: string
    summary: string
    view_list: string
    view_board: string
    empty_title: string
    empty_body: string
    load_failed: string
    delete: string
    delete_title: string
    delete_confirm: string
    delete_failed: string
    stages: {
      submitted: string
      phone_screen: string
      technical: string
      interview: string
      offer: string
      rejected: string
    }
    close: string
    deleting: string
    move_to_stage: string
    move_to: string
    current: string
    updated: string
    column_empty: string
    drop_here: string
    moved_to: string
    move_undone: string
    move_failed: string
    delete_failed_reload: string
    loading_board: string
    board_failed: string
    board_count_one: string
    board_count_many: string
    board_hint: string
    refresh: string
  }
  agents: {
    running: string
    idle: string
    queued: string
    paused: string
    unavailable: string
    retry: string
    analyze_title: string
    analyze_sub: string
    url_placeholder: string
    analysing: string
    run: string
    added: string
    analysis_failed: string
    result: string
    live_status: string
    hero_title: string
    hero_body: string
    section_title: string
    section_sub: string
    run_pipeline: string
    done_title: string
    done_body: string
    failed_title: string
    failed_body: string
    dismiss: string
    start_failed: string
  }
  all_jobs: {
    title: string
    count_one: string
    count_many: string
    applicants_exact: string
    applicants_fewer: string
    applicants_one: string
    posted: string
    first_seen: string
    last_seen: string
    show_details: string
    hide_details: string
    logo_alt: string
    company_fallback: string
    load_failed: string
    retry: string
    empty: string
    no_options: string
    ph_company: string
    ph_title: string
    f_seniority: string
    f_employment: string
    f_function: string
    f_industry: string
    ph_min_app: string
    ph_max: string
    sort: string
    clear: string
    posted_any: string
    posted_24: string
    posted_72: string
    posted_168: string
    posted_720: string
    posted_within: string
    sort_recent: string
    sort_posted: string
    sort_app_desc: string
    sort_app_asc: string
    sort_company: string
    chip_company: string
    chip_title: string
    chip_applicants: string
    remove_filter: string
    showing: string
    per_page: string
    prev_page: string
    next_page: string
  }
  modals: {
    close: string
    retry: string
    words: string
    edited: string
    pitch_title: string
    pitch_intro: string
    pitch_writing: string
    pitch_failed: string
    regenerate: string
    copied: string
    copy: string
    mock_title: string
    question: string
    your_answer: string
    answer_ph: string
    evaluating: string
    submit_answer: string
    preparing_q: string
    evaluating_long: string
    feedback: string
    end_session: string
    revise: string
    next_q: string
    q_failed: string
    eval_failed: string
  }
  analytics: {
    empty_title: string
    empty_body: string
    browse: string
    load_failed: string
    title: string
    subtitle: string
    kpi_total: string
    kpi_total_sub: string
    kpi_active: string
    kpi_active_sub: string
    kpi_rate: string
    kpi_rate_sub: string
    funnel: string
    companies: string
    companies_empty: string
    skills: string
    skills_empty: string
  }
  cv_progress: {
    title: string
    step_uploading: string
    step_reading: string
    step_analyzing: string
    hint: string
  }
}
