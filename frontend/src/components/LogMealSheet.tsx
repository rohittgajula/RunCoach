import { useEffect, useMemo, useRef, useState } from 'react'
import { ApiError } from '../lib/auth'
import { localInputValue, todayISO } from '../lib/format'
import { errorText, estimateMeal, useSaveMeal } from '../lib/queries'
import type { Confidence, Meal, MealItem, MealSource, MealType } from '../lib/types'
import { BottomSheet } from './BottomSheet'
import { Field } from './Field'
import { CameraIcon, CloseIcon, PlusIcon, SparkIcon } from './Icons'

export const MEAL_TYPES: Array<{ value: MealType; label: string }> = [
  { value: 'breakfast', label: 'Breakfast' },
  { value: 'lunch', label: 'Lunch' },
  { value: 'snack', label: 'Snack' },
  { value: 'dinner', label: 'Dinner' },
]

export function guessMealType(d = new Date()): MealType {
  const h = d.getHours() + d.getMinutes() / 60
  if (h < 10.5) return 'breakfast'
  if (h < 15) return 'lunch'
  if (h < 18) return 'snack'
  return 'dinner'
}

/** Numbers are edited as text so "1." survives while typing "1.5". */
type EditItem = { name: string; quantity: string; kcal: string; carbs_g: string; protein_g: string; fat_g: string }

const blankItem = (): EditItem => ({ name: '', quantity: '', kcal: '', carbs_g: '', protein_g: '', fat_g: '' })

const toEdit = (i: MealItem): EditItem => ({
  name: i.name,
  quantity: i.quantity ?? '',
  kcal: String(Math.round(i.kcal)),
  carbs_g: String(Math.round(i.carbs_g)),
  protein_g: String(Math.round(i.protein_g)),
  fat_g: String(Math.round(i.fat_g)),
})

function defaultTime(date: string) {
  if (date === todayISO()) return localInputValue(new Date())
  return `${date}T12:00`
}

const NUM_FIELDS: Array<{ key: 'kcal' | 'carbs_g' | 'protein_g' | 'fat_g'; label: string }> = [
  { key: 'kcal', label: 'kcal' },
  { key: 'carbs_g', label: 'Carbs g' },
  { key: 'protein_g', label: 'Protein g' },
  { key: 'fat_g', label: 'Fat g' },
]

/**
 * Log meal: photo and/or text → AI estimate → editable items → save. The estimate is
 * never saved on its own; the athlete always confirms. If the estimator is down
 * (503) they fill the items in by hand.
 */
export function LogMealSheet({
  open, onClose, date = todayISO(), meal, onSaved,
}: {
  open: boolean
  onClose: () => void
  date?: string
  meal?: Meal | null
  onSaved?: (meal: Meal) => void
}) {
  const save = useSaveMeal()
  const fileRef = useRef<HTMLInputElement>(null)
  const [step, setStep] = useState<'input' | 'review'>('input')
  const [photo, setPhoto] = useState<File | null>(null)
  const [text, setText] = useState('')
  const [mealType, setMealType] = useState<MealType>(guessMealType())
  const [eatenAt, setEatenAt] = useState(defaultTime(date))
  const [description, setDescription] = useState('')
  const [items, setItems] = useState<EditItem[]>([])
  const [source, setSource] = useState<MealSource>('manual')
  const [confidence, setConfidence] = useState<Confidence | null>(null)
  const [estimating, setEstimating] = useState(false)
  const [note, setNote] = useState('')
  const [error, setError] = useState('')

  // Reset whenever the sheet opens (fresh log, or edit of a given meal).
  useEffect(() => {
    if (!open) return
    setError('')
    setNote('')
    save.reset()
    if (meal) {
      setStep('review')
      setPhoto(null)
      setText('')
      setMealType(meal.meal_type)
      setEatenAt(localInputValue(new Date(meal.eaten_at)))
      setDescription(meal.description)
      setItems(meal.items.length ? meal.items.map(toEdit) : [blankItem()])
      setSource(meal.source)
      setConfidence(meal.ai_confidence)
    } else {
      setStep('input')
      setPhoto(null)
      setText('')
      const time = defaultTime(date)
      setEatenAt(time)
      setMealType(date === todayISO() ? guessMealType() : 'lunch')
      setDescription('')
      setItems([])
      setSource('manual')
      setConfidence(null)
    }
  }, [open, meal, date])

  const preview = useMemo(() => (photo ? URL.createObjectURL(photo) : null), [photo])
  useEffect(() => () => {
    if (preview) URL.revokeObjectURL(preview)
  }, [preview])

  const totals = items.reduce(
    (sum, i) => ({
      kcal: sum.kcal + (Number(i.kcal) || 0),
      carbs_g: sum.carbs_g + (Number(i.carbs_g) || 0),
      protein_g: sum.protein_g + (Number(i.protein_g) || 0),
      fat_g: sum.fat_g + (Number(i.fat_g) || 0),
    }),
    { kcal: 0, carbs_g: 0, protein_g: 0, fat_g: 0 },
  )

  async function runEstimate() {
    setEstimating(true)
    setError('')
    setNote('')
    try {
      const estimate = await estimateMeal({ text: text.trim() || undefined, photo, meal_type: mealType })
      setDescription(estimate.description || text.trim())
      setItems(estimate.items.length ? estimate.items.map(toEdit) : [blankItem()])
      setConfidence(estimate.confidence)
      setSource(photo ? 'ai_photo' : 'ai_text')
      setStep('review')
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 503) {
        setNote('The AI estimate is unavailable right now — add the items yourself.')
        manual()
      } else {
        setError(errorText(caught, 'Could not estimate this meal.'))
      }
    } finally {
      setEstimating(false)
    }
  }

  function manual() {
    setDescription(text.trim())
    setItems([{ ...blankItem(), name: text.trim() }])
    setSource('manual')
    setConfidence(null)
    setStep('review')
  }

  const setItem = (index: number, patch: Partial<EditItem>) =>
    setItems((prev) => prev.map((item, i) => (i === index ? { ...item, ...patch } : item)))

  function submit() {
    const clean = items
      .filter((i) => i.name.trim())
      .map((i): MealItem => ({
        name: i.name.trim(),
        quantity: i.quantity.trim(),
        kcal: Number(i.kcal) || 0,
        carbs_g: Number(i.carbs_g) || 0,
        protein_g: Number(i.protein_g) || 0,
        fat_g: Number(i.fat_g) || 0,
      }))
    if (!clean.length) {
      setError('Add at least one item.')
      return
    }
    // Edited AI estimates stay tagged as AI-sourced; the totals are recomputed server-side.
    save.mutate(
      {
        id: meal?.id,
        draft: {
          meal_type: mealType,
          eaten_at: new Date(eatenAt).toISOString(),
          description: description.trim() || clean.map((i) => i.name).join(', '),
          items: clean,
          source,
          photo,
        },
      },
      {
        onSuccess: (saved) => {
          onSaved?.(saved)
          onClose()
        },
        onError: (caught) => setError(errorText(caught, 'Could not save the meal.')),
      },
    )
  }

  const title = meal ? 'Edit meal' : 'Log meal'

  return (
    <BottomSheet open={open} onClose={onClose} title={title}>
      <div className="stack">
        <div className="segmented segmented-full" role="radiogroup" aria-label="Meal type">
          {MEAL_TYPES.map((t) => (
            <button
              key={t.value}
              type="button"
              role="radio"
              aria-checked={mealType === t.value}
              className={`segmented-option ${mealType === t.value ? 'is-active' : ''}`}
              onClick={() => setMealType(t.value)}
            >
              {t.label}
            </button>
          ))}
        </div>
        <Field label="Time">
          <input
            type="datetime-local"
            value={eatenAt}
            max={localInputValue(new Date())}
            onChange={(e) => setEatenAt(e.target.value)}
          />
        </Field>

        {step === 'input' && (
          <>
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              capture="environment"
              hidden
              onChange={(e) => setPhoto(e.target.files?.[0] ?? null)}
            />
            {preview ? (
              <div className="photo-preview">
                <img src={preview} alt="Meal" />
                <button type="button" className="chip chip-sm photo-remove" aria-label="Remove photo" onClick={() => setPhoto(null)}>
                  <CloseIcon size={16} />
                </button>
              </div>
            ) : (
              <button type="button" className="photo-drop" onClick={() => fileRef.current?.click()}>
                <CameraIcon size={28} />
                <span>Take or choose a photo</span>
              </button>
            )}
            <Field label="What did you eat?" hint="Amounts help: “2 dosa, sambar, chai with sugar”">
              <textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} placeholder="2 dosa, sambar, chai with sugar" />
            </Field>
            {error && <p className="bad small" role="alert">{error}</p>}
            <button
              type="button"
              className="btn btn-primary btn-block"
              disabled={(!photo && !text.trim()) || estimating}
              onClick={runEstimate}
            >
              <SparkIcon size={18} /> {estimating ? 'Estimating…' : 'Estimate with AI'}
            </button>
            <button type="button" className="btn btn-ghost btn-block" onClick={manual}>
              Enter items manually
            </button>
          </>
        )}

        {step === 'review' && (
          <>
            {note && <p className="notice">{note}</p>}
            {source !== 'manual' && (
              <p className="tag tag-ai">
                <SparkIcon size={14} /> AI estimate{confidence ? ` · ${confidence} confidence` : ''} — check the amounts
              </p>
            )}
            {preview && (
              <div className="photo-preview photo-preview-sm">
                <img src={preview} alt="Meal" />
              </div>
            )}
            {!preview && meal?.photo_url && (
              <div className="photo-preview photo-preview-sm">
                <img src={meal.photo_url} alt="Meal" />
              </div>
            )}
            <Field label="Description">
              <input value={description} onChange={(e) => setDescription(e.target.value)} />
            </Field>

            <div className="items">
              {items.map((item, index) => (
                <div key={index} className="item-row">
                  <div className="item-top">
                    <input
                      className="item-name"
                      aria-label="Item"
                      placeholder="Item"
                      value={item.name}
                      onChange={(e) => setItem(index, { name: e.target.value })}
                    />
                    <input
                      className="item-qty"
                      aria-label="Quantity"
                      placeholder="Qty"
                      value={item.quantity}
                      onChange={(e) => setItem(index, { quantity: e.target.value })}
                    />
                    <button
                      type="button"
                      className="icon-btn"
                      aria-label="Remove item"
                      onClick={() => setItems((prev) => prev.filter((_, i) => i !== index))}
                    >
                      <CloseIcon size={18} />
                    </button>
                  </div>
                  <div className="item-nums">
                    {NUM_FIELDS.map((f) => (
                      <label key={f.key} className="item-num">
                        <span>{f.label}</span>
                        <input
                          inputMode="decimal"
                          value={item[f.key]}
                          onChange={(e) => setItem(index, { [f.key]: e.target.value.replace(/[^\d.]/g, '') })}
                          onFocus={(e) => e.target.select()}
                        />
                      </label>
                    ))}
                  </div>
                </div>
              ))}
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setItems((prev) => [...prev, blankItem()])}>
                <PlusIcon size={16} /> Add item
              </button>
            </div>

            <div className="totals">
              <span><strong>{Math.round(totals.kcal)}</strong> kcal</span>
              <span>C {Math.round(totals.carbs_g)} g</span>
              <span>P {Math.round(totals.protein_g)} g</span>
              <span>F {Math.round(totals.fat_g)} g</span>
            </div>

            {error && <p className="bad small" role="alert">{error}</p>}
            <div className="row-end">
              {!meal && (
                <button type="button" className="btn btn-ghost" onClick={() => setStep('input')}>
                  Back
                </button>
              )}
              <button type="button" className="btn btn-primary" onClick={submit} disabled={save.isPending}>
                {save.isPending ? 'Saving…' : meal ? 'Save changes' : 'Save meal'}
              </button>
            </div>
          </>
        )}
      </div>
    </BottomSheet>
  )
}
