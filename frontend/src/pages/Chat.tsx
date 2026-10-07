import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from 'react'
import { Navigate, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ActivityAttachment, WorkoutAttachment } from '../components/Cards'
import { ChatListSheet } from '../components/ChatListSheet'
import { ChipButton, ChipGroup } from '../components/ChipButton'
import { ActivitySheet, WorkoutSheet } from '../components/DetailSheets'
import { ArrowUpIcon, ChevronDown, CloseIcon, ListIcon, NewChatIcon, PlusIcon } from '../components/Icons'
import { LogMealSheet } from '../components/LogMealSheet'
import { Markdown } from '../components/Markdown'
import { MealSummary } from '../components/MealCard'
import { PageHeader } from '../components/PageHeader'
import { PlanProposalCard } from '../components/PlanProposalCard'
import { ErrorState, Loading } from '../components/States'
import { clearPendingChat, getPendingChat } from '../lib/pending'
import { createThread, errorText, sendMessage, useMessages, useThreads } from '../lib/queries'
import type { ActivityCard, Attachment, AttachmentRef, Meal, Message, Workout } from '../lib/types'

const SUGGESTIONS = [
  'Build a plan for me to run 10k.',
  'How did my last week go?',
  'What should I eat before my long run?',
]

/** /chat → the most recent chat, or a new one when there are none. */
export function ChatIndex() {
  const threads = useThreads()
  const location = useLocation()
  if (threads.isPending) return <div className="page"><Loading block /></div>
  const latest = threads.data?.[0]
  if (latest && !(location.state as { prompt?: string } | null)?.prompt) return <Navigate to={`/chat/${latest.id}`} replace />
  return <Navigate to="/chat/new" replace state={location.state} />
}

type Outgoing = { content: string; attachments: Attachment[] }

function refOf(a: Attachment): AttachmentRef {
  switch (a.type) {
    case 'workout': return { type: 'workout', id: a.workout.id }
    case 'activity': return { type: 'activity', id: a.activity.id }
    case 'meal': return { type: 'meal', id: a.meal.id }
    case 'plan_proposal': return { type: 'plan_proposal', id: a.plan.id }
  }
}

export default function Chat() {
  const { threadId: param } = useParams()
  const threadId = param && param !== 'new' ? Number(param) : null
  const [search] = useSearchParams()
  const location = useLocation()
  const navigate = useNavigate()
  const client = useQueryClient()
  const messages = useMessages(threadId)

  const pending = getPendingChat(search.get('pending'))
  const [pendingError, setPendingError] = useState('')
  const [draft, setDraft] = useState(() => (location.state as { prompt?: string } | null)?.prompt ?? '')
  const [staged, setStaged] = useState<Attachment[]>([])
  const [outgoing, setOutgoing] = useState<Outgoing | null>(null)
  const [sendError, setSendError] = useState<{ text: string; retry: Outgoing } | null>(null)
  const [listOpen, setListOpen] = useState(false)
  const [mealOpen, setMealOpen] = useState(false)
  const [openWorkout, setOpenWorkout] = useState<Workout | null>(null)
  const [openActivity, setOpenActivity] = useState<ActivityCard | null>(null)
  const [atBottom, setAtBottom] = useState(true)
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  // A suggested prompt handed over by onboarding / the calendar empty state.
  useEffect(() => {
    const prompt = (location.state as { prompt?: string } | null)?.prompt
    if (prompt) {
      setDraft(prompt)
      inputRef.current?.focus()
    }
  }, [location.state])

  // Reset local state when switching threads.
  useEffect(() => {
    setOutgoing(null)
    setSendError(null)
  }, [threadId])

  // Guide / Review hand-off: wait for the thread the server is creating.
  useEffect(() => {
    if (!pending) return
    let live = true
    pending.promise
      .then(({ thread_id }) => {
        if (!live) return
        clearPendingChat(pending.id)
        client.invalidateQueries({ queryKey: ['threads'] })
        client.invalidateQueries({ queryKey: ['calendar'] })
        navigate(`/chat/${thread_id}`, { replace: true })
      })
      .catch((error) => {
        if (live) setPendingError(errorText(error, 'The coach could not start this chat.'))
      })
    return () => {
      live = false
    }
  }, [pending, client, navigate])

  const scrollToBottom = (smooth = false) => {
    const el = scrollRef.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
  }

  const count = messages.data?.length ?? 0
  useLayoutEffect(() => {
    scrollToBottom()
  }, [threadId, count, outgoing, pending])

  const onScroll = () => {
    const el = scrollRef.current
    if (el) setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 80)
  }

  async function send(payload: Outgoing) {
    if (!payload.content.trim() && !payload.attachments.length) return
    setOutgoing(payload)
    setSendError(null)
    setDraft('')
    setStaged([])
    try {
      let id = threadId
      if (id == null) {
        const thread = await createThread(payload.content.slice(0, 60) || 'New chat')
        id = thread.id
      }
      const result = await sendMessage(id, payload.content, payload.attachments.map(refOf))
      client.setQueryData<Message[]>(['messages', id], (prev) => [...(prev ?? []), result.user, result.assistant])
      client.invalidateQueries({ queryKey: ['threads'] })
      // Tools may have moved workouts, logged meals or remembered facts.
      for (const key of ['calendar', 'plan-active', 'profile-summary', 'diet-day', 'memory']) {
        client.invalidateQueries({ queryKey: [key] })
      }
      setOutgoing(null)
      if (threadId == null) navigate(`/chat/${id}`, { replace: true })
    } catch (error) {
      setOutgoing(null)
      setDraft(payload.content)
      setStaged(payload.attachments)
      setSendError({ text: errorText(error, 'Message not sent. Check your connection.'), retry: payload })
    }
  }

  const submit = () => send({ content: draft.trim(), attachments: staged })

  const onKey = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter sends on desktop; on touch keyboards Enter stays a newline.
    if (event.key === 'Enter' && !event.shiftKey && !('ontouchstart' in window)) {
      event.preventDefault()
      if (!outgoing) submit()
    }
  }

  // Auto-grow the composer.
  useLayoutEffect(() => {
    const el = inputRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`
  }, [draft])

  const busy = !!outgoing || (!!pending && !pendingError)
  const list = messages.data?.filter((m) => m.role !== 'tool') ?? []
  const lastUser = [...list].reverse().find((m) => m.role === 'user')
  const isEmpty = threadId == null && !pending && !outgoing

  const renderAttachment = (a: Attachment, key: string) => {
    switch (a.type) {
      case 'workout':
        return <WorkoutAttachment key={key} workout={a.workout} onOpen={() => setOpenWorkout(a.workout)} />
      case 'activity':
        return <ActivityAttachment key={key} activity={a.activity} onOpen={() => setOpenActivity(a.activity)} />
      case 'meal':
        return (
          <div key={key} className="attach attach-meal">
            <MealSummary meal={a.meal} />
          </div>
        )
      case 'plan_proposal':
        return <PlanProposalCard key={key} plan={a.plan} />
    }
  }

  return (
    <div className="page chat-page">
      <PageHeader
        left={
          <ChipGroup>
            <ChipButton label="Chats" onClick={() => setListOpen(true)}>
              <ListIcon />
            </ChipButton>
            <ChipButton label="New chat" onClick={() => navigate('/chat/new')} disabled={isEmpty}>
              <NewChatIcon />
            </ChipButton>
          </ChipGroup>
        }
        title="Coach"
      />

      <div className="chat-scroll" ref={scrollRef} onScroll={onScroll}>
        {threadId != null && messages.isPending && <Loading block />}
        {threadId != null && messages.isError && (
          <ErrorState message={errorText(messages.error, 'This chat did not load.')} onRetry={() => messages.refetch()} />
        )}

        {isEmpty && (
          <div className="chat-welcome">
            <h1 className="display">Ask your coach</h1>
            <p className="muted">Plans, workouts, how a run went, what to eat. It knows your Garmin data.</p>
            <div className="suggestions">
              {SUGGESTIONS.map((s) => (
                <button key={s} type="button" className="suggestion" onClick={() => setDraft(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="messages">
          {list.map((m) =>
            m.role === 'user' ? (
              <div key={m.id} className="msg msg-user">
                {m.attachments.map((a, i) => renderAttachment(a, `${m.id}-${i}`))}
                {m.content && <div className="bubble">{m.content}</div>}
              </div>
            ) : (
              <div key={m.id} className={`msg msg-assistant ${m.status === 'error' ? 'is-error' : ''}`}>
                {m.status === 'pending' && <p className="thinking">Thinking…</p>}
                {m.content && <Markdown text={m.content} />}
                {m.attachments.map((a, i) => renderAttachment(a, `${m.id}-${i}`))}
                {m.status === 'error' && lastUser && m.id === list[list.length - 1]?.id && (
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    disabled={busy}
                    onClick={() => send({ content: lastUser.content, attachments: [] })}
                  >
                    Try again
                  </button>
                )}
              </div>
            ),
          )}

          {pending && (
            <>
              <div className="msg msg-user">
                {pending.attachment && renderAttachment(pending.attachment, 'pending')}
                <div className="bubble">{pending.text}</div>
              </div>
              <div className="msg msg-assistant">
                {pendingError ? (
                  <>
                    <p className="bad">{pendingError}</p>
                    <button type="button" className="btn btn-secondary btn-sm" onClick={() => navigate('/calendar')}>
                      Back to calendar
                    </button>
                  </>
                ) : (
                  <p className="thinking">Thinking…</p>
                )}
              </div>
            </>
          )}

          {outgoing && (
            <>
              <div className="msg msg-user">
                {outgoing.attachments.map((a, i) => renderAttachment(a, `out-${i}`))}
                {outgoing.content && <div className="bubble">{outgoing.content}</div>}
              </div>
              <div className="msg msg-assistant">
                <p className="thinking">Thinking…</p>
              </div>
            </>
          )}

          {sendError && (
            <div className="msg msg-assistant is-error">
              <p className="bad">{sendError.text}</p>
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => send(sendError.retry)}>
                Try again
              </button>
            </div>
          )}
        </div>
      </div>

      {!atBottom && (
        <button type="button" className="chip chip-sm scroll-down" aria-label="Scroll to latest" onClick={() => scrollToBottom(true)}>
          <ChevronDown size={18} />
        </button>
      )}

      <div className="composer">
        {staged.length > 0 && (
          <div className="composer-staged">
            {staged.map((a, i) =>
              a.type === 'meal' ? (
                <span key={i} className="staged">
                  {a.meal.description || 'Meal'} · {Math.round(a.meal.kcal)} kcal
                  <button type="button" aria-label="Remove attachment" onClick={() => setStaged((s) => s.filter((_, j) => j !== i))}>
                    <CloseIcon size={14} />
                  </button>
                </span>
              ) : null,
            )}
          </div>
        )}
        <textarea
          ref={inputRef}
          rows={1}
          value={draft}
          placeholder="Ask anything"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKey}
          aria-label="Message"
        />
        <div className="composer-row">
          <button type="button" className="icon-btn" aria-label="Log a meal photo" title="Log a meal (photo or text)" onClick={() => setMealOpen(true)}>
            <PlusIcon />
          </button>
          <button
            type="button"
            className="send"
            aria-label="Send"
            disabled={busy || (!draft.trim() && !staged.length)}
            onClick={submit}
          >
            <ArrowUpIcon size={20} />
          </button>
        </div>
      </div>

      <ChatListSheet
        open={listOpen}
        onClose={() => setListOpen(false)}
        currentId={threadId}
        onSelect={(id) => {
          setListOpen(false)
          navigate(`/chat/${id}`)
        }}
        onNew={() => {
          setListOpen(false)
          navigate('/chat/new')
        }}
        onDeleted={(id) => {
          if (id === threadId) navigate('/chat/new', { replace: true })
        }}
      />
      <LogMealSheet
        open={mealOpen}
        onClose={() => setMealOpen(false)}
        onSaved={(meal: Meal) => {
          // The meal is saved to the diary; staging it lets the coach comment on it.
          setStaged((s) => [...s, { type: 'meal', meal }])
          if (!draft.trim()) setDraft('I just ate this.')
        }}
      />
      <WorkoutSheet workout={openWorkout} onClose={() => setOpenWorkout(null)} />
      <ActivitySheet activity={openActivity} onClose={() => setOpenActivity(null)} />
    </div>
  )
}
