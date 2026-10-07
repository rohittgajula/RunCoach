import { dur, pace } from '../../lib/format'
import type { Insights, SeriesPoint } from '../../lib/types'
import type { Better } from '../chartUtil'
import type { Agg } from '../health/healthRange'
import type { Point } from '../MetricChart'
import { clock } from '../StepsList'

export type ChartKey =
  | 'run_fraction' | 'longest_run' | 'easy_pace' | 'cadence'
  | 'hrv' | 'rhr' | 'sleep' | 'body_battery' | 'stress' | 'respiration' | 'vo2max'

/**
 * Series items are `{date, <value>}` where the value key varies by metric (ms, s, value,
 * bpm…). Take the first preferred key present, else the first numeric field.
 */
export function toPoints(series: SeriesPoint[] | null | undefined, prefer: string[] = ['value']): Point[] {
  if (!Array.isArray(series)) return []
  return series.map((item) => {
    let value: number | null = null
    for (const key of prefer) {
      const v = item[key]
      if (typeof v === 'number') { value = v; break }
    }
    if (value == null) {
      for (const [key, v] of Object.entries(item)) {
        if (key !== 'date' && typeof v === 'number') { value = v; break }
      }
    }
    return { date: item.date, value }
  })
}

/** {low, high}, "160-175" or [160, 175] → {low, high}. */
export function parseTarget(target: unknown): { low: number; high: number } | null {
  if (target && typeof target === 'object' && 'low' in target && 'high' in target) {
    const { low, high } = target as { low: unknown; high: unknown }
    return typeof low === 'number' && typeof high === 'number' ? { low, high } : null
  }
  if (Array.isArray(target) && target.length === 2) return { low: Number(target[0]), high: Number(target[1]) }
  if (typeof target === 'string') {
    const m = /(\d+)\s*[-–]\s*(\d+)/.exec(target)
    if (m) return { low: Number(m[1]), high: Number(m[2]) }
  }
  return null
}

/** Fractions arrive as 0–1; show percent. Already-percent series pass through. */
const asPercent = (points: Point[]) => {
  const max = Math.max(...points.map((p) => p.value ?? 0))
  return max <= 1 ? points.map((p) => ({ ...p, value: p.value == null ? null : p.value * 100 })) : points
}

const hm = (seconds: number) => {
  const m = Math.round(seconds / 60)
  return `${Math.floor(m / 60)}:${String(m % 60).padStart(2, '0')}`
}

export type ChartConfig = {
  title: string
  unit: string
  format: (v: number) => string
  reversed?: boolean
  points: (i: Insights) => Point[]
  band?: (i: Insights) => { low: number; high: number; label?: string } | null
  about: string
  /** Which direction is good (null: neither) — colours the delta chip. */
  better: Better
  /** How a change is written ("12 s" for paces); defaults to `format`. */
  delta?: (v: number) => string
  /** R10 topic colour for the chart. */
  topic?: 'run' | 'recovery' | 'sleep'
  /** R12: how a week/month bucket is formed (default mean; levels like VO2max = last). */
  agg?: Agg
}

export const CHARTS: Record<ChartKey, ChartConfig> = {
  run_fraction: {
    topic: 'run',
    better: 'higher', delta: (v) => `${Math.round(v)} pts`,
    title: 'Running share', unit: '% of distance run',
    format: (v) => `${Math.round(v)}%`,
    points: (i) => asPercent(toPoints(i.running?.run_fraction_trend)),
    about: 'How much of each outing you ran rather than walked. Rising slowly is the goal — it means your run blocks are getting longer.',
  },
  longest_run: {
    topic: 'run',
    better: 'higher',
    title: 'Longest continuous run', unit: 'per outing',
    format: (v) => (v >= 3600 ? dur(v) : clock(v)),
    points: (i) => toPoints(i.running?.longest_run_trend, ['s', 'seconds', 'value']),
    about: 'The longest stretch you ran without a walk break. Add 30–60 s at a time.',
  },
  easy_pace: {
    topic: 'run',
    better: 'lower', delta: (v) => `${Math.round(v)} s`,
    title: 'Easy-pace efficiency', unit: 'pace at Z2 heart rate',
    format: (v) => pace(v), reversed: true,
    points: (i) => toPoints(i.running?.easy_pace_trend, ['pace_s_per_km', 's_per_km', 'value']),
    about: 'Your pace while heart rate stays in zone 2. Getting faster at the same effort is aerobic fitness improving.',
  },
  cadence: {
    topic: 'run',
    better: null, delta: (v) => `${Math.round(v)} spm`,
    title: 'Cadence', unit: 'steps per minute',
    format: (v) => String(Math.round(v)),
    // The payload has no cadence series (trend is a weekly slope), so this chart is
    // empty until one is added; the tile still shows avg vs target.
    points: (i) => toPoints((i.running?.cadence as { series?: SeriesPoint[] } | undefined)?.series, ['spm', 'value']),
    band: (i) => {
      const t = parseTarget(i.running?.cadence.target)
      return t ? { ...t, label: 'Target' } : null
    },
    about: 'Steps per minute while running. Shorter, quicker steps (160–175) land under your hips and are easier on knees and shins.',
  },
  hrv: {
    topic: 'recovery',
    better: 'higher', delta: (v) => `${Math.round(v)} ms`,
    title: 'HRV', unit: 'ms, overnight',
    format: (v) => String(Math.round(v)),
    points: (i) => toPoints(i.hrv?.series as SeriesPoint[] | undefined, ['ms', 'value']),
    band: (i) =>
      i.hrv?.baseline_low != null && i.hrv.baseline_high != null
        ? { low: i.hrv.baseline_low, high: i.hrv.baseline_high, label: 'Baseline' }
        : null,
    about: 'Heart-rate variability overnight. Inside your baseline band is normal; several nights below it means recovery is lagging — keep runs easy.',
  },
  rhr: {
    topic: 'recovery',
    better: 'lower', delta: (v) => `${Math.round(v)} bpm`,
    title: 'Resting heart rate', unit: 'bpm',
    format: (v) => String(Math.round(v)),
    points: (i) => toPoints(i.resting_hr?.series, ['bpm', 'value']),
    about: 'A slowly falling resting heart rate is a sign of improving fitness. A jump of 5+ bpm can mean fatigue or illness.',
  },
  sleep: {
    topic: 'sleep',
    better: 'higher', delta: (v) => `${Math.round(v * 60)} min`,
    title: 'Sleep', unit: 'hours per night',
    format: (v) => hm(v * 3600),
    points: (i) => toPoints(i.sleep?.series as SeriesPoint[] | undefined, ['s']).map((p) => ({ ...p, value: p.value == null ? null : p.value / 3600 })),
    band: () => ({ low: 7, high: 9, label: '7–9 h' }),
    about: 'Most adaptation happens while you sleep. Under 7 hours on average makes every run harder to recover from.',
  },
  body_battery: {
    topic: 'recovery',
    better: 'higher',
    title: 'Body Battery', unit: 'Garmin, 0–100',
    format: (v) => String(Math.round(v)),
    points: (i) => toPoints(i.body_battery?.series, ['high', 'value']),
    about: 'Garmin’s estimate of your energy reserve. Waking up high means you recharged overnight.',
  },
  stress: {
    topic: 'recovery',
    better: 'lower',
    title: 'Stress', unit: 'Garmin, 0–100',
    format: (v) => String(Math.round(v)),
    points: (i) => toPoints(i.stress?.series, ['avg', 'value']),
    about: 'All-day stress from heart-rate variability. Life stress counts as training stress too.',
  },
  respiration: {
    topic: 'recovery',
    better: null,
    title: 'Breathing', unit: 'breaths per minute',
    format: (v) => v.toFixed(1),
    points: (i) => toPoints(i.respiration?.series, ['rpm', 'sleep_rpm', 'value']),
    about: 'Breathing rate, mostly measured during sleep. A rise above your usual level can be an early sign of illness — run easy only.',
  },
  vo2max: {
    topic: 'run',
    better: 'higher',
    agg: 'last',
    title: 'VO2max', unit: 'ml/kg/min, Garmin',
    format: (v) => v.toFixed(0),
    points: (i) => toPoints(i.vo2max?.series, ['value']),
    about: 'Garmin’s estimate of your aerobic ceiling. It moves slowly — look at months, not days.',
  },
}
