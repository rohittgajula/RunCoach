import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'

/**
 * R11 Day: synchronised lanes (HR / stress / body battery / steps) on one clock axis,
 * with run / sleep / habit markers and ONE scrubber that reads every lane at that time.
 * Custom SVG (not recharts) so the lanes share a single cursor and stay light.
 */

export type LanePoint = [minute: number, value: number | null]
export type Lane = {
  key: string
  label: string
  unit?: string
  /** CSS colour, e.g. var(--recovery). */
  color: string
  kind: 'line' | 'bars'
  points: LanePoint[]
  /** Fixed scale (0–100 for stress / body battery); else min/max of the data. */
  domain?: [number, number]
  format?: (v: number) => string
  /** Minutes each sample covers (bars width, and how far the scrubber looks). */
  step?: number
  /** Join samples up to this many minutes apart (default 3× the usual step, min 20). */
  maxGap?: number
  /** Optional coloured bands behind the line (stress levels). */
  bands?: Array<{ from: number; to: number; color: string }>
}
export type Marker = {
  kind: 'run' | 'sleep' | 'nap' | 'habit'
  start: number
  end?: number | null
  label: string
}

const LANE_H = 58
const LANE_GAP = 10
const TOP = 22
const AXIS_H = 20
const DAY = 24 * 60

function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null)
  const [w, setW] = useState(340)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    setW(el.clientWidth || 340)
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(([entry]) => setW(Math.round(entry.contentRect.width) || 340))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, w]
}

export const clockOf = (minute: number, short = false) => {
  const m = ((Math.round(minute) % DAY) + DAY) % DAY
  const h = Math.floor(m / 60)
  const mm = m % 60
  const d = new Date(2000, 0, 1, h, mm)
  return d.toLocaleTimeString(undefined, { hour: 'numeric', minute: short && mm === 0 ? undefined : '2-digit' })
}

/** Nearest sample within `reach` minutes of `minute`. */
export function valueAt(points: LanePoint[], minute: number, reach: number): number | null {
  let best: LanePoint | null = null
  let bestD = Infinity
  // Points are sorted; binary search for the insertion point, look either side.
  let lo = 0
  let hi = points.length - 1
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    if (points[mid][0] < minute) lo = mid + 1
    else hi = mid
  }
  for (const i of [lo - 1, lo, lo + 1]) {
    const p = points[i]
    if (!p || p[1] == null) continue
    const d = Math.abs(p[0] - minute)
    if (d < bestD) { best = p; bestD = d }
  }
  return best && bestD <= reach ? best[1] : null
}

/** Median gap between samples; a gap > 3× that (min 20 min) breaks the line. */
function typicalStep(points: LanePoint[]): number {
  if (points.length < 3) return 15
  const gaps = points.slice(1).map((p, i) => p[0] - points[i][0]).filter((g) => g > 0).sort((a, b) => a - b)
  return gaps[Math.floor(gaps.length / 2)] ?? 15
}

function linePath(points: LanePoint[], x: (m: number) => number, y: (v: number) => number, breakAfter: number): string {
  let d = ''
  let prev: number | null = null
  for (const [m, v] of points) {
    if (v == null) { prev = null; continue }
    const cmd = prev == null || m - prev > breakAfter ? 'M' : 'L'
    d += `${cmd}${x(m).toFixed(1)},${y(v).toFixed(1)}`
    prev = m
  }
  return d
}

export function DayTimeline({
  lanes, markers, start = 0, end = DAY, nowMinute, label,
}: {
  lanes: Lane[]
  markers: Marker[]
  start?: number
  end?: number
  /** Today: where "now" is (data stops there). */
  nowMinute?: number | null
  label: string
}) {
  const [wrap, width] = useWidth<HTMLDivElement>()
  const [cursor, setCursor] = useState<number | null>(null)
  const dragging = useRef(false)
  const svgRef = useRef<SVGSVGElement>(null)
  const padL = 4
  const padR = 4
  const plotW = Math.max(100, width - padL - padR)
  const span = Math.max(60, end - start)
  const x = useCallback((m: number) => padL + ((m - start) / span) * plotW, [plotW, span, start])
  const height = TOP + lanes.length * (LANE_H + LANE_GAP) + AXIS_H

  const scales = useMemo(() => lanes.map((lane) => {
    const vals = lane.points.map((p) => p[1]).filter((v): v is number => v != null)
    let [lo, hi] = lane.domain ?? [Math.min(...vals), Math.max(...vals)]
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) { lo = 0; hi = 1 }
    if (lane.kind === 'bars') lo = 0
    if (hi - lo < 1e-6) { hi = lo + 1 }
    if (!lane.domain && lane.kind === 'line') { const pad = (hi - lo) * 0.1; lo -= pad; hi += pad }
    return { lo, hi, step: lane.step ?? typicalStep(lane.points) }
  }), [lanes])

  const laneTop = (i: number) => TOP + i * (LANE_H + LANE_GAP)

  const toMinute = (clientX: number) => {
    const r = svgRef.current?.getBoundingClientRect()
    if (!r) return null
    const px = ((clientX - r.left) / r.width) * width
    return Math.max(start, Math.min(end, start + ((px - padL) / plotW) * span))
  }
  const onDown = (e: PointerEvent<SVGSVGElement>) => {
    dragging.current = true
    setCursor(toMinute(e.clientX))
  }
  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    // Mouse hover scrubs too; touch only while the finger is down.
    if (dragging.current || e.pointerType === 'mouse') setCursor(toMinute(e.clientX))
  }
  const onUp = () => { dragging.current = false }
  const onKey = (e: KeyboardEvent<SVGSVGElement>) => {
    const stepMin = e.shiftKey ? 60 : 15
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault()
      setCursor((c) => {
        const base = c ?? (nowMinute ?? 12 * 60)
        return Math.max(start, Math.min(end, base + (e.key === 'ArrowRight' ? stepMin : -stepMin)))
      })
    } else if (e.key === 'Escape') setCursor(null)
  }
  useEffect(() => {
    const up = () => { dragging.current = false }
    window.addEventListener('pointerup', up)
    return () => window.removeEventListener('pointerup', up)
  }, [])

  const ticks: number[] = []
  const tickEvery = span > 16 * 60 ? 360 : 180
  for (let t = Math.ceil(start / tickEvery) * tickEvery; t <= end; t += tickEvery) ticks.push(t)

  const active = cursor != null ? markers.filter((m) => m.end != null ? cursor >= m.start && cursor <= m.end : Math.abs(m.start - cursor) <= 10) : []
  const readings = cursor != null ? lanes.map((lane, i) => {
    const s = scales[i]
    const v = lane.kind === 'bars'
      ? valueAt(lane.points, Math.floor(cursor / s.step) * s.step, s.step)
      : valueAt(lane.points, cursor, Math.max(s.step * 1.5, 10))
    return { lane, v }
  }) : []

  // The tip sits beside the cursor, on the side with more room, so the line stays visible.
  const cx = cursor != null ? x(cursor) : 0
  const tipStyle = cx < width / 2 ? { left: Math.min(cx + 12, width - 150) } : { right: Math.min(width - cx + 12, width - 150) }

  return (
    <div className="day-timeline" ref={wrap}>
      <svg
        ref={svgRef}
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="application"
        aria-label={`${label}. Use left and right arrow keys to move through the day.`}
        tabIndex={0}
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerLeave={(e) => { if (e.pointerType === 'mouse') setCursor(null) }}
        onKeyDown={onKey}
        onBlur={() => setCursor(null)}
      >
        {/* sleep / run bands behind every lane */}
        {markers.filter((m) => m.end != null && m.kind !== 'habit').map((m, i) => (
          <rect
            key={`band-${i}`}
            x={x(Math.max(start, m.start))}
            y={TOP - 6}
            width={Math.max(2, x(Math.min(end, m.end!)) - x(Math.max(start, m.start)))}
            height={height - TOP - AXIS_H + 6}
            className={`tl-band is-${m.kind}`}
          />
        ))}
        {/* marker glyphs on the top rail */}
        {markers.map((m, i) => {
          if (m.kind === 'habit') return <circle key={`mk-${i}`} cx={x(m.start)} cy={8} r={4} className="tl-dot is-habit" />
          const x0 = x(Math.max(start, m.start))
          const x1 = x(Math.min(end, m.end ?? m.start))
          return <rect key={`mk-${i}`} x={x0} y={4} rx={3} width={Math.max(4, x1 - x0)} height={8} className={`tl-rail is-${m.kind}`} />
        })}
        {lanes.map((lane, i) => {
          const s = scales[i]
          const top = laneTop(i)
          const y = (v: number) => top + LANE_H - ((v - s.lo) / (s.hi - s.lo)) * (LANE_H - 4)
          const has = lane.points.some((p) => p[1] != null)
          return (
            <g key={lane.key}>
              <line x1={padL} x2={padL + plotW} y1={top + LANE_H} y2={top + LANE_H} className="tl-base" />
              {lane.bands?.map((b, j) => (
                <rect key={j} x={padL} width={plotW} y={y(Math.min(b.to, s.hi))} height={Math.max(0, y(Math.max(b.from, s.lo)) - y(Math.min(b.to, s.hi)))} fill={b.color} opacity={0.08} />
              ))}
              <text x={padL + 2} y={top + 9} className="tl-label">{lane.label}{lane.unit ? ` · ${lane.unit}` : ''}</text>
              {!has && <text x={padL + plotW / 2} y={top + LANE_H / 2 + 6} textAnchor="middle" className="tl-none">no data</text>}
              {lane.kind === 'line' && has && (
                <path d={linePath(lane.points, x, y, lane.maxGap ?? Math.max(20, s.step * 3))} fill="none" stroke={lane.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
              )}
              {lane.kind === 'bars' && lane.points.map(([m, v]) => v != null && v > 0 ? (
                <rect key={m} x={x(m) + 0.5} width={Math.max(1, x(m + s.step) - x(m) - 1)} y={y(v)} height={top + LANE_H - y(v)} rx={1.5} fill={lane.color} />
              ) : null)}
              {cursor != null && (() => {
                const v = readings[i]?.v
                return v != null && lane.kind === 'line' ? <circle cx={x(cursor)} cy={y(v)} r={4} fill="var(--card)" stroke={lane.color} strokeWidth={2.5} /> : null
              })()}
            </g>
          )
        })}
        {nowMinute != null && nowMinute > start && nowMinute < end && (
          <line x1={x(nowMinute)} x2={x(nowMinute)} y1={TOP - 4} y2={height - AXIS_H} className="tl-now" />
        )}
        {ticks.map((t) => (
          <text key={t} x={Math.min(Math.max(x(t), 14), width - 14)} y={height - 5} textAnchor="middle" className="tl-tick">{clockOf(t, true)}</text>
        ))}
        {cursor != null && <line x1={x(cursor)} x2={x(cursor)} y1={TOP - 6} y2={height - AXIS_H} className="tl-cursor" />}
      </svg>
      {cursor != null && (
        <div
          className="chart-tip tl-tip"
          style={tipStyle}
          role="status"
          aria-live="polite"
        >
          <p className="chart-tip-title">{clockOf(cursor)}</p>
          {readings.map(({ lane, v }) => (
            <p key={lane.key} className="chart-tip-line">
              <i style={{ background: lane.color }} />
              {lane.label} {v == null ? '—' : (lane.format ?? ((n: number) => String(Math.round(n))))(v)}
            </p>
          ))}
          {active.map((m, i) => <p key={i} className="chart-tip-line tl-tip-mark">{m.label}</p>)}
        </div>
      )}
    </div>
  )
}
