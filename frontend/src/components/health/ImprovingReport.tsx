import { dayMonth } from '../../lib/format'
import { errorText } from '../../lib/queries'
import { useImprovingReport, type ImprovingChange, type ImprovingReport as Report, type ImprovingRun } from '../../lib/improving'
import { CardHead } from '../Kit'
import { Empty, ErrorState, Skeleton } from '../States'
import { InfoButton } from './InfoButton'

const ZONES = ['below', 'Z1', 'Z2', 'Z3', 'Z4', 'Z5'] as const
const ZONE_COLOR: Record<string, string> = {
  below: 'var(--walk)', Z1: 'var(--run-soft)', Z2: 'var(--ok)', Z3: 'var(--warn)', Z4: 'var(--fuel)', Z5: 'var(--bad)',
}
const pace = (s: number | null | undefined) => (s == null ? '—' : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`)
const monthName = (m?: string) => (m ? new Date(`${m}-01T00:00:00`).toLocaleDateString('en-GB', { month: 'short' }) : '')

/** What each number means, in plain words, and how its change is shown. */
const TILES: Record<ImprovingChange['key'], { label: string; fmt: (v: number) => string; unit?: string; better: string; worse: string; flat: string; why: string }> = {
  z45_pct: { label: 'Time in zone 4–5 (hard)', fmt: (v) => `${Math.round(v)}%`, better: 'Better', worse: 'Worse', flat: 'No change', why: 'Share of each run spent at a hard effort. Easy-base running keeps this near zero.' },
  run_hr: { label: 'Heart rate while running', fmt: (v) => `${Math.round(v)}`, unit: 'bpm', better: 'Lower', worse: 'Higher', flat: 'No change', why: 'Average heart rate in the running parts only. Walk breaks are left out.' },
  m_per_beat: { label: 'Metres per heartbeat', fmt: (v) => v.toFixed(2), unit: 'm', better: 'Fitter', worse: 'Lower', flat: 'No change yet', why: 'How far one heartbeat carries you while running. This is the number that rises as your aerobic base grows.' },
  run_pace_s: { label: 'Running pace', fmt: (v) => pace(v), unit: '/km', better: 'Faster', worse: 'Slower', flat: 'Same', why: 'Average pace in the running parts. Slower is fine while you build the base.' },
  rhr: { label: 'Resting heart rate', fmt: (v) => v.toFixed(0), unit: 'bpm', better: 'Lower', worse: 'Higher', flat: 'Flat', why: 'Monthly median from your watch. It usually drops a few beats after a couple of months of regular running.' },
  max_hr: { label: 'Highest heart rate per run', fmt: (v) => `${Math.round(v)}`, unit: 'bpm', better: 'Lower', worse: 'Higher', flat: 'No change', why: 'Average of each run’s peak. Lower peaks mean fewer surges into the hard zones.' },
}
/** Pace is shown neutrally: slower on purpose is not "worse" for a base builder. */
const pillClass = (c: ImprovingChange) =>
  c.key === 'run_pace_s' ? 'pill' : c.status === 'better' ? 'pill pill-ok' : c.status === 'worse' ? 'pill pill-bad' : 'pill'

/** Health → Reports → Improving: "Am I improving?" from every outdoor run. */
export function ImprovingReport() {
  const q = useImprovingReport()
  if (q.isPending) return <section className="card"><Skeleton lines={8} /></section>
  if (q.isError) return <ErrorState message={errorText(q.error)} onRetry={() => q.refetch()} />
  const r = q.data
  if (!r.runs.length) return <Empty title="No runs yet">Your progress shows here after your first outdoor runs sync from Garmin.</Empty>
  return <ReportView r={r} />
}

function ReportView({ r }: { r: Report }) {
  const band = r.easy_band
  return (
    <div className="stack">
      <section className="card imp-verdict">
        <span className="muted small">{r.runs.length} outdoor runs · {dayMonth(r.first!)} – {dayMonth(r.last!)}</span>
        <h2>{r.verdict.title}</h2>
        <p>{r.verdict.text}</p>
        {r.gaps.length > 0 && (
          <p className="small">Breaks of 2+ weeks: {r.gaps.map((g) => `${dayMonth(g.from)}${g.to ? `–${dayMonth(g.to)}` : ' – now'} (${g.days} days)`).join(', ')}. Each break undoes some progress.</p>
        )}
      </section>

      {r.status === 'ok' && (
        <section className="stack">
          <CardHead title={`${monthName(r.from_month)} → ${monthName(r.to_month)}`} sub="Your first month with runs against your latest." />
          <div className="imp-tiles">
            {r.changes.filter((c) => c.start != null && c.end != null).map((c) => {
              const t = TILES[c.key]
              return (
                <div className="imp-tile" key={c.key}>
                  <span className="imp-label">{t.label}<InfoButton title={t.label}><p>{t.why}</p></InfoButton></span>
                  <span className="imp-nums">{t.fmt(c.start!)}<span className="imp-arrow">→</span>{t.fmt(c.end!)}{t.unit && <small>{t.unit}</small>}</span>
                  <span className={pillClass(c)}>{t[c.status === 'unknown' ? 'flat' : c.status]}</span>
                </div>
              )
            })}
            <div className="imp-tile">
              <span className="imp-label">Runs per month</span>
              <span className="imp-nums">{r.months.map((m) => m.runs).join(' · ')}</span>
              <p>{r.months.map((m) => monthName(m.month)).join(' · ')}</p>
            </div>
          </div>
        </section>
      )}

      <section className="card stack">
        <CardHead title="Heart rate while running" sub={band ? `Each dot is one run. Shaded: your easy range, ${band[0]}–${band[1]}.` : 'Each dot is one run.'} />
        <div className="imp-chart"><DotChart runs={r.runs} value={(x) => x.run_hr} band={band} color="var(--fuel)" digits={0} label="bpm" /></div>
      </section>

      <section className="card stack">
        <CardHead title="Metres per heartbeat" sub={r.mpb_goal ? `Higher is fitter. Aim for ${r.mpb_goal[0].toFixed(2)}–${r.mpb_goal[1].toFixed(2)} at your easy heart rate.` : 'Higher is fitter.'} />
        <div className="imp-chart"><DotChart runs={r.runs} value={(x) => x.m_per_beat} band={r.mpb_goal ?? null} color="var(--ok)" digits={2} label="m" /></div>
      </section>

      <section className="card stack">
        <CardHead title="Where each run’s time went" sub="Whole run, walks included. Green is zone 2. Less orange and red over time is the improvement." />
        <div className="imp-legend">
          {ZONES.map((z) => {
            const zone = r.zones?.find((x) => x.name === z)
            return <span key={z}><i style={{ background: ZONE_COLOR[z] }} />{z === 'below' ? 'Below Z1' : `${z}${zone ? ` ${zone.low}–${zone.high}` : ''}`}</span>
          })}
        </div>
        <div className="imp-chart"><ZoneBars runs={r.runs} /></div>
      </section>

      <section className="card stack">
        <CardHead title="Every run" sub="Pace, heart rate and metres per heartbeat come from the running parts only." />
        <div className="imp-table">
          <table>
            <thead><tr><th>Date</th><th>Total</th><th>Running</th><th>Pace</th><th>HR</th><th>Max</th><th>m/beat</th><th>Z2</th><th>Z4–5</th></tr></thead>
            <tbody>
              {r.runs.slice().reverse().map((x, i) => (
                <tr key={`${x.date}-${i}`} className={x.short ? 'is-short' : undefined}>
                  <td>{dayMonth(x.date)}</td><td>{Math.round(x.total_min)} min</td><td>{x.run_min.toFixed(1)} min</td>
                  <td>{pace(x.run_pace_s)}</td><td>{x.run_hr ?? '—'}</td><td>{x.max_hr ?? '—'}</td>
                  <td>{x.m_per_beat?.toFixed(2) ?? '—'}</td><td>{x.z2_pct ?? '—'}%</td><td>{x.z45_pct ?? '—'}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted small">
          Grey rows are runs under 10 minutes; they're kept in.
          {r.excluded_indoor > 0 && ` ${r.excluded_indoor} treadmill ${r.excluded_indoor === 1 ? 'run is' : 'runs are'} left out: indoors the watch's pace isn't reliable.`}
        </p>
      </section>

      <section className="card stack">
        <CardHead title="What will show you're improving" />
        <ul className="imp-next small">
          <li><b>Metres per heartbeat</b> climbs{r.mpb_goal ? ` to ${r.mpb_goal[0].toFixed(2)}+` : ''} while heart rate stays in your easy range.</li>
          <li><b>Same heart rate, faster pace</b> in the running parts.</li>
          <li><b>Zone 4–5 time</b> stays under 5% on easy runs.</li>
          <li><b>Longer running blocks</b> without heart rate climbing.</li>
          <li><b>Resting heart rate</b> drifts down a few beats.</li>
        </ul>
      </section>
    </div>
  )
}

/** One dot per run on a real time axis, so breaks show as empty space. */
function DotChart({ runs, value, band, color, digits, label }: {
  runs: ImprovingRun[]; value: (r: ImprovingRun) => number | null; band: [number, number] | null
  color: string; digits: number; label: string
}) {
  const pts = runs.map((r) => ({ r, v: value(r) })).filter((p): p is { r: ImprovingRun; v: number } => p.v != null)
  if (!pts.length) return null
  const W = 360, H = 170, L = 34, R = 10, T = 10, B = 22
  const vals = pts.map((p) => p.v).concat(band ?? [])
  const pad = digits ? 0.03 : 4
  const lo = Math.min(...vals) - pad, hi = Math.max(...vals) + pad
  const t0 = Date.parse(runs[0].date), t1 = Math.max(Date.parse(runs[runs.length - 1].date), t0 + 86_400_000)
  const x = (d: string) => L + ((Date.parse(d) - t0) / (t1 - t0)) * (W - L - R)
  const y = (v: number) => T + ((hi - v) / (hi - lo)) * (H - T - B)
  const ticks = [lo + pad, (lo + hi) / 2, hi - pad]
  // Month starts as plain strings: Date.parse('YYYY-MM-DD') is UTC, the same as the run dates.
  const months: string[] = []
  for (let [yy, mm] = runs[0].date.slice(0, 7).split('-').map(Number); Date.parse(`${yy}-${String(mm).padStart(2, '0')}-01`) <= t1; mm === 12 ? (yy++, mm = 1) : mm++) {
    months.push(`${yy}-${String(mm).padStart(2, '0')}-01`)
  }
  const last = pts[pts.length - 1]
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${label} per run`}>
      {band && <rect x={L} width={W - L - R} y={y(band[1])} height={Math.max(1, y(band[0]) - y(band[1]))} fill="var(--ok)" fillOpacity={0.15} />}
      {ticks.map((v, i) => (
        <g key={i}><line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke="var(--line)" /><text x={L - 4} y={y(v) + 3} textAnchor="end">{v.toFixed(digits)}</text></g>
      ))}
      {months.map((m) => Date.parse(m) >= t0 - 31 * 86_400_000 && (
        <g key={m}>
          {Date.parse(m) >= t0 && <line x1={x(m)} x2={x(m)} y1={T} y2={H - B} stroke="var(--line)" strokeDasharray="2 3" />}
          <text x={Math.max(L, x(m)) + 3} y={H - 6}>{monthName(m.slice(0, 7))}</text>
        </g>
      ))}
      {pts.map(({ r, v }, i) => (
        <circle key={i} cx={x(r.date)} cy={y(v)} r={i === pts.length - 1 ? 5 : 3.5} fill={r.short ? 'var(--muted)' : color}
          fillOpacity={r.short ? 0.5 : 1} stroke="var(--card)" strokeWidth={1.2}>
          <title>{`${dayMonth(r.date)}: ${v.toFixed(digits)} ${label}`}</title>
        </circle>
      ))}
      <text x={x(last.r.date) - 7} y={y(last.v) - 8} textAnchor="end" style={{ fill: 'var(--fg)', fontWeight: 600 }}>{last.v.toFixed(digits)}</text>
    </svg>
  )
}

function ZoneBars({ runs }: { runs: ImprovingRun[] }) {
  const W = 360, H = 170, L = 30, R = 6, T = 6, B = 30
  const bw = (W - L - R) / Math.max(runs.length, 1)
  const y = (v: number) => T + ((100 - v) / 100) * (H - T - B)
  const every = Math.ceil(runs.length / 8)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Share of each run in each heart-rate zone">
      {[0, 50, 100].map((v) => <g key={v}><line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke="var(--line)" /><text x={L - 4} y={y(v) + 3} textAnchor="end">{v}%</text></g>)}
      {runs.map((r, i) => {
        const total = ZONES.reduce((a, z) => a + (r.zones_pct[z] ?? 0), 0) || 1
        let acc = 0
        return (
          <g key={i}>
            {ZONES.map((z) => {
              const v = ((r.zones_pct[z] ?? 0) / total) * 100
              if (v <= 0) return null
              const rect = <rect key={z} x={L + i * bw + 1.5} width={Math.max(1, bw - 3)} y={y(acc + v)} height={y(acc) - y(acc + v)} fill={ZONE_COLOR[z]}><title>{`${dayMonth(r.date)} · ${z}: ${r.zones_pct[z]}%`}</title></rect>
              acc += v
              return rect
            })}
            {i % every === 0 && <text x={L + i * bw + bw / 2} y={H - 12} textAnchor="middle">{dayMonth(r.date)}</text>}
          </g>
        )
      })}
    </svg>
  )
}
