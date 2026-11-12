/**
 * R14 §1 "Customise Today": the optional cards under the hero, saved on the athlete as
 * `today_layout` — the enabled keys, in order. Null/absent = the defaults below. Cards
 * that are off by default still live in their home tab (Plan / Health), so turning one
 * on here only adds a shortcut.
 */
export type TodayCardKey =
  | 'weather_swap' | 'checkins' | 'injury' | 'review' | 'mood'
  | 'weather' | 'log'
  | 'wake' | 'so_far' | 'this_week' | 'tomorrow' | 'adjustments' | 'weekly_report'

export type TodayCardDef = { key: TodayCardKey; label: string; hint: string; on: boolean }

export const TODAY_CARDS: TodayCardDef[] = [
  { key: 'weather_swap', label: 'Weather swap suggestions', hint: 'Only when a run day looks bad', on: true },
  { key: 'checkins', label: 'Post-run check-ins', hint: 'Only when one is waiting', on: true },
  { key: 'injury', label: 'Injury watch', hint: 'Only at moderate or high risk', on: true },
  { key: 'review', label: 'Run review', hint: 'For 24 h after a run', on: true },
  { key: 'mood', label: 'Mood & energy', hint: 'Until you answer today', on: true },
  { key: 'weather', label: 'Weather', hint: 'Now, best time to run', on: true },
  { key: 'log', label: 'Log now', hint: 'Habits, cravings, caffeine', on: true },
  { key: 'wake', label: 'Tonight → tomorrow', hint: 'Evenings · also in Health → Sleep', on: false },
  { key: 'so_far', label: 'Today so far', hint: 'Steps, stress · also in Health → Day', on: false },
  { key: 'this_week', label: 'This week', hint: 'Runs and km · also in Plan', on: false },
  { key: 'tomorrow', label: 'Tomorrow’s readiness', hint: 'Estimate · also in Health', on: false },
  { key: 'adjustments', label: 'Plan adjustments', hint: 'Upcoming changes · also in Plan', on: false },
  { key: 'weekly_report', label: 'Weekly report', hint: 'Mondays · also in Health → Reports', on: false },
]

const KEYS = new Set<string>(TODAY_CARDS.map((c) => c.key))
export const DEFAULT_LAYOUT: TodayCardKey[] = TODAY_CARDS.filter((c) => c.on).map((c) => c.key)

/** The enabled cards, in order, from whatever the server sent (null-tolerant). */
export function resolveLayout(saved: unknown): TodayCardKey[] {
  if (!Array.isArray(saved)) return DEFAULT_LAYOUT
  const out: TodayCardKey[] = []
  for (const k of saved) {
    if (typeof k === 'string' && KEYS.has(k) && !out.includes(k as TodayCardKey)) out.push(k as TodayCardKey)
  }
  return out
}
