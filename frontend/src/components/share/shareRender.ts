/**
 * R13 §12: share cards drawn client-side on a canvas → PNG. Nothing leaves the device
 * until the athlete taps Share. Cards show only what is printed on them — no health
 * details, no map tiles, and a run's route is cut short at both ends so home/start
 * points are never revealed.
 */

export type ShareCard =
  | {
      kind: 'run'
      title: string
      date: string
      distance_m: number | null
      duration_s: number | null
      pace_s_per_km: number | null
      avg_hr?: number | null
      /** Route as [lat, lon]; already trimmed by the server when possible. */
      route?: Array<[number, number]> | null
      /** True when the server already cut the start and finish off. */
      endpointsHidden?: boolean
    }
  | {
      kind: 'week'
      label: string
      runs: number
      km: number | null
      duration_s: number | null
      /** 7 values Mon→Sun, km per day (0 when rest). */
      days?: number[] | null
    }
  | { kind: 'badge'; label: string; description: string; date?: string | null }
  | { kind: 'race'; name: string; date: string; distance_km: number; target_s: number | null; pace_s_per_km: number | null; strategy: string }
  | { kind: 'smoke_free'; days: number; saved?: string | null }

const W = 1080
const H = 1350
const FONT = '"Plus Jakarta Sans", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif'

const PALETTE = {
  run: ['#2f6bff', '#1f4fcc'],
  week: ['#2f6bff', '#7a5af8'],
  badge: ['#f2a516', '#f26b3a'],
  smoke_free: ['#0e9f9a', '#2f6bff'],
  race: ['#101418', '#2f6bff'],
} as const

function fmtDur(s: number | null | undefined): string {
  if (s == null || !Number.isFinite(s)) return '--'
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = Math.round(s % 60)
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}` : `${m}:${String(sec).padStart(2, '0')}`
}

function fmtPace(s: number | null | undefined): string {
  if (s == null || !Number.isFinite(s) || s <= 0) return '--'
  const m = Math.floor(s / 60)
  const sec = Math.round(s % 60)
  return sec === 60 ? `${m + 1}:00` : `${m}:${String(sec).padStart(2, '0')}`
}

function haversine(a: [number, number], b: [number, number]): number {
  const R = 6371000
  const toR = (d: number) => (d * Math.PI) / 180
  const dLat = toR(b[0] - a[0])
  const dLon = toR(b[1] - a[1])
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toR(a[0])) * Math.cos(toR(b[0])) * Math.sin(dLon / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(h))
}

/**
 * Cut `metres` off both ends of a route. Used when the server did not already hide the
 * endpoints — a share card never shows where a run started or finished.
 */
export function trimRoute(points: Array<[number, number]>, metres = 300): Array<[number, number]> {
  if (points.length < 4) return []
  const cum = [0]
  for (let i = 1; i < points.length; i++) cum.push(cum[i - 1] + haversine(points[i - 1], points[i]))
  const total = cum[cum.length - 1]
  if (total < metres * 3) return []
  return points.filter((_, i) => cum[i] >= metres && cum[i] <= total - metres)
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.arcTo(x + w, y, x + w, y + h, r)
  ctx.arcTo(x + w, y + h, x, y + h, r)
  ctx.arcTo(x, y + h, x, y, r)
  ctx.arcTo(x, y, x + w, y, r)
  ctx.closePath()
}

function background(ctx: CanvasRenderingContext2D, colors: readonly [string, string]) {
  const g = ctx.createLinearGradient(0, 0, W, H)
  g.addColorStop(0, colors[0])
  g.addColorStop(1, colors[1])
  ctx.fillStyle = g
  ctx.fillRect(0, 0, W, H)
  // Soft rings, a quiet nod to the app's topic rings.
  ctx.strokeStyle = 'rgba(255,255,255,0.08)'
  ctx.lineWidth = 60
  ctx.beginPath()
  ctx.arc(W - 80, 160, 260, 0, Math.PI * 2)
  ctx.stroke()
  ctx.beginPath()
  ctx.arc(80, H - 120, 200, 0, Math.PI * 2)
  ctx.stroke()
}

function brand(ctx: CanvasRenderingContext2D) {
  ctx.fillStyle = 'rgba(255,255,255,0.92)'
  ctx.font = `800 40px ${FONT}`
  ctx.textAlign = 'left'
  ctx.textBaseline = 'alphabetic'
  ctx.fillText('RunCoach', 80, H - 80)
}

function label(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, align: CanvasTextAlign = 'left') {
  ctx.fillStyle = 'rgba(255,255,255,0.75)'
  ctx.font = `700 30px ${FONT}`
  ctx.textAlign = align
  ctx.fillText(text.toUpperCase(), x, y)
}

function big(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, size: number, align: CanvasTextAlign = 'left') {
  ctx.fillStyle = '#ffffff'
  ctx.font = `800 ${size}px ${FONT}`
  ctx.textAlign = align
  ctx.fillText(text, x, y)
}

/** Fit text into maxWidth by shrinking, then ellipsis. */
function fitText(ctx: CanvasRenderingContext2D, text: string, maxWidth: number, size: number, weight = 800): number {
  let s = size
  ctx.font = `${weight} ${s}px ${FONT}`
  while (ctx.measureText(text).width > maxWidth && s > 28) {
    s -= 2
    ctx.font = `${weight} ${s}px ${FONT}`
  }
  return s
}

function drawRoute(ctx: CanvasRenderingContext2D, pts: Array<[number, number]>, box: { x: number; y: number; w: number; h: number }) {
  ctx.save()
  roundRect(ctx, box.x, box.y, box.w, box.h, 40)
  ctx.fillStyle = 'rgba(255,255,255,0.12)'
  ctx.fill()
  if (pts.length < 2) {
    ctx.fillStyle = 'rgba(255,255,255,0.7)'
    ctx.font = `600 32px ${FONT}`
    ctx.textAlign = 'center'
    ctx.fillText('No route to show', box.x + box.w / 2, box.y + box.h / 2)
    ctx.restore()
    return
  }
  const lat0 = pts.reduce((s, p) => s + p[0], 0) / pts.length
  const k = Math.cos((lat0 * Math.PI) / 180)
  const xs = pts.map((p) => p[1] * k)
  const ys = pts.map((p) => -p[0])
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys)
  const pad = 60
  const scale = Math.min((box.w - pad * 2) / (maxX - minX || 1e-9), (box.h - pad * 2) / (maxY - minY || 1e-9))
  const ox = box.x + (box.w - (maxX - minX) * scale) / 2
  const oy = box.y + (box.h - (maxY - minY) * scale) / 2
  ctx.lineJoin = 'round'
  ctx.lineCap = 'round'
  ctx.strokeStyle = 'rgba(0,0,0,0.18)'
  ctx.lineWidth = 18
  ctx.beginPath()
  xs.forEach((x, i) => {
    const px = ox + (x - minX) * scale
    const py = oy + (ys[i] - minY) * scale + 4
    if (i) ctx.lineTo(px, py)
    else ctx.moveTo(px, py)
  })
  ctx.stroke()
  ctx.strokeStyle = '#ffffff'
  ctx.lineWidth = 12
  ctx.beginPath()
  xs.forEach((x, i) => {
    const px = ox + (x - minX) * scale
    const py = oy + (ys[i] - minY) * scale
    if (i) ctx.lineTo(px, py)
    else ctx.moveTo(px, py)
  })
  ctx.stroke()
  ctx.restore()
}

function statRow(ctx: CanvasRenderingContext2D, stats: Array<[string, string]>, y: number) {
  const n = stats.length
  const colW = (W - 160) / n
  stats.forEach(([l, v], i) => {
    const x = 80 + colW * i
    label(ctx, l, x, y)
    const size = fitText(ctx, v, colW - 20, 64)
    big(ctx, v, x, y + size + 10, size)
  })
}

function drawRun(ctx: CanvasRenderingContext2D, c: Extract<ShareCard, { kind: 'run' }>) {
  background(ctx, PALETTE.run)
  label(ctx, c.date, 80, 120)
  const size = fitText(ctx, c.title || 'Run', W - 160, 64)
  big(ctx, c.title || 'Run', 80, 120 + size + 16, size)
  const raw = c.route ?? []
  const pts = c.endpointsHidden ? raw : trimRoute(raw)
  drawRoute(ctx, pts, { x: 80, y: 260, w: W - 160, h: 600 })
  const kmText = c.distance_m != null ? (c.distance_m / 1000).toFixed(2) : '--'
  label(ctx, 'Distance', 80, 940)
  big(ctx, kmText, 80, 1060, 120)
  ctx.font = `800 120px ${FONT}`
  const w = ctx.measureText(kmText).width
  ctx.fillStyle = 'rgba(255,255,255,0.8)'
  ctx.font = `700 44px ${FONT}`
  ctx.fillText(' km', 80 + w, 1060)
  const stats: Array<[string, string]> = [['Time', fmtDur(c.duration_s)], ['Pace /km', fmtPace(c.pace_s_per_km)]]
  if (c.avg_hr != null) stats.push(['Avg HR', `${Math.round(c.avg_hr)}`])
  statRow(ctx, stats, 1130)
  brand(ctx)
}

function drawWeek(ctx: CanvasRenderingContext2D, c: Extract<ShareCard, { kind: 'week' }>) {
  background(ctx, PALETTE.week)
  label(ctx, 'My week', 80, 120)
  const size = fitText(ctx, c.label, W - 160, 72)
  big(ctx, c.label, 80, 120 + size + 16, size)
  // Bars Mon→Sun.
  const days = (c.days && c.days.length === 7 ? c.days : null) ?? null
  const box = { x: 80, y: 300, w: W - 160, h: 520 }
  roundRect(ctx, box.x, box.y, box.w, box.h, 40)
  ctx.fillStyle = 'rgba(255,255,255,0.12)'
  ctx.fill()
  if (days) {
    const max = Math.max(...days, 1)
    const slot = (box.w - 80) / 7
    days.forEach((v, i) => {
      const bh = v > 0 ? Math.max(14, ((box.h - 160) * v) / max) : 8
      const x = box.x + 40 + slot * i + slot * 0.18
      const bw = slot * 0.64
      ctx.fillStyle = v > 0 ? '#ffffff' : 'rgba(255,255,255,0.3)'
      roundRect(ctx, x, box.y + box.h - 90 - bh, bw, bh, 14)
      ctx.fill()
      ctx.fillStyle = 'rgba(255,255,255,0.8)'
      ctx.font = `700 30px ${FONT}`
      ctx.textAlign = 'center'
      ctx.fillText('MTWTFSS'[i], x + bw / 2, box.y + box.h - 40)
    })
  } else {
    big(ctx, c.km != null ? c.km.toFixed(1) : '--', W / 2, box.y + box.h / 2 + 50, 200, 'center')
    ctx.fillStyle = 'rgba(255,255,255,0.8)'
    ctx.font = `700 44px ${FONT}`
    ctx.textAlign = 'center'
    ctx.fillText('km this week', W / 2, box.y + box.h / 2 + 130)
  }
  statRow(ctx, [
    ['Runs', String(c.runs)],
    ['Distance', c.km != null ? `${c.km.toFixed(1)} km` : '--'],
    ['Time', fmtDur(c.duration_s)],
  ], 920)
  brand(ctx)
}

function drawMedal(ctx: CanvasRenderingContext2D, cx: number, cy: number, r: number) {
  ctx.fillStyle = 'rgba(255,255,255,0.18)'
  ctx.beginPath()
  ctx.arc(cx, cy, r + 40, 0, Math.PI * 2)
  ctx.fill()
  ctx.fillStyle = '#ffffff'
  ctx.beginPath()
  ctx.arc(cx, cy, r, 0, Math.PI * 2)
  ctx.fill()
  // Star
  ctx.fillStyle = '#f2a516'
  ctx.beginPath()
  for (let i = 0; i < 10; i++) {
    const a = -Math.PI / 2 + (i * Math.PI) / 5
    const rr = i % 2 ? r * 0.28 : r * 0.62
    const x = cx + rr * Math.cos(a)
    const y = cy + rr * Math.sin(a)
    if (i) ctx.lineTo(x, y)
    else ctx.moveTo(x, y)
  }
  ctx.closePath()
  ctx.fill()
}

function wrap(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, maxW: number, lineH: number, maxLines = 3) {
  const words = text.split(/\s+/)
  let line = ''
  let n = 0
  for (const w of words) {
    const test = line ? `${line} ${w}` : w
    if (ctx.measureText(test).width > maxW && line) {
      ctx.fillText(line, x, y + n * lineH)
      n++
      line = w
      if (n >= maxLines) return
    } else line = test
  }
  if (line) ctx.fillText(line, x, y + n * lineH)
}

function drawBadge(ctx: CanvasRenderingContext2D, c: Extract<ShareCard, { kind: 'badge' }>) {
  background(ctx, PALETTE.badge)
  label(ctx, 'Badge earned', W / 2, 140, 'center')
  drawMedal(ctx, W / 2, 480, 200)
  const size = fitText(ctx, c.label, W - 160, 80)
  big(ctx, c.label, W / 2, 860, size, 'center')
  ctx.fillStyle = 'rgba(255,255,255,0.9)'
  ctx.font = `600 40px ${FONT}`
  ctx.textAlign = 'center'
  wrap(ctx, c.description, W / 2, 940, W - 200, 54)
  if (c.date) label(ctx, c.date, W / 2, 1140, 'center')
  brand(ctx)
}

function drawSmokeFree(ctx: CanvasRenderingContext2D, c: Extract<ShareCard, { kind: 'smoke_free' }>) {
  background(ctx, PALETTE.smoke_free)
  label(ctx, 'Smoke-free', W / 2, 160, 'center')
  ctx.strokeStyle = 'rgba(255,255,255,0.25)'
  ctx.lineWidth = 36
  ctx.beginPath()
  ctx.arc(W / 2, 560, 300, 0, Math.PI * 2)
  ctx.stroke()
  ctx.strokeStyle = '#ffffff'
  ctx.lineCap = 'round'
  ctx.beginPath()
  const share = Math.min(1, c.days / 30)
  ctx.arc(W / 2, 560, 300, -Math.PI / 2, -Math.PI / 2 + Math.max(0.02, share) * Math.PI * 2)
  ctx.stroke()
  big(ctx, String(c.days), W / 2, 610, 200, 'center')
  ctx.fillStyle = 'rgba(255,255,255,0.85)'
  ctx.font = `700 48px ${FONT}`
  ctx.textAlign = 'center'
  ctx.fillText(c.days === 1 ? 'day' : 'days', W / 2, 690)
  if (c.saved) {
    label(ctx, 'Money saved', W / 2, 1000, 'center')
    big(ctx, c.saved, W / 2, 1090, 80, 'center')
  }
  brand(ctx)
}

function drawRace(ctx: CanvasRenderingContext2D, c: Extract<ShareCard, { kind: 'race' }>) {
  background(ctx, PALETTE.race)
  label(ctx, 'Race plan', 80, 120)
  const size = fitText(ctx, c.name, W - 160, 76)
  big(ctx, c.name, 80, 120 + size + 16, size)
  label(ctx, `${c.date} · ${c.distance_km} km`, 80, 300)
  roundRect(ctx, 80, 360, W - 160, 440, 40)
  ctx.fillStyle = 'rgba(255,255,255,0.12)'
  ctx.fill()
  label(ctx, 'Target', W / 2, 450, 'center')
  big(ctx, fmtDur(c.target_s), W / 2, 610, 160, 'center')
  ctx.fillStyle = 'rgba(255,255,255,0.85)'
  ctx.font = `700 44px ${FONT}`
  ctx.textAlign = 'center'
  ctx.fillText(`${fmtPace(c.pace_s_per_km)} /km · ${c.strategy}`, W / 2, 710)
  ctx.fillStyle = 'rgba(255,255,255,0.9)'
  ctx.font = `600 40px ${FONT}`
  wrap(ctx, 'Start easy. Hold back in the first kilometre — the finish is where the race is won.', W / 2, 920, W - 200, 54)
  brand(ctx)
}

/** Draw a card and return it as a PNG blob. */
export async function renderShareCard(card: ShareCard): Promise<Blob> {
  try {
    await (document as Document & { fonts?: FontFaceSet }).fonts?.ready
  } catch {
    /* fonts are a nicety */
  }
  const canvas = document.createElement('canvas')
  canvas.width = W
  canvas.height = H
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('Canvas is not available on this device.')
  if (card.kind === 'run') drawRun(ctx, card)
  else if (card.kind === 'week') drawWeek(ctx, card)
  else if (card.kind === 'badge') drawBadge(ctx, card)
  else if (card.kind === 'race') drawRace(ctx, card)
  else drawSmokeFree(ctx, card)
  return new Promise((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('Could not draw the image.'))), 'image/png'),
  )
}

export function shareFileName(card: ShareCard): string {
  const base = card.kind === 'smoke_free' ? 'smoke-free' : card.kind
  return `runcoach-${base}.png`
}
