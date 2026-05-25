/* Spec 35 — shared hook that returns the workspace's IN_REVIEW snapshot
 * (or null). Used by the sidebar badge and Dashboard banner. */
import { useEffect, useState } from 'react'

import { api, type SnapshotOut } from './api'

export function useInReviewSnapshot(): SnapshotOut | null {
  const [snap, setSnap] = useState<SnapshotOut | null>(null)
  useEffect(() => {
    let cancelled = false
    api.listSnapshots()
      .then(list => {
        if (cancelled) return
        const m = list.find(s => s.status === 'IN_REVIEW')
        setSnap(m ?? null)
      })
      .catch(() => { if (!cancelled) setSnap(null) })
    return () => { cancelled = true }
  }, [])
  return snap
}
