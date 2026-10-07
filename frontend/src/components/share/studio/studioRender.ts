/**
 * R15 share studio renderer. Everything is drawn client-side on a canvas at full
 * resolution (1080×1920 / 1080×1080 / 1920×1080); the preview calls the same function on
 * a smaller canvas with a scale factor. A photo the athlete picks never leaves the device.
 */

export type FieldKey =
  | 'route' | 'title' | 'date' | 'weather' | 'distance' | 'time' | 'pace' | 'avg_hr' | 'max_hr'
  | 'elevation' | 'cadence' | 'calories' | 'best_km' | 'splits' | 'brand'

export type Field = { key: FieldKey; on: boolean }
export type SizeKey = 'story' | 'square' | 'landscape'
export type LayoutKey = 'bottom' | 'top' | 'stacked' | 'minimal'
export type Background = 'transparent' | 'solid' | 'photo' | 'map'
export type WeightKey = 'light' | 'regular' | 'bold'

export type StudioOptions = {
  bg: Background
  solid: string
  fields: Field[]
  splitsStyle: 'table' | 'bars'
  routeColor: string
  /** 'auto' picks white or ink from the background. */
  textColor: string
  size: SizeKey
  layout: LayoutKey
  weight: WeightKey
  photoFit: 'cover' | 'contain'
  /** 0–0.8 black overlay on a photo. */
  darken: number
}

export type Split = { km: number; split_s: number; distance_m: number; pace_s_per_km: number; avg_hr?: number | null }

export type StudioData = {
  title: string
  date: string
  distance_m: number | null
  duration_s: number | null
  pace_s_per_km: number | null
  avg_hr: number | null
  max_hr: number | null
  elevation_gain_m: number | null
  cadence_spm: number | null
  calories: number | null
  weather: string | null
  splits: Split[]
  best_km: { km: number; split_s: number } | null
  /** [lat, lon], already trimmed (server or client) — never the true start/finish. */
  route: Array<[number, number]> | null
}

export type Photo = { img: CanvasImageSource; w: number; h: number; ox: number; oy: number }

export const SIZES: Record<SizeKey, { w: number; h: number; label: string }> = {
  story: { w: 1080, h: 1920, label: 'Story' },
  square: { w: 1080, h: 1080, label: 'Square' },
  landscape: { w: 1920, h: 1080, label: 'Landscape' },
}

export const FIELD_LABEL: Record<FieldKey, string> = {
  route: 'Route line', title: 'Title', date: 'Date', weather: 'Weather', distance: 'Distance', time: 'Time',
  pace: 'Pace', avg_hr: 'Avg HR', max_hr: 'Max HR', elevation: 'Elevation', cadence: 'Cadence',
  calories: 'Calories', best_km: 'Best km', splits: 'Km splits', brand: 'RunCoach mark',
}

export const DEFAULT_FIELDS: Field[] = [
  { key: 'title', on: true }, { key: 'date', on: true }, { key: 'route', on: true },
  { key: 'distance', on: true }, { key: 'time', on: true }, { key: 'pace', on: true },
  { key: 'avg_hr', on: false }, { key: 'max_hr', on: false }, { key: 'elevation', on: false },
  { key: 'cadence', on: false }, { key: 'calories', on: false }, { key: 'best_km', on: false },
  { key: 'splits', on: false }, { key: 'weather', on: false }, { key: 'brand', on: true },
]

const FONT = '"Plus Jakarta Sans", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif'
const WEIGHTS: Record<WeightKey, { value: number; label: number; title: number }> = {
  light: { value: 500, label: 500, title: 600 },
  regular: { value: 700, label: 600, title: 700 },
  bold: { value: 800, label: 700, title: 800 },
}
const INK = '#101418'

export function fmtDur(s: number | null | undefined): string {
  if (s == null || !Number.isFinite(s)) return '--'
  const r = Math.round(s)
  const h = Math.floor(r / 3600)
  const m = Math.floor((r % 3600) / 60)
  const sec = r % 60
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}` : `${m}:${String(sec).padStart(2, '0')}`
}

export function fmtPace(s: number | null | undefined): string {
  if (s == null || !Number.isFinite(s) || s <= 0) return '--'
  const r = Math.round(s)
  return `${Math.floor(r / 60)}:${String(r % 60).padStart(2, '0')}`
}

/** Is there anything to draw for this field? (Empty ones are greyed out in the list.) */
export function hasField(d: StudioData, k: FieldKey): boolean {
  switch (k) {
    case 'route': return !!d.route && d.route.length > 1
    case 'title': return !!d.title
    case 'date': return !!d.date
    case 'weather': return !!d.weather
    case 'distance': return d.distance_m != null && d.distance_m > 0
    case 'time': return d.duration_s != null && d.duration_s > 0
    case 'pace': return d.pace_s_per_km != null && d.pace_s_per_km > 0
    case 'avg_hr': return d.avg_hr != null
    case 'max_hr': return d.max_hr != null
    case 'elevation': return d.elevation_gain_m != null
    case 'cadence': return d.cadence_spm != null
    case 'calories': return d.calories != null
    case 'best_km': return !!d.best_km
    case 'splits': return d.splits.length > 0
    case 'brand': return true
  }
}

type Metric = { label: string; value: string; unit: string }
function metric(d: StudioData, k: FieldKey): Metric | null {
  switch (k) {
    case 'distance': return { label: 'Distance', value: ((d.distance_m ?? 0) / 1000).toFixed(2), unit: 'km' }
    case 'time': return { label: 'Time', value: fmtDur(d.duration_s), unit: '' }
    case 'pace': return { label: 'Pace', value: fmtPace(d.pace_s_per_km), unit: '/km' }
    case 'avg_hr': return { label: 'Avg HR', value: String(Math.round(d.avg_hr ?? 0)), unit: 'bpm' }
    case 'max_hr': return { label: 'Max HR', value: String(Math.round(d.max_hr ?? 0)), unit: 'bpm' }
    case 'elevation': return { label: 'Elevation', value: `+${Math.round(d.elevation_gain_m ?? 0)}`, unit: 'm' }
    case 'cadence': return { label: 'Cadence', value: String(Math.round(d.cadence_spm ?? 0)), unit: 'spm' }
    case 'calories': return { label: 'Calories', value: String(Math.round(d.calories ?? 0)), unit: 'kcal' }
    case 'best_km': return d.best_km ? { label: `Best km · ${d.best_km.km}`, value: fmtPace(d.best_km.split_s), unit: '' } : null
    default: return null
  }
}

// --- colour -----------------------------------------------------------------------------

function luminance(hex: string): number {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim())
  if (!m) return 0
  const n = parseInt(m[1], 16)
  const ch = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => {
    const c = v / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]
}

/** White or ink, whichever reads better on the chosen background. */
export function autoText(o: StudioOptions): string {
  if (o.textColor !== 'auto') return o.textColor
  if (o.bg === 'solid') return luminance(o.solid) > 0.4 ? INK : '#ffffff'
  if (o.bg === 'map') return INK
  return '#ffffff'
}

function rgba(hex: string, a: number): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim())
  if (!m) return hex
  const n = parseInt(m[1], 16)
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`
}

// --- projection -----------------------------------------------------------------------

/** Web Mercator in 0…1 world units, so the route lines up with map tiles. */
function merc(lat: number, lon: number): [number, number] {
  const s = Math.sin((Math.max(-85, Math.min(85, lat)) * Math.PI) / 180)
  return [(lon + 180) / 360, 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)]
}

export type Box = { x: number; y: number; w: number; h: number }
export type Fit = { scale: number; cx: number; cy: number; box: Box }

/** Fit the route into a box with padding: world-units → canvas px. */
export function fitRoute(route: Array<[number, number]>, box: Box): Fit | null {
  if (route.length < 2 || box.w < 10 || box.h < 10) return null
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
  for (const [la, lo] of route) {
    const [x, y] = merc(la, lo)
    if (x < x0) x0 = x
    if (x > x1) x1 = x
    if (y < y0) y0 = y
    if (y > y1) y1 = y
  }
  const pad = Math.min(box.w, box.h) * 0.08
  const sw = Math.max(x1 - x0, 1e-9)
  const sh = Math.max(y1 - y0, 1e-9)
  const scale = Math.min((box.w - 2 * pad) / sw, (box.h - 2 * pad) / sh)
  return { scale, cx: (x0 + x1) / 2, cy: (y0 + y1) / 2, box }
}

const toCanvas = (f: Fit, lat: number, lon: number): [number, number] => {
  const [x, y] = merc(lat, lon)
  return [f.box.x + f.box.w / 2 + (x - f.cx) * f.scale, f.box.y + f.box.h / 2 + (y - f.cy) * f.scale]
}

// --- map tiles ------------------------------------------------------------------------

export const TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const tileCache = new Map<string, Promise<HTMLImageElement | null>>()

function loadTile(url: string): Promise<HTMLImageElement | null> {
  let p = tileCache.get(url)
  if (!p) {
    p = new Promise((resolve) => {
      const img = new Image()
      img.crossOrigin = 'anonymous'
      img.onload = () => resolve(img)
      img.onerror = () => resolve(null)
      img.src = url
    })
    tileCache.set(url, p)
  }
  return p
}

type TilePlan = { z: number; size: number; tiles: Array<{ url: string; dx: number; dy: number }> }

/** Which tiles cover the whole canvas for this fit (z chosen so tiles draw at 256–512 px). */
function tilePlan(f: Fit, W: number, H: number): TilePlan {
  const z = Math.max(1, Math.min(18, Math.floor(Math.log2(f.scale / 256))))
  const size = f.scale / 2 ** z
  const n = 2 ** z
  // Canvas (0,0) in world units.
  const wx0 = f.cx - (f.box.x + f.box.w / 2) / f.scale
  const wy0 = f.cy - (f.box.y + f.box.h / 2) / f.scale
  const tx0 = Math.floor(wx0 * n)
  const ty0 = Math.floor(wy0 * n)
  const tx1 = Math.floor((wx0 + W / f.scale) * n)
  const ty1 = Math.floor((wy0 + H / f.scale) * n)
  const tiles: TilePlan['tiles'] = []
  for (let ty = ty0; ty <= ty1; ty++) {
    if (ty < 0 || ty >= n) continue
    for (let tx = tx0; tx <= tx1; tx++) {
      const wrapped = ((tx % n) + n) % n
      tiles.push({
        url: TILE_URL.replace('{z}', String(z)).replace('{x}', String(wrapped)).replace('{y}', String(ty)),
        dx: (tx / n - wx0) * f.scale,
        dy: (ty / n - wy0) * f.scale,
      })
    }
  }
  return { z, size, tiles }
}

// --- layout ---------------------------------------------------------------------------

type Block =
  | { kind: 'title'; text: string }
  | { kind: 'line'; text: string }
  | { kind: 'metrics'; items: Metric[] }
  | { kind: 'splits'; splits: Split[] }
  | { kind: 'route' }

function blocksFor(d: StudioData, o: StudioOptions): Block[] {
  const out: Block[] = []
  if (o.layout === 'minimal') return hasField(d, 'route') && o.fields.some((f) => f.key === 'route' && f.on) ? [{ kind: 'route' }] : []
  for (const f of o.fields) {
    if (!f.on || f.key === 'brand' || !hasField(d, f.key)) continue
    if (f.key === 'route') out.push({ kind: 'route' })
    else if (f.key === 'title') out.push({ kind: 'title', text: d.title })
    else if (f.key === 'date') out.push({ kind: 'line', text: d.date })
    else if (f.key === 'weather') out.push({ kind: 'line', text: d.weather ?? '' })
    else if (f.key === 'splits') out.push({ kind: 'splits', splits: d.splits })
    else {
      const m = metric(d, f.key)
      if (!m) continue
      const last = out[out.length - 1]
      if (last?.kind === 'metrics') last.items.push(m)
      else out.push({ kind: 'metrics', items: [m] })
    }
  }
  return out
}

function metricCols(n: number, wide: boolean): number {
  if (wide) return Math.min(n, n === 5 || n === 6 ? 3 : 4)
  if (n === 4) return 2
  return Math.min(n, 3)
}

function splitRows(n: number, wide: boolean): { cols: number; rows: number } {
  const cols = n <= 6 ? 1 : n <= 14 ? 2 : wide ? 4 : 3
  return { cols, rows: Math.ceil(Math.min(n, 42) / cols) }
}

/** Height of a block at text scale k (canvas px). */
function blockHeight(b: Block, k: number, wide: boolean, o: StudioOptions): number {
  switch (b.kind) {
    case 'title': return 92 * k
    case 'line': return 50 * k
    case 'metrics': {
      const rows = Math.ceil(b.items.length / metricCols(b.items.length, wide))
      return rows * 132 * k + (rows - 1) * 22 * k
    }
    case 'splits':
      if (o.splitsStyle === 'bars') return 230 * k
      return 46 * k + splitRows(b.splits.length, wide).rows * 44 * k
    case 'route': return 0
  }
}

// --- drawing --------------------------------------------------------------------------

function setFont(ctx: CanvasRenderingContext2D, weight: number, px: number) {
  ctx.font = `${weight} ${Math.round(px)}px ${FONT}`
}

function fitFont(ctx: CanvasRenderingContext2D, text: string, weight: number, px: number, maxW: number): number {
  let s = px
  setFont(ctx, weight, s)
  while (s > 14 && ctx.measureText(text).width > maxW) {
    s *= 0.94
    setFont(ctx, weight, s)
  }
  return s
}

function ellipsize(ctx: CanvasRenderingContext2D, text: string, maxW: number): string {
  if (ctx.measureText(text).width <= maxW) return text
  let t = text
  while (t.length > 1 && ctx.measureText(`${t}…`).width > maxW) t = t.slice(0, -1)
  return `${t}…`
}

type Ctx = { ctx: CanvasRenderingContext2D; o: StudioOptions; text: string; k: number; wide: boolean; x: number; w: number; align: CanvasTextAlign }

function drawBlock(c: Ctx, b: Block, y: number) {
  const { ctx, o, text, k, x, w } = c
  const wt = WEIGHTS[o.weight]
  const ax = c.align === 'center' ? x + w / 2 : x
  ctx.textAlign = c.align
  ctx.textBaseline = 'alphabetic'
  ctx.fillStyle = text
  if (b.kind === 'title') {
    const px = fitFont(ctx, b.text, wt.title, 72 * k, w)
    ctx.fillText(ellipsize(ctx, b.text, w), ax, y + 70 * k - (72 * k - px) / 2)
    return
  }
  if (b.kind === 'line') {
    ctx.fillStyle = rgba(text, 0.82)
    setFont(ctx, wt.label, 34 * k)
    ctx.fillText(ellipsize(ctx, b.text, w), ax, y + 38 * k)
    return
  }
  if (b.kind === 'metrics') {
    const cols = metricCols(b.items.length, c.wide)
    const gap = 28 * k
    const cw = (w - gap * (cols - 1)) / cols
    b.items.forEach((m, i) => {
      const r = Math.floor(i / cols)
      const col = i % cols
      // Centre a short last row under the grid.
      const inRow = Math.min(cols, b.items.length - r * cols)
      const rowOffset = c.align === 'center' ? ((cols - inRow) * (cw + gap)) / 2 : 0
      const cx = x + rowOffset + col * (cw + gap)
      const cy = y + r * (132 + 22) * k
      const tx = c.align === 'center' ? cx + cw / 2 : cx
      ctx.textAlign = c.align
      ctx.fillStyle = rgba(text, 0.72)
      setFont(ctx, wt.label, 26 * k)
      ctx.fillText(ellipsize(ctx, m.label.toUpperCase(), cw), tx, cy + 30 * k)
      ctx.fillStyle = text
      const unitW = m.unit ? (setFont(ctx, wt.label, 30 * k), ctx.measureText(` ${m.unit}`).width) : 0
      const vpx = fitFont(ctx, m.value, wt.value, 80 * k, cw - unitW)
      setFont(ctx, wt.value, vpx)
      const vw = ctx.measureText(m.value).width
      const start = c.align === 'center' ? cx + (cw - vw - unitW) / 2 : cx
      ctx.textAlign = 'left'
      ctx.fillText(m.value, start, cy + 112 * k)
      if (m.unit) {
        ctx.fillStyle = rgba(text, 0.72)
        setFont(ctx, wt.label, 30 * k)
        ctx.fillText(` ${m.unit}`, start + vw, cy + 112 * k)
      }
    })
    return
  }
  if (b.kind === 'splits') {
    const s = b.splits.slice(0, 42)
    ctx.fillStyle = rgba(text, 0.72)
    setFont(ctx, wt.label, 26 * k)
    ctx.textAlign = c.align
    ctx.fillText('KM SPLITS', ax, y + 30 * k)
    const fastest = Math.min(...s.map((p) => p.pace_s_per_km))
    const slowest = Math.max(...s.map((p) => p.pace_s_per_km))
    if (o.splitsStyle === 'bars') {
      const top = y + 50 * k
      const hMax = 140 * k
      const gap = Math.max(3, (s.length > 20 ? 4 : 10) * k)
      const bw = (w - gap * (s.length - 1)) / s.length
      s.forEach((p, i) => {
        // Faster km = taller bar; floor of 30 % so slow kms still show.
        const t = slowest > fastest ? (slowest - p.pace_s_per_km) / (slowest - fastest) : 1
        const h = hMax * (0.3 + 0.7 * t)
        const bx = x + i * (bw + gap)
        ctx.fillStyle = p.pace_s_per_km === fastest ? o.routeColor : rgba(text, p.distance_m < 950 ? 0.35 : 0.7)
        roundRect(ctx, bx, top + hMax - h, bw, h, Math.min(8 * k, bw / 2))
        ctx.fill()
        if (s.length <= 15) {
          ctx.fillStyle = rgba(text, 0.72)
          setFont(ctx, wt.label, 22 * k)
          ctx.textAlign = 'center'
          ctx.fillText(p.distance_m < 950 ? `${(p.distance_m / 1000).toFixed(1)}` : String(p.km), bx + bw / 2, top + hMax + 30 * k)
        }
      })
      return
    }
    const { cols, rows } = splitRows(s.length, c.wide)
    const gap = 36 * k
    const cw = (w - gap * (cols - 1)) / cols
    s.forEach((p, i) => {
      const col = Math.floor(i / rows)
      const r = i % rows
      const cx = x + col * (cw + gap)
      const cy = y + 46 * k + r * 44 * k + 34 * k
      ctx.textAlign = 'left'
      ctx.fillStyle = rgba(text, 0.72)
      setFont(ctx, wt.label, 28 * k)
      ctx.fillText(p.distance_m < 950 ? `${(p.distance_m / 1000).toFixed(2)}` : `${p.km}`, cx, cy)
      ctx.textAlign = 'right'
      ctx.fillStyle = p.pace_s_per_km === fastest && s.length > 1 ? o.routeColor : text
      setFont(ctx, wt.value, 30 * k)
      ctx.fillText(fmtPace(p.pace_s_per_km), cx + cw, cy)
    })
  }
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

function drawRoute(ctx: CanvasRenderingContext2D, route: Array<[number, number]>, f: Fit, o: StudioOptions, u: number) {
  ctx.lineJoin = 'round'
  ctx.lineCap = 'round'
  const path = () => {
    ctx.beginPath()
    route.forEach(([la, lo], i) => {
      const [x, y] = toCanvas(f, la, lo)
      if (i) ctx.lineTo(x, y)
      else ctx.moveTo(x, y)
    })
  }
  // A soft dark under-stroke keeps a light line readable over photos.
  if (o.bg === 'transparent' || o.bg === 'photo' || o.bg === 'map') {
    path()
    ctx.strokeStyle = o.bg === 'map' ? 'rgba(255,255,255,0.85)' : 'rgba(0,0,0,0.28)'
    ctx.lineWidth = 20 * u
    ctx.stroke()
  }
  path()
  ctx.strokeStyle = o.routeColor
  ctx.lineWidth = 11 * u
  ctx.stroke()
}

function drawBackground(ctx: CanvasRenderingContext2D, W: number, H: number, o: StudioOptions, photo: Photo | null) {
  if (o.bg === 'solid') {
    ctx.fillStyle = o.solid
    ctx.fillRect(0, 0, W, H)
  } else if (o.bg === 'photo' && photo) {
    ctx.fillStyle = '#000'
    ctx.fillRect(0, 0, W, H)
    const s = o.photoFit === 'cover' ? Math.max(W / photo.w, H / photo.h) : Math.min(W / photo.w, H / photo.h)
    const dw = photo.w * s
    const dh = photo.h * s
    // ox/oy in -1…1 of the free space (overflow for cover, margin for contain).
    const dx = (W - dw) / 2 + (photo.ox * Math.abs(W - dw)) / 2
    const dy = (H - dh) / 2 + (photo.oy * Math.abs(H - dh)) / 2
    ctx.drawImage(photo.img, dx, dy, dw, dh)
    if (o.darken > 0) {
      ctx.fillStyle = `rgba(0,0,0,${o.darken})`
      ctx.fillRect(0, 0, W, H)
    }
  } else if (o.bg === 'map') {
    ctx.fillStyle = '#e9ecef'
    ctx.fillRect(0, 0, W, H)
  }
}

export type RenderResult = { tilesPending: Promise<unknown> | null; tilesFailed: boolean }

/**
 * Draw the card into `canvas` at `scale` (1 = full resolution). Map tiles that are not
 * loaded yet come back as `tilesPending`; redraw when it settles.
 */
export function drawStudio(canvas: HTMLCanvasElement, d: StudioData, o: StudioOptions, scale: number, photo: Photo | null, tileImages?: Map<string, HTMLImageElement | null>): RenderResult {
  const { w: W, h: H } = SIZES[o.size]
  canvas.width = Math.round(W * scale)
  canvas.height = Math.round(H * scale)
  const ctx = canvas.getContext('2d')!
  ctx.setTransform(scale, 0, 0, scale, 0, 0)
  ctx.clearRect(0, 0, W, H)
  const u = Math.min(W, H) / 1080
  const wide = W > H
  const pad = 84 * u
  const text = autoText(o)
  const result: RenderResult = { tilesPending: null, tilesFailed: false }

  drawBackground(ctx, W, H, o, photo)

  const blocks = blocksFor(d, o)
  const gap = 40 * u
  const hasRoute = blocks.some((b) => b.kind === 'route')
  const brand = o.fields.some((f) => f.key === 'brand' && f.on)
  const brandH = brand ? 60 * u : 0
  const innerH = H - 2 * pad - brandH
  // Landscape with stats above/below: route and stats side by side instead.
  const side = wide && hasRoute && (o.layout === 'bottom' || o.layout === 'top')
  const colW = side ? (W - 3 * pad) * 0.56 : W - 2 * pad
  const gridWide = wide && !side
  const minRoute = hasRoute && !side ? innerH * 0.32 : 0
  // Shrink text until everything fits with room left for the route.
  let k = u
  const shown = blocks.filter((b) => b.kind !== 'route')
  const stackH = (kk: number) =>
    shown.reduce((s, b) => s + blockHeight(b, kk, gridWide, o), 0) + Math.max(0, (side ? shown.length : blocks.length) - 1) * gap
  while (k > 0.45 * u && stackH(k) > innerH - minRoute) k *= 0.94

  const contentH = stackH(k)
  const routeH = hasRoute ? Math.max(minRoute, innerH - contentH) : 0
  const align: CanvasTextAlign = o.layout === 'stacked' ? 'center' : 'left'
  // Side by side: "Stats below" = route left, stats right; "Stats above" = stats left.
  const colX = side && o.layout === 'bottom' ? W - pad - colW : pad
  const c: Ctx = { ctx, o, text, k, wide: gridWide, x: colX, w: colW, align }

  // Where everything goes: route first/last for top/bottom; stacked follows the order.
  let order = blocks
  if (o.layout === 'bottom') order = [...blocks.filter((b) => b.kind === 'route'), ...shown]
  if (o.layout === 'top') order = [...shown, ...blocks.filter((b) => b.kind === 'route')]

  const top = pad + (o.layout === 'bottom' && brand ? brandH : 0)
  let y = top
  if (!hasRoute || side) {
    // No route (or route beside the stats): stats sit at the chosen edge, or centred.
    const free = innerH - contentH
    y += side || o.layout === 'stacked' ? free / 2 : o.layout === 'bottom' ? free : 0
  }
  let fit: Fit | null = null
  const positions: Array<{ b: Block; y: number }> = []
  for (const b of order) {
    if (b.kind === 'route') {
      if (side) {
        const rx = o.layout === 'bottom' ? pad : 2 * pad + colW
        fit = fitRoute(d.route!, { x: rx, y: pad, w: W - 3 * pad - colW, h: H - 2 * pad })
        continue
      }
      fit = fitRoute(d.route!, { x: pad, y, w: W - 2 * pad, h: routeH })
      y += routeH + gap
      continue
    }
    positions.push({ b, y })
    y += blockHeight(b, k, gridWide, o) + gap
  }

  // Map tiles behind everything (needs the route's fit to line up).
  if (o.bg === 'map' && fit) {
    const plan = tilePlan(fit, W, H)
    const missing: Array<Promise<unknown>> = []
    for (const t of plan.tiles) {
      const img = tileImages?.get(t.url)
      if (img === undefined) missing.push(loadTile(t.url).then((im) => tileImages?.set(t.url, im)))
      else if (img) ctx.drawImage(img, t.dx, t.dy, plan.size + 0.5, plan.size + 0.5)
      else result.tilesFailed = true
    }
    if (missing.length) result.tilesPending = Promise.all(missing)
    // A light wash behind the text side so stats stay readable.
    if (o.layout !== 'minimal') {
      const g = side
        ? (o.layout === 'top' ? ctx.createLinearGradient(0, 0, W * 0.7, 0) : ctx.createLinearGradient(W, 0, W * 0.3, 0))
        : o.layout === 'top' ? ctx.createLinearGradient(0, 0, 0, H * 0.6) : ctx.createLinearGradient(0, H, 0, H * 0.4)
      g.addColorStop(0, 'rgba(255,255,255,0.88)')
      g.addColorStop(1, 'rgba(255,255,255,0)')
      ctx.fillStyle = g
      ctx.fillRect(0, 0, W, H)
    }
    ctx.fillStyle = 'rgba(16,20,24,0.7)'
    setFont(ctx, 600, 20 * u)
    ctx.textAlign = 'right'
    ctx.fillText('© OpenStreetMap contributors', W - 24 * u, H - 22 * u)
  }

  // Text shadow on photos / transparent so white text holds over bright spots.
  if (o.bg === 'photo' || o.bg === 'transparent') {
    ctx.shadowColor = 'rgba(0,0,0,0.35)'
    ctx.shadowBlur = 12 * u
    ctx.shadowOffsetY = 2 * u
  }
  for (const p of positions) drawBlock(c, p.b, p.y)
  ctx.shadowColor = 'transparent'
  if (fit && d.route) drawRoute(ctx, d.route, fit, o, u)

  if (brand) {
    ctx.fillStyle = rgba(text, 0.9)
    setFont(ctx, 800, 36 * u)
    ctx.textBaseline = 'alphabetic'
    if (o.layout === 'bottom') {
      ctx.textAlign = 'left'
      ctx.fillText('RunCoach', colX, pad + 36 * u)
    } else {
      ctx.textAlign = o.layout === 'top' ? 'left' : 'center'
      ctx.fillText('RunCoach', o.layout === 'top' ? colX : W / 2, H - pad + 10 * u)
    }
  }
  return result
}

/** Full-resolution PNG (alpha kept for the transparent background). */
export async function exportPng(d: StudioData, o: StudioOptions, photo: Photo | null, tiles: Map<string, HTMLImageElement | null>): Promise<Blob> {
  try {
    const fonts = (document as Document & { fonts?: FontFaceSet }).fonts
    await Promise.all([500, 600, 700, 800].map((w) => fonts?.load(`${w} 40px "Plus Jakarta Sans"`)))
  } catch {
    /* fonts are a nicety */
  }
  const canvas = document.createElement('canvas')
  let r = drawStudio(canvas, d, o, 1, photo, tiles)
  if (r.tilesPending) {
    await r.tilesPending
    r = drawStudio(canvas, d, o, 1, photo, tiles)
  }
  return new Promise((resolve, reject) => {
    try {
      canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('Could not make the image.'))), 'image/png')
    } catch {
      reject(new Error('The map tiles blocked the export. Pick another background.'))
    }
  })
}
