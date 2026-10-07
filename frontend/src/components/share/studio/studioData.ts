/**
 * Build the studio's data from what the app already has (activity card + detail + the
 * route, which the server trims when "hide start/finish" is on), and export it as GPX
 * and CSV. Everything stays on the device.
 */
import type { ActivityRoute, RoutePoint } from '../../../lib/types'
import { trimRoute } from '../shareRender'
import type { Split, StudioData } from './studioRender'

/** km splits from the route's distance/time samples, closed by the activity totals. */
export function splitsFromRoute(points: RoutePoint[], totalM: number | null, totalS: number | null): Split[] {
  const samples: Array<{ d: number; t: number; hr: number | null }> = [{ d: 0, t: 0, hr: null }]
  for (const p of points) {
    const last = samples[samples.length - 1]
    if (p.dist_m > last.d && p.t_s >= last.t) samples.push({ d: p.dist_m, t: p.t_s, hr: p.hr })
  }
  const last = samples[samples.length - 1]
  if (totalM && totalS && totalM > last.d && totalS >= last.t) samples.push({ d: totalM, t: totalS, hr: null })
  const end = samples[samples.length - 1]
  if (end.d < 200) return []
  const timeAt = (d: number) => {
    for (let i = 1; i < samples.length; i++) {
      const a = samples[i - 1]
      const b = samples[i]
      if (d <= b.d) return a.t + ((b.t - a.t) * (d - a.d)) / (b.d - a.d || 1)
    }
    return end.t
  }
  const out: Split[] = []
  for (let km = 1; (km - 1) * 1000 < end.d - 50; km++) {
    const d0 = (km - 1) * 1000
    const d1 = Math.min(km * 1000, end.d)
    const split = timeAt(d1) - timeAt(d0)
    const dist = d1 - d0
    const hrs = samples.filter((s) => s.d > d0 && s.d <= d1 && s.hr != null).map((s) => s.hr as number)
    out.push({
      km,
      split_s: Math.round(split),
      distance_m: Math.round(dist),
      pace_s_per_km: dist > 0 ? Math.round((split * 1000) / dist) : 0,
      avg_hr: hrs.length ? Math.round(hrs.reduce((a, b) => a + b, 0) / hrs.length) : null,
    })
  }
  return out
}

export function bestKm(splits: Split[]): StudioData['best_km'] {
  const full = splits.filter((s) => s.distance_m >= 990)
  if (!full.length) return null
  const b = full.reduce((a, s) => (s.split_s < a.split_s ? s : a))
  return { km: b.km, split_s: b.split_s }
}

/** The route as drawn: the server's trim, or ours when the server sent the full line. */
export function shownRoute(r: ActivityRoute | null | undefined, hideEndpoints: boolean): Array<[number, number]> | null {
  if (!r?.available || r.points.length < 2) return null
  const pts = r.points.map((p) => [p.lat, p.lon] as [number, number])
  if (!hideEndpoints || (r.hidden_endpoints && r.trimmed_m >= 150)) return pts
  const t = trimRoute(pts, 300)
  return t.length > 1 ? t : null
}

const esc = (s: string) => s.replace(/[<>&"']/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;', "'": '&apos;' })[c]!)

/** GPX 1.1 of the shown (trimmed) route. Times only when the route carries them. */
export function toGpx(name: string, startIso: string | null, r: ActivityRoute | null | undefined, route: Array<[number, number]>): string {
  const t0 = startIso ? new Date(startIso).getTime() : NaN
  // Match drawn points back to the samples (same objects, trimmed ends) for ele/time/hr.
  const byKey = new Map((r?.points ?? []).map((p) => [`${p.lat},${p.lon}`, p]))
  const pts = route.map(([la, lo]) => {
    const p = byKey.get(`${la},${lo}`)
    const ele = p?.ele_m != null ? `<ele>${p.ele_m}</ele>` : ''
    const time = p && Number.isFinite(t0) ? `<time>${new Date(t0 + p.t_s * 1000).toISOString()}</time>` : ''
    const hr = p?.hr != null ? `<extensions><gpxtpx:TrackPointExtension><gpxtpx:hr>${p.hr}</gpxtpx:hr></gpxtpx:TrackPointExtension></extensions>` : ''
    return `      <trkpt lat="${la}" lon="${lo}">${ele}${time}${hr}</trkpt>`
  })
  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<gpx version="1.1" creator="RunCoach" xmlns="http://www.topografix.com/GPX/1/1" xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1">',
    `  <metadata><name>${esc(name)}</name></metadata>`,
    `  <trk><name>${esc(name)}</name><type>running</type>`,
    '    <trkseg>',
    ...pts,
    '    </trkseg>',
    '  </trk>',
    '</gpx>',
    '',
  ].join('\n')
}

const hms = (s: number) => {
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = Math.round(s % 60)
  return `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
}
const mss = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`

export function toCsv(splits: Split[]): string {
  let elapsed = 0
  const rows = splits.map((s) => {
    elapsed += s.split_s
    return [s.km, (s.distance_m / 1000).toFixed(2), mss(s.split_s), mss(s.pace_s_per_km), hms(elapsed), s.avg_hr ?? ''].join(',')
  })
  return ['km,distance_km,split_time,pace_per_km,elapsed,avg_hr', ...rows, ''].join('\n')
}

export const fileSlug = (title: string, date: string) =>
  `runcoach-${`${title}-${date}`.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 48) || 'run'}`

/** Save a blob: a temporary <a download>, falling back to opening it. */
export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 30_000)
}
