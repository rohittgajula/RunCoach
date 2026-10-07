import { useSearchParams } from 'react-router-dom'
import { useGuides, useInsights } from '../../lib/queries'
import type { GuideKey } from '../../lib/types'
import { ChevronRight } from '../Icons'
import { Skeleton } from '../States'
import { GUIDES, guideMeta, isGuideKey } from './guideData'
import { GuideIcon } from './GuideIcon'
import { GuideSheet } from './GuideSheet'

/** Insights → Guides: "For you" (with the reason) then every guide. `?g=form` opens one. */
export function GuidesSection() {
  const [params, setParams] = useSearchParams()
  const guides = useGuides()
  const insights = useInsights('4w')
  const forYou = (guides.data?.for_you ?? []).filter((g) => isGuideKey(g.key))
  const context = guides.data?.context ?? null
  const open = params.get('g')
  const openKey: GuideKey | null = isGuideKey(open) ? open : null
  const reason = forYou.find((g) => g.key === openKey)?.reason ?? null
  const cadence = (typeof context?.cadence_avg === 'number' ? context.cadence_avg : null) ?? insights.data?.running?.cadence?.avg ?? null

  const show = (key: GuideKey) => setParams({ g: key })
  const close = () => setParams({}, { replace: true })

  return (
    <div className="stack">
      <section className="stack-sm">
        <h2 className="section-title">For you</h2>
        {guides.isPending && <section className="card"><Skeleton lines={2} /></section>}
        {!guides.isPending && !forYou.length && (
          <p className="muted small">Nothing stands out in your last four weeks — the guides below are all there when you want them.</p>
        )}
        {forYou.map((g) => {
          const meta = guideMeta(g.key)!
          return (
            <button key={g.key} type="button" className="card guide-foryou" onClick={() => show(g.key)} style={{ ['--guide' as string]: meta.color }}>
              <span className="guide-icon"><GuideIcon guide={g.key} size={32} /></span>
              <span className="grow">
                <span className="guide-title">{meta.title}</span>
                <span className="guide-why">{g.reason}</span>
              </span>
              <ChevronRight size={20} />
            </button>
          )
        })}
      </section>
      <section className="stack-sm">
        <h2 className="section-title">All guides</h2>
        <div className="guide-grid">
          {GUIDES.map((g) => (
            <button key={g.key} type="button" className="card guide-card" onClick={() => show(g.key)} style={{ ['--guide' as string]: g.color }}>
              <span className="guide-icon"><GuideIcon guide={g.key} size={32} /></span>
              <span className="guide-title">{g.short}</span>
              <span className="muted small">{g.blurb}</span>
            </button>
          ))}
        </div>
      </section>
      <GuideSheet guide={openKey} reason={reason} context={context} cadence={cadence} onClose={close} />
    </div>
  )
}
