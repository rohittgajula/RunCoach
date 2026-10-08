import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../lib/auth'
import { dayMonth, km } from '../../lib/format'
import { errorText } from '../../lib/queries'
import type { DeletedActivity } from '../../lib/r17'
import { refreshAfterDelete } from '../../lib/r17lazy'
import { Empty, ErrorState, Skeleton } from '../States'
import '../../styles/r17lazy.css'

type Reimport = { reimported: boolean; activity_id: number | null; detail: string }

/** R17 Me → Deleted activities: what was removed from RunCoach, with Re-import. */
export function DeletedActivities() {
  const client = useQueryClient()
  const list = useQuery({ queryKey: ['activities-deleted'], queryFn: () => api<DeletedActivity[]>('/activities/deleted/') })
  const [msg, setMsg] = useState<Record<number, string>>({})
  const reimport = useMutation({
    mutationFn: (id: number) => api<Reimport>(`/activities/deleted/${id}/reimport/`, { method: 'POST' }),
    onSuccess: (r, id) => {
      setMsg((m) => ({ ...m, [id]: r.detail || (r.reimported ? 'Re-imported.' : 'Not re-imported.') }))
      refreshAfterDelete(client)
    },
    onError: (e, id) => setMsg((m) => ({ ...m, [id]: errorText(e, 'Couldn’t reach Garmin. Try again later.') })),
  })

  if (list.isPending) return <section className="card"><Skeleton lines={4} /></section>
  if (list.isError) return <ErrorState message={errorText(list.error, 'Couldn’t load deleted activities.')} onRetry={() => list.refetch()} />
  const rows = list.data ?? []
  if (!rows.length) return <Empty title="Nothing deleted">Activities you delete in RunCoach show up here, so you can bring them back.</Empty>
  return (
    <div className="stack">
      <p className="cm-intro">These won’t come back on the next sync. Re-import fetches one from Garmin again — if Garmin still has it.</p>
      <section className="card">
        <ul className="cm-list" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {rows.map((d) => (
            <li key={d.id} className="cm-fact">
              <div className="cm-fact-top">
                <span className="grow">
                  <b className="block" style={{ textTransform: 'capitalize' }}>{d.sport.replace(/_/g, ' ')}{d.distance_m ? ` · ${km(d.distance_m)}` : ''}</b>
                  <span className="cm-meta">
                    {dayMonth(d.date)} · {d.reason === 'deleted_in_garmin' ? 'removed after it was deleted in Garmin' : 'deleted by you'} {dayMonth(d.deleted_at.slice(0, 10))}
                  </span>
                </span>
                {d.can_reimport && (
                  <button type="button" className="btn btn-secondary" disabled={reimport.isPending && reimport.variables === d.id} onClick={() => reimport.mutate(d.id)}>
                    {reimport.isPending && reimport.variables === d.id ? 'Importing…' : 'Re-import'}
                  </button>
                )}
              </div>
              {msg[d.id] && <p className="small" role="status">{msg[d.id]}</p>}
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
