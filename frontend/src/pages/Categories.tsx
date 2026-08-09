/* Spec 68 (fix de placement) — Categorias (/categories), grupo Caixa & Cartões.
 *
 * Página REPORT-FIRST, acessível a member: relatório de despesa/entrada por
 * categoria. O relatório em si é alimentado pela spec 74
 * (/api/expenses/summary.by_category) — até lá, empty-state explícito.
 * A árvore de categorias aparece read-only; gestão fica em /admin/registry.
 */
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Settings2 } from 'lucide-react'
import { api, type CategoryOut, type UserOut } from '../lib/api'
import AppLayout from '../components/AppLayout'
import { Card, PageHeader, SectionTitle } from '../components/ui'
import { groupCategories, KindBadge } from './Registry'

export default function Categories() {
  const navigate = useNavigate()
  const [me, setMe] = useState<UserOut | null>(null)
  const [categories, setCategories] = useState<CategoryOut[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')

  useEffect(() => {
    api.me().then(setMe).catch(() => navigate('/login'))
  }, [navigate])

  useEffect(() => {
    if (!me) return
    setLoading(true)
    setLoadError('')
    api.listCategories()
      .then(setCategories)
      .catch(err => setLoadError(err instanceof Error ? err.message : 'Erro ao carregar.'))
      .finally(() => setLoading(false))
  }, [me])

  const grouped = useMemo(() => groupCategories(categories), [categories])
  const isAdmin = me?.role === 'admin' || me?.role === 'sysadmin'

  if (!me) return null

  return (
    <AppLayout user={me}>
      <div className="space-y-6">
        <PageHeader
          title="Categorias"
          count={categories.length}
          countLabel="categorias de despesa/renda"
          action={isAdmin ? (
            <Link to="/admin/registry" className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors">
              <Settings2 className="w-3.5 h-3.5" /> Gerenciar
            </Link>
          ) : undefined}
        />

        {/* Relatório — chega com a trilha de transações */}
        <Card>
          <SectionTitle>Despesa / entrada por categoria</SectionTitle>
          <div className="text-[12px] text-gray-400 dark:text-gray-600 text-center py-10">
            O relatório por categoria acende quando as Movimentações existirem
            (specs 70/71/74): total por mês, média 12m e participação de cada categoria.
          </div>
        </Card>

        <Card>
          <SectionTitle>Árvore de categorias</SectionTitle>
          {loadError ? (
            <div className="text-sm text-red-600 dark:text-red-400 text-center py-6">{loadError}</div>
          ) : loading ? (
            <div className="text-sm text-gray-400 dark:text-gray-600 text-center py-8">Carregando…</div>
          ) : grouped.length === 0 ? (
            <div className="text-[12px] text-gray-400 dark:text-gray-600 text-center py-8">
              Nenhuma categoria ainda — elas chegam pelo import do Notion (spec 73)
              {isAdmin && <> ou podem ser criadas em <Link to="/admin/registry" className="text-indigo-500 hover:text-indigo-400">Cadastros</Link></>}.
            </div>
          ) : (
            <div className="space-y-1">
              {grouped.map(({ root, children }) => (
                <div key={root.id}>
                  <div className="flex items-center gap-2 px-2 py-1.5 rounded-lg">
                    <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: root.color ?? '#6b7280' }} />
                    <span className="text-[13px] font-medium text-gray-900 dark:text-white flex-1">{root.name}</span>
                  </div>
                  {children.map(c => (
                    <div key={c.id} className="flex items-center gap-2 pl-8 pr-2 py-1 rounded-lg">
                      <span className="w-2 h-2 rounded-full shrink-0" style={{ background: c.color ?? '#6b7280' }} />
                      <span className="text-[12px] text-gray-700 dark:text-gray-300 flex-1">{c.name}</span>
                      {c.kind && c.kind !== 'EXPENSE' && <KindBadge kind={c.kind} />}
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </AppLayout>
  )
}
