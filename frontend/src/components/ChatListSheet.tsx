import { useState } from 'react'
import { relativeStamp } from '../lib/format'
import { errorText, useDeleteThread, useRenameThread, useThreads } from '../lib/queries'
import { BottomSheet } from './BottomSheet'
import { ChipButton } from './ChipButton'
import { ChatIcon, MoreVIcon, NewChatIcon } from './Icons'
import { Empty, ErrorState, Loading } from './States'

/** Full-screen list of chats: title + time, ⋮ → rename / delete, new chat. */
export function ChatListSheet({
  open, onClose, currentId, onSelect, onNew, onDeleted,
}: {
  open: boolean
  onClose: () => void
  currentId: number | null
  onSelect: (id: number) => void
  onNew: () => void
  onDeleted: (id: number) => void
}) {
  const threads = useThreads()
  const rename = useRenameThread()
  const remove = useDeleteThread()
  const [menu, setMenu] = useState<number | null>(null)
  const [editing, setEditing] = useState<{ id: number; title: string } | null>(null)
  const [confirm, setConfirm] = useState<number | null>(null)

  return (
    <BottomSheet
      open={open}
      onClose={onClose}
      full
      title="Chats"
      actions={
        <ChipButton label="New chat" onClick={onNew}>
          <NewChatIcon />
        </ChipButton>
      }
    >
      {threads.isPending && <Loading />}
      {threads.isError && <ErrorState message={errorText(threads.error)} onRetry={() => threads.refetch()} />}
      {threads.data?.length === 0 && (
        <Empty icon={<ChatIcon size={36} />} title="No chats yet">
          Start one and ask the coach anything.
        </Empty>
      )}
      <ul className="thread-list">
        {threads.data?.map((thread) => (
          <li key={thread.id} className={`thread ${thread.id === currentId ? 'is-current' : ''}`}>
            {editing?.id === thread.id ? (
              <form
                className="thread-edit"
                onSubmit={(e) => {
                  e.preventDefault()
                  if (editing.title.trim()) rename.mutate({ id: thread.id, title: editing.title.trim() }, { onSuccess: () => setEditing(null) })
                }}
              >
                <input autoFocus value={editing.title} onChange={(e) => setEditing({ ...editing, title: e.target.value })} aria-label="Chat title" />
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditing(null)}>Cancel</button>
                <button className="btn btn-primary btn-sm" disabled={rename.isPending}>Save</button>
              </form>
            ) : confirm === thread.id ? (
              <div className="thread-edit">
                <span className="grow">Delete “{thread.title || 'Untitled'}”?</span>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => setConfirm(null)}>Cancel</button>
                <button
                  type="button"
                  className="btn btn-danger btn-sm"
                  disabled={remove.isPending}
                  onClick={() => remove.mutate(thread.id, { onSuccess: () => { setConfirm(null); onDeleted(thread.id) } })}
                >
                  Delete
                </button>
              </div>
            ) : (
              <>
                <button type="button" className="thread-main" onClick={() => onSelect(thread.id)}>
                  <span className="thread-title">{thread.title || 'Untitled chat'}</span>
                  <span className="thread-time">{relativeStamp(thread.updated_at)}</span>
                </button>
                <div className="menu-wrap">
                  <button
                    type="button"
                    className="icon-btn"
                    aria-label="Chat options"
                    aria-expanded={menu === thread.id}
                    onClick={() => setMenu(menu === thread.id ? null : thread.id)}
                  >
                    <MoreVIcon />
                  </button>
                  {menu === thread.id && (
                    <div className="menu" role="menu">
                      <button type="button" role="menuitem" onClick={() => { setMenu(null); setEditing({ id: thread.id, title: thread.title }) }}>
                        Rename
                      </button>
                      <button type="button" role="menuitem" className="bad" onClick={() => { setMenu(null); setConfirm(thread.id) }}>
                        Delete
                      </button>
                    </div>
                  )}
                </div>
              </>
            )}
          </li>
        ))}
      </ul>
    </BottomSheet>
  )
}
