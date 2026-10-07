import { isIOS } from '../../lib/push'

/**
 * R12 §B. A web app can't set the phone's alarm clock or a Garmin watch's alarms; on
 * Android an intent URL opens the Clock app with the time filled in, on iOS we show the
 * time and say where to set it.
 */

export type Platform = 'android' | 'ios' | 'other'

export function platform(): Platform {
  if (typeof navigator === 'undefined') return 'other'
  if (/Android/i.test(navigator.userAgent)) return 'android'
  if (isIOS()) return 'ios'
  return 'other'
}

/** "HH:MM" → [hour, minute] (null when malformed). */
export function parseTime(t: string | null | undefined): [number, number] | null {
  const m = /^(\d{1,2}):(\d{2})/.exec(t ?? '')
  if (!m) return null
  const h = Number(m[1])
  const min = Number(m[2])
  return h < 24 && min < 60 ? [h, min] : null
}

/** The spec's SET_ALARM intent for the given time. */
export function alarmIntent(time: string): string | null {
  const hm = parseTime(time)
  if (!hm) return null
  return `intent:#Intent;action=android.intent.action.SET_ALARM;i.android.intent.extra.alarm.HOUR=${hm[0]};i.android.intent.extra.alarm.MINUTES=${hm[1]};S.android.intent.extra.alarm.MESSAGE=RunCoach;end`
}

/** "6:15 AM" / "06:15" in the reader's locale, always with minutes. */
export function alarmClock(t: string | null | undefined): string {
  const hm = parseTime(t)
  if (!hm) return '--:--'
  const d = new Date()
  d.setHours(hm[0], hm[1], 0, 0)
  return d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

export const DAY_SHORT = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
export const DAY_LETTER = ['M', 'T', 'W', 'T', 'F', 'S', 'S']

/** [0,1,2,3,4] → "Mon–Fri"; all → "Every day"; [5,6] → "Weekends"; else "Mon, Wed, Fri". */
export function daysText(days: number[] | null | undefined, once = false): string {
  if (once) return 'Once'
  const d = [...new Set(days ?? [])].filter((x) => x >= 0 && x <= 6).sort((a, b) => a - b)
  if (!d.length) return 'No days'
  if (d.length === 7) return 'Every day'
  if (d.length === 2 && d[0] === 5 && d[1] === 6) return 'Weekends'
  const consecutive = d.every((x, i) => i === 0 || x === d[i - 1] + 1)
  if (consecutive && d.length >= 3) return `${DAY_SHORT[d[0]]}–${DAY_SHORT[d[d.length - 1]]}`
  return d.map((x) => DAY_SHORT[x]).join(', ')
}

/** Minutes between two "HH:MM" (b − a), wrapping over midnight within ±12 h. */
export function minutesBetween(a: string, b: string): number | null {
  const x = parseTime(a)
  const y = parseTime(b)
  if (!x || !y) return null
  let d = y[0] * 60 + y[1] - (x[0] * 60 + x[1])
  if (d > 720) d -= 1440
  if (d < -720) d += 1440
  return d
}

/** Is it evening (≥ 18:00) on this device? Today shows the planner then. */
export const isEvening = (now = new Date()) => now.getHours() >= 18
