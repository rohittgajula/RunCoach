/**
 * What he eats, and what he can actually produce where he lives.
 *
 * This exists because a plan is only as good as its constraints. A 116 g protein
 * target means one thing with an induction plate and eggs, and quite another on
 * a PG plate he has no say over — and a plan that ignores the difference is a
 * plan that gets ignored back.
 *
 * The foods come from the server rather than being typed, so a dislike is a key
 * the planner will actually honour instead of a word that silently matches
 * nothing.
 */

import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, json } from '../../lib/auth'
import { errorText } from '../../lib/queries'
import { CheckIcon } from '../Icons'
import { Skeleton } from '../States'

type Option = { value: string; label: string }
type Profile = {
  pattern: string; prep: string
  provided: string[]; dislikes: string[]; staples: string[]; notes: string
  patterns: Option[]; preps: Option[]; slots: string[]
}
type Food = {
  key: string; name: string; one_portion: string; pattern: string; prep: string
  mess: boolean; available: boolean; protein_g: number; iron_mg: number; haem: boolean
}

const SLOT_LABEL: Record<string, string> = {
  breakfast: 'Breakfast', lunch: 'Lunch', snack: 'Snack', dinner: 'Dinner',
}

export function FoodPreferences() {
  const client = useQueryClient()
  const profile = useQuery({ queryKey: ['diet-profile'], queryFn: () => api<Profile>('/diet/profile/') })
  const foods = useQuery({ queryKey: ['diet-foods'], queryFn: () => api<{ foods: Food[] }>('/diet/foods/') })

  const [draft, setDraft] = useState<Partial<Profile>>({})
  useEffect(() => { if (profile.data) setDraft(profile.data) }, [profile.data])

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api<Profile>('/diet/profile/', { method: 'PUT', ...json(body) }),
    onSuccess: (next) => {
      setDraft(next)
      // The plan and the food list both depend on these answers.
      client.invalidateQueries({ queryKey: ['diet-profile'] })
      client.invalidateQueries({ queryKey: ['diet-foods'] })
      client.invalidateQueries({ queryKey: ['diet-plan'] })
    },
  })

  if (!profile.data || !foods.data) return <section className="card"><Skeleton lines={8} /></section>

  const p = { ...profile.data, ...draft } as Profile
  const set = (patch: Partial<Profile>) => setDraft((d) => ({ ...d, ...patch }))
  const toggle = (list: string[], key: string) =>
    list.includes(key) ? list.filter((k) => k !== key) : [...list, key]

  // Only foods he could actually be served or make — offering him chicken to
  // dislike when he is vegetarian is noise.
  const choosable = foods.data.foods.filter((f) => f.available)
  const proteinFirst = [...choosable].sort((a, b) => b.protein_g - a.protein_g)

  return (
    <div className="stack fp">
      <section className="card stack">
        <h2 className="card-title">What you eat</h2>
        <Choices
          options={p.patterns} value={p.pattern} onPick={(v) => set({ pattern: v })} name="pattern"
        />
      </section>

      <section className="card stack">
        <h2 className="card-title">What you can make</h2>
        <p className="muted small">
          The ceiling, not a promise. The plan still prefers the thing you don’t
          have to cook when that does the job.
        </p>
        <Choices options={p.preps} value={p.prep} onPick={(v) => set({ prep: v })} name="prep" />
      </section>

      <section className="card stack">
        <h2 className="card-title">What your PG gives you</h2>
        <p className="muted small">
          These get planned around rather than replaced — no point telling you to
          cook a breakfast that’s already waiting downstairs.
        </p>
        <div className="fp-chips">
          {p.slots.map((slot) => (
            <button
              key={slot} type="button"
              className={`chip-btn${p.provided.includes(slot) ? ' is-active' : ''}`}
              onClick={() => set({ provided: toggle(p.provided, slot) })}
            >
              {p.provided.includes(slot) && <CheckIcon size={14} />} {SLOT_LABEL[slot] ?? slot}
            </button>
          ))}
        </div>
      </section>

      <section className="card stack">
        <h2 className="card-title">Things you eat most days</h2>
        <p className="muted small">
          Kept in every plan instead of being suggested to you as though they
          were our idea.
        </p>
        <FoodPicker
          foods={proteinFirst} picked={p.staples}
          onToggle={(k) => set({ staples: toggle(p.staples, k) })}
        />
      </section>

      <section className="card stack">
        <h2 className="card-title">Don’t suggest these</h2>
        <FoodPicker
          foods={choosable} picked={p.dislikes}
          onToggle={(k) => set({ dislikes: toggle(p.dislikes, k) })}
          tone="off"
        />
      </section>

      <section className="card stack">
        <h2 className="card-title">Anything else</h2>
        <textarea
          className="pmc-input" rows={3} value={p.notes} maxLength={400}
          placeholder="PG dinner is always rice and one sabzi. No beef."
          onChange={(e) => set({ notes: e.target.value })}
        />
      </section>

      <button
        type="button" className="btn btn-primary btn-grow"
        disabled={save.isPending}
        onClick={() => save.mutate({
          pattern: p.pattern, prep: p.prep, provided: p.provided,
          dislikes: p.dislikes, staples: p.staples, notes: p.notes.trim(),
        })}
      >
        {save.isPending ? 'Saving…' : save.isSuccess ? 'Saved' : 'Save'}
      </button>
      {save.error && <p className="small bad" role="alert">{errorText(save.error, 'Not saved.')}</p>}
    </div>
  )
}

function Choices({ options, value, onPick, name }: {
  options: Option[]; value: string; onPick: (v: string) => void; name: string
}) {
  return (
    <div className="fp-choices" role="radiogroup" aria-label={name}>
      {options.map((o) => (
        <button
          key={o.value} type="button" role="radio" aria-checked={value === o.value}
          className={`fp-choice${value === o.value ? ' is-active' : ''}`}
          onClick={() => onPick(o.value)}
        >
          <span className="fp-dot" />
          <span>{o.label}</span>
        </button>
      ))}
    </div>
  )
}

function FoodPicker({ foods, picked, onToggle, tone }: {
  foods: Food[]; picked: string[]; onToggle: (key: string) => void; tone?: 'off'
}) {
  const [all, setAll] = useState(false)
  const shown = all ? foods : foods.slice(0, 12)
  return (
    <>
      <div className="fp-chips">
        {shown.map((f) => (
          <button
            key={f.key} type="button"
            className={`chip-btn${picked.includes(f.key) ? (tone === 'off' ? ' is-off' : ' is-active') : ''}`}
            onClick={() => onToggle(f.key)}
            title={f.one_portion}
          >
            {f.name}
          </button>
        ))}
      </div>
      {foods.length > 12 && (
        <button type="button" className="lab-skip" onClick={() => setAll((a) => !a)}>
          {all ? 'Show fewer' : `Show all ${foods.length}`}
        </button>
      )}
    </>
  )
}
