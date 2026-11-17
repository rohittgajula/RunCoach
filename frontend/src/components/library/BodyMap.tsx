/**
 * Front and back figures with the worked muscles filled in.
 *
 * Drawn here rather than sourced, for the same reason the library runs on
 * public-domain data: the muscle-highlighted anatomical renders every fitness
 * app uses come from a handful of commercial suppliers, and shipping somebody
 * else's artwork without a licence is a takedown waiting to happen. This is
 * crude next to those, and it is ours.
 *
 * Built from discrete parts rather than one outline with highlights clipped
 * inside it. The first version did it the other way and drew a blob: a single
 * path has to get arms, torso and legs right in one stroke, and when it does
 * not, nothing about the result tells you which bit was wrong. With a part per
 * shape the figure reads, and the highlight cannot drift out of alignment with
 * the body because the part IS the highlight.
 *
 * Deliberately not an anatomy diagram. It answers one question — "where does
 * this land?" — at a glance, on a phone, from arm's length.
 */

type Shape =
  | { kind: 'rect'; x: number; y: number; w: number; h: number; r?: number }
  | { kind: 'ellipse'; cx: number; cy: number; rx: number; ry: number }

type Part = {
  id: string
  side: 'front' | 'back' | 'both'
  /** Muscles that light this part up. Empty = structural only (head, feet). */
  muscles: string[]
  shapes: Shape[]
}

const r = (x: number, y: number, w: number, h: number, rad = 3): Shape =>
  ({ kind: 'rect', x, y, w, h, r: rad })

/** One figure in a 100 × 230 box. Mirrored pairs are listed as two shapes of
 *  the same part so a muscle lights both limbs at once. */
const PARTS: Part[] = [
  { id: 'head', side: 'both', muscles: [],
    shapes: [{ kind: 'ellipse', cx: 50, cy: 20, rx: 9, ry: 11 }] },
  { id: 'neck', side: 'both', muscles: ['trapezius'], shapes: [r(45, 30, 10, 7, 2)] },

  { id: 'shoulders', side: 'both',
    muscles: ['anterior_deltoid', 'lateral_deltoid', 'posterior_deltoid',
              'infraspinatus_teres_minor', 'supraspinatus'],
    shapes: [{ kind: 'ellipse', cx: 31, cy: 44, rx: 9, ry: 8 },
             { kind: 'ellipse', cx: 69, cy: 44, rx: 9, ry: 8 }] },

  { id: 'chest', side: 'front', muscles: ['pectoralis_major', 'serratus_anterior'],
    shapes: [r(37, 38, 26, 18, 5)] },
  { id: 'abs', side: 'front',
    muscles: ['rectus_abdominis', 'transverse_abdominis', 'hip_flexors'],
    shapes: [r(40, 57, 20, 26, 4)] },
  { id: 'obliques', side: 'front', muscles: ['obliques'],
    shapes: [r(34, 59, 5, 22, 2), r(61, 59, 5, 22, 2)] },

  { id: 'traps', side: 'back', muscles: ['trapezius'], shapes: [r(38, 37, 24, 13, 4)] },
  { id: 'upperback', side: 'back', muscles: ['latissimus_dorsi', 'rhomboids'],
    shapes: [r(36, 51, 28, 20, 4)] },
  { id: 'lowerback', side: 'back', muscles: ['erector_spinae', 'quadratus_lumborum'],
    shapes: [r(40, 72, 20, 12, 3)] },

  { id: 'upperarm', side: 'both',
    muscles: ['biceps_brachii', 'brachialis', 'triceps_brachii'],
    shapes: [r(22, 52, 9, 24, 4), r(69, 52, 9, 24, 4)] },
  { id: 'forearm', side: 'both',
    muscles: ['forearm_flexors', 'forearm_extensors', 'forearms', 'brachioradialis'],
    shapes: [r(21, 78, 8, 24, 4), r(71, 78, 8, 24, 4)] },

  { id: 'hips', side: 'both', muscles: ['gluteus_maximus', 'gluteus_medius'],
    shapes: [r(37, 85, 26, 17, 5)] },

  { id: 'outerhip', side: 'front', muscles: ['abductors'],
    shapes: [r(33, 104, 6, 30, 3), r(61, 104, 6, 30, 3)] },
  { id: 'innerthigh', side: 'front', muscles: ['adductors'], shapes: [r(46, 104, 8, 30, 3)] },
  { id: 'thighfront', side: 'front', muscles: ['quadriceps'],
    shapes: [r(39, 104, 7, 40, 3), r(54, 104, 7, 40, 3)] },
  { id: 'thighback', side: 'back', muscles: ['hamstrings'],
    shapes: [r(37, 104, 11, 40, 4), r(52, 104, 11, 40, 4)] },

  { id: 'calf', side: 'both', muscles: ['gastrocnemius', 'soleus'],
    shapes: [r(38, 148, 9, 32, 4), r(53, 148, 9, 32, 4)] },
  { id: 'shin', side: 'front', muscles: ['tibialis_anterior'],
    shapes: [r(40, 148, 4, 30, 2), r(55, 148, 4, 30, 2)] },
  { id: 'feet', side: 'both', muscles: [],
    shapes: [r(37, 183, 11, 6, 2), r(52, 183, 11, 6, 2)] },
]

function draw(shape: Shape, key: string, className: string) {
  if (shape.kind === 'ellipse') {
    return <ellipse key={key} cx={shape.cx} cy={shape.cy} rx={shape.rx} ry={shape.ry}
                    className={className} />
  }
  return <rect key={key} x={shape.x} y={shape.y} width={shape.w} height={shape.h}
               rx={shape.r} className={className} />
}

function Figure({ side, primary, secondary, label }: {
  side: 'front' | 'back'; primary: Set<string>; secondary: Set<string>; label: string
}) {
  const parts = PARTS.filter((p) => p.side === side || p.side === 'both')
  return (
    <figure className="bodymap-one">
      <svg viewBox="0 0 100 196" className="bodymap-fig" role="img" aria-label={label}>
        {parts.map((part) => {
          // Biceps are a front-view muscle and triceps a back-view one; the
          // upper arm is one part on both views, so which muscle lights it
          // depends on which way the figure is facing.
          const lights = part.muscles.filter(
            (m) => !(side === 'front' && m === 'triceps_brachii')
                   && !(side === 'back' && (m === 'biceps_brachii' || m === 'brachialis')),
          )
          const hot = lights.some((m) => primary.has(m))
          const warm = !hot && lights.some((m) => secondary.has(m))
          const cls = hot ? 'bodymap-prime' : warm ? 'bodymap-second' : 'bodymap-body'
          return part.shapes.map((shape, i) => draw(shape, `${part.id}${i}`, cls))
        })}
      </svg>
      <figcaption className="bodymap-cap">{label}</figcaption>
    </figure>
  )
}

export function BodyMap({ primary, secondary = [] }: {
  primary: string[]; secondary?: string[]
}) {
  const hot = new Set(primary)
  const warm = new Set(secondary)
  return (
    <div className="bodymap">
      <Figure side="front" primary={hot} secondary={warm} label="Front" />
      <Figure side="back" primary={hot} secondary={warm} label="Back" />
    </div>
  )
}
