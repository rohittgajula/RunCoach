import { useState } from 'react'
import { errorText, useSkipCheckin, useSubmitCheckin } from '../../lib/queries'
import type { Breathing, CheckinEntry, Legs } from '../../lib/types'
import { BREATHING, LEGS, rpeLabel } from './checkinUtil'
import { ChipChoice } from './ChipChoice'
import { useReportPains } from '../../lib/r13'
import { BodyMap, type PainSpot } from '../injury/BodyMap'
import { toPainBody } from '../injury/PainSheet'

/** Old check-in `pain` field (R7): area chips + 1–10. Kept so older reads still work. */
const LEGACY_AREA: Record<string, string> = { lower_back: 'back', hamstring: 'other', quad: 'other' }
const LEGACY_LEVEL = { 1: 3, 2: 5, 3: 8 } as const

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
  const [painOn, setPainOn] = useState(false)
  const [spots, setSpots] = useState<PainSpot[]>([])
  const [note, setNote] = useState('')
  const pains = useReportPains()
  const busy = submit.isPending || skip.isPending || pains.isPending
  const painIncomplete = painOn && !spots.length

  const done = () => {
    const worst = painOn ? [...spots].sort((a, b) => b.severity - a.severity)[0] : undefined
    submit.mutate(
      {
        activityId,
        body: {
          rpe, legs, breathing, note: note.trim(),
          pain: worst ? { where: LEGACY_AREA[worst.area] ?? worst.area, level: LEGACY_LEVEL[worst.severity] } : null,
        },
      },
      {
        onSuccess: (entry) => {
          // R13 §3: each spot becomes a PainReport linked to this run (feeds injury watch).
          if (painOn && spots.length) {
            pains.mutate(spots.map((p) => toPainBody(p, { activity_id: activityId })), { onSettled: () => onDone(entry) })
          } else onDone(entry)
        },
      },
    )
  }

  const error = submit.error ?? skip.error ?? pains.error
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
      <div className="ci-block">
        <div className="switch-row">
          <span className="ci-label">Anything hurting?</span>
          <button
            type="button" role="switch" aria-checked={painOn} aria-label="Anything hurting?"
            className={`switch ${painOn ? 'is-on is-bad' : ''}`}
            onClick={() => setPainOn(!painOn)}
          />
        </div>
        {painOn && <BodyMap value={spots} onChange={setSpots} />}
      </div>
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
