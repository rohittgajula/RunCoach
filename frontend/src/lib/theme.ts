/**
 * Theme override. "system" removes data-theme and lets prefers-color-scheme decide;
 * light/dark pin it. The choice is a per-device convenience, so localStorage is fine.
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
  if (pref !== 'system') return pref
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function applyTheme(pref: ThemePref = getThemePref()) {
  const root = document.documentElement
  if (pref === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', pref)
  // Keep the browser chrome (status bar on Android) in step with the ground colour.
  const color = effective(pref) === 'dark' ? '#0b0b0f' : '#f7f7fb'
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
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => applyTheme())
}
