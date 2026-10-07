import { dayMonth } from '../../lib/format'
import { useHealthForm, useRecords } from '../../lib/queries'
import type { FormMetric, HealthForm } from '../../lib/types'
import { CardHead, MetricTile, Pill, ToneChip } from '../Kit'
import { InfoButton } from '../health/InfoButton'
import { GLOSSARY, type GlossaryKey } from '../health/glossary'
import { Sparkline } from '../Sparkline'

/** Personal records: Garmin's and our own bests, "New" for the last 14 days. */
export function RecordsCard() {
  const records = useRecords()
  const list = records.data?.records ?? []
  if (!list.length) return null
  const garmin = list.filter((r) => r.source === 'garmin')
  const ours = list.filter((r) => r.source === 'computed')
  const block = (title: string, rows: typeof list) =>
    rows.length > 0 && (
      <div>
        <span className="lbl">{title}</span>
        <ul className="bests">
          {rows.map((r) => (
            <li key={r.key} className="best">
              <span className="grow">{r.label}{r.is_new && <> <Pill topic="run" solid>New</Pill></>}</span>
              <span className="best-value">{r.display}</span>
              <span className="muted small best-date">{r.date ? dayMonth(r.date) : ''}</span>
            </li>
          ))}
        </ul>
      </div>
    )
  return (
    <section className="card stack">
      <CardHead title="Personal records" aside={records.data!.new_count > 0 ? <ToneChip tone="good">▲ {records.data!.new_count} new</ToneChip> : undefined} />
      {block('From Garmin', garmin)}
      {block('From your runs', ours)}
    </section>
  )
}

const SERIES: Record<string, keyof HealthForm['runs'][number]> = {
  cadence: 'cadence_spm',
  ground_contact: 'ground_contact_ms',
  vertical_oscillation: 'vertical_oscillation_cm',
  stride_length: 'stride_length_m',
}
const digits = (m: FormMetric) => (m.key === 'stride_length' ? 2 : m.key === 'vertical_oscillation' ? 1 : 0)

/** Running-form trends: last 5 runs vs the 5 before, per metric, with the run-by-run line. */
export function FormTrendsCard() {
  const form = useHealthForm('3m')
  const f = form.data
  const metrics = (f?.metrics ?? []).filter((m) => m.current != null)
  if (!f || !metrics.length) return null
  return (
    <section className="card stack">
      <CardHead title="Running form" sub="Last 5 runs vs the 5 before · 3 months" />
      <div className="mt-grid">
        {metrics.map((m) => {
          const key = SERIES[m.key]
          const vals = key ? f.runs.map((r) => r[key]).filter((v): v is number => typeof v === 'number') : []
          const d = digits(m)
          const tone = m.change == null || m.better == null ? 'flat' : m.better ? 'good' : 'bad'
          return (
            <MetricTile
              key={m.key}
              className="mt-inset"
              label={m.label}
              info={m.key in GLOSSARY ? <InfoButton k={m.key as GlossaryKey} normal={m.previous != null ? `${m.previous.toFixed(d)} ${m.unit} over the 5 runs before` : undefined} /> : undefined}
              value={m.current!.toFixed(d)}
              unit={m.unit}
              chip={m.change != null && Math.abs(m.change) > 0 ? (
                <ToneChip tone={tone}>{m.change > 0 ? '▲' : '▼'} {Math.abs(m.change).toFixed(d)}</ToneChip>
              ) : <ToneChip>— steady</ToneChip>}
              sub={m.previous != null ? `was ${m.previous.toFixed(d)}` : undefined}
            >
              {vals.length >= 3 && <Sparkline values={vals} height={30} color="var(--run)" />}
            </MetricTile>
          )
        })}
      </div>
      <p className="chart-caption">Cadence: closer to ~168 spm is better. Ground contact and bounce: lower is better. Stride length is neither by itself.</p>
    </section>
  )
}
