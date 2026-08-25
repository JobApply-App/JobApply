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
