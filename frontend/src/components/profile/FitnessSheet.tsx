import { useMemo, useState } from 'react'
import { errorText, useFitness } from '../../lib/queries'
import type { FitnessStatus, Range } from '../../lib/types'
import { BottomSheet } from '../BottomSheet'
import { Markdown } from '../Markdown'
import { ChartFrame, DeltaChip } from '../ChartFrame'
import { trendOf } from '../chartUtil'
import { MetricChart } from '../MetricChart'
import { RangeSwitch } from '../RangeSwitch'
import { ErrorState, Skeleton } from '../States'
import { StatusBandChart } from '../StatusBandChart'

export type FitnessView = 'fitness' | 'fatigue' | 'status'

export const STATUS_LABEL: Record<FitnessStatus, string> = {
  detraining: 'Detraining',
  fresh: 'Fresh',
  maintaining: 'Maintaining',
  gaining: 'Gaining Fitness',
  overtraining: 'Overtraining Risk',
  insufficient_data: 'Not enough data',
}

const ABOUT: Record<FitnessView, { title: string; text: string; howTitle: string; how: string }> = {
  fitness: {
    title: 'About Fitness',
    text: 'This chart shows your fitness trend over time, based on your recent training load (a 42-day weighted average).',
    howTitle: 'How to use it:',
    how: `- Rising fitness usually means your training has been consistent enough to build long-term capacity.
- Flat fitness suggests you are maintaining — fine between blocks, not while building.
- A drop after a race or illness is normal; it comes back quickly with steady running.`,
  },
  fatigue: {
    title: 'About Fatigue',
    text: 'Fatigue is your short-term load (a 7-day weighted average). It rises fast after hard days and fades within a week.',
    howTitle: 'How to use it:',
    how: `- Fatigue well above fitness means you are absorbing a hard block — protect sleep and easy days.
- Fatigue below fitness means you are fresh — a good time for a key session or a race.`,
  },
  status: {
    title: 'About Training Status',
    text: 'This chart shows whether you are improving your fitness, based on form: fitness minus fatigue.',
    howTitle: 'Zones & tips',
    how: `- **Detraining** (above +20): very light load. Fitness will start to decline if you stay here for long.
- **Fresh** (+5 to +20): rested and ready — ideal before a race.
- **Maintaining** (−10 to +5): enough load to hold fitness, not to build it.
- **Gaining Fitness** (−30 to −10): the productive zone for a training block.
- **Overtraining Risk** (below −30): load is outrunning recovery. Back off before something breaks.`,
  },
}

export function FitnessSheet({ view, onClose }: { view: FitnessView | null; onClose: () => void }) {
  const [current, setCurrent] = useState<FitnessView>('fitness')
  const [range, setRange] = useState<Range>('3m')
  const [lastView, setLastView] = useState<FitnessView | null>(null)
  if (view !== lastView) {
    setLastView(view)
    if (view) setCurrent(view)
  }
  const fitness = useFitness(range)

  const data = fitness.data
  const series = useMemo(() => data?.series ?? [], [data])

  const heading = () => {
    if (!data) return ''
    const c = data.current
    if (current === 'status') return STATUS_LABEL[c.status]
    const v = current === 'fitness' ? c.fitness : c.fatigue
    return v == null ? '--' : String(Math.round(v))
  }
  const about = ABOUT[current]
  const values = series.map((p) => (current === 'fitness' ? p.fitness : current === 'fatigue' ? p.fatigue : p.form))
  // Fitness up is good; fatigue and form have no single good direction.
  const trend = trendOf(values, current === 'fitness' ? 'higher' : null, 0.5)
  const round = (v: number) => String(Math.round(v))
  const caption = (() => {
    if (!data || !trend) return null
    if (current === 'status') {
      const f = data.current.form
      return f == null ? null : `Form ${f > 0 ? '+' : ''}${Math.round(f)} today — ${STATUS_LABEL[data.current.status].toLowerCase()}; ${trend.delta > 0 ? 'fresher' : 'more loaded'} than earlier in this range.`
    }
    const name = current === 'fitness' ? 'Fitness' : 'Fatigue'
    const pct = Math.abs(trend.delta) / Math.max(1, Math.abs(trend.avg)) * 100
    if (pct < 2) return `${name} has held steady over this range.`
    return `${name} is ${trend.delta > 0 ? 'up' : 'down'} ${Math.round(Math.abs(trend.delta))} points vs earlier in this range${current === 'fitness' && trend.delta > 0 ? ' — training is building.' : '.'}`
  })()

  return (
    <BottomSheet
      open={view != null}
      onClose={onClose}
      full
      label="Fitness"
      actions={
        <label className="select-pill">
          <select value={current} onChange={(e) => setCurrent(e.target.value as FitnessView)} aria-label="Chart">
            <option value="fitness">Fitness</option>
            <option value="fatigue">Fatigue</option>
            <option value="status">Training Status</option>
          </select>
        </label>
      }
    >
      <RangeSwitch value={range} onChange={setRange} />
      <div className="sheet-heading-row">
        <h2 className="sheet-heading">
          {current === 'status' ? 'Training Status' : current === 'fitness' ? 'Fitness' : 'Fatigue'}:{' '}
          <span className={current === 'status' ? 'muted-strong' : ''}>{heading()}</span>
        </h2>
        <DeltaChip trend={trend} format={round} label="vs the earlier half of this range" />
      </div>
      {fitness.isPending && <Skeleton height={300} />}
      {fitness.isError && !data && <ErrorState message={errorText(fitness.error)} onRetry={() => fitness.refetch()} />}
      {data && (
        <ChartFrame caption={caption}>
        {current === 'status' ? (
          <StatusBandChart data={series.map((p) => ({ date: p.date, form: p.form }))} />
        ) : (
          <MetricChart
            data={series.map((p) => ({ date: p.date, value: current === 'fitness' ? p.fitness : p.fatigue }))}
            height={300}
            domain={[0, 'auto']}
          />
        )}
        </ChartFrame>
      )}
      <section className="card about">
        <h3>{about.title}</h3>
        <p>{about.text}</p>
        <h3>{about.howTitle}</h3>
        <Markdown text={about.how} />
      </section>
    </BottomSheet>
  )
}
