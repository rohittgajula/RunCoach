import type { GuideKey } from '../../lib/types'

/** Small hand-drawn icons for the guide cards (currentColor). */
export function GuideIcon({ guide, size = 40 }: { guide: GuideKey; size?: number }) {
  const common = { width: size, height: size, viewBox: '0 0 40 40', fill: 'none', stroke: 'currentColor', strokeWidth: 2.4, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, 'aria-hidden': true }
  switch (guide) {
    case 'form':
      return (
        <svg {...common}>
          <circle cx={24} cy={7} r={3.2} />
          <path d="M22 12l-4 9 6 4-2 9M18 21l-6 2M22 12l6 5 5-2M20 25l-8 6" />
        </svg>
      )
    case 'breathing':
      return (
        <svg {...common}>
          <path d="M20 6v12M20 18c-3 0-4 2-6 2M20 18c3 0 4 2 6 2" />
          <path d="M14 13c-5 2-8 9-7 17 1 3 6 3 8 0 2-3 1-10-1-17zM26 13c5 2 8 9 7 17-1 3-6 3-8 0-2-3-1-10 1-17z" />
        </svg>
      )
    case 'strength':
      return (
        <svg {...common}>
          <path d="M8 14v12M12 11v18M28 11v18M32 14v12M12 20h16" />
        </svg>
      )
    case 'fueling':
      return (
        <svg {...common}>
          <path d="M15 6h6M16 6v4c-3 1-4 3-4 6v16c0 1 1 2 2 2h8c1 0 2-1 2-2V16c0-3-1-5-4-6V6" />
          <path d="M12 20h12" />
          <path d="M30 14c2 3 3 5 3 7a3 3 0 0 1-6 0c0-2 1-4 3-7z" />
        </svg>
      )
    case 'warmup':
      return (
        <svg {...common}>
          <circle cx={20} cy={22} r={12} />
          <path d="M20 22V15M20 22l5 3M16 5h8" />
        </svg>
      )
  }
}
