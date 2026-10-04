import { dateTime } from '../../lib/format'
import { errorText, useInsightsSummary } from '../../lib/queries'
import type { InsightRange, Insights } from '../../lib/types'
import { SparkIcon } from '../Icons'
import { Markdown } from '../Markdown'
import { InsightCard } from './Tile'

export function FocusCard({ focus, hasRuns }: { focus: Insights['focus']; hasRuns: boolean }) {
  return (
    <InsightCard title="Focus next">
      {focus.length ? (
        <ol className="focus">
          {focus.map((item, i) => (
            <li key={i} className="focus-item">
              <span className="focus-num">{i + 1}</span>
              <div className="grow">
                <p className="focus-title">{item.title}</p>
                <p className="muted small">{item.why}</p>
                <p className="focus-how">{item.how}</p>
              </div>
            </li>
          ))}
        </ol>
      ) : (
        <p className="muted">
          {hasRuns ? 'Nothing stands out — keep doing what you’re doing.' : 'No runs in this range yet — sync a few and the coach will pick what to work on.'}
        </p>
      )}
    </InsightCard>
  )
}

export function LoadCard({ load, onOpen }: { load: Insights['load']; onOpen: () => void }) {
  if (!load) return null
  const v = (x: number | null) => (x == null ? '--' : Math.round(x))
  return (
    <section className="card insight is-tappable" onClick={onOpen} role="button" tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && onOpen()}>
      <div className="card-head">
        <h2 className="card-title">Training load</h2>
        {load.status && <span className="tag">{load.status.replace(/_/g, ' ')}</span>}
      </div>
      <dl className="kv kv-row">
        <div><dt>Fitness</dt><dd>{v(load.fitness)}</dd></div>
        <div><dt>Fatigue</dt><dd>{v(load.fatigue)}</dd></div>
        <div><dt>Form</dt><dd>{v(load.form)}</dd></div>
        {load.acwr != null && <div><dt>ACWR</dt><dd>{load.acwr.toFixed(2)}</dd></div>}
      </dl>
    </section>
  )
}

/** "Are you running well?" — AI paragraph over the numbers above, generated on demand. */
export function SummaryCard({ summary, range }: { summary: Insights['summary']; range: InsightRange }) {
  const generate = useInsightsSummary(range)
  const ready = summary?.status === 'ready' && !!summary.markdown
  return (
    <InsightCard title="Are you running well?" aside={<span className="tag tag-ai"><SparkIcon size={14} /> AI</span>}>
      {ready && summary && (
        <>
          <Markdown text={summary.markdown} />
          {summary.generated_at && <p className="muted small">Updated {dateTime(summary.generated_at)}</p>}
        </>
      )}
      {!ready && !generate.isPending && (
        <p className="muted small">An overview of the numbers above in plain words — what’s working and what to change. Uses only your data.</p>
      )}
      {generate.isPending && <p className="thinking">Reading your last weeks…</p>}
      {generate.isError && <p className="bad small">{errorText(generate.error, 'Could not generate the overview. Try again.')}</p>}
      <div className="row-end insight-actions">
        <button type="button" className={`btn ${ready ? 'btn-secondary btn-sm' : 'btn-primary'}`} disabled={generate.isPending} onClick={() => generate.mutate(ready)}>
          {generate.isPending ? 'Generating…' : ready ? 'Refresh' : 'Generate'}
        </button>
      </div>
    </InsightCard>
  )
}
