import { describe, expect, it } from 'vitest'
import { en } from '../locales/en'
import { he } from '../locales/he'

// The Ariel probe asks exactly three questions (backend
// services/ariel_probe_service.py, turns 1-3). With four labels the result
// question appeared under "Action" with a Finish button, and "Result" was
// never reached.
describe('probe step labels', () => {
  for (const [lang, dict] of [['en', en], ['he', he]] as const) {
    it(`${lang}: one label per question`, () => {
      for (const labels of Object.values(dict.trust.probe.steps)) {
        expect(labels.split('|')).toHaveLength(3)
      }
    })
  }
})
