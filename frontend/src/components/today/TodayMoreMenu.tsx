import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useIllness } from '../../lib/r17'
import { BottomSheet } from '../BottomSheet'
import { BandageIcon, SparkIcon } from '../Icons'
import IllnessSheet from '../illness/IllnessSheet'

/** R17 Today ⋯ menu (lazy chunk): illness mode and experiments. */
export default function TodayMoreMenu({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate()
  const ill = useIllness()
  const active = !!ill.data?.active
  const [sheet, setSheet] = useState(false)
  return (
    <>
      <BottomSheet open={open} onClose={onClose} title="Today">
        <div className="menu-list">
          <button type="button" className="row" onClick={() => { onClose(); setSheet(true) }}>
            <span className="row-icon" aria-hidden="true"><BandageIcon size={20} /></span>
            <span className="grow row-text">
              <span className="row-title">{active ? 'I’m better' : 'I’m sick or injured'}</span>
              <span className="row-sub">{active ? 'Ease back in with a short return-to-run plan' : 'Pause your plan and switch to rest'}</span>
            </span>
          </button>
          <button type="button" className="row" onClick={() => { onClose(); navigate('/health/experiments') }}>
            <span className="row-icon" aria-hidden="true"><SparkIcon size={20} /></span>
            <span className="grow row-text">
              <span className="row-title">Start an experiment</span>
              <span className="row-sub">Try one change for a few weeks and see what it does</span>
            </span>
          </button>
        </div>
      </BottomSheet>
      <IllnessSheet open={sheet} onClose={() => setSheet(false)} mode={active ? 'recover' : 'start'} />
    </>
  )
}
