/**
 * cvPatch — a dependency-free RFC 6902 (JSON Patch) applier.
 *
 * The client half of backend/services/cv_patch_service.py. When Ariel edits a
 * CV, POST /api/resumes/copilot returns both the authoritative `cv_data` and
 * the `patch` that produced it. Re-deriving the whole document from `cv_data`
 * throws away the one thing the patch knows and the document does not: *which
 * paths actually moved*. This module applies those ops locally so the editor
 * can show the edit before — and independently of — the wholesale reconcile.
 *
 * No npm dependency: `fast-json-patch` and friends are ~10x this file for a
 * spec we only need one direction of (apply, never observe/generate), and this
 * bundle already ships to every CV preview.
 *
 * Failure semantics match the backend exactly: **every failure path returns
 * the ORIGINAL document**. A patch is applied to a deep copy, so a patch that
 * fails on op 4 of 6 can never be observed half-applied. That matters more
 * here than on the server — the caller's document is React state a user may
 * have spent an hour editing, and a partial apply would leave it in a state
 * that is neither what they had nor what they asked for.
 *
 * Two rules from cv_patch_service.py are deliberately NOT mirrored here:
 *
 *   • The `/header` guard. That rule governs what a *model* may author. This
 *     patch is `diff_cv()` output describing what the *server already did* —
 *     including its own static-section injection, which legitimately writes
 *     header fields. Re-applying the authoring policy to a report of committed
 *     changes would make the local view diverge from the server's for an edit
 *     that was never in question.
 *   • MAX_OPS. Same reason: it is a blast-radius ceiling on model-authored
 *     patches, not a correctness bound. A large server diff is a large real
 *     change, and refusing it would silently drop a valid update.
 */
import type { RFC6902PatchOp } from './apiTypes'

/** Why a patch was refused. Mirrors PatchResult.error_kind server-side. */
export type PatchErrorKind = 'malformed' | 'path_not_found' | 'test_failed'

export type PatchResult<T> =
  | { ok: true;  doc: T; opsApplied: number }
  | { ok: false; doc: T; error: string; kind: PatchErrorKind }

// RFC 6901 §4: an array index is "0" or digits with no leading zero. "01" and
// "1.0" are pointer syntax errors, not out-of-range lookups — Number() would
// happily coerce both.
const ARRAY_INDEX = /^(?:0|[1-9][0-9]*)$/

type JsonObject = Record<string, unknown>
type Container  = JsonObject | unknown[]

function isPlainObject(v: unknown): v is JsonObject {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

function hasOwn(obj: JsonObject, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(obj, key)
}

function clone<T>(value: T): T {
  // cv_data is always JSON.parse output, so both branches are lossless. The
  // JSON fallback covers older Safari/jsdom without structuredClone.
  if (typeof structuredClone === 'function') {
    try { return structuredClone(value) } catch { /* fall through */ }
  }
  return value === undefined ? value : (JSON.parse(JSON.stringify(value)) as T)
}

/**
 * Parse a JSON Pointer into its reference tokens, or null if it is not one.
 * `""` addresses the whole document and yields `[]`.
 *
 * Unescape order is fixed by RFC 6901 §4 — `~1` before `~0`. Reversed, the
 * `~01` sequence would decode to `/` instead of the literal `~1` it encodes.
 */
export function parsePointer(pointer: string): string[] | null {
  if (pointer === '') return []
  if (pointer.charAt(0) !== '/') return null
  return pointer
    .slice(1)
    .split('/')
    .map(token => token.replace(/~1/g, '/').replace(/~0/g, '~'))
}

/** Structural equality over JSON values. Used by `test` ops and by callers
 *  reconciling an optimistic result against the authoritative one. */
export function jsonEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true
  if (Array.isArray(a) || Array.isArray(b)) {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false
    return a.every((item, i) => jsonEqual(item, b[i]))
  }
  if (isPlainObject(a) && isPlainObject(b)) {
    const keysA = Object.keys(a)
    if (keysA.length !== Object.keys(b).length) return false
    return keysA.every(k => hasOwn(b, k) && jsonEqual(a[k], b[k]))
  }
  return false
}

// ── Internal traversal ──────────────────────────────────────────────────────

/**
 * A lookup distinguishes three outcomes, not two. `invalid` means the pointer
 * itself is wrong — a token that cannot be an array index at all ("01",
 * "first") — while `missing` means the pointer is well-formed but the document
 * does not have that location. They map to different error kinds, and the
 * distinction has to survive traversal depth: `/experience/01/role` is exactly
 * as malformed as `/experience/01`, so classifying by which token happened to
 * be last would be reporting position, not cause.
 */
type Lookup =
  | { kind: 'found';   value: unknown }
  | { kind: 'missing' }
  | { kind: 'invalid'; token: string }

const MISSING: Lookup = { kind: 'missing' }

function getAt(root: unknown, tokens: readonly string[]): Lookup {
  let cur: unknown = root
  for (const token of tokens) {
    if (Array.isArray(cur)) {
      if (!ARRAY_INDEX.test(token) && token !== '-') return { kind: 'invalid', token }
      if (token === '-') return MISSING          // the append token addresses no existing member
      const i = Number(token)
      if (i >= cur.length) return MISSING
      cur = cur[i]
    } else if (isPlainObject(cur)) {
      if (!hasOwn(cur, token)) return MISSING
      cur = cur[token]
    } else {
      return MISSING
    }
  }
  return { kind: 'found', value: cur }
}

type ParentLookup =
  | { kind: 'found';   parent: Container }
  | { kind: 'missing' }
  | { kind: 'invalid'; token: string }

/** The container that holds the last token of `tokens`. */
function getParent(root: unknown, tokens: readonly string[]): ParentLookup {
  const res = getAt(root, tokens.slice(0, -1))
  if (res.kind !== 'found') return res
  return Array.isArray(res.value) || isPlainObject(res.value)
    ? { kind: 'found', parent: res.value as Container }
    : { kind: 'missing' }
}

type OpOk    = { ok: true;  root: unknown; removed?: unknown }
type OpErr   = { ok: false; error: string; kind: PatchErrorKind }
type Outcome = OpOk | OpErr

const notFound   = (p: string): OpErr => ({ ok: false, kind: 'path_not_found', error: `no such path ${p}` })
const malformed  = (msg: string): OpErr => ({ ok: false, kind: 'malformed', error: msg })
const badIndex   = (token: string): OpErr => malformed(`"${token}" is not an array index`)

/** Collapse a parent lookup into either the container or the matching error. */
function parentOrError(look: ParentLookup, path: string): Container | OpErr {
  if (look.kind === 'found')   return look.parent
  if (look.kind === 'invalid') return badIndex(look.token)
  return notFound(path)
}

function isOpErr(v: Container | OpErr): v is OpErr {
  return 'ok' in v && v.ok === false
}

function addAt(root: unknown, tokens: string[], value: unknown, path: string): Outcome {
  if (tokens.length === 0) return { ok: true, root: value }

  const key    = tokens[tokens.length - 1]
  const parent = parentOrError(getParent(root, tokens), path)
  if (isOpErr(parent)) return parent

  if (Array.isArray(parent)) {
    // "-" is RFC 6902's append token; the backend's differ emits explicit
    // indices, but a hand-authored agent patch may use it.
    if (key === '-') { parent.push(value); return { ok: true, root } }
    if (!ARRAY_INDEX.test(key)) return badIndex(key)
    const i = Number(key)
    // `add` inserts before `i`, so i === length (append) is in range while
    // anything past it is a gap RFC 6902 forbids creating.
    if (i > parent.length) return notFound(path)
    parent.splice(i, 0, value)
    return { ok: true, root }
  }

  parent[key] = value
  return { ok: true, root }
}

function removeAt(root: unknown, tokens: string[], path: string): Outcome {
  if (tokens.length === 0) return malformed('cannot remove the whole document')

  const key    = tokens[tokens.length - 1]
  const parent = parentOrError(getParent(root, tokens), path)
  if (isOpErr(parent)) return parent

  if (Array.isArray(parent)) {
    if (!ARRAY_INDEX.test(key)) return badIndex(key)
    const i = Number(key)
    if (i >= parent.length) return notFound(path)
    const [removed] = parent.splice(i, 1)
    return { ok: true, root, removed }
  }

  if (!hasOwn(parent, key)) return notFound(path)
  const removed = parent[key]
  delete parent[key]
  return { ok: true, root, removed }
}

function replaceAt(root: unknown, tokens: string[], value: unknown, path: string): Outcome {
  if (tokens.length === 0) return { ok: true, root: value }

  const key    = tokens[tokens.length - 1]
  const parent = parentOrError(getParent(root, tokens), path)
  if (isOpErr(parent)) return parent

  if (Array.isArray(parent)) {
    if (!ARRAY_INDEX.test(key)) return badIndex(key)
    const i = Number(key)
    // Unlike `add`, `replace` requires an existing target — i === length is
    // out of range here.
    if (i >= parent.length) return notFound(path)
    parent[i] = value
    return { ok: true, root }
  }

  if (!hasOwn(parent, key)) return notFound(path)
  parent[key] = value
  return { ok: true, root }
}

/** True when `a` addresses `b` or one of its ancestors. */
function isPrefixOf(a: readonly string[], b: readonly string[]): boolean {
  return a.length <= b.length && a.every((token, i) => token === b[i])
}

function applyOne(root: unknown, op: RFC6902PatchOp): Outcome {
  if (op === null || typeof op !== 'object') return malformed('operation is not an object')
  if (typeof op.path !== 'string')           return malformed(`invalid path ${JSON.stringify(op.path)}`)

  const tokens = parsePointer(op.path)
  if (tokens === null) return malformed(`${JSON.stringify(op.path)} is not a JSON Pointer`)

  switch (op.op) {
    case 'add':
    case 'replace':
    case 'test': {
      if (!('value' in op)) return malformed(`${op.op} requires "value"`)
      if (op.op === 'test') {
        const found = getAt(root, tokens)
        if (found.kind === 'invalid') return badIndex(found.token)
        if (found.kind === 'missing') return notFound(op.path)
        return jsonEqual(found.value, op.value)
          ? { ok: true, root }
          : { ok: false, kind: 'test_failed', error: `value at ${op.path} is not what the patch asserts` }
      }
      // Clone so the applied document never aliases the response object the
      // ops were parsed from.
      const value = clone(op.value)
      return op.op === 'add'
        ? addAt(root, tokens, value, op.path)
        : replaceAt(root, tokens, value, op.path)
    }

    case 'remove':
      return removeAt(root, tokens, op.path)

    case 'move':
    case 'copy': {
      if (typeof op.from !== 'string') return malformed(`${op.op} requires "from"`)
      const fromTokens = parsePointer(op.from)
      if (fromTokens === null) return malformed(`${JSON.stringify(op.from)} is not a JSON Pointer`)

      if (op.op === 'copy') {
        const src = getAt(root, fromTokens)
        if (src.kind === 'invalid') return badIndex(src.token)
        if (src.kind === 'missing') return notFound(op.from)
        return addAt(root, tokens, clone(src.value), op.path)
      }

      // RFC 6902 §4.4: moving a value into its own child is undefined.
      // Equal pointers are the degenerate case and a legal no-op.
      if (isPrefixOf(fromTokens, tokens)) {
        if (fromTokens.length === tokens.length) return { ok: true, root }
        return malformed(`cannot move ${op.from} into its own child ${op.path}`)
      }
      // Remove first, then insert — so indices in `path` are read against the
      // post-removal array, which is what makes a same-array reorder land
      // where the differ intended.
      const taken = removeAt(root, fromTokens, op.from)
      if (!taken.ok) return taken
      return addAt(taken.root, tokens, taken.removed, op.path)
    }

    default:
      return malformed(`unsupported op ${JSON.stringify((op as { op?: unknown }).op)}`)
  }
}

// ── Public entry point ──────────────────────────────────────────────────────

/**
 * Apply an RFC 6902 patch to a CV document, or return it untouched.
 *
 * A null/empty patch is a success with `opsApplied: 0` — the backend sends
 * `[]` when an instruction changed nothing, and "no ops" is not an error on
 * this side of the wire (unlike `validate_patch()`, which rejects an empty
 * patch because a model claiming a change it cannot describe *is* a bug).
 *
 * `doc` is never mutated.
 */
export function applyCvPatch<T>(
  doc: T,
  patch: readonly RFC6902PatchOp[] | null | undefined,
): PatchResult<T> {
  if (patch === null || patch === undefined) return { ok: true, doc, opsApplied: 0 }
  if (!Array.isArray(patch)) return { ok: false, doc, kind: 'malformed', error: 'patch is not an array' }
  if (patch.length === 0) return { ok: true, doc, opsApplied: 0 }
  if (doc === null || typeof doc !== 'object') {
    return { ok: false, doc, kind: 'malformed', error: 'document is not a JSON object or array' }
  }

  let root: unknown = clone(doc)

  for (let i = 0; i < patch.length; i++) {
    const op      = patch[i]
    const outcome = applyOne(root, op)
    if (!outcome.ok) {
      const label = op && typeof op === 'object' ? `${op.op} ${op.path}` : String(op)
      return { ok: false, doc, kind: outcome.kind, error: `operation ${i} (${label}): ${outcome.error}` }
    }
    root = outcome.root
  }

  return { ok: true, doc: root as T, opsApplied: patch.length }
}
