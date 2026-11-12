/**
 * Running form, drawn — and only the part that is worth drawing.
 *
 * Almost every beginner form diagram leads with foot strike: heel, midfoot,
 * forefoot. It is the wrong thing to lead with. Which part of the foot lands
 * first is mostly a consequence of *where* it lands, and a runner told to
 * "land midfoot" while still reaching out in front simply lands midfoot on a
 * straight leg, which is no better and sometimes worse.
 *
 * The thing that matters is how far in front of the hips the foot comes down.
 * A foot that lands well ahead of the body is a brake applied on every stride:
 * the leg is straight, the shock goes up through the knee rather than into a
 * bending ankle and hip, and the runner has to accelerate out of their own
 * landing. It is also the single most common cause of a run feeling harder
 * than its pace deserves.
 *
 * Cadence is the fix, and it is the fix precisely because it is measurable and
 * you cannot really overstride at a high step rate — taking more, shorter steps
 * pulls the landing back underneath you without anybody having to think about
 * their ankles mid-run. Rohit's logged cadence is 124 spm, which is low enough
 * that this is almost certainly his limiter rather than a theoretical one.
 */

type Props = { cadence?: number | null }

/** Roughly where most adult runners stop overstriding. Not a target to chase. */
const CADENCE_FLOOR = 160

function Runner({ over }: { over: boolean }) {
  // One figure, two leg positions. Everything else is identical on purpose:
  // the drawing has to isolate the variable or it is decoration.
  const footX = over ? 78 : 56
  const kneeX = over ? 70 : 54
  const hipX = 50

  return (
    <svg viewBox="0 0 100 100" role="presentation" focusable="false">
      <line x1="4" y1="92" x2="96" y2="92" className="exfig-ground" />

      {/* The hip line, dropped to the floor. The whole comparison is the gap
          between this and where the foot comes down. */}
      <line x1={hipX} y1="18" x2={hipX} y2="92" className="exfig-guide" />

      <circle cx={hipX - 2} cy={20} r={7} className="exfig-head" />
      <path
        d={`M${hipX - 1} 27 L${hipX} 54`}
        className="exfig-body" strokeWidth={5} strokeLinecap="round" fill="none"
      />
      {/* Lead leg: the one being compared. */}
      <path
        d={`M${hipX} 54 L${kneeX} 74 L${footX} 90`}
        className={`exfig-body ${over ? 'is-bad' : 'is-ok'}`}
        strokeWidth={5} strokeLinecap="round" strokeLinejoin="round" fill="none"
      />
      {/* Trailing leg, identical in both so it cannot distract. */}
      <path
        d={`M${hipX} 54 L${hipX - 12} 72 L${hipX - 22} 84`}
        className="exfig-body" strokeWidth={5} strokeLinecap="round"
        strokeLinejoin="round" fill="none" opacity={0.45}
      />
      {/* Arms. */}
      <path
        d={`M${hipX - 1} 34 L${hipX + 12} 44 M${hipX - 1} 34 L${hipX - 14} 46`}
        className="exfig-body" strokeWidth={4} strokeLinecap="round" fill="none"
      />

      {/* The measurement itself, because the point is the distance. */}
      <path
        d={`M${hipX} 96 L${footX} 96`}
        className={`exfig-measure ${over ? 'is-bad' : 'is-ok'}`}
        strokeWidth={2}
      />
    </svg>
  )
}

export function FormFigure({ cadence }: Props) {
  const low = typeof cadence === 'number' && cadence > 0 && cadence < CADENCE_FLOOR

  return (
    <section className="card">
      <h3>Where your foot lands</h3>

      <div className="formfig">
        <figure>
          <Runner over />
          <figcaption className="bad">Reaching ahead</figcaption>
        </figure>
        <span className="formfig-arrow" aria-hidden="true">→</span>
        <figure>
          <Runner over={false} />
          <figcaption className="ok">Landing under you</figcaption>
        </figure>
      </div>

      <p className="small">
        A foot that comes down well in front of your hips is a brake you apply on
        every stride. The leg is straight when it lands, so the shock travels up
        through the knee instead of being absorbed by a bending ankle and hip, and
        you have to accelerate out of your own landing.
      </p>

      <p className="small muted">
        Don't try to fix this by thinking about your feet mid-run — that mostly
        produces a different bad habit. Take <strong>more, shorter steps</strong>.
        The landing moves back underneath you on its own, because you cannot
        really overstride at a high step rate.
      </p>

      {low ? (
        <p className="small" style={{ marginTop: '0.6rem' }}>
          Your last runs averaged <strong className="num">{Math.round(cadence!)}</strong> steps
          a minute. Most adults stop overstriding somewhere around {CADENCE_FLOOR},
          so this is likely what is making a run feel harder than its pace deserves.
          Aim for about <strong className="num">{Math.round(cadence! + 5)}</strong> next
          time — five more than you do now, not a jump to a round number.
        </p>
      ) : (
        <p className="small muted" style={{ marginTop: '0.6rem' }}>
          Cadence is the number to watch here. It appears once a run with
          per-second data has been recorded.
        </p>
      )}
    </section>
  )
}
