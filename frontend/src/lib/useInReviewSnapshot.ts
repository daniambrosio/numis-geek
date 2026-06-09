/* Spec 35 — shared hook that returns the workspace's IN_REVIEW snapshot
 * (or null). Used by the sidebar badge and Dashboard banner.
 *
 * Refresh triggers: page load + `snapshot-status-changed` window event
 * (emitted by handleConfirm/handleReopen). Without the event listener the
 * sidebar badge stayed stale until full page refresh.
 */
import { useEffect, useState } from 'react'

import { api, type SnapshotOut } from './api'

export function useInReviewSnapshot(): SnapshotOut | null {
  const [snap, setSnap] = useState<SnapshotOut | null>(null)
  useEffect(() => {
    let cancelled = false
    function refresh() {
      api.listSnapshots()
        .then(list => {
          if (cancelled) return
          const m = list.find(s => s.status === 'IN_REVIEW')
          setSnap(m ?? null)
        })
        .catch(() => { if (!cancelled) setSnap(null) })
    }
    refresh()
    window.addEventListener('snapshot-status-changed', refresh)
    return () => {
      cancelled = true
      window.removeEventListener('snapshot-status-changed', refresh)
    }
  }, [])
  return snap
}
