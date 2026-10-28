// Viewer accessibility preferences for components/AccessibilityMenu.tsx.
// Plain .ts (no JSX) so it is unit-testable under vitest.
//
// Settings live in localStorage (per browser, per device) and are applied to
// <html>/<body>: classes for CSS-only adjustments (globals.css, "a11y-*"),
// inline filter/zoom for the rest. A filter on the ROOT element does not
// break position:fixed descendants (the spec exempts the root), so the chat
// launcher and dialogs keep working.

export type FontSize = 'small' | 'medium' | 'large'

export interface A11ySettings {
  font:           FontSize
  contrast:       boolean
  grayscale:      boolean
  noAnimation:    boolean
  highlightLinks: boolean
  readableFont:   boolean
  focusRing:      boolean
}

export const DEFAULT_A11Y: A11ySettings = {
  font: 'medium', contrast: false, grayscale: false, noAnimation: false,
  highlightLinks: false, readableFont: false, focusRing: false,
}

const STORAGE_KEY = 'ja_a11y'
const ZOOM: Record<FontSize, string> = { small: '0.9', medium: '', large: '1.2' }

export function loadA11y(): A11ySettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? { ...DEFAULT_A11Y, ...JSON.parse(raw) } : DEFAULT_A11Y
  } catch {
    return DEFAULT_A11Y
  }
}

export function applyA11y(s: A11ySettings, doc: Document = document): void {
  const root = doc.documentElement
  root.classList.toggle('a11y-no-animation',    s.noAnimation)
  root.classList.toggle('a11y-highlight-links', s.highlightLinks)
  root.classList.toggle('a11y-readable-font',   s.readableFont)
  root.classList.toggle('a11y-focus-ring',      s.focusRing)
  const filters = [s.contrast && 'contrast(1.35)', s.grayscale && 'grayscale(1)'].filter(Boolean)
  root.style.filter = filters.join(' ')
  // Most text sizes in this app are fixed px, so scaling the root font-size
  // would miss them; zoom scales everything consistently.
  doc.body.style.setProperty('zoom', ZOOM[s.font])
}

export function saveA11y(s: A11ySettings): void {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(s)) } catch { /* private mode / storage blocked */ }
}
