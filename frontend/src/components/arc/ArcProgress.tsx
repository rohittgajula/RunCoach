/**
 * "Am I actually improving?" — the verdict, on the screen that asks the question.
 *
 * The full report has lived at Health → Progress for a long time and nobody
 * found it, which is a fair outcome for something four taps deep inside a tab
 * about sleep. It was computing a real answer — pace against heart rate across
 * your last runs, what to work on next — and showing it to nobody.
 *
 * The arc above draws the shape of the training. This draws the verdict on it.
 * Same question, two halves, so they go on the same screen; the detail stays
 * where it is rather than being duplicated here.
 */

import { Link } from 'react-router-dom'
import { ChevronRight } from '../Icons'
import { useProgress } from '../../lib/queries'
import type { ProgressFocus, ProgressHighlight } from '../../lib/types'

/** Five runs: enough that one bad morning does not read as a decline, few
 *  enough that it is still about now. */
const WINDOW = 5 as const

/** The focus list can run long; two is what fits before it stops being advice
 *  and starts being a to-do list. */
const SHOW_FOCUS = 2

function Verdict({ items }: { items: ProgressHighlight[] }) {
  return (
    <ul className="arcp-lines">
      {items.map((h) => (
        <li key={h.text} data-tone={h.tone}>{h.text}</li>
      ))}
    </ul>
  )
}

function Focus({ items }: { items: ProgressFocus[] }) {
  return (
    <div className="arcp-focus">
      <h3 className="arcp-h">What to work on</h3>
      <ul>
        {items.slice(0, SHOW_FOCUS).map((f) => (
          <li key={f.title}>
            <b>{f.title}</b>
            {f.why && <span>{f.why}</span>}
          </li>
        ))}
      </ul>
    </div>
  )
}

export function ArcProgress() {
  const query = useProgress({ window: WINDOW })
  const data = query.data

  // Silent while it loads: this sits under a chart that has already answered
  // most of the question, and a skeleton here would be the third spinner on
  // one screen.
  if (query.isPending || query.isError || !data) return null

  const highlights = data.highlights ?? []
  const focus = data.focus ?? []
  const enough = (data.previous_n ?? 0) > 0

  if (!enough) {
    return (
      <section className="card arc-card arcp">
        <h2 className="arc-h">Am I improving?</h2>
        <p className="muted small arcp-empty">
          Not enough behind you to say yet — this compares your last {WINDOW} runs
          with the {WINDOW} before them, and there is only one group so far. It
          fills in as you run.
        </p>
      </section>
    )
  }

  return (
    <section className="card arc-card arcp">
      <h2 className="arc-h">Am I improving?</h2>
      <p className="arcp-scope muted small">
        Your last {data.current_n ?? WINDOW} runs against the {data.previous_n} before them
      </p>

      {highlights.length > 0 && <Verdict items={highlights} />}
      {focus.length > 0 && <Focus items={focus} />}

      <Link to="/health/progress" className="arcp-more">
        <span>
          <b>The full report</b>
          <span className="muted small">Pace against heart rate, bests, records, coach review</span>
        </span>
        <ChevronRight />
      </Link>
    </section>
  )
}
