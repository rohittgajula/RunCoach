import { errorText } from '../../lib/queries'
import { useDeleteActivity } from '../../lib/r17lazy'
import { BottomSheet } from '../BottomSheet'
import { showToast } from '../GlobalToast'
import '../../styles/r17lazy.css'

/** R17: in-page confirm, then DELETE /activities/{id}/ and close the run sheet. */
export default function DeleteActivitySheet({
  open, onClose, onDeleted, activityId, isRun,
}: { open: boolean; onClose: () => void; onDeleted: () => void; activityId: number; isRun: boolean }) {
  const del = useDeleteActivity()
  const noun = isRun ? 'run' : 'activity'
  return (
    <BottomSheet open={open} onClose={onClose} title={`Delete this ${noun}?`}>
      <div className="stack">
        <p>Delete this {noun} from RunCoach? It stays in Garmin unless you delete it there.</p>
        <p className="muted">Its stats, review and PRs will be recalculated. You can re-import it later from Me → Deleted activities.</p>
        {del.isError && <p className="bad small">{errorText(del.error, 'Couldn’t delete. Try again.')}</p>}
        <div className="ill-foot">
          <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button
            type="button"
            className="btn btn-solid-bad"
            disabled={del.isPending}
            onClick={() => del.mutate(activityId, {
              onSuccess: () => {
                onClose()
                onDeleted()
                showToast(`${isRun ? 'Run' : 'Activity'} deleted`, { to: '/me/deleted', label: 'Undo in Deleted' })
              },
            })}
          >
            {del.isPending ? 'Deleting…' : `Delete ${noun}`}
          </button>
        </div>
      </div>
    </BottomSheet>
  )
}
