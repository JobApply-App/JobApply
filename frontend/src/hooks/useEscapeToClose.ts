import { useEffect } from 'react'

/**
 * Closes a dialog/modal on Escape and moves focus into it on mount — the two
 * keyboard-accessibility requirements every `role="dialog"` needs. Does NOT
 * trap Tab inside the dialog or restore focus to the trigger on close; those
 * need the triggering element threaded through each call site, which the
 * modals using this hook don't currently do.
 *
 * `enabled` matters for components that stay mounted and toggle visibility
 * via `if (!open) return null` AFTER their hooks run (several sheets/modals
 * in this codebase do): without it, the Escape listener would stay attached
 * — and fire — even while the dialog is invisible. Pass the same `open`
 * flag the caller already has; defaults to true for the common case of a
 * modal that only mounts while it's actually shown.
 */
export function useEscapeToClose(
  onClose: () => void,
  containerRef?: React.RefObject<HTMLElement>,
  enabled: boolean = true,
) {
  useEffect(() => {
    if (!enabled) return
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose, enabled])

  useEffect(() => {
    if (!enabled) return
    containerRef?.current?.focus()
  }, [containerRef, enabled])
}
