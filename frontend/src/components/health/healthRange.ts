import { createContext, useContext } from 'react'
import { addDays, parseDate, todayISO } from '../../lib/format'

/**
 * R12 §A: one range + frequency control for every Health section.
 * A selection is a preset (7d · 4w · 3m · 6m · 1y) or custom dates (≤ 2 years), plus a
 * frequency (day · week · month, or auto: day ≤ 3 months, week ≤ 1 year, month beyond).
 * Kept per section in the URL (`?range=4w` | `?start=&end=`, `&freq=`) and localStorage.
 */

export type Preset = '7d' | '4w' | '3m' | '6m' | '1y'
export type Freq = 'day' | 'week' | 'month'
export type FreqChoice = Freq | 'auto'

export type Selection =
  | { kind: 'preset'; range: Preset; freq: FreqChoice }
  | { kind: 'custom'; start: string; end: string; freq: FreqChoice }

export const PRESETS: Array<{ value: Preset; label: string; long: string }> = [
  { value: '7d', label: '7d', long: '7 days' },
  { value: '4w', label: '4w', long: '4 weeks' },
  { value: '3m', label: '3m', long: '3 months' },
  { value: '6m', label: '6m', long: '6 months' },
  { value: '1y', label: '1y', long: '1 year' },
]
export const PRESET_DAYS: Record<Preset, number> = { '7d': 7, '4w': 28, '3m': 91, '6m': 182, '1y': 365 }
export const MAX_DAYS = 730
export const FREQ_WORD: Record<Freq, string> = { day: 'daily', week: 'weekly', month: 'monthly' }
export const FREQ_NOUN: Record<Freq, string> = { day: 'day', week: 'week', month: 'month' }

const isPreset = (v: unknown): v is Preset => typeof v === 'string' && v in PRESET_DAYS
const isFreq = (v: unknown): v is FreqChoice => v === 'auto' || v === 'day' || v === 'week' || v === 'month'
const ISO = /^\d{4}-\d{2}-\d{2}$/

/** Inclusive day count of start..end. */
export const daySpan = (start: string, end: string) =>
  Math.round((parseDate(end).getTime() - parseDate(start).getTime()) / 86_400_000) + 1

/** Spec default: day for ≤ 3 months, week for ≤ 1 year, month beyond. */
export const autoFreq = (days: number): Freq => (days <= 92 ? 'day' : days <= 366 ? 'week' : 'month')

/** A frequency needs a few buckets to be worth a chart. */
export const freqAllowed = (freq: Freq, days: number) =>
  freq === 'day' ? true : freq === 'week' ? days >= 14 : days >= 60

/** Why custom dates are not usable yet (null = fine). */
export function customError(start: string, end: string): string | null {
  if (!start || !end || !ISO.test(start) || !ISO.test(end)) return 'Pick both dates.'
  if (start > end) return '“From” must be on or before “to”.'
  if (end > todayISO()) return '“To” can’t be in the future.'
  if (daySpan(start, end) > MAX_DAYS) return 'Pick at most two years.'
  return null
}

export type Period = {
  selection: Selection
  start: string
  end: string
  days: number
  /** The same-length period just before (what "vs previous" means). */
  compareStart: string
  compareEnd: string
  /** Effective bucket. */
  freq: Freq
  /** Query string for the API: `range=4w&freq=day` or `start=…&end=…&freq=…`. */
  params: string
  /** "4w" or "1 Sep – 30 Sep" (pill text before the frequency). */
  short: string
  /** "4 weeks" or "1 Sep – 30 Sep". */
  long: string
}

export function resolve(sel: Selection): Period {
  let start: string
  let end: string
  if (sel.kind === 'preset') {
    end = todayISO()
    start = addDays(end, -(PRESET_DAYS[sel.range] - 1))
  } else {
    start = sel.start
    end = sel.end
  }
  const days = daySpan(start, end)
  const wanted = sel.freq === 'auto' ? autoFreq(days) : sel.freq
  const freq = freqAllowed(wanted, days) ? wanted : autoFreq(days)
  const base = sel.kind === 'preset' ? `range=${sel.range}` : `start=${start}&end=${end}`
  const span = rangeText(start, end)
  return {
    selection: sel,
    start, end, days,
    compareStart: addDays(start, -days),
    compareEnd: addDays(start, -1),
    freq,
    params: `${base}&freq=${freq}`,
    short: sel.kind === 'preset' ? sel.range : span,
    long: sel.kind === 'preset' ? PRESETS.find((p) => p.value === sel.range)!.long : span,
  }
}

const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const MONTH = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
const WD = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

/** "1 Sep" / "1 Sep 2025" — fixed English short months ("Sep", not "Sept"). */
const dm = (iso: string, year = false) => {
  const d = parseDate(iso)
  return `${d.getDate()} ${MON[d.getMonth()]}${year ? ` ${d.getFullYear()}` : ''}`
}

/** "1 Sep – 30 Sep" (adds years when the range crosses one or isn't this year). */
export function rangeText(start: string, end: string): string {
  const thisYear = String(new Date().getFullYear())
  const year = start.slice(0, 4) !== end.slice(0, 4) || end.slice(0, 4) !== thisYear
  return `${dm(start, year && start.slice(0, 4) !== end.slice(0, 4))} – ${dm(end, year)}`
}

/** "1 Sep – 30 Sep vs previous 30 days · weekly" — the period under a chart. */
export function periodCaption(p: Pick<Period, 'start' | 'end' | 'days' | 'freq'>, opts: { compare?: boolean; freq?: boolean } = {}): string {
  const { compare = true, freq = true } = opts
  const parts = [rangeText(p.start, p.end)]
  if (compare) parts[0] += ` vs previous ${p.days} ${p.days === 1 ? 'day' : 'days'}`
  if (freq && p.freq !== 'day') parts.push(`per ${FREQ_NOUN[p.freq]}`)
  return parts.join(' · ')
}

/** The pill: "4w · weekly". */
export const pillText = (p: Period) => `${p.short} · ${FREQ_WORD[p.freq]}`

/**
 * The server's `period` (R12) when present, else ours. Lets captions use the exact
 * dates the backend used.
 */
export type ApiPeriod = { start?: string | null; end?: string | null; compare_start?: string | null; compare_end?: string | null; freq?: string | null } | null | undefined
export function withApiPeriod(p: Period, api: ApiPeriod): Period {
  if (!api?.start || !api.end) return p
  const freq = isFreq(api.freq) && api.freq !== 'auto' ? api.freq : p.freq
  return {
    ...p,
    start: api.start,
    end: api.end,
    days: daySpan(api.start, api.end),
    compareStart: api.compare_start ?? p.compareStart,
    compareEnd: api.compare_end ?? p.compareEnd,
    freq,
  }
}

// --- URL + storage ------------------------------------------------------------------

const storeKey = (section: string) => `rc.health.range.${section}`

/** `?range=` / `?start=&end=` / `&freq=` → selection (null when absent/invalid). */
export function fromSearch(search: URLSearchParams): Selection | null {
  const freqRaw = search.get('freq')
  const freq: FreqChoice = isFreq(freqRaw) ? freqRaw : 'auto'
  const start = search.get('start')
  const end = search.get('end')
  if (start && end && !customError(start, end)) return { kind: 'custom', start, end, freq }
  const range = search.get('range')
  if (isPreset(range)) return { kind: 'preset', range, freq }
  return null
}

export function writeSearch(search: URLSearchParams, sel: Selection): URLSearchParams {
  const next = new URLSearchParams(search)
  next.delete('range')
  next.delete('start')
  next.delete('end')
  next.delete('freq')
  if (sel.kind === 'preset') next.set('range', sel.range)
  else {
    next.set('start', sel.start)
    next.set('end', sel.end)
  }
  if (sel.freq !== 'auto') next.set('freq', sel.freq)
  return next
}

export function readStored(section: string): Selection | null {
  try {
    const raw = localStorage.getItem(storeKey(section))
    if (!raw) return null
    const v = JSON.parse(raw) as Partial<Selection> & { range?: string; start?: string; end?: string; freq?: string }
    const freq: FreqChoice = isFreq(v.freq) ? v.freq : 'auto'
    if (v.kind === 'preset' && isPreset(v.range)) return { kind: 'preset', range: v.range, freq }
    if (v.kind === 'custom' && v.start && v.end && !customError(v.start, v.end)) return { kind: 'custom', start: v.start, end: v.end, freq }
  } catch {
    /* storage blocked or junk: fall back to the default */
  }
  return null
}

export function writeStored(section: string, sel: Selection) {
  try {
    localStorage.setItem(storeKey(section), JSON.stringify(sel))
  } catch {
    /* ignore */
  }
}

// --- context ------------------------------------------------------------------------

export type RangeValue = {
  /** Section key the selection belongs to ('' = none). */
  section: string
  period: Period
  setSelection: (s: Selection) => void
  /** Open the range sheet (the header pill does this too). */
  openSheet: () => void
}

const fallback = resolve({ kind: 'preset', range: '4w', freq: 'auto' })

/** The Health header's range control, scoped to the section on screen. */
export const RangeContext = createContext<RangeValue>({ section: '', period: fallback, setSelection: () => {}, openSheet: () => {} })

export const useHealthPeriod = () => useContext(RangeContext)

// --- bucketing (charts) ---------------------------------------------------------------

export type Agg = 'mean' | 'sum' | 'last'
type Pt = { date: string; value: number | null }

/** Monday of the ISO week / the 1st of the month / the day itself. */
export function bucketStart(iso: string, freq: Freq): string {
  if (freq === 'day') return iso.slice(0, 10)
  if (freq === 'month') return `${iso.slice(0, 7)}-01`
  const d = parseDate(iso)
  const back = (d.getDay() + 6) % 7
  return addDays(iso.slice(0, 10), -back)
}

/**
 * Aggregate a dated series into buckets (mean for rates, sum for counts, last for
 * levels). Already-bucketed series (dated on bucket starts) come out unchanged, so this
 * is safe whether or not the server bucketed them.
 */
export function bucket<T extends Pt>(points: T[], freq: Freq, agg: Agg = 'mean'): Pt[] {
  if (freq === 'day' || points.length === 0) return points
  const groups = new Map<string, number[]>()
  for (const p of points) {
    const key = bucketStart(p.date, freq)
    if (!groups.has(key)) groups.set(key, [])
    if (p.value != null && Number.isFinite(p.value)) groups.get(key)!.push(p.value)
  }
  return [...groups.entries()]
    .sort(([a], [b]) => (a < b ? -1 : 1))
    .map(([date, v]) => ({
      date,
      value: !v.length ? null : agg === 'sum' ? v.reduce((s, x) => s + x, 0) : agg === 'last' ? v[v.length - 1] : v.reduce((s, x) => s + x, 0) / v.length,
    }))
}

// --- axis labels ----------------------------------------------------------------------

/** X tick text per frequency: "14 Sep" (day), "Sep 14" (week), "Oct" (month). */
export function tickFor(freq: Freq) {
  return (iso: string) => {
    const d = parseDate(iso)
    if (freq === 'month') return MON[d.getMonth()]
    if (freq === 'week') return `${MON[d.getMonth()]} ${d.getDate()}`
    return dm(iso)
  }
}

/** Tooltip title per frequency: "Tue 14 Sep", "Week of 14 Sep", "October 2026". */
export function tipFor(freq: Freq) {
  return (iso: string) => {
    if (!iso) return ''
    const d = parseDate(iso)
    if (freq === 'month') return `${MONTH[d.getMonth()]} ${d.getFullYear()}`
    if (freq === 'week') return `Week of ${dm(iso)}`
    return `${WD[d.getDay()]} ${dm(iso)}`
  }
}

/** Which x ticks to label: months for daily data, ~5 evenly spaced weeks, every (other) month. */
export function ticksFor(dates: string[], freq: Freq): string[] {
  if (dates.length <= 2) return dates
  if (freq === 'month') return dates.length > 8 ? dates.filter((_, i) => i % 2 === 0) : dates
  if (freq === 'week') {
    const want = Math.min(5, dates.length)
    const step = (dates.length - 1) / (want - 1)
    return [...new Set(Array.from({ length: want }, (_, i) => dates[Math.round(i * step)]))]
  }
  const firsts = dates.filter((d) => d.endsWith('-01'))
  if (firsts.length >= 2) return firsts.length > 6 ? firsts.filter((_, i) => i % 2 === 0) : firsts
  return [dates[0], dates[Math.floor(dates.length / 2)], dates[dates.length - 1]]
}
