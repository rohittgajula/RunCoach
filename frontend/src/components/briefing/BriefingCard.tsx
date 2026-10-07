import { Link } from 'react-router-dom'
import { dur } from '../../lib/format'
import { errorText } from '../../lib/queries'
import { useBriefing, useBriefingAi, useDismissBriefing, type Briefing } from '../../lib/r13'
import { AdjustedChip } from '../adjust/AdjustedChip'
import { BellIcon, CloseIcon, SparkIcon } from '../Icons'
import { TopicRing } from '../Kit'
import { InfoButton } from '../health/InfoButton'

const NOTE_ICON: Record<string, string> = { injury: '🩹', habit: '🌱', sleep: '🌙', mood: '🙂', review: '📝' }

/**
 * R13 §6 "Good morning" — one card at the top of Today: readiness, today's session (and
 * any auto-adjustment), the best weather window + hydration, fuel, one focus, notes.
 * Dismissible for the day. Hidden before it's built (04:00) or when the endpoint is absent.
 */
export function BriefingCard() {
  const q = useBriefing()
  const dismiss = useDismissBriefing()
  const b = q.data
  if (!b || !b.ready || b.dismissed) return null
  return (
    <section className="card briefing" aria-label="Morning briefing">
      <div className="briefing-head">
        <div className="grow">
          <span className="lbl">Morning briefing{b.wake_time ? ` · ${b.wake_time}` : ''}</span>
          <h2 className="kit-title">{b.checkin?.headline || b.greeting}</h2>
        </div>
        <button type="button" className="chip briefing-close" aria-label="Dismiss today’s briefing" onClick={() => dismiss.mutate()}>
          <CloseIcon />
        </button>
      </div>
      <BriefingBody b={b} />
      <BriefingAi b={b} />
      <Link to="/me/reminders" className="briefing-remind small">
        <BellIcon size={16} /> Get this as a notification at wake-up
      </Link>
    </section>
  )
}

/** R14: the briefing's full content, inside Today's "See details" sheet. */
export function BriefingDetails() {
  const q = useBriefing()
  const b = q.data
  if (!b || !b.ready) return null
  return (
    <section className="card briefing" aria-label="Morning briefing">
      <span className="lbl">Morning briefing{b.wake_time ? ` · ${b.wake_time}` : ''}</span>
      <BriefingBody b={b} />
      <BriefingAi b={b} />
      <Link to="/me/reminders" className="briefing-remind small">
        <BellIcon size={16} /> Get this as a notification at wake-up
      </Link>
    </section>
  )
}

function BriefingBody({ b }: { b: Briefing }) {
  const s = b.session
  const w = b.weather
  return (
    <div className="briefing-body">
      <div className="briefing-row">
        <TopicRing value={b.readiness?.score ?? null} topic="recovery" size={64} stroke={12} label="Readiness" />
        <div className="grow">
          <span className="lbl">
            Readiness
            <InfoButton k="readiness" />
          </span>
          <p className="briefing-strong">{b.readiness?.label ?? (b.readiness?.score == null ? 'No score yet' : '')}</p>
        </div>
      </div>
      {(s?.workout || s?.strength) && (
        <div className="briefing-item">
          <span className="lbl">Today</span>
          {s.workout && <p className="briefing-strong">{s.workout.title} · {dur(s.workout.duration_s)}</p>}
          {s.strength && <p className="briefing-strong">{s.strength.title} · strength</p>}
          {s.adjustment && <AdjustedChip adjustment={s.adjustment} compact />}
        </div>
      )}
      {!s?.workout && !s?.strength && (
        <div className="briefing-item">
          <span className="lbl">Today</span>
          <p className="briefing-strong">Rest day — an easy walk is plenty.</p>
        </div>
      )}
      {w && (w.best_window || w.hydration) && (
        <div className="briefing-item">
          <span className="lbl">Weather{w.feels_like_max != null ? ` · feels like up to ${Math.round(w.feels_like_max)}°` : ''}</span>
          {w.best_window && <p className="briefing-strong">Best to run {w.best_window.start}–{w.best_window.end}</p>}
          {w.best_window?.reason && <p className="muted small">{w.best_window.reason}</p>}
          {w.hydration && (
            <p className="small">
              Drink {w.hydration.before_ml} ml before, ~{w.hydration.during_ml_per_h} ml/h during{w.hydration.electrolytes ? ' with electrolytes' : ''}. {w.hydration.after_note}
            </p>
          )}
        </div>
      )}
      {b.fuel && (
        <div className="briefing-item">
          <span className="lbl">Fuel today</span>
          <p className="briefing-strong">{b.fuel.kcal.toLocaleString()} kcal · {b.fuel.carbs_g} g carbs · {b.fuel.protein_g} g protein</p>
          <p className="muted small">Water {(b.fuel.water_ml / 1000).toFixed(1)} L</p>
        </div>
      )}
      {b.focus && (
        <div className="briefing-focus">
          <span className="lbl">One focus</span>
          <p>{b.focus.text}</p>
        </div>
      )}
      {b.notes.length > 0 && (
        <ul className="briefing-notes">
          {b.notes.map((n, i) => (
            <li key={i}><span aria-hidden="true">{NOTE_ICON[n.kind] ?? '•'}</span><span>{n.text}</span></li>
          ))}
        </ul>
      )}
    </div>
  )
}

function BriefingAi({ b }: { b: Briefing }) {
  const ai = useBriefingAi()
  const text = b.ai?.status === 'ready' ? b.ai.text : ''
  if (text) return <p className="briefing-ai"><SparkIcon size={14} /> {text}</p>
  return (
    <div className="briefing-ai-row">
      <button type="button" className="link-btn small" disabled={ai.isPending} onClick={() => ai.mutate(false)}>
        <SparkIcon size={14} /> {ai.isPending ? 'Writing…' : 'Say it in a sentence'}
      </button>
      {ai.isError && <span className="muted small">{errorText(ai.error, 'The coach is busy — the card above has everything.')}</span>}
    </div>
  )
}
