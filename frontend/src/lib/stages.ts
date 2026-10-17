import type { Dict } from '@/locales'

/** Localised label for an application stage key ("phone screen" -> stages.phone_screen). */
export function stageLabel(stage: string, stages: Dict['applications']['stages']): string {
  const key = stage.toLowerCase().replace(/\s+/g, '_') as keyof typeof stages
  return stages[key] ?? stage.charAt(0).toUpperCase() + stage.slice(1)
}
