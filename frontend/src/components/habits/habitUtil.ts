import type { Athlete } from '../../lib/auth'
import type { HabitKind, HabitStatus } from '../../lib/types'

export type HabitMeta = { kind: HabitKind; emoji: string; label: string; unit: string; units: string }

/** The three everyday habits, in quick-log order. */
export const HABITS: HabitMeta[] = [
  { kind: 'smoke', emoji: '🚬', label: 'Smoke', unit: 'cigarette', units: 'cigarettes' },
  { kind: 'alcohol', emoji: '🍺', label: 'Drink', unit: 'drink', units: 'drinks' },
  { kind: 'sugar', emoji: '🍫', label: 'Sugar', unit: 'serving', units: 'servings' },
]

/** R9 §B — only ever "🌙 Private"; no other wording anywhere. */
export const PRIVATE_HABIT: HabitMeta = { kind: 'private', emoji: '🌙', label: 'Private', unit: 'time', units: 'times' }

const ALL = [...HABITS, PRIVATE_HABIT]

export const habitMeta = (kind: HabitKind) => ALL.find((h) => h.kind === kind) ?? HABITS[0]

/** Habits offered where logging happens. `where: 'today'` also needs "Show on today card". */
export function loggableHabits(athlete: Athlete | null | undefined, where: 'today' | 'any' = 'any'): HabitMeta[] {
  const enabled = !!athlete?.private_habit_enabled
  const show = where === 'today' ? enabled && !!athlete?.private_on_today : enabled
  return show ? ALL : HABITS
}

export const countText = (kind: HabitKind, n: number) => {
  const m = habitMeta(kind)
  const v = Number.isInteger(n) ? String(n) : n.toFixed(1)
  return `${v} ${n === 1 ? m.unit : m.units}`
}

/** "+1 cigarette logged" etc. Private stays wordless: "🌙 logged". */
export const loggedText = (kind: HabitKind, n: number) =>
  kind === 'private' ? `🌙 ${n === 1 ? '' : `${n}× `}logged` : `${habitMeta(kind).emoji} ${countText(kind, n)} logged`

export const STATUS_TEXT: Record<HabitStatus, string> = {
  improving: 'Improving',
  worsening: 'Worsening',
  steady: 'Steady',
  not_enough_data: 'Not enough data',
}

export const statusTag = (s: HabitStatus | undefined | null) =>
  s === 'improving' ? 'tag-ok' : s === 'worsening' ? 'tag-bad' : s === 'steady' ? 'tag-steady' : ''

/** localStorage, never throwing (private mode, blocked storage). */
export function readFlag(key: string): boolean {
  try {
    return window.localStorage.getItem(key) === '1'
  } catch {
    return false
  }
}
export function writeFlag(key: string, on: boolean) {
  try {
    if (on) window.localStorage.setItem(key, '1')
    else window.localStorage.removeItem(key)
  } catch {
    /* storage unavailable — the choice just isn't remembered */
  }
}

export const PRIVATE_SHOWN_KEY = 'runcoach.habits.private-shown'

/** Counts start at 1; only alcohol allows a half drink. Never 0 — remove by deleting. */
export const minQty = (kind: HabitKind) => (kind === 'alcohol' ? 0.5 : 1)
export const lessQty = (kind: HabitKind, q: number) => Math.max(minQty(kind), q - (q > 1 ? 1 : 0.5))
export const moreQty = (_kind: HabitKind, q: number) => (q < 1 ? q + 0.5 : q + 1)
