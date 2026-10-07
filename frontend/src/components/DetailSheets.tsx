import { useState } from 'react'
import { dur, km, pace, parseDate, timeOfDay, todayISO } from '../lib/format'
import { errorText, useActivityAiReview, useActivityDetail, usePatchWorkout, useWorkout } from '../lib/queries'
import type { ActivityCard, Workout } from '../lib/types'
import { ActualVsPlanned } from './actual/ActualVsPlanned'
import { CoachReviewCard } from './actual/CoachReviewCard'
import { ComplianceCard } from './actual/ComplianceCard'
import { WorkoutResult } from './actual/WorkoutResult'
import { BottomSheet } from './BottomSheet'
import { CheckinSection } from './checkin/CheckinSummary'
import { EasyGuard } from './workout/EasyGuard'
import { GarminSendButton } from './workout/GarminSendButton'
import { ReviewIcon } from './Icons'
import { PhasePill } from './PhasePill'
import { Loading } from './States'
import { StepsList } from './StepsList'
import { WeatherBlock } from './weather/WeatherBlock'
import { WorkoutBar } from './WorkoutBar'
import { RunMapSection } from './map/RunMapSection'
import { RunShareButton } from './share/RunShareButton'
import { AdjustedChip } from './adjust/AdjustedChip'
import { RunReviewSection } from './review/RunReview'
import { useCoachLaunch } from './useCoachLaunch'

export { StepsList }

const longDate = (iso: string) =>
  parseDate(iso).toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })

export function FuelRows({ before, during, after }: { before: string; during: string; after: string }) {
  const rows = [
    ['Before', before],
    ['During', during],
    ['After', after],
  ].filter(([, text]) => text)
  if (!rows.length) return null
  return (
    <dl className="fuel">
      {rows.map(([label, text]) => (
        <div key={label} className="fuel-row">
          <dt>{label}</dt>
          <dd>{text}</dd>
        </div>
      ))}
    </dl>
  )
}

export function WorkoutSheet({ workout, onClose }: { workout: Workout | null; onClose: () => void }) {
  const launch = useCoachLaunch()
  const patch = usePatchWorkout()
  const [mode, setMode] = useState<'idle' | 'move' | 'skip'>('idle')
  const [moveTo, setMoveTo] = useState('')
  const [current, setCurrent] = useState<Workout | null>(null)

  // The calendar copy may predate the actual/compliance/review blocks; refetch on open.
  const fresh = useWorkout(workout?.id ?? null, workout ?? undefined).data
  const base = fresh && workout && fresh.id === workout.id ? fresh : workout
  // Show the server's answer after a move/skip without waiting for the calendar refetch.
  const w = current && base && current.id === base.id ? current : base
  const done = !!w?.actual

  const close = () => {
    setMode('idle')
    setCurrent(null)
    patch.reset()
    onClose()
  }

  return (
    <BottomSheet open={!!w} onClose={close} title={w ? undefined : ''} label="Workout">
      {w && (
        <div className="detail">
          <p className="muted">{longDate(w.date)}</p>
          <h2 className="detail-title">{w.title}</h2>
          <div className="detail-tags">
            {w.phase && <PhasePill kind={w.phase.kind} name={w.phase.name} />}
            {w.status !== 'planned' && <span className={`tag ${w.status === 'completed' ? 'tag-ok' : ''}`}>{w.status}</span>}
            {w.adjusted_by === 'checkin' && <span className="tag tag-adjusted">Adjusted by check-in</span>}
          </div>
          {w.auto_adjustment && w.status === 'planned' && <AdjustedChip adjustment={w.auto_adjustment} />}

          {done ? (
            <>
              <WorkoutResult workout={w} />
              {w.actual?.activity_id != null && <RunMapSection activityId={w.actual.activity_id} />}
            </>
          ) : (
            <>
              <WorkoutBar steps={w.steps} height={72} />
              <div className="stat-row">
                <div className="stat"><span className="stat-label">Duration</span><span className="stat-value">{dur(w.duration_s)}</span></div>
                <div className="stat"><span className="stat-label">Load</span><span className="stat-value">{Math.round(w.load)}</span></div>
                {w.target_zone && <div className="stat"><span className="stat-label">Target</span><span className="stat-value stat-value-sm">{w.target_zone}</span></div>}
              </div>
              {w.original_steps && w.adjusted_by === 'checkin' && (
                <div className="avp-bar">
                  <span className="avp-bar-label">Original</span>
                  <WorkoutBar steps={w.original_steps} height={32} compact />
                </div>
              )}
              {w.guard && <EasyGuard guard={w.guard} />}
            </>
          )}

          {done ? (
            <section className="detail-section">
              <h3>Planned steps</h3>
              <StepsList steps={w.steps} />
            </section>
          ) : (
            <StepsList steps={w.steps} />
          )}

          {w.purpose && (
            <section className="detail-section">
              <h3>Purpose</h3>
              <p>{w.purpose}</p>
            </section>
          )}
          {w.description && w.description !== w.purpose && (
            <section className="detail-section">
              <h3>How</h3>
              <p>{w.description}</p>
            </section>
          )}
          {w.fueling && (w.fueling.before || w.fueling.during || w.fueling.after) && (
            <section className="detail-section">
              <h3>Fueling</h3>
              <FuelRows {...w.fueling} />
            </section>
          )}

          {!done && w.status === 'planned' && <WeatherBlock date={w.date} durationS={w.duration_s} />}

          {mode === 'move' && (
            <div className="inline-form">
              <label className="field">
                <span className="field-label">Move to</span>
                <input type="date" min={todayISO()} value={moveTo} onChange={(e) => setMoveTo(e.target.value)} />
              </label>
              <div className="row-end">
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => setMode('idle')}>Cancel</button>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  disabled={!moveTo || patch.isPending}
                  onClick={() =>
                    patch.mutate({ id: w.id, date: moveTo }, { onSuccess: (data) => { setCurrent(data); setMode('idle') } })
                  }
                >
                  {patch.isPending ? 'Moving…' : 'Move'}
                </button>
              </div>
            </div>
          )}
          {mode === 'skip' && (
            <div className="inline-form">
              <p>Skip this workout? The coach will plan around it.</p>
              <div className="row-end">
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => setMode('idle')}>Keep it</button>
                <button
                  type="button"
                  className="btn btn-danger btn-sm"
                  disabled={patch.isPending}
                  onClick={() =>
                    patch.mutate({ id: w.id, status: 'skipped' }, { onSuccess: (data) => { setCurrent(data); setMode('idle') } })
                  }
                >
                  {patch.isPending ? 'Skipping…' : 'Skip workout'}
                </button>
              </div>
            </div>
          )}
          {patch.isError && <p className="bad small">{errorText(patch.error, 'Could not update the workout.')}</p>}

          {mode === 'idle' && w.status === 'planned' && w.date >= todayISO() && <GarminSendButton workout={w} />}

          {mode === 'idle' && (
            <div className="detail-actions">
              {w.status === 'planned' && (
                <>
                  <button type="button" className="btn btn-secondary" onClick={() => { setMoveTo(w.date); setMode('move') }}>Move</button>
                  <button type="button" className="btn btn-secondary" onClick={() => setMode('skip')}>Skip</button>
                </>
              )}
              {w.status === 'skipped' && (
                <button
                  type="button"
                  className="btn btn-secondary"
                  disabled={patch.isPending}
                  onClick={() => patch.mutate({ id: w.id, status: 'planned' }, { onSuccess: setCurrent })}
                >
                  Restore
                </button>
              )}
              <button type="button" className="btn btn-primary btn-grow" onClick={() => { close(); launch.guide(w) }}>
                <ReviewIcon size={18} /> Guide
              </button>
            </div>
          )}
        </div>
      )}
    </BottomSheet>
  )
}

export function ActivitySheet({ activity, onClose }: { activity: ActivityCard | null; onClose: () => void }) {
  const launch = useCoachLaunch()
  const detail = useActivityDetail(activity?.id ?? null)
  const aiReview = useActivityAiReview(activity?.id ?? null)
  const a = activity
  const segments = detail.data?.segments?.filter((s) => s.kind !== 'stop') ?? []

  return (
    <BottomSheet
      open={!!a}
      onClose={onClose}
      label="Activity"
      actions={a && /run|walk|hik/i.test(a.sport) ? <RunShareButton activity={a} avgHr={detail.data?.avg_hr} /> : undefined}
    >
      {a && (
        <div className="detail">
          <p className="muted">
            {longDate(a.start.slice(0, 10))} · {timeOfDay(a.start)}
          </p>
          <h2 className="detail-title">{a.name || a.sport}</h2>
          <p className="muted small">{a.device ? `${a.device} via Garmin` : 'via Garmin'}</p>
          {(a.unplanned || detail.data?.unplanned) && (
            <div className="detail-tags"><span className="tag tag-extra">Extra</span><span className="muted small">Not in the plan — still counts.</span></div>
          )}

          <WorkoutBar steps={a.steps} height={72} />

          <div className="stat-row">
            <div className="stat"><span className="stat-label">Duration</span><span className="stat-value">{dur(a.duration_s)}</span></div>
            <div className="stat"><span className="stat-label">Distance</span><span className="stat-value">{km(a.distance_m)}</span></div>
            <div className="stat"><span className="stat-label">Load</span><span className="stat-value">{Math.round(a.load)}</span></div>
          </div>

          {!detail.data?.actual && (
          <section className="detail-section">
            <h3>Run / walk truth</h3>
            <div className="truth">
              <div className="truth-bar" aria-hidden="true">
                <span className="truth-run" style={{ width: `${Math.round(a.run_fraction * 100)}%` }} />
              </div>
              <div className="stat-row">
                <div className="stat"><span className="stat-label">Run</span><span className="stat-value">{km(a.run_distance_m)}</span></div>
                <div className="stat"><span className="stat-label">Walk</span><span className="stat-value">{km(a.walk_distance_m)}</span></div>
                <div className="stat"><span className="stat-label">Longest run</span><span className="stat-value">{dur(a.longest_run_s)}</span></div>
              </div>
              <p className="muted small">{Math.round(a.run_fraction * 100)}% of the distance was running.</p>
            </div>
          </section>
          )}

          {detail.data?.actual && <ActualVsPlanned actual={detail.data.actual} />}
          {detail.data?.compliance && <ComplianceCard compliance={detail.data.compliance} />}
          {detail.data?.actual && (
            <CoachReviewCard
              review={detail.data.review}
              onGenerate={() => aiReview.mutate()}
              pending={aiReview.isPending}
              error={aiReview.isError ? errorText(aiReview.error, 'Could not get a review. Try again.') : undefined}
            />
          )}

          {/run/i.test(a.sport) && <RunReviewSection activityId={a.id} />}

          {!/strength|yoga|swim|indoor|treadmill/i.test(a.sport) && <RunMapSection activityId={a.id} />}

          {/run|walk|hik/i.test(a.sport) && (
            <CheckinSection key={a.id} activityId={a.id} entry={detail.data?.checkin} journalled={a.journalled} />
          )}

          {detail.isPending && <Loading label="Loading splits…" />}
          {detail.data && (
            <>
              <section className="detail-section">
                <h3>Heart rate</h3>
                <div className="stat-row">
                  <div className="stat"><span className="stat-label">Average</span><span className="stat-value">{detail.data.avg_hr ?? '--'}<small> bpm</small></span></div>
                  <div className="stat"><span className="stat-label">Max</span><span className="stat-value">{detail.data.max_hr ?? '--'}<small> bpm</small></span></div>
                  {detail.data.metrics?.hr_drift_percent != null && (
                    <div className="stat"><span className="stat-label">Drift</span><span className="stat-value">{detail.data.metrics.hr_drift_percent.toFixed(1)}%</span></div>
                  )}
                </div>
              </section>
              {segments.length > 0 && (
                <section className="detail-section">
                  <h3>Splits</h3>
                  <div className="table-wrap">
                    <table className="splits">
                      <thead>
                        <tr><th>#</th><th>Type</th><th>Time</th><th>Dist</th><th>Pace</th><th>HR</th></tr>
                      </thead>
                      <tbody>
                        {segments.map((s) => (
                          <tr key={s.index} className={`split-${s.kind}`}>
                            <td>{s.index + 1}</td>
                            <td>{s.kind}</td>
                            <td>{dur(s.duration_s)}</td>
                            <td>{(s.distance_m / 1000).toFixed(2)}</td>
                            <td>{pace(s.avg_pace_s_per_km)}</td>
                            <td>{s.hr_avg ?? '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              )}
            </>
          )}

          <div className="detail-actions">
            <button type="button" className="btn btn-primary btn-grow" onClick={() => { onClose(); launch.review(a) }}>
              <ReviewIcon size={18} /> {a.reviewed_thread_id ? 'Open review' : 'Review'}
            </button>
          </div>
        </div>
      )}
    </BottomSheet>
  )
}
