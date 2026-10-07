import { useState } from 'react'
import { localInputValue, timeOfDay, todayISO } from '../../lib/format'
import { errorText, useDeleteHabitLog, useHabitLogs, useLogHabit } from '../../lib/queries'
import type { HabitKind, HabitLog } from '../../lib/types'
import { BottomSheet } from '../BottomSheet'
import { Field } from '../Field'
import { TrashIcon } from '../Icons'
import { CAFFEINE_TYPES, HABITS, countText, habitMeta, lessQty, minQty, moreQty, type CaffeineType, type HabitMeta } from './habitUtil'

/** Long-press / ⋯ on the quick-log row: quantity, time and a note. */
export function HabitLogSheet({
  kind, kinds = HABITS, onClose, onLogged,
}: { kind: HabitKind | null; kinds?: HabitMeta[]; onClose: () => void; onLogged: (log: HabitLog) => void }) {
  return (
    <BottomSheet open={kind != null} onClose={onClose} title="Log">
      {kind && <HabitLogForm key={kind} initialKind={kind} kinds={kinds} onClose={onClose} onLogged={onLogged} />}
    </BottomSheet>
  )
}

function HabitLogForm({
  initialKind, kinds, onClose, onLogged,
}: { initialKind: HabitKind; kinds: HabitMeta[]; onClose: () => void; onLogged: (log: HabitLog) => void }) {
  const log = useLogHabit()
  const [kind, setKind] = useState<HabitKind>(initialKind)
  const [quantity, setQuantity] = useState(1)
  const [at, setAt] = useState(() => localInputValue(new Date()))
  const [note, setNote] = useState('')
  const [subtype, setSubtype] = useState<CaffeineType>('coffee')
  const meta = habitMeta(kind)

  const save = () =>
    log.mutate(
      { kind, quantity, at: new Date(at).toISOString(), note: note.trim() || undefined, ...(kind === 'caffeine' ? { subtype } : {}) },
      { onSuccess: (saved) => { onLogged(saved); onClose() } },
    )

  return (
    <div className="stack">
      <div className={`segmented segmented-full habit-sheet-kinds ${kinds.length > 4 ? 'is-5' : kinds.length > 3 ? 'is-4' : ''}`} role="radiogroup" aria-label="What">
        {kinds.map((h) => (
          <button
            key={h.kind}
            type="button"
            role="radio"
            aria-checked={kind === h.kind}
            className={`segmented-option ${kind === h.kind ? 'is-active' : ''}`}
            onClick={() => { setKind(h.kind); setQuantity((q) => Math.max(minQty(h.kind), q)) }}
          >
            {h.emoji} {h.label}
          </button>
        ))}
      </div>
      <div className="habit-qty">
        <button type="button" className="chip" aria-label="Less" disabled={quantity <= minQty(kind)} onClick={() => setQuantity((q) => lessQty(kind, q))}>−</button>
        <div className="habit-qty-value">
          <span className="display">{quantity}</span>
          <span className="muted small">{quantity === 1 ? meta.unit : meta.units}</span>
        </div>
        <button type="button" className="chip" aria-label="More" onClick={() => setQuantity((q) => moreQty(kind, q))}>+</button>
      </div>
      <p className="muted small centered-text">To remove an entry, delete it below.</p>
      {kind === 'alcohol' && <p className="muted small centered-text">1 standard drink ≈ a small beer, a glass of wine or a single shot.</p>}
      {kind === 'sugar' && <p className="muted small centered-text">1 serving ≈ a chocolate bar, a dessert or a sugary drink.</p>}
      {kind === 'caffeine' && (
        <>
          <div className="chips-row caffeine-types" role="radiogroup" aria-label="What kind">
            {CAFFEINE_TYPES.map((t) => (
              <button key={t.key} type="button" role="radio" aria-checked={subtype === t.key} className={`pill-btn ${subtype === t.key ? 'is-active' : ''}`} onClick={() => setSubtype(t.key)}>
                <span aria-hidden="true">{t.emoji}</span> {t.label}
              </button>
            ))}
          </div>
          <p className="muted small centered-text">1 cup ≈ a coffee, two teas or a can of energy drink. After 14:00 counts as late.</p>
        </>
      )}
      <Field label="When">
        <input type="datetime-local" value={at} max={localInputValue(new Date())} onChange={(e) => setAt(e.target.value)} />
      </Field>
      <Field label="Note (optional)">
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder={kind === 'smoke' ? 'e.g. after lunch, stressed' : ''} />
      </Field>
      {log.isError && <p className="bad small">{errorText(log.error, 'Could not save. Try again.')}</p>}
      <button type="button" className="btn btn-primary btn-block" disabled={log.isPending || !at} onClick={save}>
        {log.isPending ? 'Saving…' : kind === 'private' ? `Log 🌙 ×${quantity}` : `Log ${quantity} ${quantity === 1 ? meta.unit : meta.units}`}
      </button>
      <TodayEntries kind={kind} />
    </div>
  )
}

/** Today's entries for this habit — fix a mistaken tap: −1 (latest) or delete any one. */
function TodayEntries({ kind }: { kind: HabitKind }) {
  const today = todayISO()
  const logs = useHabitLogs(kind, today, today)
  const remove = useDeleteHabitLog()
  const meta = habitMeta(kind)
  // Placeholder data may belong to the previously selected habit.
  const rows = (logs.data ?? []).filter((l) => l.kind === kind && l.local_date === today)
  const total = rows.reduce((s, l) => s + l.quantity, 0)
  const latest = rows[0]
  return (
    <div className="today-entries">
      <div className="today-entries-head">
        <span className="habit-sub">Today {meta.emoji} {kind === 'private' ? `×${total}` : countText(kind, total)}</span>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          disabled={!latest || remove.isPending}
          aria-label="Remove the most recent entry"
          onClick={() => latest && remove.mutate(latest)}
        >
          −1
        </button>
      </div>
      {logs.isPending && <p className="muted small">Loading today’s entries…</p>}
      {logs.data && !rows.length && <p className="muted small">Nothing logged today.</p>}
      {rows.length > 0 && (
        <ul className="entry-list">
          {rows.map((l) => (
            <li key={l.id} className="entry-line">
              <span className="grow">
                {kind === 'private' ? `🌙 ×${l.quantity}` : countText(kind, l.quantity)}
                <span className="muted small"> · {timeOfDay(l.at)}{l.note ? ` · ${l.note}` : ''}</span>
              </span>
              <button
                type="button"
                className="icon-btn"
                aria-label={`Delete the ${timeOfDay(l.at)} entry`}
                disabled={remove.isPending}
                onClick={() => remove.mutate(l)}
              >
                <TrashIcon size={18} />
              </button>
            </li>
          ))}
        </ul>
      )}
      {remove.isError && <p className="bad small">{errorText(remove.error, 'Could not delete. Try again.')}</p>}
    </div>
  )
}
