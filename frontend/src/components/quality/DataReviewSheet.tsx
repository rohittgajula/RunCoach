import { useState } from 'react'
import { parseDate } from '../../lib/format'
import { errorText } from '../../lib/queries'
import { useDataReview, type ReviewDecision, type ReviewItem } from '../../lib/r17'
import { useDecideReview, useQualitySeries } from '../../lib/r17lazy'
import { BottomSheet } from '../BottomSheet'
import { Empty, Skeleton } from '../States'
import { MiniSeries } from './HrMaskChart'
import '../../styles/r17lazy.css'

const day = (iso: string) => parseDate(iso.slice(0, 10)).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })

/** The run's heart rate, bucketed down, fixed parts shaded. */
function RunMini({ id }: { id: number }) {
  const q = useQualitySeries(id)
  const pts = q.data?.series ?? []
  if (pts.length < 2) return null
  const step = Math.max(1, Math.floor(pts.length / 60))
  const series = pts.filter((_, i) => i % step === 0).map((p) => ({ v: p.hr_raw ?? p.hr_clean, flagged: p.fixed }))
  return <MiniSeries series={series} />
}

function IllnessDays({ days }: { days: Array<{ date: string; decision: string | null; has_data: boolean }> }) {
  return (
    <div className="rv-days" aria-label={`${days.length} days`}>
      {days.map((d) => (
        <span key={d.date} className={`rv-day ${d.decision === 'exclude' ? 'is-out' : ''} ${d.has_data ? '' : 'is-empty'}`} title={day(d.date)}>
          {parseDate(d.date).getDate()}
        </span>
      ))}
    </div>
  )
}

function decisionText(it: ReviewItem): string {
  if (it.kind === 'deleted_in_garmin') return it.decision === 'remove' ? 'Removed by you' : it.decision === 'keep' ? 'Kept' : ''
  if (it.decision === 'exclude') return 'Excluded by you'
  if (it.decision === 'mixed') return 'Some days excluded'
  if (it.decision === 'include') return 'Kept in trends'
  if (it.kind === 'run' && it.use_choice) return it.use_choice === 'raw' ? 'Using raw HR' : 'Using cleaned HR'
  return 'Not decided — still counted'
}

function Item({ it, decide, busy, reviewed }: { it: ReviewItem; decide: (d: ReviewDecision[]) => void; busy: boolean; reviewed: boolean }) {
  const head = (
    <div className="rv-head">
      <span className="rv-title grow">{it.kind === 'illness' ? it.label : it.title}</span>
      <span className="muted small">{it.kind === 'illness' ? `${day(it.start)} – ${day(it.end)}` : day(it.date)}</span>
    </div>
  )
  if (reviewed) {
    const undo: ReviewDecision | null = it.kind === 'run' ? { kind: 'run', id: it.id, decision: null, use: null }
      : it.kind === 'illness' ? { kind: 'illness', id: it.id, decision: null } : null
    return (
      <li className="rv-item">
        {head}
        <p className="rv-why">{it.text}</p>
        <div className="rv-actions">
          <span className={`tone-chip ${it.decision === 'exclude' || it.decision === 'remove' ? 'is-flat' : 'is-info'}`}>{decisionText(it)}</span>
          {undo && <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => decide([undo])}>Undo</button>}
        </div>
      </li>
    )
  }
  return (
    <li className="rv-item">
      {head}
      <p className="rv-why">{it.text}</p>
      {it.kind === 'run' && <RunMini id={it.id} />}
      {it.kind === 'illness' && <IllnessDays days={it.days} />}
      {it.kind === 'deleted_in_garmin' ? (
        <div className="rv-actions">
          <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => decide([{ kind: 'deleted_in_garmin', id: it.id, decision: 'keep' }])}>Keep</button>
          <button type="button" className="btn btn-solid-bad" disabled={busy} onClick={() => decide([{ kind: 'deleted_in_garmin', id: it.id, decision: 'remove' }])}>Remove here too</button>
        </div>
      ) : (
        <>
          {(it.kind === 'illness' || it.suggestion === 'exclude' || it.decision) && (
            <div className="rv-actions">
              <button type="button" className="btn btn-secondary" disabled={busy}
                onClick={() => decide([it.kind === 'run' ? { kind: 'run', id: it.id, decision: 'include' } : { kind: 'illness', id: it.id, decision: 'include' }])}>
                Keep
              </button>
              <button type="button" className="btn btn-secondary" disabled={busy}
                onClick={() => decide([it.kind === 'run' ? { kind: 'run', id: it.id, decision: 'exclude' } : { kind: 'illness', id: it.id, decision: 'exclude' }])}>
                Exclude
              </button>
            </div>
          )}
          {it.kind === 'run' && it.use_suggestion === 'cleaned' && !it.use_choice && (
            <div className="rv-actions">
              <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => decide([{ kind: 'run', id: it.id, use: 'cleaned' }])}>Use cleaned HR</button>
              <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => decide([{ kind: 'run', id: it.id, use: 'raw' }])}>Use raw HR</button>
            </div>
          )}
        </>
      )}
    </li>
  )
}

/**
 * R17 data review: each suggestion with why + a mini chart, Keep / Exclude per item,
 * Keep all / Exclude all; "Reviewed" lists every decision with Undo. Nothing is hidden
 * from any chart unless the athlete chose Exclude.
 */
export default function DataReviewSheet({ open, onClose, initialTab = 'pending' }: { open: boolean; onClose: () => void; initialTab?: 'pending' | 'reviewed' }) {
  const [tab, setTab] = useState(initialTab)
  const pending = useDataReview(false, open)
  const all = useDataReview(true, open && tab === 'reviewed')
  const decide = useDecideReview()
  const items = (tab === 'pending' ? pending.data?.items.filter((i) => i.pending) : all.data?.items.filter((i) => !i.pending)) ?? []
  const loading = tab === 'pending' ? pending.isPending : all.isPending
  const run = (d: ReviewDecision[]) => decide.mutate(d)
  const bulkable = items.filter((i) => i.kind !== 'deleted_in_garmin')
  const keepAll = (): ReviewDecision[] => items.map((i) =>
    i.kind === 'run' ? { kind: 'run', id: i.id, decision: 'include', ...(i.use_suggestion && !i.use_choice ? { use: 'cleaned' as const } : {}) }
      : i.kind === 'illness' ? { kind: 'illness', id: i.id, decision: 'include' }
        : { kind: 'deleted_in_garmin', id: i.id, decision: 'keep' })
  const excludeAll = (): ReviewDecision[] => bulkable.map((i) =>
    i.kind === 'run' ? { kind: 'run', id: i.id, decision: 'exclude' } : { kind: 'illness', id: i.id, decision: 'exclude' })

  return (
    <BottomSheet open={open} onClose={onClose} title="Review data">
      <div className="stack">
        <div className="seg2" role="tablist" aria-label="Review data">
          <button type="button" role="tab" aria-selected={tab === 'pending'} aria-pressed={tab === 'pending'} onClick={() => setTab('pending')}>
            To review{pending.data?.pending ? ` · ${pending.data.pending}` : ''}
          </button>
          <button type="button" role="tab" aria-selected={tab === 'reviewed'} aria-pressed={tab === 'reviewed'} onClick={() => setTab('reviewed')}>Reviewed</button>
        </div>
        {tab === 'pending' && (
          <p className="muted small">Some readings may be off — a sick week, a wrist sensor slipping. Everything still counts until you decide. Sometimes the data is right.</p>
        )}
        {loading && <Skeleton lines={4} />}
        {!loading && !items.length && (
          <Empty title={tab === 'pending' ? 'Nothing to review' : 'No decisions yet'}>
            {tab === 'pending' ? 'All your runs and days count as they are.' : 'Runs or days you keep or exclude show up here, and you can undo them.'}
          </Empty>
        )}
        {tab === 'pending' && items.length > 1 && (
          <div className="rv-all">
            <button type="button" className="btn btn-secondary" disabled={decide.isPending} onClick={() => run(keepAll())}>Keep all</button>
            {bulkable.length > 0 && <button type="button" className="btn btn-secondary" disabled={decide.isPending} onClick={() => run(excludeAll())}>Exclude all</button>}
          </div>
        )}
        {decide.isError && <p className="bad small">{errorText(decide.error, 'Couldn’t save. Try again.')}</p>}
        <ul className="rv-list">
          {items.map((it) => <Item key={`${it.kind}-${it.id}`} it={it} decide={run} busy={decide.isPending} reviewed={tab === 'reviewed'} />)}
        </ul>
      </div>
    </BottomSheet>
  )
}
