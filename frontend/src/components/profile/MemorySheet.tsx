import { useState, type FormEvent } from 'react'
import { errorText, useAddMemory, useDeleteMemory, useMemory } from '../../lib/queries'
import { BottomSheet } from '../BottomSheet'
import { ChipButton } from '../ChipButton'
import { DocIcon, PlusIcon, TrashIcon } from '../Icons'
import { Empty, ErrorState, Loading } from '../States'

export function MemorySheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const memory = useMemory(open)
  const add = useAddMemory()
  const remove = useDeleteMemory()
  const [adding, setAdding] = useState(false)
  const [text, setText] = useState('')

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!text.trim()) return
    add.mutate(text.trim(), { onSuccess: () => { setText(''); setAdding(false) } })
  }

  return (
    <BottomSheet
      open={open}
      onClose={onClose}
      full
      title="Memory"
      actions={
        <ChipButton label="Add a memory" onClick={() => setAdding(!adding)}>
          <PlusIcon />
        </ChipButton>
      }
    >
      <p className="muted intro">
        RunCoach remembers key facts from your chats — injuries, schedule, preferences, goals — and uses them in every
        conversation. Memory updates shortly after a chat.
      </p>

      {adding && (
        <form className="card inline-form" onSubmit={submit}>
          <textarea autoFocus rows={2} placeholder="e.g. Left knee gets sore above 15 km" value={text} onChange={(e) => setText(e.target.value)} />
          {add.isError && <p className="bad small">{errorText(add.error, 'Could not save.')}</p>}
          <div className="row-end">
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAdding(false)}>Cancel</button>
            <button className="btn btn-primary btn-sm" disabled={add.isPending || !text.trim()}>Save</button>
          </div>
        </form>
      )}

      {memory.isPending && <Loading />}
      {memory.isError && <ErrorState message={errorText(memory.error)} onRetry={() => memory.refetch()} />}
      {memory.data?.length === 0 && !adding && <Empty icon={<DocIcon size={44} />} title="No memories yet" />}
      <ul className="facts">
        {memory.data?.map((fact) => (
          <li key={fact.id} className="fact">
            <div className="grow">
              <p>{fact.text}</p>
              <p className="muted small">
                {fact.source === 'manual' ? 'Added by you' : 'From a chat'} ·{' '}
                {new Date(fact.created_at).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}
              </p>
            </div>
            <button type="button" className="icon-btn" aria-label="Forget this" disabled={remove.isPending} onClick={() => remove.mutate(fact.id)}>
              <TrashIcon size={18} />
            </button>
          </li>
        ))}
      </ul>
    </BottomSheet>
  )
}
