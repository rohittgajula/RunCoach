import type { WeatherToday } from '../../lib/types'

export const deg = (v: number | null | undefined) => (v == null ? '--' : `${Math.round(v)}°`)

/** "06:00" / "2026-10-07T06:00" (athlete-local) → "6 AM" / "6:30 AM". */
export function clock(value: string): string {
  const match = /(?:T|^)(\d{1,2}):(\d{2})/.exec(value)
  if (!match) return value
  const d = new Date()
  d.setHours(Number(match[1]), Number(match[2]), 0, 0)
  return d.toLocaleTimeString(undefined, { hour: 'numeric', minute: match[2] === '00' ? undefined : '2-digit' })
}

export const windowText = (w: WeatherToday['best_window']) => (w ? `${clock(w.start)}–${clock(w.end)}` : '')

/** US AQI bands. */
export function aqiTone(aqi: number | null | undefined): { word: string; tone: 'ok' | 'warn' | 'bad' | 'none' } {
  if (aqi == null) return { word: '', tone: 'none' }
  if (aqi <= 50) return { word: 'good', tone: 'ok' }
  if (aqi <= 100) return { word: 'moderate', tone: 'ok' }
  if (aqi <= 150) return { word: 'unhealthy for sensitive', tone: 'warn' }
  return { word: 'unhealthy', tone: 'bad' }
}

export const levelTone = (level: string) =>
  /bad|warn|danger|high/i.test(level) ? 'bad' : /caution|watch|moder/i.test(level) ? 'warn' : 'info'

export const ml = (v: number | string | null | undefined) =>
  v == null || v === '' ? '' : typeof v === 'number' ? `${Math.round(v)} ml` : v
