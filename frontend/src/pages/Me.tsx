import { lazy, Suspense, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { ExportSection } from '../components/account/ExportSection'
import { WatchAlarmsCard } from '../components/alarm/AlarmCards'
import { BadgesSection } from '../components/me/Badges'
import { CoachMemory } from '../components/me/CoachMemory'
import { DeletedActivities } from '../components/me/DeletedActivities'
import { IllnessLauncher } from '../components/illness/IllnessLauncher'
import { ReviewLauncher } from '../components/quality/ReviewEntry'
import { Row, RowGroup } from '../components/Disclose'
import {
  BandageIcon, CalendarIcon, ChevronRight, GearIcon, HealthIcon, HelpIcon, LockIcon, MedalIcon, RefreshIcon, SparkIcon, TodayIcon, TrashIcon, WatchIcon,
} from '../components/Icons'
import { initialOf } from '../components/Kit'
import { PageHeader } from '../components/PageHeader'
import { RacesCard } from '../components/profile/RacesCard'
import { useShell } from '../components/Shell'
import { Skeleton } from '../components/States'
import { useAuth } from '../lib/AuthContext'
import { useAchievements, useWatchAlarms } from '../lib/queries'
import { useDataReview, useIllness } from '../lib/r17'
import { ProfileCards } from './Profile'
import { ResetPlanning } from '../components/settings/ResetPlanning'

const CalendarSync = lazy(() => import('../components/calendar/CalendarSync').then((m) => ({ default: m.CalendarSync })))

/** Me (avatar, top-right): profile, then grouped rows — every page one tap away. */
export default function Me() {
  return (
    <Routes>
      <Route index element={<MeHome />} />
      <Route path="races" element={<SubPage title="Races"><RacesCard /></SubPage>} />
      <Route path="alarms" element={<SubPage title="Watch alarms"><WatchAlarmsCard link /></SubPage>} />
      <Route path="badges" element={<SubPage title="Badges"><BadgesSection /></SubPage>} />
      <Route path="calendar" element={<SubPage title="Calendar sync"><Suspense fallback={<section className="card"><Skeleton lines={4} /></section>}><CalendarSync /></Suspense></SubPage>} />
      <Route path="account" element={<SubPage title="Account"><AccountPage /></SubPage>} />
      <Route path="memory" element={<SubPage title="What the coach knows"><CoachMemory /></SubPage>} />
      <Route path="deleted" element={<SubPage title="Deleted activities"><DeletedActivities /></SubPage>} />
      <Route path="reset" element={<SubPage title="Clear data"><ResetPlanning /></SubPage>} />
      <Route path="*" element={<Navigate to="/me" replace />} />
    </Routes>
  )
}

function SubPage({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="page me-page">
      <PageHeader title={title} back="/me" avatar={false} />
      {children}
    </div>
  )
}

function MeHome() {
  const { athlete, username, isStaff } = useAuth()
  const { openSettings } = useShell()
  const ach = useAchievements()
  const alarms = useWatchAlarms()

  const earned = (ach.data?.badges ?? []).filter((b) => b.earned)
  const badgeSub = ach.data ? `${earned.length} of ${ach.data.badges.length} earned` : 'Streaks and personal records'
  const alarmCount = (alarms.data?.alarms ?? []).filter((a) => a.enabled).length
  const alarmSub = alarms.data?.available ? `${alarmCount} on · read from your watch` : 'Read from Garmin'
  // R17
  const illness = useIllness().data?.active ?? null
  const review = useDataReview()
  const [sheet, setSheet] = useState<'' | 'illness' | 'review'>('')

  return (
    <div className="page me-page">
      <PageHeader title="Me" back="/today" avatar={false} />
      <section className="card me-card">
        <span className="avatar-btn avatar-lg" aria-hidden="true">{initialOf(athlete?.display_name || username)}</span>
        <div className="grow">
          <p className="kit-title">{athlete?.display_name || 'Athlete'}</p>
          <p className="muted small">{username}</p>
        </div>
        <button type="button" className="btn btn-secondary btn-sm" onClick={openSettings}>
          <GearIcon size={18} /> Settings
        </button>
      </section>

      <ProfileCards />

      <RowGroup title="Gear & reminders">
        <Row to="/me/alarms" icon={<WatchIcon size={20} />} title="Watch alarms" sub={alarmSub} />
        <Row to="/me/calendar" icon={<CalendarIcon size={20} />} title="Calendar sync" sub="See planned runs in Google or Apple Calendar" />
        <Row
          to="/me/badges"
          icon={<MedalIcon size={20} />}
          title="Badges"
          sub={badgeSub}
          aside={ach.data && ach.data.unseen > 0 ? <span className="row-badge">{ach.data.unseen} new</span> : undefined}
        />
      </RowGroup>

      <RowGroup title="Health">
        <Row
          onClick={() => setSheet('illness')}
          icon={<BandageIcon size={20} />}
          title={illness ? 'I’m better' : 'I’m sick or injured'}
          sub={illness ? `${illness.type_label} · day ${illness.days_so_far} — ease back in` : 'Pause your plan and switch to rest'}
        />
        <Row to="/health/experiments" icon={<SparkIcon size={20} />} title="Experiments" sub="Try one change and see what it does" />
      </RowGroup>

      <RowGroup title="Data">
        <Row
          onClick={() => setSheet('review')}
          icon={<HealthIcon size={20} />}
          title="Review data"
          sub="Keep or exclude data that may be off"
          aside={review.data?.pending ? <span className="row-badge">{review.data.pending}</span> : undefined}
        />
        <Row to="/me/deleted" icon={<TrashIcon size={20} />} title="Deleted activities" sub="Bring back an activity you deleted" />
        {/* "Clear data", not "Start over". The row sat in the right group under
            a name nobody searching for it would think of: people look for the
            word for what they want gone, not for the mood they are in. */}
        <Row to="/me/reset" icon={<RefreshIcon size={20} />} title="Clear data & rebuild" sub="Clear the plan, gym days or calendar, rebuild it, or re-sync Garmin" />
      </RowGroup>
      <IllnessLauncher mode={illness ? 'recover' : 'start'} open={sheet === 'illness'} onClose={() => setSheet('')} />
      <ReviewLauncher open={sheet === 'review'} onClose={() => setSheet('')} />

      <RowGroup title="App">
        <Row onClick={() => openSettings()} icon={<GearIcon size={20} />} title="Settings" sub="Garmin, training days, diet, habits, Customise Today" />
        <Row onClick={() => openSettings('today')} icon={<TodayIcon size={20} />} title="Customise Today" sub="Choose which cards show under the top card" />
        <Row to="/me/account" icon={<LockIcon size={20} />} title="Account" sub="Export my data, log out, delete account" />
        <Row to="/health/guides" icon={<HelpIcon size={20} />} title="Guides" sub="Form, breathing, strength, fuelling, warm-up" />
        {isStaff && <Row to="/admin-panel" icon={<LockIcon size={20} />} title="Admin" sub="Users, AI models & costs, system" />}
      </RowGroup>
      <p className="muted small centered-text">RunCoach</p>
    </div>
  )
}

/** Me → Account: export, and the sign-out / delete controls that live in Settings. */
function AccountPage() {
  const { username } = useAuth()
  const { openSettings } = useShell()
  return (
    <div className="stack">
      <ExportSection />
      <button type="button" className="card link-card me-link" onClick={openSettings}>
        <span className="grow">
          <span className="kit-title block">Log out or delete account</span>
          <span className="muted small">Signed in as {username} · in Settings, at the bottom</span>
        </span>
        <ChevronRight className="muted" />
      </button>
    </div>
  )
}
