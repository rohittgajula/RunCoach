import { useState } from 'react'
import type { Progress } from '../../lib/types'
import { MetricTable } from './MetricTable'

/** "All runs" or one distance bucket, so like is compared with like. */
export function BucketTable({ data }: { data: Progress }) {
  const [bucket, setBucket] = useState('all')
  const buckets = data.distance_buckets ?? []
  const chosen = buckets.find((b) => (b.bucket) === bucket)
  return (
    <div className="stack">
      {buckets.length > 0 && (
        <div className="chips-row chips-row-sm" role="radiogroup" aria-label="Distance">
          {[{ key: 'all', label: 'All runs' }, ...buckets.map((b) => ({ key: b.bucket, label: b.label }))].map((b) => (
            <button
              key={b.key}
              type="button"
              role="radio"
              aria-checked={bucket === b.key}
              className={`pill-btn ${bucket === b.key ? 'is-active' : ''}`}
              onClick={() => setBucket(b.key)}
            >
              {b.label}
            </button>
          ))}
        </div>
      )}
      {chosen && (chosen.current_n != null || chosen.previous_n != null) && (
        <p className="muted small">{chosen.current_n ?? 0} recent vs {chosen.previous_n ?? 0} earlier runs in this distance.</p>
      )}
      {chosen && !chosen.metrics.length ? (
        <p className="muted small">No recent runs in this distance yet.</p>
      ) : (
        <MetricTable metrics={chosen ? chosen.metrics : data.metrics} />
      )}
    </div>
  )
}
