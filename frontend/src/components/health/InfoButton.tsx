import { useState, type ReactNode } from 'react'
import { BottomSheet } from '../BottomSheet'
import { InfoIcon } from '../Icons'
import { GLOSSARY, type GlossaryKey } from './glossary'

/**
 * Small (i) next to a metric name: opens a short sheet — what it is, why it matters for
 * running, which way is better, and "your normal" when known. Copy lives in glossary.ts;
 * `children` replaces it for one-off explanations (training status).
 */
export function InfoButton({
  k, normal, title, children, label,
}: { k?: GlossaryKey; normal?: ReactNode; title?: string; children?: ReactNode; label?: string }) {
  const [open, setOpen] = useState(false)
  const entry = k ? GLOSSARY[k] : null
  const heading = title ?? entry?.title ?? 'About'
  return (
    <>
      <button
        type="button"
        className="info-btn"
        aria-label={label ?? `What is ${heading}?`}
        onClick={(e) => { e.stopPropagation(); setOpen(true) }}
      >
        <InfoIcon size={16} />
      </button>
      <BottomSheet open={open} onClose={() => setOpen(false)} title={heading}>
        <div className="info-sheet stack">
          {entry && (
            <>
              <p>{entry.what}</p>
              <div>
                <p className="lbl">Why it matters for running</p>
                <p>{entry.why}</p>
              </div>
              <div>
                <p className="lbl">Which way is better</p>
                <p>{entry.better}</p>
              </div>
            </>
          )}
          {children}
          {normal != null && normal !== '' && (
            <p className="info-normal"><span className="lbl">Your normal</span>{normal}</p>
          )}
        </div>
      </BottomSheet>
    </>
  )
}
