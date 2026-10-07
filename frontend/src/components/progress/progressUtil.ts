import { dur, duration, pace } from '../../lib/format'
import type { Progress, ProgressBest, ProgressMetric, ProgressWindow } from '../../lib/types'

export const WINDOWS: Array<{ value: `${ProgressWindow}`; label: string }> = [
  { value: '1', label: 'Last 1' },
  { value: '5', label: '5' },
  { value: '10', label: '10' },
  { value: '20', label: '20' },
]

const isPace = (unit: string) => /s\/km|min\/km|pace/i.test(unit)

/** Unit shown once next to the label in compact tables. */
export const unitLabel = (unit: string) =>
  isPace(unit) ? '/km' : unit === 's' || unit === 'time' || unit === 'fraction' ? '' : unit === 'm/min/bpm' ? '' : unit

/** A value in the metric's own unit, readable; `compact` drops the unit (tables). */
export function fmtValue(value: number | null | undefined, unit: string, compact = false): string {
  if (value == null || !Number.isFinite(value)) return '--'
  if (compact && isPace(unit)) return pace(value)
  if (compact && unit === 'km') return value.toFixed(2)
  if (compact && unit === '%') return value.toFixed(value < 10 ? 1 : 0)
  if (compact && unit && !['s', 'm', 'time', 'fraction'].includes(unit)) {
    return value.toFixed(Math.abs(value) < 10 && !Number.isInteger(value) ? 2 : 0)
  }
  if (isPace(unit)) return `${pace(value)} /km`
  if (unit === 's') return dur(value)
  if (unit === 'time') return duration(value)
  if (unit === 'm') return value >= 1000 ? `${(value / 1000).toFixed(2)} km` : `${Math.round(value)} m`
  if (unit === 'km') return `${value.toFixed(2)} km`
  if (unit === '%') return `${value.toFixed(value < 10 ? 1 : 0)}%`
  if (unit === 'fraction') return `${Math.round(value * 100)}%`
  const digits = Math.abs(value) < 10 && !Number.isInteger(value) ? 2 : 0
  return `${value.toFixed(digits)}${unit ? ` ${unit}` : ''}`
}

/** "−12 s/km", "+3 bpm", "+0.40 km" — signed change in the metric's unit. */
export function fmtDelta(m: ProgressMetric, compact = false): string {
  const d = m.delta
  if (d == null || !Number.isFinite(d)) return ''
  const sign = d > 0 ? '+' : d < 0 ? '−' : '±'
  const a = Math.abs(d)
  if (isPace(m.unit)) return `${sign}${Math.round(a)}${compact ? 's' : ' s/km'}`
  if (compact && m.unit === 'km') return `${sign}${a.toFixed(2)}`
  if (compact && m.unit === '%') return `${sign}${a.toFixed(1)}`
  if (compact && m.unit && !['s', 'm', 'time', 'fraction'].includes(m.unit)) return `${sign}${a.toFixed(a < 10 && !Number.isInteger(a) ? 2 : 0)}`
  if (m.unit === 's') return `${sign}${dur(a)}`
  if (m.unit === 'm') return a >= 1000 ? `${sign}${(a / 1000).toFixed(2)} km` : `${sign}${Math.round(a)} m`
  if (m.unit === 'fraction') return `${sign}${Math.round(a * 100)} pts`
  if (m.unit === '%') return `${sign}${a.toFixed(1)} pts`
  const digits = a < 10 && !Number.isInteger(a) ? 2 : 0
  return `${sign}${a.toFixed(digits)}${m.unit ? ` ${m.unit}` : ''}`
}

export const windowText = (w: ProgressWindow) =>
  w === 1 ? 'Your last run vs the average of the 5 before it' : `Your last ${w} runs vs the ${w} before them`

const BESTS: Record<string, { label: string; unit: string }> = {
  fastest_1k_s: { label: 'Fastest 1 km', unit: 'time' },
  longest_run_km: { label: 'Longest run', unit: 'km' },
  longest_continuous_s: { label: 'Longest continuous run', unit: 's' },
  lowest_easy_hr: { label: 'Lowest HR at easy pace', unit: 'bpm' },
}

/** `bests` arrives as {key: {value, date, new} | null}; the list shows the ones that exist. */
export function bestsList(bests: Progress['bests'] | ProgressBest[] | null | undefined): ProgressBest[] {
  if (!bests) return []
  if (Array.isArray(bests)) return bests
  return Object.entries(bests).flatMap(([key, b]) =>
    b && b.value != null
      ? [{ key, label: BESTS[key]?.label ?? key.replace(/_/g, ' '), unit: BESTS[key]?.unit ?? '', value: b.value, date: b.date, is_new: !!b.new, activity_id: b.activity_id }]
      : [])
}
