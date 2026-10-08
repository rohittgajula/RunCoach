import { useState } from 'react'
import { ILLNESS_LABEL, type Illness } from '../../lib/r17'
import IllnessSheet from './IllnessSheet'

/** Calm "Rest & recover" hero instead of the workout while illness mode is on. */
export default function IllnessHero({ illness }: { illness: Illness }) {
  const [open, setOpen] = useState(false)
  const day = illness.days_so_far || 1
  const expected = illness.expected_days && illness.expected_days >= day ? ` of ~${illness.expected_days}` : ''
  const below = illness.fever || illness.symptoms === 'below_neck'
  const advice = illness.advice?.[0] || (illness.type === 'injury'
    ? 'No running today. Gentle movement that doesn’t hurt is fine.'
    : below
      ? 'No running today. Sleep, fluids and rest come first — run again once you’ve been symptom-free for 24–48 hours.'
      : 'No workout today. An easy walk is fine if you feel up to it.')
  return (
    <section className="card today-hero ill-hero" aria-label="Rest and recover">
      <span className="lbl">{illness.type_label || ILLNESS_LABEL[illness.type] || 'Unwell'} · day {day}{expected}</span>
      <h2 className="today-headline">Rest &amp; recover</h2>
      <p className="ill-hero-text">{advice}</p>
      <p className="muted small">
        {illness.paused_workouts ? `${illness.paused_workouts} planned ${illness.paused_workouts === 1 ? 'session is' : 'sessions are'} paused. ` : 'Your plan is paused. '}
        Streaks won’t break.
      </p>
      <button type="button" className="btn btn-primary" onClick={() => setOpen(true)}>I’m better</button>
      <IllnessSheet mode="recover" open={open} onClose={() => setOpen(false)} />
    </section>
  )
}

