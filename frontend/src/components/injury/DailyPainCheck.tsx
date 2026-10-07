import { useState } from 'react'
import { useAuth } from '../../lib/AuthContext'
import { todayISO } from '../../lib/format'
import { useInjury } from '../../lib/r13'
import { InjuryCard } from './InjuryCard'
import { PainSheet } from './PainSheet'

const key = () => `rc.pain-asked.${todayISO()}`
const askedToday = () => {
  try { return localStorage.getItem(key()) === '1' } catch { return false }
}

/**
 * Today: the injury card when risk isn't low; otherwise, if the athlete turned on the
 * daily check (Settings), a one-line "Anything hurting?" with No / Yes.
 */
export function TodayInjury() {
  const { athlete } = useAuth()
  const injury = useInjury()
  const [asked, setAsked] = useState(askedToday)
  const [open, setOpen] = useState(false)
  const d = injury.data
  if (d && d.risk !== 'low') return <InjuryCard />
  if (!athlete?.pain_daily_check || asked || !d) return null
  if (d.pains.some((p) => p.date === todayISO())) return null
  const no = () => {
    try { localStorage.setItem(key(), '1') } catch { /* ignore */ }
    setAsked(true)
  }
  return (
    <section className="card pain-ask" aria-label="Daily pain check">
      <span className="grow"><b>Anything hurting today?</b></span>
      <button type="button" className="btn btn-secondary btn-sm" onClick={no}>No</button>
      <button type="button" className="btn btn-primary btn-sm" onClick={() => setOpen(true)}>Yes</button>
      <PainSheet open={open} onClose={() => { setOpen(false); no() }} />
    </section>
  )
}
