import { useAuth } from '../../lib/AuthContext'
import type { GuideKey, GuidesContext } from '../../lib/types'
import { BottomSheet } from '../BottomSheet'
import { BreathingGuide } from './BreathingGuide'
import { FormGuide } from './FormGuide'
import { FuelingGuide } from './FuelingGuide'
import { guideMeta } from './guideData'
import { StrengthGuide } from './StrengthGuide'
import { WarmupGuide } from './WarmupGuide'

/** One guide, full screen. Closing unmounts it — the metronome and timers stop with it. */
export function GuideSheet({
  guide, reason, context, cadence, onClose,
}: { guide: GuideKey | null; reason?: string | null; context?: GuidesContext | null; cadence: number | null; onClose: () => void }) {
  const { athlete } = useAuth()
  const meta = guideMeta(guide)
  const smoking = context?.smoking ?? (!!athlete?.smoke_goal && athlete.smoke_goal !== 'none')
  return (
    <BottomSheet open={!!guide && !!meta} onClose={onClose} full title={meta?.title}>
      {reason && <p className="guide-reason">For you: {reason}</p>}
      {guide === 'form' && <FormGuide cadence={cadence} bpm={typeof context?.metronome_bpm === 'number' ? context.metronome_bpm : null} />}
      {guide === 'breathing' && <BreathingGuide smoking={smoking} />}
      {guide === 'strength' && <StrengthGuide />}
      {guide === 'fueling' && <FuelingGuide />}
      {guide === 'warmup' && <WarmupGuide />}
    </BottomSheet>
  )
}
