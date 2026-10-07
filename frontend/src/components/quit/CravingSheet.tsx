import { useCallback, useState } from 'react'
import { errorText } from '../../lib/queries'
import { CRAVING_TRIGGERS, useCravingSummary, useLogCraving, usePatchCraving, type Craving, type CravingTrigger } from '../../lib/r13'
import { BottomSheet } from '../BottomSheet'
import { CheckIcon } from '../Icons'
import { FaceRow, MOOD_WORDS } from '../mood/FaceRow'
import { CravingPacer } from './CravingPacer'

const PLACES = ['Home', 'Work', 'Outside', 'Commute', 'Out with friends']
const STRENGTH_WORDS = ['Faint', 'Mild', 'Strong', 'Very strong', 'Overwhelming']

type Step = 'form' | 'breathe' | 'ask' | 'resisted' | 'smoked'

/**
 * R13 §8 "Craving now": a 10-second form → logs the craving → 3-minute breathing pacer →
 * "Did you smoke?" (yes also logs a cigarette, server-side). Kind, never preachy.
 */
export default function CravingSheet({ onClose }: { onClose: () => void }) {
  const [step, setStep] = useState<Step>('form')
  const [intensity, setIntensity] = useState(3)
  const [trigger, setTrigger] = useState<CravingTrigger | null>(null)
  const [place, setPlace] = useState('')
  const [mood, setMood] = useState<number | null>(null)
  const [more, setMore] = useState(false)
  const [note, setNote] = useState('')
  const [saved, setSaved] = useState<Craving | null>(null)
  const log = useLogCraving()
  const patch = usePatchCraving()
  const summary = useCravingSummary('4w', step === 'resisted')

  const start = () => {
    if (!trigger) return
    log.mutate(
      { intensity, trigger, place: place.trim() || undefined, mood, note: note.trim() || undefined, smoked: false },
      { onSuccess: (c) => { setSaved(c); setStep('breathe') } },
    )
  }
  const finished = useCallback(() => setStep('ask'), [])
  const smoked = () => {
    if (!saved) return
    patch.mutate({ id: saved.id, smoked: true }, { onSuccess: () => setStep('smoked') })
  }

  const title = step === 'form' ? 'Craving now' : step === 'breathe' ? 'Breathe with it' : step === 'ask' ? 'How did it go?' : ''

  return (
    <BottomSheet open onClose={onClose} title={title} full={step === 'breathe'}>
      {step === 'form' && (
        <div className="stack craving-form">
          <p className="muted small">Log it, then breathe for 3 minutes. Most cravings fade on their own in that time.</p>
          <div className="ci-block">
            <div className="face-row-head">
              <span className="ci-label">How strong?</span>
              <span className="muted small">{STRENGTH_WORDS[intensity - 1]}</span>
            </div>
            <div className="segmented segmented-full" role="radiogroup" aria-label="How strong, 1 to 5">
              {[1, 2, 3, 4, 5].map((n) => (
                <button key={n} type="button" role="radio" aria-checked={intensity === n} aria-label={`${n}: ${STRENGTH_WORDS[n - 1]}`} className={`segmented-option ${intensity === n ? 'is-active' : ''}`} onClick={() => setIntensity(n)}>
                  {n}
                </button>
              ))}
            </div>
          </div>
          <div className="ci-block">
            <span className="ci-label">What set it off?</span>
            <div className="ci-chips" role="radiogroup" aria-label="What set it off?">
              {CRAVING_TRIGGERS.map((t) => (
                <button key={t.key} type="button" role="radio" aria-checked={trigger === t.key} className={`ci-chip ${trigger === t.key ? 'is-on' : ''}`} onClick={() => setTrigger(t.key)}>
                  {t.label}
                </button>
              ))}
            </div>
          </div>
          {!more ? (
            <button type="button" className="link-btn small craving-more" onClick={() => setMore(true)}>+ Where, mood and a note (optional)</button>
          ) : (
            <>
              <div className="ci-block">
                <span className="ci-label">Where?</span>
                <div className="ci-chips">
                  {PLACES.map((p) => (
                    <button key={p} type="button" aria-pressed={place === p} className={`ci-chip ${place === p ? 'is-on' : ''}`} onClick={() => setPlace(place === p ? '' : p)}>{p}</button>
                  ))}
                </div>
              </div>
              <FaceRow label="Mood" value={mood} onChange={setMood} words={MOOD_WORDS} topic="recovery" />
              <input className="ci-note" maxLength={200} placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
            </>
          )}
          {log.isError && <p className="bad small">{errorText(log.error, 'Could not log it — start breathing anyway.')}</p>}
          <button type="button" className="btn btn-primary btn-block craving-go" disabled={!trigger || log.isPending} onClick={start}>
            {log.isPending ? 'Logging…' : trigger ? 'Log it & breathe' : 'Pick what set it off'}
          </button>
          {log.isError && (
            <button type="button" className="btn btn-secondary btn-block" onClick={() => setStep('breathe')}>Just breathe</button>
          )}
        </div>
      )}
      {step === 'breathe' && <CravingPacer onFinish={finished} />}
      {step === 'ask' && (
        <div className="stack craving-ask">
          <p className="craving-q">Did you smoke?</p>
          <button type="button" className="btn btn-primary btn-block craving-big" onClick={() => setStep('resisted')}>
            No — I rode it out
          </button>
          <button type="button" className="btn btn-secondary btn-block craving-big" disabled={patch.isPending || !saved} onClick={smoked}>
            {patch.isPending ? 'Saving…' : 'Yes, I smoked'}
          </button>
          {!saved && <p className="muted small">The craving wasn’t saved, so log a cigarette from the 🚬 button if you smoked.</p>}
          {patch.isError && <p className="bad small">{errorText(patch.error, 'Could not save.')}</p>}
        </div>
      )}
      {step === 'resisted' && (
        <div className="stack craving-done">
          <span className="craving-badge" aria-hidden="true"><CheckIcon size={32} /></span>
          <p className="craving-q">Craving beaten.</p>
          {summary.data && summary.data.resisted > 0 && (
            <p className="centered-text">That’s {summary.data.resisted} {summary.data.resisted === 1 ? 'craving' : 'cravings'} resisted in the last 4 weeks. Each one makes the next weaker.</p>
          )}
          <button type="button" className="btn btn-primary btn-block" onClick={onClose}>Done</button>
        </div>
      )}
      {step === 'smoked' && (
        <div className="stack craving-done">
          <p className="craving-q">Logged. A slip isn’t a restart.</p>
          <p className="centered-text muted">Your smoke-free progress still counts. Notice what set this one off — that’s the one to plan for next time.</p>
          <button type="button" className="btn btn-primary btn-block" onClick={onClose}>OK</button>
        </div>
      )}
    </BottomSheet>
  )
}
