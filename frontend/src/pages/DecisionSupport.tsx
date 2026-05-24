import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Compass } from 'lucide-react'
import AppLayout from '../components/AppLayout'
import { api, type UserOut } from '../lib/api'

export default function DecisionSupport() {
  const navigate = useNavigate()
  const [me, setMe] = useState<UserOut | null>(null)

  useEffect(() => {
    api.me().then(setMe).catch(() => navigate('/login'))
  }, [navigate])

  if (!me) return null

  return (
    <AppLayout user={me}>
      <div className="w-full">
        <h1 className="text-xl font-semibold text-gray-900 dark:text-white mb-6">Decision-support</h1>
        <div className="rounded-2xl border border-dashed border-indigo-300/60 dark:border-indigo-700/40 bg-indigo-50/40 dark:bg-indigo-900/10 p-12 text-center">
          <Compass className="w-7 h-7 mx-auto text-indigo-500 dark:text-indigo-400 mb-3" />
          <p className="text-sm font-medium text-gray-900 dark:text-white">
            Cockpit de decisões de investimento — em breve.
          </p>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-3 max-w-xl mx-auto leading-relaxed">
            Snowflake/radar por ativo · cash disponível · gap vs target allocation ·
            top opportunities · reserva de emergência. Chega no Spec 25 (V1 manual,
            sem integrações de dados — providers BCB/brapi/yfinance/FMP entram em V2).
          </p>
          <p className="text-[11px] text-gray-400 dark:text-gray-600 mt-4">
            Referência: <code className="font-mono">docs/decision-support-rationale.md</code>
          </p>
        </div>
      </div>
    </AppLayout>
  )
}
