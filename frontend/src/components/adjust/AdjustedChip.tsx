import { useState } from 'react'
import { dur, parseDate } from '../../lib/format'
import { errorText } from '../../lib/queries'
import { useUndoAdjustment, type Adjustment } from '../../lib/r13'
import { BottomSheet } from '../BottomSheet'
import { UndoIcon } from '../Icons'

const day = (iso: string) => parseDate(iso).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })

/**
 * R13 §1: "Adjusted: shortened to 20 min — your HR ran 8 bpm high yesterday" + Undo.
 * Tap the text for why (signals, before → after). Auto-adjust only ever makes a
 * session easier (or, after a run of good easy days, at most 5 % longer).
 */
export function AdjustedChip({ adjustment: a, compact = false }: { adjustment: Adjustment; compact?: boolean }) {
  const undo = useUndoAdjustment()
  const [open, setOpen] = useState(false)
  if (a.status !== 'applied') return null
  const stop = (e: React.MouseEvent) => e.stopPropagation()
  return (
    <div className={`adj-chip ${compact ? 'is-compact' : ''}`} onClick={stop}>
      <button type="button" className="adj-text" onClick={() => setOpen(true)} aria-label={`${a.chip}. Why?`}>
        {a.chip}
      </button>
      {a.undoable && (
        <button type="button" className="adj-undo" disabled={undo.isPending} onClick={() => undo.mutate(a.id)} aria-label="Undo this change and keep the original session">
          <UndoIcon size={16} /> {undo.isPending ? '…' : 'Undo'}
        </button>
      )}
      {undo.isError && <span className="bad small adj-err">{errorText(undo.error, 'Could not undo.')}</span>}
      <BottomSheet open={open} onClose={() => setOpen(false)} title="Why the plan changed">
        <div className="stack">
          <p>{a.reason}</p>
          <dl className="adj-diff">
            <div><dt>Was</dt><dd>{a.before.title} · {a.before.duration_s ? dur(a.before.duration_s) : '—'} · {day(a.before.date)}</dd></div>
            <div><dt>Now</dt><dd>{a.after.title} · {a.after.duration_s ? dur(a.after.duration_s) : '—'} · {day(a.after.date)}</dd></div>
          </dl>
          {a.signals.length > 0 && (
            <div>
              <p className="lbl">What we noticed</p>
              <ul className="adj-signals">{a.signals.map((s) => <li key={s.key}>{s.label}</li>)}</ul>
            </div>
          )}
          <p className="muted small">
            Auto-adjust only makes sessions easier when your body says so — it never adds hard work. Turn it off in Settings → Training days.
          </p>
          {a.undoable && (
            <button type="button" className="btn btn-secondary btn-block" disabled={undo.isPending} onClick={() => undo.mutate(a.id, { onSuccess: () => setOpen(false) })}>
              <UndoIcon size={16} /> Undo — keep the original session
            </button>
          )}
        </div>
      </BottomSheet>
    </div>
  )
}
