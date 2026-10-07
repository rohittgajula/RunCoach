import { useState } from 'react'
import { errorText, useInsights } from '../../lib/queries'
import type { InsightRange } from '../../lib/types'
import { BottomSheet } from '../BottomSheet'
import { ChartFrame, DeltaChip } from '../ChartFrame'
import { trendCaption, trendOf } from '../chartUtil'
import { MetricChart } from '../MetricChart'
import { RangeSwitch } from '../RangeSwitch'
import { Empty, ErrorState, Skeleton } from '../States'
import { CHARTS, type ChartKey } from './charts'

export const INSIGHT_RANGES: Array<{ value: InsightRange; label: string }> = [
  { value: '4w', label: '4 weeks' },
  { value: '12w', label: '12 weeks' },
  { value: '6m', label: '6 months' },
]

/** Full chart for one Insights metric, with its own range. */
export function InsightChartSheet({
  chart, initialRange, onClose,
}: { chart: ChartKey | null; initialRange: InsightRange; onClose: () => void }) {
  const [range, setRange] = useState<InsightRange>(initialRange)
  const [last, setLast] = useState<ChartKey | null>(null)
  if (chart !== last) {
    setLast(chart)
    if (chart) setRange(initialRange)
  }
  const insights = useInsights(range)
  const config = chart ? CHARTS[chart] : null
  const data = insights.data
  const points = config && data ? config.points(data) : []
  const values = points.map((p) => p.value).filter((v): v is number => v != null)
  const latest = values.length ? values[values.length - 1] : null
  const band = config?.band && data ? config.band(data) : null
  const trend = config ? trendOf(values, config.better) : null
  const rangeLabel = INSIGHT_RANGES.find((r) => r.value === range)?.label ?? 'range'
  const deltaFmt = config?.delta ?? config?.format ?? String

  return (
    <BottomSheet open={!!chart} onClose={onClose} full label={config?.title ?? 'Chart'} title={config?.title}>
      {config && (
        <>
          <RangeSwitch value={range} onChange={setRange} options={INSIGHT_RANGES} />
          <div className="sheet-heading-row">
            <h2 className="sheet-heading">
              {latest != null ? config.format(latest) : '--'} <span className="muted small">{config.unit}</span>
            </h2>
            <DeltaChip trend={trend} format={deltaFmt} />
          </div>
          {insights.isPending && <Skeleton height={280} />}
          {insights.isError && !data && <ErrorState message={errorText(insights.error)} onRetry={() => insights.refetch()} />}
          {data && (values.length >= 2 ? (
            <ChartFrame caption={trendCaption(trend, config.title, config.format, '', `${rangeLabel}`, config.delta)}>
              <MetricChart data={points} format={config.format} reversed={config.reversed} height={280} band={band} color={`var(--${config.topic ?? 'run'})`} />
            </ChartFrame>
          ) : (
            <Empty title="Not enough data yet">Sync a few more days from Garmin to see a trend.</Empty>
          ))}
          {band?.label && <p className="legend"><span className="legend-swatch legend-band" />{band.label}: {config.format(band.low)}–{config.format(band.high)}</p>}
          <section className="card about">
            <h3>About</h3>
            <p>{config.about}</p>
          </section>
        </>
      )}
    </BottomSheet>
  )
}
