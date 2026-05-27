import '@testing-library/jest-dom/vitest'

// jsdom doesn't ship matchMedia; some modules call it at import time
// (e.g. lib/theme.ts applyTheme on load). Polyfill so tests that
// transitively import AppLayout don't crash.
if (!window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  })
}
