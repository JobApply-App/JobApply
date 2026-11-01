import { describe, expect, it } from 'vitest'
import { localizeReason, reasonSkill } from './reasonLabel'
import { dictionaries } from '../locales'

const he = dictionaries.he.job_card.reason_labels
const en = dictionaries.en.job_card.reason_labels

describe('localizeReason', () => {
  it('translates every shape the server builds', () => {
    expect(localizeReason('No Sql exp. (required)', he)).toBe('אין ניסיון ב-Sql (דרישת חובה)')
    expect(localizeReason('No Figma exp. (preferred)', he)).toBe('אין ניסיון ב-Figma (יתרון)')
    expect(localizeReason('Academic Python (Prof. Req.)', he)).toContain('Python')
    expect(localizeReason('Python (academic match)', he)).toContain('Python')
    expect(localizeReason('Fintech domain fit', he)).toContain('Fintech')
    expect(localizeReason('Remote', he)).not.toBe('Remote')
  })

  it('leaves English labels as they were', () => {
    for (const label of ['No Sql exp. (required)', 'No Figma exp. (preferred)', 'Academic Python (Prof. Req.)',
                         'Python (academic match)', 'Fintech domain fit', 'Remote']) {
      expect(localizeReason(label, en)).toBe(label)
    }
  })

  it('shows a bare skill name as it came', () => {
    expect(localizeReason('Salesforce', he)).toBe('Salesforce')
  })
})

describe('reasonSkill', () => {
  it('pulls the skill out of a gap label', () => {
    expect(reasonSkill('No Sql exp. (required)')).toBe('Sql')
    expect(reasonSkill('Salesforce')).toBe('Salesforce')
  })
})
