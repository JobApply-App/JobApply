'use client'

/** The arrow inside a search field, opening its list without typing anything. */
export function ComboChevron({ open, label, onToggle, disabled }: {
  open:     boolean
  label:    string
  onToggle: () => void
  disabled?: boolean
}) {
  return (
    <button type="button" tabIndex={-1} aria-label={label} disabled={disabled}
      // Keep focus in the field, so its blur does not close what this just opened.
      onMouseDown={e => { e.preventDefault(); onToggle() }}
      className="absolute inset-y-0 end-1 flex w-10 items-center justify-center text-slate-500 hover:text-slate-900 disabled:opacity-40">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"
        aria-hidden="true" className={`transition-transform duration-ja-ui ${open ? 'rotate-180' : ''}`}>
        <polyline points="6 9 12 15 18 9" />
      </svg>
    </button>
  )
}
