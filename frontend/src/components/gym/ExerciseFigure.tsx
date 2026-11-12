/**
 * What the movement looks like, as one figure that actually does it.
 *
 * The first version of this drew two frames, start and end, side by side. That
 * is a diagram, and a diagram is the thing a person glances at and believes
 * they have understood. The mistake in a squat is never in either end position
 * — it is in the path between them, and two still pictures are precisely the
 * view that hides it.
 *
 * So: one figure, rigged on a skeleton, moving between the two poses on a loop.
 *
 * **Poses, not paths.** Each exercise is two sets of joint coordinates, and the
 * drawing is generated from them. Hand-written `d` strings cannot be morphed —
 * SMIL interpolates between two path strings only when their command sequences
 * match exactly, and keeping thirty hand-written strings in lockstep is a
 * promise nobody keeps past the third edit. A shared skeleton makes that
 * structural rather than a thing to remember.
 *
 * **SMIL rather than a library.** `<animate>` on `d` is supported everywhere
 * this app runs, costs nothing, and keeps the figures working with no network
 * and no JavaScript — which is the normal condition in a gym basement. The
 * alternative was ~40 kB of animation library per figure, into a PWA already
 * precaching 1.7 MB.
 *
 * Reduced motion is honoured by rendering the end pose and no `<animate>` at
 * all, rather than by pausing: a paused animation still ships the machinery.
 */

import { useEffect, useState } from 'react'

type Point = [number, number]

/**
 * One pose. Every exercise defines two, and every figure is drawn from the
 * same joints, so any two poses can morph into each other by construction.
 */
type Pose = {
  head: Point
  neck: Point
  hip: Point
  knee: Point
  ankle: Point
  // The far-side leg, drawn faded so it reads as depth rather than clutter.
  knee2: Point
  ankle2: Point
  elbow: Point
  wrist: Point
}

const spine = (p: Pose) => `M${p.neck[0]} ${p.neck[1]} L${p.hip[0]} ${p.hip[1]}`
const legA = (p: Pose) =>
  `M${p.hip[0]} ${p.hip[1]} L${p.knee[0]} ${p.knee[1]} L${p.ankle[0]} ${p.ankle[1]}`
const legB = (p: Pose) =>
  `M${p.hip[0]} ${p.hip[1]} L${p.knee2[0]} ${p.knee2[1]} L${p.ankle2[0]} ${p.ankle2[1]}`
const arm = (p: Pose) =>
  `M${p.neck[0]} ${p.neck[1]} L${p.elbow[0]} ${p.elbow[1]} L${p.wrist[0]} ${p.wrist[1]}`

/** Prop drawn behind the figure: a chair, a wall, a table. */
type Prop = { x: number; y: number; w: number; h: number }

type Move = {
  /** Seconds for one full out-and-back. Slow enough to copy, not so slow it stalls. */
  dur: number
  props?: Prop[]
  /** Dashed reference line between two joints, when the cue is about alignment. */
  guide?: [keyof Pose, keyof Pose]
  a: Pose
  b: Pose
}

const MOVES: Record<string, Move> = {
  'Box squat': {
    dur: 3.4,
    props: [{ x: 62, y: 64, w: 32, h: 5 }, { x: 88, y: 64, w: 5, h: 28 }],
    a: {
      head: [44, 20], neck: [44, 29], hip: [44, 57],
      knee: [44, 75], ankle: [44, 92], knee2: [40, 75], ankle2: [40, 92],
      elbow: [34, 42], wrist: [30, 54],
    },
    b: {
      // Hips back over the chair, shins near vertical, chest up. The hip
      // travelling backwards rather than the knee travelling forwards is the
      // entire movement, so it is the thing the animation has to show.
      head: [36, 34], neck: [38, 42], hip: [60, 62],
      knee: [46, 76], ankle: [44, 92], knee2: [42, 76], ankle2: [40, 92],
      elbow: [44, 48], wrist: [54, 44],
    },
  },
  'Wall push-up': {
    dur: 3.0,
    props: [{ x: 80, y: 8, w: 6, h: 84 }],
    a: {
      head: [48, 26], neck: [52, 33], hip: [40, 66],
      knee: [36, 80], ankle: [32, 92], knee2: [34, 80], ankle2: [30, 92],
      elbow: [64, 29], wrist: [79, 26],
    },
    b: {
      head: [60, 28], neck: [63, 35], hip: [45, 68],
      knee: [38, 80], ankle: [32, 92], knee2: [36, 80], ankle2: [30, 92],
      elbow: [70, 40], wrist: [79, 27],
    },
  },
  'Glute bridge': {
    dur: 3.2,
    guide: ['neck', 'knee'],
    a: {
      head: [16, 80], neck: [25, 82], hip: [52, 84],
      knee: [70, 76], ankle: [74, 92], knee2: [70, 80], ankle2: [76, 92],
      elbow: [32, 90], wrist: [44, 91],
    },
    b: {
      head: [16, 80], neck: [25, 81], hip: [52, 64],
      knee: [70, 74], ankle: [74, 92], knee2: [70, 78], ankle2: [76, 92],
      elbow: [32, 90], wrist: [44, 91],
    },
  },
  'Calf raise': {
    dur: 2.2,
    a: {
      head: [50, 22], neck: [50, 31], hip: [50, 62],
      knee: [50, 77], ankle: [50, 92], knee2: [46, 77], ankle2: [46, 92],
      elbow: [40, 44], wrist: [38, 56],
    },
    b: {
      // The whole body rises; the ankle is the joint that does it.
      head: [50, 13], neck: [50, 22], hip: [50, 53],
      knee: [50, 68], ankle: [50, 84], knee2: [46, 68], ankle2: [46, 84],
      elbow: [40, 35], wrist: [38, 47],
    },
  },
  'Table row': {
    dur: 3.0,
    props: [{ x: 6, y: 34, w: 88, h: 5 }],
    a: {
      head: [24, 76], neck: [32, 74], hip: [66, 79],
      knee: [78, 86], ankle: [90, 92], knee2: [78, 88], ankle2: [90, 93],
      elbow: [31, 58], wrist: [30, 40],
    },
    b: {
      head: [24, 60], neck: [32, 59], hip: [66, 72],
      knee: [78, 82], ankle: [90, 92], knee2: [78, 84], ankle2: [90, 93],
      elbow: [26, 50], wrist: [30, 40],
    },
  },
  'Dead bug': {
    dur: 3.6,
    guide: ['neck', 'hip'],
    a: {
      head: [18, 70], neck: [27, 72], hip: [58, 74],
      knee: [70, 58], ankle: [78, 48], knee2: [70, 86], ankle2: [80, 90],
      elbow: [26, 60], wrist: [30, 48],
    },
    b: {
      // Opposite arm and leg reach away; the back must not lift to let them.
      head: [18, 70], neck: [27, 72], hip: [58, 74],
      knee: [74, 70], ankle: [88, 68], knee2: [70, 84], ankle2: [78, 90],
      elbow: [18, 58], wrist: [10, 50],
    },
  },
}

/** Patterns fall back to a related movement so a new rung is never a blank box. */
const BY_PATTERN: Record<string, string> = {
  calf: 'Calf raise', squat: 'Box squat', hinge: 'Glute bridge',
  push: 'Wall push-up', pull: 'Table row', core: 'Dead bug',
}

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false)
  useEffect(() => {
    const query = window.matchMedia('(prefers-reduced-motion: reduce)')
    const sync = () => setReduced(query.matches)
    sync()
    query.addEventListener('change', sync)
    return () => query.removeEventListener('change', sync)
  }, [])
  return reduced
}

/** One limb, morphing between its two poses. */
function Limb({
  d, from, to, dur, animate, className, width = 5, opacity,
}: {
  d: (p: Pose) => string
  from: Pose
  to: Pose
  dur: number
  animate: boolean
  className: string
  width?: number
  opacity?: number
}) {
  const start = d(from)
  const end = d(to)
  return (
    <path
      d={animate ? start : end}
      className={className}
      strokeWidth={width}
      strokeLinecap="round"
      strokeLinejoin="round"
      fill="none"
      opacity={opacity}
    >
      {animate && (
        <animate
          attributeName="d"
          values={`${start};${end};${start}`}
          keyTimes="0;0.5;1"
          dur={`${dur}s`}
          repeatCount="indefinite"
          calcMode="spline"
          // Ease out and back in: real movement decelerates into the end
          // position and pauses there, which is also where the athlete is
          // meant to be looking.
          keySplines="0.4 0 0.2 1;0.4 0 0.2 1"
        />
      )}
    </path>
  )
}

export function ExerciseFigure({
  pattern, name, className = '',
}: { pattern: string; name: string; className?: string }) {
  const reduced = usePrefersReducedMotion()
  const move = MOVES[name] ?? MOVES[BY_PATTERN[pattern]]
  if (!move) return null

  const animate = !reduced
  const { a, b, dur } = move
  const guide = move.guide
    ? {
        from: `M${a[move.guide[0]][0]} ${a[move.guide[0]][1]} L${a[move.guide[1]][0]} ${a[move.guide[1]][1]}`,
        to: `M${b[move.guide[0]][0]} ${b[move.guide[0]][1]} L${b[move.guide[1]][0]} ${b[move.guide[1]][1]}`,
      }
    : null

  return (
    <div className={`exfig ${className}`}>
      <svg viewBox="0 0 100 100" role="img" aria-label={`${name} demonstration`}>
        <line x1="4" y1="92" x2="96" y2="92" className="exfig-ground" />
        {(move.props ?? []).map((p, i) => (
          <rect key={i} x={p.x} y={p.y} width={p.w} height={p.h} rx="1.5" className="exfig-prop" />
        ))}

        {guide && (
          <path d={animate ? guide.from : guide.to} className="exfig-guide" fill="none">
            {animate && (
              <animate attributeName="d" values={`${guide.from};${guide.to};${guide.from}`}
                       keyTimes="0;0.5;1" dur={`${dur}s`} repeatCount="indefinite" />
            )}
          </path>
        )}

        <Limb d={legB} from={a} to={b} dur={dur} animate={animate} className="exfig-body" opacity={0.4} />
        <Limb d={legA} from={a} to={b} dur={dur} animate={animate} className="exfig-body" />
        <Limb d={spine} from={a} to={b} dur={dur} animate={animate} className="exfig-body" />
        <Limb d={arm} from={a} to={b} dur={dur} animate={animate} className="exfig-body" width={4} />

        <circle r="7" cx={animate ? a.head[0] : b.head[0]} cy={animate ? a.head[1] : b.head[1]}
                className="exfig-head">
          {animate && (
            <>
              <animate attributeName="cx" values={`${a.head[0]};${b.head[0]};${a.head[0]}`}
                       keyTimes="0;0.5;1" dur={`${dur}s`} repeatCount="indefinite"
                       calcMode="spline" keySplines="0.4 0 0.2 1;0.4 0 0.2 1" />
              <animate attributeName="cy" values={`${a.head[1]};${b.head[1]};${a.head[1]}`}
                       keyTimes="0;0.5;1" dur={`${dur}s`} repeatCount="indefinite"
                       calcMode="spline" keySplines="0.4 0 0.2 1;0.4 0 0.2 1" />
            </>
          )}
        </circle>
      </svg>
    </div>
  )
}
