import { useState } from 'react'
import { Link } from 'react-router-dom'
import { dayMonth, todayISO } from '../../lib/format'
import { errorText, useDeleteShoe, useGear, useSaveShoe } from '../../lib/queries'
import type { Shoe } from '../../lib/types'
import { Field } from '../Field'
import { ChevronRight, ShoeIcon } from '../Icons'
import { CardHead, Meter, Pill, ToneChip } from '../Kit'
import { Empty, ErrorState, Skeleton } from '../States'

const kmText = (v: number) => `${Math.round(v).toLocaleString()} km`

function ReplaceChip({ shoe }: { shoe: Shoe }) {
  if (shoe.retired) return <Pill>Retired</Pill>
  if (shoe.replace_due) return <ToneChip tone="bad">! Replace now</ToneChip>
  if (shoe.replace_soon) return <ToneChip tone="bad">Replace soon</ToneChip>
  return null
}

function ShoeRow({ shoe, editable = true }: { shoe: Shoe; editable?: boolean }) {
  const save = useSaveShoe()
  const remove = useDeleteShoe()
  const [editing, setEditing] = useState(false)
  const [retireKm, setRetireKm] = useState(String(Math.round(shoe.retire_km)))
  const [confirm, setConfirm] = useState(false)
  const error = save.error ?? remove.error
  return (
    <div className="shoe">
      <div className="shoe-head">
        <span className="shoe-name">{shoe.name}</span>
        {shoe.is_default && !shoe.retired && <Pill topic="run">Default</Pill>}
        <ReplaceChip shoe={shoe} />
      </div>
      <Meter value={shoe.distance_km} max={shoe.retire_km} topic="run" over={shoe.replace_due} label={`${shoe.name}: ${kmText(shoe.distance_km)} of ${kmText(shoe.retire_km)}`} />
      <div className="fuel-row-line small">
        <span className="shoe-km">{kmText(shoe.distance_km)} <span className="muted">of {kmText(shoe.retire_km)}</span></span>
        <span className="muted">
          {shoe.retired ? '' : `${kmText(Math.max(0, shoe.remaining_km))} left · `}
          {shoe.activities} {shoe.activities === 1 ? 'run' : 'runs'}{shoe.brand ? ` · ${shoe.brand}` : ''}{shoe.source === 'garmin' ? ' · Garmin' : ''}
        </span>
      </div>
      {shoe.last_used && <span className="muted small">Last run {dayMonth(shoe.last_used)}</span>}
      {editable && (
        editing ? (
          <div className="inline-form">
            <Field label="Replace at (km)">
              <input inputMode="numeric" value={retireKm} onChange={(e) => setRetireKm(e.target.value)} />
            </Field>
            <div className="row-end">
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditing(false)}>Cancel</button>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                disabled={save.isPending || !(Number(retireKm) >= 100 && Number(retireKm) <= 2000)}
                onClick={() => save.mutate({ id: shoe.id, retire_km: Number(retireKm) }, { onSuccess: () => setEditing(false) })}
              >
                Save
              </button>
            </div>
          </div>
        ) : confirm ? (
          <div className="confirm-box">
            <p className="small">Delete {shoe.name}? Its runs stay; they just lose the shoe.</p>
            <div className="row-end">
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setConfirm(false)}>Keep</button>
              <button type="button" className="btn btn-confirm-danger btn-sm" disabled={remove.isPending} onClick={() => remove.mutate(shoe.id)}>Delete</button>
            </div>
          </div>
        ) : (
          <div className="row-wrap">
            {!shoe.is_default && !shoe.retired && (
              <button type="button" className="btn btn-secondary btn-sm" disabled={save.isPending} onClick={() => save.mutate({ id: shoe.id, is_default: true })}>Make default</button>
            )}
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => setEditing(true)}>Replace at…</button>
            <button type="button" className="btn btn-secondary btn-sm" disabled={save.isPending} onClick={() => save.mutate({ id: shoe.id, retired: !shoe.retired })}>
              {shoe.retired ? 'Back in use' : 'Retire'}
            </button>
            {shoe.source === 'local' && (
              <button type="button" className="btn btn-danger btn-sm" onClick={() => setConfirm(true)}>Delete</button>
            )}
          </div>
        )
      )}
      {error && <p className="bad small">{errorText(error, 'Could not save that.')}</p>}
    </div>
  )
}

function AddShoe({ defaultKm, first }: { defaultKm: number; first: boolean }) {
  const save = useSaveShoe()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [brand, setBrand] = useState('')
  const [startKm, setStartKm] = useState('0')
  const [retireKm, setRetireKm] = useState(String(defaultKm))
  const [since, setSince] = useState(todayISO())
  const [isDefault, setIsDefault] = useState(first)

  if (!open) {
    return <button type="button" className="btn btn-primary btn-block" onClick={() => setOpen(true)}>Add a shoe</button>
  }
  const valid = name.trim().length > 0 && Number(retireKm) >= 100 && Number(retireKm) <= 2000 && Number(startKm) >= 0
  return (
    <section className="card stack">
      <CardHead title="New shoe" />
      <Field label="Name"><input value={name} maxLength={80} onChange={(e) => setName(e.target.value)} placeholder="e.g. Pegasus 41" /></Field>
      <Field label="Brand (optional)"><input value={brand} onChange={(e) => setBrand(e.target.value)} /></Field>
      <div className="grid-2 grid-2-even">
        <Field label="Already run (km)"><input inputMode="numeric" value={startKm} onChange={(e) => setStartKm(e.target.value)} /></Field>
        <Field label="Replace at (km)"><input inputMode="numeric" value={retireKm} onChange={(e) => setRetireKm(e.target.value)} /></Field>
      </div>
      <Field label="In use since" hint="Runs from this day with no shoe count for the default shoe.">
        <input type="date" value={since} max={todayISO()} onChange={(e) => setSince(e.target.value)} />
      </Field>
      <div className="switch-row">
        <span className="grow"><strong>Default shoe</strong><span className="muted small block">New runs are counted on it</span></span>
        <button type="button" role="switch" aria-checked={isDefault} aria-label="Default shoe" className={`switch ${isDefault ? 'is-on' : ''}`} onClick={() => setIsDefault(!isDefault)} />
      </div>
      {save.isError && <p className="field-error">{errorText(save.error, 'Could not add the shoe.')}</p>}
      <div className="row-end">
        <button type="button" className="btn btn-ghost" onClick={() => setOpen(false)}>Cancel</button>
        <button
          type="button"
          className="btn btn-primary"
          disabled={!valid || save.isPending}
          onClick={() =>
            save.mutate(
              { name: name.trim(), brand: brand.trim(), start_km: Number(startKm), retire_km: Number(retireKm), is_default: isDefault, in_use_since: since || null },
              { onSuccess: () => { setOpen(false); setName(''); setBrand(''); setStartKm('0') } },
            )
          }
        >
          {save.isPending ? 'Adding…' : 'Add shoe'}
        </button>
      </div>
    </section>
  )
}

/** Me → Shoes: mileage against "replace at", Garmin gear plus your own shoes. */
export function ShoesSection() {
  const gear = useGear()
  const g = gear.data
  if (gear.isPending) return <section className="card"><Skeleton lines={4} /></section>
  if (gear.isError) return <ErrorState message={errorText(gear.error)} onRetry={() => gear.refetch()} />
  if (!g) return <Empty title="Shoes aren’t available yet">Check back after the next update.</Empty>
  const active = g.shoes.filter((s) => !s.retired)
  const retired = g.shoes.filter((s) => s.retired)
  return (
    <div className="stack">
      {active.length > 0 ? (
        <section className="card">
          <CardHead title="In use" sub={`Most shoes last ${g.default_retire_km}–800 km. We remind you at 90 %.`} />
          {active.map((s) => <ShoeRow key={s.id} shoe={s} />)}
        </section>
      ) : (
        <Empty icon={<ShoeIcon size={32} />} title="No shoes yet">
          Add the pair you run in — or add them in Garmin Connect and sync. Runs count towards your default shoe.
        </Empty>
      )}
      <AddShoe defaultKm={g.default_retire_km} first={!active.length} />
      {retired.length > 0 && (
        <section className="card">
          <CardHead title="Retired" />
          {retired.map((s) => <ShoeRow key={s.id} shoe={s} />)}
        </section>
      )}
    </div>
  )
}

export function ShoesTeaser() {
  const gear = useGear()
  const shoes = (gear.data?.shoes ?? []).filter((s) => !s.retired)
  if (!gear.data) return null
  const main = shoes.find((s) => s.is_default) ?? shoes[0]
  const due = shoes.filter((s) => s.replace_soon || s.replace_due)
  return (
    <Link to="/me/shoes" className="card me-teaser">
      <div className="kit-head">
        <span className="link-row-icon"><ShoeIcon /></span>
        <span className="grow">
          <span className="link-row-title">Shoes</span>
          <span className="link-row-text">
            {main ? `${main.name} · ${kmText(main.distance_km)} of ${kmText(main.retire_km)}` : 'Track mileage and get a reminder to replace them'}
          </span>
        </span>
        <ChevronRight size={18} className="muted" />
      </div>
      {main && <Meter value={main.distance_km} max={main.retire_km} topic="run" over={main.replace_due} label={`${main.name} mileage`} />}
      {due.length > 0 && <p className="bad small">{due.some((s) => s.replace_due) ? 'Time to replace' : 'Replace soon'}: {due.map((s) => s.name).join(', ')}</p>}
    </Link>
  )
}
