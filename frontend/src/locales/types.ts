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
