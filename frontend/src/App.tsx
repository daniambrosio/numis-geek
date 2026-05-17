import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Profile from './pages/Profile'
import AdminUsers from './pages/admin/Users'
import AdminAudit from './pages/admin/Audit'
import AdminAccounts from './pages/admin/Accounts'
import Assets from './pages/admin/Assets'
import Lancamentos from './pages/Lancamentos'
import SysAdminFinancialInstitutions from './pages/sysadmin/FinancialInstitutions'
import SysAdminAssets from './pages/sysadmin/Assets'
import ComingSoon from './components/ComingSoon'
import { applyTheme, getTheme } from './lib/theme'
import { getToken } from './lib/api'

// Apply saved theme before first render
applyTheme(getTheme())

function PrivateRoute({ children }: { children: React.ReactNode }) {
  return getToken() ? <>{children}</> : <Navigate to="/login" replace />
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/dashboard" element={<PrivateRoute><Dashboard /></PrivateRoute>} />
        <Route path="/profile" element={<PrivateRoute><Profile /></PrivateRoute>} />

        {/* Investimentos */}
        <Route path="/patrimonio" element={<PrivateRoute><ComingSoon title="Patrimônio" hint="Drilldowns por classe, país e custódia. Chega quando o spec de Patrimônio for implementado." /></PrivateRoute>} />
        <Route path="/assets" element={<PrivateRoute><Assets /></PrivateRoute>} />
        <Route path="/lancamentos" element={<PrivateRoute><Lancamentos /></PrivateRoute>} />
        <Route path="/proventos" element={<PrivateRoute><ComingSoon title="Proventos" hint="Dividendos, JCP, juros e aluguel. Depende da entidade Distribution (spec 08)." /></PrivateRoute>} />

        {/* Caixa & Cartões */}
        <Route path="/movimentacoes" element={<PrivateRoute><ComingSoon title="Movimentações" hint="Transações de contas e cartões. Depende da entidade Transaction (spec 11)." /></PrivateRoute>} />
        <Route path="/cartoes" element={<PrivateRoute><ComingSoon title="Cartões" hint="Cartões de crédito como entidade própria. Depende do spec 11." /></PrivateRoute>} />
        <Route path="/faturas" element={<PrivateRoute><ComingSoon title="Faturas" hint="Fechamento de cartão por período. Depende do spec 11." /></PrivateRoute>} />
        <Route path="/orcamento" element={<PrivateRoute><ComingSoon title="Orçamento" hint="Categorias × meses, com targets. Depende dos specs 11 + 12." /></PrivateRoute>} />

        {/* Estrutura */}
        <Route path="/instituicoes" element={<PrivateRoute><ComingSoon title="Instituições" hint="FI Hub com contas, cartões e ativos agregados. Depende dos specs 10 + 11." /></PrivateRoute>} />
        <Route path="/accounts" element={<PrivateRoute><AdminAccounts /></PrivateRoute>} />

        {/* Admin */}
        <Route path="/admin/users" element={<PrivateRoute><AdminUsers /></PrivateRoute>} />
        <Route path="/admin/audit" element={<PrivateRoute><AdminAudit /></PrivateRoute>} />

        {/* Sistema */}
        <Route path="/sysadmin/financial-institutions" element={<PrivateRoute><SysAdminFinancialInstitutions /></PrivateRoute>} />
        <Route path="/sysadmin/assets" element={<PrivateRoute><SysAdminAssets /></PrivateRoute>} />

        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
