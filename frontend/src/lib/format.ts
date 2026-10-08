/** Seconds per km as "m:ss". Nobody thinks in 495. */
export const pace = (secondsPerKm: number | null | undefined): string => {
  if (!secondsPerKm || !Number.isFinite(secondsPerKm)) return '—'
  const total = Math.round(secondsPerKm)
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

/** Duration as "12:34" or "1:02:33". */
export const duration = (seconds: number | null | undefined): string => {
  if (seconds == null || !Number.isFinite(seconds)) return '—'
  const total = Math.round(seconds)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  return h
    ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
    : `${m}:${String(s).padStart(2, '0')}`
}

export const km = (metres: number | null | undefined): string =>
  metres == null ? '—' : `${(metres / 1000).toFixed(2)} km`

/** Metres, but as a whole number — for run distances where 967 reads better than 0.97 km. */
export const metres = (value: number | null | undefined): string =>
  value == null ? '—' : `${Math.round(value)} m`

export const day = (iso: string): string =>
  new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  })

// --- RunCoach additions --------------------------------------------------------

/** Compact training duration: "40m", "1h 5m", "2h". */
export const dur = (seconds: number | null | undefined): string => {
  if (seconds == null || !Number.isFinite(seconds)) return '—'
  const minutes = Math.round(seconds / 60)
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  if (!h) return `${m}m`
  return m ? `${h}h ${m}m` : `${h}h`
}

/** "5:30–6:00 /km" from a pace band; tolerates one side missing. */
export const paceBand = (min: number | null | undefined, max: number | null | undefined): string => {
  if (min && max) return `${pace(min)}–${pace(max)} /km`
  if (min || max) return `${pace(min || max)} /km`
  return ''
}

/** "m:ss" text → seconds, or null when unparseable. */
export const parsePace = (text: string): number | null => {
  const match = /^(\d{1,2}):([0-5]\d)$/.exec(text.trim())
  return match ? Number(match[1]) * 60 + Number(match[2]) : null
}

export const round = (value: number | null | undefined, digits = 0): string =>
  value == null || !Number.isFinite(value) ? '--' : value.toFixed(digits)

export const signed = (value: number, digits = 0): string =>
  `${value > 0 ? '+' : value < 0 ? '−' : ''}${Math.abs(value).toFixed(digits)}`

// --- local dates (YYYY-MM-DD, never through UTC) -------------------------------

export const parseDate = (iso: string): Date => new Date(`${iso.slice(0, 10)}T00:00:00`)

export const isoDate = (d: Date): string =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

export const addDays = (iso: string, days: number): string => {
  const d = parseDate(iso)
  d.setDate(d.getDate() + days)
  return isoDate(d)
}

export const todayISO = (): string => isoDate(new Date())

/** "Oct 5" */
export const monthDay = (iso: string): string =>
  parseDate(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })

/** "5 Oct" — the RestOrTrain style in timelines. */
export const dayMonth = (iso: string): string =>
  parseDate(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })

export const weekday = (iso: string): string =>
  parseDate(iso).toLocaleDateString(undefined, { weekday: 'short' })

export const timeOfDay = (iso: string): string =>
  new Date(iso).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })

/** "4 Oct 2026 at 3:08 am" */
export const dateTime = (iso: string): string => {
  const d = new Date(iso)
  return `${d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })} at ${d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}`
}

/** Today → time, this week → weekday, else date. For the chat list. */
export const relativeStamp = (iso: string): string => {
  const d = new Date(iso)
  const now = new Date()
  if (isoDate(d) === isoDate(now)) return timeOfDay(iso)
  const diff = (now.getTime() - d.getTime()) / 86_400_000
  if (diff < 7) return d.toLocaleDateString(undefined, { weekday: 'short' }) + ' ' + timeOfDay(iso)
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
}

/** datetime-local input value for a Date (local clock). */
export const localInputValue = (d: Date): string =>
  `${isoDate(d)}T${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`

/** R18: "≈ 5.2 km · ≈ 2.5 loops" for a planned workout ('' without an estimate). */
export function estimateText(e: { km: number; loops: number | null } | null | undefined): string {
  if (!e || !(e.km > 0)) return ''
  const n = (v: number) => (Math.round(v * 10) / 10).toString()
  return `≈ ${n(e.km)} km${e.loops ? ` · ≈ ${n(e.loops)} ${e.loops === 1 ? 'loop' : 'loops'}` : ''}`
}
