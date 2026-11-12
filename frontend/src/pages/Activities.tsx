/**
 * Activities — every run, and two to four of them side by side.
 *
 * There was no such page. Runs were reachable only by finding the day they
 * happened on in the calendar, which works when you remember the date and not
 * otherwise. "Was Tuesday better than last Tuesday" had no screen at all.
 *
 * Two things shape it.
 *
 * **Every number is the segmented one.** The list shows what was actually run,
 * not what the watch logged, with the logged figure underneath in small type so
 * the two can be told apart. Rohit's own runs are the argument: Garmin lists
 * one of them as "2.50 km at 12:39/km", and it contained a few hundred metres
 * of running in several blocks. A list built on the logged figure sorts and
 * compares by how long somebody was outside.
 *
 * **Selection is the point, not a feature.** Tapping a row opens it; the
 * checkbox is always visible rather than hidden behind an "edit" mode, because
 * comparison is the reason to come here and a mode you have to discover is a
 * feature nobody uses.
 */

import { useMemo, useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../lib/auth'
import { dur, pace as fmtPace } from '../lib/format'
import { PageHeader } from '../components/PageHeader'
import { ErrorState, Loading, Skeleton } from '../components/States'
import { CompareChart } from '../components/activity/CompareChart'

const MAX_COMPARE = 4

type Metrics = {
  run_distance_m: number
  run_duration_s: number
  longest_run_s: number
  run_fraction: number
  run_block_count: number
  run_pace_s_per_km: number | null
  avg_run_hr: number | null
  avg_run_cadence_spm: number | null
}

type Row = {
  id: number
  local_date: string
  sport: string
  started_at: string
  total_distance_m: number
  total_timer_s: number
  avg_hr: number | null
  metrics: Metrics | null
}

type Page = { count: number; results: Row[] }

type CompareMetric = {
  key: string
  label: string
  direction: number
  note: string
  baseline_id: number
  values: Record<string, number>
  change_pct: Record<string, number>
}

type Comparison = {
  activities: { id: number; date: string; analysed: boolean; logged_km: number }[]
  metrics: CompareMetric[]
  unanalysed: number[]
  review?: {
    available: boolean
    headline?: string
    improving?: string[]
    watch?: string[]
    do_next?: string[]
    markdown?: string
    detail?: string
  }
}

const FORMAT: Record<string, (v: number) => string> = {
  run_distance_m: (v) => `${(v / 1000).toFixed(2)} km`,
  run_duration_s: (v) => dur(v),
  longest_run_s: (v) => dur(v),
  run_pace_s_per_km: (v) => `${fmtPace(v)}/km`,
  avg_run_hr: (v) => `${Math.round(v)} bpm`,
  avg_run_cadence_spm: (v) => `${Math.round(v)} spm`,
  run_fraction: (v) => `${v.toFixed(0)}%`,
  run_block_count: (v) => `${v}`,
  hr_drift_percent: (v) => `${v.toFixed(1)}%`,
}

const fmt = (key: string, value: number) => (FORMAT[key] ?? ((v: number) => `${v}`))(value)

/**
 * Whether a change is an improvement, given which way the metric runs.
 * Never inferred from the sign — a pace that fell and a distance that fell are
 * both negative and only one of them is good news.
 */
function tone(direction: number, pct: number): 'good' | 'bad' | 'flat' {
  if (Math.abs(pct) < 2 || direction === 0) return 'flat'
  return Math.sign(pct) === Math.sign(direction) ? 'good' : 'bad'
}

function ActivityRow({
  row, selected, onToggle, disabled,
}: { row: Row; selected: boolean; onToggle: () => void; disabled: boolean }) {
  const m = row.metrics
  const date = new Date(`${row.local_date}T00:00:00`)

  return (
    <li className={`act-row ${selected ? 'is-selected' : ''}`}>
      <button
        type="button"
        className={`act-tick ${selected ? 'on' : ''}`}
        onClick={onToggle}
        disabled={disabled && !selected}
        aria-pressed={selected}
        aria-label={selected ? 'Remove from comparison' : 'Add to comparison'}
      />
      <Link to={`/activities/${row.id}`} className="act-link">
        <div className="act-when">
          <strong>{date.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}</strong>
          <span className="small muted">
            {date.toLocaleDateString(undefined, { weekday: 'short' })}
          </span>
        </div>

        <div
          className="act-main"
          data-date={date.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}
        >
          {m && m.run_block_count > 0 ? (
            <>
              <span className="act-primary num">{(m.run_distance_m / 1000).toFixed(2)} km run</span>
              <span className="small muted">
                {(row.total_distance_m / 1000).toFixed(2)} km logged ·{' '}
                {m.run_block_count} block{m.run_block_count === 1 ? '' : 's'}
              </span>
            </>
          ) : (
            <>
              <span className="act-primary num">
                {(row.total_distance_m / 1000).toFixed(2)} km {row.sport.replace('_', ' ')}
              </span>
              <span className="small muted">
                {m ? 'No running blocks' : 'Not analysed yet'}
              </span>
            </>
          )}
        </div>

        <div className="act-stats">
          <span className="num">{dur(row.total_timer_s)}</span>
          <span className="num">{m?.run_pace_s_per_km ? `${fmtPace(m.run_pace_s_per_km)}/km` : '—'}</span>
          <span className="num">{m?.longest_run_s ? dur(m.longest_run_s) : '—'}</span>
          <span className="num">{row.avg_hr ? `${row.avg_hr}` : '—'}</span>
        </div>
      </Link>
    </li>
  )
}

function ComparePanel({
  ids, onClear,
}: { ids: number[]; onClear: () => void }) {
  const [explained, setExplained] = useState(false)

  const query = useQuery<Comparison>({
    queryKey: ['compare', [...ids].sort((a, b) => a - b)],
    queryFn: () => api('/activities/compare/', {
      method: 'POST', body: JSON.stringify({ ids }),
    }),
    enabled: ids.length >= 2,
  })

  const explain = useMutation({
    mutationFn: () => api<Comparison>('/activities/compare/', {
      method: 'POST', body: JSON.stringify({ ids, explain: true }),
    }),
    onSuccess: () => setExplained(true),
  })

  if (ids.length < 2) {
    return (
      <section className="card compare-hint">
        <p className="small muted">
          Tick {2 - ids.length} more run{2 - ids.length === 1 ? '' : 's'} to compare.
          Up to {MAX_COMPARE}.
        </p>
      </section>
    )
  }

  if (query.isPending) return <section className="card"><Skeleton lines={6} /></section>
  if (query.isError || !query.data) {
    return <ErrorState message="The comparison did not load." onRetry={() => query.refetch()} />
  }

  const { activities, metrics, unanalysed } = query.data
  const review = explain.data?.review ?? query.data.review
  const columns = activities.map((a) => a.id)
  const label = (id: number) => {
    const row = activities.find((a) => a.id === id)!
    return new Date(`${row.date}T00:00:00`).toLocaleDateString(undefined,
      { day: 'numeric', month: 'short' })
  }

  return (
    <section className="card compare">
      <div className="row">
        <h2>Compared</h2>
        <button type="button" className="linkish small" onClick={onClear}>Clear</button>
      </div>

      {unanalysed.length > 0 && (
        <p className="small muted compare-warn">
          {unanalysed.length} of these has no segmented data yet, so it is listed
          but not compared.
        </p>
      )}

      <div className="compare-grid" style={{ '--cols': columns.length } as React.CSSProperties}>
        <span className="ch">Measurement</span>
        {columns.map((id) => (
          <span key={id} className="ch r">
            {label(id)}
            {id === metrics[0]?.baseline_id && <small>baseline</small>}
          </span>
        ))}

        {metrics.map((metric) => (
          <Fragmentish key={metric.key}>
            <span className="cl">
              {metric.label}
              <small>{metric.note}</small>
            </span>
            {columns.map((id) => {
              const value = metric.values[String(id)]
              const pct = metric.change_pct[String(id)]
              const isBase = id === metric.baseline_id
              return (
                <span key={id} className="cv num">
                  {value == null ? '—' : fmt(metric.key, value)}
                  {!isBase && value != null && (
                    <em className={`cd ${tone(metric.direction, pct)}`}>
                      {Math.abs(pct) < 2 ? '·' : pct > 0 ? '▲' : '▼'} {Math.abs(pct).toFixed(0)}%
                    </em>
                  )}
                </span>
              )
            })}
          </Fragmentish>
        ))}
      </div>

      {/* The table says the pace fell 2%. The chart says where — whether the
          whole run was slower, or the first half matched and it fell apart at
          twelve minutes. Different problems, different answers. */}
      <CompareChart activities={activities.map((a) => ({ id: a.id, date: a.date }))} />

      {review?.available ? (
        <div className="compare-review">
          <p className="compare-headline">{review.headline}</p>
          {review.improving && review.improving.length > 0 && (
            <>
              <h3>Improving</h3>
              <ul>{review.improving.map((t) => <li key={t}>{t}</li>)}</ul>
            </>
          )}
          {review.watch && review.watch.length > 0 && (
            <>
              <h3>Watch</h3>
              <ul>{review.watch.map((t) => <li key={t}>{t}</li>)}</ul>
            </>
          )}
          {review.do_next && review.do_next.length > 0 && (
            <>
              <h3>Do next</h3>
              <ul>{review.do_next.map((t) => <li key={t}>{t}</li>)}</ul>
            </>
          )}
        </div>
      ) : (
        <button
          type="button"
          className="btn-secondary compare-explain"
          onClick={() => explain.mutate()}
          disabled={explain.isPending || explained}
        >
          {explain.isPending ? 'Reading…' : 'What does this mean?'}
        </button>
      )}
    </section>
  )
}

/** React.Fragment with a key, without importing Fragment at every call site. */
function Fragmentish({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}

export default function Activities() {
  const [sport, setSport] = useState<string>('')
  const [ranOnly, setRanOnly] = useState(true)
  const [picked, setPicked] = useState<number[]>([])

  const query = useQuery<Page>({
    queryKey: ['activities', sport, ranOnly],
    queryFn: () => api(
      `/activities/?page_size=50${sport ? `&sport=${sport}` : ''}${ranOnly ? '&ran=true' : ''}`,
    ),
  })

  const rows = query.data?.results ?? []
  const toggle = (id: number) =>
    setPicked((current) =>
      current.includes(id)
        ? current.filter((x) => x !== id)
        : current.length >= MAX_COMPARE ? current : [...current, id],
    )

  const sports = useMemo(
    () => Array.from(new Set(rows.map((r) => r.sport))).sort(),
    [rows],
  )

  if (query.isPending) return <Loading />
  if (query.isError) {
    return <ErrorState message="Your activities did not load." onRetry={() => query.refetch()} />
  }

  return (
    <div className="page">
      <PageHeader title="Activities" />

      <div className="act-filters">
        <button
          type="button"
          className={`chip-btn ${ranOnly ? 'on' : ''}`}
          onClick={() => setRanOnly((v) => !v)}
        >
          Runs with running in them
        </button>
        {sports.length > 1 && sports.map((s) => (
          <button
            key={s}
            type="button"
            className={`chip-btn ${sport === s ? 'on' : ''}`}
            onClick={() => setSport((current) => (current === s ? '' : s))}
          >
            {s.replace('_', ' ')}
          </button>
        ))}
        {picked.length > 0 && (
          <span className="act-count small">
            {picked.length} of {MAX_COMPARE} selected
          </span>
        )}
      </div>

      {picked.length > 0 && (
        <ComparePanel ids={picked} onClear={() => setPicked([])} />
      )}

      {rows.length === 0 ? (
        <section className="card">
          <h2>Nothing here yet</h2>
          <p className="small muted">
            {ranOnly
              ? 'No runs with running blocks in them. Turn off the filter to see everything recorded.'
              : 'No activities recorded. Once Garmin syncs, they appear here.'}
          </p>
        </section>
      ) : (
        <section className="card">
          <div className="act-head small muted">
            <span />
            <span>Date</span>
            <span>What you ran</span>
            <span className="act-stats">
              <span>Time</span><span>Pace</span><span>Longest</span><span>HR</span>
            </span>
          </div>
          <ul className="act-list">
            {rows.map((row) => (
              <ActivityRow
                key={row.id}
                row={row}
                selected={picked.includes(row.id)}
                onToggle={() => toggle(row.id)}
                disabled={picked.length >= MAX_COMPARE}
              />
            ))}
          </ul>
          <p className="small muted act-foot">
            {query.data.count} recorded. Pace and longest block are the running
            parts only — the walking is excluded.
          </p>
        </section>
      )}
    </div>
  )
}
