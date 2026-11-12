/**
 * Theme override. The app is dark; "system" no longer means "ask the OS",
 * because the OS is not what decides this — it means "no explicit choice", and
 * with no explicit choice the stylesheet gives you dark. light/dark pin it.
 * The choice is a per-device convenience, so localStorage is fine.
 */
export type ThemePref = 'system' | 'light' | 'dark'

const KEY = 'runcoach-theme'

export function getThemePref(): ThemePref {
  try {
    const value = localStorage.getItem(KEY)
    return value === 'light' || value === 'dark' ? value : 'system'
  } catch {
    return 'system'
  }
}

function effective(pref: ThemePref): 'light' | 'dark' {
  // Anything that is not an explicit "light" renders dark, which is what the
  // stylesheet does. These two must agree or the Android status bar ends up a
  // different colour from the page under it.
  return pref === 'light' ? 'light' : 'dark'
}

export function applyTheme(pref: ThemePref = getThemePref()) {
  const root = document.documentElement
  if (pref === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', pref)
  // Keep the browser chrome (status bar on Android) in step with the ground colour.
  const color = effective(pref) === 'dark' ? '#0b0d10' : '#f4f5f7'
  document.querySelectorAll('meta[name="theme-color"]').forEach((meta) => meta.setAttribute('content', color))
}

export function setThemePref(pref: ThemePref) {
  try {
    if (pref === 'system') localStorage.removeItem(KEY)
    else localStorage.setItem(KEY, pref)
  } catch {
    /* private mode — still apply for this session */
  }
  applyTheme(pref)
}

export function watchSystemTheme() {
  // Nothing to watch any more: the OS does not decide the theme. Kept as a
  // no-op so callers do not need changing, and so the next person to look for
  // the OS listener finds this note instead of its absence.
}
