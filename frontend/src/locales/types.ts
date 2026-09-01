// ── Dictionary type ────────────────────────────────────────────────────────────
//
// Every key in Dict must have an entry in BOTH en.ts and he.ts.
// TypeScript enforces this at compile time via the `satisfies Dict` check.

export interface Dict {
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
  }
  ariel: {
    name:            string
    role:            string
    launcher_title:  string
    launcher_label:  string
    job_context:     string
    continue_recent: string
    continue_hint:   string
    start_new:       string
    what_work_on:    string
    input_start:     string
    input_reply:     string
    quick_actions: ReadonlyArray<{ label: string; prompt: string }>
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
  }
  discover: {
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
    }
    intake: {
      title:          string
      intro:          string
      upload_cta:     string
      upload_hint:    string
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
    missing_prefix:  string   // "Missing from LinkedIn (3) —"
    missing_suffix:  string   // "add to your Skills section"
    present_prefix:  string   // "Already in your profile (5)"
    tailored_title:  string
    ai_written_sub:  string
    missing_kw:      string
    cv_copilot:      string
    auto_refreshes:  string
    coverage_label:  string   // role · company label inside keyword panel
  }
}
