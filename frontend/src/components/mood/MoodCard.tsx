import { useEffect, useState } from 'react'
import { errorText } from '../../lib/queries'
import { useMoodToday, useSaveMood } from '../../lib/r13'
import { CheckIcon } from '../Icons'
import { InfoButton } from '../health/InfoButton'
import { ENERGY_WORDS, Face, FaceRow, MOOD_WORDS } from './FaceRow'

/**
 * R13 §10 mood & energy: two rows of five faces. On Today when today's entry is missing;
 * once saved it collapses to one line with "Change". Saves as soon as both are picked.
 */
export function MoodCard({ embedded = false, untilAnswered = false }: { embedded?: boolean; untilAnswered?: boolean }) {
  const q = useMoodToday()
  const save = useSaveMood()
  const entry = q.data?.entry ?? null
  const [mood, setMood] = useState<number | null>(entry?.mood ?? null)
  const [energy, setEnergy] = useState<number | null>(entry?.energy ?? null)
  const [editing, setEditing] = useState(false)

  useEffect(() => {
    if (entry) {
      setMood(entry.mood)
      setEnergy(entry.energy)
    }
  }, [entry])

  if (q.data === null || q.isPending) return null // endpoint absent / loading: Today works without it

  const pick = (m: number | null, e: number | null) => {
    setMood(m)
    setEnergy(e)
    if (m && e) save.mutate({ mood: m, energy: e }, { onSuccess: () => setEditing(false) })
  }

  if (entry && !editing && untilAnswered) return null
  if (entry && !editing) {
    return (
      <section className={`${embedded ? 'mood-embedded' : 'card'} mood-done`} aria-label="Mood and energy today">
        <span className="mood-done-faces" aria-hidden="true">
          <span className="mood-face is-mood"><Face n={entry.mood} size={24} /></span>
          <span className="mood-face is-energy"><Face n={entry.energy} size={24} /></span>
        </span>
        <span className="grow small">
          <b>Mood {MOOD_WORDS[entry.mood - 1].toLowerCase()}</b> · energy {ENERGY_WORDS[entry.energy - 1].toLowerCase()}
        </span>
        <button type="button" className="link-btn small mood-change" onClick={() => setEditing(true)}>Change</button>
      </section>
    )
  }

  return (
    <section className={`${embedded ? 'mood-embedded' : 'card'} mood-card stack-sm`} aria-label="How are you today?">
      <div className="mood-head">
        {embedded ? <span className="ci-label">How are you today?</span> : <h2 className="kit-title">How are you today?</h2>}
        <InfoButton title="Mood & energy">
          <p>One tap each, once a day. Over weeks it shows how sleep, stress, habits and training affect how you feel — and when an easier week would help.</p>
          <p>It stays private: the coach only ever sees your weekly averages.</p>
        </InfoButton>
        {save.isSuccess && !editing && <CheckIcon size={18} />}
      </div>
      <FaceRow label="Mood" value={mood} onChange={(v) => pick(v, energy)} words={MOOD_WORDS} topic="recovery" disabled={save.isPending} />
      <FaceRow label="Energy" value={energy} onChange={(v) => pick(mood, v)} words={ENERGY_WORDS} topic="fuel" disabled={save.isPending} />
      {save.isError && <p className="bad small">{errorText(save.error, 'Could not save.')}</p>}
      {editing && <button type="button" className="link-btn small" onClick={() => setEditing(false)}>Cancel</button>}
    </section>
  )
}
