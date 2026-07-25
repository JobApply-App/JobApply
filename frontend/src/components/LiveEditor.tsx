'use client'

import { useCallback, useEffect, useRef } from 'react'
import { TOKENS } from '@/lib/tokens'
import type { ParsedCV, ParsedSkillCategory, GeneratedField } from '@/lib/cv'
import { updateFieldById, updateSkillItemsById } from '@/lib/cvParser'

// ── Wire format ───────────────────────────────────────────────────────────
// The raw JSON shape the backend actually sends/accepts (/api/resumes/tailor's
// `cv_data`, fetchMatchScore, renderPdf, saveCv, ...). LiveEditor itself no
// longer speaks this shape directly — see lib/cvParser.ts's parseCv() /
// toLiveEditorCvData() for the conversion at the I/O boundary — but it stays
// exported from here since it's still the wire type other call sites pass
// around raw CV JSON with.

export interface CvData {
  title:        string
  summary:      string
  experience:   Array<{
    role:     string
    company:  string
    dates:    string
    bullets:  string[]
  }>
  education:    Array<{
    degree:      string
    institution: string
    dates:       string
    honors:      string
    coursework:  string
  }>
  military?:    { role: string; unit: string; dates: string }
  skills:       { categories: Array<{ label: string; items: string[] }> }
  languages:    Array<{ language: string; level: string }>
  volunteering: string
  [key: string]: unknown
}

export interface LiveEditorProps {
  cv:               ParsedCV
  onChange:         (updated: ParsedCV) => void
  onReset:          () => void
  isDirty:          boolean
  isSaving:         boolean
  onSave:           () => void
}

// ── Icons ─────────────────────────────────────────────────────────────────────

function UndoIcon() {
  return (
    <svg width={13} height={13} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <polyline points="9 14 4 9 9 4" /><path d="M20 20v-7a4 4 0 0 0-4-4H4" />
    </svg>
  )
}

function SaveIcon() {
  return (
    <svg width={13} height={13} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" />
      <polyline points="17 21 17 13 7 13 7 21" /><polyline points="7 3 7 8 15 8" />
    </svg>
  )
}

// ── Generated-content marker (Meridian V2 §6.1) ──────────────────────────────
// A field's own `isAiGenerated` flag is the single source of truth for the
// marker — it's already correctly maintained by cvParser.ts's
// updateFieldById()/resetToOriginal() (true = pristine, untouched Ariel
// output → amethyst; false = user_edit → the amber "you changed this"
// treatment). This component never re-derives that signal from `origin`
// itself — reading two places for one fact is how they drift.
const AI_MARKER_BORDER = '#7C3AED'   // ja.ai
const AI_MARKER_BG     = '#F5F3FF'   // ja.aiSubtle
const EDITED_BORDER     = 'oklch(0.75 0.14 80)'
const EDITED_BG         = 'oklch(0.98 0.02 80)'

// ── Small text field (auto-expanding textarea) ────────────────────────────────
// Operates on a single GeneratedField<string> — the same field object that
// lives at `bullet.text`, `experience.role`, `education.degree`, etc. — so
// every editable leaf in the CV gets identical Amethyst-marker behavior from
// one place, keyed by the field's own stable id rather than its position.

function EditableField({
  field, onChange, rows = 2, mono = false,
}: {
  field:    GeneratedField<string>
  onChange: (id: string, value: string) => void
  rows?:    number
  mono?:    boolean
}) {
  const ref = useRef<HTMLTextAreaElement>(null)

  // Auto-resize
  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight}px`
  }, [field.value])

  const isEdited    = !field.isAiGenerated
  const markerColor = isEdited ? EDITED_BORDER : AI_MARKER_BORDER
  const markerBg    = isEdited ? EDITED_BG : AI_MARKER_BG

  return (
    <textarea
      ref={ref}
      value={field.value}
      rows={rows}
      dir="auto"
      onChange={e => onChange(field.id, e.target.value)}
      style={{
        width: '100%',
        resize: 'none',
        overflow: 'hidden',
        border: `1px solid ${TOKENS.color.line}`,
        borderLeft: `2px solid ${markerColor}`,
        borderRadius: 6,
        padding: '5px 8px',
        fontSize: mono ? 11 : 11.5,
        fontFamily: mono ? '"SF Mono", "Fira Mono", monospace' : 'inherit',
        lineHeight: 1.5,
        color: TOKENS.color.ink2,
        background: markerBg,
        outline: 'none',
        transition: 'border-color 0.15s, background 0.15s',
        textAlign: 'start',
        unicodeBidi: 'plaintext',
      }}
      // Only the top/right/bottom sides respond to focus — the left marker
      // color is the AI/edited-state signal and must stay visible while typing.
      onFocus={e => {
        e.currentTarget.style.borderTopColor    = TOKENS.color.primary
        e.currentTarget.style.borderRightColor  = TOKENS.color.primary
        e.currentTarget.style.borderBottomColor = TOKENS.color.primary
      }}
      onBlur={e => {
        e.currentTarget.style.borderTopColor    = TOKENS.color.line
        e.currentTarget.style.borderRightColor  = TOKENS.color.line
        e.currentTarget.style.borderBottomColor = TOKENS.color.line
      }}
    />
  )
}

// ── Section wrapper ───────────────────────────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 18 }}>
      <p style={{
        fontSize: 9.5, fontWeight: 700, letterSpacing: '1.4px',
        textTransform: 'uppercase', color: TOKENS.color.primary,
        paddingBottom: 4, borderBottom: `0.75px solid ${TOKENS.color.line}`,
        marginBottom: 10,
      }}>
        {title}
      </p>
      {children}
    </div>
  )
}

// ── Skill tag editor ──────────────────────────────────────────────────────────
// Skill items are plain string[] on a ParsedSkillCategory — never AI-marked
// prose (they're structured tags, not generated text) — updates are keyed by
// the category's own stable id via updateSkillItemsById(), not its index.

function SkillCategoryEditor({
  category, onChange,
}: { category: ParsedSkillCategory; onChange: (categoryId: string, items: string[]) => void }) {
  const inputRef = useRef<HTMLInputElement>(null)

  const remove = (i: number) => onChange(category.id, category.items.filter((_, idx) => idx !== i))

  const add = () => {
    const v = (inputRef.current?.value ?? '').trim()
    if (v && !category.items.includes(v)) onChange(category.id, [...category.items, v])
    if (inputRef.current) inputRef.current.value = ''
  }

  return (
    <div style={{ marginBottom: 10 }}>
      <p style={{ fontSize: 10, fontWeight: 600, color: TOKENS.color.muted,
        textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 5 }}>
        {category.label}
      </p>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 5px', marginBottom: 6 }}>
        {category.items.map((item, i) => (
          <span key={item} style={{
            display: 'flex', alignItems: 'center', gap: 4,
            fontSize: 10.5, fontWeight: 500,
            padding: '2px 7px', borderRadius: 5,
            background: TOKENS.color.primarySoft,
            color: TOKENS.color.primary,
            border: `0.75px solid oklch(0.85 0.06 255)`,
          }}>
            {item}
            <button onClick={() => remove(i)} style={{
              background: 'none', border: 'none', cursor: 'pointer',
              padding: 0, lineHeight: 1, color: TOKENS.color.primary, opacity: 0.6,
              fontSize: 12, marginTop: -1,
            }}>×</button>
          </span>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 5 }}>
        <input
          ref={inputRef}
          onKeyDown={e => e.key === 'Enter' && add()}
          placeholder="Add skill…"
          dir="auto"
          style={{
            flex: 1, fontSize: 11, padding: '3px 8px', borderRadius: 5,
            border: `1px solid ${TOKENS.color.line}`,
            background: TOKENS.color.bg, color: TOKENS.color.ink2,
            outline: 'none',
            textAlign: 'start',
            unicodeBidi: 'plaintext',
          }}
        />
        <button onClick={add} style={{
          fontSize: 11, padding: '3px 10px', borderRadius: 5,
          background: TOKENS.color.primarySoft, color: TOKENS.color.primary,
          border: `1px solid oklch(0.85 0.06 255)`, cursor: 'pointer', fontWeight: 600,
        }}>
          +
        </button>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export function LiveEditor({
  cv, onChange, onReset, isDirty, isSaving, onSave,
}: LiveEditorProps) {

  // ── ID-based update handlers ──────────────────────────────────────────────
  // No array indices anywhere below: every edit is routed through the field's
  // own stable id via cvParser.ts's updateFieldById()/updateSkillItemsById(),
  // which locate the target by id, apply the edit, and mark it
  // `origin: 'user_edit'` (flipping isAiGenerated false) while leaving every
  // other field's id, factIds, and skillTags untouched. If an id is somehow
  // stale (should not happen — see cvParser.ts's resilience note), the update
  // is a logged no-op rather than a crash.

  const setFieldValue = useCallback((fieldId: string, value: string) => {
    onChange(updateFieldById(cv, fieldId, value))
  }, [cv, onChange])

  const setSkillItems = useCallback((categoryId: string, items: string[]) => {
    onChange(updateSkillItemsById(cv, categoryId, items))
  }, [cv, onChange])

  // ── Auto-save: debounced 30s after last change ────────────────────────────
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (!isDirty) return
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    saveTimerRef.current = setTimeout(onSave, 30_000)
    return () => { if (saveTimerRef.current) clearTimeout(saveTimerRef.current) }
  }, [cv, isDirty, onSave])

  return (
    <div style={{
      width: '100%', height: '100%',
      overflowY: 'auto',
      padding: '16px 20px 20px',
      display: 'flex', flexDirection: 'column',
      gap: 0,
    }}>

      {/* ── Toolbar ── */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 16, flexShrink: 0,
      }}>
        <p style={{ fontSize: 12.5, fontWeight: 600, color: TOKENS.color.ink }}>
          Live Editor
          {isDirty && (
            <span style={{ fontSize: 10.5, fontWeight: 400, color: TOKENS.color.muted, marginLeft: 6 }}>
              · unsaved changes
            </span>
          )}
        </p>
        <div style={{ display: 'flex', gap: 6 }}>
          <button
            onClick={onReset}
            title="Reset to original generated CV"
            style={{
              display: 'flex', alignItems: 'center', gap: 5,
              padding: '4px 10px', borderRadius: 20,
              fontSize: 11.5, fontWeight: 500,
              color: TOKENS.color.muted,
              background: 'white',
              border: `1.5px solid ${TOKENS.color.line}`,
              cursor: 'pointer',
            }}
          >
            <UndoIcon /> Reset
          </button>
          <button
            onClick={onSave}
            disabled={!isDirty || isSaving}
            style={{
              display: 'flex', alignItems: 'center', gap: 5,
              padding: '4px 12px', borderRadius: 20,
              fontSize: 11.5, fontWeight: 600,
              color: 'white',
              background: isDirty && !isSaving ? TOKENS.color.primary : TOKENS.color.subtle,
              border: 'none', cursor: isDirty && !isSaving ? 'pointer' : 'default',
              transition: 'background 0.15s',
            }}
          >
            <SaveIcon /> {isSaving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>

      {/* ── Summary ── */}
      <Section title="Professional Summary">
        <EditableField field={cv.summary} onChange={setFieldValue} rows={4} />
      </Section>

      {/* ── Experience bullets ── */}
      <Section title="Experience">
        {cv.experience.map(exp => (
          <div key={exp.id} style={{ marginBottom: 14 }}>
            <div style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
              marginBottom: 6,
            }}>
              <p style={{ fontSize: 11.5, fontWeight: 700, color: TOKENS.color.ink }}>
                {exp.role.value}
              </p>
              <p style={{ fontSize: 10.5, color: TOKENS.color.muted, fontStyle: 'italic' }}>
                {exp.company.value} · {exp.dates.value}
              </p>
            </div>
            {exp.bullets.map(bullet => (
              <div key={bullet.id} style={{ display: 'flex', gap: 6, marginBottom: 5, alignItems: 'flex-start' }}>
                <span style={{
                  marginTop: 7, flexShrink: 0, width: 5, height: 5, borderRadius: '50%',
                  background: TOKENS.color.subtle,
                }} />
                <div style={{ flex: 1 }}>
                  <EditableField field={bullet.text} onChange={setFieldValue} rows={2} />
                </div>
              </div>
            ))}
          </div>
        ))}
      </Section>

      {/* ── Military Service (read-only — always injected from verified profile) ── */}
      {cv.military?.role && (
        <Section title="Military Service">
          <div style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
            padding: '7px 10px',
            borderRadius: 7,
            border: `1px solid ${TOKENS.color.line}`,
            background: 'oklch(0.98 0 0)',
          }}>
            <div>
              <span style={{ fontSize: 11.5, fontWeight: 700, color: TOKENS.color.ink }}>
                {cv.military.role}
              </span>
              <span style={{
                fontSize: 11, color: TOKENS.color.muted,
                fontStyle: 'italic', marginLeft: 6,
              }}>
                {cv.military.unit}
              </span>
            </div>
            <span style={{ fontSize: 10.5, color: TOKENS.color.muted }}>
              {cv.military.dates}
            </span>
          </div>
          <p style={{
            fontSize: 10, color: TOKENS.color.muted,
            marginTop: 5, fontStyle: 'italic',
          }}>
            Auto-injected from your verified profile — not editable here.
          </p>
        </Section>
      )}

      {/* ── Volunteering — hidden entirely when absent or empty ── */}
      {cv.volunteering.value && cv.volunteering.value.trim().length > 0 && (
        <Section title="Volunteering">
          <EditableField field={cv.volunteering} onChange={setFieldValue} rows={2} />
        </Section>
      )}

      {/* ── Skills ── */}
      <Section title="Skills">
        {cv.skills.map(category => (
          <SkillCategoryEditor
            key={category.id}
            category={category}
            onChange={setSkillItems}
          />
        ))}
      </Section>

    </div>
  )
}
