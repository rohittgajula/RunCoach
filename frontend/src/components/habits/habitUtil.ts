import type { HabitKind } from '../../lib/types'

export const HABITS: Array<{ kind: HabitKind; emoji: string; label: string; unit: string; units: string }> = [
  { kind: 'smoke', emoji: '🚬', label: 'Smoke', unit: 'cigarette', units: 'cigarettes' },
  { kind: 'alcohol', emoji: '🍺', label: 'Drink', unit: 'drink', units: 'drinks' },
  { kind: 'sugar', emoji: '🍫', label: 'Sugar', unit: 'serving', units: 'servings' },
]

export const habitMeta = (kind: HabitKind) => HABITS.find((h) => h.kind === kind) ?? HABITS[0]

export const countText = (kind: HabitKind, n: number) => {
  const m = habitMeta(kind)
  const v = Number.isInteger(n) ? String(n) : n.toFixed(1)
  return `${v} ${n === 1 ? m.unit : m.units}`
}

/** "+1 cigarette logged" etc. */
export const loggedText = (kind: HabitKind, n: number) => `${habitMeta(kind).emoji} ${countText(kind, n)} logged`
