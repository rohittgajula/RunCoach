/**
 * Run the gym session, set by set.
 *
 * Runs have had a step timer for a long time; the gym had nothing unless you
 * sent it to the watch, so the phone sat in your pocket while you lost count
 * of which set you were on.
 *
 * A gym session cannot be driven by one countdown, which is why the run timer
 * could not simply be reused. Two different kinds of step:
 *
 *   A set of reps has no duration. Twelve push-ups take as long as they take,
 *   and a clock that decides when you are finished is worse than no clock —
 *   it either rushes you or stands there expired. So a rep set waits for a
 *   tap.
 *
 *   Rest does have a duration, and it is the part people get wrong, cutting
 *   it short while they still feel fine. So rest counts itself down and beeps.
 *
 *   A hold (a plank, a stretch) is timed like rest, because there the clock
 *   is the exercise.
 *
 * The last rest of the session is dropped. Resting after the final set is
 * resting before going home.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { mmss, useBeeper } from '../guides/audio'

type Exercise = {
  key: string
  name: string
  sets: number
  reps: number | null
  seconds: number | null
  per_side: boolean
  rest_s: number
}

type Step =
  | { kind: 'work'; name: string; detail: string; seconds: number | null; set: number; of: number }
  | { kind: 'rest'; name: string; detail: string; seconds: number; set: number; of: number }

function build(exercises: Exercise[]): Step[] {
  const steps: Step[] = []
  exercises.forEach((e) => {
    const sets = Math.max(1, e.sets)
    for (let set = 1; set <= sets; set += 1) {
      steps.push({
        kind: 'work',
        name: e.name,
        detail: e.reps != null
          ? `${e.reps} reps${e.per_side ? ' a side' : ''}`
          : `${e.seconds}s${e.per_side ? ' a side' : ''}`,
        seconds: e.reps != null ? null : e.seconds,
        set,
        of: sets,
      })
      if (e.rest_s) {
        steps.push({
          kind: 'rest', name: 'Rest', detail: `before ${e.name.toLowerCase()}`,
          seconds: e.rest_s, set, of: sets,
        })
      }
    }
  })
  // Trailing rest belongs to nothing.
  while (steps.length && steps[steps.length - 1].kind === 'rest') steps.pop()
  return steps
}

export function GymTimer({ exercises, onClose }: { exercises: Exercise[]; onClose: () => void }) {
  const steps = useMemo(() => build(exercises), [exercises])
  const [index, setIndex] = useState(0)
  const [left, setLeft] = useState<number>(steps[0]?.seconds ?? 0)
  const [running, setRunning] = useState(false)
  const endAt = useRef<number | null>(null)
  const { ensure, play } = useBeeper()

  const step = steps[index]
  const timed = !!step && step.seconds != null
  const finished = index >= steps.length

  useEffect(() => {
    setLeft(steps[index]?.seconds ?? 0)
    // A timed step starts itself; a rep set waits for you.
    setRunning(!!steps[index] && steps[index].seconds != null)
  }, [index, steps])

  useEffect(() => {
    if (!running || !timed) return
    endAt.current = Date.now() + left * 1000
    const tick = setInterval(() => {
      const remaining = ((endAt.current ?? 0) - Date.now()) / 1000
      if (remaining > 0) {
        setLeft(remaining)
        return
      }
      clearInterval(tick)
      play(880)
      setIndex((i) => i + 1)
    }, 200)
    return () => clearInterval(tick)
    // `left` is read once to set the end time; tracking it would restart the
    // interval on every tick.
     
  }, [running, timed, index, play])

  if (finished) {
    return (
      <div className="gymtimer is-done">
        <p className="gymtimer-done">Session done.</p>
        <button type="button" className="btn btn-primary btn-grow" onClick={onClose}>
          Close
        </button>
      </div>
    )
  }

  const next = steps[index + 1]
  const pct = Math.round((index / steps.length) * 100)

  return (
    <div className="gymtimer" data-kind={step.kind}>
      <div className="gymtimer-bar"><i style={{ width: `${pct}%` }} /></div>

      <p className="gymtimer-kind">
        {step.kind === 'rest' ? 'Rest' : `Set ${step.set} of ${step.of}`}
      </p>
      <h3 className="gymtimer-name">{step.kind === 'rest' ? step.detail : step.name}</h3>

      {timed ? (
        <p className="gymtimer-clock num">{mmss(Math.ceil(left))}</p>
      ) : (
        <p className="gymtimer-reps num">{step.detail}</p>
      )}

      <div className="gymtimer-actions">
        {timed ? (
          <button
            type="button"
            className="btn btn-secondary btn-grow"
            onClick={() => { ensure(); setRunning((r) => !r) }}
          >
            {running ? 'Pause' : 'Resume'}
          </button>
        ) : (
          <button
            type="button"
            className="btn btn-primary btn-grow"
            onClick={() => { ensure(); setIndex((i) => i + 1) }}
          >
            Done — next
          </button>
        )}
        <button type="button" className="btn btn-plain" onClick={() => setIndex((i) => i + 1)}>
          Skip
        </button>
      </div>

      <p className="gymtimer-next muted small">
        {next ? <>Next: {next.kind === 'rest' ? 'rest' : `${next.name} · ${next.detail}`}</> : 'Last one.'}
      </p>
    </div>
  )
}
