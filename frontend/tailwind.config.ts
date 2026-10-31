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
        // --font-latin (Inter) first, --font-hebrew (Assistant) right behind
        // it: Inter has no Hebrew glyphs, so Hebrew text falls through to
        // Assistant instead of to an arbitrary system font. Both variables
        // are set on <body> in app/layout.tsx.
        sans: [
          'var(--font-latin)', 'var(--font-hebrew)',
          'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif',
        ],
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
        // 2026-11 redesign: the shadows are tinted with slate ink and the
        // harbor teal instead of pure black, and each tier adds a long, soft
        // drop. Surfaces read as lifted off the page, not outlined on it.
        // Mirrors --ja-elevation-* in globals.css.
        'elevation-1': [
          '0 1px 2px rgba(15,23,42,0.05)',
          '0 2px 6px -2px rgba(15,23,42,0.06)',
        ].join(', '),
        'elevation-2': [
          '0 1px 2px rgba(15,23,42,0.06)',
          '0 8px 16px -8px rgba(15,23,42,0.08)',
          '0 24px 48px -28px rgba(19,78,74,0.22)',
        ].join(', '),
        'floating': [
          '0 1px 2px rgba(15,23,42,0.06)',
          '0 14px 28px -14px rgba(19,78,74,0.28)',
          '0 40px 70px -36px rgba(19,78,74,0.28)',
          '0 1px 0px rgba(255,255,255,0.8) inset',
        ].join(', '),
        // legacy alias — preserves existing uses of shadow-card
        'card': '0 1px 2px rgba(15,23,42,0.05), 0 2px 6px -2px rgba(15,23,42,0.06)',
      },
      // Apple-style ease-out: fast start, long gentle settle. Replaces
      // Tailwind's default curve, so every `transition` class in the app
      // moves on it without touching the components.
      transitionTimingFunction: {
        DEFAULT: 'cubic-bezier(0.23, 1, 0.32, 1)',
        'ja-out': 'cubic-bezier(0.23, 1, 0.32, 1)',
        'ja-in-out': 'cubic-bezier(0.65, 0, 0.35, 1)',
      },
      transitionDuration: {
        DEFAULT: '180ms',
        'ja-press': '120ms',
        'ja-ui': '240ms',
        'ja-enter': '400ms',
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
        // Meridian V2 §8 — canonical modal entrance, shared by every modal.
        // 2026-11: rises a few pixels while it scales, on the ja-out curve,
        // so the panel arrives like a sheet instead of popping in place.
        'modal-in': {
          '0%':   { opacity: '0', transform: 'translateY(8px) scale(0.96)' },
          '100%': { opacity: '1', transform: 'translateY(0) scale(1)' },
        },
        // Backdrop behind a modal: fades, never moves.
        'ja-fade': {
          '0%':   { opacity: '0' },
          '100%': { opacity: '1' },
        },
        // Content arriving in place (a section, a card, a toast).
        'ja-rise': {
          '0%':   { opacity: '0', transform: 'translateY(12px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        // Bottom sheet on phones: slides up from the edge it leaves by.
        'ja-sheet-up': {
          '0%':   { transform: 'translateY(100%)' },
          '100%': { transform: 'translateY(0)' },
        },
      },
      animation: {
        'modal-in':    'modal-in 260ms cubic-bezier(0.23, 1, 0.32, 1)',
        'ja-fade':     'ja-fade 200ms cubic-bezier(0.23, 1, 0.32, 1)',
        'ja-rise':     'ja-rise 400ms cubic-bezier(0.23, 1, 0.32, 1) both',
        'ja-sheet-up': 'ja-sheet-up 320ms cubic-bezier(0.23, 1, 0.32, 1)',
      },
    },
  },
  plugins: [],
}

export default config
