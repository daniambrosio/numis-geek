import { useEffect } from 'react'

/** Close a modal/panel when the user presses Escape.
 *
 * Every modal in this app MUST close on ESC. Use this hook (or replicate
 * the same listener pattern) in every component that overlays content
 * above the page. See CLAUDE.md → "Frontend Patterns" for the rule. */
export function useEscapeKey(onEscape: () => void): void {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault()
        onEscape()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onEscape])
}
