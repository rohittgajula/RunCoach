import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { ExportSection } from '../components/account/ExportSection'
import { WatchAlarmsCard } from '../components/alarm/AlarmCards'
import { BadgesSection } from '../components/me/Badges'
import { RemindersSection } from '../components/me/Reminders'
import { ShoesSection } from '../components/me/Shoes'
import { Row, RowGroup } from '../components/Disclose'
import {
  BellIcon, CalendarIcon, ChevronRight, GearIcon, HelpIcon, LockIcon, MedalIcon, ShoeIcon, TodayIcon, WatchIcon,
} from '../components/Icons'
import { initialOf } from '../components/Kit'
import { PageHeader } from '../components/PageHeader'
import { RacesCard } from '../components/profile/RacesCard'
import { useShell } from '../components/Shell'
import { Skeleton } from '../components/States'
import { useAuth } from '../lib/AuthContext'
import { useAchievements, useGear, useReminders, useWatchAlarms } from '../lib/queries'
import { ProfileCards } from './Profile'

const CalendarSync = lazy(() => import('../components/calendar/CalendarSync').then((m) => ({ default: m.CalendarSync })))

/** Me (avatar, top-right): profile, then grouped rows — every page one tap away. */
export default function Me() {
  return (
    <Routes>
      <Route index element={<MeHome />} />
      <Route path="races" element={<SubPage title="Races"><RacesCard /></SubPage>} />
      <Route path="shoes" element={<SubPage title="Shoes"><ShoesSection /></SubPage>} />
      <Route path="reminders" element={<SubPage title="Reminders"><RemindersSection /></SubPage>} />
      <Route path="alarms" element={<SubPage title="Watch alarms"><WatchAlarmsCard link /></SubPage>} />
      <Route path="badges" element={<SubPage title="Badges"><BadgesSection /></SubPage>} />
      <Route path="calendar" element={<SubPage title="Calendar sync"><Suspense fallback={<section className="card"><Skeleton lines={4} /></section>}><CalendarSync /></Suspense></SubPage>} />
      <Route path="account" element={<SubPage title="Account"><AccountPage /></SubPage>} />
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
  const gear = useGear()
  const reminders = useReminders()
  const ach = useAchievements()
  const alarms = useWatchAlarms()

  const shoes = (gear.data?.shoes ?? []).filter((s) => !s.retired)
  const shoe = shoes.find((s) => s.is_default) ?? shoes[0]
  const due = shoes.filter((s) => s.replace_soon || s.replace_due)
  const shoeSub = due.length
    ? `${due.some((s) => s.replace_due) ? 'Time to replace' : 'Replace soon'}: ${due.map((s) => s.name).join(', ')}`
    : shoe ? `${shoe.name} · ${Math.round(shoe.distance_km)} of ${shoe.retire_km} km` : 'Track kilometres per pair'
  const on = [...(reminders.data?.reminders ?? []), ...(reminders.data?.nudges ?? [])].filter((r) => r.enabled)
  const remSub = on.length ? on.map((r) => r.label).join(' · ') : 'Check-in, habit log, water, weekly report'
  const earned = (ach.data?.badges ?? []).filter((b) => b.earned)
  const badgeSub = ach.data ? `${earned.length} of ${ach.data.badges.length} earned` : 'Streaks and personal records'
  const alarmCount = (alarms.data?.alarms ?? []).filter((a) => a.enabled).length
  const alarmSub = alarms.data?.available ? `${alarmCount} on · read from your watch` : 'Read from Garmin'

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
        <Row to="/me/shoes" icon={<ShoeIcon size={20} />} title="Shoes" sub={shoeSub} />
        <Row to="/me/reminders" icon={<BellIcon size={20} />} title="Reminders" sub={remSub} />
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

      <RowGroup title="App">
        <Row onClick={openSettings} icon={<GearIcon size={20} />} title="Settings" sub="Garmin, training days, diet, habits, Customise Today" />
        <Row onClick={openSettings} icon={<TodayIcon size={20} />} title="Customise Today" sub="Choose which cards show under the top card" />
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
