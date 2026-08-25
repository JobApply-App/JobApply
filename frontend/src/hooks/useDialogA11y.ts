import { useEffect, useRef } from 'react'

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'textarea:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

function getFocusable(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
    // getClientRects().length === 0 for display:none and detached elements —
    // more reliable here than checking offsetParent, which is also null for
    // position:fixed elements (several of these dialogs use fixed wrappers).
    .filter(el => el.getClientRects().length > 0)
}

/**
 * The full WAI-ARIA APG dialog keyboard contract, in one hook:
 *
 *   - Escape closes the dialog.
 *   - Tab and Shift+Tab cycle only within the dialog, wrapping at the first
 *     and last focusable element — background content is unreachable by
 *     keyboard while the dialog is open.
 *   - Focus moves to the dialog's first focusable element as soon as it
 *     opens (the container itself as a fallback if it has none), and
 *     returns to whatever had focus before the dialog opened once it closes
 *     — a keyboard user's place in the page is never lost.
 *
 * `enabled` matters for components that stay mounted and toggle visibility
 * via `if (!open) return null` AFTER their hooks run (several sheets/modals
 * in this codebase do): without it, the listeners would stay attached — and
 * fire — even while the dialog is invisible. Pass the same `open` flag the
 * caller already has; defaults to true for the common case of a dialog that
 * only mounts while it's actually shown.
 */
export function useDialogA11y(
  onClose: () => void,
  containerRef: React.RefObject<HTMLElement>,
  enabled: boolean = true,
) {
  const triggerRef = useRef<HTMLElement | null>(null)

  // Capture whatever had focus before the dialog opened, move focus in, and
  // restore it on close.
  useEffect(() => {
    if (!enabled) return

    triggerRef.current = document.activeElement as HTMLElement | null
    const container = containerRef.current
    const [first] = container ? getFocusable(container) : []
    ;(first ?? container)?.focus()

    return () => {
      triggerRef.current?.focus?.()
    }
    // containerRef is a stable ref object — reading .current at the moment
    // this effect runs is the intended behavior, not a missing dependency.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled])

  // Escape + Tab-trap.
  useEffect(() => {
    if (!enabled) return

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        onClose()
        return
      }
      if (e.key !== 'Tab') return

      const container = containerRef.current
      if (!container) return
      const focusable = getFocusable(container)
      if (focusable.length === 0) {
        e.preventDefault()
        return
      }

      const first  = focusable[0]
      const last   = focusable[focusable.length - 1]
      const active = document.activeElement as HTMLElement | null

      if (e.shiftKey) {
        if (active === first || !active || !container.contains(active)) {
          e.preventDefault()
          last.focus()
        }
      } else {
        if (active === last || !active || !container.contains(active)) {
          e.preventDefault()
          first.focus()
        }
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
    // containerRef is a stable ref object; handleKeyDown reads .current at
    // keypress time, not effect-setup time, which is what we want.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onClose, enabled])
}
