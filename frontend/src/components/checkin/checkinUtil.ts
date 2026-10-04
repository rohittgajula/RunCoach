import { dur } from '../../lib/format'
import type { SignalReason, Verdict } from '../../lib/types'

/** Pill colour + short word per verdict (green go / blue easy / amber swap / red rest). */
export const VERDICT: Record<Verdict, { word: string; tone: string }> = {
  go: { word: 'Go', tone: 'go' },
  easy: { word: 'Easy', tone: 'easy' },
  swap: { word: 'Swap', tone: 'swap' },
  rest: { word: 'Rest', tone: 'rest' },
  no_plan: { word: 'Rest day', tone: 'none' },
}

const SIGNAL_NAME: Record<string, string> = {
  sleep: 'Sleep', hrv: 'HRV', rhr: 'Resting HR', body_battery: 'Body battery',
  readiness: 'Readiness', pain: 'Pain', illness: 'Illness', load: 'Load', stress: 'Stress',
  rpe: 'Last run effort',
}

export const signalName = (signal: string) => SIGNAL_NAME[signal] ?? signal.replace(/_/g, ' ')

/** Server sends display strings where it can; numbers get a unit by signal. */
export function signalValue(reason: SignalReason): string {
  const v = reason.value
  if (v == null || v === '' || typeof v === 'boolean') return ''
  if (typeof v === 'string') return v
  switch (reason.signal) {
    case 'sleep': return v > 24 ? dur(v) : `${v.toFixed(1)}h`
    case 'hrv': return `${Math.round(v)} ms`
    case 'rhr': return `${Math.round(v)} bpm`
    case 'load': return v.toFixed(2)
    default: return String(Math.round(v))
  }
}

const MISSING: Record<string, string> = {
  sleep: 'No sleep data last night', hrv: 'No HRV last night', rhr: 'No resting HR last night',
  body_battery: 'No body battery', readiness: 'No Garmin readiness today', stress: 'No stress data',
  load: 'Not enough training history for load', rpe: 'No check-in after the last run',
}

export const missingLine = (missing: string[]) =>
  missing.map((m) => MISSING[m] ?? `No ${signalName(m)} data`).join(' · ')

// --- post-run check-in -----------------------------------------------------------

export const RPE_LABELS: Array<[number, string]> = [
  [2, 'Very easy'], [4, 'Easy'], [6, 'Moderate'], [8, 'Hard'], [10, 'Max'],
]
export const rpeLabel = (rpe: number) => RPE_LABELS.find(([top]) => rpe <= top)?.[1] ?? 'Max'

export const LEGS = ['fresh', 'ok', 'heavy', 'sore'] as const
export const BREATHING = ['easy', 'ok', 'hard'] as const
export const PAIN_AREAS = ['foot', 'ankle', 'shin', 'calf', 'knee', 'hip', 'back', 'other'] as const

export const cap = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s)

// --- per-device memory (never required for correctness) ----------------------------

function readSet(key: string): Set<string> {
  try {
    const raw = window.localStorage.getItem(key)
    return new Set(raw ? (JSON.parse(raw) as string[]) : [])
  } catch {
    return new Set()
  }
}

function addToSet(key: string, value: string, keep = 60) {
  try {
    const next = [...readSet(key), value].slice(-keep)
    window.localStorage.setItem(key, JSON.stringify(next))
  } catch {
    /* storage blocked — the sheet may simply prompt again */
  }
}

const PROMPTED = 'rc.checkin.prompted'
export const wasPrompted = (activityId: number) => readSet(PROMPTED).has(String(activityId))
export const markPrompted = (activityId: number) => addToSet(PROMPTED, String(activityId))

const KEPT = 'rc.today.kept'
export const keptPlan = (date: string) => readSet(KEPT).has(date)
export const markKept = (date: string) => addToSet(KEPT, date, 14)
export function unmarkKept(date: string) {
  try {
    const next = [...readSet(KEPT)].filter((d) => d !== date)
    window.localStorage.setItem(KEPT, JSON.stringify(next))
  } catch {
    /* ignore */
  }
}
