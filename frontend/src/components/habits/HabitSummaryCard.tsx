import { dateTime } from '../../lib/format'
import { errorText, useHabitSummaryText } from '../../lib/queries'
import type { HabitSummaryText } from '../../lib/types'
import { SparkIcon } from '../Icons'
import { Markdown } from '../Markdown'

/** AI explanation of the habit numbers, on demand (cached per day on the server). */
export function HabitSummaryCard({ summary, range }: { summary: HabitSummaryText | null; range: string }) {
  const generate = useHabitSummaryText(range)
  const ready = summary?.status === 'ready' && !!summary.markdown
  return (
    <div className="habit-ai">
      <div className="card-head">
        <h3 className="habit-sub">What the coach sees</h3>
        <span className="tag tag-ai"><SparkIcon size={14} /> AI</span>
      </div>
      {ready && summary && (
        <>
          <Markdown text={summary.markdown} />
          {summary.generated_at && <p className="muted small">Updated {dateTime(summary.generated_at)}</p>}
        </>
      )}
      {!ready && !generate.isPending && <p className="muted small">A plain-words read of your habit logs next to your sleep, HRV and runs. Uses only totals and averages.</p>}
      {generate.isPending && <p className="thinking">Reading your logs…</p>}
      {generate.isError && <p className="bad small">{errorText(generate.error, 'Could not generate it. Try again.')}</p>}
      <div className="row-end insight-actions">
        <button type="button" className={`btn ${ready ? 'btn-secondary btn-sm' : 'btn-primary'}`} disabled={generate.isPending} onClick={() => generate.mutate(ready)}>
          {generate.isPending ? 'Generating…' : ready ? 'Refresh' : 'Generate'}
        </button>
      </div>
    </div>
  )
}
