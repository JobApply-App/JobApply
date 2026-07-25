/**
 * Tone Adaptation Engine
 *
 * Generates a personalised system-prompt fragment that instructs the AI
 * to match the user's communication style and domain vocabulary, derived
 * from their master profile.
 */

export interface UserProfile {
  /** Primary professional domain, e.g. 'Product Management', 'Customer Success' */
  domain?:            string
  /** Preferred communication tone: 'direct' | 'collaborative' | 'analytical' */
  communicationStyle?: 'direct' | 'collaborative' | 'analytical'
  /** Years of relevant experience */
  yearsExperience?:   number
  /** Key skill tags from the master profile */
  topSkills?:         string[]
}

const DOMAIN_VOCAB: Record<string, string> = {
  'Product Management': 'product management terminology (roadmaps, OKRs, user stories, prioritisation frameworks)',
  'Customer Success':   'customer success terminology (NPS, churn, QBRs, expansion revenue, health scores)',
  'Engineering':        'software engineering terminology (system design, CI/CD, scalability, code review)',
  'Data':               'data and analytics terminology (SQL, dashboards, KPIs, A/B testing, funnel analysis)',
  'Sales':              'sales terminology (pipeline, ARR, discovery calls, objection handling, quota)',
}

const STYLE_INSTRUCTIONS: Record<NonNullable<UserProfile['communicationStyle']>, string> = {
  direct:        'Be concise and direct. Skip pleasantries. Lead with the recommendation, follow with evidence.',
  collaborative: 'Use an inclusive, collaborative tone. Frame suggestions as team decisions. Acknowledge tradeoffs.',
  analytical:    'Be data-driven and methodical. Structure responses with clear reasoning. Reference metrics where possible.',
}

export function generateSystemPrompt(userProfile: UserProfile): string {
  const domain    = userProfile.domain ?? 'General'
  const style     = userProfile.communicationStyle ?? 'direct'
  const vocab     = DOMAIN_VOCAB[domain] ?? `${domain} terminology`
  const styleInst = STYLE_INSTRUCTIONS[style]
  const seniorityNote = userProfile.yearsExperience != null
    ? ` The user has ${userProfile.yearsExperience} years of experience — calibrate depth accordingly.`
    : ''
  const skillsNote = userProfile.topSkills && userProfile.topSkills.length > 0
    ? ` Acknowledge their strengths in: ${userProfile.topSkills.slice(0, 5).join(', ')}.`
    : ''

  const prompt = [
    `You are assisting a ${domain} professional.`,
    styleInst,
    `Use ${vocab} naturally — do not over-explain domain concepts.`,
    seniorityNote,
    skillsNote,
  ].filter(Boolean).join(' ')

  return prompt
}
