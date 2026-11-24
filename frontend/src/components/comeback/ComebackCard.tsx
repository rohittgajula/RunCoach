/**
 * "Are you still running?" — the question the app never asked.
 *
 * Ten runs in eleven weeks, a four-week gap through October, then thirteen
 * days of nothing, and the app's only response was to keep writing sessions.
 * It had a journal and a morning check-in the whole time and neither of them
 * ever asked why he stopped.
 *
 * Three things, in the order they matter:
 *
 *   the gap     one question, asked once, with answers that do something
 *   the return  a first run back small enough that there will be a second one
 *   the week    a floor he clears, instead of a target he misses
 *
 * The answers are the whole point. A prompt that only records the reply is a
 * survey, and a survey that changes nothing teaches you to ignore the next
 * one — so each button says what it will do before you press it.
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, json } from '../../lib/auth'
import { errorText, invalidatePlanData } from '../../lib/queries'

type Answer = { key: string; label: string; action: string; note: string }
type Card = {
  week: { floor: number; runs: number; met: boolean; line: string; recent: number[] }
  gap: { days: number; long: boolean; headline: string; answers: Answer[] } | null
  return: { minutes: number; framing: string } | null
}

export function ComebackCard() {
  const client = useQueryClient()
  const [done, setDone] = useState<{ action: string; label: string } | null>(null)

  const card = useQuery({
    queryKey: ['comeback'],
    queryFn: () => api<Card>('/today/comeback/'),
  })

  const reply = useMutation({
    mutationFn: (key: string) =>
      api<{ action: string; label: string }>('/today/comeback/answer/',
        { method: 'POST', ...json({ key }) }),
    onSuccess: (result) => {
      setDone(result)
      invalidatePlanData(client)
      client.invalidateQueries({ queryKey: ['comeback'] })
    },
  })

  const c = card.data
  if (!c) return null

  return (
    <section className="card stack cmb">
      {/* The week is always here, gap or no gap. A week is a week. */}
      <div className="cmb-week">
        <span className={`cmb-dot${c.week.met ? ' is-met' : ''}`} aria-hidden="true" />
        <span className="cmb-line">{c.week.line}</span>
      </div>

      {c.gap && !done && (
        <>
          <p className="cmb-head">{c.gap.headline}</p>
          <div className="cmb-answers">
            {c.gap.answers.map((a) => (
              <button
                key={a.key}
                type="button"
                className="cmb-answer"
                disabled={reply.isPending}
                onClick={() => reply.mutate(a.key)}
              >
                <span className="cmb-answer-label">{a.label}</span>
                {/* Says what it will do before you press it. */}
                <span className="cmb-answer-note">{a.note}</span>
              </button>
            ))}
          </div>
          {reply.error && (
            <p className="small bad" role="alert">
              {errorText(reply.error, 'That did not go through.')}
            </p>
          )}
        </>
      )}

      {done && (
        <p className="cmb-done" role="status">
          {done.action === 'illness'
            ? <>Noted. <Link to="/health/illness">Tell me what is hurting</Link> and the plan waits for you.</>
            : done.action === 'shrink'
              ? 'Done — the weeks ahead now start from what you were actually managing.'
              : done.action === 'restart'
                ? 'Started again from today. Have a look at the Plan tab.'
                : 'Noted. Nothing changed — the plan is where you left it.'}
        </p>
      )}

      {c.return && !done && (
        <div className="cmb-return">
          <p className="cmb-return-min">{c.return.minutes} min</p>
          <p className="cmb-return-say">{c.return.framing}</p>
        </div>
      )}
    </section>
  )
}
