/* Spec 68 (fix de placement) — Fornecedores/Clientes (/parties), grupo
 * Caixa & Cartões.
 *
 * Página REPORT-FIRST, acessível a member: quanto entrou/saiu por
 * fornecedor/cliente. Relatório alimentado pela spec 74 (top_parties);
 * até lá, empty-state explícito. Lista read-only; gestão (CRUD + merge)
 * em /admin/registry.
 */
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Settings2 } from 'lucide-react'
import { api, type PartyOut, type UserOut } from '../lib/api'
import AppLayout from '../components/AppLayout'
import { Card, PageHeader, SectionTitle, INPUT_CLS } from '../components/ui'
import { PARTY_KIND_META } from './Registry'

export default function Parties() {
  const navigate = useNavigate()
  const [me, setMe] = useState<UserOut | null>(null)
  const [parties, setParties] = useState<PartyOut[]>([])
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')

  useEffect(() => {
    api.me().then(setMe).catch(() => navigate('/login'))
  }, [navigate])

  useEffect(() => {
    if (!me) return
    setLoading(true)
    setLoadError('')
    api.listParties()
      .then(setParties)
      .catch(err => setLoadError(err instanceof Error ? err.message : 'Erro ao carregar.'))
      .finally(() => setLoading(false))
  }, [me])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return parties
    return parties.filter(p => p.name.toLowerCase().includes(q))
  }, [parties, search])

  const isAdmin = me?.role === 'admin' || me?.role === 'sysadmin'

  if (!me) return null

  return (
    <AppLayout user={me}>
      <div className="space-y-6">
        <PageHeader
          title="Fornecedores/Clientes"
          count={parties.length}
          countLabel="contrapartes de transações"
          action={isAdmin ? (
            <Link to="/admin/registry" className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors">
              <Settings2 className="w-3.5 h-3.5" /> Gerenciar
            </Link>
          ) : undefined}
        />

        <Card>
          <SectionTitle>Movimento por fornecedor/cliente</SectionTitle>
          <div className="text-[12px] text-gray-400 dark:text-gray-600 text-center py-10">
            O relatório por contraparte acende quando as Movimentações existirem
            (specs 70/71/74): quanto você gastou/recebeu de cada um nos últimos 12 meses.
          </div>
        </Card>

        <Card>
          <div className="flex items-center justify-between gap-3 mb-3">
            <SectionTitle>Contrapartes</SectionTitle>
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Buscar…"
              className={`${INPUT_CLS} max-w-[220px]`}
            />
          </div>
          {loadError ? (
            <div className="text-sm text-red-600 dark:text-red-400 text-center py-6">{loadError}</div>
          ) : loading ? (
            <div className="text-sm text-gray-400 dark:text-gray-600 text-center py-8">Carregando…</div>
          ) : filtered.length === 0 ? (
            <div className="text-[12px] text-gray-400 dark:text-gray-600 text-center py-8">
              {parties.length === 0
                ? 'Nenhum fornecedor/cliente ainda — o import de extrato (spec 71) cria automaticamente a partir das descrições.'
                : 'Nada encontrado.'}
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-1">
              {filtered.map(p => (
                <div key={p.id} className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800/40">
                  <span className="text-[13px] text-gray-900 dark:text-white flex-1 truncate">{p.name}</span>
                  <span className="text-[10px] uppercase tracking-wider text-gray-500">{PARTY_KIND_META[p.kind]}</span>
                  {p.alias_count > 0 && <span className="text-[10px] text-gray-500 tnum">{p.alias_count} alias</span>}
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </AppLayout>
  )
}
