import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { reducedMotion } from '../../lib/navMotion'
import type { RecoveryRoutine, RecoveryStep } from '../../lib/r17'
import { useRecovery, useRecoveryDone } from '../../lib/r17lazy'
import { Figure } from '../guides/StrengthGuide'
import { mmss, useBeeper } from '../guides/audio'
import { CheckIcon, ChevronLeft, CloseIcon } from '../Icons'
import { poseFor } from './figures'
import '../../styles/r17lazy.css'

/** One timed block: a step, or one side of a per-side step. */
type Phase = { step: RecoveryStep; stepIndex: number; side: 'left' | 'right' | null; seconds: number }

function phasesOf(steps: RecoveryStep[]): Phase[] {
  return steps.flatMap((step, stepIndex): Phase[] => {
    const s = Math.max(5, Math.round(step.seconds || 30))
    return step.per_side
      ? [{ step, stepIndex, side: 'left' as const, seconds: s }, { step, stepIndex, side: 'right' as const, seconds: s }]
      : [{ step, stepIndex, side: null, seconds: s }]
  })
}

const buzz = (pattern: number | number[]) => {
  try { navigator.vibrate?.(pattern) } catch { /* not supported */ }
}

/** Keep the screen on while the routine runs (re-taken when the tab comes back). */
function useWakeLock(on: boolean) {
  useEffect(() => {
    type Sentinel = { release: () => Promise<void> }
    const nav = navigator as Navigator & { wakeLock?: { request: (t: 'screen') => Promise<Sentinel> } }
    if (!on || !nav.wakeLock) return
    let lock: Sentinel | null = null
    let alive = true
    const take = () => {
      if (document.visibilityState !== 'visible') return
      nav.wakeLock?.request('screen').then((l) => { if (alive) lock = l; else l.release().catch(() => {}) }).catch(() => {})
    }
    take()
    document.addEventListener('visibilitychange', take)
    return () => {
      alive = false
      document.removeEventListener('visibilitychange', take)
      lock?.release().catch(() => {})
    }
  }, [on])
}

function Ring({ share, children }: { share: number; children: React.ReactNode }) {
  const r = 52
  const c = 2 * Math.PI * r
  return (
    <div className="rt-ring">
      <svg viewBox="0 0 120 120" aria-hidden="true">
        <circle cx="60" cy="60" r={r} className="rt-ring-track" />
        <circle
          cx="60" cy="60" r={r}
          className="rt-ring-fill"
          strokeDasharray={`${c.toFixed(1)} ${c.toFixed(1)}`}
          strokeDashoffset={(c * (1 - Math.max(0, Math.min(1, share)))).toFixed(1)}
          transform="rotate(-90 60 60)"
        />
      </svg>
      <div className="rt-ring-mid">{children}</div>
    </div>
  )
}

const sideWord = (s: Phase['side']) => (s === 'left' ? 'Left side' : s === 'right' ? 'Right side' : '')
const doseOf = (s: RecoveryStep) => `${mmss(s.seconds)}${s.per_side ? ' / side' : ''}`

/**
 * R17 §1: the full-screen guided recovery routine — figure, countdown ring, side-switch
 * cue, next-up, back / pause / skip, beep + vibration at each change, screen kept awake
 * while it runs. Ends on a small "done" screen (POST …/recovery/done/).
 */
export default function RecoveryTimer({ activityId, onClose }: { activityId: number; onClose: () => void }) {
  const q = useRecovery(activityId)
  if (!q.data) {
    return createPortal(
      <div className="rt" role="dialog" aria-modal="true" aria-label="Recovery routine">
        <header className="rt-head">
          <button type="button" className="chip rt-close" aria-label="Close routine" onClick={onClose}><CloseIcon size={20} /></button>
          <span className="grow rt-head-title">Recovery</span>
        </header>
        <div className="rt-body"><div className="rt-done">
          {q.isError ? (
            <>
              <p className="rt-title">Couldn’t build your routine</p>
              <button type="button" className="btn btn-primary" onClick={() => q.refetch()}>Try again</button>
            </>
          ) : <p className="muted">Building your routine…</p>}
        </div></div>
      </div>,
      document.body,
    )
  }
  return <Routine activityId={activityId} routine={q.data} onClose={onClose} />
}

function Routine({ activityId, routine, onClose }: { activityId: number; routine: RecoveryRoutine; onClose: () => void }) {
  const steps = useMemo(() => (routine.steps ?? []).filter((s) => s && s.seconds > 0), [routine.steps])
  const phases = useMemo(() => phasesOf(steps), [steps])
  const [i, setI] = useState(0)
  const [left, setLeft] = useState(phases[0]?.seconds ?? 0)
  const [running, setRunning] = useState(false)
  const [started, setStarted] = useState(false)
  const [done, setDone] = useState(false)
  const [cue, setCue] = useState('')
  const endAt = useRef(0)
  // Seconds actually spent with the timer running (skips don't count).
  const spent = useRef(0)
  const lastTick = useRef(0)
  const { ensure, play } = useBeeper()
  const markDone = useRecoveryDone(activityId)
  const skipped = useRef(new Set<string>())
  const closeRef = useRef<HTMLButtonElement>(null)
  useWakeLock(running)

  const phase = phases[i]
  const total = phases.reduce((s, p) => s + p.seconds, 0)
  const elapsed = phases.slice(0, i).reduce((s, p) => s + p.seconds, 0) + ((phase?.seconds ?? 0) - left)

  const finish = useCallback(() => {
    setRunning(false)
    setDone(true)
    setLeft(0)
    play(660, 0.5)
    buzz([120, 80, 120, 80, 240])
    markDone.mutate([...skipped.current])
  }, [markDone, play])

  const goTo = useCallback((next: number, auto: boolean) => {
    if (next >= phases.length) { finish(); return }
    const from = phases[i]
    const to = phases[Math.max(0, next)]
    setI(Math.max(0, next))
    setLeft(to.seconds)
    endAt.current = Date.now() + to.seconds * 1000
    if (!auto) return
    if (from && to.stepIndex === from.stepIndex && to.side === 'right') {
      setCue('Switch sides')
      play(988, 0.12)
      setTimeout(() => play(988, 0.12), 180)
      buzz([90, 70, 90])
    } else {
      setCue('')
      play(880, 0.18)
      buzz(160)
    }
  }, [phases, i, finish, play])

  // Countdown on the wall clock, so a busy main thread never slows the routine.
  useEffect(() => {
    if (!running) return
    endAt.current = Date.now() + left * 1000
    lastTick.current = Date.now()
    const t = setInterval(() => {
      const now = Date.now()
      spent.current += (now - lastTick.current) / 1000
      lastTick.current = now
      const rem = (endAt.current - Date.now()) / 1000
      if (rem > 0) {
        setLeft(rem)
        // Three soft ticks before a change.
        const whole = Math.ceil(rem)
        if (whole <= 3 && Math.abs(rem - whole + 1) < 0.12) play(660, 0.05)
        return
      }
      goTo(i + 1, true)
    }, 100)
    return () => clearInterval(t)
    // `left` is read only when (re)starting; the interval owns it afterwards.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running, i])

  useEffect(() => {
    if (!cue) return
    const t = setTimeout(() => setCue(''), 2600)
    return () => clearTimeout(t)
  }, [cue])

  // Full screen: no page scroll behind, Escape closes, focus starts on close.
  useEffect(() => {
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    closeRef.current?.focus()
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => { document.body.style.overflow = prev; window.removeEventListener('keydown', onKey) }
  }, [onClose])

  const toggle = () => {
    ensure()
    if (!started) { setStarted(true); play(880, 0.15); buzz(60) }
    setRunning((r) => !r)
  }
  const back = () => {
    // Early in a block → previous step; later → restart this one.
    const into = (phase?.seconds ?? 0) - left
    const target = into > 3 ? phases.findIndex((p) => p.stepIndex === phase.stepIndex) : Math.max(0, phases.findIndex((p) => p.stepIndex === Math.max(0, phase.stepIndex - 1)))
    setCue('')
    goTo(target, false)
  }
  const skip = () => {
    const next = phases.findIndex((p) => p.stepIndex > phase.stepIndex)
    if ((phase.seconds - left) < phase.seconds / 2) skipped.current.add(phase.step.key)
    setCue('')
    if (next < 0) finish()
    else goTo(next, false)
  }

  const nextStep = phase ? steps[phase.stepIndex + 1] : undefined
  const reduced = reducedMotion()

  const body = !phases.length ? (
    <div className="rt-done">
      <p className="rt-title">Nothing to do today</p>
      <p className="muted">This routine has no steps. A 5-minute easy walk is plenty.</p>
      <button type="button" className="btn btn-primary" onClick={onClose}>Close</button>
    </div>
  ) : done ? (
    <div className="rt-done" aria-live="polite">
      <span className="rt-done-check" aria-hidden="true"><CheckIcon size={40} /></span>
      <p className="rt-title">Recovery done</p>
      <p className="muted">
        {spent.current >= 60 ? `${Math.round(spent.current / 60)} min of easy moves — your legs will thank you tomorrow.` : 'Every bit helps — your legs will thank you tomorrow.'}
      </p>
      {(markDone.data?.streak?.current ?? 0) > 1 && (
        <p className="rt-streak">Recovery streak: <b>{markDone.data?.streak?.current}</b> runs in a row</p>
      )}
      {markDone.data?.new_badges?.map((b) => <p key={b.key} className="rt-streak">New badge: <b>{b.label}</b></p>)}
      {markDone.isError && <p className="muted small">Couldn’t save it — it still counts.</p>}
      <button type="button" className="btn btn-primary" onClick={onClose}>Close</button>
    </div>
  ) : (
    <>
      <div className="rt-progress" aria-hidden="true">
        {steps.map((s, k) => (
          <span key={`${s.key}-${k}`} className={k < phase.stepIndex ? 'is-done' : k === phase.stepIndex ? 'is-now' : ''} />
        ))}
      </div>
      <div className="rt-figure-wrap">
        <Figure pose={poseFor(phase.step.figure, phase.step.key)} label={phase.step.title} className={`rt-figure ${phase.side === 'right' ? 'is-mirror' : ''}`} />
        {cue && <span className="rt-cue" role="status">{cue}</span>}
      </div>
      <div className="rt-info">
        <p className="rt-eyebrow">
          Step {phase.stepIndex + 1} of {steps.length}
          {phase.side && <span className="rt-side">{sideWord(phase.side)}</span>}
          {phase.step.optional && <span className="rt-opt">Optional</span>}
          {phase.step.softened && <span className="rt-opt">Gentler today</span>}
        </p>
        <h2 className="rt-title">{phase.step.title}</h2>
        {phase.step.cue && <p className="rt-cue-text">{phase.step.cue}</p>}
        {!started && (routine.avoided ?? []).map((a) => <p key={a.area} className="rt-avoid">{a.text}</p>)}
      </div>
      <Ring share={reduced ? (phase.seconds - Math.ceil(left)) / phase.seconds : 1 - left / phase.seconds}>
        <span className="rt-clock" aria-live="off">{mmss(left)}</span>
        <span className="rt-clock-sub">{running ? (phase.side ? sideWord(phase.side) : 'Hold, breathe') : started ? 'Paused' : 'Ready'}</span>
      </Ring>
      <p className="rt-next">
        {nextStep ? <>Next: <b>{nextStep.title}</b> · {doseOf(nextStep)}</> : phase.side === 'left' ? 'Then the right side' : 'Last one'}
      </p>
      <div className="rt-actions">
        <button type="button" className="btn btn-secondary" onClick={back} disabled={i === 0 && left >= phase.seconds - 0.5} aria-label="Back">
          <ChevronLeft size={20} /> Back
        </button>
        <button type="button" className="btn btn-primary rt-main" onClick={toggle}>
          {running ? 'Pause' : started ? 'Resume' : 'Start'}
        </button>
        <button type="button" className="btn btn-secondary" onClick={skip}>Skip</button>
      </div>
      <p className="muted small centered-text">{mmss(Math.max(0, total - elapsed))} left · {routine.notes?.[0] ?? 'Ease into each stretch — mild tension, never pain.'}</p>
    </>
  )

  return createPortal(
    <div className="rt" role="dialog" aria-modal="true" aria-label={`Recovery routine, ${routine.minutes ?? Math.round(total / 60)} minutes`}>
      <header className="rt-head">
        <button ref={closeRef} type="button" className="chip rt-close" aria-label="Close routine" onClick={onClose}><CloseIcon size={20} /></button>
        <span className="grow rt-head-title">Recovery · {routine.minutes ?? Math.max(1, Math.round(total / 60))} min</span>
      </header>
      <div className="rt-body">{body}</div>
    </div>,
    document.body,
  )
}
