import { useEffect, useRef, useState } from 'react'
import { mmss, useBeeper } from './audio'

export type TimerStep = { label: string; seconds: number; detail?: string; rest?: boolean }

/**
 * A simple step-by-step timer: current step, countdown, next step, overall progress.
 * Start / pause / skip / reset; a beep at each change (once started by a tap).
 */
export function StepTimer({ steps, title = 'Timer' }: { steps: TimerStep[]; title?: string }) {
  const [index, setIndex] = useState(0)
  const [left, setLeft] = useState(steps[0]?.seconds ?? 0)
  const [running, setRunning] = useState(false)
  const [done, setDone] = useState(false)
  const endAt = useRef<number | null>(null)
  const { ensure, play } = useBeeper()

  const total = steps.reduce((s, x) => s + x.seconds, 0)
  const elapsed = steps.slice(0, index).reduce((s, x) => s + x.seconds, 0) + ((steps[index]?.seconds ?? 0) - left)

  useEffect(() => {
    if (!running) return
    endAt.current = Date.now() + left * 1000
    const t = setInterval(() => {
      const rem = ((endAt.current ?? 0) - Date.now()) / 1000
      if (rem > 0) {
        setLeft(rem)
        return
      }
      clearInterval(t)
      const nextIndex = index + 1
      if (nextIndex >= steps.length) {
        setRunning(false)
        setDone(true)
        setLeft(0)
        play(660, 0.5)
        return
      }
      setLeft(steps[nextIndex].seconds)
      setIndex(nextIndex)
      play(steps[nextIndex].rest ? 520 : 880, 0.15)
    }, 200)
    return () => clearInterval(t)
    // `left` is only read when (re)starting — the interval owns it afterwards.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running, index])

  const toggle = () => {
    if (done) return
    if (!running) ensure()
    setRunning((r) => !r)
  }
  const skip = () => {
    if (index + 1 >= steps.length) {
      setRunning(false)
      setDone(true)
      setLeft(0)
      return
    }
    setIndex(index + 1)
    setLeft(steps[index + 1].seconds)
  }
  const reset = () => {
    setRunning(false)
    setDone(false)
    setIndex(0)
    setLeft(steps[0]?.seconds ?? 0)
  }

  const step = steps[index]
  const next = steps[index + 1]
  if (!step) return null
  const stepPct = step.seconds ? 1 - left / step.seconds : 0

  return (
    <div className={`step-timer ${running ? 'is-running' : ''} ${step.rest ? 'is-rest' : ''}`} aria-label={title}>
      <div className="step-timer-head">
        <span className="eyebrow">{title}</span>
        <span className="muted small">{done ? 'Done' : `Step ${index + 1} of ${steps.length}`}</span>
      </div>
      <div className="step-timer-main" aria-live="polite">
        <div className="grow">
          <p className="step-timer-label">{done ? 'All done — nice work' : step.label}</p>
          {!done && step.detail && <p className="muted small">{step.detail}</p>}
        </div>
        <span className="step-timer-clock">{mmss(left)}</span>
      </div>
      <div className="step-timer-bar" aria-hidden="true">
        <span style={{ width: `${Math.min(100, (done ? 1 : stepPct) * 100)}%` }} />
      </div>
      {!done && next && <p className="muted small">Next: {next.label} · {mmss(next.seconds)}</p>}
      <div className="step-timer-actions">
        <button type="button" className="btn btn-secondary btn-sm" onClick={reset}>Reset</button>
        <button type="button" className="btn btn-secondary btn-sm" onClick={skip} disabled={done}>Skip</button>
        <button type="button" className="btn btn-primary btn-sm btn-grow" onClick={toggle} disabled={done}>
          {running ? 'Pause' : elapsed > 0 ? 'Resume' : 'Start'}
        </button>
      </div>
      <p className="muted small">Total {mmss(total)} · {mmss(Math.max(0, total - elapsed))} left</p>
    </div>
  )
}
