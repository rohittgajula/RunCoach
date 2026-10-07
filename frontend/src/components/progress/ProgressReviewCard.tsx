import { dateTime } from '../../lib/format'
import { errorText, useProgressReview } from '../../lib/queries'
import type { ProgressReview, ProgressWindow } from '../../lib/types'
import { SparkIcon } from '../Icons'
import { Markdown } from '../Markdown'

function List({ title, items, tone }: { title: string; items: string[]; tone: string }) {
  if (!items?.length) return null
  return (
    <div className={`review-list ${tone}`}>
      <p className="review-list-title">{title}</p>
      <ul>{items.map((t, i) => <li key={i}>{t}</li>)}</ul>
    </div>
  )
}

/** AI review of the comparison, cached per window per day on the server. */
export function ProgressReviewCard({ review, window }: { review: ProgressReview | null | undefined; window: ProgressWindow }) {
  const run = useProgressReview(window)
  const fresh = run.data && 'went_well' in run.data ? run.data : null
  const given = fresh ?? review
  // `review` comes back with status "none" and empty lists until one is generated.
  const r = given && (given.status === 'ready' || given.markdown || given.went_well?.length || given.improve?.length || given.check?.length) ? given : null
  const hasLists = !!r && (r.went_well?.length || r.improve?.length || r.check?.length)
  return (
    <div className="progress-review">
      <div className="card-head">
        <h3 className="habit-sub">Coach review</h3>
        <span className="tag tag-ai"><SparkIcon size={14} /> AI</span>
      </div>
      {r && (
        <>
          {hasLists ? (
            <>
              <List title="Went well" items={r.went_well} tone="is-good" />
              <List title="To improve" items={r.improve} tone="is-improve" />
              <List title="Worth checking" items={r.check} tone="is-check" />
            </>
          ) : (
            r.markdown && <Markdown text={r.markdown} />
          )}
          {r.generated_at && <p className="muted small">Updated {dateTime(r.generated_at)}</p>}
        </>
      )}
      {!r && !run.isPending && <p className="muted small">What went well, what to improve and what to check — read from the numbers above.</p>}
      {run.isPending && <p className="thinking">Comparing your runs…</p>}
      {run.isError && <p className="bad small">{errorText(run.error, 'Could not get a review. Try again.')}</p>}
      {!r && (
        <div className="row-end insight-actions">
          <button type="button" className="btn btn-primary" disabled={run.isPending} onClick={() => run.mutate()}>
            {run.isPending ? 'Reviewing…' : 'Review my progress'}
          </button>
        </div>
      )}
    </div>
  )
}
