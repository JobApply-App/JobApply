export const TOKENS = {
  color: {
    bg:          '#F8FAFC',   // slate-50 — editorial canvas
    surface:     '#FFFFFF',
    ink:         '#0F172A',   // slate-900
    ink2:        '#334155',   // slate-700
    muted:       '#64748B',   // slate-500
    subtle:      '#94A3B8',   // slate-400
    line:        '#E2E8F0',   // slate-200 — crisp borders
    lineSoft:    '#F1F5F9',   // slate-100
    primary:     '#0D9488',   // teal-600 — deep teal
    primaryHover:'#0F766E',   // teal-700
    primarySoft: '#F0FDFA',   // teal-50
    // Semantic — MUST mirror the --ja-* vars in globals.css exactly
    success:     '#059669',   // emerald-600
    warn:        '#D97706',   // amber-600
    danger:      '#DC2626',   // red-600
    violet:      '#7C3AED',   // violet-600 — tertiary accent (KPIs, quick actions)
    // Meridian V2 §2.2/§2.4 — mirrors --ja-gradient-intelligence in globals.css
    gradientIntelligence: 'linear-gradient(135deg, #7C3AED 0%, #0D9488 100%)',
  },
  shadow: {
    card: '0 1px 3px rgba(15,23,42,0.06), 0 1px 2px rgba(15,23,42,0.04)',
    // Meridian V2 §2.4 — mirrors --ja-glow-ai; reserved for Ariel's identity
    // anchors (panel header, welcome screen) — not per-message repetition.
    glowAi: '0 4px 24px rgba(124,58,237,0.35)',
  },
}

export type Tone = 'success' | 'warn' | 'danger' | 'muted' | 'primary'
