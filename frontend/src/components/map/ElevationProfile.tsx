import { useLayoutEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import type { RoutePoint } from '../../lib/types'

/** Elevation over distance; scrubbing it moves the dot on the map (and vice versa). */
export function ElevationProfile({
  points, selected, onSelect, gain: serverGain = null,
}: { points: RoutePoint[]; selected: number | null; onSelect: (i: number | null) => void; gain?: number | null }) {
  const wrap = useRef<HTMLDivElement>(null)
  const svg = useRef<SVGSVGElement>(null)
  const [width, setWidth] = useState(340)
  const down = useRef(false)
  useLayoutEffect(() => {
    const el = wrap.current
    if (!el) return
    setWidth(el.clientWidth || 340)
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(([e]) => setWidth(Math.round(e.contentRect.width) || 340))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const withElev = points.map((p, i) => ({ i, d: p.dist_m, e: p.ele_m })).filter((p): p is { i: number; d: number; e: number } => p.e != null)
  if (withElev.length < 2) return null

  const H = 96
  const top = 10
  const bottom = 18
  const left = 4
  const right = 34
  const plotW = Math.max(100, width - left - right)
  const d0 = points[0].dist_m
  const d1 = points[points.length - 1].dist_m || d0 + 1
  const elev = withElev.map((p) => p.e)
  let lo = Math.min(...elev)
  let hi = Math.max(...elev)
  if (hi - lo < 10) { const mid = (hi + lo) / 2; lo = mid - 5; hi = mid + 5 }
  const x = (d: number) => left + ((d - d0) / (d1 - d0 || 1)) * plotW
  const y = (e: number) => top + (1 - (e - lo) / (hi - lo)) * (H - top - bottom)
  const line = withElev.map((p, k) => `${k ? 'L' : 'M'}${x(p.d).toFixed(1)},${y(p.e).toFixed(1)}`).join('')
  const area = `${line}L${x(withElev[withElev.length - 1].d).toFixed(1)},${H - bottom}L${x(withElev[0].d).toFixed(1)},${H - bottom}Z`
  // The server's gain is from the full track; the simplified points under-/over-count.
  const gain = serverGain ?? withElev.slice(1).reduce((s, p, k) => s + Math.max(0, p.e - withElev[k].e), 0)

  const pick = (clientX: number) => {
    const r = svg.current?.getBoundingClientRect()
    if (!r) return
    const d = d0 + (((clientX - r.left) / r.width) * width - left) / plotW * (d1 - d0)
    let best = 0
    let bestD = Infinity
    points.forEach((p, i) => { const dd = Math.abs(p.dist_m - d); if (dd < bestD) { bestD = dd; best = i } })
    onSelect(best)
  }
  const onDown = (e: PointerEvent<SVGSVGElement>) => { down.current = true; pick(e.clientX) }
  const onMove = (e: PointerEvent<SVGSVGElement>) => { if (down.current || e.pointerType === 'mouse') pick(e.clientX) }
  const onKey = (e: KeyboardEvent<SVGSVGElement>) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
    e.preventDefault()
    const stepN = Math.max(1, Math.round(points.length / 40))
    const cur = selected ?? 0
    onSelect(Math.max(0, Math.min(points.length - 1, cur + (e.key === 'ArrowRight' ? stepN : -stepN))))
  }
  const sel = selected != null ? points[selected] : null
  const selElev = sel?.ele_m ?? null
  const kmTicks: number[] = []
  const stepKm = (d1 - d0) / 1000 > 12 ? 5 : (d1 - d0) / 1000 > 5 ? 2 : 1
  for (let k = Math.ceil(d0 / 1000 / stepKm) * stepKm; k * 1000 <= d1; k += stepKm) kmTicks.push(k)

  return (
    <div className="elev" ref={wrap}>
      <div className="elev-head">
        <span className="lbl">Elevation</span>
        <span className="lbl">+{Math.round(gain)} m · {Math.round(lo)}–{Math.round(hi)} m</span>
      </div>
      <svg
        ref={svg}
        width={width}
        height={H}
        viewBox={`0 0 ${width} ${H}`}
        role="slider"
        aria-label="Elevation profile — move along the route"
        aria-valuemin={0}
        aria-valuemax={Math.round(d1 / 10) / 100}
        aria-valuenow={sel ? Math.round(sel.dist_m / 10) / 100 : 0}
        aria-valuetext={sel ? `${(sel.dist_m / 1000).toFixed(2)} km${selElev != null ? `, ${Math.round(selElev)} m` : ''}` : 'start'}
        tabIndex={0}
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={() => { down.current = false }}
        onPointerCancel={() => { down.current = false }}
        onKeyDown={onKey}
      >
        <path d={area} className="elev-area" />
        <path d={line} className="elev-line" fill="none" />
        <text x={width - right + 4} y={y(hi) + 4} className="tl-tick">{Math.round(hi)}</text>
        <text x={width - right + 4} y={y(lo) + 2} className="tl-tick">{Math.round(lo)}</text>
        {kmTicks.map((k) => <text key={k} x={Math.min(Math.max(x(k * 1000), 8), width - right - 8)} y={H - 4} textAnchor="middle" className="tl-tick">{k} km</text>)}
        {sel && (
          <>
            <line x1={x(sel.dist_m)} x2={x(sel.dist_m)} y1={top - 4} y2={H - bottom} className="tl-cursor" />
            {selElev != null && <circle cx={x(sel.dist_m)} cy={y(selElev)} r={5} fill="var(--card)" stroke="var(--fg)" strokeWidth={2.5} />}
          </>
        )}
      </svg>
    </div>
  )
}
