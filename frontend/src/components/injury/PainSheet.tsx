import { useState } from 'react'
import { errorText } from '../../lib/queries'
import { useReportPains, type PainBody, type PainLocation } from '../../lib/r13'
import { BottomSheet } from '../BottomSheet'
import { BodyMap, type PainSpot } from './BodyMap'

export const toPainBody = (p: PainSpot, extra: Partial<PainBody> = {}): PainBody => ({
  location: p.area as PainLocation,
  side: p.area === 'lower_back' ? 'center' : p.side,
  severity: p.severity,
  ...extra,
})

/** "Anything hurting?" — the daily (or any-time) pain check as a sheet. */
export function PainSheet({ open, onClose, activityId }: { open: boolean; onClose: () => void; activityId?: number | null }) {
  const [spots, setSpots] = useState<PainSpot[]>([])
  const report = useReportPains()
  const close = () => {
    setSpots([])
    report.reset()
    onClose()
  }
  const save = () =>
    report.mutate(spots.map((p) => toPainBody(p, activityId ? { activity_id: activityId } : {})), { onSuccess: close })
  return (
    <BottomSheet
      open={open}
      onClose={close}
      title="Anything hurting?"
      footer={
        <button type="button" className="btn btn-primary btn-block" disabled={!spots.length || report.isPending} onClick={save}>
          {report.isPending ? 'Saving…' : spots.length ? `Save ${spots.length === 1 ? 'it' : `${spots.length} spots`}` : 'Tap where it hurts'}
        </button>
      }
    >
      <div className="stack">
        <p className="muted small">Tap the body or the names below. It helps the plan keep you healthy — reports only ever make training easier.</p>
        <BodyMap value={spots} onChange={setSpots} />
        {report.isError && <p className="bad small">{errorText(report.error, 'Could not save.')}</p>}
      </div>
    </BottomSheet>
  )
}
