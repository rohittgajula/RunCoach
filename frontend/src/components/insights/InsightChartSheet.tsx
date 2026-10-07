import { useState } from 'react'
import { errorText, useInsights } from '../../lib/queries'
import type { InsightRange } from '../../lib/types'
import { BottomSheet } from '../BottomSheet'
import { ChartFrame, DeltaChip } from '../ChartFrame'
import { trendCaption, trendOf } from '../chartUtil'
import { RangePill, RangeSheet } from '../health/RangeControl'
import { FREQ_WORD, bucket, periodCaption, useHealthPeriod, withApiPeriod } from '../health/healthRange'
import { MetricChart } from '../MetricChart'
import { Empty, ErrorState, Skeleton } from '../States'
import { CHARTS, type ChartKey } from './charts'

export const INSIGHT_RANGES: Array<{ value: InsightRange; label: string }> = [
  { value: '4w', label: '4 weeks' },
  { value: '12w', label: '12 weeks' },
  { value: '6m', label: '6 months' },
]

/** Full chart for one Insights metric, on the section's range + frequency (R12). */
export function InsightChartSheet({ chart, onClose }: { chart: ChartKey | null; onClose: () => void }) {
  const { period: chosen, setSelection } = useHealthPeriod()
  const [rangeOpen, setRangeOpen] = useState(false)
  const insights = useInsights(chosen.params)
  const config = chart ? CHARTS[chart] : null
  const data = insights.data
  const period = withApiPeriod(chosen, data?.period)
  const points = config && data ? bucket(config.points(data), period.freq, config.agg) : []
  const values = points.map((p) => p.value).filter((v): v is number => v != null)
  const latest = values.length ? values[values.length - 1] : null
  const band = config?.band && data ? config.band(data) : null
  const trend = config ? trendOf(values, config.better) : null
  const rangeLabel = chosen.selection.kind === 'preset' ? `${chosen.long}` : 'period'
  const deltaFmt = config?.delta ?? config?.format ?? String

  return (
    <BottomSheet open={!!chart} onClose={onClose} full label={config?.title ?? 'Chart'} title={config?.title}>
      {config && (
        <>
          <div className="row-wrap" style={{ justifyContent: 'space-between' }}>
            <span className="muted small">{period.freq === 'day' ? 'Per day' : `${FREQ_WORD[period.freq][0].toUpperCase()}${FREQ_WORD[period.freq].slice(1)} ${config.agg === 'last' ? 'values' : 'averages'}`}</span>
            <RangePill period={chosen} onClick={() => setRangeOpen(true)} />
          </div>
          <div className="sheet-heading-row">
            <h2 className="sheet-heading">
              {latest != null ? config.format(latest) : '--'} <span className="muted small">{config.unit}</span>
            </h2>
            <DeltaChip trend={trend} format={deltaFmt} />
          </div>
          {insights.isPending && <Skeleton height={280} />}
          {insights.isError && !data && <ErrorState message={errorText(insights.error)} onRetry={() => insights.refetch()} />}
          {data && (values.length >= 2 ? (
            <ChartFrame caption={<>{trendCaption(trend, config.title, config.format, '', `${rangeLabel}`, config.delta)}<span className="block">{periodCaption(period)}</span></>}>
              <MetricChart data={points} format={config.format} reversed={config.reversed} height={280} band={band} color={`var(--${config.topic ?? 'run'})`} freq={period.freq} />
            </ChartFrame>
          ) : (
            <Empty title="Not enough data yet">Sync a few more days from Garmin to see a trend.</Empty>
          ))}
          {band?.label && <p className="legend"><span className="legend-swatch legend-band" />{band.label}: {config.format(band.low)}–{config.format(band.high)}</p>}
          <RangeSheet open={rangeOpen} onClose={() => setRangeOpen(false)} period={chosen} onApply={setSelection} />
          <section className="card about">
            <h3>About</h3>
            <p>{config.about}</p>
          </section>
        </>
      )}
    </BottomSheet>
  )
}
