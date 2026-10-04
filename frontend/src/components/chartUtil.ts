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
