import type { HabitKind } from '../../lib/types'
import { DrinkIcon, MoonIcon, SmokeIcon, SugarIcon } from '../Icons'

/** Habit glyph in the Habits topic colour (🌙 Private stays a moon, nothing more). */
export function HabitIcon({ kind, size = 20 }: { kind: HabitKind; size?: number }) {
  const Icon = kind === 'smoke' ? SmokeIcon : kind === 'alcohol' ? DrinkIcon : kind === 'sugar' ? SugarIcon : MoonIcon
  return <Icon size={size} className="habit-icon" />
}
