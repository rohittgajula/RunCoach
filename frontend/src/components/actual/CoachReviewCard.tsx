import type { CoachReview } from '../../lib/types'
import { SparkIcon } from '../Icons'
import { Markdown } from '../Markdown'

/**
 * "Coach review" — the AI reading of compliance + metrics. Lazily generated: until it
 * exists we show a button (when the caller can generate one) instead of an empty card.
 */
export function CoachReviewCard({
  review, onGenerate, pending = false, error,
}: {
  review: CoachReview | null | undefined
  onGenerate?: () => void
  pending?: boolean
  error?: string
}) {
  const ready = review?.status === 'ready'
  if (!ready && !onGenerate) return null
  return (
    <section className="card review-card">
      <div className="card-head">
        <h3 className="card-title">Coach review</h3>
        <span className="tag tag-ai"><SparkIcon size={14} /> AI</span>
      </div>
      {ready && review ? (
        <div className="stack">
          {review.summary_md && <Markdown text={review.summary_md} />}
          {review.went_well.length > 0 && (
            <div className="review-list">
              <h4 className="review-list-title review-good">Went well</h4>
              <ul>{review.went_well.map((item, i) => <li key={i}>{item}</li>)}</ul>
            </div>
          )}
          {review.to_improve.length > 0 && (
            <div className="review-list">
              <h4 className="review-list-title review-improve">To improve</h4>
              <ul>{review.to_improve.map((item, i) => <li key={i}>{item}</li>)}</ul>
            </div>
          )}
        </div>
      ) : (
        <div className="stack">
          <p className="muted small">
            {pending
              ? 'Reading your run against the plan… this takes a few seconds.'
              : 'A short read of how this run went against the plan, and what to change next time.'}
          </p>
          {error && <p className="bad small">{error}</p>}
          <button type="button" className="btn btn-primary" disabled={pending} onClick={onGenerate}>
            {pending ? <><span className="spinner spinner-inv" aria-hidden="true" /> Reviewing…</> : 'Get review'}
          </button>
        </div>
      )}
    </section>
  )
}
