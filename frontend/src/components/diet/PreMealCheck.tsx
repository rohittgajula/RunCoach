/**
 * "I'm about to eat this — is it a good idea?"
 *
 * The one food screen that runs before the meal rather than after it, which is
 * the only point at which an answer can change anything.
 *
 * The split on screen mirrors the split in the backend. The numbers — what is
 * left of the day, what this plate does to it, what the next session asks for —
 * are computed in Python and shown as numbers. The sentences are the model's and
 * are about the food itself: how it is cooked, what it is missing, and what his
 * flagged blood markers mean for what is on the plate. Nothing the model wrote
 * is a number, and nothing Python computed is a sentence.
 *
 * The verdict chip is Python's, from fixed rules, so the same plate reads the
 * same way on a Tuesday and a Wednesday.
 *
 * It saves nothing. "Log it" hands the estimate to the normal meal sheet, where
 * he confirms it as he always has.
 */

import { useEffect, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api, json } from '../../lib/auth'
import { errorText } from '../../lib/queries'
import { DietIcon, RunIcon, SparkIcon } from '../Icons'
import { LogMealSheet, MEAL_TYPES } from '../LogMealSheet'

type Estimate = {
  description: string
  items: { name: string; quantity: string; kcal: number; carbs_g: number; protein_g: number; fat_g: number }[]
  kcal: number; carbs_g: number; protein_g: number; fat_g: number
  confidence: 'low' | 'medium' | 'high'
}
type Fit = {
  verdict: 'good' | 'fits' | 'heavy' | 'over'
  reason: string
  kcal_left_before: number; kcal_in_meal: number; kcal_left_after: number
  share_of_day_pct: number
  protein_gap_before_g: number; protein_in_meal_g: number
  carb_gap_before_g: number; carbs_in_meal_g: number
  next_demanding: { when: string; title: string; kind: string; minutes: number } | null
  upcoming: { when: string; title: string; kind: string; minutes: number; demanding: boolean }[]
  ran_today: boolean
}
type Result = {
  estimate: Estimate
  fit: Fit
  advice: { headline: string; good: string[]; watch: string[]; swap: string; timing: string }
  bloods: { taken_on: string | null; flagged: { key: string; label: string }[] }
  standing_note: string
}

/** Python's four verdicts, said in words. The tone is the chip's own colour. */
const VERDICT: Record<Fit['verdict'], { label: string; tone: string }> = {
  good: { label: 'Good call', tone: 'good' },
  fits: { label: 'Fits your day', tone: 'ok' },
  heavy: { label: 'On the heavy side', tone: 'warn' },
  over: { label: 'Past today', tone: 'bad' },
}

const CONFIDENCE_SAID: Record<Estimate['confidence'], string> = {
  high: 'The portions look clear.',
  medium: 'The portions are a reasonable guess.',
  low: 'The portions are a rough guess — say how much if you want it closer.',
}

export function PreMealCheck({ date, onOpen, variant = 'card' }: {
  date: string
  /** True while a verdict is on screen. The page's "Log meal" FAB is fixed to
   *  the bottom-right and sits squarely on this card's own "I ate it — log it"
   *  button, so the page hides it while the verdict is up. */
  onOpen?: (open: boolean) => void
  /** 'inline' drops the card chrome so this can sit inside Today's Food card
   *  without nesting a card in a card. The behaviour is identical. */
  variant?: 'card' | 'inline'
}) {
  const [text, setText] = useState('')
  const [mealType, setMealType] = useState('lunch')
  const [logging, setLogging] = useState(false)

  const check = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api<Result>('/diet/precheck/', { method: 'POST', ...json(body) }),
  })
  const result = check.data

  useEffect(() => { onOpen?.(!!result) }, [result, onOpen])
  useEffect(() => () => onOpen?.(false), [onOpen])

  const inline = variant === 'inline'
  const Wrapper = inline ? 'div' : 'section'

  return (
    <Wrapper className={inline ? 'stack pmc pmc-inline' : 'card stack pmc'}>
      {!inline && (
        <div className="card-head">
          <h2 className="card-title"><SparkIcon size={18} /> Before you eat it</h2>
        </div>
      )}
      <p className="muted small">
        Say what you are about to have. You get it read against today’s food, your
        next run and anything flagged in your bloods — before you eat, not after.
      </p>

      <label className="field-label" htmlFor="pmc-text">What are you about to eat?</label>
      <textarea
        id="pmc-text" className="pmc-input" rows={3} value={text}
        placeholder="2 dosa with sambar and a coconut chutney, and a chai"
        onChange={(e) => setText(e.target.value)}
      />

      <div className="pmc-types" role="group" aria-label="Which meal">
        {MEAL_TYPES.map((m) => (
          <button
            key={m.value} type="button"
            className={`chip-btn${mealType === m.value ? ' is-active' : ''}`}
            onClick={() => setMealType(m.value)}
          >
            {m.label}
          </button>
        ))}
      </div>

      <button
        type="button" className="btn btn-primary btn-grow"
        disabled={!text.trim() || check.isPending}
        onClick={() => check.mutate({ text: text.trim(), meal_type: mealType })}
      >
        {check.isPending ? 'Having a look…' : 'Check it'}
      </button>
      {check.error && (
        <p className="small bad" role="alert">{errorText(check.error, 'Could not check that.')}</p>
      )}

      {result && (
        <div className="pmc-out stack">
          <div className={`pmc-verdict is-${VERDICT[result.fit.verdict].tone}`}>
            <strong>{VERDICT[result.fit.verdict].label}</strong>
            <span>{result.fit.reason}</span>
          </div>

          <p className="pmc-headline">{result.advice.headline}</p>

          {/* Numbers, and only numbers, from Python. */}
          <ul className="pmc-nums">
            <li>
              <span className="pmc-num num">{result.estimate.kcal}</span>
              <span className="pmc-lbl">kcal on the plate</span>
            </li>
            <li>
              <span className="pmc-num num">{result.fit.kcal_left_after}</span>
              <span className="pmc-lbl">
                kcal left of today {result.fit.kcal_left_after < 0 ? '(over)' : 'after it'}
              </span>
            </li>
            <li>
              <span className="pmc-num num">{result.fit.protein_in_meal_g}g</span>
              <span className="pmc-lbl">
                protein, of {result.fit.protein_gap_before_g}g still short
              </span>
            </li>
            <li>
              <span className="pmc-num num">{result.fit.carbs_in_meal_g}g</span>
              <span className="pmc-lbl">
                carbs, of {result.fit.carb_gap_before_g}g still short
              </span>
            </li>
          </ul>

          {!!result.advice.good.length && (
            <ul className="pmc-list is-good">
              {result.advice.good.map((line) => <li key={line}>{line}</li>)}
            </ul>
          )}
          {!!result.advice.watch.length && (
            <ul className="pmc-list is-watch">
              {result.advice.watch.map((line) => <li key={line}>{line}</li>)}
            </ul>
          )}

          {result.advice.swap && (
            <p className="pmc-swap"><strong>One change:</strong> {result.advice.swap}</p>
          )}

          {(result.advice.timing || result.fit.next_demanding) && (
            <p className="pmc-timing">
              <RunIcon size={16} />
              {/* Title only. Plan titles already carry their own duration
                  ("Long run 28m"), so printing the minutes again beside it is at
                  best redundant and at worst reads as a contradiction. */}
              {result.fit.next_demanding && (
                <span className="pmc-next">
                  {result.fit.next_demanding.title} {result.fit.next_demanding.when}
                </span>
              )}
              {result.advice.timing && <span>{result.advice.timing}</span>}
            </p>
          )}

          {!!result.bloods.flagged.length && (
            <p className="muted small">
              Read against {result.bloods.flagged.map((f) => f.label).join(', ')} from your
              panel on {result.bloods.taken_on}.
            </p>
          )}

          <details className="pmc-items">
            <summary>What it reckons is on the plate</summary>
            <ul>
              {result.estimate.items.map((item) => (
                <li key={`${item.name}-${item.quantity}`}>
                  <span>{item.quantity} {item.name}</span>
                  <span className="muted num">{Math.round(item.kcal)} kcal</span>
                </li>
              ))}
            </ul>
            <p className="muted small">{CONFIDENCE_SAID[result.estimate.confidence]}</p>
          </details>

          <p className="lab-standing">{result.standing_note}</p>

          <div className="pmc-actions">
            <button type="button" className="btn btn-secondary btn-sm"
                    onClick={() => setLogging(true)}>
              <DietIcon size={16} /> I ate it — log it
            </button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => check.reset()}>
              Ask about something else
            </button>
          </div>
        </div>
      )}

      {/* The normal meal sheet, pre-filled. Confirming it is the same step as always. */}
      <LogMealSheet
        open={logging} onClose={() => { setLogging(false); check.reset(); setText('') }}
        date={date} prefill={result ? { ...result.estimate, meal_type: mealType } : undefined}
      />
    </Wrapper>
  )
}
