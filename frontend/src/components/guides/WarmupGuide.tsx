import { useState } from 'react'
import { mmss } from './audio'
import { StepTimer, type TimerStep } from './StepTimer'

const WARMUP: TimerStep[] = [
  { label: 'Brisk walk', seconds: 180, detail: 'Swing the arms, get warm' },
  { label: 'Leg swings', seconds: 60, detail: '10 front-to-back + 10 side-to-side each leg, hold a wall' },
  { label: 'Walking lunges', seconds: 60, detail: 'Slow, torso tall' },
  { label: 'Hip circles & ankle rolls', seconds: 45, detail: 'Both directions' },
  { label: 'A-skips', seconds: 30, detail: 'Knee up, land under you' },
  { label: 'Butt kicks', seconds: 30, detail: 'Quick and light' },
  { label: 'Easy jog', seconds: 180, detail: 'Slower than easy pace — let the HR rise gently' },
]

const COOLDOWN: TimerStep[] = [
  { label: 'Easy walk', seconds: 300, detail: 'Let breathing and heart rate settle' },
  { label: 'Calf stretch — left', seconds: 30, detail: 'Back leg straight, heel down' },
  { label: 'Calf stretch — right', seconds: 30, detail: 'Back leg straight, heel down' },
  { label: 'Hamstring — both sides', seconds: 60, detail: 'Hinge at the hips, soft knee, 30 s each' },
  { label: 'Quad — both sides', seconds: 60, detail: 'Hold the ankle, knees together, 30 s each' },
  { label: 'Hip flexor — both sides', seconds: 60, detail: 'Half-kneel, tuck the pelvis, 30 s each' },
  { label: 'Glute (figure-4) — both sides', seconds: 60, detail: 'Lying or seated, 30 s each' },
]

const COLORS = ['var(--easy)', 'var(--easy-2)', 'var(--moderate)', 'var(--extra)', 'var(--ok)', 'var(--warn)', 'var(--hard)']

/** Proportional bar of the sequence (like the workout bar). */
function SequenceBar({ steps }: { steps: TimerStep[] }) {
  const total = steps.reduce((s, x) => s + x.seconds, 0)
  return (
    <div className="seq-bar" aria-hidden="true">
      {steps.map((s, i) => (
        <span key={s.label} style={{ flexGrow: s.seconds / total, background: COLORS[i % COLORS.length] }} />
      ))}
    </div>
  )
}

export function WarmupGuide() {
  const [which, setWhich] = useState<'warm' | 'cool'>('warm')
  const steps = which === 'warm' ? WARMUP : COOLDOWN
  const total = steps.reduce((s, x) => s + x.seconds, 0)
  return (
    <div className="stack">
      <div className="segmented segmented-full" role="radiogroup" aria-label="Sequence">
        <button type="button" role="radio" aria-checked={which === 'warm'} className={`segmented-option ${which === 'warm' ? 'is-active' : ''}`} onClick={() => setWhich('warm')}>Warm-up</button>
        <button type="button" role="radio" aria-checked={which === 'cool'} className={`segmented-option ${which === 'cool' ? 'is-active' : ''}`} onClick={() => setWhich('cool')}>Cool-down</button>
      </div>
      <section className="card stack guide-block">
        <div className="card-head">
          <h3 className="habit-sub">{which === 'warm' ? 'Before every run' : 'After every run'}</h3>
          <span className="tag tag-plain">{mmss(total)}</span>
        </div>
        <SequenceBar steps={steps} />
        <ol className="seq">
          {steps.map((s, i) => (
            <li key={s.label} className="seq-item">
              <i className="seq-key" style={{ background: COLORS[i % COLORS.length] }} />
              <div className="grow">
                <p className="cue-title">{s.label}</p>
                {s.detail && <p className="muted small">{s.detail}</p>}
              </div>
              <span className="seq-time">{mmss(s.seconds)}</span>
            </li>
          ))}
        </ol>
        <p className="muted small">
          {which === 'warm'
            ? 'Before a hard session, add 4 × 20 s strides at the end with a walk back.'
            : 'Stretch gently — mild tension, never pain. Hold still; no bouncing.'}
        </p>
      </section>
      <section className="card">
        <StepTimer key={which} title={which === 'warm' ? 'Warm-up timer' : 'Cool-down timer'} steps={steps} />
      </section>
    </div>
  )
}
