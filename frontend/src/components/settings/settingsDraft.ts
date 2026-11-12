import type { Athlete, PlanReflow } from '../../lib/auth'

/** Everything the Settings form edits, as strings where it is a text input. */
export type Draft = {
  display_name: string
  sex: '' | 'male' | 'female'
  date_of_birth: string
  height_cm: string
  timezone: string
  available_days: Record<string, boolean>
  long_run_day: number
  max_hr: string
  resting_hr: string
  diet_goal: 'maintain' | 'lose' | 'gain'
  diet_rate_kg_per_week: number
  // R8
  runs_per_week: number | null
  smoke_goal: 'quit' | 'reduce' | 'none'
  smoke_quit_date: string
  smoke_baseline_per_day: string
  cigarette_price: string
  alcohol_goal: 'reduce' | 'none'
  sugar_goal: 'reduce' | 'none'
  // R9 §B
  private_habit_enabled: boolean
  private_on_today: boolean
  private_goal: 'reduce' | 'none'
  location_source: 'runs' | 'city'
  location_city: string
  // R13
  auto_adjust_plan: boolean
  strength_per_week: number
  // Which weekdays are gym days, and what is in the gym. Both decide the
  // calendar and neither had a control until now.
  gym_days: Record<string, boolean>
  gym_equipment: string
  caffeine_on_today: boolean
  pain_daily_check: boolean
}

export type SetDraft = <K extends keyof Draft>(key: K, value: Draft[K]) => void

const str = (v: number | null | undefined) => (v != null ? String(v) : '')

export const toDraft = (a: Athlete): Draft => ({
  display_name: a.display_name ?? '',
  sex: a.sex ?? '',
  date_of_birth: a.date_of_birth ?? '',
  height_cm: str(a.height_cm),
  timezone: a.timezone ?? '',
  available_days: a.available_days ?? {},
  long_run_day: a.long_run_day ?? 6,
  max_hr: str(a.max_hr),
  resting_hr: str(a.resting_hr),
  diet_goal: a.diet_goal ?? 'maintain',
  diet_rate_kg_per_week: a.diet_rate_kg_per_week ?? 0.25,
  runs_per_week: a.runs_per_week ?? null,
  smoke_goal: a.smoke_goal ?? 'none',
  smoke_quit_date: a.smoke_quit_date ?? '',
  smoke_baseline_per_day: str(a.smoke_baseline_per_day),
  cigarette_price: str(a.cigarette_price),
  alcohol_goal: a.alcohol_goal ?? 'none',
  sugar_goal: a.sugar_goal ?? 'none',
  private_habit_enabled: !!a.private_habit_enabled,
  private_on_today: !!a.private_on_today,
  private_goal: a.private_goal ?? 'none',
  location_source: a.location_source === 'city' || a.location_city ? 'city' : 'runs',
  location_city: a.location_city || (a.location_source === 'city' ? a.location_name ?? '' : ''),
  auto_adjust_plan: a.auto_adjust_plan ?? true,
  strength_per_week: a.strength_per_week ?? 0,
  gym_days: a.gym_days ?? {},
  gym_equipment: a.gym_equipment ?? 'bodyweight',
  caffeine_on_today: !!a.caffeine_on_today,
  pain_daily_check: !!a.pain_daily_check,
})

const num = (text: string) => (text.trim() === '' ? null : Number(text))

/** The PATCH body. Location goes only when it changed (a city triggers a geocode). */
export function toPatch(draft: Draft, athlete: Athlete): Partial<Athlete> & { location_city?: string } {
  const before = toDraft(athlete)
  const patch: Partial<Athlete> & { location_city?: string } = {
    display_name: draft.display_name,
    sex: draft.sex || null,
    date_of_birth: draft.date_of_birth || null,
    height_cm: num(draft.height_cm),
    timezone: draft.timezone,
    available_days: draft.available_days,
    long_run_day: draft.long_run_day,
    max_hr: num(draft.max_hr),
    resting_hr: num(draft.resting_hr),
    diet_goal: draft.diet_goal,
    diet_rate_kg_per_week: draft.diet_rate_kg_per_week,
    runs_per_week: draft.runs_per_week,
    smoke_goal: draft.smoke_goal,
    smoke_quit_date: draft.smoke_quit_date || null,
    smoke_baseline_per_day: num(draft.smoke_baseline_per_day),
    cigarette_price: num(draft.cigarette_price),
    alcohol_goal: draft.alcohol_goal,
    sugar_goal: draft.sugar_goal,
  }
  // Only sent once touched, so a backend without the fields never sees them.
  if (draft.private_habit_enabled !== before.private_habit_enabled) patch.private_habit_enabled = draft.private_habit_enabled
  if (draft.private_on_today !== before.private_on_today) patch.private_on_today = draft.private_on_today
  if (draft.private_goal !== before.private_goal) patch.private_goal = draft.private_goal
  // R13 — only once touched (an older server never sees them).
  if (draft.auto_adjust_plan !== before.auto_adjust_plan) patch.auto_adjust_plan = draft.auto_adjust_plan
  if (draft.strength_per_week !== before.strength_per_week) patch.strength_per_week = draft.strength_per_week
  if (JSON.stringify(draft.gym_days) !== JSON.stringify(before.gym_days)) patch.gym_days = draft.gym_days
  if (draft.gym_equipment !== before.gym_equipment) patch.gym_equipment = draft.gym_equipment
  if (draft.caffeine_on_today !== before.caffeine_on_today) patch.caffeine_on_today = draft.caffeine_on_today
  if (draft.pain_daily_check !== before.pain_daily_check) patch.pain_daily_check = draft.pain_daily_check
  if (draft.location_source !== before.location_source || draft.location_city.trim() !== before.location_city.trim()) {
    patch.location_source = draft.location_source
    // An empty city hands the location back to your runs.
    patch.location_city = draft.location_source === 'city' ? draft.location_city.trim() : ''
  }
  return patch
}

// "Upcoming workouts moved to your new days (2 updated on your watch)."
export function reflowText(reflow: PlanReflow | null | undefined): string {
  if (!reflow) return ''
  const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`
  const extras: string[] = []
  if (reflow.dropped) extras.push(`${plural(reflow.dropped, 'easy session')} dropped to fit`)
  if (reflow.watch_updated) extras.push(`${reflow.watch_updated} updated on your watch`)
  if (reflow.watch_removed) extras.push(`${reflow.watch_removed} removed from your watch`)
  const head = reflow.regenerated
    ? `${plural(reflow.regenerated, 'upcoming session')} rebuilt — same weekly total, new split`
    : reflow.moved
      ? 'Upcoming workouts moved to your new days'
      : 'Your plan now fits your new days'
  return `${head}${extras.length ? ` (${extras.join(', ')})` : ''}.`
}
