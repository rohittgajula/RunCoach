import type { QualityFlag } from '../../lib/r17'

export type HrPoint = { t: number; raw: number | null; clean: number | null }

const W = 320
const H = 120
const PAD = { l: 28, r: 6, t: 8, b: 18 }

const mm = (s: number) => `${Math.round(s / 60)}′`

/**
 * R17 §2: heart rate over the run — the cleaned line in run colour, the raw reading
 * dashed grey, and every fixed / masked stretch shaded grey.
 */
export function HrMaskChart({ points, flags, label = 'Heart rate with fixed parts greyed' }: { points: HrPoint[]; flags: QualityFlag[]; label?: string }) {
  const pts = points.filter((p) => Number.isFinite(p.t))
  if (pts.length < 2) return <p className="muted small">No heart-rate trace to show for this run.</p>
  const t0 = pts[0].t
  const t1 = pts[pts.length - 1].t || t0 + 1
  const vals = pts.flatMap((p) => [p.raw, p.clean]).filter((v): v is number => v != null && Number.isFinite(v))
  const lo = Math.floor((Math.min(...vals) - 5) / 10) * 10
  const hi = Math.ceil((Math.max(...vals) + 5) / 10) * 10
  const x = (t: number) => PAD.l + ((t - t0) / Math.max(1, t1 - t0)) * (W - PAD.l - PAD.r)
  const y = (v: number) => PAD.t + (1 - (v - lo) / Math.max(1, hi - lo)) * (H - PAD.t - PAD.b)
  const line = (key: 'raw' | 'clean') => {
    let d = ''
    let pen = false
    for (const p of pts) {
      const v = p[key]
      if (v == null) { pen = false; continue }
      d += `${pen ? 'L' : 'M'}${x(p.t).toFixed(1)},${y(v).toFixed(1)}`
      pen = true
    }
    return d
  }
  const mid = Math.round((lo + hi) / 2)
  return (
    <figure style={{ margin: 0 }}>
      <svg className="dq-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label}>
        {flags.map((f, i) => {
          const a = Math.max(t0, f.start_s)
          const b = Math.min(t1, Math.max(f.end_s, f.start_s + 1))
          if (b <= a) return null
          return <rect key={i} className="dq-mask" x={x(a)} y={PAD.t} width={Math.max(2, x(b) - x(a))} height={H - PAD.t - PAD.b} rx={2} />
        })}
        {[lo, mid, hi].map((v) => (
          <g key={v}>
            <line className="dq-base" x1={PAD.l} x2={W - PAD.r} y1={y(v)} y2={y(v)} />
            <text x={PAD.l - 4} y={y(v) + 3} textAnchor="end">{v}</text>
          </g>
        ))}
        <path className="dq-raw" d={line('raw')} />
        <path className="dq-clean" d={line('clean')} />
        <text x={PAD.l} y={H - 4}>{mm(0)}</text>
        <text x={W - PAD.r} y={H - 4} textAnchor="end">{mm(t1 - t0)}</text>
      </svg>
      <figcaption className="dq-legend">
        <span><i style={{ background: 'var(--run)' }} />Cleaned</span>
        <span><i style={{ background: 'var(--faint)' }} />Raw reading</span>
        <span><i style={{ background: 'color-mix(in srgb, var(--faint) 28%, transparent)' }} />Fixed / ignored</span>
      </figcaption>
    </figure>
  )
}

/** A small sparkline for review items (daily values or a run trace), flagged points grey. */
export function MiniSeries({ series, baseline }: { series: Array<{ v: number | null; flagged?: boolean }>; baseline?: number | null }) {
  const vals = series.map((s) => s.v).filter((v): v is number => v != null)
  if (vals.length < 2) return null
  const all = baseline != null ? [...vals, baseline] : vals
  const lo = Math.min(...all)
  const hi = Math.max(...all)
  const w = 240
  const h = 48
  const x = (i: number) => 4 + (i / (series.length - 1)) * (w - 8)
  const y = (v: number) => 4 + (1 - (v - lo) / Math.max(1, hi - lo)) * (h - 8)
  let d = ''
  series.forEach((s, i) => { if (s.v != null) d += `${d ? 'L' : 'M'}${x(i).toFixed(1)},${y(s.v).toFixed(1)}` })
  return (
    <svg className="dq-chart" viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Values around this item, flagged ones shaded" style={{ maxWidth: 320 }}>
      {series.map((s, i) => s.flagged ? <rect key={i} className="dq-mask" x={x(i) - (w / series.length) / 2} y={0} width={w / series.length} height={h} /> : null)}
      {baseline != null && <line className="dq-base" x1={0} x2={w} y1={y(baseline)} y2={y(baseline)} />}
      <path className="dq-clean" d={d} />
    </svg>
  )
}
