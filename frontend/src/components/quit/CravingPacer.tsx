import { useEffect, useRef, useState } from 'react'
import { mmss, useBeeper } from '../guides/audio'

const PHASES = [
  { label: 'Breathe in', s: 4, scale: 1 },
  { label: 'Breathe out', s: 6, scale: 0.55 },
] as const

/**
 * R13 §8: a 3-minute slow-breathing pacer (in 4 · out 6, the Guides' belly breathing).
 * Starts on mount (the tap that opened it is the user gesture), ends itself, and can
 * be finished early. Cravings usually pass within a few minutes.
 */
export function CravingPacer({ seconds = 180, onFinish }: { seconds?: number; onFinish: (early: boolean) => void }) {
  const [phase, setPhase] = useState(0)
  const [phaseLeft, setPhaseLeft] = useState<number>(PHASES[0].s)
  const [left, setLeft] = useState(seconds)
  const end = useRef(Date.now() + seconds * 1000)
  const phaseEnd = useRef(Date.now() + PHASES[0].s * 1000)
  const idx = useRef(0)
  const done = useRef(false)
  const { ensure, play } = useBeeper()
  const reduced = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

  useEffect(() => {
    ensure()
    const t = setInterval(() => {
      const now = Date.now()
      if (now >= end.current) {
        if (!done.current) {
          done.current = true
          play(660, 0.4)
          onFinish(false)
        }
        clearInterval(t)
        return
      }
      setLeft((end.current - now) / 1000)
      if (now >= phaseEnd.current) {
        idx.current = (idx.current + 1) % PHASES.length
        phaseEnd.current = now + PHASES[idx.current].s * 1000
        setPhase(idx.current)
      }
      setPhaseLeft((phaseEnd.current - now) / 1000)
    }, 100)
    return () => clearInterval(t)
  }, [ensure, play, onFinish])

  const p = PHASES[phase]
  return (
    <div className="craving-pacer stack">
      <div className="pacer" aria-live="polite">
        <div className="pacer-ring" aria-hidden="true" />
        <div
          className={`pacer-circle ${phase === 0 ? 'is-inhale' : 'is-exhale'} is-running`}
          style={{ transform: `scale(${reduced ? 0.8 : p.scale})`, transitionDuration: `${reduced ? 0 : p.s}s` }}
          aria-hidden="true"
        />
        <div className="pacer-label">
          <span className="pacer-phase">{p.label}</span>
          <span className="pacer-count">{Math.ceil(phaseLeft)}</span>
        </div>
      </div>
      <p className="craving-time" aria-label={`${Math.ceil(left)} seconds left`}>{mmss(left)}</p>
      <p className="muted small centered-text">Slow breaths into your belly. A craving usually peaks and fades within a few minutes — ride it out.</p>
      <button type="button" className="btn btn-secondary btn-block" onClick={() => { if (!done.current) { done.current = true; onFinish(true) } }}>
        I’m done
      </button>
    </div>
  )
}
