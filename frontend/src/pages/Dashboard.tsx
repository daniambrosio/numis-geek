import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type UserOut } from '../lib/api'
import AppLayout from '../components/AppLayout'

export default function Dashboard() {
  const navigate = useNavigate()
  const [user, setUser] = useState<UserOut | null>(null)

  useEffect(() => {
    api.me().then(setUser).catch(() => navigate('/login'))
  }, [navigate])

  if (!user) return null

  return (
    <AppLayout user={user}>
      <h1 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">Dashboard</h1>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-8">
        Olá, <span className="font-medium text-gray-700 dark:text-gray-300">{user.name ?? user.email}</span>
      </p>
      <div className="rounded-2xl border border-dashed border-gray-300 dark:border-gray-700 p-16 text-center text-gray-400 dark:text-gray-600 text-sm">
        Features em construção…
      </div>
    </AppLayout>
  )
}
