const KEY = 'comfort'

export function getComfort(): boolean {
  return localStorage.getItem(KEY) === 'on'
}

export function applyComfort(on: boolean) {
  document.body.classList.toggle('comfort', on)
  localStorage.setItem(KEY, on ? 'on' : 'off')
}

export function toggleComfort(): boolean {
  const next = !getComfort()
  applyComfort(next)
  return next
}

applyComfort(getComfort())
