/**
 * One movement: what it looks like, what it works, how to do it.
 *
 * The shape follows what Rohit shared — the picture first, then a
 * Muscle / How-to-do switch, then the focus areas and a body map. That order
 * is right: you look something up to see it, and reading comes second.
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../lib/auth'
import { BottomSheet } from '../BottomSheet'
import { ErrorState, Loading } from '../States'
import { BodyMap } from './BodyMap'
import { ExerciseFrames, type Media } from './ExerciseFrames'

type Detail = {
  slug: string
  name: string
  equipment_label: string
  level: string
  category: string
  body_part: string
  primary_muscles: string[]
  secondary_muscles: string[]
  /** Anatomical keys, which is what the body map highlights by. */
  primary_keys: string[]
  secondary_keys: string[]
  media: Media
  instructions: string[]
  tips: string[]
  met: number | null
}

export function ExerciseDetail({ slug, onClose }: { slug: string | null; onClose: () => void }) {
  const [tab, setTab] = useState<'muscle' | 'how'>('muscle')
  const query = useQuery({
    queryKey: ['exercise', slug],
    queryFn: () => api<Detail>(`/exercises/${slug}/`),
    enabled: slug != null,
  })
  const x = query.data

  return (
    <BottomSheet open={slug != null} onClose={onClose} title={x?.name ?? ''} label="Exercise">
      {query.isLoading && <Loading />}
      {query.isError && <ErrorState message="That exercise did not load." onRetry={() => query.refetch()} />}
      {x && (
        <div className="exdetail">
          <ExerciseFrames media={x.media} name={x.name} />

          <div className="exmeta">
            {x.equipment_label && <span className="expill">{x.equipment_label}</span>}
            <span className="expill">{x.level}</span>
            <span className="expill">{x.category}</span>
          </div>

          <div className="extabs" role="tablist">
            <button type="button" role="tab" aria-selected={tab === 'muscle'}
                    className={`extab${tab === 'muscle' ? ' is-on' : ''}`}
                    onClick={() => setTab('muscle')}>Muscle</button>
            <button type="button" role="tab" aria-selected={tab === 'how'}
                    className={`extab${tab === 'how' ? ' is-on' : ''}`}
                    onClick={() => setTab('how')}>How to do</button>
          </div>

          {tab === 'muscle' ? (
            <>
              <h3 className="exhead">Focus area</h3>
              <div className="exfocus">
                {x.primary_muscles.map((m) => (
                  <span key={m} className="exchip is-prime"><i /> {m}</span>
                ))}
                {x.secondary_muscles.map((m) => (
                  <span key={m} className="exchip"><i /> {m}</span>
                ))}
                {!x.primary_muscles.length && !x.secondary_muscles.length && (
                  <span className="muted small">Not recorded for this one.</span>
                )}
              </div>
              <BodyMap primary={x.primary_keys} secondary={x.secondary_keys} />
              <p className="muted small exnote">
                Solid is the muscle it works; faint is what helps.
              </p>
            </>
          ) : (
            <>
              <ol className="exsteps">
                {x.instructions.length
                  ? x.instructions.map((step, i) => <li key={i}>{step}</li>)
                  : <li className="muted">No written steps — go by the picture.</li>}
              </ol>
              {!!x.tips.length && (
                <>
                  <h3 className="exhead">Watch for</h3>
                  <ul className="extips">
                    {x.tips.map((tip, i) => <li key={i}>{tip}</li>)}
                  </ul>
                </>
              )}
            </>
          )}
        </div>
      )}
    </BottomSheet>
  )
}
