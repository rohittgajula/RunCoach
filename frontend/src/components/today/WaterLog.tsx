import { useEffect, useRef, useState } from 'react'
import { todayISO } from '../../lib/format'
import { errorText, useAddWater, useDeleteWater, useWater } from '../../lib/queries'
import type { WaterDay } from '../../lib/types'
import { DropIcon } from '../Icons'
import { Meter } from '../Kit'

const litres = (ml: number) => `${(ml / 1000).toFixed(ml % 100 ? 2 : 1)} L`

/**
 * R11 §D water log: progress against today's target (incl. the heat bonus), quick-add
 * 250 / 500 ml, a custom amount and a 6-second undo. Past days are read-only.
 */
export function WaterLog({ date, fallback, compact = false }: { date: string; fallback?: WaterDay | null; compact?: boolean }) {
  const q = useWater(date)
  const add = useAddWater()
  const del = useDeleteWater()
  const [custom, setCustom] = useState(false)
  const [amount, setAmount] = useState('')
  const [undo, setUndo] = useState<{ id: number; ml: number } | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const w = (q.data && q.data.date === date ? q.data : null) ?? (fallback && fallback.date === date ? fallback : null)
  const isToday = date === todayISO()

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])

  if (!w) return null

  const log = (ml: number) => {
    if (!Number.isFinite(ml) || ml < 50 || ml > 2000) return
    add.mutate({ ml }, {
      onSuccess: (r) => {
        setUndo({ id: r.log.id, ml })
        setCustom(false)
        setAmount('')
        if (timer.current) clearTimeout(timer.current)
        timer.current = setTimeout(() => setUndo(null), 6000)
      },
    })
  }
  const doUndo = () => {
    if (!undo) return
    del.mutate(undo.id, { onSettled: () => setUndo(null) })
  }
  const quick = w.quick_add?.length ? w.quick_add : [250, 500]
  const customMl = Number(amount)
  const customOk = Number.isFinite(customMl) && customMl >= 50 && customMl <= 2000

  return (
    <div className="water-log">
      <div className="water-row">
        <span className="water"><DropIcon size={16} /> <span className="num-strong">{litres(w.drunk_ml)}</span> / {litres(w.target_ml)} water</span>
        <span className="muted">
          {w.remaining_ml > 0 ? `${litres(w.remaining_ml)} to go` : 'Target reached'}
          {w.bonus_ml > 0 && !compact ? ` · incl. +${litres(w.bonus_ml)} for heat` : ''}
        </span>
      </div>
      <Meter value={w.drunk_ml} max={w.target_ml} topic="run" label="Water drunk vs target" />
      {isToday && (
        undo ? (
          <div className="water-undo" role="status">
            <span>Added {undo.ml} ml</span>
            <button type="button" className="btn btn-ghost btn-sm" onClick={doUndo} disabled={del.isPending}>Undo</button>
          </div>
        ) : custom ? (
          <form className="water-custom" onSubmit={(e) => { e.preventDefault(); if (customOk) log(customMl) }}>
            <input
              inputMode="numeric"
              aria-label="Amount of water in millilitres"
              placeholder="ml (50–2000)"
              value={amount}
              onChange={(e) => setAmount(e.target.value.replace(/[^\d]/g, ''))}
              autoFocus
            />
            <button type="submit" className="btn btn-primary btn-sm" disabled={!customOk || add.isPending}>Add</button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setCustom(false); setAmount('') }}>Cancel</button>
          </form>
        ) : (
          <div className="water-buttons">
            {quick.map((ml) => (
              <button key={ml} type="button" className="btn btn-secondary btn-sm" disabled={add.isPending} onClick={() => log(ml)} aria-label={`Add ${ml} millilitres of water`}>
                +{ml} ml
              </button>
            ))}
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => setCustom(true)}>Custom</button>
          </div>
        )
      )}
      {(add.isError || del.isError) && <p className="bad small">{errorText(add.error ?? del.error, 'Could not save that.')}</p>}
      {!compact && w.logs.length > 0 && (
        <p className="muted small">
          {w.logs.length} {w.logs.length === 1 ? 'drink' : 'drinks'} logged · last at{' '}
          {new Date(w.logs[w.logs.length - 1].at).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}
        </p>
      )}
    </div>
  )
}
