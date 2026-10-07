import { Link, Navigate, Route, Routes } from 'react-router-dom'
import { WatchAlarmsCard } from '../components/alarm/AlarmCards'
import { BadgesSection, BadgesTeaser } from '../components/me/Badges'
import { RemindersSection, RemindersTeaser } from '../components/me/Reminders'
import { ShoesSection, ShoesTeaser } from '../components/me/Shoes'
import { ChevronRight, GearIcon } from '../components/Icons'
import { initialOf } from '../components/Kit'
import { PageHeader } from '../components/PageHeader'
import { useShell } from '../components/Shell'
import { useAuth } from '../lib/AuthContext'
import { ProfileCards } from './Profile'

/** Me (avatar, top-right): profile, settings, shoes, reminders, badges, account. */
export default function Me() {
  return (
    <Routes>
      <Route index element={<MeHome />} />
      <Route path="shoes" element={<SubPage title="Shoes"><ShoesSection /></SubPage>} />
      <Route path="reminders" element={<SubPage title="Reminders"><RemindersSection /></SubPage>} />
      <Route path="badges" element={<SubPage title="Badges"><BadgesSection /></SubPage>} />
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
  const { athlete, username } = useAuth()
  const { openSettings } = useShell()
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

      <ShoesTeaser />
      <RemindersTeaser />
      <WatchAlarmsCard link />
      <BadgesTeaser />

      <button type="button" className="card link-card me-link" onClick={openSettings}>
        <span className="grow">
          <span className="kit-title block">Settings &amp; account</span>
          <span className="muted small">Garmin, training days, diet goal, habits, location, theme, install, log out, delete account</span>
        </span>
        <ChevronRight className="muted" />
      </button>
      <p className="muted small centered-text"><Link to="/health/guides">Guides</Link> · RunCoach</p>
    </div>
  )
}
