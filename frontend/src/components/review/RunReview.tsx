import { useState } from 'react'
import { pace } from '../../lib/format'
import { errorText } from '../../lib/queries'
import { useRecentReview, useRunReview, useRunReviewAi, type RunReview, type RunReviewMetric } from '../../lib/r13'
import { Bullets } from '../Bullets'
import { CloseIcon, SparkIcon } from '../Icons'
import { CardHead, Delta } from '../Kit'
import { Markdown } from '../Markdown'
import { InfoButton } from '../health/InfoButton'
import type { GlossaryKey } from '../health/glossary'

const INFO: Record<string, GlossaryKey> = { hr_at_pace: 'hr_at_pace', hr_drift: 'hr_drift', cadence: 'cadence', run_fraction: 'run_fraction' }
const BUCKET: Record<string, string> = { lt2: 'under 2 km', '2to5': '2–5 km', '5to8': '5–8 km', '8plus': '8 km+' }

function fmt(m: RunReviewMetric, v: number | null): string {
  if (v == null) return '--'
  if (m.unit === 's/km') return pace(v)
  if (m.unit === '%') return `${Math.round(v)}%`
  return `${Math.round(v * 10) / 10}${m.unit && m.unit !== '%' ? ` ${m.unit}` : ''}`
}
function fmtDelta(m: RunReviewMetric, v: number): string {
  if (m.unit === 's/km') return `${Math.round(v)} s`
  if (m.unit === '%') return `${Math.round(v * 10) / 10}%`
  return `${Math.round(v * 10) / 10}`
}

/** This run vs similar past runs, three lists, optional AI paragraph. */
export function RunReviewBody({ review: r }: { review: RunReview }) {
  const ai = useRunReviewAi(r.activity_id)
  const aiText = r.ai?.status === 'ready' ? r.ai.markdown : ''
  return (
    <div className="stack">
      {r.metrics.length > 0 && (
        <div className="table-wrap">
          <table className="review-table">
            <thead>
              <tr><th>Metric</th><th>This run</th><th>Usual</th><th aria-label="Change" /></tr>
            </thead>
            <tbody>
              {r.metrics.map((m) => (
                <tr key={m.key}>
                  <td><span className="review-metric">{m.label}{INFO[m.key] && <InfoButton k={INFO[m.key]} />}</span></td>
                  <td><b>{fmt(m, m.this_run)}</b></td>
                  <td className="muted">{fmt(m, m.typical)}</td>
                  <td>
                    {m.delta != null && (
                      <Delta
                        value={m.delta}
                        // `better` is "this run is better" — express it as the direction that is good.
                        better={m.better == null ? null : (m.delta > 0) === m.better ? 'higher' : 'lower'}
                        format={(v) => fmtDelta(m, v)}
                      />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {r.went_well.length > 0 && (
        <div><span className="lbl">Went well</span><Bullets items={r.went_well.map((t) => ({ tone: 'good', text: t }))} /></div>
      )}
      {r.to_improve.length > 0 && (
        <div><span className="lbl">To improve</span><Bullets items={r.to_improve.map((t) => ({ tone: 'bad', text: t }))} /></div>
      )}
      {r.next_time.length > 0 && (
        <div><span className="lbl">Next time</span><Bullets items={r.next_time.map((t) => ({ tone: 'neutral', text: t }))} /></div>
      )}
      {aiText ? (
        <div className="review-ai">
          <span className="tag tag-ai"><SparkIcon size={14} /> Coach</span>
          <Markdown text={aiText} />
        </div>
      ) : (
        <div className="row-end">
          {ai.isError && <span className="muted small grow">{errorText(ai.error, 'The coach is busy right now.')}</span>}
          <button type="button" className="btn btn-secondary btn-sm" disabled={ai.isPending} onClick={() => ai.mutate(false)}>
            <SparkIcon size={14} /> {ai.isPending ? 'Writing…' : 'Coach’s take'}
          </button>
        </div>
      )}
    </div>
  )
}

const comparedText = (r: RunReview) =>
  r.compared_with > 0
    ? `Compared with your last ${r.compared_with} similar ${r.compared_with === 1 ? 'run' : 'runs'}${r.bucket ? ` (${BUCKET[r.bucket] ?? r.bucket})` : ''}.`
    : 'No similar past runs yet — this one becomes the baseline.'

/** Run sheet section. */
export function RunReviewSection({ activityId }: { activityId: number }) {
  const q = useRunReview(activityId)
  const r = q.data
  if (!r || !r.available) return null
  return (
    <section className="detail-section">
      <h3>Post-run review</h3>
      <p className="muted small">{comparedText(r)}</p>
      <RunReviewBody review={r} />
    </section>
  )
}

const hiddenKey = (id: number) => `rc.review-hidden.${id}`

/** Today: the newest review from the last 24 h. */
export function RecentReviewCard() {
  const q = useRecentReview()
  const r = q.data
  const [hiddenNow, setHidden] = useState(false)
  const [open, setOpen] = useState(false)
  if (!r || !r.available || hiddenNow) return null
  try {
    if (localStorage.getItem(hiddenKey(r.activity_id)) === '1') return null
  } catch { /* storage blocked: just show it */ }
  const hide = () => {
    try { localStorage.setItem(hiddenKey(r.activity_id), '1') } catch { /* ignore */ }
    setHidden(true)
  }
  const first = r.went_well[0] ?? r.to_improve[0] ?? ''
  return (
    <section className="card review-card" aria-label="Post-run review">
      <CardHead
        title="Your run, reviewed"
        sub={comparedText(r)}
        aside={<button type="button" className="chip review-close" aria-label="Hide this review" onClick={hide}><CloseIcon /></button>}
      />
      {open ? <RunReviewBody review={r} /> : (
        <>
          {first && <p className="review-lead">{first}</p>}
          {r.next_time[0] && <p className="small"><b>Next time:</b> {r.next_time[0]}</p>}
        </>
      )}
      <button type="button" className="btn btn-secondary btn-block" onClick={() => setOpen(!open)}>
        {open ? 'Show less' : 'See the full review'}
      </button>
    </section>
  )
}
