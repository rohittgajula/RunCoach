import { useState } from 'react'
import { addDays, dayMonth, localInputValue, timeOfDay, todayISO, weekday } from '../../lib/format'
import { errorText, useDeleteHabitLog, useHabitLogs, useUpdateHabitLog } from '../../lib/queries'
import type { HabitKind, HabitLog, InsightRange } from '../../lib/types'
import { BottomSheet } from '../BottomSheet'
import { Field } from '../Field'
import { TrashIcon } from '../Icons'
import { InsightCard } from '../insights/Tile'
import { Skeleton } from '../States'
import { countText, habitMeta, lessQty, minQty, moreQty, type HabitMeta } from './habitUtil'

const RANGE_DAYS: Record<InsightRange, number> = { '4w': 28, '12w': 84, '6m': 182 }
const PAGE = 40

const qtyText = (log: HabitLog) => (log.kind === 'private' ? `🌙 ×${log.quantity}` : countText(log.kind, log.quantity))

/** Every log in the range, newest first, filter by habit; tap to edit or delete. */
export function LogHistory({ range, kinds }: { range: InsightRange; kinds: HabitMeta[] }) {
  const [filter, setFilter] = useState<HabitKind | 'all'>('all')
  const [limit, setLimit] = useState(PAGE)
  const [editing, setEditing] = useState<HabitLog | null>(null)
  const end = todayISO()
  const start = addDays(end, -(RANGE_DAYS[range] - 1))
  const logs = useHabitLogs(filter === 'all' ? null : filter, start, end)
  const remove = useDeleteHabitLog()
  const [confirmId, setConfirmId] = useState<number | null>(null)
  const allowed = new Set(kinds.map((k) => k.kind))
  const rows = (logs.data ?? []).filter((l) => allowed.has(l.kind))
  const shown = rows.slice(0, limit)

  // Group by local day.
  const days: Array<{ date: string; logs: HabitLog[] }> = []
  for (const log of shown) {
    const last = days[days.length - 1]
    if (last && last.date === log.local_date) last.logs.push(log)
    else days.push({ date: log.local_date, logs: [log] })
  }

  return (
    <InsightCard title="Log history">
      <div className="chips-row chips-row-sm" role="radiogroup" aria-label="Habit">
        {[{ key: 'all' as const, label: 'All' }, ...kinds.map((k) => ({ key: k.kind, label: `${k.emoji} ${k.label}` }))].map((c) => (
          <button
            key={c.key}
            type="button"
            role="radio"
            aria-checked={filter === c.key}
            className={`pill-btn ${filter === c.key ? 'is-active' : ''}`}
            onClick={() => { setFilter(c.key); setLimit(PAGE) }}
          >
            {c.label}
          </button>
        ))}
      </div>
      {logs.isPending && <Skeleton lines={4} />}
      {logs.isError && <p className="bad small">{errorText(logs.error, 'Logs did not load.')}</p>}
      {remove.isError && <p className="bad small">{errorText(remove.error, 'Could not delete. Try again.')}</p>}
      {logs.data && !rows.length && <p className="muted small">No logs in this range.</p>}
      {days.length > 0 && (
        <ul className={`log-days ${logs.isPlaceholderData ? 'is-stale' : ''}`}>
          {days.map((d) => (
            <li key={d.date}>
              <p className="log-day">{d.date === end ? 'Today' : `${weekday(d.date)} ${dayMonth(d.date)}`}</p>
              <ul className="log-rows">
                {d.logs.map((log) => (
                  <li key={log.id} className="log-item">
                    <button type="button" className="log-row" onClick={() => setEditing(log)}>
                      <span className="log-emoji" aria-hidden="true">{habitMeta(log.kind).emoji}</span>
                      <span className="grow">
                        <span className="log-qty">{qtyText(log)}</span>
                        {log.note && <span className="muted small block log-note">{log.note}</span>}
                      </span>
                      <span className="muted small">{timeOfDay(log.at)}</span>
                    </button>
                    {confirmId === log.id ? (
                      <button
                        type="button"
                        className="btn btn-sm btn-confirm-danger"
                        disabled={remove.isPending}
                        onClick={() => remove.mutate(log, { onSettled: () => setConfirmId(null) })}
                      >
                        {remove.isPending ? '…' : 'Delete'}
                      </button>
                    ) : (
                      <button type="button" className="icon-btn" aria-label="Delete this log" onClick={() => setConfirmId(log.id)}>
                        <TrashIcon size={18} />
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
      {rows.length > limit && (
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => setLimit((n) => n + PAGE)}>
          Show more
        </button>
      )}
      <BottomSheet open={editing != null} onClose={() => setEditing(null)} title="Edit log">
        {editing && <EditLog key={editing.id} log={editing} onDone={() => setEditing(null)} />}
      </BottomSheet>
    </InsightCard>
  )
}

function EditLog({ log, onDone }: { log: HabitLog; onDone: () => void }) {
  const update = useUpdateHabitLog()
  const remove = useDeleteHabitLog()
  const [quantity, setQuantity] = useState(log.quantity)
  const [at, setAt] = useState(() => localInputValue(new Date(log.at)))
  const [note, setNote] = useState(log.note ?? '')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const meta = habitMeta(log.kind)
  const busy = update.isPending || remove.isPending

  const save = () =>
    update.mutate({ id: log.id, quantity, at: new Date(at).toISOString(), note: note.trim() }, { onSuccess: onDone })

  return (
    <div className="stack">
      <p className="centered-text"><span aria-hidden="true">{meta.emoji}</span> {meta.label}</p>
      <div className="habit-qty">
        <button type="button" className="chip" aria-label="Less" disabled={quantity <= minQty(log.kind)} onClick={() => setQuantity((q) => lessQty(log.kind, q))}>−</button>
        <div className="habit-qty-value">
          <span className="display">{quantity}</span>
          <span className="muted small">{quantity === 1 ? meta.unit : meta.units}</span>
        </div>
        <button type="button" className="chip" aria-label="More" onClick={() => setQuantity((q) => moreQty(log.kind, q))}>+</button>
      </div>
      <p className="muted small centered-text">To remove an entry, delete it below.</p>
      <Field label="When">
        <input type="datetime-local" value={at} max={localInputValue(new Date())} onChange={(e) => setAt(e.target.value)} />
      </Field>
      <Field label="Note (optional)">
        <input value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} />
      </Field>
      {update.isError && <p className="bad small">{errorText(update.error, 'Could not save. Try again.')}</p>}
      {remove.isError && <p className="bad small">{errorText(remove.error, 'Could not delete. Try again.')}</p>}
      {confirmDelete ? (
        <div className="confirm-box">
          <p className="small">Delete this log?</p>
          <div className="row-end">
            <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => setConfirmDelete(false)}>Cancel</button>
            <button type="button" className="btn btn-sm btn-confirm-danger" disabled={busy} onClick={() => remove.mutate(log, { onSuccess: onDone })}>
              {remove.isPending ? 'Deleting…' : 'Delete'}
            </button>
          </div>
        </div>
      ) : (
        <div className="row-end">
          <button type="button" className="btn btn-danger btn-sm mr-auto" disabled={busy} onClick={() => setConfirmDelete(true)}>Delete</button>
          <button type="button" className="btn btn-primary" disabled={busy || !at} onClick={save}>
            {update.isPending ? 'Saving…' : 'Save'}
          </button>
        </div>
      )}
    </div>
  )
}
