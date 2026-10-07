import { useState } from 'react'
import { useMetronome } from './audio'

const HIP_X = 120
const GROUND = 189

/** One leg: thigh rotates at the hip, shin at the knee (CSS animations in guides.css). */
function Leg({ side }: { side: 'near' | 'far' }) {
  return (
    <g className={`leg ${side}`}>
      <g className="thigh">
        <line x1={HIP_X} y1={104} x2={HIP_X} y2={146} />
        <g className="shin">
          <line x1={HIP_X} y1={146} x2={HIP_X} y2={186} />
          <line className="foot" x1={HIP_X - 3} y1={187} x2={HIP_X + 11} y2={187} />
        </g>
      </g>
    </g>
  )
}

function Arm({ side }: { side: 'near' | 'far' }) {
  return (
    <g className={`arm ${side}`}>
      <line x1={HIP_X} y1={62} x2={HIP_X} y2={84} />
      <line x1={HIP_X} y1={84} x2={HIP_X + 15} y2={80} />
    </g>
  )
}

/** Side-view runner: good landing (under the hips) vs overstride (heel far ahead). */
export function Runner({ good }: { good: boolean }) {
  return (
    <svg
      viewBox="0 0 240 200"
      className={`runner guide-anim ${good ? 'is-good' : 'is-over'}`}
      role="img"
      aria-label={good ? 'Runner landing with the foot under the hips, midfoot first, leaning slightly forward' : 'Runner overstriding: heel lands far ahead of the hips, braking each step'}
    >
      <line className="runner-ground" x1={0} y1={GROUND + 2} x2={240} y2={GROUND + 2} />
      {good ? (
        <g className="land-mark is-good">
          <line x1={HIP_X} y1={108} x2={HIP_X} y2={GROUND} className="land-line" />
          <ellipse cx={HIP_X + 10} cy={GROUND + 2} rx={16} ry={4} />
          <text x={HIP_X + 30} y={GROUND - 6}>lands under hips</text>
        </g>
      ) : (
        <g className="land-mark is-bad">
          <line x1={HIP_X} y1={118} x2={HIP_X} y2={GROUND} className="land-line" />
          <ellipse cx={HIP_X + 44} cy={GROUND + 2} rx={16} ry={4} />
          <line x1={HIP_X + 4} y1={GROUND - 8} x2={HIP_X + 38} y2={GROUND - 8} className="land-gap" />
          <text x={HIP_X + 62} y={GROUND - 6}>heel ahead = brake</text>
        </g>
      )}
      <g className="runner-drop">
        <g className="runner-body">
          <Leg side="far" />
          <g className="runner-torso">
            <Arm side="far" />
            <line className="torso" x1={HIP_X} y1={104} x2={HIP_X} y2={58} />
            <circle className="head" cx={HIP_X + 2} cy={43} r={10} />
            <Arm side="near" />
          </g>
          <Leg side="near" />
        </g>
      </g>
    </svg>
  )
}

const CUES = [
  { title: 'Foot lands under your hips', text: 'Not out in front — let it touch down close beneath your body.' },
  { title: 'Midfoot, soft and quiet', text: 'Aim for a light, quiet landing; no slapping heel.' },
  { title: 'Slight forward lean', text: 'From the ankles, not the waist — tall chest, eyes ahead.' },
  { title: 'Short, quick steps', text: 'A few more steps per minute shortens the stride by itself.' },
  { title: 'Relaxed arms at ~90°', text: 'Swing front-to-back, hands loose, shoulders down.' },
]

const clampBpm = (v: number) => Math.max(140, Math.min(200, Math.round(v)))

/** Cadence metronome: WebAudio clicks at the chosen steps per minute. */
function Metronome({ cadence, bpmHint }: { cadence: number | null; bpmHint: number | null }) {
  const suggested = clampBpm(bpmHint ?? (cadence ?? 160) * 1.05)
  const [bpm, setBpm] = useState(suggested)
  const metronome = useMetronome(bpm)
  const [noAudio, setNoAudio] = useState(false)
  return (
    <section className="card stack guide-block">
      <h3 className="habit-sub">Cadence metronome</h3>
      <p className="muted small">
        {cadence
          ? `Your recent average is ${Math.round(cadence)} spm. Try ${suggested} (+5%) on an easy run — step on each click.`
          : 'Step on each click. +5% on your usual cadence is a gentle change; start on an easy run.'}
      </p>
      <div className="metronome">
        <button type="button" className="chip" aria-label="2 steps per minute slower" onClick={() => setBpm((b) => clampBpm(b - 2))}>−</button>
        <div className="metronome-value">
          <span
            key={`${bpm}-${metronome.running}`}
            className={`metronome-dot guide-anim ${metronome.running ? 'is-on' : ''}`}
            style={{ animationDuration: `${60 / bpm}s` }}
            aria-hidden="true"
          />
          <span className="display">{bpm}</span>
          <span className="muted small">steps / min</span>
        </div>
        <button type="button" className="chip" aria-label="2 steps per minute faster" onClick={() => setBpm((b) => clampBpm(b + 2))}>+</button>
      </div>
      <button
        type="button"
        className={`btn btn-block ${metronome.running ? 'btn-secondary' : 'btn-primary'}`}
        onClick={() => {
          if (metronome.running) metronome.stop()
          else setNoAudio(!metronome.start())
        }}
      >
        {metronome.running ? 'Stop' : 'Start metronome'}
      </button>
      {noAudio && <p className="bad small">This browser can’t play sound here.</p>}
      {bpm !== suggested && (
        <button type="button" className="link-btn small" onClick={() => setBpm(suggested)}>Back to {suggested}</button>
      )}
    </section>
  )
}

export function FormGuide({ cadence, bpm }: { cadence: number | null; bpm?: number | null }) {
  const [good, setGood] = useState(true)
  return (
    <div className="stack">
      <section className="card stack guide-block">
        <div className="segmented segmented-full" role="radiogroup" aria-label="Landing">
          <button type="button" role="radio" aria-checked={good} className={`segmented-option ${good ? 'is-active' : ''}`} onClick={() => setGood(true)}>
            Good landing
          </button>
          <button type="button" role="radio" aria-checked={!good} className={`segmented-option ${!good ? 'is-active' : ''}`} onClick={() => setGood(false)}>
            Overstride
          </button>
        </div>
        <div className="runner-wrap">
          <Runner good={good} />
        </div>
        <p className={`small ${good ? 'good-text' : 'bad'}`}>
          {good
            ? 'Foot lands close under the hips, midfoot first, knee slightly bent — the leg absorbs the landing and you roll straight into the next step.'
            : 'Foot reaches out ahead and lands on the heel with a straight knee — every step brakes you and sends the shock up the shin and knee.'}
        </p>
      </section>
      <section className="card stack guide-block">
        <h3 className="habit-sub">5 cues</h3>
        <ol className="cues">
          {CUES.map((c, i) => (
            <li key={c.title} className="cue">
              <span className="focus-num">{i + 1}</span>
              <div className="grow">
                <p className="cue-title">{c.title}</p>
                <p className="muted small">{c.text}</p>
              </div>
            </li>
          ))}
        </ol>
        <p className="muted small">Pick one cue per run. Form changes stick when they’re small and repeated.</p>
      </section>
      <Metronome cadence={cadence} bpmHint={bpm ?? null} />
    </div>
  )
}
