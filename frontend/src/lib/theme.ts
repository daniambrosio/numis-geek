export type Theme = 'dark' | 'light' | 'system'

const CYCLE: Theme[] = ['dark', 'light', 'system']

function systemIsDark(): boolean {
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

export function getTheme(): Theme {
  return (localStorage.getItem('theme') as Theme) ?? 'system'
}

export function applyTheme(theme: Theme) {
  const dark = theme === 'dark' || (theme === 'system' && systemIsDark())
  document.documentElement.classList.toggle('dark', dark)
  localStorage.setItem('theme', theme)
}

export function cycleTheme(): Theme {
  const current = getTheme()
  const next = CYCLE[(CYCLE.indexOf(current) + 1) % CYCLE.length]
  applyTheme(next)
  return next
}

// Apply on load
applyTheme(getTheme())
