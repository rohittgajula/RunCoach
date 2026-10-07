import { useMemo, useState, type FormEvent } from 'react'
import { dateTime, isoDate, localInputValue, pace, parsePace, todayISO } from '../../lib/format'
import { errorText, useAddMetric, useDeleteMetric, useMetricEntries } from '../../lib/queries'
import type { MetricKind, MetricSource, Range } from '../../lib/types'
import { BottomSheet } from '../BottomSheet'
import { ChipButton, ChipGroup } from '../ChipButton'
import { Field } from '../Field'
import { HelpIcon, PlusIcon, TrashIcon } from '../Icons'
import { ChartFrame, DeltaChip } from '../ChartFrame'
import { trendCaption, trendOf, type Better } from '../chartUtil'
import { MetricChart } from '../MetricChart'
import { RangeSwitch } from '../RangeSwitch'
import { Empty, ErrorState, Skeleton } from '../States'

type Config = {
  title: string
  unit: string
  format: (v: number) => string
  parse: (text: string) => number | null
  placeholder: string
  reversed?: boolean
  help: string
  /** Which direction is good for the delta chip (null: neither). */
  better: Better
  delta: (v: number) => string
}

export const METRICS: Record<MetricKind, Config> = {
  weight: {
    title: 'Weight',
    unit: 'kg',
    format: (v) => v.toFixed(1),
    parse: (t) => (Number.isFinite(Number(t)) && Number(t) > 20 ? Number(t) : null),
    placeholder: '72.5',
    better: null, delta: (v) => `${v.toFixed(1)} kg`,
    help: 'Used for calorie and carb targets (g/kg) and to compare your predicted vs actual weight trend. Weigh in at the same time of day for a clean trend.',
  },
  threshold_pace: {
    title: 'Threshold Pace',
    unit: 'min/km',
    format: (v) => pace(v),
    parse: parsePace,
    placeholder: '5:30',
    better: 'lower', delta: (v) => `${Math.round(v)} s/km`,
    reversed: true,
    help: 'The fastest pace you could hold for about an hour. Every pace target in your plan is derived from it. Estimated from your runs, or set it yourself after a test.',
  },
  resting_hr: {
    title: 'Resting HR',
    unit: 'bpm',
    format: (v) => String(Math.round(v)),
    parse: (t) => (Number(t) >= 25 && Number(t) <= 120 ? Number(t) : null),
    placeholder: '52',
    better: 'lower', delta: (v) => `${Math.round(v)} bpm`,
    help: 'Your heart rate fully at rest, ideally first thing in the morning. Together with max HR it sets your heart-rate zones.',
  },
  max_hr: {
    title: 'Max HR',
    unit: 'bpm',
    format: (v) => String(Math.round(v)),
    parse: (t) => (Number(t) >= 120 && Number(t) <= 230 ? Number(t) : null),
    placeholder: '188',
    better: null, delta: (v) => `${Math.round(v)} bpm`,
    help: 'The highest heart rate you can reach. A measured value from a hard effort beats any age formula.',
  },
}

const SOURCE: Record<MetricSource, string> = { manual: 'Manual input', garmin: 'Garmin', estimated: 'Estimated' }

export function MetricSheet({ kind, onClose }: { kind: MetricKind | null; onClose: () => void }) {
  return (
    <BottomSheet
      open={kind != null}
      onClose={onClose}
      full
      title={kind ? METRICS[kind].title : ''}
      label="Metric history"
    >
      {kind && <MetricBody kind={kind} />}
    </BottomSheet>
  )
}

function MetricBody({ kind }: { kind: MetricKind }) {
  const config = METRICS[kind]
  const [range, setRange] = useState<Range>('3m')
  const [adding, setAdding] = useState(false)
  const [help, setHelp] = useState(false)
  const [value, setValue] = useState('')
  const [when, setWhen] = useState(localInputValue(new Date()))
  const [formError, setFormError] = useState('')
  const entries = useMetricEntries(kind, range)
  const add = useAddMetric()
  const remove = useDeleteMetric()

  const chart = useMemo(() => {
    const list = [...(entries.data?.entries ?? [])].sort((a, b) => a.recorded_at.localeCompare(b.recorded_at))
    const points = list.map((e) => ({ date: isoDate(new Date(e.recorded_at)), value: e.value }))
    // The latest reading holds until today — draw it to the right edge.
    const last = points[points.length - 1]
    if (last && last.date < todayISO()) points.push({ date: todayISO(), value: last.value })
    return points
  }, [entries.data])

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const parsed = config.parse(value)
    if (parsed == null) {
      setFormError(kind === 'threshold_pace' ? 'Use m:ss, for example 5:30.' : 'That does not look right.')
      return
    }
    setFormError('')
    add.mutate(
      { kind, value: parsed, recorded_at: new Date(when).toISOString() },
      {
        onSuccess: () => {
          setAdding(false)
          setValue('')
        },
      },
    )
  }

  const list = [...(entries.data?.entries ?? [])].sort((a, b) => b.recorded_at.localeCompare(a.recorded_at))

  return (
    <div className="metric">
      <div className="metric-tools">
        <ChipGroup>
          <ChipButton label="About this metric" onClick={() => setHelp(!help)} className={help ? 'is-on' : ''}>
            <HelpIcon />
          </ChipButton>
          <ChipButton label="Add entry" onClick={() => setAdding(!adding)} className={adding ? 'is-on' : ''}>
            <PlusIcon />
          </ChipButton>
        </ChipGroup>
      </div>

      {help && <p className="help">{config.help}</p>}

      {adding && (
        <form className="card inline-form" onSubmit={submit}>
          <div className="grid-2">
            <Field label={`${config.title} (${config.unit})`} error={formError}>
              <input autoFocus inputMode={kind === 'threshold_pace' ? 'text' : 'decimal'} placeholder={config.placeholder} value={value} onChange={(e) => setValue(e.target.value)} />
            </Field>
            <Field label="When">
              <input type="datetime-local" value={when} max={localInputValue(new Date())} onChange={(e) => setWhen(e.target.value)} />
            </Field>
          </div>
          {add.isError && <p className="bad small">{errorText(add.error, 'Could not save.')}</p>}
          <div className="row-end">
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAdding(false)}>Cancel</button>
            <button className="btn btn-primary btn-sm" disabled={add.isPending}>{add.isPending ? 'Saving…' : 'Save'}</button>
          </div>
        </form>
      )}

      {entries.isPending && <Skeleton height={240} />}
      {entries.isError && !entries.data && <ErrorState message={errorText(entries.error)} onRetry={() => entries.refetch()} />}
      {entries.data && (
        <>
          {chart.length > 0 ? (
            <ChartFrame
              title={config.title}
              chip={<DeltaChip trend={trendOf(chart.map((p) => p.value), config.better)} format={config.delta} label="vs the earlier half of this range" />}
              caption={trendCaption(trendOf(chart.map((p) => p.value), config.better), config.title, config.format, config.unit === 'min/km' ? '/km' : config.unit, 'range', config.delta)}
            >
              <MetricChart data={chart} format={config.format} reversed={config.reversed} axis="left" step />
            </ChartFrame>
          ) : (
            <Empty title="No entries in this range">Tap + to add one.</Empty>
          )}
          <RangeSwitch value={range} onChange={setRange} />
          <ul className="entries">
            {list.map((entry) => (
              <li key={entry.id} className="entry">
                <div className="entry-main">
                  <p className="entry-when">
                    {dateTime(entry.recorded_at)}
                    {entries.data?.current?.id === entry.id && <span className="badge">Current</span>}
                  </p>
                  <p className="muted small">{SOURCE[entry.source] ?? entry.source}</p>
                </div>
                <p className="entry-value">
                  <strong>{config.format(entry.value)}</strong> <span className="muted">{config.unit}</span>
                </p>
                {entry.source === 'manual' && (
                  <button type="button" className="icon-btn" aria-label="Delete entry" disabled={remove.isPending} onClick={() => remove.mutate(entry.id)}>
                    <TrashIcon size={18} />
                  </button>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
