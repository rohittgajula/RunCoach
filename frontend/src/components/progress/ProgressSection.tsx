import { Disclosure, Row, RowGroup } from '../Disclose'
import { ExcludedNote } from '../quality/ReviewEntry'
import { HealthIcon } from '../Icons'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ApiError } from '../../lib/auth'
import { todayISO } from '../../lib/format'
import { errorText, progressParams, useProgress } from '../../lib/queries'
import type { ProgressHighlight, ProgressQuery, ProgressWindow } from '../../lib/types'
import { Bullets } from '../Bullets'
import { Field } from '../Field'
import { RangePill, RangeSheet, useSectionSelection } from '../health/RangeControl'
import { fromSearch } from '../health/healthRange'
import { RangeSwitch } from '../RangeSwitch'
import { Empty, ErrorState, Skeleton } from '../States'
import { BestsList } from './BestsList'
import { BucketTable } from './BucketTable'
import { ProgressChart } from './ProgressChart'
import { ProgressFocus } from './ProgressFocus'
import { ProgressReviewCard } from './ProgressReviewCard'
import { FormTrendsCard, RecordsCard } from './RecordsAndForm'
import { bestsList, daySpan, periodText, windowText } from './progressUtil'

type Mode = '1' | '5' | '10' | '20' | 'dates'

const MODES: Array<{ value: Mode; label: string }> = [
  { value: '1', label: '1' },
  { value: '5', label: '5' },
  { value: '10', label: '10' },
  { value: '20', label: '20' },
  { value: 'dates', label: 'Dates' },
]

const MAX_DAYS = 730

type Dates = { start: string; end: string; compare: boolean; compare_start: string; compare_end: string }
type CompareDates = Pick<Dates, 'compare' | 'compare_start' | 'compare_end'>

function datesError(d: Dates): string | null {
  if (!d.start || !d.end) return 'Pick both dates.'
  if (d.start > d.end) return '“From” must be on or before “to”.'
  if (daySpan(d.start, d.end) > MAX_DAYS) return 'Pick at most two years.'
  if (d.compare) {
    if (!d.compare_start || !d.compare_end) return 'Pick both compare dates.'
    if (d.compare_start > d.compare_end) return 'Compare “from” must be on or before “to”.'
    if (daySpan(d.compare_start, d.compare_end) > MAX_DAYS) return 'Compare range: at most two years.'
  }
  return null
}

/** Insights → Progress: 1 · 5 · 10 · 20 · Dates, summary bullets, table, chart, review. */
export function ProgressSection() {
  const [search] = useSearchParams()
  const [mode, setMode] = useState<Mode>(() => (fromSearch(search) ? 'dates' : '5'))
  // R12: "Dates" uses the shared Health range control (presets or custom, ≤ 2 years).
  const [period, setSelection] = useSectionSelection(mode === 'dates' ? 'progress' : '', '4w')
  const [rangeOpen, setRangeOpen] = useState(false)
  const [cmp, setCmp] = useState<CompareDates | null>(null)
  const dates: Dates = {
    start: period.start,
    end: period.end,
    compare: cmp?.compare ?? false,
    compare_start: cmp?.compare_start ?? period.compareStart,
    compare_end: cmp?.compare_end ?? period.compareEnd,
  }
  const invalid = mode === 'dates' ? datesError(dates) : null

  const query: ProgressQuery = mode === 'dates'
    ? { start: dates.start, end: dates.end, ...(dates.compare ? { compare_start: dates.compare_start, compare_end: dates.compare_end } : {}) }
    : { window: Number(mode) as ProgressWindow }
  const progress = useProgress(query, !invalid)
  const data = progress.data

  const setDate = (key: keyof CompareDates, value: string | boolean) =>
    setCmp({ compare: dates.compare, compare_start: dates.compare_start, compare_end: dates.compare_end, [key]: value })

  if (progress.isError && progress.error instanceof ApiError && progress.error.status === 404) {
    return <Empty title="Progress isn’t available yet">Sync a few runs and check back.</Empty>
  }

  return (
    <div className="stack">
      <RangeSwitch value={mode} onChange={setMode} options={MODES} />
      <ExcludedNote />

      {mode === 'dates' ? (
        <section className="card stack dates-card">
          <div className="row-wrap" style={{ justifyContent: 'space-between' }}>
            <span className="grow">
              <strong className="block">Runs between</strong>
              <span className="muted small">{period.days} days</span>
            </span>
            <RangePill period={period} freq={false} onClick={() => setRangeOpen(true)} />
          </div>
          <div className="switch-row">
            <span className="grow">
              <strong>Compare with</strong>
              <span className="muted small block">{dates.compare ? 'Your own range' : 'Off — the same length just before'}</span>
            </span>
            <button
              type="button"
              role="switch"
              aria-checked={dates.compare}
              aria-label="Compare with another range"
              className={`switch ${dates.compare ? 'is-on' : ''}`}
              onClick={() => setDate('compare', !dates.compare)}
            />
          </div>
          {dates.compare && (
            <div className="grid-2 grid-2-even">
              <Field label="From">
                <input type="date" value={dates.compare_start} max={dates.compare_end || todayISO()} onChange={(e) => setDate('compare_start', e.target.value)} />
              </Field>
              <Field label="To">
                <input type="date" value={dates.compare_end} min={dates.compare_start} max={todayISO()} onChange={(e) => setDate('compare_end', e.target.value)} />
              </Field>
            </div>
          )}
          {invalid && <p className="field-error">{invalid}</p>}
        </section>
      ) : (
        <p className="muted small centered-text">{windowText(Number(mode) as ProgressWindow)}</p>
      )}
      {mode === 'dates' && !invalid && <p className="muted small centered-text">{periodText(data?.period, dates)}</p>}
      <RangeSheet open={rangeOpen} onClose={() => setRangeOpen(false)} period={period} onApply={setSelection} title="Progress dates" showFreq={false} />

      {!invalid && progress.isPending && <Skeleton height={240} />}
      {!invalid && progress.isError && !data && <ErrorState message={errorText(progress.error)} onRetry={() => progress.refetch()} />}
      {!invalid && data && (
        <div className={`stack ${progress.isPlaceholderData ? 'is-stale' : ''}`}>
          <Highlights items={data.highlights} />
          <section className="card stack">
            <ProgressChart series={data.series ?? []} />
          </section>
          <RowGroup>
            <Row to="/health/heart" icon={<HealthIcon size={20} />} title="Heart adaptation" sub="Day by day: HR at your easy pace, time under your cap" />
          </RowGroup>
          {/* R14 §1: the full table, bests, focus, records, form and the coach review, grouped. */}
          <Disclosure id="progress-details" title="Compared in detail" sub="Every number, side by side">
            <section className="card stack">
              <h3 className="habit-sub">Compared</h3>
              <BucketTable data={data} />
            </section>
          </Disclosure>
          <Disclosure id="progress-more" title="Bests, records, form & coach review" sub="What to work on next">
          {bestsList(data.bests).length > 0 && (
            <section className="card stack">
              <h3 className="habit-sub">Bests</h3>
              <BestsList bests={bestsList(data.bests)} />
            </section>
          )}
          {(data.focus?.length ?? 0) > 0 && (
            <section className="card stack">
              <h3 className="habit-sub">What to work on</h3>
              <ProgressFocus focus={data.focus} />
            </section>
          )}
          <RecordsCard />
          <FormTrendsCard />
          <section className="card">
            <ProgressReviewCard key={progressParams(query)} review={data.review} query={query} />
          </section>
          </Disclosure>
        </div>
      )}
    </div>
  )
}

/** "Summary": the server's highlights as bullets with coloured dots, good first. */
function Highlights({ items }: { items: ProgressHighlight[] | undefined }) {
  if (!items?.length) return null
  return (
    <section className="card stack">
      <h3 className="habit-sub">Summary</h3>
      <Bullets items={items} />
    </section>
  )
}
