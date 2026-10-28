import { describe, expect, it } from 'vitest'
import { applyA11y, DEFAULT_A11Y } from './a11yPrefs'

// The menu's preferences must actually reach the page (classes/filters/zoom
// on <html>/<body>) and "reset" must undo every one of them.

function fakeDoc() {
  const classes = new Set<string>()
  const bodyProps: Record<string, string> = {}
  const doc = {
    documentElement: {
      classList: { toggle: (c: string, on: boolean) => { if (on) classes.add(c); else classes.delete(c) } },
      style: { filter: '' },
    },
    body: { style: { setProperty: (k: string, v: string) => { bodyProps[k] = v } } },
  }
  return { doc: doc as unknown as Document, classes, bodyProps }
}

describe('applyA11y', () => {
  it('applies every chosen preference', () => {
    const { doc, classes, bodyProps } = fakeDoc()
    applyA11y({ font: 'large', contrast: true, grayscale: true, noAnimation: true,
      highlightLinks: true, readableFont: true, focusRing: true }, doc)
    expect(Array.from(classes).sort()).toEqual(
      ['a11y-focus-ring', 'a11y-highlight-links', 'a11y-no-animation', 'a11y-readable-font'])
    expect(doc.documentElement.style.filter).toBe('contrast(1.35) grayscale(1)')
    expect(bodyProps.zoom).toBe('1.2')
  })

  it('reset removes everything', () => {
    const { doc, classes, bodyProps } = fakeDoc()
    applyA11y({ ...DEFAULT_A11Y, contrast: true, noAnimation: true, font: 'small' }, doc)
    applyA11y(DEFAULT_A11Y, doc)
    expect(classes.size).toBe(0)
    expect(doc.documentElement.style.filter).toBe('')
    expect(bodyProps.zoom).toBe('')
  })
})
