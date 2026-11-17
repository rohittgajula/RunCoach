/**
 * Every movement there is, filtered down to the one you want.
 *
 * Rohit: "i need all kind of workouts in which i should be able to add filter
 * based on musele like calf all workouts related to that, i need each an every
 * body part exercises ... with gym equipment too".
 *
 * The muscle filter leads, because that is the question people actually
 * arrive with — "what can I do for calves" — and equipment is the second cut,
 * because it is a constraint rather than a goal. Both carry counts so the bar
 * never offers a filter that returns an empty screen.
 *
 * A muscle matches a movement that works it either way round: searching
 * "calves" returns the exercises that load the calves, not only the ones named
 * after them. That is what somebody means and it costs nothing to honour.
 */

import { useEffect, useMemo, useState } from 'react'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { api } from '../../lib/auth'
import { ErrorState, Loading } from '../States'
import { ExerciseDetail } from './ExerciseDetail'
import { ExerciseThumb, type Media } from './ExerciseFrames'

type Count = { key: string; label: string; count: number }
type Group = Count & { muscles: Count[] }
type Collection = Count & { note: string }
type Facets = {
  total: number
  collections: Collection[]
  groups: Group[]
  equipment: Count[]
  categories: Count[]
  levels: Count[]
}
type Row = {
  id: number
  slug: string
  name: string
  equipment_label: string
  level: string
  primary_muscles: string[]
  media: Media
}
type Page = { total: number; page: number; has_more: boolean; results: Row[] }

const PAGE_SIZE = 40

function useDebounced<T>(value: T, ms = 300): T {
  const [out, setOut] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setOut(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return out
}

export function ExerciseLibrary() {
  const [collections, setCollections] = useState<Set<string>>(new Set())
  const [muscles, setMuscles] = useState<Set<string>>(new Set())
  const [equipment, setEquipment] = useState<Set<string>>(new Set())
  const [search, setSearch] = useState('')
  const [openSlug, setOpenSlug] = useState<string | null>(null)
  const q = useDebounced(search)

  const facets = useQuery({ queryKey: ['exercise-facets'], queryFn: () => api<Facets>('/exercises/facets/') })

  const params = useMemo(() => {
    const p = new URLSearchParams()
    collections.forEach((c) => p.append('collection', c))
    muscles.forEach((m) => p.append('muscle', m))
    equipment.forEach((e) => p.append('equipment', e))
    if (q.trim()) p.set('q', q.trim())
    p.set('page_size', String(PAGE_SIZE))
    return p
  }, [collections, muscles, equipment, q])

  const list = useInfiniteQuery({
    queryKey: ['exercise-list', params.toString()],
    initialPageParam: 1,
    queryFn: ({ pageParam }) => {
      const p = new URLSearchParams(params)
      p.set('page', String(pageParam))
      return api<Page>(`/exercises/?${p}`)
    },
    getNextPageParam: (last) => (last.has_more ? last.page + 1 : undefined),
  })

  const toggle = (set: Set<string>, put: (s: Set<string>) => void) => (key: string) => {
    const next = new Set(set)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    put(next)
  }

  const rows = list.data?.pages.flatMap((p) => p.results) ?? []
  const total = list.data?.pages[0]?.total ?? 0
  const picked = collections.size + muscles.size + equipment.size

  return (
    <section className="exlib">
      <input
        className="exsearch"
        type="search"
        value={search}
        placeholder={`Search ${facets.data?.total ?? ''} exercises`}
        onChange={(e) => setSearch(e.target.value)}
        aria-label="Search exercises"
      />

      {facets.isError && <ErrorState message="Filters did not load." onRetry={() => facets.refetch()} />}

      {facets.data && (
        <>
          {/* The two curated sets first. A runner opening a 708-exercise list
              does not want to begin by choosing between forty biceps
              variations. */}
          <div className="exfilter">
            <div className="goal-pills">
              {facets.data.collections.map((c) => (
                <button
                  key={c.key}
                  type="button"
                  className={`goal-pill is-wide${collections.has(c.key) ? ' is-on' : ''}`}
                  onClick={() => toggle(collections, setCollections)(c.key)}
                >
                  {c.label} <span className="exfilter-n">{c.count}</span>
                </button>
              ))}
            </div>
            {/* Shown only when chosen, because it is a caveat about the thing
                you just asked for, not a disclaimer on the whole screen. */}
            {facets.data.collections
              .filter((c) => collections.has(c.key) && c.note)
              .map((c) => <p key={c.key} className="excollection-note">{c.note}</p>)}
          </div>

          {/* Then muscle: "what can I do for calves" is the question people
              arrive with. Grouped, because thirty flat chips is a wall. */}
          {facets.data.groups.map((group) => (
            <div key={group.key} className="exfilter">
              <p className="exfilter-head">{group.label}</p>
              <div className="goal-pills">
                {group.muscles.filter((m) => m.count > 0).map((m) => (
                  <button
                    key={m.key}
                    type="button"
                    className={`goal-pill${muscles.has(m.key) ? ' is-on' : ''}`}
                    onClick={() => toggle(muscles, setMuscles)(m.key)}
                  >
                    {m.label} <span className="exfilter-n">{m.count}</span>
                  </button>
                ))}
              </div>
            </div>
          ))}

          <div className="exfilter">
            <p className="exfilter-head">Equipment</p>
            <div className="goal-pills">
              {facets.data.equipment.map((e) => (
                <button
                  key={e.key}
                  type="button"
                  className={`goal-pill${equipment.has(e.key) ? ' is-on' : ''}`}
                  onClick={() => toggle(equipment, setEquipment)(e.key)}
                >
                  {e.label} <span className="exfilter-n">{e.count}</span>
                </button>
              ))}
            </div>
          </div>
        </>
      )}

      <div className="exlib-bar">
        <span className="muted small">
          {list.isLoading ? 'Looking…' : `${total} exercise${total === 1 ? '' : 's'}`}
        </span>
        {picked > 0 && (
          <button type="button" className="btn btn-ghost btn-sm"
                  onClick={() => { setCollections(new Set()); setMuscles(new Set()); setEquipment(new Set()) }}>
            Clear {picked}
          </button>
        )}
      </div>

      {list.isError && <ErrorState message="The library did not load." onRetry={() => list.refetch()} />}
      {list.isLoading && <Loading />}

      <div className="exgrid">
        {rows.map((row) => (
          <button key={row.id} type="button" className="excard" onClick={() => setOpenSlug(row.slug)}>
            <ExerciseThumb media={row.media} className="excard-img" />
            <span className="excard-name">{row.name}</span>
            <span className="excard-sub">
              {row.equipment_label}
              {row.primary_muscles.length ? ` · ${row.primary_muscles[0]}` : ''}
            </span>
          </button>
        ))}
      </div>

      {!list.isLoading && !rows.length && (
        <p className="muted small centered-text">
          Nothing matches that. Try fewer filters.
        </p>
      )}

      {list.hasNextPage && (
        <button
          type="button"
          className="btn btn-secondary btn-grow"
          disabled={list.isFetchingNextPage}
          onClick={() => list.fetchNextPage()}
        >
          {list.isFetchingNextPage ? 'Loading…' : 'Show more'}
        </button>
      )}

      {/* Both source licences require a visible credit, so it is on the screen
          the material is used on rather than buried in an about page. The
          animations and classic stills are the CC BY-NC preview pack, which
          permits personal use; if this app is ever published commercially they
          have to be replaced with RepDB's paid bundle. */}
      <p className="excredit">
        Exercise data &amp; images:{' '}
        <a href="https://repdb.co" target="_blank" rel="noreferrer nofollow">RepDB</a>.
        Animations from the preview pack (CC BY-NC 4.0) — personal use only.
      </p>

      <ExerciseDetail slug={openSlug} onClose={() => setOpenSlug(null)} />
    </section>
  )
}
