import { useEffect, useRef, useState } from 'react'
import { mmss, useBeeper } from './audio'

const STEP_S = 0.36 // ~165 steps per minute

const RHYTHMS = [
  { key: 'easy', name: 'Easy', ratio: '3:3', inn: 3, out: 3, text: 'Three steps in, three steps out — or breathe through your nose. If you can’t, slow down a little.' },
  { key: 'steady', name: 'Steady', ratio: '2:2', inn: 2, out: 2, text: 'Two steps in, two out. Tempo and steady runs; you can still say short sentences.' },
  { key: 'hard', name: 'Hard', ratio: '2:1', inn: 2, out: 1, text: 'Two in, one out for hard intervals and hills. Short spells only.' },
]

/** One breath cycle as a row of steps; the highlight walks along in time. */
function StepDots({ inn, out }: { inn: number; out: number }) {
  const total = inn + out
  return (
    <div className="step-dots guide-anim" aria-hidden="true">
      {Array.from({ length: total }, (_, i) => (
        <span
          key={i}
          className={`step-dot ${i < inn ? 'is-in' : 'is-out'}`}
          style={{ animationDuration: `${total * STEP_S}s`, animationDelay: `${i * STEP_S}s` }}
        >
          <i />
          <small>{i < inn ? 'in' : 'out'}</small>
        </span>
      ))}
    </div>
  )
}

type Phase = { label: 'Inhale' | 'Hold' | 'Exhale'; s: number; scale: number; hint?: string }
const PATTERNS: Array<{ key: string; name: string; sub: string; phases: Phase[] }> = [
  {
    key: 'box', name: 'Box', sub: '4-4-4-4 · calm before a race or to wind down',
    phases: [
      { label: 'Inhale', s: 4, scale: 1 },
      { label: 'Hold', s: 4, scale: 1 },
      { label: 'Exhale', s: 4, scale: 0.55 },
      { label: 'Hold', s: 4, scale: 0.55 },
    ],
  },
  {
    key: 'belly', name: 'Diaphragmatic', sub: 'In 4 · out 6 · belly rises, chest stays still',
    phases: [
      { label: 'Inhale', s: 4, scale: 1, hint: 'Belly out' },
      { label: 'Exhale', s: 6, scale: 0.55, hint: 'Belly in, slowly' },
    ],
  },
  {
    key: 'pursed', name: 'Pursed-lip', sub: 'In 2 through the nose · out 4 through pursed lips',
    phases: [
      { label: 'Inhale', s: 2, scale: 1, hint: 'Through the nose' },
      { label: 'Exhale', s: 4, scale: 0.55, hint: 'Lips pursed, like blowing out a candle' },
    ],
  },
]

/** Expanding/contracting circle with inhale / hold / exhale, for 3 or 5 minutes. */
function Pacer() {
  const [patternKey, setPatternKey] = useState(PATTERNS[0].key)
  const [minutes, setMinutes] = useState(3)
  const [running, setRunning] = useState(false)
  const [phaseIndex, setPhaseIndex] = useState(0)
  const [phaseLeft, setPhaseLeft] = useState(0)
  const [sessionLeft, setSessionLeft] = useState(minutes * 60)
  const phaseEnd = useRef(0)
  const sessionEnd = useRef(0)
  const index = useRef(0)
  const { ensure, play } = useBeeper()
  const pattern = PATTERNS.find((p) => p.key === patternKey) ?? PATTERNS[0]

  useEffect(() => {
    if (!running) return
    const t = setInterval(() => {
      const now = Date.now()
      if (now >= sessionEnd.current) {
        setRunning(false)
        setSessionLeft(0)
        play(660, 0.5)
        return
      }
      setSessionLeft((sessionEnd.current - now) / 1000)
      if (now >= phaseEnd.current) {
        index.current = (index.current + 1) % pattern.phases.length
        phaseEnd.current = now + pattern.phases[index.current].s * 1000
        setPhaseIndex(index.current)
      }
      setPhaseLeft((phaseEnd.current - now) / 1000)
    }, 100)
    return () => clearInterval(t)
  }, [running, pattern, play])

  const start = () => {
    ensure()
    const now = Date.now()
    index.current = 0
    phaseEnd.current = now + pattern.phases[0].s * 1000
    sessionEnd.current = now + minutes * 60 * 1000
    setPhaseIndex(0)
    setPhaseLeft(pattern.phases[0].s)
    setSessionLeft(minutes * 60)
    setRunning(true)
  }
  const stop = () => {
    setRunning(false)
    setSessionLeft(minutes * 60)
  }

  const phase = pattern.phases[phaseIndex] ?? pattern.phases[0]
  const scale = running ? phase.scale : 0.55
  const duration = running && phase.label !== 'Hold' ? phase.s : 0.4

  return (
    <section className="card stack guide-block">
      <h3 className="habit-sub">Breathing pacer</h3>
      <div className="chips-row chips-row-sm" role="radiogroup" aria-label="Pattern">
        {PATTERNS.map((p) => (
          <button
            key={p.key}
            type="button"
            role="radio"
            aria-checked={patternKey === p.key}
            className={`pill-btn ${patternKey === p.key ? 'is-active' : ''}`}
            onClick={() => { setPatternKey(p.key); setRunning(false); setPhaseIndex(0) }}
          >
            {p.name}
          </button>
        ))}
      </div>
      <p className="muted small">{pattern.sub}</p>
      <div className="pacer" aria-live="polite">
        <div className="pacer-ring" aria-hidden="true" />
        <div
          className={`pacer-circle is-${phase.label.toLowerCase()} ${running ? 'is-running' : ''}`}
          style={{ transform: `scale(${scale})`, transitionDuration: `${duration}s` }}
          aria-hidden="true"
        />
        <div className="pacer-label">
          <span className="pacer-phase">{running ? phase.label : 'Ready'}</span>
          {running && <span className="pacer-count">{Math.ceil(phaseLeft)}</span>}
          {running && phase.hint && <span className="muted small">{phase.hint}</span>}
        </div>
      </div>
      <div className="pacer-foot">
        <div className="segmented" role="radiogroup" aria-label="Length">
          {[3, 5].map((m) => (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={minutes === m}
              className={`segmented-option ${minutes === m ? 'is-active' : ''}`}
              disabled={running}
              onClick={() => { setMinutes(m); setSessionLeft(m * 60) }}
            >
              {m} min
            </button>
          ))}
        </div>
        <span className="pacer-time">{mmss(sessionLeft)}</span>
      </div>
      <button type="button" className={`btn btn-block ${running ? 'btn-secondary' : 'btn-primary'}`} onClick={running ? stop : start}>
        {running ? 'Stop' : 'Start'}
      </button>
    </section>
  )
}

export function BreathingGuide({ smoking }: { smoking: boolean }) {
  return (
    <div className="stack">
      {smoking && (
        <section className="card guide-note">
          <p className="habit-sub">Lungs recover — and running helps</p>
          <p className="small">
            After stopping smoking, breathing typically gets easier within weeks as the airways clear, and lung
            function keeps improving over the following months. Expect easy runs to feel easier first. The pursed-lip
            and belly breathing below help when you feel short of breath — and if breathlessness or chest pain is
            new or severe, see a doctor.
          </p>
        </section>
      )}
      <section className="card stack guide-block">
        <h3 className="habit-sub">Rhythm by effort</h3>
        <p className="muted small">Match breaths to footsteps. Each dot is one step.</p>
        <ul className="rhythms">
          {RHYTHMS.map((r) => (
            <li key={r.key} className="rhythm">
              <div className="rhythm-head">
                <span className="rhythm-name">{r.name}</span>
                <span className="tag tag-plain">{r.ratio}</span>
              </div>
              <StepDots inn={r.inn} out={r.out} />
              <p className="muted small">{r.text}</p>
            </li>
          ))}
        </ul>
        <p className="muted small">Breathe from the belly, exhale fully, and keep shoulders loose. Side stitch? Exhale as the opposite foot lands for a minute.</p>
      </section>
      <Pacer />
    </div>
  )
}
