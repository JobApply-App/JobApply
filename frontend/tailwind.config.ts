import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
      },
      colors: {
        ja: {
          // ── Canvas & surface ──────────────────────────────────────────────
          bg:         '#F8FAFC',   // slate-50  — cool page canvas
          surface:    '#FFFFFF',   // pure white card / panel
          surfaceHover: '#F8FAFC', // subtle hover state for interactive surfaces

          // ── Text ─────────────────────────────────────────────────────────
          ink:        '#0F172A',   // slate-900 — primary text
          ink2:       '#334155',   // slate-700 — secondary text
          muted:      '#64748B',   // slate-500 — labels, captions
          subtle:     '#94A3B8',   // slate-400 — placeholders, disabled

          // ── Borders & dividers ────────────────────────────────────────────
          line:       '#E2E8F0',   // slate-200 — standard dividers / card borders
          lineSoft:   '#F1F5F9',   // slate-100 — ultra-subtle inner separators

          // ── Brand ─────────────────────────────────────────────────────────
          primary:       '#0D9488',   // teal-600 — serene, modern, non-corporate
          primaryHover:  '#0F766E',   // teal-700 — ~5% darker on hover
          primarySubtle: '#F0FDFA',   // teal-50  — selected states, pill bg

          // ── Semantic feedback (mirrors --ja-* vars in globals.css) ────────
          success:       '#059669',   // emerald-600
          successSubtle: '#ECFDF5',   // emerald-50
          warn:          '#D97706',   // amber-600
          warnSubtle:    '#FFFBEB',   // amber-50
          danger:        '#DC2626',   // red-600
          dangerSubtle:  '#FEF2F2',   // red-50

          // ── Fixed brand constants ─────────────────────────────────────────
          linkedin:      '#0A66C2',   // LinkedIn brand blue — external constant
          inkDeep:       '#0A1F1C',   // near-black teal — dark hero/auth gradient stop

          // ── V2 'Meridian' — Abyss / Harbor (dark anchor tier) ──────────────
          harbor:        '#134E4A',   // teal-900 — authoritative fills, dark-surface buttons

          // ── V2 'Meridian' — Amethyst (AI voice) ────────────────────────────
          ai:            '#7C3AED',   // violet-600 — Ariel identity, AI-generated content
          aiSubtle:      '#F5F3FF',   // violet-50  — AI-surface fills
          support:       '#4F46E5',   // indigo-600 — Eliya support chat only

          // ── V2 'Meridian' — Electric Emerald (verification) ────────────────
          verified:      '#10B981',   // emerald-500 — live/verified signals, high-match pulses
        },
      },
      maxWidth: {
        content: '1120px',
      },
      boxShadow: {
        // ── Elevation system (layered, Intercom-grade) ─────────────────────
        //    Each tier stacks a diffuse ambient layer with a tighter key layer.
        //    Keep all alpha values low so cards look lifted, not heavy.
        'elevation-1': [
          '0 1px 2px rgba(0,0,0,0.04)',
          '0 1px 4px rgba(0,0,0,0.06)',
        ].join(', '),
        'elevation-2': [
          '0 2px 4px rgba(0,0,0,0.04)',
          '0 4px 12px rgba(0,0,0,0.08)',
        ].join(', '),
        'floating': [
          '0 4px 6px rgba(0,0,0,0.04)',
          '0 12px 32px rgba(0,0,0,0.12)',
          '0 1px 0px rgba(255,255,255,0.8) inset',
        ].join(', '),
        // legacy alias — preserves existing uses of shadow-card
        'card': '0 1px 2px rgba(0,0,0,0.04), 0 1px 4px rgba(0,0,0,0.06)',
      },
      borderRadius: {
        // explicit semantic radius tokens
        'sm':  '6px',
        'md':  '8px',
        'lg':  '12px',
        'xl':  '16px',
        '2xl': '20px',
      },
      keyframes: {
        // Meridian V2 §8 — canonical modal entrance: fade + scale, 200ms.
        // Single shared definition so every modal panel animates identically.
        'modal-in': {
          '0%':   { opacity: '0', transform: 'scale(0.96)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
      },
      animation: {
        'modal-in': 'modal-in 200ms ease-out',
      },
    },
  },
  plugins: [],
}

export default config
