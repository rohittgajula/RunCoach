/**
 * One run, in full.
 *
 * The page leads with the two numbers that disagree, because that disagreement
 * is the whole premise of this app: what the watch logged, and what was
 * actually run. Garmin shows Rohit's 9 Nov outing as "2.50 km at 12:39/km" —
 * a figure that describes neither his running nor his walking, being the
 * average of two things he did at different speeds.
 *
 * Then the blocks, then every trace drawn against them. A heart rate climbing
 * through a walk block means something quite different from one climbing
 * through a run block, and no chart without the blocks on it can tell you which
 * you are looking at.
 */

import { useQuery, useMutation } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { api } from '../lib/auth'
import { dur, pace as fmtPace } from '../lib/format'
import { PageHeader } from '../components/PageHeader'
import { ErrorState, Loading, Skeleton } from '../components/States'
import { BlockStrip, RunChart, clock, type Block, type SeriesPoint } from '../components/activity/RunChart'
import { RunMapSection } from '../components/map/RunMapSection'
import { RunShareButton } from '../components/share/RunShareButton'

type Metrics = {
  run_distance_m: number
  walk_distance_m: number
  run_fraction: number
  run_duration_s: number
  walk_duration_s: number
  run_block_count: number
  longest_run_m: number
  longest_run_s: number
  run_pace_s_per_km: number | null
  walk_pace_s_per_km: number | null
  blended_pace_s_per_km: number | null
  avg_run_cadence_spm: number | null
  avg_run_hr: number | null
  hr_drift_percent: number | null
}

type Detail = {
  id: number
  local_date: string
  sport: string
  started_at: string
  total_distance_m: number
  total_timer_s: number
  total_elapsed_s: number
  avg_hr: number | null
  max_hr: number | null
  total_ascent_m: number | null
  calories: number | null
  metrics: Metrics | null
  segments: Block[]
}

type Series = {
  points: SeriesPoint[]
  has_hr: boolean
  has_cadence: boolean
  has_altitude: boolean
}

/**
 * The share studio wants an ActivityCard; this page loads the fuller detail
 * shape. Only the fields the card actually renders are mapped, rather than
 * widening the detail query to carry a second representation of the same run.
 */
function shareCard(a: Detail, m: Metrics) {
  return {
    id: a.id,
    name: a.sport.replace('_', ' '),
    sport: a.sport,
    device: '',
    start: a.started_at,
    duration_s: a.total_timer_s || a.total_elapsed_s,
    distance_m: a.total_distance_m,
    load: 0,
    run_distance_m: m.run_distance_m,
    walk_distance_m: m.walk_distance_m,
    run_fraction: m.run_fraction,
    longest_run_s: m.longest_run_s,
    steps: null,
    journalled: false,
    reviewed_thread_id: null,
  } as never
}

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="run-stat">
      <span className="run-stat-label">{label}</span>
      <span className="run-stat-value num">{value}</span>
      {note && <span className="run-stat-note">{note}</span>}
    </div>
  )
}

export default function ActivityDetail() {
  const { id } = useParams<{ id: string }>()

  const detail = useQuery<Detail>({
    queryKey: ['activity', id],
    queryFn: () => api(`/activities/${id}/`),
  })
  const series = useQuery<Series>({
    queryKey: ['activity-series', id],
    queryFn: () => api(`/activities/${id}/series/`),
    enabled: !!detail.data,
  })
  const review = useMutation({
    mutationFn: () => api(`/activities/${id}/ai-review/`, { method: 'POST' }),
  })

  if (detail.isPending) return <Loading />
  if (detail.isError || !detail.data) {
    return <ErrorState message="That run did not load." onRetry={() => detail.refetch()} />
  }

  const a = detail.data
  const m = a.metrics
  const blocks = a.segments ?? []
  const points = series.data?.points ?? []
  const date = new Date(`${a.local_date}T00:00:00`)
  const ran = m && m.run_block_count > 0

  return (
    <div className="page">
      <PageHeader
        title={date.toLocaleDateString(undefined, {
          weekday: 'short', day: 'numeric', month: 'short',
        })}
        back="/activities"
        right={ran ? <RunShareButton activity={shareCard(a, m!)} /> : undefined}
      />

      {/* The disagreement, stated first. */}
      <section className="card run-headline">
        {ran ? (
          <>
            <p className="run-truth">
              You ran <strong className="num">{(m!.run_distance_m / 1000).toFixed(2)} km</strong>
              {' '}in <strong className="num">{m!.run_block_count}</strong>{' '}
              block{m!.run_block_count === 1 ? '' : 's'}, at{' '}
              <strong className="num">
                {m!.run_pace_s_per_km ? `${fmtPace(m!.run_pace_s_per_km)}/km` : '—'}
              </strong>.
            </p>
            <p className="small muted">
              The watch logged {(a.total_distance_m / 1000).toFixed(2)} km at{' '}
              {m!.blended_pace_s_per_km ? `${fmtPace(m!.blended_pace_s_per_km)}/km` : '—'} —
              an average of running and walking, which is a speed you never
              actually travelled at.
            </p>
          </>
        ) : (
          <p className="run-truth">
            {(a.total_distance_m / 1000).toFixed(2)} km of{' '}
            {a.sport.replace('_', ' ')} in {dur(a.total_timer_s)}.
            {m ? ' No running blocks in it.' : ' Not analysed yet.'}
          </p>
        )}
      </section>

      {ran && (
        <>
          <section className="card">
            <h2>The blocks</h2>
            <BlockStrip blocks={blocks} total={a.total_elapsed_s || a.total_timer_s} />
            <div className="run-stats">
              <Stat label="Longest unbroken" value={dur(m!.longest_run_s)}
                    note="The number that decides race day" />
              <Stat label="Run time" value={dur(m!.run_duration_s)}
                    note={`${dur(m!.walk_duration_s)} walking`} />
              <Stat label="Run fraction" value={`${Math.round(m!.run_fraction * 100)}%`}
                    note="Of the time you were out" />
              <Stat label="Walk pace"
                    value={m!.walk_pace_s_per_km ? `${fmtPace(m!.walk_pace_s_per_km)}/km` : '—'} />
              <Stat label="Cadence while running"
                    value={m!.avg_run_cadence_spm ? `${Math.round(m!.avg_run_cadence_spm)} spm` : '—'}
                    note={m!.avg_run_cadence_spm && m!.avg_run_cadence_spm < 160
                      ? 'Below 160 — short steps help' : undefined} />
              <Stat label="HR drift"
                    value={m!.hr_drift_percent != null ? `${m!.hr_drift_percent.toFixed(1)}%` : '—'}
                    note="Rising HR at steady effort means fatigue" />
            </div>
          </section>

          <section className="card">
            <div className="row">
              <h2>What the coach makes of it</h2>
            </div>
            {review.data ? (
              <div className="run-review">
                <p>{(review.data as { markdown?: string }).markdown}</p>
              </div>
            ) : (
              <button
                type="button"
                className="btn-secondary"
                onClick={() => review.mutate()}
                disabled={review.isPending}
              >
                {review.isPending ? 'Reading…' : 'Read this run'}
              </button>
            )}
            {review.isError && (
              <p className="small bad">That could not be produced just now.</p>
            )}
          </section>
        </>
      )}

      <section className="card">
        <h2>Through the run</h2>
        <p className="small muted run-legend">
          <i className="bs-run" /> running &nbsp; <i className="bs-walk" /> walking
          — every trace below is drawn over the blocks.
        </p>

        {series.isPending ? (
          <Skeleton lines={8} />
        ) : points.length === 0 ? (
          <p className="small muted">
            No per-second data for this one, so there is nothing to plot.
          </p>
        ) : (
          <div className="run-charts">
            <RunChart points={points} blocks={blocks} metric="pace" label="Pace"
                      unit="/km" reversed format={clock} colour="var(--run)" />
            {series.data?.has_hr && (
              <RunChart points={points} blocks={blocks} metric="hr" label="Heart rate"
                        unit="bpm" colour="var(--bad)" />
            )}
            {series.data?.has_cadence && (
              <RunChart points={points} blocks={blocks} metric="cadence" label="Cadence"
                        unit="spm" colour="var(--habits)"
                        band={{ low: 160, high: 180, label: 'target' }} />
            )}
            {series.data?.has_altitude && (
              <RunChart points={points} blocks={blocks} metric="altitude" label="Elevation"
                        unit="m" colour="var(--recovery)" height={120} />
            )}
          </div>
        )}
      </section>

      <RunMapSection activityId={a.id} />

      {blocks.length > 0 && (
        <section className="card">
          <h2>Block by block</h2>
          {/* A list, not a table. Six grid columns in the ~307px a phone gives a
              card left the kind column about five pixels wide. Each block is a
              row that wraps instead. */}
          <ol className="run-blocks">
            {blocks.map((b) => {
              const row = b as Block & {
                distance_m: number
                avg_pace_s_per_km: number | null
                hr_avg: number | null
              }
              return (
                <li key={b.index} className={`run-block bk-${b.kind}`}>
                  <span className="run-block-no num">{b.index + 1}</span>
                  <span className="run-block-kind">{b.kind}</span>
                  <span className="run-block-dur num">{dur(b.duration_s)}</span>
                  <span className="run-block-rest num">
                    {Math.round(row.distance_m)} m
                    {row.avg_pace_s_per_km ? ` · ${fmtPace(row.avg_pace_s_per_km)}/km` : ''}
                    {row.hr_avg ? ` · ${row.hr_avg} bpm` : ''}
                  </span>
                </li>
              )
            })}
          </ol>
        </section>
      )}

      <p className="small muted">
        <Link to="/activities">← All activities</Link>
      </p>
    </div>
  )
}
