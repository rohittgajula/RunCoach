/**
 * R13 §10: five faces, 1 (low) → 5 (great). Drawn as SVG so they look the same on every
 * phone; the selected face fills with the topic colour. Each face is a 44 px+ radio.
 */
const MOUTH: Record<number, string> = {
  1: 'M8 17c1.2-2 6.8-2 8 0',
  2: 'M8.5 16.2c1.5-1 5.5-1 7 0',
  3: 'M8.5 15.5h7',
  4: 'M8.5 14.8c1.5 1 5.5 1 7 0',
  5: 'M8 14c1.2 2.6 6.8 2.6 8 0',
}

export function Face({ n, size = 30 }: { n: number; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" aria-hidden="true">
      <circle cx="12" cy="12" r="9.5" />
      <path d="M9 9.5h.01M15 9.5h.01" strokeWidth={2.6} />
      <path d={MOUTH[n] ?? MOUTH[3]} />
    </svg>
  )
}

export function FaceRow({
  label, value, onChange, words, topic = 'recovery', disabled = false,
}: {
  label: string
  value: number | null
  onChange: (v: number) => void
  /** Five words, low → high, for screen readers and the caption. */
  words: [string, string, string, string, string]
  topic?: 'recovery' | 'sleep' | 'habits' | 'run' | 'fuel'
  disabled?: boolean
}) {
  return (
    <div className="face-row-wrap">
      <div className="face-row-head">
        <span className="ci-label">{label}</span>
        <span className="muted small">{value ? words[value - 1] : 'Tap a face'}</span>
      </div>
      <div className="face-row" role="radiogroup" aria-label={label} style={{ ['--face' as string]: `var(--${topic})`, ['--face-tint' as string]: `var(--${topic}-tint)` }}>
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            type="button"
            role="radio"
            aria-checked={value === n}
            aria-label={`${n} of 5: ${words[n - 1]}`}
            className={`face-btn ${value === n ? 'is-on' : ''}`}
            disabled={disabled}
            onClick={() => onChange(n)}
          >
            <Face n={n} />
          </button>
        ))}
      </div>
    </div>
  )
}

export const MOOD_WORDS: [string, string, string, string, string] = ['Low', 'Meh', 'OK', 'Good', 'Great']
export const ENERGY_WORDS: [string, string, string, string, string] = ['Drained', 'Tired', 'OK', 'Fresh', 'Full of energy']
