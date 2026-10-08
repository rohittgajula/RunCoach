import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, json } from '../../lib/auth'
import { errorText } from '../../lib/queries'
import type { CoachFact } from '../../lib/r17'
import { CardHead } from '../Kit'
import { EditIcon, PlusIcon, TrashIcon } from '../Icons'
import { Empty, ErrorState, Skeleton } from '../States'
import '../../styles/r17lazy.css'

const GROUPS: Array<{ key: string; title: string; hint: string }> = [
  { key: 'health', title: 'Injuries & health', hint: 'e.g. Left knee gets sore above 15 km' },
  { key: 'schedule', title: 'Schedule & preferences', hint: 'e.g. I can only run before 7 am on weekdays' },
  { key: 'goals', title: 'Goals', hint: 'e.g. Sub-60 10k by March' },
  { key: 'other', title: 'Other', hint: 'Anything else the coach should know' },
]
const groupOf = (c: string | null | undefined) => (GROUPS.some((g) => g.key === c) ? (c as string) : 'other')

const SOURCE: Record<string, string> = { chat: 'From a chat', checkin: 'From a check-in', app: 'From the app', manual: 'Added by you' }
const when = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: new Date(iso).getFullYear() === new Date().getFullYear() ? undefined : 'numeric' }) : ''

type FactPatch = Partial<Pick<CoachFact, 'text' | 'category' | 'pinned'>>

function useFacts() {
  return useQuery({ queryKey: ['memory'], queryFn: () => api<CoachFact[] | { facts: CoachFact[] }>('/memory/') })
}
function useFactMutations() {
  const client = useQueryClient()
  const done = () => {
    client.invalidateQueries({ queryKey: ['memory'] })
    client.invalidateQueries({ queryKey: ['profile-summary'] })
  }
  return {
    add: useMutation({ mutationFn: (b: { text: string; category: string; pinned?: boolean }) => api<CoachFact>('/memory/', { method: 'POST', ...json(b) }), onSuccess: done }),
    patch: useMutation({ mutationFn: ({ id, ...b }: FactPatch & { id: number }) => api<CoachFact>(`/memory/${id}/`, { method: 'PATCH', ...json(b) }), onSuccess: done }),
    remove: useMutation({ mutationFn: (id: number) => api(`/memory/${id}/`, { method: 'DELETE' }), onSuccess: done }),
  }
}

const PinIcon = ({ on }: { on: boolean }) => (
  <svg viewBox="0 0 24 24" width="20" height="20" fill={on ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="2" strokeLinejoin="round" aria-hidden="true">
    <path d="M9 3h6l-1 6 4 4v2H6v-2l4-4-1-6zM12 15v6" />
  </svg>
)

function FactRow({ fact, m }: { fact: CoachFact; m: ReturnType<typeof useFactMutations> }) {
  const [mode, setMode] = useState<'view' | 'edit' | 'delete'>('view')
  const [text, setText] = useState(fact.text)
  const [category, setCategory] = useState(groupOf(fact.category))
  const [err, setErr] = useState('')
  const save = () => {
    const t = text.trim()
    if (!t) return
    setErr('')
    m.patch.mutate({ id: fact.id, text: t, category: category as CoachFact['category'] }, { onSuccess: () => setMode('view'), onError: (e) => setErr(errorText(e, 'Could not save.')) })
  }
  return (
    <li className="cm-fact">
      {mode === 'edit' ? (
        <div className="cm-edit">
          <textarea aria-label="Fact" value={text} onChange={(e) => setText(e.target.value)} autoFocus maxLength={500} />
          <select aria-label="Group" value={category} onChange={(e) => setCategory(e.target.value)}>
            {GROUPS.map((g) => <option key={g.key} value={g.key}>{g.title}</option>)}
          </select>
          {err && <p className="bad small">{err}</p>}
          <div className="cm-edit-actions">
            <button type="button" className="btn btn-ghost" onClick={() => { setMode('view'); setText(fact.text) }}>Cancel</button>
            <button type="button" className="btn btn-primary" disabled={!text.trim() || m.patch.isPending} onClick={save}>Save</button>
          </div>
        </div>
      ) : (
        <>
          <div className="cm-fact-top">
            <p className="cm-text">{fact.text}</p>
            <span className="cm-btns">
              <button
                type="button"
                aria-pressed={!!fact.pinned}
                aria-label={fact.pinned ? 'Unpin: coach no longer always keeps this in mind' : 'Pin: coach always keeps this in mind'}
                onClick={() => m.patch.mutate({ id: fact.id, pinned: !fact.pinned })}
              >
                <PinIcon on={!!fact.pinned} />
              </button>
              <button type="button" aria-label="Edit" onClick={() => setMode('edit')}><EditIcon size={18} /></button>
              <button type="button" aria-label="Delete" onClick={() => setMode('delete')}><TrashIcon size={18} /></button>
            </span>
          </div>
          <p className="cm-meta">
            {fact.pinned && <span className="cm-pin-tag">Pinned ·</span>}
            <span>{SOURCE[fact.source] ?? 'Remembered'}{fact.created_at ? ` · ${when(fact.updated_at || fact.created_at)}` : ''}</span>
          </p>
          {mode === 'delete' && (
            <div className="cm-confirm" role="alertdialog" aria-label="Forget this fact?">
              <p><b>The coach will forget this.</b> It won’t be used in any chat from now on.</p>
              <div className="cm-edit-actions">
                <button type="button" className="btn btn-ghost" onClick={() => setMode('view')}>Keep it</button>
                <button type="button" className="btn btn-solid-bad" disabled={m.remove.isPending} onClick={() => m.remove.mutate(fact.id)}>
                  Forget
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </li>
  )
}

function AddFact({ m, onDone }: { m: ReturnType<typeof useFactMutations>; onDone: () => void }) {
  const [text, setText] = useState('')
  const [category, setCategory] = useState('health')
  const [pinned, setPinned] = useState(false)
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!text.trim()) return
    m.add.mutate({ text: text.trim(), category, pinned }, { onSuccess: () => { setText(''); onDone() } })
  }
  return (
    <form className="card cm-add" onSubmit={submit}>
      <CardHead title="Tell the coach something" />
      <textarea aria-label="New fact" autoFocus maxLength={500} placeholder={GROUPS.find((g) => g.key === category)?.hint} value={text} onChange={(e) => setText(e.target.value)} />
      <select aria-label="Group" value={category} onChange={(e) => setCategory(e.target.value)}>
        {GROUPS.map((g) => <option key={g.key} value={g.key}>{g.title}</option>)}
      </select>
      <label className="ill-check"><input type="checkbox" checked={pinned} onChange={(e) => setPinned(e.target.checked)} /><span>Pin it<small>The coach always keeps pinned facts in mind.</small></span></label>
      {m.add.isError && <p className="bad small">{errorText(m.add.error, 'Could not save.')}</p>}
      <div className="cm-edit-actions">
        <button type="button" className="btn btn-ghost" onClick={onDone}>Cancel</button>
        <button className="btn btn-primary" disabled={!text.trim() || m.add.isPending}>Save</button>
      </div>
    </form>
  )
}

/** R17 §16 Me → What the coach knows: grouped facts; edit, pin, delete, add. */
export function CoachMemory() {
  const facts = useFacts()
  const m = useFactMutations()
  const [adding, setAdding] = useState(false)

  if (facts.isPending) return <section className="card"><Skeleton lines={5} /></section>
  if (facts.isError) return <ErrorState message={errorText(facts.error, 'Couldn’t load what the coach knows.')} onRetry={() => facts.refetch()} />
  const raw = facts.data
  const list: CoachFact[] = Array.isArray(raw) ? raw : raw?.facts ?? []
  const sorted = [...list].sort((a, b) => Number(!!b.pinned) - Number(!!a.pinned) || (b.created_at ?? '').localeCompare(a.created_at ?? ''))

  return (
    <div className="stack">
      <p className="cm-intro">
        The coach remembers these facts from your chats, check-ins and the app, and uses them in every chat. Changes apply from your next message. Your private habit log is never stored here.
      </p>
      {adding ? <AddFact m={m} onDone={() => setAdding(false)} /> : (
        <button type="button" className="btn btn-secondary" onClick={() => setAdding(true)}><PlusIcon size={18} /> Add a fact</button>
      )}
      {!list.length && !adding && <Empty title="Nothing remembered yet">Chat with the coach, or add a fact yourself — injuries, schedule, goals.</Empty>}
      {GROUPS.map((g) => {
        const items = sorted.filter((f) => groupOf(f.category) === g.key)
        if (!items.length) return null
        return (
          <section key={g.key} className="card cm-group">
            <CardHead title={g.title} aside={<span className="muted small">{items.length}</span>} />
            <ul className="cm-list" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
              {items.map((f) => <FactRow key={f.id} fact={f} m={m} />)}
            </ul>
          </section>
        )
      })}
    </div>
  )
}
