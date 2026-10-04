import { useState } from 'react'
import { errorText, useSkipCheckin, useSubmitCheckin } from '../../lib/queries'
import type { Breathing, CheckinEntry, Legs } from '../../lib/types'
import { BREATHING, LEGS, rpeLabel } from './checkinUtil'
import { ChipChoice } from './ChipChoice'
import { PainPicker, type PainState } from './PainPicker'

/**
 * "How did it feel?" — sensible defaults so a normal run is one slide and Done (~10 s).
 * `onCancel` replaces Skip with a plain Cancel (used inline in the activity sheet).
 */
export function CheckinForm({
  activityId, onDone, onSkipped, onCancel,
}: {
  activityId: number
  onDone: (entry: CheckinEntry) => void
  onSkipped?: () => void
  onCancel?: () => void
}) {
  const submit = useSubmitCheckin()
  const skip = useSkipCheckin()
  const [rpe, setRpe] = useState(4)
  const [legs, setLegs] = useState<Legs>('ok')
  const [breathing, setBreathing] = useState<Breathing>('ok')
  const [pain, setPain] = useState<PainState>({ on: false, where: '', level: 3 })
  const [note, setNote] = useState('')
  const busy = submit.isPending || skip.isPending
  const painIncomplete = pain.on && !pain.where

  const done = () =>
    submit.mutate(
      {
        activityId,
        body: { rpe, legs, breathing, pain: pain.on ? { where: pain.where, level: pain.level } : null, note: note.trim() },
      },
      { onSuccess: onDone },
    )

  const error = submit.error ?? skip.error
  return (
    <div className="checkin">
      <label className="ci-range ci-rpe">
        <span className="ci-range-head">
          <span className="ci-label">Effort</span>
          <span><b className="ci-rpe-num">{rpe}</b> · {rpeLabel(rpe)}</span>
        </span>
        <input
          type="range" min={1} max={10} step={1} value={rpe} aria-label="Effort, 1 to 10"
          onChange={(e) => setRpe(Number(e.target.value))}
          style={{ ['--fill' as string]: `${((rpe - 1) / 9) * 100}%` }}
        />
        <span className="ci-scale" aria-hidden="true">
          <span>Very easy</span><span>Moderate</span><span>Max</span>
        </span>
      </label>
      <ChipChoice label="Legs" options={LEGS} value={legs} onChange={setLegs} />
      <ChipChoice label="Breathing" options={BREATHING} value={breathing} onChange={setBreathing} />
      <PainPicker value={pain} onChange={setPain} />
      <textarea
        className="ci-note" rows={2} placeholder="Anything else? (optional)"
        value={note} onChange={(e) => setNote(e.target.value)}
      />
      {error && <p className="bad small">{errorText(error, 'Could not save the check-in.')}</p>}
      <div className="ci-actions">
        {onCancel ? (
          <button type="button" className="btn btn-secondary" onClick={onCancel} disabled={busy}>Cancel</button>
        ) : (
          <button
            type="button" className="btn btn-secondary" disabled={busy}
            onClick={() => skip.mutate({ activityId, reason: 'skipped' }, { onSuccess: () => onSkipped?.() })}
          >
            {skip.isPending ? 'Skipping…' : 'Skip'}
          </button>
        )}
        <button type="button" className="btn btn-primary btn-grow" onClick={done} disabled={busy || painIncomplete}>
          {submit.isPending ? 'Saving…' : painIncomplete ? 'Where does it hurt?' : 'Done'}
        </button>
      </div>
    </div>
  )
}
