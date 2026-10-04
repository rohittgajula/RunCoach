import type { ButtonHTMLAttributes, ReactNode } from 'react'

/** Round header icon button ("chip"). Group several with <ChipGroup>. */
export function ChipButton({
  label, children, className = '', ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string; children: ReactNode }) {
  return (
    <button type="button" className={`chip ${className}`} aria-label={label} title={label} {...rest}>
      {children}
    </button>
  )
}

export function ChipGroup({ children }: { children: ReactNode }) {
  return <div className="chip-group">{children}</div>
}
