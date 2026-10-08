import { StepTimer, type TimerStep } from './StepTimer'

export type Pt = [number, number]
/** A stick-figure pose; limbs are polylines, `focus` marks the working muscle. */
export type Pose = { head: Pt; limbs: Pt[][]; back?: Pt[][]; focus: Pt; prop?: 'mat'; roller?: Pt; wall?: number }

export function Figure({ pose, label, className = '' }: { pose: Pose; label: string; className?: string }) {
  const path = (pts: Pt[]) => pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x},${y}`).join(' ')
  return (
    <svg viewBox="0 0 120 90" className={`ex-figure guide-anim ${className}`} role="img" aria-label={label}>
      <line className="ex-ground" x1={4} y1={84} x2={116} y2={84} />
      {/* R17: wall (calf stretch) and foam roller props. */}
      {pose.wall != null && <line className="ex-ground" x1={pose.wall} y1={8} x2={pose.wall} y2={84} />}
      {pose.roller && <circle className="ex-roller" cx={pose.roller[0]} cy={pose.roller[1]} r={6} />}
      <circle className="ex-focus" cx={pose.focus[0]} cy={pose.focus[1]} r={9} />
      {(pose.back ?? []).map((pts, i) => <path key={`b${i}`} className="ex-limb is-back" d={path(pts)} />)}
      {pose.limbs.map((pts, i) => <path key={i} className="ex-limb" d={path(pts)} />)}
      <circle className="ex-head" cx={pose.head[0]} cy={pose.head[1]} r={6.5} />
    </svg>
  )
}

export const EXERCISES: Array<{ key: string; name: string; dose: string; cue: string; pose: Pose; work: number }> = [
  {
    key: 'calf', name: 'Calf raise', dose: '3 × 15', cue: 'Slow up, slower down. Single-leg once easy.', work: 45,
    pose: { head: [60, 13], limbs: [[[60, 20], [60, 50]], [[60, 50], [61, 66], [61, 77], [68, 82]], [[60, 26], [57, 40], [57, 50]]], back: [[[60, 50], [59, 66], [58, 77], [65, 82]]], focus: [61, 72] },
  },
  {
    key: 'bridge', name: 'Glute bridge', dose: '3 × 12', cue: 'Squeeze glutes, ribs down, pause 2 s at the top.', work: 45,
    pose: { head: [16, 76], limbs: [[[24, 79], [60, 60]], [[60, 60], [80, 50], [88, 82]], [[28, 80], [46, 83]]], focus: [60, 62] },
  },
  {
    key: 'split', name: 'Split squat', dose: '3 × 8 / leg', cue: 'Front knee over the toes, torso tall, lower slowly.', work: 50,
    pose: { head: [58, 12], limbs: [[[58, 19], [58, 48]], [[58, 48], [78, 52], [78, 82]], [[58, 25], [55, 38], [57, 46]]], back: [[[58, 48], [44, 76], [30, 82]]], focus: [68, 52] },
  },
  {
    key: 'plank', name: 'Plank', dose: '3 × 30 s', cue: 'Straight line head to heels; breathe.', work: 30,
    pose: { head: [18, 56], limbs: [[[26, 60], [66, 64], [104, 82]], [[28, 61], [28, 82], [40, 82]]], focus: [48, 63] },
  },
  {
    key: 'side', name: 'Side plank', dose: '2 × 20 s / side', cue: 'Hips high, body in one line.', work: 40,
    pose: { head: [24, 50], limbs: [[[30, 57], [66, 69], [104, 82]], [[30, 58], [30, 82], [40, 82]], [[32, 56], [34, 30]]], focus: [64, 68] },
  },
  {
    key: 'clam', name: 'Clamshell', dose: '2 × 15 / side', cue: 'Heels together, open the top knee, don’t roll back.', work: 40,
    pose: { head: [14, 66], limbs: [[[22, 70], [58, 74]], [[58, 74], [74, 54], [86, 76]], [[22, 72], [14, 82]]], back: [[[58, 76], [80, 80], [88, 78]]], focus: [62, 70] },
  },
  {
    key: 'askip', name: 'A-skip', dose: '3 × 20 m', cue: 'Knee to hip height, land under you, quick and light.', work: 30,
    pose: { head: [60, 10], limbs: [[[60, 17], [60, 46]], [[60, 46], [78, 46], [76, 64]], [[60, 23], [70, 33], [77, 26]]], back: [[[60, 46], [60, 64], [62, 82]], [[60, 23], [52, 35], [47, 44]]], focus: [70, 46] },
  },
  {
    key: 'hipflexor', name: 'Hip-flexor stretch', dose: '2 × 30 s / side', cue: 'Tuck the pelvis, gently push hips forward.', work: 60,
    pose: { head: [60, 16], limbs: [[[60, 23], [60, 52]], [[60, 52], [80, 54], [80, 82]], [[60, 30], [66, 42], [62, 50]]], back: [[[60, 52], [46, 82], [28, 82]]], focus: [57, 58] },
  },
]

const REST = 20
const CIRCUIT: TimerStep[] = [1, 2].flatMap((round) =>
  EXERCISES.flatMap((e, i) => {
    const step: TimerStep = { label: e.name, seconds: e.work, detail: `Round ${round} · ${e.dose} · ${e.cue}` }
    const last = round === 2 && i === EXERCISES.length - 1
    return last ? [step] : [step, { label: 'Rest', seconds: REST, rest: true, detail: 'Shake out, breathe' }]
  }),
)

export function StrengthGuide() {
  return (
    <div className="stack">
      <section className="card guide-note">
        <p className="habit-sub">2× per week, ~20 min</p>
        <p className="muted small">
          On easy days or after an easy run — never the day before a hard session. Stop a set when form slips.
        </p>
      </section>
      <ul className="ex-grid">
        {EXERCISES.map((e) => (
          <li key={e.key} className="card ex-card">
            <Figure pose={e.pose} label={e.name} />
            <p className="ex-name">{e.name}</p>
            <p className="ex-dose">{e.dose}</p>
            <p className="muted small">{e.cue}</p>
          </li>
        ))}
      </ul>
      <section className="card">
        <StepTimer title="Today’s circuit" steps={CIRCUIT} />
      </section>
    </div>
  )
}
