import { useState } from 'react'
import { localInputValue } from '../../lib/format'
import { errorText, useLogHabit } from '../../lib/queries'
import type { HabitKind, HabitLog } from '../../lib/types'
import { BottomSheet } from '../BottomSheet'
import { Field } from '../Field'
import { HABITS, habitMeta } from './habitUtil'

/** Long-press / ⋯ on the quick-log row: quantity, time and a note. */
export function HabitLogSheet({
  kind, onClose, onLogged,
}: { kind: HabitKind | null; onClose: () => void; onLogged: (log: HabitLog) => void }) {
  return (
    <BottomSheet open={kind != null} onClose={onClose} title="Log">
      {kind && <HabitLogForm key={kind} initialKind={kind} onClose={onClose} onLogged={onLogged} />}
    </BottomSheet>
  )
}

function HabitLogForm({
  initialKind, onClose, onLogged,
}: { initialKind: HabitKind; onClose: () => void; onLogged: (log: HabitLog) => void }) {
  const log = useLogHabit()
  const [kind, setKind] = useState<HabitKind>(initialKind)
  const [quantity, setQuantity] = useState(1)
  const [at, setAt] = useState(() => localInputValue(new Date()))
  const [note, setNote] = useState('')
  const meta = habitMeta(kind)

  const save = () =>
    log.mutate(
      { kind, quantity, at: new Date(at).toISOString(), note: note.trim() || undefined },
      { onSuccess: (saved) => { onLogged(saved); onClose() } },
    )

  return (
    <div className="stack">
      <div className="segmented segmented-full habit-sheet-kinds" role="radiogroup" aria-label="What">
        {HABITS.map((h) => (
          <button
            key={h.kind}
            type="button"
            role="radio"
            aria-checked={kind === h.kind}
            className={`segmented-option ${kind === h.kind ? 'is-active' : ''}`}
            onClick={() => setKind(h.kind)}
          >
            {h.emoji} {h.label}
          </button>
        ))}
      </div>
      <div className="habit-qty">
        <button type="button" className="chip" aria-label="Less" disabled={quantity <= 0.5} onClick={() => setQuantity((q) => Math.max(0.5, q - (q > 1 ? 1 : 0.5)))}>−</button>
        <div className="habit-qty-value">
          <span className="display">{quantity}</span>
          <span className="muted small">{quantity === 1 ? meta.unit : meta.units}</span>
        </div>
        <button type="button" className="chip" aria-label="More" onClick={() => setQuantity((q) => q + (q < 1 ? 0.5 : 1))}>+</button>
      </div>
      {kind === 'alcohol' && <p className="muted small centered-text">1 standard drink ≈ a small beer, a glass of wine or a single shot.</p>}
      {kind === 'sugar' && <p className="muted small centered-text">1 serving ≈ a chocolate bar, a dessert or a sugary drink.</p>}
      <Field label="When">
        <input type="datetime-local" value={at} max={localInputValue(new Date())} onChange={(e) => setAt(e.target.value)} />
      </Field>
      <Field label="Note (optional)">
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder={kind === 'smoke' ? 'e.g. after lunch, stressed' : ''} />
      </Field>
      {log.isError && <p className="bad small">{errorText(log.error, 'Could not save. Try again.')}</p>}
      <button type="button" className="btn btn-primary btn-block" disabled={log.isPending || !at} onClick={save}>
        {log.isPending ? 'Saving…' : `Log ${quantity} ${quantity === 1 ? meta.unit : meta.units}`}
      </button>
    </div>
  )
}
