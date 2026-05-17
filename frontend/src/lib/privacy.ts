const KEY = 'privacy'

export function getPrivacy(): boolean {
  return localStorage.getItem(KEY) === 'on'
}

export function applyPrivacy(on: boolean) {
  document.body.classList.toggle('privacy', on)
  localStorage.setItem(KEY, on ? 'on' : 'off')
}

export function togglePrivacy(): boolean {
  const next = !getPrivacy()
  applyPrivacy(next)
  return next
}

applyPrivacy(getPrivacy())
