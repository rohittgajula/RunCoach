import { isoDate, parseDate } from '../../lib/format'
import type { MonthDay, MonthDayStatus } from '../../lib/types'

/** "2026-10" for a YYYY-MM-DD date. */
export const monthOf = (iso: string) => iso.slice(0, 7)

export const shiftMonth = (month: string, by: number) => {
  const d = parseDate(`${month}-01`)
  d.setMonth(d.getMonth() + by)
  return isoDate(d).slice(0, 7)
}

export const monthLabel = (month: string) =>
  parseDate(`${month}-01`).toLocaleDateString(undefined, { month: 'long', year: 'numeric' })

/** Mon-first grid: leading nulls, then every day of the month. */
export function monthCells(month: string, days: MonthDay[] | undefined): Array<MonthDay | null> {
  const first = parseDate(`${month}-01`)
  const lead = (first.getDay() + 6) % 7
  const byDate = new Map((days ?? []).map((d) => [d.date, d]))
  const cells: Array<MonthDay | null> = Array.from({ length: lead }, () => null)
  const d = new Date(first)
  while (d.getMonth() === first.getMonth()) {
    const iso = isoDate(d)
    cells.push(byDate.get(iso) ?? { date: iso, planned: null, status: null, activities: [] })
    d.setDate(d.getDate() + 1)
  }
  while (cells.length % 7) cells.push(null)
  return cells
}

export const STATUS_TEXT: Record<MonthDayStatus, string> = {
  done: 'Done', partial: 'Partly done', missed: 'Missed', planned: 'Planned', extra: 'Extra run',
  rest: 'Rest', today: 'Today',
}

export const LEGEND: Array<{ status: MonthDayStatus; label: string }> = [
  { status: 'done', label: 'Done' },
  { status: 'partial', label: 'Partial' },
  { status: 'missed', label: 'Missed' },
  { status: 'planned', label: 'Planned' },
  { status: 'extra', label: 'Extra' },
]
