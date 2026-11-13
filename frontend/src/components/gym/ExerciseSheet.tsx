/**
 * One exercise, opened.
 *
 * The card in the list has to fit six of these on a screen, so its figure is
 * small and its text is a single cue. That is the right size for a move you
 * already know and the wrong size for one you have never done — which, on a
 * first gym programme, is all of them.
 *
 * So the card becomes a button and this is what it opens: the same figure at
 * the size you can actually copy, the cue, the reason the move is in the
 * programme at all, and for a lift, where it sits on its ladder and what
 * earns the next rung. Nothing here is new information; it is the information
 * the card had to leave out.
 */

import { BottomSheet } from '../BottomSheet'
import { ExerciseFigure } from './ExerciseFigure'

export type SheetExercise = {
  key: string
  pattern: string
  name: string
  sets: number
  reps: number | null
  seconds: number | null
  per_side: boolean
  rest_s: number
  load: string
  cue: string
  why: string
  level: number
  max_level: number
  ceiling: number
  at_ceiling: boolean
  graduate_when: string
  is_warmup?: boolean
}

const dose = (e: SheetExercise): string => {
  const amount = e.reps != null ? `${e.reps}` : `${e.seconds}s`
  return `${e.sets} × ${amount}${e.per_side ? ' a side' : ''}`
}

export function ExerciseSheet({
  exercise, onClose,
}: { exercise: SheetExercise | null; onClose: () => void }) {
  return (
    <BottomSheet
      open={!!exercise}
      onClose={onClose}
      title={exercise?.name}
      label="Exercise"
    >
      {exercise && (
        <div className="exsheet">
          <div className="exsheet-dose">
            <span className="exsheet-pattern">
              {exercise.is_warmup ? 'Warm-up' : exercise.pattern}
            </span>
            <span className="exsheet-amount num">{dose(exercise)}</span>
          </div>

          <ExerciseFigure
            pattern={exercise.key}
            name={exercise.name}
            className="exsheet-fig"
          />

          <p className="exsheet-cue">{exercise.cue}</p>

          <dl className="exsheet-facts">
            <div><dt>Load</dt><dd>{exercise.load}</dd></div>
            <div>
              <dt>Rest</dt>
              <dd>{exercise.rest_s ? `${exercise.rest_s}s` : 'None — keep moving'}</dd>
            </div>
          </dl>

          {exercise.why && (
            <section className="exsheet-why">
              <h4>Why this one</h4>
              <p>{exercise.why}</p>
            </section>
          )}

          {/* A warm-up move has no ladder: it is the same six moves at week one
              and at week fifty, which is the point of them. */}
          {!exercise.is_warmup && (
            <section className="exsheet-ladder">
              <h4>Where you are</h4>
              <div className="rungs" aria-label={`Rung ${exercise.level} of ${exercise.max_level}`}>
                {Array.from({ length: exercise.max_level }).map((_, i) => {
                  const rung = i + 1
                  const state = rung <= exercise.level ? 'on'
                    : rung <= exercise.ceiling ? '' : 'locked'
                  return <i key={rung} className={state} />
                })}
              </div>
              <p className="exsheet-rung num">
                Rung {exercise.level} of {exercise.max_level}
              </p>
              <p className="exsheet-next">
                {exercise.at_ceiling
                  ? exercise.load.toLowerCase().includes('bodyweight')
                    ? 'This is as far as bodyweight goes on this movement. A dumbbell opens the next rung — it is equipment you are missing, not strength.'
                    : 'Top of what your equipment reaches. Change it in Settings to go further.'
                  : `Move up when: ${exercise.graduate_when}`}
              </p>
            </section>
          )}
        </div>
      )}
    </BottomSheet>
  )
}
