/**
 * ParsedCV — the Live-Editor-ready CV data model.
 *
 * Scope note (see conversation): this is a normalization/validation layer,
 * NOT a rival extraction engine. Raw-resume LLM extraction and fact-provenance
 * validation already live server-side in backend/services/cv_assembly_engine.py
 * ("Zero-Hallucination CV Assembly Engine") and backend/agents/resume.py. This
 * file defines the typed contract the frontend uses to consume that output,
 * plus the stability/tracking guarantees LiveEditor.tsx needs that the
 * backend's plain JSON (see LiveEditor.tsx's `CvData`) doesn't provide:
 * persistent per-field IDs and explicit AI-generated vs. user-edited state.
 *
 * Zod schemas are the source of truth; TS types are inferred from them so the
 * runtime validator and the compile-time type can never drift apart.
 */
import { z } from 'zod'

// ── Provenance vocabulary ──────────────────────────────────────────────────
// Mirrors backend/services/cv_assembly_engine.py's VerifiedFact.source_type
// exactly, plus 'user_edit' for content typed directly into LiveEditor. Using
// the same vocabulary means an edited field can round-trip to the backend's
// fact-provenance validator later without a translation layer.
export const FIELD_ORIGINS = [
  'cv_parse',           // extracted from an uploaded CV
  'conversation_star',  // captured via an Ariel STAR probe
  'portfolio',          // sourced from a linked portfolio artifact
  'certification',      // sourced from an uploaded certification
  'user_edit',          // typed directly by the user in LiveEditor
] as const
export const FieldOriginSchema = z.enum(FIELD_ORIGINS)
export type FieldOrigin = z.infer<typeof FieldOriginSchema>

// ── GeneratedField<T> ───────────────────────────────────────────────────────
// Every editable text leaf is wrapped in this. It is the single source of
// truth the Amethyst "generated-content marker" (DESIGN_SYSTEM_V2.md §6.1)
// reads from: `isAiGenerated && value === originalValue` → untouched machine
// output → amethyst marker. The moment `value !== originalValue`, LiveEditor's
// amber "you edited this" treatment takes over — see LiveEditor.tsx's
// EditableField, which currently derives that same signal by comparing
// against originalCvData at the same array index. GeneratedField replaces
// that index-based comparison with an explicit, ID-anchored one.
function generatedFieldSchema<Inner extends z.ZodTypeAny>(inner: Inner) {
  return z.object({
    id:            z.string().min(1),
    value:         inner,
    originalValue: inner,
    isAiGenerated: z.boolean(),
    origin:        FieldOriginSchema,
  })
}
export type GeneratedField<T> = {
  id: string
  value: T
  originalValue: T
  isAiGenerated: boolean
  origin: FieldOrigin
}

// ── Bullet ────────────────────────────────────────────────────────────────
export const ParsedBulletSchema = z.object({
  id:        z.string().min(1),
  text:      generatedFieldSchema(z.string()),
  /** Skill entities this specific bullet evidences — not just a document-level
   *  skills list (Core Requirement 2: "categorize skills within specific bullets"). */
  skillTags: z.array(z.string()),
  /** backend/services/cv_assembly_engine.py BulletDraft.fact_ids, when the
   *  backend provided provenance for this bullet. Empty for bullets that
   *  predate fact-provenance tracking or were typed directly by the user. */
  factIds:   z.array(z.string()),
})
export type ParsedBullet = z.infer<typeof ParsedBulletSchema>

// ── Experience ────────────────────────────────────────────────────────────
export const ParsedExperienceSchema = z.object({
  id:       z.string().min(1),
  role:     generatedFieldSchema(z.string()),
  company:  generatedFieldSchema(z.string()),
  dates:    generatedFieldSchema(z.string()),
  bullets:  z.array(ParsedBulletSchema),
})
export type ParsedExperience = z.infer<typeof ParsedExperienceSchema>

// ── Education ─────────────────────────────────────────────────────────────
export const ParsedEducationSchema = z.object({
  id:          z.string().min(1),
  degree:      generatedFieldSchema(z.string()),
  institution: generatedFieldSchema(z.string()),
  dates:       generatedFieldSchema(z.string()),
  honors:      generatedFieldSchema(z.string()),
  coursework:  generatedFieldSchema(z.string()),
})
export type ParsedEducation = z.infer<typeof ParsedEducationSchema>

// ── Military (verified-profile data, never AI-generated — kept read-only,
//    mirrors the "Auto-injected from your verified profile" note already in
//    LiveEditor.tsx) ────────────────────────────────────────────────────────
export const ParsedMilitarySchema = z.object({
  id:    z.string().min(1),
  role:  z.string(),
  unit:  z.string(),
  dates: z.string(),
})
export type ParsedMilitary = z.infer<typeof ParsedMilitarySchema>

// ── Skills / Languages ────────────────────────────────────────────────────
export const ParsedSkillCategorySchema = z.object({
  id:    z.string().min(1),
  label: z.string(),
  items: z.array(z.string()),
})
export type ParsedSkillCategory = z.infer<typeof ParsedSkillCategorySchema>

export const ParsedLanguageSchema = z.object({
  id:       z.string().min(1),
  language: z.string(),
  level:    z.string(),
})
export type ParsedLanguage = z.infer<typeof ParsedLanguageSchema>

// ── Extraction metadata ───────────────────────────────────────────────────
export const ExtractionMetaSchema = z.object({
  /** 0-100, 1-decimal — mirrors the .ai_rules score-precision convention used
   *  everywhere else in the app, even though this is a completeness heuristic
   *  rather than a match/confidence score (see cvParser.ts heuristicConfidence). */
  confidence:      z.number().min(0).max(100),
  isPartial:       z.boolean(),
  missingSections: z.array(z.string()),
  warnings:        z.array(z.string()),
  parsedAt:        z.string(),
})
export type ExtractionMeta = z.infer<typeof ExtractionMetaSchema>

// ── ParsedCV ──────────────────────────────────────────────────────────────
export const ParsedCVSchema = z.object({
  /** Stable per-document id — a content hash of the source, so re-parsing
   *  unchanged input yields the same id (Core Requirement 1: deterministic). */
  id:           z.string().min(1),
  title:        generatedFieldSchema(z.string()),
  summary:      generatedFieldSchema(z.string()),
  experience:   z.array(ParsedExperienceSchema),
  education:    z.array(ParsedEducationSchema),
  military:     ParsedMilitarySchema.optional(),
  skills:       z.array(ParsedSkillCategorySchema),
  languages:    z.array(ParsedLanguageSchema),
  volunteering: generatedFieldSchema(z.string()),
  meta:         ExtractionMetaSchema,
})
export type ParsedCV = z.infer<typeof ParsedCVSchema>

// ── Lenient input schema ─────────────────────────────────────────────────
// What we actually expect back from the backend today (matches LiveEditor's
// CvData shape — see LiveEditor.tsx). Deliberately permissive: every field is
// optional/defaulted so a messy or partial LLM response never throws before
// cvParser.ts gets a chance to flag it as a partial result with clear errors
// (Core Requirement 3), rather than failing validation outright.
export const RawCvInputSchema = z.object({
  title:        z.string().optional().default(''),
  summary:      z.string().optional().default(''),
  experience:   z.array(z.object({
    role:    z.string().optional().default(''),
    company: z.string().optional().default(''),
    dates:   z.string().optional().default(''),
    bullets: z.array(z.string()).optional().default([]),
  })).optional().default([]),
  education:    z.array(z.object({
    degree:      z.string().optional().default(''),
    institution: z.string().optional().default(''),
    dates:       z.string().optional().default(''),
    honors:      z.string().optional().default(''),
    coursework:  z.string().optional().default(''),
  })).optional().default([]),
  military:     z.object({
    role: z.string(), unit: z.string(), dates: z.string(),
  }).optional(),
  skills:       z.object({
    categories: z.array(z.object({
      label: z.string(),
      items: z.array(z.string()).optional().default([]),
    })).optional().default([]),
  }).optional().default({ categories: [] }),
  languages:    z.array(z.object({
    language: z.string(), level: z.string(),
  })).optional().default([]),
  volunteering: z.string().optional().default(''),
})
export type RawCvInput = z.infer<typeof RawCvInputSchema>
