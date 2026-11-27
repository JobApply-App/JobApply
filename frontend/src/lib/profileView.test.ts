import { describe, expect, it } from 'vitest'
import {
  capabilityDomains, companyEntries, latestRole, knowledgeTopics, periodYears, roleFamilies, roleFamily, when,
  type ProfileExperience, type ProfileView,
} from './profileView'
import type { AboutAnswers } from './api'

const job = (company: string, role: string, start: string, end: string, extra: Partial<ProfileExperience> = {}): ProfileExperience =>
  ({ company, role, start, end, details: 'Did things.', kind: '', source: 'cv', ...extra })

// Ron's real timeline (27.11), most recent first, plus the parallel
// Customer Service role he defined and his army service.
const RON: ProfileExperience[] = [
  job('JobApply', 'Founder', '2026', 'present'),
  job('GO-OUT', 'Customer Success and Partnerships Team Lead', '2025', '2026'),
  job('GO-OUT', 'Customer Success and Partnerships Manager', '2023', '2025'),
  job('GO-OUT', 'Customer Service', '2023', '2025', { source: 'ariel' }),
  job('Solution', 'Insurance and Financial Referent', '2020', '2023'),
  job('IDF', 'Staff Officer', '2017', '2019', { kind: 'military' }),
]

describe('roleFamilies', () => {
  it('puts similar target roles together, in the order the user first named one', () => {
    const groups = roleFamilies([
      { role: 'Customer Success Manager', seniority: 'senior' },
      { role: 'Product Manager', seniority: 'mid' },
      { role: 'Account Manager', seniority: 'senior' },
    ])
    expect(groups.map(g => g.family)).toEqual(['customer', 'product'])
    expect(groups[0].items.map(i => i.role)).toEqual(['Customer Success Manager', 'Account Manager'])
  })

  it('reads the more specific family first', () => {
    expect(roleFamily('Product Designer')).toBe('design')
    expect(roleFamily('Sales Engineer')).toBe('sales')
    expect(roleFamily('מנהל מוצר')).toBe('product')
    expect(roleFamily('Chef')).toBe('other')
  })
})

describe('capabilityDomains', () => {
  const entities = [
    { name: 'Jira', category: 'Product', score: 50.2 },
    { name: 'Figma', category: 'Product', score: 12.7 },
    { name: 'Python', category: 'Technical', score: 64.7 },
    { name: 'Monday', category: 'Technical', score: 12.0 },
    { name: 'B2B2C SaaS', category: 'Domain', score: 69.0 },
  ]

  it('builds only the domains the user has, strongest first, skills strongest first', () => {
    const d = capabilityDomains(entities)
    expect(d.map(x => x.category)).toEqual(['Domain', 'Technical', 'Product'])
    expect(d[1].skills.map(s => s.name)).toEqual(['Python', 'Monday'])
    expect(d[2].avg).toBeCloseTo(31.45)
  })

  it('leaves hidden capabilities out of the domain and its average', () => {
    const d = capabilityDomains(entities, ['figma'])
    expect(d.find(x => x.category === 'Product')).toMatchObject({ count: 1, avg: 50.2 })
  })
})

describe('companyEntries', () => {
  it('stacks a company\'s roles into one entry and shows a parallel role beside its twin', () => {
    const e = companyEntries(RON)
    expect(e.map(c => c.company)).toEqual(['JobApply', 'GO-OUT', 'Solution'])
    const go = e[1]
    expect(go.start).toBe('2023')
    expect(go.end).toBe('2026')
    expect(go.steps.map(s => s.role.role)).toEqual([
      'Customer Success and Partnerships Team Lead', 'Customer Success and Partnerships Manager',
    ])
    expect(go.steps[1].parallel.map(p => p.role)).toEqual(['Customer Service'])
    expect(go.steps[0].parallel).toEqual([])   // 2023-2025 then 2025-2026 follow each other
  })

  it('keeps army service out of the job timeline', () => {
    expect(companyEntries(RON).some(c => c.company === 'IDF')).toBe(false)
  })

  it('the headline role is the newest job, ended or not, never army service', () => {
    expect(latestRole(RON)?.role).toBe('Founder')
    expect(latestRole(RON.slice(1))?.role).toBe('Customer Success and Partnerships Team Lead')
    expect(latestRole(RON.slice(5))).toBeNull()
  })

  it('keeps a stint together when a course sits between its roles, and finds roles held side by side', () => {
    // Ron's stored timeline (27.11), as Ariel wrote it: month dates, a course in the middle.
    const e = companyEntries([
      job('GO-OUT', 'Customer Success Team Leader', '2025-03', '2026-02'),
      job('GO-OUT', 'Team Manager - Partnerships & Customer Service', '2025-01', '2026-02'),
      job('Pitango Academy', 'Product Management Course', '2024-11', '2025-03'),
      job('GO-OUT', 'Customer Success & Partnerships Team Lead', '2023-01', '2026-02'),
      job('GO-OUT', 'Customer Success Manager', '2023-04', '2025-03'),
      job('GO-OUT', 'Customer Support Representative', '2023-03', '2024-08'),
      job('Solution', 'Insurance & Financial Referent', '2020-01', '2023-01'),
    ])
    expect(e.map(c => c.company)).toEqual(['GO-OUT', 'Pitango Academy', 'Solution'])
    const go = e[0]
    expect([go.start, go.end]).toEqual(['2023-01', '2026-02'])
    expect(go.steps.map(s => [s.role.role, s.parallel.map(p => p.role)])).toEqual([
      // Both end 2026-02; the one that started first leads.
      ['Team Manager - Partnerships & Customer Service', ['Customer Success Team Leader']],
      ['Customer Success & Partnerships Team Lead', ['Customer Success Manager', 'Customer Support Representative']],
    ])
  })

  it('reads months and shows years', () => {
    expect(when('2023-04', Infinity)).toBeCloseTo(2023.25)
    expect(when('present', Infinity)).toBe(Infinity)
    expect(periodYears('2023-01', '2026-02', 'present')).toBe('2023–2026')
    expect(periodYears('2026', '', 'היום')).toBe('2026–היום')
    expect(periodYears('2025-01', '2025-09', 'present')).toBe('2025')
  })
})

describe('knowledgeTopics', () => {
  const view: ProfileView = {
    personal: { name: '', email: '', phone: '', linkedin: '', location: '' },
    summary: '',
    education: [{ degree: 'BA', school: 'Reichman', period: '2020-2023', status: '' }],
    experience: RON,
    languages: [],
  }
  const about: AboutAnswers = {
    gender: 'male', locations: [], work_environment: null, career_change: null,
    home_city: 'פתח תקווה', home_abroad: null, search_mode: 'radius', radius_km: null,
  } as AboutAnswers

  it('scores each topic from what is actually known, with one decimal', () => {
    const { topics, overall } = knowledgeTopics({
      view, about,
      entities: Array.from({ length: 12 }, (_, i) => ({ name: `s${i}`, category: 'Technical', score: 10 * (i + 1) })),
      roles: [{ role: 'Product Manager', seniority: 'mid' }],
    })
    const v = Object.fromEntries(topics.map(t => [t.id, t.value]))
    // 5 jobs, all described; 1 of 5 talked through with Ariel: 70 + 30 * 1/5
    expect(v.exp).toBe(76)
    // the ten strongest of 10..120
    expect(v.cap).toBe(75)
    // home + roles of 5
    expect(v.mob).toBe(40)
    // degree + army of 4
    expect(v.edu).toBe(50)
    expect(overall).toBe(60.3)
  })

  it('lists what is missing', () => {
    const { topics } = knowledgeTopics({ view, about, entities: [], roles: [] })
    const mob = topics.find(t => t.id === 'mob')!
    expect(mob.checks.filter(c => !c.ok).map(c => c.key)).toEqual(['mob_roles', 'mob_range', 'mob_work_model', 'mob_career_change'])
    expect(topics.find(t => t.id === 'cap')!.value).toBe(0)
  })
})
