import { useEffect, useLayoutEffect, useMemo, useRef, useState, type PointerEvent } from 'react'
import { addDays } from '../../lib/format'
import { bucket, bucketStart, tickFor, ticksFor, tipFor, type Freq } from '../health/healthRange'

type Pt = { date: string; value: number }

const PER: Record<Freq, string> = { day: '/day', week: '/week', month: '/month' }
const Y_GUTTER = 30 // right-hand y labels live outside the bars
const X_AXIS = 20
const TOP = 34 // room for the tooltip above the bars
const fmt1 = (v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(1))

function nextBucket(iso: string, freq: Freq) {
  if (freq === 'day') return addDays(iso, 1)
  if (freq === 'week') return addDays(iso, 7)
  const [y, m] = iso.split('-').map(Number)
  return m === 12 ? `${y + 1}-01-01` : `${y}-${String(m + 1).padStart(2, '0')}-01`
}

/**
 * Every bucket of the range, in order, summed — days with nothing logged are real
 * zeros, so bars sit at their true dates and the average means "per day in this range".
 */
export function habitBuckets(data: Pt[], freq: Freq, start?: string, end?: string): Pt[] {
  const summed = new Map<string, number>()
  for (const p of bucket(data.map((d) => ({ date: d.date.slice(0, 10), value: d.value })), freq, 'sum')) {
    const key = bucketStart(p.date, freq)
    summed.set(key, (summed.get(key) ?? 0) + (p.value ?? 0))
  }
  const keys = [...summed.keys()].sort()
  const from = bucketStart(start ?? keys[0] ?? '', freq)
  const to = bucketStart(end ?? keys[keys.length - 1] ?? '', freq)
  if (!from || !to || from > to) return keys.map((date) => ({ date, value: summed.get(date) ?? 0 }))
  const out: Pt[] = []
  for (let d = from; d <= to && out.length < 400; d = nextBucket(d, freq)) out.push({ date: d, value: summed.get(d) ?? 0 })
  return out
}

/** One average for a habit chart and anything that quotes it: total ÷ buckets in range. */
export const habitAverage = (pts: Pt[]) => (pts.length ? pts.reduce((a, p) => a + p.value, 0) / pts.length : null)

function niceMax(v: number) {
  if (v <= 2) return 2
  if (v <= 4) return 4
  const step = 10 ** Math.floor(Math.log10(v))
  const n = v / step
  return (n <= 2 ? 2 : n <= 5 ? 5 : 10) * step
}

/**
 * Small count chart (per day / week / month). Plain SVG rather than Recharts: the bar
 * under the finger is the one the tooltip names (nearest-bar snapping), the y labels
 * sit in their own gutter, bars keep a readable width with gaps, zero days are a faint
 * baseline tick, and the average lives in the key row above — never on an axis label.
 */
export function HabitBarChart({
  data, color, unit, height = 150, freq = 'day', start, end,
}: { data: Pt[]; color: string; unit: string; height?: number; freq?: Freq; start?: string; end?: string }) {
  const pts = useMemo(() => habitBuckets(data, freq, start, end), [data, freq, start, end])
  const avg = habitAverage(pts)
  const box = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)
  const [active, setActive] = useState<number | null>(null)
  const frame = useRef(0)

  useLayoutEffect(() => {
    const el = box.current
    if (!el) return
    setWidth(el.clientWidth)
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(([e]) => setWidth(Math.round(e.contentRect.width)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  useEffect(() => () => cancelAnimationFrame(frame.current), [])

  const n = pts.length
  const plotW = Math.max(0, width - Y_GUTTER)
  const plotH = Math.max(0, height - X_AXIS - TOP)
  const band = n ? plotW / n : 0
  const barW = band >= 6 ? Math.min(18, Math.max(4, band * 0.62)) : Math.max(1.5, band - 1)
  const max = niceMax(Math.max(1, ...pts.map((p) => p.value)))
  const y = (v: number) => TOP + plotH - (v / max) * plotH
  const cx = (i: number) => band * i + band / 2

  const tick = tickFor(freq)
  const tickDates = useMemo(() => new Set(ticksFor(pts.map((p) => p.date), freq)), [pts, freq])
  // Drop labels that would collide (about 40 px each on a phone).
  const labels: Array<{ i: number; text: string }> = []
  let lastX = -Infinity
  pts.forEach((p, i) => {
    if (!tickDates.has(p.date)) return
    const x = cx(i)
    if (x - lastX < 42) return
    labels.push({ i, text: tick(p.date) })
    lastX = x
  })

  const pick = (event: PointerEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    const x = event.clientX - rect.left
    cancelAnimationFrame(frame.current)
    frame.current = requestAnimationFrame(() => {
      if (!band) return
      setActive(Math.min(n - 1, Math.max(0, Math.floor(x / band))))
    })
  }
  const leave = () => {
    cancelAnimationFrame(frame.current)
    setActive(null)
  }

  const a = active != null ? pts[active] : null
  const tipLeft = active != null ? Math.min(Math.max(cx(active), 60), Math.max(60, plotW - 60)) : 0
  const radius = Math.min(4, barW / 2)

  return (
    <div className="metric-chart habit-chart">
      {avg != null && n >= 3 && avg > 0 && (
        <div className="chart-key">
          <span><i className="key-avg" />avg {fmt1(Math.round(avg * 10) / 10)}{PER[freq]}</span>
        </div>
      )}
      <div
        ref={box}
        className="chart hbar"
        style={{ height }}
        onPointerMove={pick}
        onPointerDown={pick}
        onPointerLeave={leave}
        onPointerCancel={leave}
        role="img"
        aria-label={`${unit} per ${freq}: ${pts.map((p) => `${tick(p.date)} ${fmt1(p.value)}`).join(', ')}`}
      >
        {width > 0 && (
          <svg width={width} height={height} aria-hidden="true">
            {[0, max / 2, max].map((v) => (
              <g key={v}>
                <line x1={0} x2={plotW} y1={y(v)} y2={y(v)} className={v === 0 ? 'hbar-base' : 'hbar-grid'} />
                <text x={width - 2} y={y(v)} dy="0.32em" textAnchor="end" className="hbar-label">{fmt1(v)}</text>
              </g>
            ))}
            {avg != null && avg > 0 && n >= 3 && (
              <line x1={0} x2={plotW} y1={y(avg)} y2={y(avg)} className="hbar-avg" />
            )}
            {pts.map((p, i) => {
              const x = cx(i) - barW / 2
              const on = active === i
              if (p.value <= 0) {
                return <rect key={p.date} x={x} y={y(0) - 2} width={barW} height={2} rx={1} className={`hbar-zero ${on ? 'is-on' : ''}`} />
              }
              const top = y(p.value)
              const h = Math.max(2, y(0) - top)
              const r = Math.min(radius, h)
              return (
                <path
                  key={p.date}
                  d={`M${x},${y(0)} V${y(0) - h + r} Q${x},${y(0) - h} ${x + r},${y(0) - h} H${x + barW - r} Q${x + barW},${y(0) - h} ${x + barW},${y(0) - h + r} V${y(0)} Z`}
                  fill={color}
                  className={`hbar-bar ${active == null ? '' : on ? 'is-on' : 'is-off'}`}
                />
              )
            })}
            {labels.map(({ i, text }) => {
              const x = cx(i)
              const anchor = x < 24 ? 'start' : x > plotW - 24 ? 'end' : 'middle'
              return <text key={i} x={anchor === 'start' ? Math.max(0, x - barW / 2) : anchor === 'end' ? Math.min(plotW, x + barW / 2) : x} y={height - 4} textAnchor={anchor} className="hbar-label">{text}</text>
            })}
          </svg>
        )}
        {a && (
          <div className="chart-tip hbar-tip" style={{ transform: `translateX(calc(${tipLeft}px - 50%))` }}>
            <p className="chart-tip-title">{tipFor(freq)(a.date)}</p>
            <p className="chart-tip-line"><i style={{ background: color }} />{fmt1(a.value)} {a.value === 1 ? unit.replace(/s$/, '') : unit}</p>
          </div>
        )}
      </div>
    </div>
  )
}
