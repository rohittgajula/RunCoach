/**
 * One figure doing the movement, rigged well enough to copy.
 *
 * Three versions of this now. Two still frames was a diagram, and a diagram is
 * what somebody glances at, believes they understood, and then performs as a
 * knees-forward squat. One figure morphing between two poses fixed that, and
 * still moved like a puppet.
 *
 * The reason it moved like a puppet was not the joint count. It was that every
 * limb started and stopped at the same instant. Real movement is staggered: in
 * a squat the hips go back first and the knees follow a beat later, and the
 * arms are last because they are reacting rather than driving. Perfect lockstep
 * reads as mechanism; a quarter of a second of lag reads as a body. So each
 * limb now carries its own `lead` — where in the cycle it arrives — and the
 * easing is asymmetric, braking hard into the end position and drifting back.
 *
 * The skeleton grew to match: a two-segment spine so the torso can round, a
 * foot so the ankle has something to pivot on, and a shoulder and wrist. A calf
 * raise where the toe stays planted and everything above it rises is the detail
 * that makes it read as a calf raise rather than a hop.
 *
 * Still SMIL, still no dependency. The alternative was ~250 kB of animation
 * runtime plus 40–80 kB per exercise, into a PWA opened in a gym basement.
 */

import { useEffect, useState } from 'react'

type Point = [number, number]

/**
 * One pose. Every figure is drawn from the same joints, so any two poses morph
 * into each other by construction — which is what stops thirty hand-written
 * path strings from having to be kept in lockstep by hand.
 */
type Pose = {
  head: Point
  neck: Point
  chest: Point
  hip: Point
  knee: Point
  ankle: Point
  toe: Point
  knee2: Point
  ankle2: Point
  shoulder: Point
  elbow: Point
  wrist: Point
}

const at = (pose: Pose, joint: keyof Pose) => `${pose[joint][0]} ${pose[joint][1]}`

/**
 * Each limb is one path through a named chain of joints, with its own arrival
 * time. The spread across these `lead` values is the whole realism budget.
 */
const CHAINS: {
  key: string; joints: (keyof Pose)[]; width: number; lead: number; fade?: number
}[] = [
  // Far leg first and faded, so it reads as depth rather than clutter.
  { key: 'legFar', joints: ['hip', 'knee2', 'ankle2'], width: 5, lead: 0.52, fade: 0.38 },
  // The spine leads almost everything: the hips are what start a squat or a hinge.
  { key: 'spine', joints: ['neck', 'chest', 'hip'], width: 5.5, lead: 0.46 },
  { key: 'legNear', joints: ['hip', 'knee', 'ankle', 'toe'], width: 5, lead: 0.5 },
  // Arms arrive last. On most of these they are reacting, and moving them in
  // time with the hips is the single thing that most makes a figure look
  // mechanical.
  { key: 'arm', joints: ['shoulder', 'elbow', 'wrist'], width: 4, lead: 0.57 },
]

type Prop = { x: number; y: number; w: number; h: number }

type Move = {
  dur: number
  props?: Prop[]
  guide?: [keyof Pose, keyof Pose]
  facing: [number, number]
  surface: 'stand' | 'lie' | 'wall' | 'under'
  a: Pose
  b: Pose
}

const MOVES: Record<string, Move> = {
  // --- the warm-up ---------------------------------------------------------
  // Six moves that had no figure at all, so the top half of the Gym screen —
  // the part you actually read first, standing in the room about to start —
  // was a wall of prose. These are the cheapest figures to get right because
  // the cue is almost always "which limb goes where", and none of them carries
  // load, so nothing here can be performed dangerously by copying the drawing.
  'March on the spot': {
    // Fast and alternating: the one thing to show is knee height, hip or above.
    dur: 1.6, facing: [-1, 0], surface: 'stand',
    a: {
      head: [46, 18], neck: [46, 27], chest: [46, 38], hip: [46, 57],
      knee: [35, 55], ankle: [33, 69], toe: [25, 72],
      knee2: [47, 74], ankle2: [47, 90],
      shoulder: [46, 30], elbow: [53, 42], wrist: [57, 52],
    },
    b: {
      head: [46, 18], neck: [46, 27], chest: [46, 38], hip: [46, 57],
      knee: [45, 74], ankle: [45, 90], toe: [37, 91],
      knee2: [36, 55], ankle2: [34, 69],
      shoulder: [46, 30], elbow: [39, 42], wrist: [35, 52],
    },
  },
  'Leg swings': {
    // A hand stays on the wall throughout. Without the prop this reads as a
    // kick, which is the error — the point is a relaxed swing from a stable
    // trunk, not height.
    dur: 2.4, facing: [-1, 0], surface: 'stand',
    props: [{ x: 78, y: 6, w: 5, h: 86 }],
    a: {
      head: [50, 18], neck: [50, 27], chest: [50, 38], hip: [50, 57],
      knee: [40, 69], ankle: [34, 81], toe: [26, 84],
      knee2: [51, 74], ankle2: [51, 90],
      shoulder: [50, 30], elbow: [62, 31], wrist: [75, 29],
    },
    b: {
      head: [50, 18], neck: [50, 27], chest: [50, 38], hip: [50, 57],
      knee: [60, 70], ankle: [66, 81], toe: [74, 85],
      knee2: [51, 74], ankle2: [51, 90],
      shoulder: [50, 30], elbow: [62, 31], wrist: [75, 29],
    },
  },
  'Ankle rocks': {
    // Half-kneeling, and the whole movement is the front knee travelling
    // forward over the toes while the heel stays down. The heel is therefore
    // the one joint that must not move between the poses.
    dur: 2.8, facing: [-1, 0], surface: 'stand',
    a: {
      head: [50, 30], neck: [50, 38], chest: [50, 47], hip: [50, 62],
      knee: [42, 74], ankle: [42, 88], toe: [33, 90],
      knee2: [59, 80], ankle2: [70, 88],
      shoulder: [50, 41], elbow: [46, 52], wrist: [44, 62],
    },
    b: {
      head: [45, 32], neck: [46, 40], chest: [47, 49], hip: [50, 63],
      knee: [33, 74], ankle: [42, 88], toe: [33, 90],
      knee2: [59, 80], ankle2: [70, 88],
      shoulder: [46, 43], elbow: [42, 54], wrist: [40, 63],
    },
  },
  Clamshell: {
    // On the side, heels together, top knee opens. Drawn from above-behind so
    // the opening is visible at all; from the side it would be two lines
    // crossing.
    dur: 2.6, facing: [0, -1], surface: 'lie',
    a: {
      head: [17, 76], neck: [25, 77], chest: [38, 79], hip: [54, 81],
      knee: [66, 73], ankle: [58, 84], toe: [51, 88],
      knee2: [66, 77], ankle2: [58, 86],
      shoulder: [26, 79], elbow: [21, 86], wrist: [15, 90],
    },
    b: {
      head: [17, 76], neck: [25, 77], chest: [38, 79], hip: [54, 81],
      knee: [69, 61], ankle: [58, 82], toe: [51, 86],
      knee2: [66, 77], ankle2: [58, 86],
      shoulder: [26, 79], elbow: [21, 86], wrist: [15, 90],
    },
  },
  'Hip-flexor stretch': {
    // Half-kneeling again, but here nothing bends — the hips travel forward
    // and the back knee trails. People do this as a forward lean, which
    // stretches nothing, so the spine stays upright in both poses.
    dur: 3.0, facing: [-1, 0], surface: 'stand',
    a: {
      head: [48, 26], neck: [48, 34], chest: [48, 44], hip: [48, 60],
      knee: [38, 70], ankle: [36, 86], toe: [27, 88],
      knee2: [58, 80], ankle2: [70, 88],
      shoulder: [48, 37], elbow: [46, 48], wrist: [46, 58],
    },
    b: {
      head: [44, 24], neck: [45, 32], chest: [47, 42], hip: [53, 58],
      knee: [40, 70], ankle: [36, 86], toe: [27, 88],
      knee2: [64, 80], ankle2: [76, 88],
      shoulder: [45, 35], elbow: [43, 46], wrist: [43, 56],
    },
  },
  'A-skip': {
    // The fastest of the six and the only one that leaves the ground. Support
    // ankle rises to the toe at the top, which is what separates a skip from
    // a march.
    dur: 1.4, facing: [-1, 0], surface: 'stand',
    a: {
      head: [46, 14], neck: [46, 23], chest: [46, 34], hip: [46, 53],
      knee: [33, 50], ankle: [31, 64], toe: [23, 67],
      knee2: [48, 70], ankle2: [48, 86],
      shoulder: [46, 26], elbow: [56, 36], wrist: [62, 45],
    },
    b: {
      head: [46, 18], neck: [46, 27], chest: [46, 38], hip: [46, 57],
      knee: [44, 74], ankle: [44, 90], toe: [36, 91],
      knee2: [37, 56], ankle2: [35, 70],
      shoulder: [46, 30], elbow: [37, 40], wrist: [32, 49],
    },
  },

  // --- the session ---------------------------------------------------------
  'Box squat': {
    dur: 3.4, facing: [-1, 0], surface: 'stand',
    props: [{ x: 60, y: 63, w: 34, h: 5 }, { x: 89, y: 63, w: 5, h: 29 }],
    a: {
      head: [44, 18], neck: [44, 27], chest: [44, 38], hip: [44, 57],
      knee: [44, 74], ankle: [44, 90], toe: [35, 91],
      knee2: [41, 74], ankle2: [41, 90],
      shoulder: [44, 30], elbow: [38, 44], wrist: [36, 56],
    },
    b: {
      // The hips travel BACK rather than down: the shin stays near vertical and
      // the heel never leaves the floor. That is the whole movement, so it is
      // what the animation has to make obvious.
      head: [33, 33], neck: [36, 41], chest: [43, 50], hip: [58, 61],
      knee: [46, 76], ankle: [44, 90], toe: [35, 91],
      knee2: [43, 76], ankle2: [41, 90],
      shoulder: [37, 43], elbow: [46, 50], wrist: [55, 46],
    },
  },
  'Wall push-up': {
    dur: 3.0, facing: [1, 0], surface: 'wall',
    props: [{ x: 82, y: 6, w: 6, h: 86 }],
    a: {
      head: [46, 25], neck: [50, 32], chest: [48, 42], hip: [42, 62],
      knee: [38, 78], ankle: [33, 90], toe: [27, 91],
      knee2: [36, 78], ankle2: [31, 90],
      shoulder: [52, 31], elbow: [64, 28], wrist: [79, 26],
    },
    b: {
      // One line from head to heels throughout: the body travels as a unit and
      // only the elbow angle changes. Sagging hips is the error this rules out.
      head: [58, 27], neck: [61, 34], chest: [56, 44], hip: [47, 64],
      knee: [40, 79], ankle: [33, 90], toe: [27, 91],
      knee2: [38, 79], ankle2: [31, 90],
      shoulder: [63, 33], elbow: [70, 40], wrist: [79, 27],
    },
  },
  'Glute bridge': {
    dur: 3.2, facing: [0, -1], surface: 'lie', guide: ['shoulder', 'knee'],
    a: {
      head: [16, 80], neck: [24, 81], chest: [36, 83], hip: [52, 84],
      knee: [70, 77], ankle: [74, 90], toe: [81, 91],
      knee2: [70, 80], ankle2: [76, 90],
      shoulder: [25, 83], elbow: [33, 89], wrist: [43, 90],
    },
    b: {
      // Shoulders stay down, hips rise, knees barely move. The dashed guide runs
      // shoulder to knee, because that straight line IS the cue.
      head: [16, 80], neck: [24, 80], chest: [38, 71], hip: [54, 63],
      knee: [71, 74], ankle: [74, 90], toe: [81, 91],
      knee2: [71, 77], ankle2: [76, 90],
      shoulder: [25, 82], elbow: [33, 89], wrist: [43, 90],
    },
  },
  'Calf raise': {
    dur: 2.2, facing: [-1, 0], surface: 'stand',
    a: {
      head: [50, 21], neck: [50, 30], chest: [50, 40], hip: [50, 60],
      knee: [50, 76], ankle: [50, 90], toe: [41, 91],
      knee2: [47, 76], ankle2: [47, 90],
      shoulder: [50, 32], elbow: [44, 45], wrist: [42, 57],
    },
    b: {
      // The toe is the pivot and does not move; everything above it rises. The
      // heel lifting away from a planted toe is what makes this a calf raise
      // rather than a hop.
      head: [50, 13], neck: [50, 22], chest: [50, 32], hip: [50, 52],
      knee: [50, 68], ankle: [50, 83], toe: [41, 91],
      knee2: [47, 68], ankle2: [47, 83],
      shoulder: [50, 24], elbow: [44, 37], wrist: [42, 49],
    },
  },
  'Table row': {
    dur: 3.0, facing: [0, -1], surface: 'under',
    props: [{ x: 4, y: 34, w: 92, h: 5 }],
    a: {
      head: [24, 75], neck: [32, 74], chest: [44, 75], hip: [64, 78],
      knee: [78, 85], ankle: [90, 90], toe: [96, 89],
      knee2: [78, 87], ankle2: [90, 92],
      shoulder: [32, 72], elbow: [31, 56], wrist: [30, 40],
    },
    b: {
      // Hands stay on the table; the body comes up to meet them, straight from
      // shoulder to heel. The elbow is what bends.
      head: [24, 60], neck: [32, 59], chest: [44, 64], hip: [64, 72],
      knee: [78, 82], ankle: [90, 90], toe: [96, 89],
      knee2: [78, 84], ankle2: [90, 92],
      shoulder: [32, 57], elbow: [26, 49], wrist: [30, 40],
    },
  },
  'Dead bug': {
    dur: 3.6, facing: [0, -1], surface: 'lie', guide: ['chest', 'hip'],
    a: {
      head: [18, 70], neck: [26, 71], chest: [40, 73], hip: [58, 74],
      knee: [70, 58], ankle: [78, 48], toe: [84, 45],
      knee2: [70, 85], ankle2: [80, 90],
      shoulder: [27, 70], elbow: [32, 56], wrist: [36, 46],
    },
    b: {
      // Opposite arm and leg reach away from each other while the trunk does
      // not move at all — which is the exercise. The guide line stays put while
      // everything attached to it travels.
      head: [18, 70], neck: [26, 71], chest: [40, 73], hip: [58, 74],
      knee: [74, 70], ankle: [88, 67], toe: [94, 66],
      knee2: [70, 84], ankle2: [78, 90],
      shoulder: [27, 71], elbow: [18, 60], wrist: [10, 52],
    },
  },
}

const BY_PATTERN: Record<string, string> = {
  calf: 'Calf raise', squat: 'Box squat', hinge: 'Glute bridge',
  push: 'Wall push-up', pull: 'Table row', core: 'Dead bug',
  // The warm-up keys, which the session list passes as `pattern`. Without
  // these every warm-up move fell through to `return null`.
  march: 'March on the spot', legswing: 'Leg swings', anklerock: 'Ankle rocks',
  clam: 'Clamshell', hipflexor: 'Hip-flexor stretch', askip: 'A-skip',
}

/**
 * Brake hard into the end position, drift back out.
 *
 * Asymmetric on purpose. The end position is where the athlete is meant to be
 * looking, so the figure decelerates into it and sits there for an instant; the
 * return is the uninteresting half and gets out of the way.
 */
const SPLINES = '0.33 0 0.15 1;0.5 0 0.4 1'

/** The head rides with the spine, a fraction behind it. */
const HEAD_LEAD = 0.47

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

function Chain({
  chain, from, to, dur, animate,
}: {
  chain: (typeof CHAINS)[number]
  from: Pose
  to: Pose
  dur: number
  animate: boolean
}) {
  const draw = (pose: Pose) => 'M' + chain.joints.map((j) => at(pose, j)).join(' L')
  const start = draw(from)
  const end = draw(to)

  return (
    <path
      d={animate ? start : end}
      className="exfig-body"
      strokeWidth={chain.width}
      strokeLinecap="round"
      strokeLinejoin="round"
      fill="none"
      opacity={chain.fade}
    >
      {animate && (
        <animate
          attributeName="d"
          values={`${start};${end};${start}`}
          keyTimes={`0;${chain.lead};1`}
          dur={`${dur}s`}
          repeatCount="indefinite"
          calcMode="spline"
          keySplines={SPLINES}
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
  // A pattern id has to be unique per figure, or several on one page share the
  // first one — which looks fine until a figure is removed and the rest lose
  // their floor.
  const hatchId = `hatch-${name.replace(/\W+/g, '-').toLowerCase()}`
  const floorY = move.surface === 'lie' ? 88 : move.surface === 'under' ? 90 : 92

  // Which way the figure faces is carried by the head's OFFSET from the neck,
  // not by a line drawn out of it.
  //
  // The first version drew a nose — a stroke sticking out of the skull — which
  // read as a spike rather than a face. A head actually sits slightly forward
  // of the spine, so nudging the circle in the facing direction says the same
  // thing anatomically and disappears into the drawing instead of fighting it.
  const facedHead = (pose: Pose): [number, number] => {
    const [fx, fy] = move.facing
    return [pose.head[0] + fx * 2.5, pose.head[1] + fy * 2.5]
  }
  const headA = facedHead(a)
  const headB = facedHead(b)
  const guide = move.guide
    ? {
        from: `M${at(a, move.guide[0])} L${at(a, move.guide[1])}`,
        to: `M${at(b, move.guide[0])} L${at(b, move.guide[1])}`,
      }
    : null

  return (
    <div className={`exfig ${className}`}>
      <svg viewBox="0 0 100 100" role="img" aria-label={`${name} demonstration`}>
        <defs>
          <pattern id={hatchId} width="4" height="4" patternUnits="userSpaceOnUse"
                   patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="4" className="exfig-hatch" />
          </pattern>
        </defs>

        {/* The floor as a surface with thickness. A hairline under the heels is
            enough for a standing figure and tells you nothing about one lying
            down, which is how the supine movements became unreadable. */}
        <rect x="0" y={floorY} width="100" height={100 - floorY}
              fill={`url(#${hatchId})`} className="exfig-floor" />
        <line x1="0" y1={floorY} x2="100" y2={floorY} className="exfig-ground" />
        {move.surface === 'wall' && (
          <line x1="88" y1="0" x2="88" y2={floorY} className="exfig-ground" />
        )}
        {(move.props ?? []).map((prop, i) => (
          <rect key={i} x={prop.x} y={prop.y} width={prop.w} height={prop.h}
                rx="1.5" className="exfig-prop" />
        ))}

        {guide && (
          <path d={animate ? guide.from : guide.to} className="exfig-guide" fill="none">
            {animate && (
              <animate attributeName="d" values={`${guide.from};${guide.to};${guide.from}`}
                       keyTimes="0;0.46;1" dur={`${dur}s`} repeatCount="indefinite"
                       calcMode="spline" keySplines={SPLINES} />
            )}
          </path>
        )}

        {CHAINS.map((chain) => (
          <Chain key={chain.key} chain={chain} from={a} to={b} dur={dur} animate={animate} />
        ))}

        {/* Neck to head, so the skull is attached rather than floating. */}
        <path
          d={animate
            ? `M${at(a, 'neck')} L${headA[0]} ${headA[1]}`
            : `M${at(b, 'neck')} L${headB[0]} ${headB[1]}`}
          className="exfig-body" strokeWidth={4.5} strokeLinecap="round" fill="none"
        >
          {animate && (
            <animate
              attributeName="d"
              values={`M${at(a, 'neck')} L${headA[0]} ${headA[1]};M${at(b, 'neck')} L${headB[0]} ${headB[1]};M${at(a, 'neck')} L${headA[0]} ${headA[1]}`}
              keyTimes={`0;${HEAD_LEAD};1`} dur={`${dur}s`} repeatCount="indefinite"
              calcMode="spline" keySplines={SPLINES} />
          )}
        </path>

        <circle r="6.5" cx={animate ? headA[0] : headB[0]} cy={animate ? headA[1] : headB[1]}
                className="exfig-head">
          {animate && (
            <>
              <animate attributeName="cx" values={`${headA[0]};${headB[0]};${headA[0]}`}
                       keyTimes={`0;${HEAD_LEAD};1`} dur={`${dur}s`} repeatCount="indefinite"
                       calcMode="spline" keySplines={SPLINES} />
              <animate attributeName="cy" values={`${headA[1]};${headB[1]};${headA[1]}`}
                       keyTimes={`0;${HEAD_LEAD};1`} dur={`${dur}s`} repeatCount="indefinite"
                       calcMode="spline" keySplines={SPLINES} />
            </>
          )}
        </circle>
      </svg>
    </div>
  )
}
