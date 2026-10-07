import { parseDate } from '../lib/format'

/** First-of-month dates present in the series → "1 Aug" ticks like RestOrTrain. */
export function monthTicks(dates: string[]): string[] {
  const ticks = dates.filter((d) => d.endsWith('-01'))
  if (ticks.length >= 2) return ticks.length > 6 ? ticks.filter((_, i) => i % 2 === 0) : ticks
  // Short series: start, middle, end.
  if (dates.length < 3) return dates
  return [dates[0], dates[Math.floor(dates.length / 2)], dates[dates.length - 1]]
}

export const tickDate = (iso: string) =>
  parseDate(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })

/** Which way is good for a metric; null = neither (shown grey). */
export type Better = 'higher' | 'lower' | null

export type Trend = {
  avg: number
  last: number
  /** Mean of the later half minus the mean of the earlier half ("vs previous period"). */
  delta: number
  tone: 'good' | 'bad' | 'flat' | 'neutral'
}

/** Split the visible series in two: the later half is "now", the earlier "before". */
export function trendOf(values: Array<number | null | undefined>, better: Better, flatWithin = 0): Trend | null {
  const v = values.filter((x): x is number => x != null && Number.isFinite(x))
  if (v.length < 4) return null
  const mid = Math.floor(v.length / 2)
  const mean = (a: number[]) => a.reduce((s, x) => s + x, 0) / a.length
  const before = mean(v.slice(0, mid))
  const now = mean(v.slice(mid))
  const delta = now - before
  const flat = Math.abs(delta) <= Math.max(flatWithin, Math.abs(before) * 0.01)
  const tone = flat ? 'flat' : better == null ? 'neutral' : (delta > 0) === (better === 'higher') ? 'good' : 'bad'
  return { avg: mean(v), last: v[v.length - 1], delta, tone }
}

/** "HRV 4 ms above your 4-week average." — one sentence from the data. */
export function trendCaption(t: Trend | null, name: string, format: (v: number) => string, unit = '', period = 'period', diffFormat?: (v: number) => string): string | null {
  if (!t) return null
  const diff = t.last - t.avg
  const u = unit ? ` ${unit}` : ''
  if (Math.abs(diff) < Math.max(Math.abs(t.avg) * 0.01, 1e-9)) return `${name} is right on your ${period} average (${format(t.avg)}${u}).`
  // Paces are formatted values (m:ss); say "faster/slower" style through the formatter.
  const d = diffFormat ? diffFormat(Math.abs(diff)) : `${format(Math.abs(diff))}${u}`
  return `Latest ${name} ${format(t.last)}${u} — ${d} ${diff > 0 ? 'above' : 'below'} your ${period} average.`
}
