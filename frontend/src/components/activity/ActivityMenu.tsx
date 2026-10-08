import { useState } from 'react'
import { BottomSheet } from '../BottomSheet'
import { TrashIcon } from '../Icons'
import DeleteActivitySheet from './DeleteActivitySheet'

/** R17: run / activity sheet ⋯ menu → "Delete activity" → confirm (this whole chunk is lazy). */
export default function ActivityMenu({ open, onClose, activityId, sport, onDeleted }: { open: boolean; onClose: () => void; activityId: number; sport: string; onDeleted: () => void }) {
  const [confirm, setConfirm] = useState(false)
  const isRun = /run/i.test(sport)
  return (
    <>
      <BottomSheet open={open} onClose={onClose} title={isRun ? 'This run' : 'This activity'}>
        <div className="menu-list">
          <button
            type="button"
            className="row row-danger"
            onClick={() => { onClose(); setConfirm(true) }}
          >
            <span className="row-icon" aria-hidden="true"><TrashIcon size={20} /></span>
            <span className="grow row-text">
              <span className="row-title">Delete activity</span>
              <span className="row-sub">Remove it from RunCoach (not from Garmin)</span>
            </span>
          </button>
        </div>
      </BottomSheet>
      <DeleteActivitySheet open={confirm} onClose={() => setConfirm(false)} onDeleted={onDeleted} activityId={activityId} isRun={isRun} />
    </>
  )
}
