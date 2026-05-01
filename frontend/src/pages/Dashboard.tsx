import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api'

interface Me {
  user_id: string
  workspace_id: string
  role: string
}

export default function Dashboard() {
  const navigate = useNavigate()
  const [me, setMe] = useState<Me | null>(null)

  useEffect(() => {
    api.me()
      .then(setMe)
      .catch(() => navigate('/login'))
  }, [navigate])

  function logout() {
    localStorage.removeItem('token')
    navigate('/login')
  }

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950">
      <header className="border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-6 py-4 flex items-center justify-between">
        <span className="font-semibold text-gray-900 dark:text-white">Numis-Geek</span>
        <button
          onClick={logout}
          className="text-sm text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition-colors"
        >
          Sair
        </button>
      </header>

      <main className="max-w-4xl mx-auto p-8">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">Dashboard</h2>
        {me && (
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Logado como <span className="font-medium text-gray-700 dark:text-gray-300">{me.role}</span>
          </p>
        )}
        <div className="mt-8 rounded-2xl border border-dashed border-gray-300 dark:border-gray-700 p-12 text-center text-gray-400 dark:text-gray-600 text-sm">
          Features em construção...
        </div>
      </main>
    </div>
  )
}
