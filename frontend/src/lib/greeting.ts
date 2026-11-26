// The greeting and date in the app header ("Good evening, Ron · Thursday, 26
// November"). Moved here from Overview when they left its hero for the header.

export function timeOfDay(): 'morning' | 'afternoon' | 'evening' | 'night' {
  const h = new Date().getHours()
  if (h >= 5  && h < 12) return 'morning'
  if (h >= 12 && h < 17) return 'afternoon'
  if (h >= 17 && h < 21) return 'evening'
  return 'night'
}

// Takes the locale so the weekday and month names follow the interface
// language; a Hebrew page showing an English date reads as untranslated.
export function todayLabel(locale: string): string {
  return new Date().toLocaleDateString(locale === 'he' ? 'he-IL' : 'en-GB', {
    weekday: 'long', day: 'numeric', month: 'long',
  })
}
