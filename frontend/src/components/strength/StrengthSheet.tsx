import { todayISO } from '../../lib/format'
import { errorText } from '../../lib/queries'
import { usePatchStrength, useStrengthToWatch, type Strength, type StrengthExercise } from '../../lib/r13'
import { BottomSheet } from '../BottomSheet'
import { CheckIcon, WatchIcon } from '../Icons'
import { InfoButton } from '../health/InfoButton'
import { EXERCISES, Figure } from '../guides/StrengthGuide'

const dose = (e: StrengthExercise) => {
  const each = e.reps != null ? `${e.reps}` : e.seconds != null ? `${e.seconds} s` : ''
  return `${e.sets} × ${each}${e.per_side ? ' / side' : ''}`
}

/** R13 §4: the session's exercises (Guides figures), done / skip, send to watch. */
export default function StrengthSheet({ session, onClose }: { session: Strength; onClose: () => void }) {
  const patch = usePatchStrength()
  const watch = useStrengthToWatch()
  const s = session
  const future = s.date >= todayISO()
  const canWatch = s.can_send_to_watch && s.status === 'planned' && future
  const error = patch.error ?? watch.error

  return (
    <BottomSheet
      open
      onClose={onClose}
      title="Strength"
      footer={
        <div className="strength-actions">
          {s.status === 'completed' ? (
            <button type="button" className="btn btn-secondary btn-grow" disabled={patch.isPending} onClick={() => patch.mutate({ id: s.id, status: 'planned' })}>
              Not done
            </button>
          ) : (
            <>
              {s.status !== 'skipped' && (
                <button type="button" className="btn btn-secondary" disabled={patch.isPending} onClick={() => patch.mutate({ id: s.id, status: 'skipped' }, { onSuccess: onClose })}>
                  Skip
                </button>
              )}
              <button type="button" className="btn btn-primary btn-grow" disabled={patch.isPending} onClick={() => patch.mutate({ id: s.id, status: 'completed' }, { onSuccess: onClose })}>
                <CheckIcon size={18} /> {patch.isPending ? 'Saving…' : 'Done'}
              </button>
            </>
          )}
        </div>
      }
    >
      <div className="stack strength-sheet">
        <div>
          <p className="muted small">
            {new Date(`${s.date}T00:00:00`).toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'short' })}
          </p>
          <h2 className="detail-title">{s.title}</h2>
          <p className="muted small">
            About {Math.round(s.duration_s / 60)} min · level {s.level}
            <InfoButton title="Strength level">
              <p>Sessions get a little harder every two weeks — a few more reps or one more set — as long as you’ve been doing them.</p>
              <p>Strength work for the calves, hips and core makes runners more injury-resistant. Stop a set when your form slips; it should never hurt.</p>
            </InfoButton>
          </p>
          {s.auto_completed && <p className="muted small">Marked done from your Garmin strength activity.</p>}
        </div>
        <ol className="strength-list">
          {s.exercises.map((e, i) => {
            const fig = EXERCISES.find((x) => x.key === e.key)
            return (
              <li key={`${e.key}-${i}`} className="strength-ex">
                {fig ? <Figure pose={fig.pose} label={e.name} /> : <span className="ex-figure" aria-hidden="true" />}
                <div className="grow">
                  <b>{e.name}</b>
                  <span className="strength-dose">{dose(e)}{e.rest_s ? <small> · rest {e.rest_s} s</small> : null}</span>
                  {e.cue && <span className="muted small block">{e.cue}</span>}
                </div>
              </li>
            )
          })}
        </ol>
        {canWatch && (
          <button
            type="button"
            className="btn btn-secondary btn-block strength-watch"
            disabled={watch.isPending}
            onClick={() => watch.mutate({ id: s.id, remove: s.garmin_status === 'synced' })}
          >
            <WatchIcon size={18} />
            {watch.isPending ? 'Sending…' : watch.isSuccess ? 'Queued — syncs on your next watch sync' : s.garmin_status === 'synced' ? 'Remove from watch' : s.garmin_status === 'changed' ? 'Update on watch' : 'Send to watch'}
          </button>
        )}
        {error && <p className="bad small">{errorText(error, 'Could not save that.')}</p>}
        <p className="muted small">Easy effort, good form. Skip it the day before a long or hard run — the plan never puts it there.</p>
      </div>
    </BottomSheet>
  )
}
