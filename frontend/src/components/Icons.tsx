import type { SVGProps } from 'react'

/** Inline stroke icons, 24-unit grid, currentColor. No icon library. */
type IconProps = SVGProps<SVGSVGElement> & { size?: number }

function Svg({ size = 22, children, ...rest }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {children}
    </svg>
  )
}

export const CalendarIcon = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3.5" y="5" width="17" height="15.5" rx="2.5" />
    <path d="M8 3v4M16 3v4M3.5 10h17" />
    <path d="M8 14h.01M12 14h.01M16 14h.01M8 17.5h.01M12 17.5h.01M16 17.5h.01" strokeWidth={2.4} />
  </Svg>
)

export const ChatIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 5.5A1.5 1.5 0 0 1 5.5 4h13A1.5 1.5 0 0 1 20 5.5v10a1.5 1.5 0 0 1-1.5 1.5H9l-5 4z" />
  </Svg>
)

export const DietIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M7 3v8M4.5 3v5a2.5 2.5 0 0 0 5 0V3M7 11v10" />
    <path d="M17 21V3c-2.2 1.2-3.5 3.8-3.5 7v3H17" />
  </Svg>
)

export const ProfileIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="8" r="3.6" />
    <path d="M4.5 20.5c.8-3.6 3.8-5.5 7.5-5.5s6.7 1.9 7.5 5.5z" />
  </Svg>
)

export const GearIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
  </Svg>
)

export const RefreshIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M20 11a8 8 0 1 0-2.3 5.7" />
    <path d="M20 4v7h-7" />
  </Svg>
)

export const ListIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M9 6h11M9 12h11M9 18h11" />
    <path d="M4.5 6h.01M4.5 12h.01M4.5 18h.01" strokeWidth={3} />
  </Svg>
)

export const NewChatIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 5.5A1.5 1.5 0 0 1 5.5 4h13A1.5 1.5 0 0 1 20 5.5v10a1.5 1.5 0 0 1-1.5 1.5H13l-4 4v-4H5.5A1.5 1.5 0 0 1 4 15.5z" />
    <path d="M12 7.5v6M9 10.5h6" />
  </Svg>
)

export const CloseIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M6 6l12 12M18 6L6 18" />
  </Svg>
)

export const PlusIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 5v14M5 12h14" />
  </Svg>
)

export const ArrowUpIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 19V5M6 11l6-6 6 6" />
  </Svg>
)

export const ChevronRight = (p: IconProps) => (
  <Svg {...p}>
    <path d="M9 6l6 6-6 6" />
  </Svg>
)

export const ChevronLeft = (p: IconProps) => (
  <Svg {...p}>
    <path d="M15 6l-6 6 6 6" />
  </Svg>
)

export const ChevronDown = (p: IconProps) => (
  <Svg {...p}>
    <path d="M6 9l6 6 6-6" />
  </Svg>
)

export const MoreVIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 5h.01M12 12h.01M12 19h.01" strokeWidth={3} />
  </Svg>
)

export const MoreHIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 12h.01M12 12h.01M19 12h.01" strokeWidth={3.2} />
  </Svg>
)

export const HelpIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6v.6M12 17h.01" />
  </Svg>
)

export const RunIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="14" cy="4.5" r="1.8" />
    <path d="M8 21l3-6 3 2.5V22M6 11.5l3-3 4 .5 2.5 3.5 3 1M11 15l1.5-5" />
  </Svg>
)

export const WalkIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="13" cy="4.5" r="1.8" />
    <path d="M10 21l2-6 2.5 2V21M8 13l1-4.5 3.5-1 2 3.5 2.5 1M12 15l.6-5" />
  </Svg>
)

export const ActivityIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 12h4l3-8 4 16 3-8h4" />
  </Svg>
)

export const ReviewIcon = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3.5" y="4" width="17" height="15" rx="2" />
    <path d="M12 8.5v7M8.5 12h7" />
  </Svg>
)

export const TrashIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 7h16M9 7V4.5h6V7M6.5 7l1 13h9l1-13" />
  </Svg>
)

export const EditIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 20h4L19 9l-4-4L4 16z" />
  </Svg>
)

export const CameraIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 8h3l2-3h6l2 3h3v11H4z" />
    <circle cx="12" cy="13" r="3.5" />
  </Svg>
)

export const DocIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M6 3h8l4 4v14H6z" />
    <path d="M14 3v4h4M9 13h6M9 17h6" />
  </Svg>
)

export const DropIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z" />
  </Svg>
)

export const CheckIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 12.5l4.5 4.5L19 7.5" />
  </Svg>
)

export const SparkIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z" />
  </Svg>
)

export const InsightsIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3.5 20.5h17" />
    <path d="M4 15.5l4.5-5 4 3.5 7-8" />
    <path d="M15.5 6h4v4" />
  </Svg>
)

// --- R10 ------------------------------------------------------------------------------

export const TodayIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7v5l3 2" />
  </Svg>
)

export const PlanIcon = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3" y="5" width="18" height="16" rx="3" />
    <path d="M3 10h18M8 3v4M16 3v4" />
  </Svg>
)

export const CoachIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 5h16v11H9l-5 4z" />
  </Svg>
)

export const HealthIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 12h4l3-7 4 14 3-7h4" />
  </Svg>
)

export const ForkIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M7 3v8M5 3v5a2 2 0 0 0 4 0V3M7 11v10M17 3c-2 0-3 2-3 6s1 4 3 4v8" />
  </Svg>
)

export const SmokeIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 15h13v3H3zM19 15v3M22 15v3M16 8c0-2 2-2 2-4M19 8c0-2 2-2 2-4" />
  </Svg>
)

export const DrinkIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 8h10v12a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1zM15 11h2a2 2 0 0 1 2 2v2a2 2 0 0 1-2 2h-2M5 8a3 3 0 0 1 5-2 3 3 0 0 1 5 2" />
  </Svg>
)

export const SugarIcon = (p: IconProps) => (
  <Svg {...p}>
    <rect x="6" y="3" width="12" height="18" rx="2" />
    <path d="M6 9h12M6 15h12M12 3v18" />
  </Svg>
)

export const MoonIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" />
  </Svg>
)

export const SunIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
  </Svg>
)

export const ShoeIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 17.5V9.5l3-3 2.5 3.5c1.2 1.4 3 2 5 2.2l4.5.6A3 3 0 0 1 21 15.8v1.7a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z" />
    <path d="M3 14.5h18M9.5 11l-1.5 2M12.5 12l-1 1.8" />
  </Svg>
)

export const BellIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z" />
    <path d="M10 20.5a2 2 0 0 0 4 0" />
  </Svg>
)

export const MedalIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M8 3h8l-2.5 6h-3z" />
    <circle cx="12" cy="15" r="6" />
    <path d="M12 12.2l.9 1.8 2 .3-1.4 1.4.3 2-1.8-.9-1.8.9.3-2-1.4-1.4 2-.3z" strokeWidth={1.4} />
  </Svg>
)

export const LockIcon = (p: IconProps) => (
  <Svg {...p}>
    <rect x="5" y="10.5" width="14" height="10" rx="2.5" />
    <path d="M8 10.5V8a4 4 0 0 1 8 0v2.5" />
  </Svg>
)

export const ScatterIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3.5 3.5v17h17" />
    <path d="M7.5 15.5h.01M11 12.5h.01M9 9.5h.01M14.5 10h.01M17 6.5h.01M13 15h.01" strokeWidth={3} />
  </Svg>
)

export const ReportIcon = (p: IconProps) => (
  <Svg {...p}>
    <rect x="4.5" y="3" width="15" height="18" rx="2.5" />
    <path d="M8.5 8h7M8.5 12h7M8.5 16h4" />
  </Svg>
)

export const LungsIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3v9M12 12l-3-2M12 12l3-2" />
    <path d="M8.5 7.5C6 8 3.5 12 3.5 17c0 2 1 3 2.5 3 2.5 0 3.5-1.5 3.5-4V9.5c0-1-.4-2-1-2zM15.5 7.5c2.5.5 5 4.5 5 9.5 0 2-1 3-2.5 3-2.5 0-3.5-1.5-3.5-4V9.5c0-1 .4-2 1-2z" />
  </Svg>
)

export const AlarmIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="13" r="7.5" />
    <path d="M12 9.5V13l2.5 1.8M4 5.5 6.5 3M20 5.5 17.5 3" />
  </Svg>
)

export const WatchIcon = (p: IconProps) => (
  <Svg {...p}>
    <rect x="6.5" y="6.5" width="11" height="11" rx="3" />
    <path d="M9 6.5 9.5 3h5l.5 3.5M9 17.5l.5 3.5h5l.5-3.5M12 9.8V12l1.5 1" />
  </Svg>
)

export const InfoIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 11v5.5M12 7.6v.01" strokeWidth={2.4} />
  </Svg>
)

// --- R13 ---------------------------------------------------------------------------

export const ShareIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3v12M7.5 7.5 12 3l4.5 4.5" />
    <path d="M5 12v6.5A2.5 2.5 0 0 0 7.5 21h9a2.5 2.5 0 0 0 2.5-2.5V12" />
  </Svg>
)

export const FlagIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 21V4M5 4h11l-2 4 2 4H5" />
  </Svg>
)

export const UndoIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M9 14 4 9l5-5" />
    <path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11" />
  </Svg>
)

export const DumbbellIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M6.5 6.5v11M17.5 6.5v11M3.5 9v6M20.5 9v6M6.5 12h11" />
  </Svg>
)

export const CoffeeIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 9h12v5a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5V9Z" />
    <path d="M16 10.5h1.5a2.5 2.5 0 0 1 0 5H16M8 3.5c0 1 1 1.5 1 2.5M12 3.5c0 1 1 1.5 1 2.5" />
  </Svg>
)

export const BandageIcon = (p: IconProps) => (
  <Svg {...p}>
    <rect x="2.5" y="8" width="19" height="8" rx="4" transform="rotate(-45 12 12)" />
    <path d="M10.5 10.5h.01M13.5 13.5h.01M13.5 10.5h.01M10.5 13.5h.01" strokeWidth={2.4} />
  </Svg>
)

export const DownloadIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3v12M7.5 10.5 12 15l4.5-4.5M4.5 20h15" />
  </Svg>
)

export const WindIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 8h10a3 3 0 1 0-3-3M3 12h15a3 3 0 1 1-3 3M3 16h7" />
  </Svg>
)

export const PiggyIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 11a7 6 0 0 1 12.5-2.5L20 8v4l-1.5.8A7 6 0 0 1 15 17v2.5h-2.5V18h-3v1.5H7V17a6 6 0 0 1-2-6Z" />
    <path d="M15 10.5h.01" strokeWidth={2.6} />
  </Svg>
)
