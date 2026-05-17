const KEY = 'privacy'

export function getPrivacy(): boolean {
  return localStorage.getItem(KEY) === 'on'
}

export function applyPrivacy(on: boolean) {
  document.documentElement.setAttribute('data-privacy', on ? 'on' : 'off')
  localStorage.setItem(KEY, on ? 'on' : 'off')
}

export function togglePrivacy(): boolean {
  const next = !getPrivacy()
  applyPrivacy(next)
  return next
}

applyPrivacy(getPrivacy())
