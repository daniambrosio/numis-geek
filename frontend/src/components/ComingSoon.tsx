import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import AppLayout from './AppLayout'
import { api, type UserOut } from '../lib/api'

interface Props {
  title: string
  hint?: string
}

export default function ComingSoon({ title, hint }: Props) {
  const navigate = useNavigate()
  const [me, setMe] = useState<UserOut | null>(null)

  useEffect(() => {
    api.me().then(setMe).catch(() => navigate('/login'))
  }, [navigate])

  if (!me) return null

  return (
    <AppLayout user={me}>
      <div className="w-full">
        <h1 className="text-xl font-semibold text-gray-900 dark:text-white mb-6">{title}</h1>
        <div className="rounded-2xl border border-dashed border-gray-300 dark:border-gray-700 bg-white/40 dark:bg-gray-900/40 p-12 text-center">
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Em breve.
          </p>
          {hint && (
            <p className="text-xs text-gray-400 dark:text-gray-600 mt-2 max-w-md mx-auto">{hint}</p>
          )}
        </div>
      </div>
    </AppLayout>
  )
}
