// The Matches focus view (design direction 2, Ron 27.11): one match at a
// time. The place in the queue is kept as the job's id plus its position, so
// it survives the list changing under it: a skipped job leaves the list and
// the one after it takes its place; a reorder keeps the same job in view.

export interface FocusCursor { id: string | null; idx: number }

/** Where the cursor is in `ids`. `ids.length` means the queue is finished. */
export function resolveIndex(ids: readonly string[], cursor: FocusCursor): number {
  if (cursor.id !== null) {
    const at = ids.indexOf(cursor.id)
    if (at !== -1) return at
  }
  return Math.max(0, Math.min(cursor.idx, ids.length))
}

/** The cursor moved by `step` (clamped to the queue, end included). */
export function moveCursor(ids: readonly string[], cursor: FocusCursor, step: number): FocusCursor {
  const idx = Math.max(0, Math.min(resolveIndex(ids, cursor) + step, ids.length))
  return { id: ids[idx] ?? null, idx }
}
