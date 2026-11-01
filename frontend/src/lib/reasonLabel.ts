// Match-reason tags arrive from the server as finished English phrases
// (backend/services/feed_service.py _proficiency_reason_tags, agents/matcher.py),
// and are stored that way, so a Hebrew user saw "No Sql exp. (required)" on
// every card. Parsing the few fixed shapes here translates old tags as well as
// new ones; anything else (a bare skill name) is shown as it came.

export type ReasonCode =
  | 'academic_only' | 'academic_match' | 'no_exp_required' | 'no_exp_preferred'
  | 'domain_fit' | 'remote'

const SHAPES: ReadonlyArray<[ReasonCode, RegExp]> = [
  ['academic_only',    /^Academic (.+) \(Prof\. Req\.\)$/],
  ['academic_match',   /^(.+) \(academic match\)$/],
  ['no_exp_required',  /^No (.+) exp\. \(required\)$/],
  ['no_exp_preferred', /^No (.+) exp\. \(preferred\)$/],
  ['domain_fit',       /^(.+) domain fit$/],
  ['remote',           /^(Remote)$/],
]

/** The fixed shape a server label was built from, and the skill inside it. */
export function parseReason(label: string): { code: ReasonCode; skill: string } | null {
  for (const [code, re] of SHAPES) {
    const m = label.match(re)
    if (m) return { code, skill: m[1] }
  }
  return null
}

/** The skill a reason is about: "No Sql exp. (required)" is about "Sql". */
export function reasonSkill(label: string): string {
  return parseReason(label)?.skill ?? label
}

/** The label in the interface language, from templates with a {skill} slot. */
export function localizeReason(label: string, templates: Record<ReasonCode, string>): string {
  const parsed = parseReason(label)
  return parsed ? templates[parsed.code].replace('{skill}', parsed.skill) : label
}
